"""OpenAI-compatible chat client with prompt-hash cache, replay, audit log, retry and breaker."""

from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from factory.common.paths import REPO_ROOT

CACHE_DIR = REPO_ROOT / "factory" / "cache" / "llm"


class LLMError(Exception):
    """Base class for LLM failures."""


class ReplayMissError(LLMError):
    """--replay was requested but no cached response exists for this prompt hash."""


class CircuitOpenError(LLMError):
    """Too many consecutive failures; calls are refused until the cool-down ends."""


@dataclass(frozen=True)
class LLMConfig:
    base_url: str = os.environ.get("FACTORY_LLM_BASE_URL", "http://127.0.0.1:8089/v1")
    model: str = os.environ.get("FACTORY_LLM_MODEL", "qwen2.5-3b-instruct-q4_k_m")
    api_key: str = os.environ.get("FACTORY_LLM_API_KEY", "")
    temperature: float = 0.0
    max_tokens: int = 256
    timeout_s: float = 120.0
    retries: int = 3
    # Local CPU inference has no per-token price; cost is reported as local compute seconds.
    usd_per_1k_tokens: float = float(os.environ.get("FACTORY_LLM_USD_PER_1K", "0"))


@dataclass
class Breaker:
    threshold: int = 3
    cooldown_s: float = 30.0
    failures: int = 0
    opened_at: float = 0.0

    def check(self) -> None:
        if self.failures >= self.threshold and time.monotonic() - self.opened_at < self.cooldown_s:
            raise CircuitOpenError(f"{self.failures} consecutive failures")

    def record(self, ok: bool) -> None:
        if ok:
            self.failures = 0
            return
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.monotonic()


def prompt_hash(
    model: str, temperature: float, messages: list[dict[str, str]], max_tokens: int
) -> str:
    blob = json.dumps(
        {"m": model, "t": temperature, "n": max_tokens, "msgs": messages}, sort_keys=True
    )
    return hashlib.sha256(blob.encode()).hexdigest()


@dataclass
class LLMClient:
    audit_path: Path
    stage: str
    replay: bool = False
    config: LLMConfig = field(default_factory=LLMConfig)
    breaker: Breaker = field(default_factory=Breaker)
    cache_dir: Path = CACHE_DIR
    _lock: threading.Lock = field(default_factory=threading.Lock)
    stats: dict[str, float] = field(
        default_factory=lambda: {
            "calls": 0,
            "cache_hits": 0,
            "tokens": 0,
            "seconds": 0.0,
            "tokens_incl_replay": 0,
            "ms_incl_replay": 0,
        }
    )

    def chat(self, messages: list[dict[str, str]], prompt_version: str) -> str:
        h = prompt_hash(
            self.config.model, self.config.temperature, messages, self.config.max_tokens
        )
        cached = self.cache_dir / f"{h}.json"
        if cached.exists():
            rec: dict[str, Any] = json.loads(cached.read_text())
            self._audit(h, prompt_version, messages, rec, cache_hit=True)
            return str(rec["content"])
        if self.replay:
            raise ReplayMissError(h)
        rec = self._call(messages)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n")
        self._audit(h, prompt_version, messages, rec, cache_hit=False)
        return str(rec["content"])

    def _call(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else {}
        body = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "seed": 0,
        }
        last: Exception | None = None
        for attempt in range(self.config.retries + 1):
            self.breaker.check()
            t0 = time.monotonic()
            try:
                r = httpx.post(
                    f"{self.config.base_url}/chat/completions",
                    json=body,
                    headers=headers,
                    timeout=self.config.timeout_s,
                )
                r.raise_for_status()
                data = r.json()
                self.breaker.record(True)
                usage = data.get("usage", {})
                return {
                    "content": data["choices"][0]["message"]["content"],
                    "model": data.get("model", self.config.model),
                    "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                    "completion_tokens": int(usage.get("completion_tokens", 0)),
                    "seconds": round(time.monotonic() - t0, 3),
                }
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                last = exc
                self.breaker.record(False)
                time.sleep(min(8.0, 0.5 * 2**attempt) + random.uniform(0, 0.25))  # noqa: S311
        raise LLMError(f"LLM call failed after {self.config.retries + 1} attempts: {last}")

    def _audit(
        self,
        h: str,
        prompt_version: str,
        messages: list[dict[str, str]],
        rec: dict[str, Any],
        cache_hit: bool,
    ) -> None:
        tokens = int(rec.get("prompt_tokens", 0)) + int(rec.get("completion_tokens", 0))
        entry = {
            "stage": self.stage,
            "prompt_hash": h,
            "prompt_version": prompt_version,
            "model": rec.get("model", self.config.model),
            "temperature": self.config.temperature,
            "input_sha256": hashlib.sha256(json.dumps(messages).encode()).hexdigest(),
            "output": rec["content"],
            "prompt_tokens": rec.get("prompt_tokens", 0),
            "completion_tokens": rec.get("completion_tokens", 0),
            "duration_s": rec.get("seconds", 0.0),
            "cost_usd": round(tokens / 1000 * self.config.usd_per_1k_tokens, 6),
            "cache_hit": cache_hit,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        with self._lock:
            self.stats["calls"] += 1
            self.stats["tokens_incl_replay"] += tokens
            self.stats["ms_incl_replay"] += round(float(rec.get("seconds", 0.0)) * 1000)
            if cache_hit:
                self.stats["cache_hits"] += 1
            else:
                self.stats["tokens"] += tokens
                self.stats["seconds"] += float(rec.get("seconds", 0.0))
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, sort_keys=True) + "\n")

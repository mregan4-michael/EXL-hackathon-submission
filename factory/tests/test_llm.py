"""LLM client failure handling and audit accounting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from factory.common import llm


def _client(tmp_path: Path, **cfg: Any) -> llm.LLMClient:
    config = llm.LLMConfig(retries=0, **cfg)
    return llm.LLMClient(tmp_path / "audit.jsonl", "test", config=config, cache_dir=tmp_path)


def test_empty_choices_raise_llm_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    req = httpx.Request("POST", "http://x/v1/chat/completions")
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: httpx.Response(200, json={"choices": []}, request=req)
    )
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    with pytest.raises(llm.LLMError):
        _client(tmp_path).chat([{"role": "user", "content": "hi"}], "p.v1")


def test_cache_hits_cost_nothing(tmp_path: Path) -> None:
    c = _client(tmp_path, usd_per_1k_tokens=1.0)
    msgs = [{"role": "user", "content": "hi"}]
    h = llm.prompt_hash(c.config.model, c.config.temperature, msgs, c.config.max_tokens)
    rec = {"content": "ok", "prompt_tokens": 500, "completion_tokens": 500}
    (tmp_path / f"{h}.json").write_text(json.dumps(rec))
    assert c.chat(msgs, "p.v1") == "ok"
    entry = json.loads((tmp_path / "audit.jsonl").read_text().splitlines()[-1])
    assert entry["cache_hit"] is True and entry["cost_usd"] == 0.0

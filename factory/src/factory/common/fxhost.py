"""Client for tools/fxhost: Microsoft's Power Fx parser and interpreter over JSON lines."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

from factory.common.paths import FXHOST_DIR


class FxHostError(RuntimeError):
    """The fxhost process failed or returned an unparseable response."""


def _dotnet() -> str:
    found = shutil.which("dotnet")
    if found:
        return found
    home = Path.home() / ".dotnet" / "dotnet"
    if home.exists():
        return str(home)
    raise FxHostError("dotnet SDK not found; run `make setup`")


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("DOTNET_ROOT", str(Path(_dotnet()).parent))
    env["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
    env["DOTNET_NOLOGO"] = "1"
    return env


def ensure_built() -> Path:
    dll = FXHOST_DIR / "bin" / "Release" / "net8.0" / "fxhost.dll"
    if not dll.exists():
        subprocess.run(  # noqa: S603
            [_dotnet(), "build", "-c", "Release", "-v", "q", str(FXHOST_DIR)],
            check=True,
            env=_env(),
            capture_output=True,
        )
    return dll


class FxHost:
    """A long-lived fxhost process. Thread-safe; one request at a time."""

    def __init__(self) -> None:
        dll = ensure_built()
        self._proc = subprocess.Popen(  # noqa: S603
            [_dotnet(), str(dll)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            env=_env(),
            bufsize=1,
        )
        self._lock = threading.Lock()

    def _call(self, req: dict[str, Any]) -> dict[str, Any]:
        assert self._proc.stdin is not None and self._proc.stdout is not None
        with self._lock:
            self._proc.stdin.write(json.dumps(req) + "\n")
            self._proc.stdin.flush()
            line = self._proc.stdout.readline()
        if not line:
            raise FxHostError("fxhost exited")
        resp: dict[str, Any] = json.loads(line)
        return resp

    def parse(self, formula: str) -> dict[str, Any]:
        return self._call({"op": "parse", "formula": formula})

    def eval(self, formula: str, variables: dict[str, Any]) -> dict[str, Any]:
        return self._call({"op": "eval", "formula": formula, "vars": variables})

    def close(self) -> None:
        if self._proc.stdin:
            self._proc.stdin.close()
        self._proc.wait(timeout=10)

    def __enter__(self) -> FxHost:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

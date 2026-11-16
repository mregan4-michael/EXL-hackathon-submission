"""Repository-relative paths. Every artefact path is resolved from REPO_ROOT."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(os.environ.get("FACTORY_REPO_ROOT", Path(__file__).resolve().parents[4]))
LEGACY = REPO_ROOT / "legacy"
OUT = REPO_ROOT / "factory" / "out"
PROMPTS = REPO_ROOT / "prompts"
SCHEMAS = REPO_ROOT / "schemas"
FXHOST_DIR = REPO_ROOT / "tools" / "fxhost"


def rel(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()

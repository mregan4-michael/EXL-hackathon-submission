"""Locate source lines for extracted items so every rule traces to file:line."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=256)
def file_lines(path: Path) -> tuple[str, ...]:
    return tuple(path.read_text(encoding="utf-8-sig").splitlines())


def find_line(path: Path, needles: tuple[str, ...], start: int = 0) -> int:
    """1-based line of the first needle found in order (each searched after the previous)."""
    lines = file_lines(path)
    idx = start
    for needle in needles:
        for i in range(idx, len(lines)):
            if needle in lines[i]:
                idx = i
                break
        else:
            return idx + 1 if idx else 1
    return idx + 1

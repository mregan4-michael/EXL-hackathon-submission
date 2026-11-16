"""Deterministic test-input generation for one legacy formula.

Inputs come from the legacy AST only (its literals and parameter types), never from the
generated C#, so the test set cannot be tuned to the code it judges. Three kinds:
  baseline  - a typical and an all-blank screen state;
  boundary  - one parameter at a time over threshold values (literal -1, -0.01, =, +0.01, +1),
              blank, empty and non-numeric text, and day offsets that hit date-difference limits;
  random    - seeded random combinations of the same pools (property-style, reproducible).
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from factory.analyse import fxast
from factory.generate.transpile import BOOL, DATE, NUM, STR, Param

BASE_DATE = date(2024, 1, 15)
LEAP_DAY = date(2024, 2, 29)
STEP = (Decimal(-1), Decimal("-0.01"), Decimal(0), Decimal("0.01"), Decimal(1))
MAX_POOL = 24
MAX_CASES = 160


def number_literals(ast: dict[str, Any]) -> list[Decimal]:
    return sorted({Decimal(str(n["v"])) for n in fxast.walk(ast) if n["k"] in ("NumLit", "DecLit")})


def string_literals(ast: dict[str, Any]) -> list[str]:
    return sorted({str(n["v"]) for n in fxast.walk(ast) if n["k"] == "StrLit"})


def _num(d: Decimal) -> Decimal:
    return d.normalize() if d == d.to_integral_value() else d


def _numbers(lits: list[Decimal]) -> list[Decimal]:
    out: list[Decimal] = []
    for lit in lits:
        out += [_num(lit + s) for s in STEP]
    out += [Decimal(0), Decimal(1), Decimal(-1)]
    seen: list[Decimal] = []
    for d in out:
        if d not in seen:
            seen.append(d)
    return seen[:MAX_POOL]


def _dates(lits: list[Decimal]) -> list[Any]:
    days = sorted({int(x) for x in lits if x == x.to_integral_value() and 0 < abs(x) <= 3660})
    ds = [BASE_DATE]
    for k in days:
        for off in (k - 1, k, k + 1, -k):
            ds.append(BASE_DATE + timedelta(days=off))
    ds.append(LEAP_DAY)
    uniq = list(dict.fromkeys(ds))[:MAX_POOL]
    return [{"$date": d.isoformat()} for d in uniq]


def pool(p: Param, ast: dict[str, Any]) -> list[Any]:
    nums = _numbers(number_literals(ast))
    if p.type == NUM:
        return [*nums, None]
    if p.type == BOOL:
        return [False, True, None]
    if p.type == DATE:
        return [*_dates(number_literals(ast)), None]
    if p.type == STR:
        texts = [format(d, "f") for d in nums] + string_literals(ast)
        return [*dict.fromkeys([*texts, "", "abc"]), None][: MAX_POOL + 4]
    return [None]


def _typical(p: Param, values: list[Any]) -> Any:
    if p.type == BOOL:
        return False
    if p.type == DATE:
        return {"$date": BASE_DATE.isoformat()}
    return next((v for v in values if v not in (None, "")), None)


def dumps(v: Any) -> str:
    return json.dumps(v, sort_keys=True, default=_default)


def _default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(type(o).__name__)


def generate(key: str, params: list[Param], ast: dict[str, Any]) -> list[dict[str, Any]]:
    """Return [{kind, inputs}] for one formula; deterministic in (key, AST)."""
    if not params:
        return [{"kind": "baseline", "inputs": {}}]
    pools = {p.ref: pool(p, ast) for p in params}
    typical = {p.ref: _typical(p, pools[p.ref]) for p in params}
    raw: list[tuple[str, dict[str, Any]]] = [
        ("baseline", typical),
        ("baseline", {p.ref: None for p in params}),
    ]
    for p in params:
        for v in pools[p.ref]:
            raw.append(("boundary", {**typical, p.ref: v}))
    rng = random.Random(hashlib.sha256(key.encode()).hexdigest())  # noqa: S311 (test data)
    for _ in range(min(48, 12 * len(params))):
        raw.append(("random", {p.ref: rng.choice(pools[p.ref]) for p in params}))
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for kind, inputs in raw:
        k = dumps(inputs)
        if k not in seen:
            seen.add(k)
            out.append({"kind": kind, "inputs": inputs})
    return out[:MAX_CASES]

"""Deterministic Power Fx AST -> C# expression compiler (ADR-008).

The LLM never writes rule code. Each executed-oracle rule is compiled from the
Microsoft Power Fx AST into a pure static C# method over the `Fx` runtime, which
re-implements the Power Fx semantics used by the legacy formula (blank coercion,
case-insensitive text functions, half-away-from-zero rounding). Constructs that
the compiler does not support raise `UnsupportedError`; the rule is then routed
to scenario evidence rather than given hand-written code.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from factory.analyse import fxast

NUM, STR, BOOL, DATE, BLANK = "num", "str", "bool", "date", "blank"
CS_TYPE = {NUM: "decimal?", STR: "string?", BOOL: "bool?", DATE: "DateTime?", BLANK: "object?"}
ENUMS = {"DisplayMode", "TimeUnit"}
CMP = {
    "Greater": "Gt",
    "GreaterEqual": "Ge",
    "Less": "Lt",
    "LessEqual": "Le",
    "Equal": "Eq",
    "NotEqual": "Ne",
}
ARITH = {"Add": "Add", "Mul": "Mul", "Div": "Div"}


class UnsupportedError(Exception):
    """The formula uses a construct the compiler does not translate."""


@dataclass
class Param:
    ref: str
    name: str
    type: str


@dataclass
class Compiled:
    expr: str
    type: str
    params: list[Param] = field(default_factory=list)


def param_name(ref: str) -> str:
    return re.sub(r"\W", "_", ref.replace("()", ""))


def ref_type(ref: str, bool_context: bool) -> str:
    """Type of a legacy reference, from Power Apps control-property conventions."""
    last = ref.rsplit(".", 1)[-1]
    if last in {"SelectedDate", "DefaultDate"}:
        return DATE
    if last in {"Visible", "Checked"} or (last == "Value" and ref.startswith(("chk", "tgl"))):
        return BOOL
    if last in {"Text"} or ref.endswith(".Selected.Value") or ref.startswith("User()."):
        return STR
    if "." not in ref:
        return BOOL if bool_context else NUM
    return STR


def _lit(s: str) -> str:
    return json.dumps(s)


class _Compiler:
    def __init__(self) -> None:
        self.params: dict[str, Param] = {}

    def ref(self, ref: str, bool_context: bool) -> tuple[str, str]:
        head = ref.split(".", 1)[0]
        if head in ENUMS:
            if head == "TimeUnit":
                return f"Fx.TimeUnit.{ref.split('.', 1)[1]}", "unit"
            return _lit(ref.split(".", 1)[1]), STR
        p = self.params.get(ref)
        if p is None:
            p = Param(ref, param_name(ref), ref_type(ref, bool_context))
            self.params[ref] = p
        return p.name, p.type

    def cond(self, n: dict[str, Any]) -> str:
        e, t = self.expr(n, bool_context=True)
        if t not in (BOOL, BLANK):
            raise UnsupportedError(f"non-boolean condition of type {t}")
        return f"Fx.B({e})"

    def expr(self, n: dict[str, Any], bool_context: bool = False) -> tuple[str, str]:
        k = n["k"]
        if k in {"DecLit", "NumLit"}:
            return f"(decimal?){n['v']}m", NUM
        if k == "StrLit":
            return f"(string?){_lit(n['v'])}", STR
        if k == "BoolLit":
            return f"(bool?){str(n['v']).lower()}", BOOL
        if k == "DottedName" and n["l"]["k"] == "Call" and n["l"]["fn"] == "User":
            return self.ref(f"User().{n['name']}", bool_context)
        if k in {"FirstName", "DottedName"}:
            d = fxast.dotted(n)
            if d is None:
                raise UnsupportedError("non-dotted name")
            return self.ref(d, bool_context)
        if k == "UnaryOp":
            if n["op"] == "Not":
                return f"(bool?)!{self.cond(n['x'])}", BOOL
            if n["op"] == "Minus":
                return f"Fx.Neg({self.num(n['x'])})", NUM
            raise UnsupportedError(f"unary {n['op']}")
        if k == "BinaryOp":
            return self.binary(n)
        if k == "Call":
            return self.call(n)
        raise UnsupportedError(f"node {k}")

    def num(self, n: dict[str, Any]) -> str:
        e, t = self.expr(n)
        if t == NUM:
            return e
        if t == STR:
            return f"Fx.Value({e})"
        if t == BOOL:
            return f"Fx.ToNum({e})"
        raise UnsupportedError(f"numeric coercion from {t}")

    def binary(self, n: dict[str, Any]) -> tuple[str, str]:
        op = n["op"]
        if op in {"And", "Or"}:
            j = " && " if op == "And" else " || "
            return f"(bool?)({self.cond(n['l'])}{j}{self.cond(n['r'])})", BOOL
        if op in ARITH:
            return f"Fx.{ARITH[op]}({self.num(n['l'])}, {self.num(n['r'])})", NUM
        if op == "Concat":
            return f"Fx.Concat({self.text(n['l'])}, {self.text(n['r'])})", STR
        if op in CMP:
            (le, lt), (re_, rt) = self.expr(n["l"]), self.expr(n["r"])
            if op in {"Equal", "NotEqual"} and lt == rt and lt in {STR, BOOL, NUM, DATE}:
                return f"Fx.{CMP[op]}({le}, {re_})", BOOL
            if DATE in (lt, rt):
                return f"Fx.{CMP[op]}({le}, {re_})", BOOL
            if STR in (lt, rt) and op in {"Equal", "NotEqual"}:
                return f"Fx.{CMP[op]}({self.text(n['l'])}, {self.text(n['r'])})", BOOL
            return f"Fx.{CMP[op]}({self.num(n['l'])}, {self.num(n['r'])})", BOOL
        raise UnsupportedError(f"binary {op}")

    def text(self, n: dict[str, Any]) -> str:
        e, t = self.expr(n)
        if t == STR:
            return e
        if t in (NUM, BOOL, DATE):
            return f"Fx.Text({e})"
        raise UnsupportedError(f"text coercion from {t}")

    def branches(
        self, pairs: list[tuple[str, dict[str, Any]]], default: dict[str, Any] | None
    ) -> tuple[str, str]:
        vals = [self.expr(v) for _, v in pairs]
        dflt = self.expr(default) if default is not None else None
        types = {t for _, t in vals} | ({dflt[1]} if dflt else set())
        types.discard(BLANK)
        if len(types) > 1:
            raise UnsupportedError(f"mixed branch types {sorted(types)}")
        t = types.pop() if types else BLANK
        cs = CS_TYPE[t]
        out = f"({cs})({dflt[0]})" if dflt else f"({cs})null"
        for (c, _), (v, _) in reversed(list(zip(pairs, vals, strict=True))):
            out = f"({c} ? ({cs})({v}) : {out})"
        return out, t

    def call(self, n: dict[str, Any]) -> tuple[str, str]:
        fn, a = n["fn"], n["args"]
        if fn == "If":
            pairs = [(self.cond(a[i]), a[i + 1]) for i in range(0, len(a) - 1, 2)]
            return self.branches(pairs, a[-1] if len(a) % 2 else None)
        if fn == "Switch":
            subj, rest = a[0], a[1:]
            pairs = []
            for i in range(0, len(rest) - 1, 2):
                eq, _ = self.binary({"k": "BinaryOp", "op": "Equal", "l": subj, "r": rest[i]})
                pairs.append((f"Fx.B({eq})", rest[i + 1]))
            return self.branches(pairs, rest[-1] if len(rest) % 2 else None)
        if fn == "Value":
            return self.num(a[0]), NUM
        if fn == "IsBlank":
            return f"(bool?)Fx.IsBlank({self.expr(a[0])[0]})", BOOL
        if fn == "Len":
            return f"Fx.Len({self.text(a[0])})", NUM
        if fn in {"StartsWith", "EndsWith"}:
            return f"Fx.{fn}({self.text(a[0])}, {self.text(a[1])})", BOOL
        if fn == "IsMatch":
            if len(a) != 2 or a[1]["k"] != "StrLit":
                raise UnsupportedError("IsMatch needs a literal pattern and no options")
            return f"Fx.IsMatch({self.text(a[0])}, {_lit(a[1]['v'])})", BOOL
        if fn in {"Round", "RoundUp", "RoundDown"}:
            return f"Fx.{fn}({self.num(a[0])}, {self.num(a[1])})", NUM
        if fn in {"Max", "Min", "Sum"} and all(x["k"] != "Table" for x in a):
            return f"Fx.{fn}({', '.join(self.num(x) for x in a)})", NUM
        if fn == "Abs":
            return f"Fx.Abs({self.num(a[0])})", NUM
        if fn == "DateDiff":
            unit = self.expr(a[2])[0] if len(a) > 2 else "Fx.TimeUnit.Days"
            return f"Fx.DateDiff({self.date(a[0])}, {self.date(a[1])}, {unit})", NUM
        if fn == "DateAdd":
            unit = self.expr(a[2])[0] if len(a) > 2 else "Fx.TimeUnit.Days"
            return f"Fx.DateAdd({self.date(a[0])}, {self.num(a[1])}, {unit})", DATE
        if fn in {"Lower", "Upper", "Trim"}:
            return f"Fx.{fn}({self.text(a[0])})", STR
        if fn in {"And", "Or"}:
            j = " && " if fn == "And" else " || "
            return f"(bool?)({j.join(self.cond(x) for x in a)})", BOOL
        if fn == "Not":
            return f"(bool?)!{self.cond(a[0])}", BOOL
        raise UnsupportedError(f"function {fn}")

    def date(self, n: dict[str, Any]) -> str:
        e, t = self.expr(n)
        if t != DATE:
            raise UnsupportedError(f"date coercion from {t}")
        return e


def compile_formula(ast: dict[str, Any]) -> Compiled:
    c = _Compiler()
    expr, t = c.expr(ast)
    return Compiled(expr, t, sorted(c.params.values(), key=lambda p: p.ref))


def string_options(ast: dict[str, Any]) -> list[str] | None:
    """`["A", "B"]` (a single-column table of text literals) -> ["A", "B"], else None."""
    if ast.get("k") != "Table":
        return None
    out = []
    for item in ast.get("args", []):
        if item.get("k") != "StrLit":
            return None
        out.append(str(item["v"]))
    return out

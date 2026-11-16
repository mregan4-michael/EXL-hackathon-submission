"""Queries over the Power Fx AST JSON emitted by tools/fxhost."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

Ast = dict[str, Any]


def walk(node: Ast) -> Iterator[Ast]:
    yield node
    for key in ("l", "r", "x"):
        child = node.get(key)
        if isinstance(child, dict):
            yield from walk(child)
    for child in node.get("args", []):
        yield from walk(child)
    for child in node.get("fields", {}).values():
        yield from walk(child)


def functions(node: Ast) -> set[str]:
    return {n["fn"] for n in walk(node) if n["k"] == "Call"}


def dotted(node: Ast) -> str | None:
    if node["k"] == "FirstName":
        return str(node["name"])
    if node["k"] == "DottedName":
        left = dotted(node["l"])
        return f"{left}.{node['name']}" if left else None
    if node["k"] == "Self":
        return "Self"
    if node["k"] == "Parent":
        return "Parent"
    return None


def references(node: Ast) -> set[str]:
    """Outermost dotted references (e.g. `txtAmount.Text`, `gblUser.Email`)."""
    out: set[str] = set()

    def visit(n: Ast) -> None:
        name = dotted(n)
        if name is not None:
            out.add(name)
            return
        for key in ("l", "r", "x"):
            if isinstance(n.get(key), dict):
                visit(n[key])
        for c in n.get("args", []):
            visit(c)
        for c in n.get("fields", {}).values():
            visit(c)

    visit(node)
    return out


def numbers(node: Ast) -> list[float]:
    return [float(n["v"]) for n in walk(node) if n["k"] in ("NumLit", "DecLit")]


def has_branching(node: Ast) -> bool:
    fns = functions(node)
    ops = {n.get("op") for n in walk(node) if n["k"] == "BinaryOp"}
    comparisons = {
        "Equal",
        "NotEqual",
        "Less",
        "LessEqual",
        "Greater",
        "GreaterEqual",
        "In",
        "Exactin",
    }
    return bool(
        fns & {"If", "Switch", "IfError", "Filter", "LookUp", "CountIf", "IsBlank", "Not"}
    ) or bool(ops & comparisons)

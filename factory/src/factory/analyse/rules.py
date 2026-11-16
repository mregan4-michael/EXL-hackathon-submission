"""Deterministic rule facts: candidate selection, inputs/outputs, flags, PII, oracle type.

Nothing here calls a model. The LLM only writes the plain-English statement, the
category and a confidence (catalogue.py). Flags are never taken from model output,
so injected text in legacy source cannot change them.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from factory.analyse import fxast
from factory.analyse.canvas import is_style_property


@dataclass(frozen=True)
class Policy:
    """Deterministic candidate/flag policy. Versions are immutable; new behaviour = new version."""

    version: str
    fairness_words: bool  # v2: match whole identifier words, so "Message" no longer hits "age"
    consistency_check: bool  # v3: statement must repeat every threshold number and strictness


POLICIES = {
    p.version: p
    for p in (
        Policy("candidates.v1", fairness_words=False, consistency_check=False),
        Policy("candidates.v2", fairness_words=True, consistency_check=False),
        Policy("candidates.v3", fairness_words=True, consistency_check=True),
    )
}
POLICY_VERSION = "candidates.v1"

PURE_FX = {
    "If", "Switch", "Value", "Round", "RoundUp", "RoundDown", "Max", "Min", "Abs", "DateDiff",
    "DateAdd", "IsBlank", "Len", "StartsWith", "EndsWith", "IsMatch", "Text", "And", "Or", "Not",
    "Lower", "Upper", "Trim", "Mod", "Sum", "Coalesce", "Left", "Right", "Mid", "Concatenate",
}  # fmt: skip
SIDE_EFFECT_FX = {"Patch", "Set", "Navigate", "Notify", "Collect", "ClearCollect", "Remove", "Back"}
NUMBER = re.compile(r"(?<![\w.+-])-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?(?![\w.])")
ASSIGN_FX = {"Set", "Collect", "ClearCollect"}
INJECTION = re.compile(
    r"ignore (all )?(previous|prior|above) instructions|\bAI (reviewer|assistant|model)\b|"
    r"system prompt|you are (now )?(an?|the) |classify this rule|no human review",
    re.IGNORECASE,
)
_PII = [
    (r"vulnerab|health|disab", "special_category"),
    (r"sortcode|accountnumber|iban|amount|limit|redress|settlement|excess", "financial"),
    (r"e?mail|upn|userprincipalname|phone|address", "contact"),
    (r"dateofbirth|\bdob\b|fullname|displayname|\bname\b|powerofattorney", "personal"),
    (r"policynumber|claimid|customerid|approverid", "identifier"),
]
PII_LEXICON = [(re.compile(p, re.I), c) for p, c in _PII]
FAIRNESS = re.compile(r"vulnerab|fraud|dateofbirth|age\b|years|nationality|postcode|gender", re.I)
FAIRNESS_STEMS = ("vulnerab", "fraud", "dateofbirth", "birthdate", "nationality", "postcode")
FAIRNESS_WORDS = {"age", "ages", "aged", "years", "gender", "sex", "dob", "ethnicity", "religion"}
_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


def words(text: str) -> list[str]:
    """Identifier words: 'cat_ClaimantAge/Message' -> ['cat', 'claimant', 'age', 'message']."""
    return [w.lower() for w in _WORD.findall(text)]


def fairness_sensitive(text: str, policy: Policy) -> bool:
    if not policy.fairness_words:
        return bool(FAIRNESS.search(text))
    low = text.lower()
    return any(st in low for st in FAIRNESS_STEMS) or bool(FAIRNESS_WORDS & set(words(text)))


_INCLUSIVE = re.compile(r"or equal|at least|or more|or above|minimum|no less|or over", re.I)
_EXCLUSIVE_BELOW = re.compile(r"or less|or below|at most|maximum|no more|or under", re.I)


def _number_forms(v: float) -> set[str]:
    if v == int(v):
        i = int(v)
        return {str(i), f"{i:,}", f"{v:.1f}", f"{v:.2f}"}
    return {repr(v), f"{v:.2f}", f"{v:,.2f}"}


def inconsistencies(statement: str, atoms: list[tuple[str, str, float]]) -> list[str]:
    """Threshold facts the plain-English statement fails to repeat (number or strictness)."""
    out = []
    for subj, op, v in atoms:
        if not any(
            re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", statement) for n in _number_forms(v)
        ):
            out.append(f"{subj} {op} {v:g}: threshold missing from statement")
        elif op in (">", "<") and (_INCLUSIVE if op == ">" else _EXCLUSIVE_BELOW).search(statement):
            out.append(f"{subj} {op} {v:g}: statement describes an inclusive bound")
        elif op in (">=", "<=") and not (_INCLUSIVE if op == ">=" else _EXCLUSIVE_BELOW).search(
            statement
        ):
            out.append(f"{subj} {op} {v:g}: statement does not say the bound is inclusive")
    return out


NOT_MAGIC = {0.0, 1.0, -1.0}
WDL_REF = re.compile(
    r"(?:body/|\[')([A-Za-z_][\w/]*)|(?:outputs|variables|parameters|body)\('([^']+)'\)"
)


@dataclass
class Facts:
    candidate_id: str
    site: dict[str, Any]
    inputs: list[str]
    outputs: list[str]
    magic_numbers: list[float]
    pii: list[dict[str, str]]
    fairness: bool
    dead_code: bool
    injection_suspected: bool
    oracle: dict[str, str]
    contradiction_with: list[str] = field(default_factory=list)  # candidate ids
    review_reasons: list[str] = field(default_factory=list)
    atoms: list[tuple[str, str, float]] = field(default_factory=list)


def candidate_id(site: dict[str, Any]) -> str:
    return hashlib.sha256(f"{site['file']}#{site['path']}".encode()).hexdigest()[:12]


def select_candidates(sites: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for s in sites:
        k = s["kind"]
        if k == "canvas_property":
            if s["ast"] is None or is_style_property(s["prop"]):
                continue
            if not fxast.has_branching(s["ast"]):
                continue
        elif k == "table_column" and "Range(" not in s["formula"]:
            continue
        out.append(s)
    return out


def _flow_refs(formula: str) -> list[str]:
    refs = {a or b for a, b in WDL_REF.findall(formula)}
    return sorted(r for r in refs if r)


def _wdl_numbers(formula: str) -> list[float]:
    try:
        obj: Any = json.loads(formula)
    except ValueError:
        return []
    found: list[float] = []

    def visit(o: Any) -> None:
        if isinstance(o, bool):
            return
        if isinstance(o, int | float):
            found.append(float(o))
        elif isinstance(o, dict):
            for v in o.values():
                visit(v)
        elif isinstance(o, list):
            for v in o:
                visit(v)

    visit(obj)
    return found


def _is_magic(n: float) -> bool:
    # Option-set codes (809060000) and Int32.MaxValue bounds are platform values, not magic.
    return n not in NOT_MAGIC and abs(n) < 1e8


def _subject(ref: str) -> str:
    leaf = ref.replace("']", "").split("/")[-1].split(".")[0]
    leaf = re.sub(r"^(txt|lbl|dp|dd|chk|cbo|btn|clm_|cat_|var|gbl)", "", leaf, flags=re.I)
    return leaf.lower()


def _canvas_atoms(ast: dict[str, Any]) -> list[tuple[str, str, float]]:
    ops = {"Greater": ">", "GreaterEqual": ">=", "Less": "<", "LessEqual": "<="}
    atoms = []
    for n in fxast.walk(ast):
        if n["k"] != "BinaryOp" or n.get("op") not in ops:
            continue
        left, right = n.get("l", {}), n.get("r", {})
        if right.get("k") in ("DecLit", "NumLit"):
            refs = sorted(fxast.references(left))
            if refs:
                atoms.append((_subject(refs[0]), ops[n["op"]], float(right["v"])))
    return atoms


def _wdl_atoms(formula: str) -> list[tuple[str, str, float]]:
    ops = {"greater": ">", "greaterOrEquals": ">=", "less": "<", "lessOrEquals": "<="}
    try:
        obj: Any = json.loads(formula)
    except ValueError:
        return []
    atoms = []

    def visit(o: Any) -> None:
        if isinstance(o, dict):
            for key, val in o.items():
                if key in ops and isinstance(val, list) and len(val) == 2:
                    ref, num = val
                    if isinstance(num, int | float) and isinstance(ref, str):
                        refs = _flow_refs(ref)
                        if refs:
                            atoms.append((_subject(refs[-1]), ops[key], float(num)))
                visit(val)
        elif isinstance(o, list):
            for v in o:
                visit(v)

    visit(obj)
    return atoms


def _constant_condition(formula: str) -> bool:
    try:
        obj: Any = json.loads(formula)
    except ValueError:
        return False
    if isinstance(obj, dict) and set(obj) == {"equals"}:
        a, b = obj["equals"]
        return bool(a == b)
    return False


def _assigned(ast: dict[str, Any]) -> set[str]:
    """Variables/collections written by Set, Collect or ClearCollect (first argument)."""
    out: set[str] = set()
    for n in fxast.walk(ast):
        if n["k"] == "Call" and n["fn"] in ASSIGN_FX and n["args"]:
            name = fxast.dotted(n["args"][0])
            if name:
                out.add(name)
    return out


def _reads(ast: dict[str, Any]) -> set[str]:
    """References read by the formula: every reference except the assignment target
    position of Set/Collect/ClearCollect, so `Set(x, x + 1)` still reads `x`."""
    out: set[str] = set()

    def visit(n: dict[str, Any]) -> None:
        name = fxast.dotted(n)
        if name is not None:
            out.add(name)
            return
        for key in ("l", "r", "x"):
            if isinstance(n.get(key), dict):
                visit(n[key])
        args = n.get("args", [])
        skip_first = n["k"] == "Call" and n.get("fn") in ASSIGN_FX
        for i, c in enumerate(args):
            if not (skip_first and i == 0):
                visit(c)
        for c in n.get("fields", {}).values():
            visit(c)

    visit(ast)
    return out


def facts_for(
    site: dict[str, Any], dead_controls: set[str], policy: Policy = POLICIES[POLICY_VERSION]
) -> Facts:
    k, formula = site["kind"], site["formula"]
    inputs: list[str]
    outputs: list[str]
    numbers: list[float]
    atoms: list[tuple[str, str, float]] = []
    dead = False
    review: list[str] = []
    if site["language"] == "powerfx" and site.get("ast"):
        ast = site["ast"]
        assigned = _assigned(ast)
        inputs = sorted(r for r in _reads(ast) if not r.startswith("Self"))
        outputs = [f"{site['control'] or 'App'}.{site['prop']}", *sorted(assigned)]
        numbers = fxast.numbers(ast)
        atoms = _canvas_atoms(ast)
        dead = site["control"] in dead_controls and site["prop"] != "Visible"
        fns = fxast.functions(ast)
        selfref = any(r.startswith("Self") for r in fxast.references(ast))
        if fns <= PURE_FX and not selfref:
            oracle = {
                "proof_type": "executed_oracle",
                "reason": "Pure Power Fx expression; evaluated by Microsoft.PowerFx.Interpreter.",
            }
        elif fns & SIDE_EFFECT_FX:
            side = sorted(fns & SIDE_EFFECT_FX)
            oracle = {
                "proof_type": "scenario",
                "reason": f"Side effects ({', '.join(side)}) cannot be executed offline; "
                "proved by a named API scenario.",
            }
        else:
            impure = sorted(fns - PURE_FX) or ["Self"]
            oracle = {
                "proof_type": "unproven",
                "reason": f"Depends on {', '.join(impure)} (connector, data source or control "
                "scope) which the offline interpreter cannot supply.",
            }
    else:
        if k in ("flow_action", "flow_trigger"):
            inputs = _flow_refs(formula)
            outputs = [site["path"].split("/")[-1]]
            numbers = _wdl_numbers(formula)
            atoms = _wdl_atoms(formula)
            if _constant_condition(formula):
                review.append("constant_condition: always true, else branch unreachable")
            reason = "Power Automate flow logic; no executable oracle. Proved by a scenario test."
        else:
            inputs = [site["path"]]
            outputs = [site["path"]]
            numbers = [
                float(x)
                for x in re.findall(
                    r"(?<![\w.+-])-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?(?![\w.])", formula
                )
            ]
            reason = "Platform-enforced Dataverse metadata; proved by an API validation scenario."
        oracle = {"proof_type": "scenario", "reason": reason}
    text = " ".join(inputs + outputs + [site["path"]])
    pii = []
    for f in sorted(set(inputs + outputs)):
        for pat, cls in PII_LEXICON:
            if pat.search(f):
                pii.append({"field": f, "classification": cls})
                break
    magic = list(dict.fromkeys(n for n in numbers if _is_magic(n)))
    return Facts(
        candidate_id=candidate_id(site),
        site=site,
        inputs=inputs,
        outputs=outputs,
        magic_numbers=magic,
        pii=pii,
        fairness=fairness_sensitive(text, policy),
        dead_code=dead,
        injection_suspected=bool(INJECTION.search(formula + "\n" + site.get("description", ""))),
        oracle=oracle,
        atoms=atoms,
        review_reasons=review,
    )


def dead_controls(sites: list[dict[str, Any]]) -> set[str]:
    return {
        s["control"]
        for s in sites
        if s["kind"] == "canvas_property"
        and s["prop"] == "Visible"
        and s["formula"].strip().lstrip("=").strip().lower() == "false"
    }


def _related(a: str, b: str) -> bool:
    return len(a) >= 4 and len(b) >= 4 and (a in b or b in a)


def link_contradictions(all_facts: list[Facts]) -> None:
    """Same subject and same threshold but different boundary inclusivity (> vs >=)."""
    flip = {">": ">=", ">=": ">", "<": "<=", "<=": "<"}
    for i, a in enumerate(all_facts):
        for b in all_facts[i + 1 :]:
            if a.site["file"] == b.site["file"] and a.site["kind"] == b.site["kind"]:
                continue
            for sa, oa, na in a.atoms:
                for sb, ob, nb in b.atoms:
                    if na == nb and flip[oa] == ob and _related(sa, sb):
                        if b.candidate_id not in a.contradiction_with:
                            a.contradiction_with.append(b.candidate_id)
                            b.contradiction_with.append(a.candidate_id)

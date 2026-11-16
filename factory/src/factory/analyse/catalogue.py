"""Build a schema-valid rule catalogue from a parsed LegacyModel.

Deterministic facts come from rules.py. The model only adds the statement, category,
confidence and an is_business_rule vote. Legacy text goes inside a delimited,
explicitly untrusted block.
"""

from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import jsonschema

from factory.analyse import rules
from factory.common.llm import LLMClient, LLMError
from factory.common.paths import OUT, PROMPTS, SCHEMAS

CATEGORIES = {
    "validation", "calculation", "authorisation", "routing", "visibility", "state_transition",
    "deadline", "notification", "data_integrity", "other",
}  # fmt: skip
LANG = {"powerfx": "powerfx", "wdl": "wdl", "dataverse": "dataverse_metadata"}
MAX_SOURCE_CHARS = 3000
REVIEW_CONFIDENCE = 0.7


def load_prompt(version: str) -> str:
    return (PROMPTS / "analyse" / f"{version}.md").read_text(encoding="utf-8")


def verify_schema_lock() -> dict[str, Any]:
    raw = (SCHEMAS / "rule-catalogue.schema.json").read_bytes()
    want = (SCHEMAS / "SCHEMA.lock").read_text().split()[0]
    got = hashlib.sha256(raw).hexdigest()
    if got != want:
        raise SystemExit(f"rule-catalogue schema changed: {got} != SCHEMA.lock {want}")
    schema: dict[str, Any] = json.loads(raw)
    return schema


def build_messages(system: str, f: rules.Facts) -> list[dict[str, str]]:
    s = f.site
    src = s["formula"][:MAX_SOURCE_CHARS].replace("</legacy_source", "<\\/legacy_source")
    facts = {
        "location": {"file": s["file"], "path": s["path"], "kind": s["kind"]},
        "language": s["language"],
        "inputs": f.inputs[:20],
        "outputs": f.outputs,
    }
    desc = s.get("description", "")[:MAX_SOURCE_CHARS].replace(
        "</legacy_source", "<\\/legacy_source"
    )
    if desc:
        src = f"// description: {desc}\n{src}"
    user = (
        f"Deterministic facts (trusted):\n{json.dumps(facts, indent=1)}\n\n"
        f'<legacy_source id="{f.candidate_id}">\n{src}\n</legacy_source id="{f.candidate_id}">\n\n'
        "Reply with the JSON object only."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_reply(text: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    statement = obj.get("statement")
    if not isinstance(statement, str) or len(statement.strip()) < 10:
        return None
    category = obj.get("category") if obj.get("category") in CATEGORIES else "other"
    try:
        confidence = min(1.0, max(0.0, float(obj.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "statement": statement.strip(),
        "category": category,
        "confidence": confidence,
        "is_business_rule": obj.get("is_business_rule") is not False,
    }


def interpret(llm: LLMClient, system: str, version: str, f: rules.Facts) -> dict[str, Any]:
    try:
        reply = parse_reply(llm.chat(build_messages(system, f), version))
    except LLMError as exc:
        return {"error": f"interpretation_failed: {type(exc).__name__}"}
    return reply if reply is not None else {"error": "interpretation_failed: unparseable reply"}


def _rule(rid: str, f: rules.Facts, interp: dict[str, Any]) -> dict[str, Any]:
    s = f.site
    reasons = list(f.review_reasons)
    if "error" in interp:
        statement = (
            f"UNINTERPRETED: {', '.join(f.outputs)} is set by the legacy logic at {s['path']}."
        )
        category, confidence = "other", 0.0
        reasons.append(interp["error"])
    else:
        statement, category, confidence = (
            interp["statement"],
            interp["category"],
            interp["confidence"],
        )
    if f.injection_suspected:
        confidence = min(confidence, 0.5)
        reasons.append("prompt_injection_suspected: legacy source contains text addressed to an AI")
    if confidence < REVIEW_CONFIDENCE:
        reasons.append(f"low_confidence<{REVIEW_CONFIDENCE}")
    if f.contradiction_with:
        reasons.append("contradiction")
    if f.dead_code:
        reasons.append("dead_code")
    if f.fairness:
        reasons.append("fairness_review: fraud/vulnerability/age-related decision")
    if f.oracle["proof_type"] == "unproven":
        reasons.append("no_executable_oracle")
    return {
        "id": rid,
        "candidate_id": f.candidate_id,
        "statement": statement,
        "category": category,
        "formula": s["formula"],
        "formula_language": LANG.get(s["language"], s["language"]),
        "source_locations": [
            {"file": s["file"], "kind": s["kind"], "path": s["path"], "line": max(1, s["line"])}
        ],
        "inputs": f.inputs,
        "outputs": f.outputs,
        "confidence": round(confidence, 3),
        "pii": f.pii,
        "flags": {
            "contradiction_with": [],
            "dead_code": f.dead_code,
            "magic_numbers": f.magic_numbers,
            "fairness_review": f.fairness,
            "needs_human_review": bool(reasons),
            "review_reasons": reasons,
        },
        "oracle": f.oracle,
    }


def _graph(app_id: str, kept: list[tuple[dict[str, Any], rules.Facts]]) -> dict[str, Any]:
    nodes: dict[str, str] = {app_id: "app"}
    edges: set[tuple[str, str, str]] = set()
    produced = {o.split(".")[0]: r["id"] for r, f in kept for o in f.outputs}
    for r, f in kept:
        s = f.site
        nodes[r["id"]] = "rule"
        if s["kind"] in ("flow_action", "flow_trigger"):
            owner, kind = f"flow:{s['path'].split('/')[0]}", "flow"
        elif s["kind"] in ("table_column", "calculated_column"):
            owner, kind = f"table:{s['path'].split('.')[0]}", "table"
        else:
            owner, kind = f"screen:{s.get('screen') or 'App'}", "screen"
        nodes[owner] = kind
        edges.add((app_id, owner, "contains"))
        edges.add((owner, r["id"], "defines"))
        for inp in f.inputs:
            src = produced.get(inp.split(".")[0])
            if src and src != r["id"]:
                edges.add((src, r["id"], "reads"))
    return {
        "nodes": [{"id": k, "kind": v} for k, v in sorted(nodes.items())],
        "edges": [{"from": a, "to": b, "kind": k} for a, b, k in sorted(edges)],
    }


def build_catalogue(
    model: dict[str, Any], llm: LLMClient, prompt_version: str, workers: int = 4
) -> tuple[dict[str, Any], dict[str, Any]]:
    schema = verify_schema_lock()
    system = load_prompt(prompt_version)
    sites = rules.select_candidates(model["sites"])
    dead = rules.dead_controls(model["sites"])
    all_facts = [rules.facts_for(s, dead) for s in sites]
    rules.link_contradictions(all_facts)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        interps = list(pool.map(lambda f: interpret(llm, system, prompt_version, f), all_facts))
    order = sorted(
        range(len(all_facts)),
        key=lambda i: (
            all_facts[i].site["file"],
            all_facts[i].site["line"],
            all_facts[i].site["path"],
        ),
    )
    kept: list[tuple[dict[str, Any], rules.Facts]] = []
    rejected = []
    for i in order:
        f, interp = all_facts[i], interps[i]
        if interp.get("is_business_rule") is False and not f.injection_suspected:
            rejected.append({"candidate_id": f.candidate_id, "path": f.site["path"]})
            continue
        kept.append((_rule(f"BR-{len(kept) + 1:03d}", f, interp), f))
    by_cid = {f.candidate_id: r["id"] for r, f in kept}
    for r, f in kept:
        r["flags"]["contradiction_with"] = sorted(
            by_cid[c] for c in f.contradiction_with if c in by_cid
        )
    versions = {"interpret": prompt_version, "candidates": rules.POLICY_VERSION}
    run_id = hashlib.sha256(
        json.dumps([model["source"], versions], sort_keys=True).encode()
    ).hexdigest()[:16]
    catalogue = {
        "schema_version": "1.0.0",
        "app_id": model["app_id"],
        "generated_at_run": run_id,
        "prompt_versions": versions,
        "rules": [r for r, _ in kept],
        "dependency_graph": _graph(model["app_id"], kept),
    }
    jsonschema.validate(catalogue, schema)
    report = {
        "app_id": model["app_id"],
        "run_id": run_id,
        "candidates": len(all_facts),
        "rules": len(kept),
        "rejected_by_model": rejected,
        "llm": dict(llm.stats),
    }
    return catalogue, report


def write(app_id: str, catalogue: dict[str, Any], report: dict[str, Any]) -> Path:
    out = OUT / app_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "analysis-report.json").write_text(json.dumps(report, indent=2) + "\n")
    path = out / "rule-catalogue.json"
    path.write_text(json.dumps(catalogue, indent=2, ensure_ascii=False) + "\n")
    return path

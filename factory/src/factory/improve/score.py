"""The Phase 5 objective (docs/scoring.md). Every term is measured from artefacts.

score = 0.40 executed_oracle_parity_rate + 0.20 rule_recall_vs_ground_truth
      + 0.15 (1 - human_review_rate) + 0.15 generated_test_pass_rate + 0.10 cost_efficiency

Apps without ground truth (the synthetic held-out app) omit recall; the other weights are
renormalised (ADR-005).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from factory.common.paths import REPO_ROOT
from factory.parity import harness

WEIGHTS = {
    "executed_oracle_parity_rate": 0.40,
    "rule_recall_vs_ground_truth": 0.20,
    "one_minus_human_review_rate": 0.15,
    "generated_test_pass_rate": 0.15,
    "cost_efficiency": 0.10,
}
TOKEN_BUDGET_PER_RULE = 2000  # LLM tokens (prompt + completion, replayed calls included)
GT_DIR = REPO_ROOT / "experiments" / "ground-truth"


def ground_truth(app: str) -> set[tuple[str, str]] | None:
    path = GT_DIR / f"{app}.json"
    if not path.exists():
        return None
    lock = {
        n: h
        for h, n in (x.split() for x in (GT_DIR / "GROUNDTRUTH.lock").read_text().splitlines() if x)
    }
    got = hashlib.sha256(path.read_bytes()).hexdigest()
    if lock.get(f"experiments/ground-truth/{app}.json") != got:
        raise SystemExit(f"{path.name}: sha256 {got} does not match GROUNDTRUTH.lock")
    return {(r["file"], r["path"]) for r in json.loads(path.read_text())["rules"]}


def parity_report(app: str) -> dict[str, Any]:
    return dict(json.loads((harness.PARITY / "reports" / app / "parity-report.json").read_text()))


def components(
    app: str, catalogue: dict[str, Any], report: dict[str, Any], parity: dict[str, Any]
) -> dict[str, Any]:
    if "tokens_incl_replay" not in report["llm"]:
        raise SystemExit(f"{app}: analysis report predates token accounting; re-run analyse")
    rules = catalogue["rules"]
    n = len(rules)
    # Formula statuses come from the committed parity run and do not depend on the catalogue;
    # the catalogue decides which rules they evidence. Skip dispositions only change gap text.
    evidence = harness.classify_rules(app, catalogue, parity["formula_results"], [])
    classes = Counter(r["class"] for r in evidence)
    review = sum(bool(r["flags"]["needs_human_review"]) for r in rules)
    f = parity["formulas"]
    tokens = int(report["llm"]["tokens_incl_replay"])
    out: dict[str, Any] = {
        "executed_oracle_parity_rate": classes["executed"] / n if n else 0.0,
        "one_minus_human_review_rate": 1 - review / n if n else 0.0,
        "generated_test_pass_rate": f.get("pass", 0) / f["total"] if f["total"] else 0.0,
        "cost_efficiency": max(0.0, 1 - tokens / n / TOKEN_BUDGET_PER_RULE) if n else 0.0,
    }
    gt = ground_truth(app)
    if gt is not None:
        found = {(loc["file"], loc["path"]) for r in rules for loc in r["source_locations"]}
        out["rule_recall_vs_ground_truth"] = len(gt & found) / len(gt)
    out = {k: round(v, 4) for k, v in out.items()}
    out["counts"] = {
        "rules": n,
        "candidates": report["candidates"],
        "needs_review": review,
        "evidence": dict(sorted(classes.items())),
        "llm_tokens_incl_replay": tokens,
        "ground_truth_found": None if gt is None else len(gt & found),
        "ground_truth_total": None if gt is None else len(gt),
    }
    return out


def total(comp: dict[str, Any]) -> float:
    used = {k: w for k, w in WEIGHTS.items() if k in comp}
    return float(round(sum(w * comp[k] for k, w in used.items()) / sum(used.values()), 4))


def score_committed(app: str) -> dict[str, Any]:
    art = REPO_ROOT / "artefacts" / app
    comp = components(
        app,
        json.loads((art / "rule-catalogue.json").read_text()),
        json.loads((art / "analysis-report.json").read_text()),
        parity_report(app),
    )
    return {"app": app, "score": total(comp), "components": comp}

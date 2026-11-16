"""dashboard/index.html: measured figures from artefacts plus an editable, labelled effort model."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from factory.common.paths import REPO_ROOT
from factory.evidence import trace
from factory.evidence.review import APPS, queue
from factory.improve import experiment, score

# Every assumption is shown in the UI as an editable, orange "ASSUMPTION" input.
ASSUMPTIONS: list[dict[str, Any]] = [
    {"key": "apps", "label": "Apps in estate", "value": 30, "why": "client brief"},
    {"key": "weeks", "label": "Window (weeks)", "value": 12, "why": "client brief: 2-3 months"},
    {"key": "engineers", "label": "Engineers on the programme", "value": 6, "why": "assumed"},
    {"key": "hours_week", "label": "Productive hours / engineer / week", "value": 30,
     "why": "assumed"},
    {"key": "review_min", "label": "Minutes per human-review item", "value": 20, "why": "assumed"},
    {"key": "unproven_min",
     "label": "Minutes to write a scenario check for a migrated but unproven rule",
     "value": 45, "why": "assumed"},
    {"key": "manual_min", "label": "Minutes to hand-migrate a rule the factory did not target",
     "value": 90, "why": "assumed"},
    {"key": "fixed_days", "label": "Fixed days per app (integration, data migration, UAT)",
     "value": 8, "why": "assumed"},
]  # fmt: skip


def measured(app: str) -> dict[str, Any]:
    a = trace.load(app)
    m = trace.matrix(app)
    n = len(m["rules"])
    ev = Counter(r["evidence"] for r in m["rules"])
    llm = a["analysis"]["llm"]
    return {
        "app": app,
        "rules": n,
        "candidates": a["analysis"]["candidates"],
        "auto_migrated": sum(r["auto_migrated"] for r in m["rules"]),
        "evidence": {k: ev.get(k, 0) for k in ("executed", "scenario", "unproven", "failed")},
        "migrated_unproven": sum(
            r["auto_migrated"] and r["evidence"] == "unproven" for r in m["rules"]
        ),
        "review_queue": len(queue(app)),
        "llm_calls": llm["calls"],
        "llm_tokens": llm["tokens_incl_replay"],
        "llm_seconds": round(llm["ms_incl_replay"] / 1000, 1),
        "frozen_cases": a["parity"]["frozen_cases"],
        "oracle_drift": a["parity"]["oracle_drift"],
        "formulas": {k: a["parity"]["formulas"].get(k, 0) for k in ("pass", "fail", "unproven")},
        "mutation": a["parity"]["mutation"],
        "score": score.score_committed(app)["score"],
        "sources": {
            "rules": f"artefacts/{app}/rule-catalogue.json",
            "evidence": f"parity/reports/{app}/parity-report.json",
            "llm": f"artefacts/{app}/analysis-report.json",
            "auto_migrated": f"artefacts/{app}/traceability-matrix.json",
        },
    }


def write() -> None:
    data = {
        "apps": [measured(a) for a in APPS],
        "leaderboard": [
            {"name": r["name"], "tuning": r["tuning"]["score"], "heldout": r["heldout"]["score"],
             "decision": r["decision"]}
            for r in experiment.load_runs()
        ],  # fmt: skip
        "assumptions": ASSUMPTIONS,
    }
    tpl = (REPO_ROOT / "dashboard" / "template.html").read_text()
    out = tpl.replace("/*DATA*/null", json.dumps(data, indent=1))
    (REPO_ROOT / "dashboard" / "index.html").write_text(out)

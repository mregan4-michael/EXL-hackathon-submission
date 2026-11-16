"""Evidence is derived from committed artefacts and cannot overstate migration or proof."""

from __future__ import annotations

import json

from factory.common.paths import REPO_ROOT
from factory.evidence import review, trace

APPS = review.APPS


def test_every_rule_has_a_row_and_source_link() -> None:
    for app in APPS:
        cat = json.loads((REPO_ROOT / f"artefacts/{app}/rule-catalogue.json").read_text())
        m = trace.matrix(app)
        assert [r["id"] for r in m["rules"]] == [r["id"] for r in cat["rules"]]
        assert all(r["links"] for r in m["rules"])


def test_design_only_and_not_compiled_are_not_auto_migrated() -> None:
    for app in APPS:
        for r in trace.matrix(app)["rules"]:
            kinds = {x["target"]["code"] == "" for x in r["links"]}
            if True in kinds:
                assert not r["auto_migrated"], r["id"]


def test_evidence_class_matches_parity_report() -> None:
    for app in APPS:
        rep = json.loads((REPO_ROOT / f"parity/reports/{app}/parity-report.json").read_text())
        want = {e["id"]: e["class"] for e in rep["rule_evidence"]}
        got = {r["id"]: r["evidence"] for r in trace.matrix(app)["rules"]}
        assert got == want


def test_review_queue_contains_every_flagged_and_failed_rule() -> None:
    for app in APPS:
        q = {i["id"] for i in review.queue(app)}
        for r in trace.matrix(app)["rules"]:
            if r["needs_human_review"] or r["evidence"] == "failed":
                assert r["id"] in q


def test_startup_globals_with_unresolved_values_are_not_migrated() -> None:
    design = {
        "app_id": "x",
        "generated": {"formulas": [], "not_compiled": []},
        "actions": [],
        "rbac": {},
        "flows": [],
        "session_globals": [
            {"name": "gblLimit", "resolved": True},
            {"name": "gblIsManager", "resolved": False},
        ],
    }
    t = trace._targets(design)["App.OnStart"]
    assert t["code"] == "" and "gblIsManager" in t["symbol"]
    design["session_globals"] = design["session_globals"][:1]
    assert trace._targets(design)["App.OnStart"]["code"]

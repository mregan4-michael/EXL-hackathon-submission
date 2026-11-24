"""Phase 5: the objective and the experiment protocol (docs/scoring.md, ADR-013)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from factory.analyse import rules
from factory.improve import experiment, score


def test_total_renormalises_when_recall_is_absent() -> None:
    full = {k: 1.0 for k in score.WEIGHTS}
    assert score.total(full) == 1.0
    no_gt = {k: v for k, v in full.items() if k != "rule_recall_vs_ground_truth"}
    no_gt["executed_oracle_parity_rate"] = 0.0
    assert score.total(no_gt) == round(1 - 0.40 / 0.80, 4)


def test_ground_truth_is_locked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert score.ground_truth("claims-workbench") is None  # held-out app has no labels
    assert len(score.ground_truth("approvals-kit") or ()) == 124
    gt = tmp_path / "approvals-kit.json"
    gt.write_text((score.GT_DIR / "approvals-kit.json").read_text().replace("}", "} ", 1))
    (tmp_path / "GROUNDTRUTH.lock").write_text((score.GT_DIR / "GROUNDTRUTH.lock").read_text())
    monkeypatch.setattr(score, "GT_DIR", tmp_path)
    with pytest.raises(SystemExit, match="GROUNDTRUTH.lock"):
        score.ground_truth("approvals-kit")


def test_cost_needs_replay_inclusive_tokens() -> None:
    with pytest.raises(SystemExit, match="token accounting"):
        score.components("claims-workbench", {"rules": []}, {"llm": {}}, {"formulas": {}})


def test_fairness_word_policy_ignores_age_inside_other_words() -> None:
    v1, v2 = rules.POLICIES["candidates.v1"], rules.POLICIES["candidates.v2"]
    assert rules.fairness_sensitive("varMessage", v1)  # v1: substring match (the false positive)
    assert not rules.fairness_sensitive("varMessage", v2)
    assert not rules.fairness_sensitive("Stage", v2)
    assert rules.fairness_sensitive("cat_ClaimantAge", v2)
    assert rules.fairness_sensitive("IsVulnerableCustomer", v2)


def test_experiment_must_change_exactly_one_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = {"name": "p", "config": {"interpret": "interpret.v1", "candidates": "candidates.v1"}}
    (tmp_path / "itp.json").write_text(json.dumps(parent | {"name": "p"}))
    monkeypatch.setattr(experiment, "RUNS", tmp_path)
    with pytest.raises(SystemExit, match="exactly one variable"):
        experiment.run("x", "interpret.v2", "candidates.v2", "", "p", replay=True)
    with pytest.raises(SystemExit, match="exactly one variable"):
        experiment.run("x", "interpret.v1", "candidates.v1", "", "p", replay=True)


def test_recorded_runs_follow_the_keep_rule() -> None:
    runs = {r["name"]: r for r in experiment.load_runs()}
    assert len(runs) >= 3
    for r in runs.values():
        if r["parent"] is None:
            assert r["decision"] == "baseline"
            continue
        better = r["tuning"]["score"] > runs[r["parent"]]["tuning"]["score"]
        assert r["decision"] == ("kept" if better else "reverted")
        assert set(r["heldout"]) == {"app", "score"}  # aggregate only
    assert any(r["decision"] == "reverted" for r in runs.values())


def test_runs_are_loaded_whatever_their_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "fairness-v4.json").write_text(json.dumps({"name": "fairness-v4"}))
    (tmp_path / "fairness-v4.critique.json").write_text("{}")
    monkeypatch.setattr(experiment, "RUNS", tmp_path)
    assert [r["name"] for r in experiment.load_runs()] == ["fairness-v4"]


def test_experiment_results_are_append_only_and_branch_from_kept_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = {"interpret": "interpret.v1", "candidates": "candidates.v1"}
    (tmp_path / "a.json").write_text(json.dumps({"name": "a", "config": cfg, "decision": "kept"}))
    (tmp_path / "r.json").write_text(
        json.dumps({"name": "r", "config": cfg, "decision": "reverted"})
    )
    monkeypatch.setattr(experiment, "RUNS", tmp_path)
    with pytest.raises(SystemExit, match="already recorded"):
        experiment.run("a", "interpret.v2", "candidates.v1", "", None, replay=True)
    for alias in ("./a", "a.critique", "../runs/a", ""):
        with pytest.raises(SystemExit, match="run names may only use"):
            experiment.run(alias, "interpret.v2", "candidates.v1", "", None, replay=True)
    with pytest.raises(SystemExit, match="was reverted"):
        experiment.run("x", "interpret.v2", "candidates.v1", "", "r", replay=True)
    with pytest.raises(SystemExit, match="unknown parent"):
        experiment.run("x", "interpret.v2", "candidates.v1", "", "nope", replay=True)


def test_locked_ground_truth_cannot_go_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "GROUNDTRUTH.lock").write_text((score.GT_DIR / "GROUNDTRUTH.lock").read_text())
    monkeypatch.setattr(score, "GT_DIR", tmp_path)
    with pytest.raises(SystemExit, match="missing"):
        score.ground_truth("approvals-kit")
    assert score.ground_truth("claims-workbench") is None

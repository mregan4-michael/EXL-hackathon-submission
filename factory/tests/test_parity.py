"""Phase 4 parity: inputs come from the legacy AST, expectations from the Power Fx oracle."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from factory.common.fxhost import FxHost
from factory.generate.transpile import BOOL, DATE, NUM, STR, Param
from factory.parity import cases, harness


@pytest.fixture(scope="module")
def fx() -> Any:
    with FxHost() as h:
        yield h


def _ast(fx: FxHost, formula: str) -> dict[str, Any]:
    r = fx.parse(formula)
    assert r["ok"], r
    ast: dict[str, Any] = r["ast"]
    return ast


def test_boundary_values_straddle_each_threshold(fx: FxHost) -> None:
    ast = _ast(fx, "If(Value(t.Text) > 10000, 1, 0)")
    pool = cases.pool(Param("t.Text", "t_Text", STR), ast)
    assert {"9999.99", "10000", "10000.01", "9999", "10001", "", "abc", None} <= set(pool)


def test_date_pool_hits_day_difference_limits(fx: FxHost) -> None:
    ast = _ast(fx, "DateDiff(a.SelectedDate, b.SelectedDate) > 56")
    pool = cases.pool(Param("b.SelectedDate", "b", DATE), ast)
    assert {"$date": "2024-03-11"} in pool and {"$date": "2024-03-12"} in pool
    assert None in pool


def test_generation_is_deterministic_and_seeded_by_key(fx: FxHost) -> None:
    ast = _ast(fx, "If(x > 5 && y.Visible, 1, 2)")
    ps = [Param("x", "x", NUM), Param("y.Visible", "y_Visible", BOOL)]
    assert cases.generate("k", ps, ast) == cases.generate("k", ps, ast)
    assert {c["kind"] for c in cases.generate("k", ps, ast)} == {"baseline", "boundary", "random"}
    assert cases.generate("k", [], ast) == [{"kind": "baseline", "inputs": {}}]


def test_oracle_vars_nest_control_properties_and_type_blanks() -> None:
    ps = [Param("txtA.Text", "a", STR), Param("dd.Selected.Value", "d", STR), Param("g", "g", NUM)]
    env = harness.oracle_vars(ps, {"txtA.Text": "1", "dd.Selected.Value": None, "g": Decimal(5)})
    assert env is not None
    assert env["txtA"] == {"Text": "1"} and env["dd"] == {
        "Selected": {"Value": {"$blank": "string"}}
    }
    assert env["g"] == Decimal(5) and "DisplayMode" in env
    assert harness.oracle_vars([Param("User().Email", "u", STR)], {}) is None


def test_canvas_ismatch_default_is_complete(fx: FxHost) -> None:
    f = 'IsMatch(t, "\\d{2}")'
    shimmed = harness.canvas_host(f, _ast(fx, f))
    assert shimmed == 'IsMatch(t, "\\d{2}", MatchOptions.Complete)'
    assert fx.eval(shimmed, {"t": "a12"})["value"] is False
    assert fx.eval(f, {"t": "a12"})["value"] is True  # interpreter default is Contains


def test_mutants_swap_boundaries_and_bump_literals(fx: FxHost) -> None:
    f = "If(Value(t.Text) > 10000 && x <= 2, 1, 0)"
    texts = {" ".join(t.split()) for _, t in harness.mutants(f, _ast(fx, f))}
    assert "If(Value(t.Text) >= 10000 && x <= 2, 1, 0)" in texts
    assert "If(Value(t.Text) > 10000 && x < 2, 1, 0)" in texts
    assert "If(Value(t.Text) > 10001 && x <= 2, 1, 0)" in texts
    assert "If(Value(t.Text) > 10000 || x <= 2, 1, 0)" in texts


def test_errors_agree_only_with_errors() -> None:
    assert harness.same({"error": "a"}, {"error": "b"})
    assert not harness.same({"error": "a"}, {"value": 0})
    assert harness.same({"value": Decimal("2950.00")}, {"value": 2950})
    assert not harness.same({"value": None}, {"value": ""})


def test_claims_workbench_parity_has_no_mismatch_or_drift() -> None:
    rep = harness.run("claims-workbench")
    assert rep["oracle_drift"] == 0
    assert rep["formulas"].get("fail", 0) == 0
    assert rep["formulas"]["pass"] >= 25
    assert rep["mutation"]["killed"] > 0


def test_testset_lock_rejects_edited_testset(tmp_path, monkeypatch):
    from factory.parity import harness

    ts = tmp_path / "testset"
    ts.mkdir()
    (ts / "x.jsonl").write_text('{"case": 0}\n')
    monkeypatch.setattr(harness, "PARITY", tmp_path)
    monkeypatch.setattr(harness, "LOCK", ts / "TESTSET.lock")
    import hashlib

    good = hashlib.sha256((ts / "x.jsonl").read_bytes()).hexdigest()
    (ts / "TESTSET.lock").write_text(f"{good}  x.jsonl\n")
    harness.verify_lock("x")
    (ts / "x.jsonl").write_text('{"case": 1}\n')
    with pytest.raises(SystemExit, match="does not match TESTSET.lock"):
        harness.verify_lock("x")

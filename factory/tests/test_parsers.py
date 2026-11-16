"""Golden tests for the deterministic Stage 1a parsers (no AI involved)."""

from __future__ import annotations

from pathlib import Path

import pytest

from factory.analyse import canvas, dataverse, flows, fxast
from factory.common.fxhost import FxHost
from factory.common.paths import LEGACY

CW = LEGACY / "claims-workbench"
AK = LEGACY / "approvals-kit"


@pytest.fixture(scope="module")
def fx() -> FxHost:
    return FxHost()


def test_pa_yaml_line_numbers_point_at_formula() -> None:
    sites = {s.path: s for s in canvas.parse_pa_yaml(CW / "CanvasApps" / "src")}
    site = sites["SettlementScreen/lblExcess.Text"]
    lines = Path(site.file).read_text().splitlines() if Path(site.file).is_absolute() else []
    if not lines:
        lines = (LEGACY.parent / site.file).read_text().splitlines()
    assert "Text:" in lines[site.line - 1]
    assert site.formula.lstrip().startswith("//")
    assert sites["App.OnStart"].kind == "app_onstart"


def test_pa_yaml_strips_leading_equals() -> None:
    for s in canvas.parse_pa_yaml(CW / "CanvasApps" / "src"):
        assert not s.formula.startswith("=")


def test_msapp_controls_walk_nested_children() -> None:
    app_dir = next((AK / "CanvasApps").iterdir())
    sites = list(canvas.parse_msapp_controls(app_dir))
    assert len(sites) > 2000
    assert all(s.line > 0 for s in sites)
    assert any("/" in s.path.split(".")[0] for s in sites)


def test_dataverse_entity_types_and_ranges() -> None:
    xml = CW / "Entities" / "clm_Payment" / "Entity.xml"
    table = dataverse.parse_entity(xml)
    amount = next(a for a in table.attributes if a.name == "clm_Amount")
    assert amount.required and amount.min_value == 0 and amount.max_value == 1_000_000
    sort_code = next(a for a in table.attributes if a.name == "clm_SortCode")
    assert sort_code.max_length == 8
    formulas = {s.path: s.formula for s in dataverse.column_sites(table, xml)}
    assert (
        formulas["clm_Payment.clm_Amount"] == "Required(clm_Amount) && Range(clm_Amount, 0, 1e+06)"
    )


def test_role_privileges_extracted() -> None:
    roles = {s.path: s.formula for s in dataverse.role_sites(CW / "Roles")}
    assert "prvApproveclm_Payment" not in roles["ClaimsHandler"]
    assert "prvApproveclm_Payment:Global" in roles["ClaimsManager"]


def test_flow_conditions_switches_and_loops() -> None:
    path = next((CW / "Workflows").glob("ClaimsComplaintDeadlines-*.json"))
    flow, sites = flows.parse_flow(path)
    assert flow.trigger_kind == "Recurrence"
    nested = [s for s in sites if "Apply_to_each_complaint/actions/" in s.path]
    assert {s.path.rsplit("/", 1)[-1] for s in nested} == {
        "Check_reminder_window",
        "Check_eight_week_breach",
    }
    pay = next((CW / "Workflows").glob("ClaimsPaymentAuthorisation-*.json"))
    pflow, psites = flows.parse_flow(pay)
    assert any(s.formula.startswith("Switch(") for s in psites)
    assert "clm_payments" in pflow.writes


def test_approval_kit_flows_parse() -> None:
    files = sorted((AK / "Workflows").glob("*.json"))
    assert len(files) == 25
    for f in files:
        flow, _ = flows.parse_flow(f)
        assert flow.trigger_kind


def test_fxhost_parse_ast_and_queries(fx: FxHost) -> None:
    resp = fx.parse('If(Value(txtAmount.Text) > 25000, "Manager", "Handler")')
    assert not resp.get("errors")
    ast = resp["ast"]
    assert fxast.has_branching(ast)
    assert {"If", "Value"} <= set(fxast.functions(ast))
    assert 25000 in fxast.numbers(ast)
    assert "txtAmount.Text" in fxast.references(ast)


def test_fxhost_eval_and_unsupported(fx: FxHost) -> None:
    ok = fx.eval("If(x > 25000, 1, 0)", {"x": 25000})
    assert ok["value"] == 0
    bad = fx.eval("Patch(T, Defaults(T), {a: 1})", {})
    assert bad["ok"] is False and "Patch" in bad["error"]


def test_injection_comment_is_preserved_as_data() -> None:
    """The parser must keep the comment verbatim; defence happens in the agent layer."""
    sites = {s.path: s for s in canvas.parse_pa_yaml(CW / "CanvasApps" / "src")}
    assert "ignore all previous instructions" in sites["SettlementScreen/lblExcess.Text"].formula

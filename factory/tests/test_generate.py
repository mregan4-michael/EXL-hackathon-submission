"""Phase 3 generator: deterministic, honest about what it cannot compile."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from factory.analyse.parse import parse_app
from factory.common.fxhost import FxHost
from factory.generate import design as dsn
from factory.generate import emit, transpile

CATALOGUE = Path(__file__).resolve().parents[2] / "artefacts" / "claims-workbench"


@pytest.fixture(scope="module")
def model() -> dict[str, Any]:
    with FxHost() as fx:
        m = parse_app("claims-workbench", fx)
    out: dict[str, Any] = json.loads(json.dumps(m.to_json()))
    return out


@pytest.fixture(scope="module")
def catalogue() -> dict[str, Any]:
    out: dict[str, Any] = json.loads((CATALOGUE / "rule-catalogue.json").read_text())
    return out


def _site(model: dict[str, Any], path_suffix: str) -> dict[str, Any]:
    return next(s for s in model["sites"] if s["path"].endswith(path_suffix))


def test_settlement_guard_compiles_with_authority_limit_input(model: dict[str, Any]) -> None:
    c = transpile.compile_formula(_site(model, "btnApprovePayment.DisplayMode")["ast"])
    refs = {p.ref for p in c.params}
    assert "gblUserAuthorityLimit" in refs
    assert "txtClaimAmount.Text" in refs


def test_side_effect_formulas_are_not_compiled(model: dict[str, Any]) -> None:
    with pytest.raises(transpile.UnsupportedError):
        transpile.compile_formula(_site(model, "btnApprovePayment.OnSelect")["ast"])


def test_every_skipped_formula_has_a_disposition(
    model: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    gens, skipped = emit.formulas(model, catalogue)
    assert gens and skipped
    assert all(s["disposition"] for s in skipped)
    compiled = {g.output for g in gens}
    assert compiled.isdisjoint({s["path"].split("/")[-1] for s in skipped})


def test_collection_items_are_static_options_not_compiled_references(
    model: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    gens, skipped = emit.formulas(model, catalogue)
    assert "ddClaimType.Items" not in {g.output for g in gens}
    dd = next(s for s in skipped if s["path"].endswith("ddClaimType.Items"))
    assert dd["disposition"].startswith("static options")
    assert dsn.collections(model["sites"])["colClaimTypes"] == [
        "Motor",
        "Home",
        "Theft",
        "Injury",
        "Travel",
    ]


def test_generated_csharp_is_deterministic(
    model: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    d = dsn.design(model, catalogue)
    a = emit.formulas(model, catalogue)[0]
    b = emit.formulas(model, catalogue)[0]
    acts = emit._compile_fields(d["actions"])
    assert emit.rules_cs(a, acts) == emit.rules_cs(b, acts)


def test_partition_keys_are_justified(model: dict[str, Any], catalogue: dict[str, Any]) -> None:
    d = dsn.design(model, catalogue)
    for c in d["containers"]:
        assert c["partition_key"].startswith("/")
        assert c["partition_key_rationale"]


def test_compose_never_targets_a_cloud_endpoint() -> None:
    text = emit.compose("claims-workbench")
    assert "documents.azure.com" not in text
    assert "Store__Kind: file" in text


@pytest.mark.parametrize(
    ("control_type", "widget"),
    [
        ("TextInput", "text"),
        ("button", "button"),
        ("checkbox", "checkbox"),
        ("dropdown", "select"),
        ("combobox", "select"),
        ("Microsoft_CoreControls_ComboBox", "select"),
        ("Microsoft_CoreControls_Checkbox", "checkbox"),
        ("cat_PowerCAT.CommandBar", "label"),
    ],
)
def test_widget_mapping_ignores_case_and_namespace(control_type: str, widget: str) -> None:
    assert dsn.widget_for(control_type) == widget

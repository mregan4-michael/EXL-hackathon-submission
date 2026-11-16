"""Stage 1a: deterministic parse of a legacy app into a queryable LegacyModel (no AI)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from factory.analyse import canvas, dataverse, flows
from factory.analyse.model import LegacyModel
from factory.common.fxhost import FxHost
from factory.common.paths import LEGACY, OUT


def load_manifest(app_id: str) -> dict[str, Any]:
    manifest: dict[str, Any] = yaml.safe_load((LEGACY / app_id / "manifest.yaml").read_text())
    return manifest


def parse_app(app_id: str, fx: FxHost) -> LegacyModel:
    manifest = load_manifest(app_id)
    root = LEGACY / app_id
    model = LegacyModel(app_id=app_id, source=str(manifest.get("source", "")))
    for c in manifest.get("canvas") or []:
        app_dir = root / c["path"]
        sites = (
            canvas.parse_msapp_controls(app_dir)
            if c["format"] == "msapp_json"
            else canvas.parse_pa_yaml(app_dir)
        )
        model.sites.extend(sites)
        model.controls.extend(canvas.list_controls(app_dir, c["format"]))
    if manifest.get("entities"):
        for entity_dir in sorted((root / manifest["entities"]).iterdir()):
            xml = entity_dir / "Entity.xml"
            if not xml.exists():
                continue
            table = dataverse.parse_entity(xml)
            model.tables.append(table)
            model.sites.extend(dataverse.column_sites(table, xml))
            model.sites.extend(dataverse.calculated_sites(entity_dir, table))
    if manifest.get("roles"):
        model.sites.extend(dataverse.role_sites(root / manifest["roles"]))
    if manifest.get("flows"):
        for path in sorted((root / manifest["flows"]).glob("*.json")):
            flow, flow_sites = flows.parse_flow(path)
            model.flows.append(flow)
            model.sites.extend(flow_sites)
    model.screens = sorted(
        {s.screen for s in model.sites if s.kind == "canvas_property" and s.screen}
    )
    for site in model.sites:
        if site.language == "powerfx":
            resp = fx.parse(site.formula)
            site.ast = resp.get("ast")
            site.parse_errors = list(resp.get("errors", []))
    return model


def write_model(model: LegacyModel) -> Path:
    out = OUT / model.app_id / "legacy-model.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(model.to_json(), indent=1, sort_keys=True))
    return out

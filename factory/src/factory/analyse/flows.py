"""Cloud-flow parser: Logic Apps workflow definition language (WDL) JSON."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from factory.analyse._lines import find_line
from factory.analyse.model import Flow, FormulaSite
from factory.common.paths import rel

_READ_OPS = {"ListRecords", "GetItem", "ListRecordsWithOrganization", "GetItemWithOrganization"}
_WRITE_OPS = {
    "CreateRecord",
    "UpdateRecord",
    "DeleteRecord",
    "UpdateOnlyRecord",
    "PerformBoundAction",
}
_LOGIC_IN_VALUE = re.compile(
    r"\b(if|equals|greater|less|greaterOrEquals|lessOrEquals|and|or|not)\("
)


def flow_name(path: Path) -> str:
    return re.sub(r"-[0-9A-F]{8}-[0-9A-F-]{27}$", "", path.stem)


def parse_flow(path: Path) -> tuple[Flow, list[FormulaSite]]:
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    definition = doc["properties"]["definition"]
    name = flow_name(path)
    sites: list[FormulaSite] = []
    triggers: dict[str, dict[str, Any]] = definition.get("triggers", {})
    trig_name, trig = next(iter(triggers.items()), ("", {}))
    params: dict[str, Any] = trig.get("inputs", {}).get("parameters", {})
    flow = Flow(
        name=name,
        file=rel(path),
        trigger_kind=str(trig.get("type", "")),
        trigger_entity=str(params.get("subscriptionRequest/entityname", "")),
        trigger_message=str(params.get("subscriptionRequest/message", "")),
        trigger_filter=str(
            params.get("subscriptionRequest/filterexpression", "")
            or params.get("subscriptionRequest/filteringattributes", "")
        ),
    )
    recurrence = trig.get("recurrence")
    if flow.trigger_filter or recurrence:
        formula = (
            f"Recurrence({json.dumps(recurrence, sort_keys=True)})"
            if recurrence
            else (
                f"On({flow.trigger_entity}, message={flow.trigger_message}, "
                f"filter={flow.trigger_filter})"
            )
        )
        sites.append(_site(path, name, f"triggers/{trig_name}", trig_name, formula, "flow_trigger"))
    for aname, action in definition.get("actions", {}).items():
        sites.extend(_walk(path, name, flow, f"actions/{aname}", aname, action))
    return flow, sites


def _site(path: Path, flow: str, jpath: str, aname: str, formula: str, kind: str) -> FormulaSite:
    return FormulaSite(
        site_id=f"{rel(path)}#{jpath}",
        file=rel(path),
        kind=kind,  # type: ignore[arg-type]
        path=f"{flow}/{jpath}",
        line=find_line(path, (f'"{aname}": {{',)),
        language="wdl",
        formula=formula,
        screen=flow,
        control=aname,
    )


def _walk(
    path: Path, fname: str, flow: Flow, jpath: str, aname: str, action: dict[str, Any]
) -> Iterator[FormulaSite]:
    flow.actions += 1
    atype = action.get("type", "")
    inputs = action.get("inputs", {}) if isinstance(action.get("inputs"), dict) else {}
    desc = str(action.get("description", ""))
    if atype == "If":
        site = _site(path, fname, jpath, aname, json.dumps(action.get("expression")), "flow_action")
        site.description = desc
        yield site
    elif atype == "Switch":
        cases = {k: v.get("case") for k, v in action.get("cases", {}).items()}
        formula = f"Switch({json.dumps(action.get('expression'))}, cases={json.dumps(cases)})"
        site = _site(path, fname, jpath, aname, formula, "flow_action")
        site.description = desc
        yield site
    elif atype == "Until":
        expr, limit = json.dumps(action.get("expression")), json.dumps(action.get("limit"))
        formula = f"Until({expr}, limit={limit})"
        yield _site(path, fname, jpath, aname, formula, "flow_action")
    elif atype in ("InitializeVariable", "SetVariable", "Compose"):
        value = json.dumps(inputs)
        if _LOGIC_IN_VALUE.search(value):
            site = _site(path, fname, jpath, aname, f"{atype}({value})", "flow_action")
            site.description = desc
            yield site
    host = inputs.get("host", {}) if isinstance(inputs.get("host"), dict) else {}
    op = str(host.get("operationId", ""))
    entity = (
        str(inputs.get("parameters", {}).get("entityName", ""))
        if isinstance(inputs.get("parameters"), dict)
        else ""
    )
    if op in _READ_OPS and entity:
        flow.reads.append(entity)
    if op in _WRITE_OPS and entity:
        flow.writes.append(entity)
    if atype == "Workflow":
        flow.calls.append(str(inputs.get("host", {}).get("workflowReferenceName", "")))
    children: list[tuple[str, dict[str, Any]]] = []
    for k, v in action.get("actions", {}).items():
        children.append((f"{jpath}/actions/{k}", v))
    for k, v in action.get("else", {}).get("actions", {}).items():
        children.append((f"{jpath}/else/actions/{k}", v))
    for case, body in action.get("cases", {}).items():
        for k, v in body.get("actions", {}).items():
            children.append((f"{jpath}/cases/{case}/actions/{k}", v))
    for k, v in action.get("default", {}).get("actions", {}).items():
        children.append((f"{jpath}/default/actions/{k}", v))
    for cpath, child in children:
        yield from _walk(path, fname, flow, cpath, cpath.rsplit("/", 1)[-1], child)

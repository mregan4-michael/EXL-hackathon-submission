"""Design stage: derive the target design from the legacy model and rule catalogue.

Everything here is deterministic. Outputs (under generated/<app>/design/):
  design.json        tables -> Cosmos containers (partition key + rationale, PII,
                     retention), RBAC matrix, screen actions, session globals,
                     flow -> Azure hosting decisions, screen component map
  openapi.json       OpenAPI 3.0 contract for the generated API
"""

from __future__ import annotations

import re
from typing import Any

from factory.analyse import fxast, rules
from factory.generate import transpile

JSON_TYPE = {
    "primarykey": {"type": "string"},
    "lookup": {"type": "string"},
    "nvarchar": {"type": "string"},
    "ntext": {"type": "string"},
    "money": {"type": "number"},
    "decimal": {"type": "number"},
    "int": {"type": "integer"},
    "bit": {"type": "boolean"},
    "datetime": {"type": "string", "format": "date"},
}
RETENTION = {
    "special_category": "Minimise: store only while the claim is open; erase on request unless "
    "a legal hold applies (UK GDPR Art. 9; ASSUMPTION, confirm with DPO).",
    "financial": "Retain 7 years after claim closure for FCA/HMRC record keeping (ASSUMPTION), "
    "then erase.",
    "contact": "Erase or pseudonymise on a valid erasure request once no claim is open.",
    "personal": "Erase or pseudonymise on a valid erasure request once no claim is open.",
    "identifier": "Kept with the record it identifies; pseudonymised when that record is erased.",
}
PRIV = re.compile(r"prv(Create|Read|Write|Delete|Append|AppendTo|Assign|Share|Approve)(\w+?):(\w+)")
# Keyed by the lowercase base type: pa.yaml uses "TextInput", .msapp JSON uses "textInput",
# "button", and modern controls are namespaced ("Microsoft_CoreControls_ComboBox").
CONTROL_WIDGET = {
    "textinput": "text",
    "datepicker": "date",
    "dropdown": "select",
    "combobox": "select",
    "checkbox": "checkbox",
    "toggle": "checkbox",
    "label": "label",
    "button": "button",
}


def widget_for(control_type: str) -> str:
    base = re.split(r"[_.]", control_type)[-1].lower()
    return CONTROL_WIDGET.get(base, "label")


def plural(word: str) -> str:
    if word.endswith("y") and word[-2:-1] not in "aeiou":
        return word[:-1] + "ies"
    return word if word.endswith("s") else word + "s"


def container_name(table: str) -> str:
    base = table.split("_", 1)[-1]
    return plural(re.sub(r"(?<!^)(?=[A-Z])", "-", base).lower())


def entity_set(table: str) -> str:
    return plural(table)


def _pii(name: str) -> str | None:
    for pat, cls in rules.PII_LEXICON:
        if pat.search(name):
            return cls
    return None


def cosmos(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in tables:
        attrs = t["attributes"]
        pk_attr = next((a for a in attrs if a["type"] == "primarykey"), None)
        parent = next((a for a in attrs if a["type"] == "lookup" and a.get("required")), None)
        if parent:
            pk = f"/{parent['name']}"
            why = (
                f"Required lookup {parent['name']} is the aggregate parent: the legacy app "
                f"reads {t['name']} rows by their parent, so those reads stay single-partition, "
                "and parent "
                "ids are high-cardinality so writes spread evenly."
            )
        else:
            pk = "/id"
            why = (
                "No required parent lookup; rows are read by id, so /id gives point reads and "
                "uniform distribution. Revisit if a cross-row query pattern appears."
            )
        fields = []
        for a in attrs:
            cls = _pii(a["name"])
            fields.append(
                {
                    "name": a["name"],
                    "type": a["type"],
                    "required": bool(a.get("required")),
                    "pii": cls,
                    "retention": RETENTION.get(cls or "", None),
                    "indexed": a["type"] != "ntext" and cls != "special_category",
                }
            )
        out.append(
            {
                "table": t["name"],
                "entity_set": entity_set(t["name"]),
                "container": container_name(t["name"]),
                "id_field": pk_attr["name"] if pk_attr else "id",
                "partition_key": pk,
                "partition_key_rationale": why,
                "fields": fields,
                "excluded_from_index": [f["name"] for f in fields if not f["indexed"]],
            }
        )
    return out


def rbac(sites: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, str]]]:
    """role -> table -> privilege -> depth (User | BusinessUnit | Global)."""
    roles: dict[str, dict[str, dict[str, str]]] = {}
    for s in sites:
        if s["kind"] != "security_role":
            continue
        grants: dict[str, dict[str, str]] = {}
        for priv, table, depth in PRIV.findall(s["formula"]):
            grants.setdefault(table, {})[priv] = depth
        roles[s["path"]] = {t: dict(sorted(p.items())) for t, p in sorted(grants.items())}
    return roles


def _patches(ast: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for n in fxast.walk(ast):
        if n["k"] == "Call" and n["fn"] == "Patch" and len(n["args"]) >= 3:
            target = fxast.dotted(n["args"][0])
            second = n["args"][1]
            creates = second["k"] == "Call" and second["fn"] == "Defaults"
            rec = n["args"][2]
            if target and rec.get("fields"):
                row = None if creates else fxast.dotted(second)
                out.append(
                    {"entity_set": target, "create": creates, "row": row, "fields": rec["fields"]}
                )
    return out


def actions(sites: list[dict[str, Any]], tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_set = {entity_set(t["name"]).lower(): t for t in tables}
    guards = {
        (s["screen"], s["control"]): s["path"]
        for s in sites
        if s["kind"] == "canvas_property" and s["prop"] == "DisplayMode"
    }
    out = []
    for s in sites:
        if s["kind"] != "canvas_property" or s["prop"] != "OnSelect" or not s.get("ast"):
            continue
        for p in _patches(s["ast"]):
            t = by_set.get(p["entity_set"].lower())
            if not t:
                continue
            cols = {a["name"].lower(): a["name"] for a in t["attributes"]}
            fields = {cols.get(k.lower(), k): v for k, v in sorted(p["fields"].items())}
            missing = [
                a["name"]
                for a in t["attributes"]
                if p["create"]
                and a.get("required")
                and a["type"] != "primarykey"
                and a["name"] not in fields
            ]
            out.append(
                {
                    "screen": s["screen"],
                    "control": s["control"],
                    "source": {"file": s["file"], "line": s["line"], "path": s["path"]},
                    "table": t["name"],
                    "operation": "Create" if p["create"] else "Write",
                    "guard": guards.get((s["screen"], s["control"])),
                    "row": p["row"],
                    "fields": fields,
                    "context_fields": missing,
                    "navigates_to": sorted(
                        fxast.dotted(n["args"][0]) or ""
                        for n in fxast.walk(s["ast"])
                        if n["k"] == "Call" and n["fn"] == "Navigate" and n["args"]
                    ),
                }
            )
    return out


def session_globals(
    sites: list[dict[str, Any]], tables: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """`Set(g, LookUp(T, Col = User().Email).Field)` in App.OnStart -> per-user server lookup."""
    by_set = {entity_set(t["name"]).lower(): t for t in tables}
    out = []
    for s in sites:
        if s["kind"] != "app_onstart" or not s.get("ast"):
            continue
        for n in fxast.walk(s["ast"]):
            if n["k"] != "Call" or n["fn"] != "Set" or len(n["args"]) != 2:
                continue
            name, val = fxast.dotted(n["args"][0]), n["args"][1]
            entry: dict[str, Any] = {"name": name, "source_line": s["line"], "resolved": False}
            if val["k"] == "DottedName" and val["l"]["k"] == "Call" and val["l"]["fn"] == "LookUp":
                lk = val["l"]["args"]
                t = by_set.get((fxast.dotted(lk[0]) or "").lower())
                cond = lk[1] if len(lk) > 1 else {}
                if t and cond.get("op") == "Equal" and "User" in fxast.functions(cond):
                    col = fxast.dotted(cond["l"]) or ""
                    cols = {a["name"].split("_", 1)[-1].lower(): a["name"] for a in t["attributes"]}
                    entry.update(
                        resolved=True,
                        table=t["name"],
                        match_column=cols.get(col.lower(), col),
                        value_column=cols.get(val["name"].lower(), val["name"]),
                    )
            if not entry["resolved"]:
                entry["reason"] = "Not a per-user LookUp; supplied as blank (fails closed)."
            out.append(entry)
    return out


def flow_hosting(model: dict[str, Any]) -> list[dict[str, Any]]:
    text: dict[str, str] = {}
    for s in model["sites"]:
        if s["kind"] in ("flow_action", "flow_trigger"):
            text.setdefault(s["path"].split("/")[0], "")
            text[s["path"].split("/")[0]] += s["formula"]
    out = []
    for f in model["flows"]:
        body = text.get(f["name"], "")
        waits = bool(re.search(r"approval|\"Wait\"|\"Until\"|Delay", body, re.IGNORECASE))
        if f["trigger_kind"] == "Recurrence":
            host, why = "Azure Functions (TimerTrigger)", "Scheduled batch with no human wait."
        elif waits:
            host = "Azure Durable Functions (orchestration)"
            why = "Waits on a human approval or timer; needs durable state and replay."
        else:
            host = "Azure Functions (Cosmos DB change-feed trigger)"
            why = f"Reacts to {f['trigger_entity'] or 'data'} changes; short, stateless."
        out.append(
            {"flow": f["name"], "trigger": f["trigger_kind"], "filter": f["trigger_filter"],
             "hosting": host, "rationale": why}  # fmt: skip
        )
    return out


def collections(sites: list[dict[str, Any]]) -> dict[str, list[str]]:
    """`ClearCollect(col, ["A", "B"])` in App.OnStart -> static option lists."""
    out: dict[str, list[str]] = {}
    for s in sites:
        if s["kind"] != "app_onstart" or not s.get("ast"):
            continue
        for n in fxast.walk(s["ast"]):
            if n["k"] == "Call" and n["fn"] in ("ClearCollect", "Collect") and len(n["args"]) == 2:
                name, opts = fxast.dotted(n["args"][0]), transpile.string_options(n["args"][1])
                if name and opts is not None:
                    out[name] = opts
    return out


def components(model: dict[str, Any], catalogue: dict[str, Any]) -> list[dict[str, Any]]:
    """Screen -> controls (every control, including formula-less inputs) with rule bindings."""
    by_path = {r["source_locations"][0]["path"]: r["id"] for r in catalogue["rules"]}
    cols = collections(model["sites"])
    props: dict[tuple[str, str], dict[str, Any]] = {}
    for s in model["sites"]:
        if s["kind"] == "canvas_property" and s["screen"]:
            props[(s["screen"], s["control"])] = props.get((s["screen"], s["control"]), {})
            props[(s["screen"], s["control"])][s["prop"]] = s
    screens: dict[str, list[dict[str, Any]]] = {}
    for c in model.get("controls", []):
        if c["type"] == "screen":
            screens.setdefault(c["screen"], [])
            continue
        widget = widget_for(c["type"])
        entry: dict[str, Any] = {
            "name": c["name"],
            "type": c["type"],
            "widget": widget,
            "source": {"file": c["file"], "line": c["line"]},
            "rules": {},
        }
        for prop, s in sorted(props.get((c["screen"], c["name"]), {}).items()):
            if s["path"] in by_path:
                entry["rules"][prop] = by_path[s["path"]]
            if prop == "Items" and s.get("ast"):
                opts = transpile.string_options(s["ast"])
                ref = fxast.dotted(s["ast"]) if opts is None else None
                if opts is None and ref in cols:
                    opts = cols[ref]
                if opts is not None:
                    entry["options"] = opts
            if prop == "Text" and widget == "button":
                entry["label"] = s["formula"].strip().strip('"')
        screens.setdefault(c["screen"], []).append(entry)
    return [{"screen": k, "controls": v} for k, v in sorted(screens.items())]


def openapi(app_id: str, containers: list[dict[str, Any]], screens: list[str]) -> dict[str, Any]:
    paths: dict[str, Any] = {
        "/health": {"get": {"responses": {"200": {"description": "ok"}}}},
        "/api/rules/{ruleId}/evaluate": {
            "post": {
                "summary": "Evaluate one generated rule",
                "parameters": [{"name": "ruleId", "in": "path", "required": True,
                                "schema": {"type": "string"}}],  # fmt: skip
                "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}},
                "responses": {
                    "200": {"description": "rule value"},
                    "404": {"description": "unknown"},
                },
            }
        },
        "/api/screens/{screen}/evaluate": {
            "post": {
                "summary": "Evaluate every rule on a screen in dependency order",
                "parameters": [{"name": "screen", "in": "path", "required": True,
                                "schema": {"type": "string", "enum": screens}}],  # fmt: skip
                "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}},
                "responses": {"200": {"description": "map of control.property -> value"}},
            }
        },
        "/api/screens/{screen}/actions/{control}": {
            "post": {
                "summary": "Run a legacy button action (guard + RBAC + persist)",
                "parameters": [
                    {
                        "name": "screen",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "control",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                ],
                "responses": {
                    "201": {"description": "created"},
                    "403": {"description": "role lacks the Dataverse privilege"},
                    "409": {"description": "legacy DisplayMode guard disables the action"},
                },
            }
        },
    }
    schemas: dict[str, Any] = {}
    for c in containers:
        props = {f["name"]: dict(JSON_TYPE.get(f["type"], {"type": "string"})) for f in c["fields"]}
        for f in c["fields"]:
            if f["pii"]:
                props[f["name"]]["x-pii"] = f["pii"]
        schemas[c["table"]] = {
            "type": "object",
            "required": [
                f["name"] for f in c["fields"] if f["required"] and f["type"] != "primarykey"
            ],
            "properties": props,
        }
        ref = {"$ref": f"#/components/schemas/{c['table']}"}
        paths[f"/api/{c['entity_set']}"] = {
            "get": {"responses": {"200": {"description": "list",
                    "content": {"application/json": {"schema": {"type": "array", "items": ref}}}}}},
        }  # fmt: skip
        paths[f"/api/{c['entity_set']}/{{id}}"] = {
            "get": {"parameters": [{"name": "id", "in": "path", "required": True,
                                    "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "row", "content": {"application/json":
                                  {"schema": ref}}}, "404": {"description": "not found"}}},
        }  # fmt: skip
    return {
        "openapi": "3.0.3",
        "info": {"title": f"{app_id} API (generated)", "version": "1.0.0"},
        "components": {
            "schemas": schemas,
            "securitySchemes": {
                "demoRole": {"type": "apiKey", "in": "header", "name": "X-Demo-User",
                             "description": "Offline only (Identity:Mode=demo)."},
                "entra": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT",
                          "description": "Azure: Entra ID token validated by Container Apps "
                                         "built-in auth; app role = legacy security role."}
            },
        },  # fmt: skip
        "security": [{"entra": []}, {"demoRole": []}],
        "paths": dict(sorted(paths.items())),
    }


def design(model: dict[str, Any], catalogue: dict[str, Any]) -> dict[str, Any]:
    containers = cosmos(model["tables"])
    comps = components(model, catalogue)
    return {
        "app_id": model["app_id"],
        "containers": containers,
        "rbac": rbac(model["sites"]),
        "actions": actions(model["sites"], model["tables"]),
        "session_globals": session_globals(model["sites"], model["tables"]),
        "flows": flow_hosting(model),
        "screens": comps,
        "openapi": openapi(model["app_id"], containers, [c["screen"] for c in comps]),
    }

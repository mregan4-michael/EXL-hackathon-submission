"""Emit stage: write the generated target (C#, TypeScript, Bicep, Compose) for one app.

Deterministic: the same legacy model + catalogue always produce byte-identical files.
App-specific code is generated (Rules.g.cs, App.g.cs, app.g.ts, main.bicep); the shared
runtime/host/UI shell is copied verbatim from factory/templates/. Nothing here calls a model.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from factory.analyse import fxast
from factory.common.paths import REPO_ROOT as ROOT
from factory.generate import design as dsn
from factory.generate import transpile

TEMPLATES = ROOT / "factory" / "templates"
GENERATED = ROOT / "generated"
ACCESSOR = {"num": "Num", "str": "Str", "bool": "Bool", "date": "Date", "blank": "Raw"}
DEFAULT_OF = {"DefaultDate": "SelectedDate", "Default": "Text"}
BEHAVIOUR_PROPS = {"OnSelect", "OnVisible", "OnChange", "OnStart", "OnHidden"}
PRESENTATION_FNS = {"RGBA", "ColorValue", "ColorFade"}
PRESENTATION_PROPS = {"Fill", "Color", "BorderColor", "HoverFill", "PressedFill", "FontWeight"}


@dataclass
class Gen:
    method: str
    output: str
    screen: str
    rule_id: str | None
    source: str
    formula: str
    compiled: transpile.Compiled


def _ident(s: str) -> str:
    return re.sub(r"\W", "_", s)


def _cs(s: str | None) -> str:
    return "null" if s is None else json.dumps(s)


def _arr(xs: list[str]) -> str:
    return "[" + ", ".join(_cs(x) for x in xs) + "]"


COLLECTION = "OnStart collection"


def _disposition(site: dict[str, Any], err: str) -> str:
    fns = fxast.functions(site["ast"]) if site.get("ast") else set()
    if site["prop"] in PRESENTATION_PROPS or fns & PRESENTATION_FNS:
        return "presentation: styling, not a business rule; React uses its own design tokens"
    if site["prop"] == "Items" and transpile.string_options(site["ast"]) is not None:
        return "static options: emitted into app.g.ts"
    if err == COLLECTION:
        return "static options: App.OnStart collection literal emitted into app.g.ts"
    if site["prop"] == "Items":
        return "data query: served by the list endpoint; filter/sort is a scenario-tested gap"
    if site["prop"] in BEHAVIOUR_PROPS and "Patch" in fns:
        return "action: generated as an action endpoint (guard + RBAC + persist)"
    return f"unsupported ({err}): routed to scenario/unproven evidence, no code generated"


def formulas(
    model: dict[str, Any], catalogue: dict[str, Any]
) -> tuple[list[Gen], list[dict[str, Any]]]:
    """Compile every pure canvas formula; return them in dependency order plus the rest."""
    rule_of = {loc["path"]: r["id"] for r in catalogue["rules"] for loc in r["source_locations"]}
    gens: list[Gen] = []
    skipped: list[dict[str, Any]] = []
    cols = dsn.collections(model["sites"])
    for s in model["sites"]:
        if s["kind"] != "canvas_property" or not s.get("ast") or not s["screen"]:
            continue
        src = f"{s['file']}:{s['line']}"
        try:
            if s["prop"] in BEHAVIOUR_PROPS:
                raise transpile.UnsupportedError("behaviour property")
            if s["prop"] == "Items" and fxast.dotted(s["ast"]) in cols:
                raise transpile.UnsupportedError(COLLECTION)
            c = transpile.compile_formula(s["ast"])
        except transpile.UnsupportedError as e:
            skipped.append(
                {
                    "path": s["path"],
                    "source": src,
                    "rule_id": rule_of.get(s["path"]),
                    "disposition": _disposition(s, str(e)),
                }
            )
            continue
        gens.append(
            Gen(
                _ident(f"{s['screen']}_{s['control']}_{s['prop']}"),
                f"{s['control']}.{s['prop']}",
                s["screen"],
                rule_of.get(s["path"]),
                src,
                s["formula"],
                c,
            )
        )
    return _order(gens), skipped


def _order(gens: list[Gen]) -> list[Gen]:
    """Topological order: a formula runs after every formula whose output it reads."""
    by_out = {g.output: g for g in gens}
    for g in gens:
        ctrl, _, prop = g.output.rpartition(".")
        if prop in DEFAULT_OF:
            by_out.setdefault(f"{ctrl}.{DEFAULT_OF[prop]}", g)
    done: list[Gen] = []
    state: dict[str, int] = {}

    def visit(g: Gen, stack: list[str]) -> None:
        if state.get(g.method) == 2:
            return
        if state.get(g.method) == 1:
            raise ValueError("formula cycle: " + " -> ".join([*stack, g.output]))
        state[g.method] = 1
        for p in g.compiled.params:
            dep = by_out.get(p.ref)
            if dep is not None and dep is not g:
                visit(dep, [*stack, g.output])
        state[g.method] = 2
        done.append(g)

    for g in sorted(gens, key=lambda x: x.method):
        visit(g, [])
    return done


def _method(name: str, c: transpile.Compiled, doc: list[str]) -> str:
    ret = transpile.CS_TYPE[c.type]
    params = ", ".join(f"{transpile.CS_TYPE[p.type]} {p.name}" for p in c.params)
    lines = [
        f"    /// <summary>{_xml(d)}</summary>" if i == 0 else f"    /// {_xml(d)}"
        for i, d in enumerate(doc)
    ]
    return "\n".join([*lines, f"    public static {ret} {name}({params}) =>", f"        {c.expr};"])


def _xml(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _bind(name: str, c: transpile.Compiled) -> str:
    args = ", ".join(f"e.{ACCESSOR[p.type]}({_cs(p.ref)})" for p in c.params)
    return f"e => Rules.{name}({args})"


def rules_cs(gens: list[Gen], acts: list[dict[str, Any]]) -> str:
    out = [
        "// <auto-generated> by factory.generate.emit from the legacy Power Fx AST. Do not edit.",
        "// Pure functions: no I/O, no clock, no globals. Every method cites its legacy source.",
        "#nullable enable",
        "using Factory.Runtime;",
        "",
        "namespace Factory.Generated;",
        "",
        "public static class Rules",
        "{",
    ]
    body = []
    for g in gens:
        formula = " ".join(g.formula.split())
        doc = [
            f"{g.output} on {g.screen}",
            f"Rule: {g.rule_id or 'none'}; source: {g.source}",
            f"Power Fx: {formula}",
        ]
        body.append(_method(g.method, g.compiled, doc))
    for a in acts:
        for f in a["compiled_fields"]:
            doc = [
                f"{a['table']}.{f['column']} written by {a['screen']}/{a['control']}",
                f"source: {a['source']['file']}:{a['source']['line']}",
            ]
            body.append(_method(f["method"], f["compiled"], doc))
    out.append("\n\n".join(body))
    out += ["}", ""]
    return "\n".join(out)


def _compile_fields(acts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for a in acts:
        a = dict(a)
        a["compiled_fields"] = []
        a["unsupported_fields"] = []
        for col, ast in a["fields"].items():
            try:
                c = transpile.compile_formula(ast)
            except transpile.UnsupportedError as e:
                a["unsupported_fields"].append({"column": col, "reason": str(e)})
                continue
            method = _ident(f"Action_{a['screen']}_{a['control']}_{col}")
            a["compiled_fields"].append({"column": col, "method": method, "compiled": c})
        out.append(a)
    return out


def app_cs(app_id: str, d: dict[str, Any], gens: list[Gen], acts: list[dict[str, Any]]) -> str:
    lines = [
        "// <auto-generated> by factory.generate.emit. Do not edit.",
        "#nullable enable",
        "using Factory.Runtime;",
        "",
        "namespace Factory.Generated;",
        "",
        "public static class App",
        "{",
        f"    public const string Id = {_cs(app_id)};",
        "",
        "    public static readonly ContainerDef[] Containers =",
        "    [",
    ]
    for c in d["containers"]:
        fields = ", ".join(
            f"new({_cs(f['name'])}, {_cs(f['type'])}, "
            f"{str(f['required']).lower()}, {_cs(f['pii'])})"
            for f in c["fields"]
        )
        lines.append(
            f"        new({_cs(c['table'])}, {_cs(c['entity_set'])}, {_cs(c['container'])}, "
            f"{_cs(c['id_field'])}, {_cs(c['partition_key'])}, [{fields}]),"
        )
    lines += [
        "    ];",
        "",
        "    /// <summary>Every compiled formula, in dependency order.</summary>",
        "    public static readonly Formula[] Formulas =",
        "    [",
    ]
    for g in gens:
        lines.append(
            f"        new({_cs(g.output)}, {_cs(g.screen)}, {_cs(g.rule_id)}, {_cs(g.source)}, "
            f"{_arr([p.ref for p in g.compiled.params])}, {_bind(g.method, g.compiled)}),"
        )
    lines += ["    ];", "", "    public static readonly ActionDef[] Actions =", "    ["]
    for a in acts:
        fields = ", ".join(
            f"new({_cs(f['column'])}, {_arr([p.ref for p in f['compiled'].params])}, "
            f"{_bind(f['method'], f['compiled'])})"
            for f in a["compiled_fields"]
        )
        guard = a["guard"].split("/", 1)[1] if a["guard"] else None
        src = f"{a['source']['file']}:{a['source']['line']}"
        lines.append(
            f"        new({_cs(a['screen'])}, {_cs(a['control'])}, {_cs(a['table'])}, "
            f"{_cs(a['operation'])}, {_cs(guard)}, {_cs(a['row'])}, [{fields}], "
            f"{_arr(a['context_fields'])}, {_arr(a['navigates_to'])}, {_cs(src)}),"
        )
    lines += [
        "    ];",
        "",
        "    /// <summary>Legacy Dataverse security roles: role -> table -> privilege -> depth."
        "</summary>",
        "    public static readonly "
        "Dictionary<string, Dictionary<string, Dictionary<string, string>>>"
        " Roles = new()",
        "    {",
    ]
    for role, tables in d["rbac"].items():
        lines.append(f"        [{_cs(role)}] = new()")
        lines.append("        {")
        for t, privs in tables.items():
            ps = ", ".join(f"[{_cs(p)}] = {_cs(v)}" for p, v in privs.items())
            lines.append(f"            [{_cs(t)}] = new() {{ {ps} }},")
        lines.append("        },")
    lines += ["    };", "", "    public static readonly GlobalDef[] Globals =", "    ["]
    for sg in d["session_globals"]:
        lines.append(
            f"        new({_cs(sg['name'])}, {_cs(sg.get('table'))}, "
            f"{_cs(sg.get('match_column'))}, {_cs(sg.get('value_column'))}, "
            f"{_cs(sg.get('reason'))}),"
        )
    lines += ["    ];", "}", ""]
    return "\n".join(lines)


def web_ts(app_id: str, d: dict[str, Any], gens: list[Gen]) -> str:
    outputs = {g.output for g in gens}
    screens = []
    for sc in d["screens"]:
        ctrls = []
        for c in sc["controls"]:
            computed = sorted(
                o.split(".", 1)[1] for o in outputs if o.split(".", 1)[0] == c["name"]
            )
            ctrls.append(
                {
                    **{k: v for k, v in c.items() if k != "source"},
                    "source": f"{c['source']['file']}:{c['source']['line']}",
                    "computed": computed,
                }
            )
        screens.append({"screen": sc["screen"], "controls": ctrls})
    actions = [
        {
            "screen": a["screen"],
            "control": a["control"],
            "table": a["table"],
            "operation": a["operation"],
            "contextFields": a["context_fields"],
            "row": a["row"],
        }
        for a in d["actions"]
    ]
    containers = [
        {
            "table": c["table"],
            "entitySet": c["entity_set"],
            "fields": [f["name"] for f in c["fields"]],
        }
        for c in d["containers"]
    ]
    body = json.dumps(
        {"appId": app_id, "screens": screens, "actions": actions, "containers": containers},
        indent=2,
        ensure_ascii=False,
    )
    return (
        "// <auto-generated> by factory.generate.emit from the legacy canvas app. Do not edit.\n"
        'import type { AppDefinition } from "./types";\n\n'
        f"export const app: AppDefinition = {body};\n"
    )


# The Cosmos emulator's key is public and identical on every install (documented by
# Microsoft); it only works against the local emulator container.
EMULATOR_KEY = (
    "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="
)


def compose(app_id: str) -> str:
    return f"""# <auto-generated> by factory.generate.emit. Do not edit.
# Offline:  docker compose up --build             (file-backed store, no cloud)
# Cosmos:   docker compose --profile cosmos up --build api-cosmos cosmos web
name: {app_id}
services:
  api:
    build: {{ context: ./src, dockerfile: Api/Dockerfile }}
    environment:
      Identity__Mode: demo
      Store__Kind: file
    ports: ["8080:8080"]
    volumes: ["api-data:/data"]
  web:
    build: ./web
    ports: ["5173:8080"]
    depends_on: [api]
  cosmos:
    profiles: [cosmos]
    image: mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator:vnext-preview
    command: ["--protocol", "http"]
    ports: ["8081:8081"]
  api-cosmos:
    profiles: [cosmos]
    build: {{ context: ./src, dockerfile: Api/Dockerfile }}
    environment:
      Identity__Mode: demo
      Store__Kind: cosmos
      Store__Emulator: "true"
      Store__Database: {app_id}
      Store__CosmosConnectionString: "{{CONN}}"  # gitleaks:allow
    ports: ["8080:8080"]
    depends_on: [cosmos]
volumes:
  api-data: {{}}
""".replace("{CONN}", f"AccountEndpoint=http://cosmos:8081/;AccountKey={EMULATOR_KEY}")


def _copy_tree(src: Path, dst: Path) -> None:
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src).parts
        if p.is_file() and not {"node_modules", "dist", "bin", "obj"} & set(rel):
            t = dst / p.relative_to(src)
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, t)


def emit(app_id: str, model: dict[str, Any], catalogue: dict[str, Any]) -> dict[str, Any]:
    from factory.generate import infra

    d = dsn.design(model, catalogue)
    decisions = ROOT / "factory" / "fixtures" / app_id / "rbac-decisions.json"
    d["rbac_decisions"] = []
    if decisions.exists():
        for dec in json.loads(decisions.read_text())["decisions"]:
            role = d["rbac"].setdefault(dec["role"], {})
            role.setdefault(dec["table"], {})[dec["privilege"]] = dec["depth"]
            role[dec["table"]] = dict(sorted(role[dec["table"]].items()))
            d["rbac_decisions"].append(dec)
    gens, skipped = formulas(model, catalogue)
    acts = _compile_fields(d["actions"])
    out = GENERATED / app_id
    for sub in ("src", "web/src", "infra", "design"):
        if (out / sub).exists():
            shutil.rmtree(out / sub)
    _copy_tree(TEMPLATES / "dotnet", out / "src")
    _copy_tree(TEMPLATES / "web", out / "web")
    (out / "web" / "src").mkdir(parents=True, exist_ok=True)
    gen_dir = out / "src" / "Domain" / "Generated"
    gen_dir.mkdir(parents=True, exist_ok=True)
    (gen_dir / "Rules.g.cs").write_text(rules_cs(gens, acts))
    (gen_dir / "App.g.cs").write_text(app_cs(app_id, d, gens, acts))
    (out / "web" / "src" / "app.g.ts").write_text(web_ts(app_id, d, gens))
    seed = ROOT / "factory" / "fixtures" / app_id / "seed.json"
    if seed.exists():
        shutil.copyfile(seed, out / "src" / "Api" / "seed.json")
    (out / "docker-compose.yml").write_text(compose(app_id))
    (out / "infra").mkdir(parents=True, exist_ok=True)
    (out / "infra" / "main.bicep").write_text(infra.bicep(app_id, d))
    d["generated"] = {
        "formulas": [
            {
                "output": g.output,
                "screen": g.screen,
                "rule_id": g.rule_id,
                "method": f"Rules.{g.method}",
                "source": g.source,
            }
            for g in gens
        ],
        "not_compiled": skipped,
        "action_fields_not_compiled": [
            {"action": f"{a['screen']}/{a['control']}", **u}
            for a in acts
            for u in a["unsupported_fields"]
        ],
    }
    (out / "design").mkdir(parents=True, exist_ok=True)
    (out / "design" / "design.json").write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    spec = json.dumps(d["openapi"], indent=2) + "\n"
    (out / "design" / "openapi.json").write_text(spec)
    (out / "src" / "Api" / "openapi.json").write_text(spec)
    return d

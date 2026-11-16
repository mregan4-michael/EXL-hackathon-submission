"""Differential parity: generated C# vs the Microsoft Power Fx interpreter (the oracle).

freeze: generate inputs from the legacy AST, evaluate each with the oracle, write the frozen
        test set parity/testset/<app>.jsonl (expected values are the oracle's, never the C#'s).
run:    re-evaluate the frozen set with the oracle (drift check), evaluate it with the
        generated C# (the same Formula.Eval the API calls), compare, run mutation analysis on
        the oracle to measure how sharp the test set is, and classify every catalogue rule as
        executed / scenario / unproven / failed. Writes parity/reports/<app>/.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from factory.analyse import fxast
from factory.common import fxhost
from factory.common.paths import OUT, REPO_ROOT
from factory.generate import emit
from factory.generate.transpile import BOOL, DATE, NUM, STR, Param
from factory.parity import cases as gen

PARITY = REPO_ROOT / "parity"
# Canvas-host semantics the canvas-free interpreter lacks; applied to the oracle only, listed in
# every report. DisplayMode is a canvas enum (string-valued). Canvas IsMatch defaults to
# MatchOptions.Complete; Microsoft.PowerFx.Interpreter 1.8.1 defaults to Contains.
CANVAS_ENUMS = {"DisplayMode": {"Edit": "Edit", "Disabled": "Disabled", "View": "View"}}
LOCK = PARITY / "testset" / "TESTSET.lock"
HOST_SHIMS = [
    "DisplayMode enum bound as a record of its string values",
    "two-argument IsMatch made explicit as IsMatch(text, pattern, MatchOptions.Complete)",
]
KIND_REASON = {
    "table_column": (
        "Dataverse column constraint: emitted as container field metadata, no executable check"
    ),
    "security_role": "security role: generated RBAC table; no journey check exercises this role",
    "flow_trigger": "Power Automate flow: not generated (Durable Functions hosting decision only)",
    "flow_action": "Power Automate flow: not generated (Durable Functions hosting decision only)",
    "app_onstart": "App.OnStart side effects: no journey check exercises them",
}
BLANK_TYPE = {NUM: "number", STR: "string", BOOL: "bool", DATE: "date"}
OPS = {
    "Less": ("<", "<="),
    "LessEqual": ("<=", "<"),
    "Greater": (">", ">="),
    "GreaterEqual": (">=", ">"),
    "Equal": ("=", "<>"),
    "NotEqual": ("<>", "="),
    "And": ("&&", "||"),
    "Or": ("||", "&&"),
}
TOKEN = re.compile(r"<=|>=|<>|&&|\|\||<|>|=|\bAnd\b|\bOr\b")
WORD = {"And": "&&", "Or": "||"}


@dataclass
class Entry:
    output: str
    screen: str
    path: str
    rule_id: str | None
    source: str
    formula: str
    ast: dict[str, Any]
    params: list[Param]

    @property
    def sha(self) -> str:
        return hashlib.sha256(self.formula.encode()).hexdigest()[:16]

    @property
    def oracle_formula(self) -> str:
        return canvas_host(self.formula, self.ast)


def canvas_host(formula: str, ast: dict[str, Any]) -> str:
    """Make canvas-host defaults explicit for the interpreter (see HOST_SHIMS)."""
    ins = [
        n["e"] - 1
        for n in fxast.walk(ast)
        if n["k"] == "Call"
        and n["fn"] == "IsMatch"
        and len(n["args"]) == 2
        and formula[n["e"] - 1] == ")"
    ]
    for i in sorted(ins, reverse=True):
        formula = formula[:i] + ", MatchOptions.Complete" + formula[i:]
    return formula


def entries(model: dict[str, Any], catalogue: dict[str, Any]) -> list[Entry]:
    gens, _ = emit.formulas(model, catalogue)
    site = {
        (s["screen"], f"{s['control']}.{s['prop']}"): s
        for s in model["sites"]
        if s["kind"] == "canvas_property" and s.get("ast") and s["screen"]
    }
    out = []
    for g in gens:
        s = site[(g.screen, g.output)]
        out.append(
            Entry(
                g.output,
                g.screen,
                s["path"],
                g.rule_id,
                g.source,
                g.formula,
                s["ast"],
                g.compiled.params,
            )
        )
    return sorted(out, key=lambda e: e.path)


# ---------------------------------------------------------------- oracle
def oracle_vars(params: list[Param], inputs: dict[str, Any]) -> dict[str, Any] | None:
    """Screen state as Power Fx records: {"txtA.Text": "1"} -> txtA = {Text: "1"}."""
    root: dict[str, Any] = {k: dict(v) for k, v in CANVAS_ENUMS.items()}
    for p in params:
        if "()" in p.ref or p.ref.split(".")[0] in {"Self", "Parent"}:
            return None
        v = inputs.get(p.ref)
        val = {"$blank": BLANK_TYPE.get(p.type, "string")} if v is None else v
        parts = p.ref.split(".")
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = val
    return root


def _jsonable(v: Any) -> Any:
    return json.loads(gen.dumps(v))


def oracle_result(
    fx: fxhost.FxHost, formula: str, params: list[Param], inputs: dict[str, Any]
) -> dict[str, Any]:
    env = oracle_vars(params, inputs)
    if env is None:
        return {"unsupported": "reference not representable in the oracle (User()/Self/Parent)"}
    r = fx.eval(formula, _jsonable(env))
    if not r.get("ok"):
        return {"unsupported": str(r.get("error"))[:300]}
    if "error_value" in r:
        return {"error": str(r["error_value"])[:300]}
    return {"value": r.get("value")}


def canon(v: Any) -> Any:
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, int | float | Decimal):
        return ("n", str(Decimal(str(v)).normalize()))
    if isinstance(v, dict) and "$date" in v:
        return ("d", v["$date"])
    if isinstance(v, dict) and "$datetime" in v:
        return ("dt", v["$datetime"])
    return ("?", json.dumps(v, sort_keys=True, default=str))


def outcome(r: dict[str, Any]) -> str:
    """value | error (a Power Fx error value) | unsupported (oracle) | crash (C# non-Fx failure)."""
    if "unsupported" in r:
        return "unsupported"
    if "error" in r:
        return "error" if r.get("kind", "fx") == "fx" else "crash"
    return "value"


def same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ka, kb = outcome(a), outcome(b)
    if ka != kb or ka == "crash":
        return False
    if ka == "value":
        return bool(canon(a.get("value")) == canon(b.get("value")))
    if ka == "unsupported":
        return bool(a["unsupported"] == b["unsupported"])
    return True  # both are Power Fx errors; messages differ between engines by design


# ---------------------------------------------------------------- freeze
def freeze(app: str) -> Path:
    model, catalogue = _load(app)
    rows = []
    with fxhost.FxHost() as fx:
        for e in entries(model, catalogue):
            for i, c in enumerate(gen.generate(f"{app}:{e.path}", e.params, e.ast)):
                rows.append(
                    {
                        "path": e.path,
                        "output": e.output,
                        "formula_sha": e.sha,
                        "case": i,
                        "kind": c["kind"],
                        "inputs": _jsonable(c["inputs"]),
                        "expected": oracle_result(fx, e.oracle_formula, e.params, c["inputs"]),
                    }
                )
    path = PARITY / "testset" / f"{app}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    lock = _lock_entries()
    lock[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    LOCK.write_text("".join(f"{h}  {n}\n" for n, h in sorted(lock.items())))
    return path


def _lock_entries() -> dict[str, str]:
    if not LOCK.exists():
        return {}
    return {n: h for h, n in (x.split() for x in LOCK.read_text().splitlines() if x)}


def verify_lock(app: str) -> None:
    """The frozen test set is immutable outside `--freeze`; TESTSET.lock pins its bytes."""
    path = PARITY / "testset" / f"{app}.jsonl"
    want = _lock_entries().get(path.name)
    got = hashlib.sha256(path.read_bytes()).hexdigest()
    if want != got:
        raise SystemExit(f"{path.name}: sha256 {got} does not match TESTSET.lock ({want})")


def load_testset(app: str) -> list[dict[str, Any]]:
    path = PARITY / "testset" / f"{app}.jsonl"
    if not path.exists():
        return []
    verify_lock(app)
    return [json.loads(x, parse_float=Decimal) for x in path.read_text().splitlines() if x]


# ---------------------------------------------------------------- C#
def run_csharp(app: str, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    proj = REPO_ROOT / "generated" / app / "src" / "Parity"
    bin_dir = OUT / app / "parity-bin"
    subprocess.run(  # noqa: S603
        [fxhost._dotnet(), "build", "-c", "Release", "-v", "q", "-o", str(bin_dir), str(proj)],
        check=True,
        env=fxhost._env(),
        capture_output=True,
    )
    stdin = "".join(json.dumps(r, default=gen._default) + "\n" for r in requests)
    p = subprocess.run(  # noqa: S603
        [fxhost._dotnet(), str(bin_dir / "Factory.Parity.dll")],
        input=stdin,
        text=True,
        capture_output=True,
        env=fxhost._env(),
        check=True,
    )
    by_id = {}
    for line in p.stdout.splitlines():
        r = json.loads(line, parse_float=Decimal)
        by_id[r["id"]] = r
    return [by_id.get(r["id"], {"error": "no response", "kind": "crash"}) for r in requests]


# ---------------------------------------------------------------- mutation
def mutants(formula: str, ast: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for n in fxast.walk(ast):
        if n["k"] == "BinaryOp" and n["op"] in OPS:
            lo, hi = n["l"]["e"], n["r"]["s"]
            seg = formula[lo:hi]
            toks = list(TOKEN.finditer(seg))
            want, repl = OPS[n["op"]]
            if len(toks) == 1 and WORD.get(toks[0].group(), toks[0].group()) == want:
                t = toks[0]
                new = seg[: t.start()] + f" {repl} " + seg[t.end() :]
                out.append((f"{want} -> {repl} @{lo}", formula[:lo] + new + formula[hi:]))
        elif n["k"] in ("NumLit", "DecLit"):
            text = formula[n["s"] : n["e"]]
            try:
                bumped = str(Decimal(text) + 1)
            except ArithmeticError:
                continue
            out.append(
                (f"{text} -> {bumped} @{n['s']}", formula[: n["s"]] + bumped + formula[n["e"] :])
            )
    return out


def mutation(fx: fxhost.FxHost, e: Entry, rows: list[dict[str, Any]]) -> dict[str, Any]:
    killed, survived, invalid = [], [], 0
    for desc, text in mutants(e.formula, e.ast):
        parsed = fx.parse(text)
        if not parsed.get("ok"):
            invalid += 1
            continue
        oracle_text = canvas_host(text, parsed["ast"])
        results = [oracle_result(fx, oracle_text, e.params, r["inputs"]) for r in rows]
        if all("unsupported" in r for r in results):
            invalid += 1
            continue
        if any(
            "unsupported" not in m and not same(m, r["expected"])
            for m, r in zip(results, rows, strict=True)
        ):
            killed.append(desc)
        else:
            survived.append(desc)
    return {"killed": len(killed), "survived": survived, "invalid": invalid}


# ---------------------------------------------------------------- report
def _load(app: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = OUT / app / "legacy-model.json"
    if not path.exists():  # deterministic, so a clean checkout can run parity directly
        from factory.analyse.parse import parse_app, write_model

        with fxhost.FxHost() as fx:
            write_model(parse_app(app, fx))
    model = json.loads(path.read_text())
    catalogue = json.loads((REPO_ROOT / "artefacts" / app / "rule-catalogue.json").read_text())
    return model, catalogue


def run(app: str) -> dict[str, Any]:
    model, catalogue = _load(app)
    es = entries(model, catalogue)
    testset = load_testset(app)
    by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in testset:
        by_path[r["path"]].append(r)

    reqs, owners = [], []
    status: dict[str, dict[str, Any]] = {}
    with fxhost.FxHost() as fx:
        drift = 0
        for e in es:
            rows = by_path.get(e.path, [])
            if not rows:
                status[e.path] = {"status": "unproven", "reason": "not in frozen test set"}
                continue
            if rows[0]["formula_sha"] != e.sha:
                status[e.path] = {
                    "status": "unproven",
                    "reason": "stale: legacy formula changed since freeze",
                }
                continue
            for r in rows:
                if not same(
                    oracle_result(fx, e.oracle_formula, e.params, r["inputs"]), r["expected"]
                ):
                    drift += 1
                reqs.append({"id": f"{e.path}#{r['case']}", "output": e.output, "env": r["inputs"]})
                owners.append((e, r))
        got = run_csharp(app, reqs) if reqs else []

        per: dict[str, Counter[str]] = defaultdict(Counter)
        mismatches: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for (e, r), c in zip(owners, got, strict=True):
            exp = r["expected"]
            if "unsupported" in exp:
                per[e.path]["oracle_unsupported"] += 1
            elif same(c, exp):
                per[e.path]["agree"] += 1
            else:
                per[e.path]["mismatch"] += 1
                if len(mismatches[e.path]) < 3:
                    mismatches[e.path].append(
                        {
                            "case": r["case"],
                            "kind": r["kind"],
                            "inputs": r["inputs"],
                            "oracle": exp,
                            "csharp": {k: c[k] for k in ("value", "error") if k in c},
                        }
                    )
        for e in es:
            if e.path in status:
                continue
            n = per[e.path]
            st = "fail" if n["mismatch"] else "pass" if n["agree"] else "unproven"
            status[e.path] = {"status": st, "cases": dict(sorted(n.items()))}
            if st == "unproven":
                msg = next(
                    (
                        r["expected"]["unsupported"]
                        for r in by_path[e.path]
                        if "unsupported" in r["expected"]
                    ),
                    "",
                )
                status[e.path][
                    "reason"
                ] = f"oracle cannot evaluate in a canvas-free host: {_brief(msg)}"
            if mismatches[e.path]:
                status[e.path]["mismatches"] = mismatches[e.path]
            if e.params and st in ("pass", "fail"):
                status[e.path]["mutation"] = mutation(fx, e, by_path[e.path])

    report = _report(app, catalogue, es, status, drift, len(reqs))
    _write(app, report, es)
    return report


def _brief(msg: str) -> str:
    """First oracle diagnostic without its source position."""
    m = re.search(r"Error \d+-\d+: ([^\r\n]+?)(?:\r|\n|$)", msg)
    return (m.group(1) if m else msg)[:120]


def _scenarios(app: str) -> list[dict[str, Any]]:
    p = PARITY / "scenarios" / f"{app}.json"
    return list(json.loads(p.read_text())["checks"]) if p.exists() else []


def _report(
    app: str,
    catalogue: dict[str, Any],
    es: list[Entry],
    status: dict[str, dict[str, Any]],
    drift: int,
    n_cases: int,
) -> dict[str, Any]:
    _, skipped = emit.formulas(*_load(app))
    skipped_by = {s["path"]: s["disposition"] for s in skipped}
    scen: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    for c in _scenarios(app):
        for p in c["paths"]:
            scen[p].append((c["name"], bool(c["ok"])))

    rules = []
    for r in catalogue["rules"]:
        locs = []
        for loc in r["source_locations"]:
            p = loc["path"]
            failed_checks = [n for n, o in scen.get(p, []) if not o]
            if failed_checks:  # a failing journey check outranks any formula-level pass
                locs.append({"path": p, "evidence": "scenario_fail", "checks": failed_checks})
            elif p in status:
                locs.append({"path": p, "evidence": status[p]["status"]})
            elif p in scen:
                ok = all(o for _, o in scen[p])
                locs.append(
                    {
                        "path": p,
                        "evidence": "scenario" if ok else "scenario_fail",
                        "checks": [n for n, _ in scen[p]],
                    }
                )
            else:
                why = skipped_by.get(p) or KIND_REASON.get(
                    loc.get("kind", ""), "no generated formula or journey check"
                )
                locs.append({"path": p, "evidence": "unproven", "reason": why})
        ev = {x["evidence"] for x in locs}
        if ev & {"fail", "scenario_fail"}:
            cls = "failed"
        elif "pass" in ev:
            cls = "executed"
        elif "scenario" in ev:
            cls = "scenario"
        else:
            cls = "unproven"
        rules.append(
            {
                "id": r["id"],
                "statement": r["statement"],
                "class": cls,
                "declared": r["oracle"]["proof_type"],
                "covered": sum(x["evidence"] in ("pass", "scenario") for x in locs),
                "locations": locs,
            }
        )

    muts = [s["mutation"] for s in status.values() if "mutation" in s]
    killed = sum(m["killed"] for m in muts)
    total = killed + sum(len(m["survived"]) for m in muts)
    fstat = Counter(s["status"] for s in status.values())
    linked = [e for e in es if e.rule_id]
    return {
        "app": app,
        "oracle": "Microsoft.PowerFx.Interpreter 1.8.1 (tools/fxhost)",
        "host_shims": HOST_SHIMS,
        "frozen_cases": n_cases,
        "oracle_drift": drift,
        "formulas": {
            "total": len(es),
            **dict(sorted(fstat.items())),
            "rule_linked": len(linked),
            "rule_linked_pass": sum(status[e.path]["status"] == "pass" for e in linked),
        },
        "not_compiled": len(skipped),
        "unproven_reasons": dict(
            Counter(s["reason"] for s in status.values() if s["status"] == "unproven").most_common()
        ),
        "mutation": {
            "formulas": len(muts),
            "killed": killed,
            "total": total,
            "score": round(killed / total, 4) if total else None,
        },
        "rules": {"total": len(rules), **dict(sorted(Counter(r["class"] for r in rules).items()))},
        "rule_evidence": rules,
        "formula_results": dict(sorted(status.items())),
    }


def _write(app: str, rep: dict[str, Any], es: list[Entry]) -> None:
    d = PARITY / "reports" / app
    d.mkdir(parents=True, exist_ok=True)
    (d / "parity-report.json").write_text(
        json.dumps(rep, indent=2, sort_keys=True, default=gen._default) + "\n"
    )
    f, m, rl = rep["formulas"], rep["mutation"], rep["rules"]
    lines = [
        f"# Parity report: {app}",
        "",
        "Generated by `factory parity`. Oracle: Microsoft Power Fx interpreter evaluating",
        "the *legacy* "
        "formula; subject: the generated C# `Formula.Eval` (same code path as the API).",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Frozen test cases | {rep['frozen_cases']} |",
        f"| Oracle drift vs frozen expectations | {rep['oracle_drift']} |",
        f"| Compiled formulas | {f['total']} |",
        f"| pass / fail / unproven | {f.get('pass', 0)} / {f.get('fail', 0)} / "
        f"{f.get('unproven', 0)} |",
        f"| Rule-linked formulas passing | {f['rule_linked_pass']} / {f['rule_linked']} |",
        f"| Formulas not compiled (routed, no code) | {rep['not_compiled']} |",
        f"| Mutation score (oracle mutants killed by the test set) | {m['killed']} / {m['total']}"
        f" ({m['score']}) over {m['formulas']} formulas |",
        f"| Rules executed / scenario / unproven / failed | {rl.get('executed', 0)} / "
        f"{rl.get('scenario', 0)} / {rl.get('unproven', 0)} / {rl.get('failed', 0)} "
        f"of {rl['total']} |",
        "",
        *(
            ["Unproven formulas by reason:", ""]
            + [f"- {n} x {r}" for r, n in rep["unproven_reasons"].items()]
            + [""]
            if rep["unproven_reasons"]
            else []
        ),
        "Oracle host shims (canvas semantics the interpreter lacks): "
        + "; ".join(rep["host_shims"])
        + ".",
        "",
        "Evidence classes: **executed** = at least one source location is a generated formula that",
        "agreed with the oracle on every frozen case; **scenario** = covered only by a passing",
        "end-to-end journey check; **unproven** = no executed or scenario evidence (reason given);",
        "**failed** = a mismatch or failing journey check.",
        "",
    ]
    fails = {p: s for p, s in rep["formula_results"].items() if s["status"] == "fail"}
    if fails:
        lines += ["## Mismatches", ""]
        for p, s in fails.items():
            lines.append(f"- `{p}` {s['cases']}")
            for mm in s.get("mismatches", []):
                lines.append(
                    f"  - inputs `{gen.dumps(mm['inputs'])}`: oracle `{gen.dumps(mm['oracle'])}`,"
                    f" C# `{gen.dumps(mm['csharp'])}`"
                )
        lines.append("")
    lines += [
        "## Rules",
        "",
        "| Rule | Achieved | Declared in catalogue | Covered locations | Gap |",
        "|---|---|---|---|---|",
    ]
    for r in rep["rule_evidence"]:
        gap = "; ".join(sorted({x["reason"] for x in r["locations"] if "reason" in x}))
        lines.append(
            f"| {r['id']} | {r['class']} | {r['declared']} | "
            f"{r['covered']}/{len(r['locations'])} | {gap} |"
        )
    surv = [
        (p, s["mutation"]["survived"])
        for p, s in rep["formula_results"].items()
        if s.get("mutation", {}).get("survived")
    ]
    if surv:
        lines += ["", "## Surviving mutants (test-set blind spots or equivalent mutants)", ""]
        lines += [f"- `{p}`: {', '.join(sv)}" for p, sv in surv]
    (d / "parity-report.md").write_text("\n".join(lines) + "\n")
    (d / "parity-report.html").write_text(_html(rep))


_CLS = {"executed": "#1b7f3b", "scenario": "#1f5fa8", "unproven": "#8a6d00", "failed": "#b3261e"}


def _html(rep: dict[str, Any]) -> str:
    e = html.escape
    f, m, rl = rep["formulas"], rep["mutation"], rep["rules"]
    summary = [
        ("Frozen test cases", rep["frozen_cases"]),
        ("Oracle drift vs frozen expectations", rep["oracle_drift"]),
        ("Compiled formulas pass / fail / unproven",
         f"{f.get('pass', 0)} / {f.get('fail', 0)} / {f.get('unproven', 0)} of {f['total']}"),
        ("Formulas not compiled (routed, no code)", rep["not_compiled"]),
        ("Mutation score", f"{m['killed']} / {m['total']} over {m['formulas']} formulas"),
        *[(f"Rules {k}", rl.get(k, 0)) for k in _CLS],
    ]  # fmt: skip
    rows = "".join(f"<tr><th>{e(k)}</th><td>{e(str(v))}</td></tr>" for k, v in summary)
    rules = "".join(
        f"<tr><td>{e(r['id'])}</td><td style='color:{_CLS[r['class']]}'><b>{r['class']}</b></td>"
        f"<td>{e(r['statement'])}</td><td>{r['covered']}/{len(r['locations'])}</td><td>"
        + e("; ".join(sorted({x["reason"] for x in r["locations"] if "reason" in x})))
        + "</td></tr>"
        for r in rep["rule_evidence"]
    )
    forms = "".join(
        f"<tr><td><code>{e(p)}</code></td><td>{s['status']}</td>"
        f"<td>{e(gen.dumps(s.get('cases', {})))}</td>"
        f"<td>{e(', '.join(s.get('mutation', {}).get('survived', [])) or s.get('reason', ''))}"
        "</td></tr>"
        for p, s in rep["formula_results"].items()
    )
    reasons = "".join(f"<li>{n} x {e(r)}</li>" for r, n in rep["unproven_reasons"].items())
    return (
        "<!doctype html><html lang=en><meta charset=utf-8>"
        f"<title>Parity report: {e(rep['app'])}</title><style>"
        "body{font:14px system-ui,sans-serif;margin:2rem;max-width:1200px}"
        "table{border-collapse:collapse;margin:1rem 0}td,th{border:1px solid #ccc;"
        "padding:4px 8px;text-align:left;vertical-align:top}code{font-size:12px}</style>"
        f"<h1>Parity report: {e(rep['app'])}</h1><p>Oracle: {e(rep['oracle'])} evaluating the "
        "<em>legacy</em> formula. Subject: generated C# <code>Formula.Eval</code> (the API code "
        "path). Every number is measured by <code>factory parity</code>; nothing is estimated."
        f"</p><table>{rows}</table><p>Host shims: {e('; '.join(rep['host_shims']))}.</p>"
        f"<h2>Unproven formulas by reason</h2><ul>{reasons}</ul>"
        "<h2>Rules</h2><table><tr><th>Rule</th><th>Evidence</th><th>Statement</th>"
        f"<th>Covered</th><th>Gap</th></tr>{rules}</table>"
        "<h2>Formulas</h2><table><tr><th>Path</th><th>Status</th><th>Cases</th>"
        f"<th>Surviving mutants / reason</th></tr>{forms}</table></html>\n"
    )

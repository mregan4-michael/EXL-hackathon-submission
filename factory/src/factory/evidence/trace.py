"""Traceability matrix: legacy source -> BR-xxx -> design -> generated code -> test -> parity.

Built only from committed artefacts; nothing here is hand-written per rule.
"""

from __future__ import annotations

import html
import json
from typing import Any

from factory.common.paths import REPO_ROOT

ART = REPO_ROOT / "artefacts"


def _j(path: str) -> dict[str, Any]:
    return dict(json.loads((REPO_ROOT / path).read_text()))


def load(app: str) -> dict[str, dict[str, Any]]:
    return {
        "catalogue": _j(f"artefacts/{app}/rule-catalogue.json"),
        "analysis": _j(f"artefacts/{app}/analysis-report.json"),
        "design": _j(f"generated/{app}/design/design.json"),
        "parity": _j(f"parity/reports/{app}/parity-report.json"),
    }


def _targets(design: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Legacy path -> where the migrated behaviour lives."""
    out: dict[str, dict[str, str]] = {}
    g = design["generated"]
    for f in g["formulas"]:
        out[f"{f['screen']}/{f['output']}"] = {
            "kind": "domain formula",
            "code": f"generated/{design['app_id']}/src/Domain/Generated/Rules.g.cs",
            "symbol": f["method"],
        }
    for a in design["actions"]:
        out[a["source"]["path"]] = {
            "kind": f"API action ({a['operation']} {a['table']})",
            "code": f"generated/{design['app_id']}/src/Api/Program.cs",
            "symbol": f"{a['screen']}/{a['control']}",
        }
    for n in g["not_compiled"]:
        out.setdefault(n["path"], {"kind": "not compiled", "code": "", "symbol": n["disposition"]})
    for fl in design["flows"]:
        out.setdefault(
            f"flow:{fl['flow']}", {"kind": fl["hosting"], "code": "", "symbol": "design only"}
        )
    return out


def matrix(app: str) -> dict[str, Any]:
    a = load(app)
    targets = _targets(a["design"])
    ev = {r["id"]: r for r in a["parity"]["rule_evidence"]}
    fr = a["parity"]["formula_results"]
    rows = []
    for r in a["catalogue"]["rules"]:
        links = []
        for loc in r["source_locations"]:
            p = loc["path"]
            t = targets.get(p) or targets.get(f"flow:{p.split('/')[0]}")
            res = fr.get(p, {})
            links.append(
                {
                    "source": f"{loc['file']}:{loc['line']}",
                    "path": p,
                    "target": t or {"kind": "no generated target", "code": "", "symbol": ""},
                    "parity_cases": sum(res.get("cases", {}).values()),
                    "formula_status": res.get("status"),
                }
            )
        e = ev.get(r["id"], {})
        rows.append(
            {
                "id": r["id"],
                "statement": r["statement"],
                "category": r["category"],
                "confidence": r["confidence"],
                "links": links,
                "evidence": e.get("class", "unproven"),
                "scenario_checks": sorted(
                    {c for loc in e.get("locations", []) for c in loc.get("checks", [])}
                ),
                "needs_human_review": r["flags"]["needs_human_review"],
                "review_reasons": r["flags"]["review_reasons"],
                # Migrated only if every source location maps to generated code; design-only
                # flow hosting and not-compiled formulas do not count.
                "auto_migrated": bool(links) and all(x["target"]["code"] for x in links),
            }
        )
    return {"app": app, "rules": rows}


def write(app: str) -> None:
    m = matrix(app)
    d = ART / app
    (d / "traceability-matrix.json").write_text(json.dumps(m, indent=1) + "\n")
    e = html.escape
    body = []
    for r in m["rules"]:
        parts = []
        for x in r["links"]:
            t = x["target"]
            cell = f"<code>{e(x['source'])}</code> → {e(t['kind'])} <code>{e(t['symbol'])}</code>"
            if x["parity_cases"]:
                cell += f" · {x['parity_cases']} cases ({e(str(x['formula_status']))})"
            parts.append(cell)
        review = "yes: " + "; ".join(r["review_reasons"]) if r["needs_human_review"] else "no"
        checks = "; ".join(r["scenario_checks"])
        body.append(
            f"<tr class={e(r['evidence'])}><td>{e(r['id'])}</td><td>{e(r['statement'])}</td>"
            f"<td>{'<br>'.join(parts)}</td><td>{e(r['evidence'])}<br><small>{e(checks)}"
            f"</small></td><td>{e(review)}</td></tr>"
        )
    (d / "traceability-matrix.html").write_text(
        "<!doctype html><html lang=en><meta charset=utf-8>"
        f"<title>Traceability: {e(app)}</title><style>body{{font:13px system-ui;margin:2em}}"
        "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px;vertical-align:top}"
        ".executed td:nth-child(4){background:#d7f5dd}.scenario td:nth-child(4){background:#dde8ff}"
        ".failed td:nth-child(4){background:#ffd6d6}.unproven td:nth-child(4){background:#fff3c4}"
        "</style>"
        f"<h1>Traceability matrix: {e(app)}</h1><p>Generated by <code>factory evidence</code> from "
        "rule-catalogue.json, design.json and parity-report.json. Legacy source → rule → "
        "generated target → parity evidence.</p><table><tr><th>Rule</th><th>Statement</th>"
        "<th>Source → target · parity cases</th><th>Evidence</th><th>Human review</th></tr>"
        + "".join(body)
        + "</table></html>\n"
    )

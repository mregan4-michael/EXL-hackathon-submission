"""One-variable experiments on the analysis stage, scored on a tuning app and a held-out app.

Protocol (ADR-013):
- Tuning app = approvals-kit (real, has locked ground truth). Held-out = claims-workbench
  (synthetic, authored separately). Only the held-out *aggregate* score is stored or printed;
  its per-rule catalogue goes to the git-ignored factory/out/experiments/ and is never read.
- Each run changes one variable (interpret prompt version or candidate policy version) relative
  to its parent. Prompts and policies are versioned, never edited in place.
- Kept iff the tuning score is strictly higher than the parent's; otherwise reverted. The
  decision is computed, not chosen.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from factory.analyse import rules
from factory.analyse.catalogue import build_catalogue, load_prompt
from factory.common.llm import LLMClient
from factory.common.paths import OUT, PROMPTS, REPO_ROOT
from factory.improve import score

TUNING, HELDOUT = "approvals-kit", "claims-workbench"
RUNS = REPO_ROOT / "experiments" / "runs"
# A run name is its file stem: no separators, dots or suffixes that could alias another file.
RUN_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]*")
CRITIC_PROMPT = "critic.v1"


def _model(app: str) -> dict[str, Any]:
    path = OUT / app / "legacy-model.json"
    if not path.exists():
        from factory.analyse.parse import parse_app, write_model
        from factory.common import fxhost

        with fxhost.FxHost() as fx:
            write_model(parse_app(app, fx))
    return dict(json.loads(path.read_text()))


def _analyse(name: str, app: str, interpret: str, policy: str, replay: bool) -> dict[str, Any]:
    out = OUT / "experiments" / name / app
    out.mkdir(parents=True, exist_ok=True)
    llm = LLMClient(audit_path=out / "audit.jsonl", stage=f"experiment:{name}", replay=replay)
    cat, rep = build_catalogue(_model(app), llm, interpret, policy_version=policy)
    (out / "rule-catalogue.json").write_text(json.dumps(cat, indent=2) + "\n")
    (out / "analysis-report.json").write_text(json.dumps(rep, indent=2) + "\n")
    return score.components(app, cat, rep, score.parity_report(app))


def load_runs() -> list[dict[str, Any]]:
    paths = sorted(p for p in RUNS.glob("*.json") if not p.name.endswith(".critique.json"))
    return [json.loads(p.read_text()) for p in paths]


def run(
    name: str | None, interpret: str, policy: str, hypothesis: str, parent: str | None, replay: bool
) -> dict[str, Any]:
    if not name:
        raise SystemExit("experiment run needs a NAME")
    load_prompt(interpret)
    if policy not in rules.POLICIES:
        raise SystemExit(f"unknown candidate policy {policy}")
    if not RUN_NAME.fullmatch(name):
        raise SystemExit(f"{name!r}: run names may only use letters, digits, '-' and '_'")
    prev = {r["name"]: r for r in load_runs()}
    if name in prev or (RUNS / f"{name}.json").exists():
        raise SystemExit(f"{name}: already recorded; results are append-only, pick a new name")
    if parent is not None:
        if parent not in prev:
            raise SystemExit(f"{name}: unknown parent {parent}")
        if prev[parent].get("decision") == "reverted":
            raise SystemExit(f"{name}: parent {parent} was reverted; branch from a kept run")
        p = prev[parent]["config"]
        changed = [
            k for k, v in {"interpret": interpret, "candidates": policy}.items() if p[k] != v
        ]
        if len(changed) != 1:
            raise SystemExit(f"{name}: must change exactly one variable vs {parent}, got {changed}")
    tuning = _analyse(name, TUNING, interpret, policy, replay)
    held = _analyse(name, HELDOUT, interpret, policy, replay)
    t = score.total(tuning)
    base = prev[parent]["tuning"]["score"] if parent else None
    result = {
        "name": name,
        "parent": parent,
        "config": {"interpret": interpret, "candidates": policy},
        "hypothesis": hypothesis,
        "tuning": {"app": TUNING, "score": t, "components": tuning},
        # Aggregate only: the held-out score is reported, never used to choose or tune.
        "heldout": {"app": HELDOUT, "score": score.total(held)},
        "decision": "baseline" if base is None else ("kept" if t > base else "reverted"),
    }
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / f"{name}.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def replay_all() -> list[str]:
    """Re-execute every recorded run from the LLM cache; return runs whose scores changed."""
    bad = []
    for r in load_runs():
        c = r["config"]
        t = score.total(_analyse(r["name"], TUNING, c["interpret"], c["candidates"], True))
        h = score.total(_analyse(r["name"], HELDOUT, c["interpret"], c["candidates"], True))
        if (t, h) != (r["tuning"]["score"], r["heldout"]["score"]):
            bad.append(f"{r['name']}: tuning {t} vs {r['tuning']['score']}, held-out {h} vs "
                       f"{r['heldout']['score']}")  # fmt: skip
    return bad


def failure_summary(name: str) -> dict[str, Any]:
    """Aggregate tuning-app failures for the critic (tuning app only, by construction)."""
    d = OUT / "experiments" / name / TUNING
    cat = json.loads((d / "rule-catalogue.json").read_text())
    rep = json.loads((d / "analysis-report.json").read_text())
    gt = score.ground_truth(TUNING) or set()
    found = {(loc["file"], loc["path"]) for r in cat["rules"] for loc in r["source_locations"]}
    rejected = {x["path"] for x in rep["rejected_by_model"]}
    missed = sorted(gt - found)
    reasons: dict[str, int] = {}
    for r in cat["rules"]:
        for why in r["flags"]["review_reasons"]:
            k = why.split(":")[0].split("<")[0]
            reasons[k] = reasons.get(k, 0) + 1
    return {
        "app": TUNING,
        "rules": len(cat["rules"]),
        "missed_ground_truth": len(missed),
        "missed_because_model_said_not_a_business_rule": sum(p in rejected for _, p in missed),
        "missed_examples": [p for _, p in missed][:10],
        "review_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "components": score.components(TUNING, cat, rep, score.parity_report(TUNING)),
    }


def critique(name: str, replay: bool) -> dict[str, Any]:
    summary = failure_summary(name)
    system = (PROMPTS / "improve" / f"{CRITIC_PROMPT}.md").read_text()
    llm = LLMClient(
        audit_path=OUT / "experiments" / name / "critic-audit.jsonl",
        stage=f"critic:{name}",
        replay=replay,
    )
    msgs = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(summary, indent=1)},
    ]
    proposal = llm.chat(msgs, CRITIC_PROMPT)
    out = {"run": name, "prompt": CRITIC_PROMPT, "summary": summary, "proposal": proposal}
    (RUNS / f"{name}.critique.json").write_text(json.dumps(out, indent=2) + "\n")
    return out


def leaderboard() -> Path:
    runs = load_runs()
    by = {r["name"]: r for r in runs}
    keys = list(score.WEIGHTS)
    lines = [
        "# Leaderboard (Phase 5 self-improvement)",
        "",
        "Generated by `factory experiment leaderboard` from `experiments/runs/*.json`; "
        "`make improve` replays every run from the LLM cache and fails if any score moves.",
        f"Tuning app: `{TUNING}` (locked ground truth). Held-out app: `{HELDOUT}` "
        "(aggregate score only; never used for a decision). Objective: `docs/scoring.md`.",
        "",
        "| Iteration | Change (one variable) | Tuning score | Δ vs parent | Held-out score | "
        "Decision | Rationale (measured) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in runs:
        par = by.get(r["parent"]) if r["parent"] else None
        t = r["tuning"]
        if par:
            pc = par["tuning"]["components"]
            moved = [
                f"{k} {pc.get(k, 0):.4f}→{t['components'].get(k, 0):.4f}"
                for k in keys
                if pc.get(k) != t["components"].get(k)
            ]
            delta = f"{t['score'] - par['tuning']['score']:+.4f}"
            change = ", ".join(
                f"{k} {par['config'][k]}→{v}"
                for k, v in r["config"].items()
                if par["config"][k] != v
            )
        else:
            moved, delta = [], "—"
            change = f"baseline ({r['config']['interpret']}, {r['config']['candidates']})"
        why = r["hypothesis"] + (" Measured: " + "; ".join(moved) + "." if moved else "")
        if par and r["decision"] == "kept" and r["heldout"]["score"] < par["heldout"]["score"]:
            why += (
                f" **Held-out fell {r['heldout']['score'] - par['heldout']['score']:+.4f}:"
                " the tuning gain did not generalise to the held-out app.**"
            )
        lines.append(
            f"| {r['name']} | {change} | {t['score']:.4f} | {delta} | {r['heldout']['score']:.4f} "
            f"| {r['decision']} | {why} |"
        )
    path = REPO_ROOT / "experiments" / "leaderboard.md"
    path.write_text("\n".join(lines) + "\n")
    return path

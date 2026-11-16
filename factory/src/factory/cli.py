"""Factory command-line entry point."""

from __future__ import annotations

import argparse
import collections
import sys

from factory import __version__


def _cmd_parse(args: argparse.Namespace) -> int:
    from factory.analyse.parse import parse_app, write_model
    from factory.common.fxhost import FxHost

    with FxHost() as fx:
        for app in args.app:
            model = parse_app(app, fx)
            path = write_model(model)
            kinds = collections.Counter(s.kind for s in model.sites)
            fx_sites = [s for s in model.sites if s.language == "powerfx"]
            ok = sum(1 for s in fx_sites if not s.parse_errors)
            print(
                f"{app}: {len(model.sites)} sites {dict(kinds)}; {len(model.tables)} tables; "
                f"{len(model.flows)} flows; powerfx parsed {ok}/{len(fx_sites)} -> {path}"
            )
    return 0


def _cmd_analyse(args: argparse.Namespace) -> int:
    import json

    from factory.analyse.catalogue import build_catalogue, write
    from factory.analyse.parse import parse_app, write_model
    from factory.common.fxhost import FxHost
    from factory.common.llm import LLMClient
    from factory.common.paths import OUT

    for app in args.app:
        model_path = OUT / app / "legacy-model.json"
        if not model_path.exists():
            with FxHost() as fx:
                write_model(parse_app(app, fx))
        model = json.loads(model_path.read_text())
        llm = LLMClient(audit_path=OUT / app / "audit.jsonl", stage="analyse", replay=args.replay)
        catalogue, report = build_catalogue(model, llm, args.prompt, workers=args.workers)
        path = write(app, catalogue, report)
        review = sum(1 for r in catalogue["rules"] if r["flags"]["needs_human_review"])
        print(
            f"{app}: {report['candidates']} candidates -> {report['rules']} rules "
            f"({len(report['rejected_by_model'])} rejected, {review} need review); "
            f"llm calls {llm.stats['calls']:.0f}, cache hits {llm.stats['cache_hits']:.0f}, "
            f"tokens {llm.stats['tokens']:.0f}, {llm.stats['seconds']:.1f}s -> {path}"
        )
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    import json

    from factory.common.paths import OUT, REPO_ROOT
    from factory.generate.emit import GENERATED, emit

    for app in args.app:
        model = json.loads((OUT / app / "legacy-model.json").read_text())
        catalogue = json.loads((REPO_ROOT / "artefacts" / app / "rule-catalogue.json").read_text())
        d = emit(app, model, catalogue)
        g = d["generated"]
        print(
            f"{app}: {len(d['containers'])} containers, {len(g['formulas'])} compiled formulas, "
            f"{len(g['not_compiled'])} not compiled, {len(d['actions'])} actions, "
            f"{len(d['screens'])} screens -> {GENERATED / app}"
        )
    return 0


def _cmd_parity(args: argparse.Namespace) -> int:
    from factory.parity import harness

    bad = 0
    apps = args.app or (["claims-workbench", "approvals-kit"] if args.all else [])
    if not apps:
        raise SystemExit("factory parity: name an app or pass --all")
    for app in apps:
        if args.freeze:
            print(f"{app}: froze {harness.freeze(app)}")
        rep = harness.run(app)
        f, m, r = rep["formulas"], rep["mutation"], rep["rules"]
        print(
            f"{app}: {rep['frozen_cases']} cases, drift {rep['oracle_drift']}; formulas "
            f"pass {f.get('pass', 0)} fail {f.get('fail', 0)} unproven {f.get('unproven', 0)}; "
            f"mutation {m['killed']}/{m['total']}; rules executed {r.get('executed', 0)} "
            f"scenario {r.get('scenario', 0)} unproven {r.get('unproven', 0)} "
            f"failed {r.get('failed', 0)}"
        )
        bad += rep["oracle_drift"] + (f.get("fail", 0) if args.check else 0)
    return 1 if bad else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="factory", description=__doc__)
    parser.add_argument("--version", action="version", version=f"factory {__version__}")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("parse", help="deterministically parse legacy apps to a LegacyModel")
    p.add_argument("app", nargs="+")
    p.set_defaults(func=_cmd_parse)
    a = sub.add_parser("analyse", help="build rule-catalogue.json from parsed models")
    a.add_argument("app", nargs="+")
    a.add_argument("--replay", action="store_true", help="cache only; fail on any cache miss")
    a.add_argument("--prompt", default="interpret.v1")
    a.add_argument("--workers", type=int, default=4)
    a.set_defaults(func=_cmd_analyse)
    g = sub.add_parser("generate", help="emit the .NET/React/Bicep target from model + catalogue")
    g.add_argument("app", nargs="+")
    g.set_defaults(func=_cmd_generate)
    q = sub.add_parser("parity", help="differential parity of generated C# vs the Power Fx oracle")
    q.add_argument("app", nargs="*")
    q.add_argument("--all", action="store_true")
    q.add_argument("--freeze", action="store_true", help="(re)build the frozen test set first")
    q.add_argument("--check", action="store_true", help="exit non-zero on any mismatch")
    q.set_defaults(func=_cmd_parity)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not hasattr(args, "func"):
        build_parser().print_help()
        return 0
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())

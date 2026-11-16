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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="factory", description=__doc__)
    parser.add_argument("--version", action="version", version=f"factory {__version__}")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("parse", help="deterministically parse legacy apps to a LegacyModel")
    p.add_argument("app", nargs="+")
    p.set_defaults(func=_cmd_parse)
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

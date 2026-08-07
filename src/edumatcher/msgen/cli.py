"""pm-msgen — CLI entry point.

Usage:
    pm-msgen generate [--spec DIR] [--out-python DIR]
    pm-msgen check    [--spec DIR] [--out-python DIR]
    pm-msgen lint     [--spec DIR]

``check`` is the one that matters: it re-renders from the spec and fails if the
committed output differs, so neither a spec change without regeneration nor a
hand-edit to a generated file can reach main (design section 7.2).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from edumatcher.msgen import generate as gen
from edumatcher.msgen.spec import SpecError, load_all

_EXIT_OK = 0
_EXIT_DRIFT = 1
_EXIT_ERROR = 2

_DEFAULT_SPEC = Path("spec")
_DEFAULT_OUT_PYTHON = Path("src/edumatcher/models/generated")


def _add_common(parser: argparse.ArgumentParser, *, with_out: bool) -> None:
    parser.add_argument(
        "--spec",
        type=Path,
        default=_DEFAULT_SPEC,
        metavar="DIR",
        help=f"Spec root holding transports.yaml and messages/ (default: {_DEFAULT_SPEC})",
    )
    if with_out:
        parser.add_argument(
            "--out-python",
            type=Path,
            default=_DEFAULT_OUT_PYTHON,
            metavar="DIR",
            help=f"Python output directory (default: {_DEFAULT_OUT_PYTHON})",
        )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pm-msgen",
        description="Generate message bindings from the canonical specification.",
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-msgen")
    sub = parser.add_subparsers(dest="command", required=True)

    _add_common(sub.add_parser("generate", help="Write generated files"), with_out=True)
    _add_common(
        sub.add_parser("check", help="Fail if committed output differs from the spec"),
        with_out=True,
    )
    _add_common(sub.add_parser("lint", help="Validate the spec only"), with_out=False)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        if args.command == "lint":
            _transports, families = load_all(args.spec)
            count = sum(len(f.messages) for f in families)
            print(
                f"pm-msgen lint: OK - {len(families)} family/families, "
                f"{count} message(s)"
            )
            return _EXIT_OK

        artifacts = gen.build_artifacts(args.spec, args.out_python)
    except SpecError as exc:
        print(f"pm-msgen: spec error: {exc}", file=sys.stderr)
        return _EXIT_ERROR
    except FileNotFoundError as exc:
        print(f"pm-msgen: {exc}", file=sys.stderr)
        return _EXIT_ERROR

    if args.command == "generate":
        changed = gen.write(artifacts)
        for art in changed:
            print(f"pm-msgen: wrote {art.label}")
        if not changed:
            print("pm-msgen: already up to date")
        return _EXIT_OK

    diffs = gen.diff(artifacts)
    if diffs:
        print(
            "pm-msgen check: generated output is out of date with the spec.\n"
            "Run `pm-msgen generate` and commit the result.\n",
            file=sys.stderr,
        )
        for text in diffs:
            print(text, file=sys.stderr)
        return _EXIT_DRIFT
    print(f"pm-msgen check: OK - {len(artifacts)} generated file(s) match the spec")
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

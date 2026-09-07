"""CLI entry point for ``pm-systest``.

Dispatches to the ``run``, ``list``, ``record``, ``compare``, ``verify``,
and ``report`` subcommands using the standard library ``argparse``, matching
every other ``pm-*-cli`` entry point in the codebase (e.g. ``pm-audit-cli``,
``pm-stats-cli``, ``pm-msgen``).

Task 1.2 implements only the top-level dispatcher: subcommand parsing,
no-subcommand/unrecognized-subcommand usage and error output on ``stderr``,
and non-zero exit codes, all of which happen strictly before any
``Orchestrator`` is constructed. The actual subcommand behaviors (running a
Scenario, listing Scenarios, recording a golden file, comparing outcomes,
verifying from a snapshot, and reporting results) are implemented in later
tasks (20.1, 20.2, 21.1, 24.3, 36.2); each subcommand is a minimal stub here.

See design.md Components §1 (Module Layout) and the CLI usage/error/exit-code
behaviour paragraph under Module Layout.
"""

from __future__ import annotations

import argparse
import sys

_SUBCOMMANDS = ("run", "list", "record", "compare", "verify", "report")


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level ``pm-systest`` parser with its six subcommands.

    ``add_subparsers(..., required=True)`` makes argparse itself enforce
    Requirement 1.4/1.5: with no subcommand or an unrecognized one, argparse
    prints a usage/error message identifying the problem to ``stderr`` and
    raises ``SystemExit(2)`` from inside ``parse_args`` -- before this
    function (or ``main``) ever constructs an ``Orchestrator`` or starts any
    process.
    """
    parser = argparse.ArgumentParser(
        prog="pm-systest",
        description=(
            "System-level trading verification framework for EduMatcher's "
            "LIMIT/MARKET order paths."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-systest")

    # No ``metavar`` override here (unlike most other ``pm-*-cli`` parsers in
    # this codebase): with a custom metavar, argparse's usage/error output on
    # the no-subcommand path shows only the placeholder name, not the actual
    # subcommand choices, which would violate Requirement 1.4 ("print usage
    # information listing the run/list/record/compare/verify/report
    # subcommands ... to standard error"). Leaving the default metavar makes
    # argparse render the full ``{run,list,record,compare,verify,report}``
    # choice set in both the usage line and the "required" error message.
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run", help="Run a Scenario under one or more Bindings")
    sub.add_parser("list", help="List available Scenarios")
    sub.add_parser("record", help="Run a Scenario and record its golden file")
    sub.add_parser("compare", help="Compare Canonical Outcomes across Bindings")
    sub.add_parser("verify", help="Verify results from a captured snapshot")
    sub.add_parser("report", help="Render an AssertionReport in text/JSON/JUnit")

    return parser


# ---------------------------------------------------------------------------
# Subcommand stubs
#
# Each handler is a placeholder for a later task; none of them construct an
# Orchestrator or start any process. They exist so that a recognized
# subcommand parses and dispatches cleanly rather than falling through to an
# "unknown command" branch.
# ---------------------------------------------------------------------------


def _cmd_run(args: argparse.Namespace) -> int:
    print("pm-systest run: not yet implemented (see task 20.2)")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    print("pm-systest list: not yet implemented (see task 20.2)")
    return 0


def _cmd_record(args: argparse.Namespace) -> int:
    print("pm-systest record: not yet implemented (see task 20.1)")
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    print("pm-systest compare: not yet implemented (see task 20.2)")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    print("pm-systest verify: not yet implemented (see task 36.2)")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    print("pm-systest report: not yet implemented (see task 21.1)")
    return 0


_HANDLERS = {
    "run": _cmd_run,
    "list": _cmd_list,
    "record": _cmd_record,
    "compare": _cmd_compare,
    "verify": _cmd_verify,
    "report": _cmd_report,
}


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``pm-systest`` console script.

    Parses the subcommand before constructing anything else. With no
    subcommand or an unrecognized subcommand, ``parser.parse_args`` prints
    usage/error information to ``stderr`` and raises ``SystemExit(2)``,
    which propagates out of ``main`` unchanged -- no process is started and
    no ``Orchestrator`` is constructed in either case.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    handler = _HANDLERS.get(args.command)
    if handler is None:  # pragma: no cover - unreachable, argparse enforces choices
        print(f"[ERROR] Unrecognized subcommand: {args.command}", file=sys.stderr)
        return 2

    return handler(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

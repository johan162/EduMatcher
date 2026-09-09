"""pm-help / pm-man — CLI entry point.

Two modes of invocation:

A) ``pm-help`` (no argument)
   Prints the version and data-file locations (the same information as
   ``pm-opctl-cli show``), then a table of every ``pm-*`` command with a
   one-sentence explanation, grouped by category.

B) ``pm-help <pm-command>``
   Prints a full man page for that command: synopsis, description, options,
   subcommands, ports/message-bus involvement, related commands, and
   examples.

``pm-man`` is a plain alias -- both entry points call :func:`main` below;
the invocation name used for ``--help``/usage text and the two banner lines
is taken from ``sys.argv[0]`` so each alias introduces itself correctly.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from edumatcher.cli_version import add_version_argument, package_version
from edumatcher.config import COMPILED_CONFIG_FILE, DATA_DIR, ENGINE_CONFIG_FILE
from edumatcher.pm_help.registry import close_matches, get_command
from edumatcher.pm_help.render import make_console, render_command_index, render_man_page

_EXIT_OK = 0
_EXIT_UNKNOWN_COMMAND = 2

#: Width used when stdout is not a terminal and no width override exists --
#: matches pm-config-show's convention so piped/redirected output stays sane.
_PIPE_WIDTH = 100


def _prog_name() -> str:
    name = Path(sys.argv[0]).name
    return name if name in ("pm-help", "pm-man") else "pm-help"


def _parse_args(argv: list[str] | None, prog: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "List every pm-* command with a one-sentence explanation, or print a "
            "full man page for one of them."
        ),
    )
    add_version_argument(parser, prog)
    parser.add_argument(
        "command",
        nargs="?",
        default=None,
        metavar="COMMAND",
        help="a pm-* command name (e.g. pm-viewer) to show its full man page",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["table", "text"],
        default="table",
        help="table = UTF-8 box-drawing (default); text = plain aligned columns",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show extra detail (and an example, where one exists) for each command",
    )
    parser.add_argument(
        "--no-color", action="store_true", default=False, help="disable ANSI colour"
    )
    return parser.parse_args(argv)


def _print_version_and_paths(prog: str) -> None:
    version = package_version()
    print(f"{prog} (EduMatcher) v{version}")
    print(f"EduMatcher data: {DATA_DIR}")
    print(f"Config source:   {ENGINE_CONFIG_FILE}")
    print(f"Config compiled: {COMPILED_CONFIG_FILE}")
    print()


def main(argv: list[str] | None = None) -> int:
    prog = _prog_name()
    args = _parse_args(argv, prog)

    piped = not sys.stdout.isatty()
    no_color = args.no_color or bool(os.environ.get("NO_COLOR")) or piped
    width = _PIPE_WIDTH if piped else None
    console = make_console(output_format=args.output_format, no_color=no_color, width=width)

    if args.command is None:
        _print_version_and_paths(prog)
        render_command_index(console, output_format=args.output_format, verbose=args.verbose)
        return _EXIT_OK

    cmd = get_command(args.command)
    if cmd is None:
        print(f"{prog}: unknown command {args.command!r}", file=sys.stderr)
        suggestions = close_matches(args.command)
        if suggestions:
            print(f"Did you mean: {', '.join(suggestions)}?", file=sys.stderr)
        print(f"Run `{prog}` with no arguments to list every pm-* command.", file=sys.stderr)
        return _EXIT_UNKNOWN_COMMAND

    render_man_page(console, cmd, output_format=args.output_format)
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""pm-config-show — CLI entry point.

Usage:
    pm-config-show [OPTIONS]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml
from rich.console import Console

from edumatcher.cli_version import add_version_argument
from edumatcher.config import ENGINE_CONFIG_FILE
from edumatcher.config_show import theme as T
from edumatcher.config_show.extract import build_view, resolve_source
from edumatcher.config_show.render_term import render

_EXIT_OK = 0
_EXIT_NO_FILE = 2
_EXIT_BAD_YAML = 3

#: Width used when stdout is not a terminal and --width was not given.
_PIPE_WIDTH = 100


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pm-config-show",
        description="Show engine_config.yaml as a terminal dashboard or a PDF. "
        "Read-only: the configuration is never modified.",
    )
    add_version_argument(parser, "pm-config-show")
    parser.add_argument(
        "-f",
        "--file",
        metavar="YAML",
        help=f"config file to read (default: {ENGINE_CONFIG_FILE})",
    )
    parser.add_argument(
        "-m",
        "--density",
        nargs="?",
        const=1,
        type=int,
        choices=[1, 2],
        default=0,
        metavar="{1,2}",
        help="pack more information in; bare -m means 1",
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        dest="show_all",
        help="show everything, including unmasked API keys",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["terminal", "pdf"],
        default="terminal",
        help="output format (default: terminal)",
    )
    parser.add_argument(
        "-o", "--output", metavar="FILE", help="destination for --format pdf"
    )
    parser.add_argument(
        "--no-color", action="store_true", default=False, help="disable ANSI colour"
    )
    parser.add_argument(
        "--ascii",
        action="store_true",
        default=False,
        help="ASCII box drawing (auto on non-UTF-8 terminals)",
    )
    parser.add_argument(
        "--width", type=int, help="force render width (testing / piping)"
    )
    parser.add_argument(
        "--height", type=int, help="force render height (testing / piping)"
    )
    return parser.parse_args(argv)


def _wants_ascii(explicit: bool) -> bool:
    if explicit:
        return True
    encoding = (getattr(sys.stdout, "encoding", None) or "").lower()
    return bool(encoding) and "utf" not in encoding


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    source = resolve_source(args.file, ENGINE_CONFIG_FILE)
    if not source.exists:
        print(f"pm-config-show: no such config file: {source.path}", file=sys.stderr)
        if not args.file:
            print(
                "Point at one with --file, or run pm-setup to create the "
                "data directory.",
                file=sys.stderr,
            )
        return _EXIT_NO_FILE

    try:
        with source.path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except OSError as exc:
        print(f"pm-config-show: cannot read {source.path}: {exc}", file=sys.stderr)
        return _EXIT_NO_FILE
    except yaml.YAMLError as exc:
        print(
            f"pm-config-show: {source.path} is not valid YAML:\n{exc}", file=sys.stderr
        )
        print("\nRun pm-cverifier for a full diagnosis.", file=sys.stderr)
        return _EXIT_BAD_YAML

    view = build_view(raw, source)
    # Density is a layout control, --all a disclosure control; --all implies
    # the densest layout but -m 2 alone stays safe to run in front of a class.
    density = 2 if args.show_all else args.density

    if _wants_ascii(args.ascii):
        T.THEME.to_ascii()

    if args.output_format == "pdf":
        from edumatcher.config_show.render_pdf import render_pdf

        target = (
            Path(args.output)
            if args.output
            else Path(f"engine-config-{source.path.stem}.pdf")
        )
        # An A4 page has room the terminal does not, so the PDF defaults to
        # the densest content unless -m says otherwise.
        pdf_density = density if (args.density or args.show_all) else 2
        render_pdf(view, target, pdf_density, reveal=args.show_all)
        print(f"pm-config-show: wrote {target}")
        return _EXIT_OK

    # Colour belongs on a terminal, not in a redirect: escape codes in a
    # `> file` or `| grep` are corruption, not decoration. An explicit --width
    # means a deliberate capture, so honour the caller's colour choice there.
    piped = not sys.stdout.isatty()
    no_color = args.no_color or bool(os.environ.get("NO_COLOR")) or piped
    width = args.width
    if width is None and piped:
        width = _PIPE_WIDTH
    console = Console(
        width=width,
        height=args.height,
        no_color=no_color,
        force_terminal=not no_color,
        highlight=False,
        soft_wrap=False,
    )
    render(view, console, density, reveal=args.show_all)
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

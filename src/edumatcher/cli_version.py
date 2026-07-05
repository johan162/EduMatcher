"""Shared CLI version helpers for pm-* entrypoints."""

from __future__ import annotations

import argparse
import sys
from importlib.metadata import PackageNotFoundError, version


def package_version() -> str:
    """Return installed package version or a safe fallback."""
    try:
        return version("edumatcher")
    except PackageNotFoundError:
        return "unknown"


def add_version_argument(parser: argparse.ArgumentParser, prog: str) -> None:
    """Add standard --version support to an argparse parser."""
    parser.add_argument(
        "--version",
        action="version",
        version=f"{prog} {package_version()}",
    )


def maybe_print_version_and_exit(prog: str) -> None:
    """Handle --version for non-argparse entrypoints and exit early."""
    if "--version" in sys.argv:
        print(f"{prog} {package_version()}")
        raise SystemExit(0)

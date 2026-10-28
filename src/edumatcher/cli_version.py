"""Shared CLI version helpers for pm-* entrypoints."""

from __future__ import annotations

import argparse
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def package_version() -> str:
    """Return installed package version or a safe fallback."""
    try:
        return version("edumatcher")
    except PackageNotFoundError:
        return "unknown"


def source_commit() -> str:
    """``git describe --always --dirty`` of the source this code runs from,
    or "unknown" (an installed wheel, no git). The package version stays put
    between releases; the commit says which code it was."""
    src = Path(__file__).resolve().parent
    try:
        return subprocess.run(
            ["git", "-C", str(src), "describe", "--always", "--dirty"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except OSError, subprocess.SubprocessError:
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

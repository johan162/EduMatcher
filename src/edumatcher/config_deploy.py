"""
pm-config-deploy — install an engine configuration for this data directory.

EduMatcher separates the configuration you *author* from the configuration the
exchange *runs*:

  * The authored ``engine_config.yaml`` lives wherever suits you — typically
    under version control next to the rest of your course material. Edit it,
    review it, diff it.
  * The deployed copy lives at ``<DATA_DIR>/ref_data/engine_config.yaml`` and
    is the only file any running process will read. No process accepts a
    config path, which is what makes it impossible for two of them to disagree.

This command is the bridge: it validates an authored file and installs it as
the deployed one. Validation is the same load every process performs at
startup, so a successful deploy means no process will fail to parse it.

Usage
-----
  pm-config-deploy engine_config.yaml       # validate and install
  pm-config-deploy --show                   # print the deployed path
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from edumatcher.config import ENGINE_CONFIG_FILE
from edumatcher.engine.config_loader import load_engine_config


def deploy(source: Path, dest: Path) -> int:
    """Validate *source* and install it at *dest*. Returns a symbol count."""
    config = load_engine_config(source)

    dest.parent.mkdir(parents=True, exist_ok=True)
    # Write beside the destination and rename, so a process starting midway
    # through a deploy sees either the old config or the new one, never half
    # of either.
    staged = dest.with_name(dest.name + ".tmp")
    staged.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    os.replace(staged, dest)

    return len(config.symbols)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pm-config-deploy",
        description=(
            "Validate an engine configuration and install it as the one every "
            "EduMatcher process reads."
        ),
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-config-deploy")
    parser.add_argument(
        "source",
        metavar="SOURCE",
        nargs="?",
        help="Authored engine_config.yaml to validate and install",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Print the deployed configuration path and exit",
    )
    args = parser.parse_args()

    if args.show:
        print(ENGINE_CONFIG_FILE)
        return

    if not args.source:
        parser.error("SOURCE is required (or pass --show)")

    source = Path(args.source).expanduser().resolve()
    if not source.is_file():
        print(f"[ERROR] No such configuration file: {source}", file=sys.stderr)
        sys.exit(1)

    if source == ENGINE_CONFIG_FILE:
        print(f"[ERROR] {source} is already the deployed copy.", file=sys.stderr)
        sys.exit(1)

    try:
        symbol_count = deploy(source, ENGINE_CONFIG_FILE)
    except Exception as exc:
        print(f"[ERROR] {source} is not a usable configuration: {exc}", file=sys.stderr)
        print("        Nothing was deployed.", file=sys.stderr)
        sys.exit(1)

    print(f"Deployed {source}")
    print(f"      to {ENGINE_CONFIG_FILE}")
    print(f"   {symbol_count} symbol(s). Restart any running processes to pick it up.")

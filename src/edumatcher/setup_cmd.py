"""
pm-setup — Bootstrap an EduMatcher session directory.

Run once after installation (pipx install edumatcher) to:
  1. Create the data directory where engine state is stored.
  2. Copy the bundled sample engine_config.yaml to your working directory.
  3. Print the shell environment snippet to add to your shell profile.

Usage
-----
  pm-setup                          # use all defaults
  pm-setup --data-dir ~/my-session  # explicit data directory
  pm-setup --force                  # overwrite existing engine_config.yaml
  pm-setup --no-config              # only create the data dir, skip config copy
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from importlib import resources
from pathlib import Path


def _default_data_dir() -> Path:
    """Return the default data directory for an installed (non-source) run."""
    env = os.environ.get("EDUMATCHER_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path("~/.local/share/edumatcher").expanduser()


def _extract_sample_config(dest: Path, force: bool) -> bool:
    """
    Copy the bundled engine_config.sample.yaml to *dest*.
    Returns True on success, False if the file already existed and --force was
    not given.
    """
    if dest.exists() and not force:
        return False

    try:
        # Python 3.9+ importlib.resources API
        pkg = resources.files("edumatcher")
        sample = pkg.joinpath("engine_config.sample.yaml")
        dest.write_text(sample.read_text(encoding="utf-8"), encoding="utf-8")
    except (FileNotFoundError, TypeError) as exc:
        print(f"  ERROR: could not extract bundled sample config: {exc}", file=sys.stderr)
        print(
            "  If running from a source checkout, copy engine_config.yaml manually.",
            file=sys.stderr,
        )
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pm-setup",
        description=(
            "Bootstrap an EduMatcher session directory. "
            "Creates the data dir and copies a sample engine_config.yaml."
        ),
    )
    parser.add_argument(
        "--data-dir",
        metavar="PATH",
        default=None,
        help=(
            "Data directory for persistent engine files "
            "(default: $EDUMATCHER_DATA_DIR or ~/.local/share/edumatcher)"
        ),
    )
    parser.add_argument(
        "--config-dest",
        metavar="PATH",
        default=None,
        help=(
            "Where to write engine_config.yaml "
            "(default: engine_config.yaml in the current working directory)"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite engine_config.yaml even if it already exists",
    )
    parser.add_argument(
        "--no-config",
        action="store_true",
        help="Only create the data directory; do not copy engine_config.yaml",
    )
    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # 1. Resolve the data directory
    # -----------------------------------------------------------------------
    if args.data_dir:
        data_dir = Path(args.data_dir).expanduser().resolve()
    else:
        data_dir = _default_data_dir()

    print(f"\npm-setup — EduMatcher session initialisation")
    print(f"{'=' * 50}")

    # -----------------------------------------------------------------------
    # 2. Create the data directory
    # -----------------------------------------------------------------------
    if data_dir.exists():
        print(f"  ✓ Data directory already exists:  {data_dir}")
    else:
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            print(f"  ✓ Created data directory:          {data_dir}")
        except OSError as exc:
            print(f"  ✗ Could not create data directory: {data_dir}", file=sys.stderr)
            print(f"    {exc}", file=sys.stderr)
            sys.exit(1)

    # -----------------------------------------------------------------------
    # 3. Copy sample engine_config.yaml
    # -----------------------------------------------------------------------
    if not args.no_config:
        config_dest = (
            Path(args.config_dest).expanduser().resolve()
            if args.config_dest
            else Path.cwd() / "engine_config.yaml"
        )
        ok = _extract_sample_config(config_dest, force=args.force)
        if ok:
            print(f"  ✓ Sample config written to:        {config_dest}")
            print(f"    → Edit this file before starting the engine.")
        else:
            print(f"  ✓ Config already exists (skipped): {config_dest}")
            print(f"    → Use --force to overwrite.")

    # -----------------------------------------------------------------------
    # 4. Print shell profile snippet
    # -----------------------------------------------------------------------
    shell = Path(os.environ.get("SHELL", "/bin/bash")).name
    rc_file = "~/.zshrc" if shell == "zsh" else "~/.bashrc"
    print()
    print("  Shell environment snippet — add to your shell profile:")
    print(f"  ({rc_file})")
    print()
    print("  " + "-" * 46)
    print(f'  export EDUMATCHER_DATA_DIR="{data_dir}"')
    if not args.no_config:
        config_dest_str = str(
            Path(args.config_dest).expanduser().resolve()
            if args.config_dest
            else Path.cwd() / "engine_config.yaml"
        )
        print(f'  export EDUMATCHER_CONFIG="{config_dest_str}"')
    print("  " + "-" * 46)
    print()
    print("  After editing engine_config.yaml, start the exchange with:")
    print()
    print("    pm-engine --verbose     # terminal 1 — matching engine")
    print("    pm-scheduler            # terminal 2 — session phases (optional)")
    print("    pm-gateway --id GW01    # terminal 3 — participant terminal")
    print()
    print("  Or launch everything at once:")
    print()
    print("    tools/launch_all.sh")
    print()


if __name__ == "__main__":
    main()

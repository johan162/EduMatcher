"""
pm-setup — Bootstrap an EduMatcher session directory.

Run once after installation (pipx install edumatcher) to:
  1. Create the data directory where engine state is stored.
  2. Compile and deploy the bundled sample config so the exchange can start.
  3. Print the shell environment snippet to add to your shell profile.

The sample is compiled to ``<DATA_DIR>/ref_data/engine_config.json`` — the
single file every process reads — with the source kept beside it. To run a
configuration of your own, author it wherever you like and install it with
``pm-config-deploy``.

Usage
-----
  pm-setup                          # use all defaults
  pm-setup --data-dir ~/my-session  # explicit data directory
  pm-setup --force                  # replace an already-deployed config
  pm-setup --no-config              # only create the data dir
"""

from __future__ import annotations

import argparse
import os
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
        print(
            f"  ERROR: could not extract bundled sample config: {exc}", file=sys.stderr
        )
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
            "Creates the data dir and compiles a sample engine_config.yaml."
        ),
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-setup")
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
        "--force",
        action="store_true",
        help="Recompile and overwrite an already-deployed configuration",
    )
    parser.add_argument(
        "--no-config",
        action="store_true",
        help="Only create the data directory; do not deploy a sample config",
    )
    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # 1. Resolve the data directory
    # -----------------------------------------------------------------------
    if args.data_dir:
        data_dir = Path(args.data_dir).expanduser().resolve()
    else:
        data_dir = _default_data_dir()

    print("\npm-setup — EduMatcher session initialisation")
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
    # 3. Compile and deploy the bundled sample engine_config.yaml
    # -----------------------------------------------------------------------
    if not args.no_config:
        ref_data = data_dir / "ref_data"
        artifact = ref_data / "engine_config.json"
        source = ref_data / "engine_config.yaml"
        ref_data.mkdir(parents=True, exist_ok=True)

        if artifact.exists() and not args.force:
            print(f"  ✓ Config already deployed (kept):  {artifact}")
            print("    → Use --force to overwrite.")
        elif not _extract_sample_config(source, force=True):
            print("  ✗ Could not extract the bundled sample config", file=sys.stderr)
            sys.exit(1)
        else:
            # Compile it: processes read the artifact, not the YAML, so a
            # fresh install that only copied the source would start every
            # process on built-in defaults.
            from edumatcher.config_deploy import CompileError, deploy

            try:
                compiled = deploy(source, artifact)
            except CompileError as exc:
                print(
                    f"  ✗ Bundled sample config did not compile: {exc}", file=sys.stderr
                )
                sys.exit(1)
            print(f"  ✓ Sample config compiled to:       {artifact}")
            print(f"    {len(compiled.engine.symbols)} symbol(s) ready to trade.")

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
    print("  " + "-" * 46)
    print()
    print("  This is the only variable to set. Every process derives its")
    print("  configuration, database and log paths from it, so they cannot")
    print("  drift apart.")
    print()
    print("  To edit the configuration, work on your own copy and install it:")
    print()
    print("    pm-config-deploy my-engine_config.yaml")
    print()
    print("  Then start the exchange with:")
    print()
    print("    pm-opctl-cli start")
    print()
    print()


if __name__ == "__main__":
    main()

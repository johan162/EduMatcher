"""
pm-setup — Bootstrap an EduMatcher session directory.

Run once after installation (pipx install edumatcher) to:
  1. Create the data directory where engine state is stored.
  2. Compile and deploy an example config so the exchange can start.
  3. Print the shell environment snippet to add to your shell profile.

The example is compiled to ``<DATA_DIR>/ref_data/engine_config.json`` — the
single file every process reads — with the source kept beside it. To run a
configuration of your own, author it wherever you like and install it with
``pm-config-deploy``.

Which example gets installed is controlled by ``--config`` and resolved the
same way ``pm-config-deploy --example`` resolves it — see
``edumatcher.config_deploy.resolve_example`` for the shorthand-to-path
mapping (e.g. ``three-basic`` ->
``docs/examples/ref_data/three-books-basic-setup/engine_config.yaml``). When
``--config`` is omitted, ``three-basic`` is installed.

Usage
-----
  pm-setup                          # use all defaults (three-basic)
  pm-setup --config one-basic       # install a specific bundled example
  pm-setup --data-dir ~/my-session  # explicit data directory
  pm-setup --force                  # replace an already-deployed config
  pm-setup --no-config              # only create the data dir
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from edumatcher.config_deploy import resolve_example

DEFAULT_EXAMPLE_CONFIG = "three-basic"


def _default_data_dir() -> Path:
    """Return the default data directory for an installed (non-source) run."""
    env = os.environ.get("EDUMATCHER_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path("~/.local/share/edumatcher").expanduser()


def _extract_example_config(dest: Path, force: bool, config_name: str) -> bool:
    """
    Copy the bundled example config named *config_name* (e.g. ``three-basic``,
    resolved via ``resolve_example``) to *dest*.
    Returns True on success, False if the file already existed and --force was
    not given.
    """
    if dest.exists() and not force:
        return False

    try:
        source = resolve_example(config_name)
        dest.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    except ValueError as exc:
        print(f"  ERROR: {exc}", file=sys.stderr)
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pm-setup",
        description=(
            "Bootstrap an EduMatcher session directory. "
            "Creates the data dir and compiles a bundled example engine_config.yaml."
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
        "--config",
        metavar="NAME",
        default=DEFAULT_EXAMPLE_CONFIG,
        help=(
            "Bundled example config to deploy, e.g. 'one-basic', 'three-nominal', "
            "'ten-complex' (resolves to "
            "docs/examples/ref_data/<count>-book(s)-<profile>-setup/engine_config.yaml; "
            f"default: {DEFAULT_EXAMPLE_CONFIG!r})"
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
        help="Only create the data directory; do not deploy an example config",
    )
    args = parser.parse_args()

    if not args.no_config:
        try:
            resolve_example(args.config)
        except ValueError as exc:
            parser.error(str(exc))

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
    # 3. Compile and deploy the selected bundled example engine_config.yaml
    # -----------------------------------------------------------------------
    if not args.no_config:
        ref_data = data_dir / "ref_data"
        artifact = ref_data / "engine_config.json"
        source = ref_data / "engine_config.yaml"
        ref_data.mkdir(parents=True, exist_ok=True)

        if artifact.exists() and not args.force:
            print(f"  ✓ Config already deployed (kept):  {artifact}")
            print("    → Use --force to overwrite.")
        elif not _extract_example_config(source, force=True, config_name=args.config):
            print(
                f"  ✗ Could not extract the bundled {args.config!r} example config",
                file=sys.stderr,
            )
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
                    f"  ✗ Bundled {args.config!r} example config did not compile: {exc}",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(f"  ✓ Example config {args.config!r} compiled to: {artifact}")
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

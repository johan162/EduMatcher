"""
pm-config-deploy — compile an engine configuration and install it.

EduMatcher separates the configuration you *author* from the configuration the
exchange *runs*:

  * The authored ``engine_config.yaml`` lives wherever suits you — typically
    under version control next to the rest of your course material. Edit it,
    review it, diff it.
  * The compiled artifact lives at ``<DATA_DIR>/ref_data/engine_config.json``
    and is the only file any running process reads. No process accepts a
    config path, which is what makes it impossible for two of them to
    disagree.

This command is the bridge. It validates the authored file with the same four
layers ``pm-cverifier`` runs, resolves every default exactly once, and installs
the result. Two consequences worth knowing:

  * A configuration that fails validation is never installed, so a process can
    no longer be started against a file nobody checked.
  * Defaults are decided here rather than in eight separate loaders, so they
    cannot drift apart between subsystems.

The authored YAML is installed alongside the artifact, purely so the deployed
directory records what the running exchange was built from.

Usage
-----
  pm-config-deploy engine_config.yaml       # validate, compile and install
  pm-config-deploy --check engine_config.yaml   # validate only, install nothing
  pm-config-deploy --show                   # print the deployed paths
  pm-config-deploy --example three-basic    # deploy a bundled example config
  pm-config-deploy --example three-basic-nomm   # same, with an empty order book
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from edumatcher.alf_gwy.config import load_alf_gateway_config
from edumatcher.api_gateway.config import load_named_api_gateway_configs
from edumatcher.balf_gwy.config import load_balf_gateway_config
from edumatcher.cli_version import package_version
from edumatcher.config import COMPILED_CONFIG_FILE, ENGINE_CONFIG_FILE
from edumatcher.config_artifact import (
    SCHEMA_VERSION,
    ArtifactMeta,
    CompiledConfig,
    content_digest,
    encode,
    source_digest,
)
from edumatcher.cverifier.cli import run as run_verifier
from edumatcher.cverifier.models import CheckResult, Severity
from edumatcher.dc_gateway.config import load_dc_gateway_config
from edumatcher.engine.config_loader import load_engine_config
from edumatcher.log_srv.config import load_log_client_config, load_log_server_config
from edumatcher.md_gateway.config import load_market_data_gateway_config
from edumatcher.ralf_gateway.config import load_ralf_gateway_config

# ---------------------------------------------------------------------------
# --example resolution
# ---------------------------------------------------------------------------
# docs/examples/ref_data/<book-count>-book(s)-<profile>-setup/engine_config.yaml
# is shipped both in the source tree and, alongside the installed package, in
# the wheel (see pyproject.toml's [tool.poetry.include]). The two layouts
# differ by one directory level: in a source checkout "docs/" is a sibling of
# "src/" (repo root), but a wheel install has no "src/" layer, so "docs/"
# lands as a sibling of the "edumatcher" package directory itself. This mirrors
# edumatcher.config's own source-tree detection (this file lives in the same
# "src/edumatcher/" directory that module's _IN_SOURCE_TREE check is based on).
_EXAMPLE_COUNTS = {"one": "book", "three": "books", "ten": "books", "thirty": "books"}
_EXAMPLE_PROFILES = ("basic", "nominal", "complex")


def _examples_root() -> Path:
    pkg_dir = Path(__file__).parent  # .../edumatcher/
    src_dir = pkg_dir.parent  # .../src/  (source) or site-packages (installed)
    base = src_dir.parent if src_dir.name == "src" else src_dir
    return base / "docs" / "examples" / "ref_data"


def resolve_example(name: str) -> Path:
    """Resolve an ``--example`` shorthand (e.g. ``three-basic``) to its YAML.

    An optional trailing ``-nomm`` selects the no-market-maker-quotes variant
    of the same example (e.g. ``three-basic-nomm`` ->
    ``docs/examples/ref_data/three-books-basic-nomm-setup/engine_config.yaml``)
    — see docs/concepts/03-concepts-mm-quotes.md.

    Raises ``ValueError`` with the available names when *name* is not one of
    the bundled examples.
    """
    base = name
    nomm = False
    if base.endswith("-nomm"):
        nomm = True
        base = base[: -len("-nomm")]

    count, _, profile = base.partition("-")
    unit = _EXAMPLE_COUNTS.get(count)
    if unit is None or profile not in _EXAMPLE_PROFILES:
        available = ", ".join(
            f"{count}-{profile}{suffix}"
            for count in _EXAMPLE_COUNTS
            for profile in _EXAMPLE_PROFILES
            for suffix in ("", "-nomm")
        )
        raise ValueError(f"Unknown example {name!r}. Available: {available}")

    nomm_suffix = "-nomm" if nomm else ""
    path = (
        _examples_root()
        / f"{count}-{unit}-{profile}{nomm_suffix}-setup"
        / "engine_config.yaml"
    )
    if not path.is_file():
        raise ValueError(f"Example {name!r} not found (expected {path})")
    return path


class CompileError(Exception):
    """The authored configuration cannot be compiled.

    ``findings`` holds the blocking verifier results when validation was what
    failed, and is empty when a loader rejected the file for its own reasons.
    """

    def __init__(self, message: str, findings: list[CheckResult] | None = None) -> None:
        super().__init__(message)
        self.findings = findings or []


def validate(source: Path) -> list[CheckResult]:
    """Return the blocking findings for *source* — empty means it compiles.

    Only ``ERROR`` blocks. Warnings are advice about a configuration that will
    still run, and a deploy command that refused on advice would push people
    towards editing the deployed copy directly, which is the habit this whole
    arrangement exists to remove.
    """
    results, _raw = run_verifier(source)
    return [r for r in results if r.severity is Severity.ERROR]


def compile_config(source: Path) -> CompiledConfig:
    """Validate *source* and resolve it into a compiled artifact.

    Every section is produced by the subsystem's own loader, so compiling
    reuses the behaviour those loaders already have rather than restating it.
    """
    blocking = validate(source)
    if blocking:
        raise CompileError(f"{source} failed validation", blocking)

    text = source.read_text(encoding="utf-8")
    meta = ArtifactMeta(
        schema_version=SCHEMA_VERSION,
        compiler_version=package_version(),
        compiled_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        source_path=str(source),
        source_sha256=source_digest(text),
    )

    try:
        compiled = CompiledConfig(
            meta=meta,
            engine=load_engine_config(source),
            alf_gateway=load_alf_gateway_config(source),
            balf_gateway=load_balf_gateway_config(source),
            market_data_gateway=load_market_data_gateway_config(source),
            post_trade_gateway=load_ralf_gateway_config(source),
            dc_gateway=load_dc_gateway_config(source),
            log_server=load_log_server_config(source),
            log_client=load_log_client_config(source),
            api_gateways=load_named_api_gateway_configs(source),
        )
    except CompileError:
        raise
    except Exception as exc:
        raise CompileError(f"{source} could not be resolved: {exc}") from exc

    # Stamp the payload digest last: it covers every section but not the meta
    # block that carries it, so it has to be computed once the sections exist.
    return replace(
        compiled, meta=replace(meta, content_sha256=content_digest(compiled))
    )


def _write_atomically(path: Path, text: str) -> None:
    """Write *text* to *path* via a staged rename.

    A process starting midway through a deploy must see either the old file or
    the new one, never half of either.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(path.name + ".tmp")
    staged.write_text(text, encoding="utf-8")
    os.replace(staged, path)


def deploy(source: Path, dest: Path = COMPILED_CONFIG_FILE) -> CompiledConfig:
    """Compile *source* and install the artifact at *dest*.

    The authored YAML is copied *beside the artifact*, derived from ``dest``
    rather than from the global path, so that deploying somewhere else puts
    both files there together. A deployed directory holding an artifact and
    an unrelated source would be worse than one holding neither.
    """
    config = compile_config(source)
    _write_atomically(dest, encode(config))
    _write_atomically(
        dest.with_name(ENGINE_CONFIG_FILE.name), source.read_text("utf-8")
    )
    return config


def _report(findings: list[CheckResult]) -> None:
    for finding in findings:
        location = f" [{finding.path}]" if finding.path else ""
        print(f"  {finding.code}{location}: {finding.message}", file=sys.stderr)
        if finding.suggestion:
            print(f"      {finding.suggestion}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pm-config-deploy",
        description=(
            "Validate and compile an engine configuration, and install it as "
            "the one every EduMatcher process reads."
        ),
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-config-deploy")
    parser.add_argument(
        "source",
        metavar="SOURCE",
        nargs="?",
        help="Authored engine_config.yaml to validate, compile and install",
    )
    parser.add_argument(
        "--example",
        metavar="NAME",
        help=(
            "Use a bundled example config instead of SOURCE, e.g. 'three-basic' "
            "for docs/examples/ref_data/three-books-basic-setup/engine_config.yaml; "
            "append '-nomm' for the no-market-maker-quotes variant, e.g. "
            "'three-basic-nomm'"
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate and compile, but install nothing",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Print the deployed configuration paths and exit",
    )
    args = parser.parse_args()

    if args.show:
        print(f"compiled: {COMPILED_CONFIG_FILE}")
        print(f"source:   {ENGINE_CONFIG_FILE}")
        return

    if args.source and args.example:
        parser.error("SOURCE and --example are mutually exclusive")

    if args.example:
        try:
            source = resolve_example(args.example)
        except ValueError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            sys.exit(1)
    elif args.source:
        source = Path(args.source).expanduser().resolve()
        if not source.is_file():
            print(f"[ERROR] No such configuration file: {source}", file=sys.stderr)
            sys.exit(1)
    else:
        parser.error("SOURCE is required (or pass --example / --show)")
        return  # unreachable, parser.error() exits; keeps type checkers happy

    try:
        config = compile_config(source) if args.check else deploy(source)
    except CompileError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        _report(exc.findings)
        print("        Nothing was deployed.", file=sys.stderr)
        sys.exit(1)

    symbols = len(config.engine.symbols)
    gateways = len(config.engine.fix_gateways)
    if args.check:
        print(f"OK — {source} compiles ({symbols} symbol(s), {gateways} gateway(s))")
        return

    print(f"Compiled {source}")
    print(f"      to {COMPILED_CONFIG_FILE}")
    print(f"   {symbols} symbol(s), {gateways} gateway(s).")
    print("   Restart any running processes to pick it up.")


if __name__ == "__main__":
    main()

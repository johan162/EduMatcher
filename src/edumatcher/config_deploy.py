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

    if not args.source:
        parser.error("SOURCE is required (or pass --show)")

    source = Path(args.source).expanduser().resolve()
    if not source.is_file():
        print(f"[ERROR] No such configuration file: {source}", file=sys.stderr)
        sys.exit(1)

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

"""The listing sequence: check, edit, validate, write and deploy."""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edumatcher.config_deploy import CompileError, compile_config, deploy
from edumatcher.config_include import LoadedConfig, load_config_mapping
from edumatcher.cverifier.cli import run as run_verifier
from edumatcher.cverifier.models import CheckResult, Severity
from edumatcher.engine.config_loader import load_engine_config
from edumatcher.new_symbol.config import resolve_target
from edumatcher.new_symbol.guards import (
    discard_saved_state,
    engine_running,
    other_processes,
    saved_state,
)
from edumatcher.new_symbol.listing import build_listing
from edumatcher.new_symbol.yaml_edit import insert_symbol
from edumatcher.market_sim.config import FILE_NAME as SIM_FILE_NAME


@dataclass
class Result:
    symbol: str
    source: Path
    #: The file the symbol was written to: ``source``, or one of its includes.
    edited: Path
    deployed: bool
    artifact: Path
    payload: dict[str, Any]
    warnings: list[CheckResult]
    #: The saved state --discard-saved-state removed, one line per file.
    discarded: list[str]
    #: pm-* programs still running on the configuration as it was.
    still_running: list[str]


def _symbols_file(loaded: LoadedConfig) -> Path:
    """The file new symbols go into: the one supplying the last listed symbol."""
    symbol_files = [
        path for (key, _), path in loaded.entry_files.items() if key == "symbols"
    ]
    if not symbol_files:
        raise ValueError("configuration has no symbols mapping to add to")
    return symbol_files[-1]


def add_symbol(args: argparse.Namespace) -> Result:
    target = resolve_target(args.config)
    source = target.source
    # The engine rewrites the saved-state files at its next checkpoint, so
    # discarding them needs it stopped even when nothing is deployed.
    guard_engine = target.deploys or args.discard_saved_state
    if guard_engine:
        running = engine_running()
        if running:
            raise ValueError(f"{running}; stop the exchange before listing a symbol")

    loaded = load_config_mapping(source)
    edited = _symbols_file(loaded)
    text = edited.read_text(encoding="utf-8")
    symbol, payload = build_listing(args, load_engine_config(source))
    state = saved_state(symbol)
    if state and not args.discard_saved_state:
        raise ValueError(
            f"the data directory holds saved state for {symbol}, which the "
            "engine would restore instead of the IPO listing:\n  "
            + "\n  ".join(state)
            + f"\nList again with --discard-saved-state to remove {symbol}'s "
            "saved state (and nothing else). 'pm-opctl-cli clear --state' "
            "would also remove it, with every other symbol's resting orders "
            "and last prices, clearing.db (positions and P&L), stats.db, "
            "the index state and the market model's values."
        )
    updated = insert_symbol(text, symbol, payload)

    # Verify a staged copy of the whole file tree, so an included file is
    # checked exactly as it will be loaded and the real files change only once
    # the result is known to be good.
    staging = Path(tempfile.mkdtemp(prefix=".new-symbol-", dir=source.parent))
    try:
        for path in loaded.files:
            copy = staging / path.relative_to(source.parent)
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, copy)
        sim = source.with_name(SIM_FILE_NAME)
        if sim.is_file():
            shutil.copy2(sim, staging / SIM_FILE_NAME)
        candidate = staging / edited.relative_to(source.parent)
        candidate.write_text(updated, encoding="utf-8")
        candidate_main = staging / source.relative_to(source.parent)

        results, _raw = run_verifier(candidate_main)
        blocking = [r for r in results if r.severity is Severity.ERROR]
        if blocking:
            raise CompileError(f"{symbol} would make {edited} invalid", blocking)
        try:
            compile_config(candidate_main)
        except CompileError as exc:
            raise CompileError(
                f"{symbol} would make {edited} invalid: {exc}", exc.findings
            ) from exc

        if guard_engine:
            running = engine_running()
            if running:
                raise ValueError(f"{running}; nothing was changed")
        # The listing is known to be good: only now remove the saved state
        # that would override it.
        discarded = discard_saved_state(symbol) if state else []
        # An error from here on must not hide that the state is gone.
        removed_note = (
            f" {symbol}'s saved state was already removed: {'; '.join(discarded)}."
            if discarded
            else ""
        )
        try:
            os.replace(candidate, edited)
        except OSError as exc:
            raise ValueError(
                f"{symbol} could not be written to {edited} ({exc}).{removed_note}"
            ) from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    if target.deploys:
        try:
            deploy(source, target.artifact)
        except (OSError, CompileError) as exc:
            raise ValueError(
                f"{symbol} was written to {source} but not deployed ({exc}); "
                f"run pm-config-deploy {source}.{removed_note}"
            ) from exc

    warnings = [
        r
        for r in results
        if r.severity is Severity.WARN
        and (r.path or "").startswith(f"symbols.{symbol}")
    ]
    return Result(
        symbol,
        source,
        edited,
        target.deploys,
        target.artifact,
        payload,
        warnings,
        discarded,
        other_processes() if target.deploys else [],
    )

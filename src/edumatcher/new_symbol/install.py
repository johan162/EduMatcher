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
from edumatcher.cverifier.cli import run as run_verifier
from edumatcher.cverifier.models import CheckResult, Severity
from edumatcher.engine.config_loader import load_engine_config
from edumatcher.new_symbol.config import resolve_target
from edumatcher.new_symbol.guards import engine_running, saved_state
from edumatcher.new_symbol.listing import build_listing
from edumatcher.new_symbol.yaml_edit import insert_symbol


@dataclass
class Result:
    symbol: str
    source: Path
    deployed: bool
    artifact: Path
    payload: dict[str, Any]
    warnings: list[CheckResult]


def add_symbol(args: argparse.Namespace) -> Result:
    target = resolve_target(args.config)
    source = target.source
    if target.deploys:
        running = engine_running()
        if running:
            raise ValueError(f"{running}; stop the exchange before listing a symbol")

    text = source.read_text(encoding="utf-8")
    symbol, payload = build_listing(args, load_engine_config(source))
    state = saved_state(symbol)
    if state:
        raise ValueError(
            f"the data directory holds saved state for {symbol}, which the "
            "engine would restore instead of the IPO listing:\n  "
            + "\n  ".join(state)
            + "\nRemove it from those files, or clear all engine state with "
            "'pm-opctl-cli clear', before listing."
        )
    updated = insert_symbol(text, symbol, payload)

    fd, name = tempfile.mkstemp(
        prefix=".new-symbol-", suffix=".yaml", dir=source.parent
    )
    candidate = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as staged:
            staged.write(updated)
        shutil.copymode(source, candidate)

        results, _raw = run_verifier(candidate)
        blocking = [r for r in results if r.severity is Severity.ERROR]
        if blocking:
            raise CompileError(f"{symbol} would make {source} invalid", blocking)
        try:
            compile_config(candidate)
        except CompileError as exc:
            raise CompileError(
                f"{symbol} would make {source} invalid: {exc}", exc.findings
            ) from exc

        if target.deploys:
            running = engine_running()
            if running:
                raise ValueError(f"{running}; nothing was changed")
        os.replace(candidate, source)
    finally:
        candidate.unlink(missing_ok=True)

    if target.deploys:
        try:
            deploy(source, target.artifact)
        except (OSError, CompileError) as exc:
            raise ValueError(
                f"{symbol} was written to {source} but not deployed ({exc}); "
                f"run pm-config-deploy {source}"
            ) from exc

    warnings = [
        r
        for r in results
        if r.severity is Severity.WARN
        and (r.path or "").startswith(f"symbols.{symbol}")
    ]
    return Result(symbol, source, target.deploys, target.artifact, payload, warnings)

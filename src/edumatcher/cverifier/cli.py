"""pm-cverifier — CLI entry point.

Usage:
    pm-cverifier [OPTIONS] CONFIG_FILE
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from edumatcher.cverifier import (
    layer1_yaml,
    layer2_schema,
    layer3_semantic,
    layer4_complete,
)
from edumatcher.cverifier import risk_summary as risk_summary_mod
from edumatcher.cverifier.formatter import format_json, format_text
from edumatcher.cverifier.models import (
    CheckResult,
    LayerOutcome,
    RiskSummary,
    Severity,
    VerificationReport,
)

_EXIT_OK = 0
_EXIT_WARN = 1
_EXIT_ERROR = 2


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pm-cverifier",
        description="Read-only engine_config.yaml verification tool.",
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-cverifier")
    parser.add_argument(
        "config_file", metavar="CONFIG_FILE", help="Path to engine_config.yaml"
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--level",
        choices=["info", "warn", "error"],
        default="info",
        help="Minimum severity to show (default: info)",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI color in text output",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Treat warnings as errors for CI exit-code purposes",
    )
    return parser.parse_args(argv)


def _compute_verdict(results: list[CheckResult], strict: bool) -> str:
    has_error = any(r.severity is Severity.ERROR for r in results)
    has_warn = any(r.severity is Severity.WARN for r in results)
    if has_error:
        return "ERROR"
    if has_warn:
        return "WARN" if not strict else "ERROR"
    return "OK"


def _compute_exit_code(verdict: str) -> int:
    if verdict == "OK":
        return _EXIT_OK
    if verdict == "WARN":
        return _EXIT_WARN
    return _EXIT_ERROR


def run_layers(
    config_path: Path,
) -> tuple[list[LayerOutcome], dict[str, Any] | None]:
    """Run the verification layers, recording per-layer outcomes.

    Layers 3 and 4 are skipped when Layer 1 or Layer 2 reports an error, since
    later checks assume a syntactically valid, schema-correct document.
    """
    layers: list[LayerOutcome] = []

    def _skip_rest(*names: str) -> None:
        for name in names:
            layers.append(LayerOutcome(name, status="skipped"))

    # Layer 1 — YAML syntax (parse the file exactly once and reuse the result).
    l1, raw = layer1_yaml.load(config_path)
    layers.append(LayerOutcome("YAML syntax", "ran", l1))
    if any(r.severity is Severity.ERROR for r in l1) or raw is None:
        _skip_rest("Schema", "Semantic", "Completeness")
        return layers, None

    # Layer 2 — Schema
    l2 = layer2_schema.check(raw, config_path)
    layers.append(LayerOutcome("Schema", "ran", l2))
    if any(r.severity is Severity.ERROR for r in l2):
        _skip_rest("Semantic", "Completeness")
        return layers, raw

    # Layer 3 — Semantic
    l3 = layer3_semantic.check(raw, config_path)
    layers.append(LayerOutcome("Semantic", "ran", l3))

    # Layer 4 — Completeness
    l4 = layer4_complete.check(raw, config_path)
    layers.append(LayerOutcome("Completeness", "ran", l4))

    return layers, raw


def run(config_path: Path) -> tuple[list[CheckResult], dict[str, Any] | None]:
    """Run all verification layers; return (flat results, raw)."""
    layers, raw = run_layers(config_path)
    results = [r for layer in layers for r in layer.results]
    return results, raw


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    config_path = Path(args.config_file)
    color = (
        not args.no_color and sys.stdout.isatty()
        if args.output_format == "text"
        else False
    )
    if args.no_color:
        color = False

    layers, raw = run_layers(config_path)
    results = [r for layer in layers for r in layer.results]

    rs: RiskSummary
    if raw is not None:
        rs = risk_summary_mod.build(raw)
    else:
        rs = RiskSummary()

    n_errors = sum(1 for r in results if r.severity is Severity.ERROR)
    n_warns = sum(1 for r in results if r.severity is Severity.WARN)
    n_info = sum(1 for r in results if r.severity is Severity.INFO)
    summary = {"errors": n_errors, "warnings": n_warns, "info": n_info}

    verdict = _compute_verdict(results, args.strict)

    report = VerificationReport(
        file=str(config_path),
        results=results,
        summary=summary,
        risk_summary=rs,
        verdict=verdict,
        layers=layers,
        strict=args.strict,
    )

    _sev_map = {"info": Severity.INFO, "warn": Severity.WARN, "error": Severity.ERROR}
    min_sev = _sev_map[args.level]

    if args.output_format == "json":
        print(format_json(report))
    else:
        print(format_text(report, color=color, min_severity=min_sev))

    sys.exit(_compute_exit_code(verdict))


if __name__ == "__main__":
    main()

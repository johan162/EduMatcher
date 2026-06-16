"""pm-config-gen — generate engine_config.yaml from high-level CLI inputs."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

from edumatcher.engine.config_loader import load_engine_config
from edumatcher.models.participant import ParticipantRole

from edumatcher.config_gen.builder import ConfigBuilder, ConfigSpec
from edumatcher.config_gen.cb_spec import CbSpec, parse_cb_spec
from edumatcher.config_gen.defaults import (
    DEFAULT_CB_WINDOW_NS,
    DEFAULT_MM_MIN_QTY,
    DEFAULT_MM_SPREAD_TICKS,
    DEFAULT_SNAPSHOT_INTERVAL_SEC,
    DEFAULT_SCHEDULE,
    DEFAULT_TICK_DECIMALS,
)
from edumatcher.config_gen.gateway_spec import GatewaySpec, parse_gateway_spec
from edumatcher.config_gen.renderer import render_yaml
from edumatcher.config_gen.risk_spec import parse_risk_level_spec
from edumatcher.config_gen.symbol_spec import SymbolOverride
from edumatcher.config_gen.symbol_spec import parse_symbol_opts
from edumatcher.config_gen.warnings import evaluate_diagnostics


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm-config-gen",
        description=(
            "Generate a parser-compatible engine_config.yaml from concise CLI inputs."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "--symbols",
        nargs="+",
        required=True,
        metavar="SYM",
        help="One or more symbols.",
    )
    parser.add_argument(
        "--gateways",
        nargs="+",
        required=True,
        metavar="GW_SPEC",
        help="One or more gateway specs (ID[:ROLE[:DISCONNECT]]).",
    )
    parser.add_argument(
        "--symbol-opts",
        action="append",
        default=[],
        metavar="SYMBOL:KEY=VALUE[,KEY=VALUE]",
        help="Per-symbol overrides. Can be repeated.",
    )

    sess_group = parser.add_mutually_exclusive_group()
    sess_group.add_argument(
        "--sessions-enabled",
        dest="sessions_enabled",
        action="store_true",
        help="Enable scheduler-driven sessions.",
    )
    sess_group.add_argument(
        "--no-sessions-enabled",
        dest="sessions_enabled",
        action="store_false",
        help="Disable scheduler-driven sessions.",
    )
    parser.set_defaults(sessions_enabled=False)

    parser.add_argument(
        "--snapshot-interval",
        type=float,
        default=DEFAULT_SNAPSHOT_INTERVAL_SEC,
        metavar="SECS",
        help="Snapshot interval seconds (> 0).",
    )

    parser.add_argument(
        "--no-collars",
        action="store_true",
        help="Set enforce_collars: false.",
    )
    parser.add_argument(
        "--no-circuit-breakers",
        action="store_true",
        help="Set enforce_circuit_breakers: false.",
    )

    parser.add_argument(
        "--static-band",
        type=float,
        default=None,
        metavar="PCT",
        help="DEFAULT static band pct in (0,1).",
    )
    parser.add_argument(
        "--dynamic-band",
        type=float,
        default=None,
        metavar="PCT",
        help="DEFAULT dynamic band pct in (0,1).",
    )

    parser.add_argument(
        "--risk-level",
        action="append",
        default=[],
        metavar="LEVEL_SPEC",
        help="Repeatable NAME:STATIC_PCT[:DYNAMIC_PCT]",
    )

    parser.add_argument(
        "--cb-levels",
        nargs="+",
        default=None,
        metavar="CB_SPEC",
        help="NAME:SHIFT_PCT[:HALT_MINS] entries.",
    )
    parser.add_argument(
        "--cb-window-ns",
        type=int,
        default=DEFAULT_CB_WINDOW_NS,
        metavar="NS",
        help="CB reference window nanoseconds.",
    )

    parser.add_argument(
        "--mm-spread-ticks",
        type=int,
        default=DEFAULT_MM_SPREAD_TICKS,
        metavar="N",
        help="Global MM max spread ticks.",
    )
    parser.add_argument(
        "--mm-min-qty",
        type=int,
        default=DEFAULT_MM_MIN_QTY,
        metavar="N",
        help="Global MM min qty.",
    )

    mm_group = parser.add_mutually_exclusive_group()
    mm_group.add_argument(
        "--enforce-mm-obligations",
        dest="enforce_mm_obligations",
        action="store_true",
        help="Enable MM obligations globally.",
    )
    mm_group.add_argument(
        "--no-enforce-mm-obligations",
        dest="enforce_mm_obligations",
        action="store_false",
        help="Disable MM obligations globally.",
    )
    parser.set_defaults(enforce_mm_obligations=False)

    parser.add_argument(
        "--tick-decimals",
        type=int,
        default=DEFAULT_TICK_DECIMALS,
        metavar="N",
        help="Default symbol tick decimals.",
    )
    parser.add_argument(
        "--seed-last-prices",
        action="store_true",
        help="Emit last_buy_price/last_sell_price null placeholders.",
    )

    sched_group = parser.add_mutually_exclusive_group()
    sched_group.add_argument(
        "--schedule",
        dest="schedule",
        action="store_true",
        default=None,
        help="Force emit schedule section.",
    )
    sched_group.add_argument(
        "--no-schedule",
        dest="schedule",
        action="store_false",
        default=None,
        help="Suppress schedule section.",
    )

    parser.add_argument(
        "--pre-open", default=DEFAULT_SCHEDULE["pre_open"], metavar="HH:MM"
    )
    parser.add_argument(
        "--opening-auction",
        default=DEFAULT_SCHEDULE["opening_auction_start"],
        metavar="HH:MM",
    )
    parser.add_argument(
        "--continuous",
        default=DEFAULT_SCHEDULE["continuous_start"],
        metavar="HH:MM",
    )
    parser.add_argument(
        "--closing-auction",
        default=DEFAULT_SCHEDULE["closing_auction_start"],
        metavar="HH:MM",
    )
    parser.add_argument(
        "--closing-end",
        default=DEFAULT_SCHEDULE["closing_auction_end"],
        metavar="HH:MM",
    )

    parser.add_argument(
        "--output", default=None, metavar="FILE", help="Output file path."
    )
    parser.add_argument(
        "--force", action="store_true", help="Overwrite existing output file."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print only, do not write."
    )

    return parser


def _validate_basic_args(args: argparse.Namespace) -> None:
    if args.snapshot_interval <= 0:
        raise ValueError("--snapshot-interval must be > 0")
    if not (0 <= args.tick_decimals <= 8):
        raise ValueError("--tick-decimals must be in range 0..8")
    if args.mm_spread_ticks <= 0:
        raise ValueError("--mm-spread-ticks must be > 0")
    if args.mm_min_qty <= 0:
        raise ValueError("--mm-min-qty must be > 0")
    if args.cb_window_ns <= 0:
        raise ValueError("--cb-window-ns must be > 0")

    if args.static_band is not None and not (0 < args.static_band < 1):
        raise ValueError("--static-band must be in (0, 1)")
    if args.dynamic_band is not None and not (0 < args.dynamic_band < 1):
        raise ValueError("--dynamic-band must be in (0, 1)")


def _parse_specs(args: argparse.Namespace) -> tuple[
    list[str],
    list[GatewaySpec],
    dict[str, tuple[float, float | None]],
    list[CbSpec],
    dict[str, SymbolOverride],
    list[str],
]:
    symbols = [s.upper() for s in args.symbols]

    gateways = [parse_gateway_spec(raw) for raw in args.gateways]

    risk_levels: dict[str, tuple[float, float | None]] = {}
    for raw in args.risk_level:
        spec = parse_risk_level_spec(raw)
        risk_levels[spec.name] = (spec.static_pct, spec.dynamic_pct)

    cb_levels: list[CbSpec] = []
    if args.cb_levels is not None:
        cb_levels = [parse_cb_spec(raw) for raw in args.cb_levels]

    symbol_overrides, symbol_opt_warnings = parse_symbol_opts(
        specs=args.symbol_opts,
        allowed_symbols=set(symbols),
    )

    return (
        symbols,
        gateways,
        risk_levels,
        cb_levels,
        symbol_overrides,
        symbol_opt_warnings,
    )


def _resolve_emit_schedule(args: argparse.Namespace) -> bool:
    if args.schedule is None:
        return bool(args.sessions_enabled)
    return bool(args.schedule)


def _print_diagnostics(lines: list[str]) -> None:
    for line in lines:
        print(line, file=sys.stderr)


def _write_output(output_path: Path, content: str, force: bool) -> None:
    if output_path.exists() and not force:
        raise FileExistsError("Output file already exists")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


def _validate_generated_when_possible(content: str, has_mm_gateway: bool) -> str | None:
    # With MM stubs bid/ask are null by design, so parser validation is expected to fail.
    if has_mm_gateway:
        return None

    with NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as fh:
        fh.write(content)
        tmp_path = Path(fh.name)

    try:
        load_engine_config(tmp_path)
    except Exception as exc:  # pragma: no cover - defensive
        return f"[WARN] Internal validation failed for generated config: {exc}"
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass

    return "[INFO] Generated config passed load_engine_config() validation."


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        _validate_basic_args(args)
        (
            symbols,
            gateways,
            risk_levels,
            cb_levels,
            symbol_overrides,
            symbol_opt_warnings,
        ) = _parse_specs(args)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    spec = ConfigSpec(
        symbols=symbols,
        gateways=gateways,
        sessions_enabled=bool(args.sessions_enabled),
        snapshot_interval_sec=float(args.snapshot_interval),
        enforce_collars=not args.no_collars,
        enforce_circuit_breakers=not args.no_circuit_breakers,
        static_band_pct=args.static_band,
        dynamic_band_pct=args.dynamic_band,
        risk_levels=risk_levels,
        cb_levels=cb_levels,
        cb_window_ns=int(args.cb_window_ns),
        mm_spread_ticks=int(args.mm_spread_ticks),
        mm_min_qty=int(args.mm_min_qty),
        enforce_mm_obligations=bool(args.enforce_mm_obligations),
        emit_mm_defaults=any(g.role == ParticipantRole.MARKET_MAKER for g in gateways),
        tick_decimals=int(args.tick_decimals),
        seed_last_prices=bool(args.seed_last_prices),
        emit_schedule=_resolve_emit_schedule(args),
        pre_open=str(args.pre_open),
        opening_auction=str(args.opening_auction),
        continuous=str(args.continuous),
        closing_auction=str(args.closing_auction),
        closing_end=str(args.closing_end),
        symbol_overrides=symbol_overrides,
    )

    output_path = Path(args.output) if args.output else None
    output_exists = bool(output_path and output_path.exists() and not args.force)

    diagnostics = evaluate_diagnostics(
        spec=spec,
        parsed_symbol_option_warnings=symbol_opt_warnings,
        raw_symbols=args.symbols,
        raw_gateways=args.gateways,
        output_exists=output_exists,
    )

    # Fatal if user requested file output but file exists and no --force.
    if output_exists:
        _print_diagnostics(diagnostics)
        raise SystemExit(1)

    config = ConfigBuilder(spec).build()
    cmd_line = "pm-config-gen " + " ".join(sys.argv[1:])
    rendered = render_yaml(
        config=config,
        command=cmd_line,
        generated_version="1.1.0",
        generated_date=str(date.today()),
    )

    _print_diagnostics(diagnostics)

    validation_line = _validate_generated_when_possible(
        content=rendered,
        has_mm_gateway=any(g.role == ParticipantRole.MARKET_MAKER for g in gateways),
    )
    if validation_line:
        print(validation_line, file=sys.stderr)

    if args.dry_run or output_path is None:
        print(rendered, end="")
        if not args.dry_run and output_path is None:
            print(
                "[INFO] No --output specified; YAML printed to stdout.",
                file=sys.stderr,
            )
        return

    _write_output(output_path=output_path, content=rendered, force=bool(args.force))
    print(f"[INFO] Wrote generated config to {output_path}", file=sys.stderr)

    if any(g.role == ParticipantRole.MARKET_MAKER for g in gateways):
        print(
            "[HINT] Fill all market_maker_quotes bid_price/ask_price values before "
            "starting pm-engine.",
            file=sys.stderr,
        )
    print(
        "[HINT] Validate with: poetry run python -c 'from pathlib import Path; "
        "from edumatcher.engine.config_loader import load_engine_config; "
        'print(load_engine_config(Path("engine_config.yaml")))\'',
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()

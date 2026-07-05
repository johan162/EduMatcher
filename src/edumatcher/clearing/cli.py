"""pm-clearing-cli — read-only query interface for the clearing SQLite database."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from edumatcher.clearing.store import (
    open_readonly_connection,
    open_writer_connection as _open_writer,
    prune_old_events,
    query_daily,
    query_dates,
    query_exposure,
    query_gateways,
    query_health,
    query_pnl,
    query_positions,
    query_reconcile,
    query_symbols,
    query_trades,
    validate_date,
)

_FORMATS = ("table", "json", "csv")

# Column lists for each verb — determines output order.
_GATEWAYS_COLS = [
    "gateway_id",
    "realized_pnl_total",
    "unrealized_pnl_total",
    "total_pnl",
    "net_qty_total",
]
_POSITIONS_COLS = [
    "gateway_id",
    "symbol",
    "net_qty",
    "avg_cost",
    "mark_price",
    "tick_decimals",
    "realized_pnl",
    "unrealized_pnl",
    "buy_qty",
    "sell_qty",
    "buy_notional",
    "sell_notional",
    "last_trade_ts_ns",
    "updated_ts_ns",
]
_PNL_COLS = [
    "gateway_id",
    "symbol",
    "realized_pnl",
    "unrealized_pnl",
    "total_pnl",
    "net_qty",
    "mark_price",
    "tick_decimals",
]
_DAILY_COLS = [
    "trade_date",
    "gateway_id",
    "symbol",
    "traded_qty",
    "traded_notional",
    "buy_qty",
    "sell_qty",
    "buy_notional",
    "sell_notional",
    "net_amount",
    "realized_pnl",
    "end_net_qty",
    "end_avg_cost",
    "end_unrealized_pnl",
    "tick_decimals",
    "last_trade_ts_ns",
    "updated_ts_ns",
]
_TRADES_COLS = [
    "id",
    "ts_ns",
    "trade_date",
    "symbol",
    "quantity",
    "price",
    "tick_decimals",
    "buy_order_id",
    "sell_order_id",
    "buy_gateway_id",
    "sell_gateway_id",
    "aggressor_side",
    "ingest_ts_ns",
]
_EXPOSURE_COLS = [
    "gateway_id",
    "symbol",
    "net_qty",
    "mark_price",
    "tick_decimals",
    "net_notional",
    "gross_notional",
    "realized_pnl",
    "unrealized_pnl",
    "total_pnl",
]
_SYMBOLS_COLS = [
    "symbol",
    "traded_qty",
    "traded_notional",
    "realized_pnl",
    "tick_decimals",
    "open_net_qty",
    "open_unrealized_pnl",
]
_DATES_COLS = ["trade_date"]
_DATES_TOTALS_COLS = [
    "trade_date",
    "traded_qty_total",
    "traded_notional_total",
    "net_amount_total",
]
_HEALTH_COLS = [
    "db_path",
    "trade_events_rows",
    "gateway_symbol_positions_rows",
    "gateway_daily_summary_rows",
    "last_trade_ts_ns",
    "last_flush_ts_ns",
    "wal_mode",
]
_RECONCILE_COLS = [
    "trade_date",
    "gateway_id",
    "symbol",
    "raw_buy_qty",
    "summary_buy_qty",
    "qty_diff",
    "notional_diff",
]

_NORMALIZE_FIELDS: dict[str, tuple[str, ...]] = {
    "positions": (
        "avg_cost",
        "mark_price",
        "realized_pnl",
        "unrealized_pnl",
        "buy_notional",
        "sell_notional",
    ),
    "pnl": ("mark_price", "realized_pnl", "unrealized_pnl", "total_pnl"),
    "daily": (
        "traded_notional",
        "buy_notional",
        "sell_notional",
        "net_amount",
        "realized_pnl",
        "end_avg_cost",
        "end_unrealized_pnl",
    ),
    "trades": ("price",),
    "exposure": (
        "mark_price",
        "net_notional",
        "gross_notional",
        "realized_pnl",
        "unrealized_pnl",
        "total_pnl",
    ),
    "symbols": ("traded_notional", "realized_pnl", "open_unrealized_pnl"),
}


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm-clearing-cli",
        description="Query EduMatcher clearing DB without writing SQL",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-clearing-cli")

    parser.add_argument(
        "--datapath",
        default=None,
        metavar="PATH",
        help="Data directory or explicit .db file path",
    )
    parser.add_argument(
        "--db-name",
        default="clearing.db",
        metavar="NAME",
        help="SQLite filename within data directory (default: clearing.db)",
    )
    parser.add_argument(
        "--format",
        default="table",
        choices=_FORMATS,
        help="Output format: table, json, csv (default: table)",
    )
    parser.add_argument(
        "--no-header",
        action="store_true",
        help="Suppress header row for csv output",
    )
    parser.add_argument(
        "--raw-output",
        action="store_true",
        help="Show raw tick-unit values instead of normalized display values",
    )

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    # gateways
    gw = sub.add_parser("gateways", help="List gateways with P&L totals")
    gw.add_argument("--gateway", metavar="GW_ID")
    gw.add_argument("--limit", type=int, default=1000, metavar="N")

    # positions
    pos = sub.add_parser("positions", help="Current positions by gateway/symbol")
    pos.add_argument("--gateway", metavar="GW_ID")
    pos.add_argument("--symbol", metavar="SYMBOL")
    pos.add_argument("--limit", type=int, default=10000, metavar="N")

    # pnl
    pnl = sub.add_parser("pnl", help="Realized/unrealized/total P&L")
    pnl.add_argument("--gateway", metavar="GW_ID")
    pnl.add_argument("--symbol", metavar="SYMBOL")
    pnl.add_argument("--limit", type=int, default=10000, metavar="N")

    # daily
    daily = sub.add_parser("daily", help="Daily rollup summaries")
    daily.add_argument("--gateway", metavar="GW_ID")
    daily.add_argument("--symbol", metavar="SYMBOL")
    daily.add_argument("--date", metavar="YYYY-MM-DD")
    daily.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD")
    daily.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD")
    daily.add_argument("--limit", type=int, default=1000, metavar="N")

    # trades
    trades = sub.add_parser("trades", help="Raw trade events")
    trades.add_argument("--gateway", metavar="GW_ID")
    trades.add_argument("--symbol", metavar="SYMBOL")
    trades.add_argument("--date", metavar="YYYY-MM-DD")
    trades.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD")
    trades.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD")
    trades.add_argument("--limit", type=int, default=200, metavar="N")

    # exposure
    exp = sub.add_parser("exposure", help="Net/gross notional exposure")
    exp.add_argument("--gateway", metavar="GW_ID")
    exp.add_argument("--symbol", metavar="SYMBOL")
    exp.add_argument("--sort", default="gross_notional", metavar="FIELD")
    exp.add_argument("--limit", type=int, default=1000, metavar="N")

    # symbols
    syms = sub.add_parser("symbols", help="Symbol-level clearing totals")
    syms.add_argument("--date", metavar="YYYY-MM-DD")
    syms.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD")
    syms.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD")
    syms.add_argument("--sort", default="symbol", metavar="FIELD")
    syms.add_argument("--limit", type=int, default=1000, metavar="N")

    # dates
    dates = sub.add_parser("dates", help="Available trading dates")
    dates.add_argument("--gateway", metavar="GW_ID")
    dates.add_argument("--symbol", metavar="SYMBOL")
    dates.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD")
    dates.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD")
    dates.add_argument(
        "--with-totals",
        action="store_true",
        help="Include per-date quantity and net-amount totals",
    )
    dates.add_argument("--limit", type=int, default=1000, metavar="N")

    # health
    sub.add_parser("health", help="DB metadata and row counts")

    # reconcile
    rec = sub.add_parser(
        "reconcile",
        help="Compare raw trade_events against gateway_daily_summary aggregates",
    )
    rec.add_argument("--gateway", metavar="GW_ID")
    rec.add_argument("--symbol", metavar="SYMBOL")
    rec.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD")
    rec.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD")

    # prune
    prune = sub.add_parser(
        "prune",
        help="Delete trade_events rows older than N days (default: 90) and VACUUM",
    )
    prune.add_argument(
        "--days",
        type=int,
        default=90,
        metavar="N",
        help="Retention window in days (default: 90)",
    )
    prune.add_argument(
        "--dry-run",
        action="store_true",
        help="Show how many rows would be deleted without actually deleting",
    )

    return parser


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


def _validate_args(args: argparse.Namespace) -> None:
    if hasattr(args, "limit") and args.limit <= 0:
        raise ValueError("--limit must be > 0")

    for attr in ("date", "from_date", "to_date"):
        val = getattr(args, attr, None)
        if val is not None:
            validate_date(str(val))


# ---------------------------------------------------------------------------
# Output rendering (shared with pm-stats-cli style)
# ---------------------------------------------------------------------------


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _render_table(
    rows: list[dict[str, Any]], columns: list[str], no_header: bool
) -> None:
    if not rows:
        print("No rows found.")
        return

    widths: list[int] = []
    for col in columns:
        content_w = max((len(_stringify(row.get(col))) for row in rows), default=0)
        widths.append(max(len(col), content_w))

    def _line(values: list[str]) -> str:
        return " | ".join(v.ljust(w) for v, w in zip(values, widths, strict=True))

    if not no_header:
        print(_line(columns))
        print("-+-".join("-" * w for w in widths))

    for row in rows:
        print(_line([_stringify(row.get(col)) for col in columns]))


def _render_json(rows: list[dict[str, Any]], columns: list[str]) -> None:
    projected = [{col: row.get(col) for col in columns} for row in rows]
    print(json.dumps(projected, indent=2))


def _render_csv(
    rows: list[dict[str, Any]], columns: list[str], no_header: bool
) -> None:
    writer = csv.DictWriter(sys.stdout, fieldnames=columns)
    if not no_header:
        writer.writeheader()
    for row in rows:
        writer.writerow({col: row.get(col) for col in columns})


def _normalize_rows(command: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = _NORMALIZE_FIELDS.get(command)
    if not fields:
        return rows

    out: list[dict[str, Any]] = []
    for row in rows:
        tick_decimals = row.get("tick_decimals")
        if tick_decimals is None:
            out.append(row)
            continue

        decimals = int(tick_decimals)
        scale = float(10**decimals)
        normalized = dict(row)
        for field in fields:
            val = normalized.get(field)
            if isinstance(val, (int, float)):
                normalized[field] = float(val) / scale
        out.append(normalized)
    return out


# ---------------------------------------------------------------------------
# Query dispatch
# ---------------------------------------------------------------------------


def _run_query(
    conn: object,
    args: argparse.Namespace,
    db_path: Path,
) -> tuple[list[str], list[dict[str, Any]]]:
    import sqlite3

    assert isinstance(conn, sqlite3.Connection)

    cmd = args.command

    if cmd == "gateways":
        rows = query_gateways(
            conn,
            gateway=_upper(getattr(args, "gateway", None)),
            limit=args.limit,
        )
        return _GATEWAYS_COLS, rows

    if cmd == "positions":
        rows = query_positions(
            conn,
            gateway=_upper(args.gateway),
            symbol=_upper(args.symbol),
            limit=args.limit,
        )
        return _POSITIONS_COLS, rows

    if cmd == "pnl":
        rows = query_pnl(
            conn,
            gateway=_upper(args.gateway),
            symbol=_upper(args.symbol),
            limit=args.limit,
        )
        return _PNL_COLS, rows

    if cmd == "daily":
        rows = query_daily(
            conn,
            gateway=_upper(args.gateway),
            symbol=_upper(args.symbol),
            date_value=args.date,
            from_date=args.from_date,
            to_date=args.to_date,
            limit=args.limit,
        )
        return _DAILY_COLS, rows

    if cmd == "trades":
        rows = query_trades(
            conn,
            gateway=_upper(args.gateway),
            symbol=_upper(args.symbol),
            date_value=args.date,
            from_date=args.from_date,
            to_date=args.to_date,
            limit=args.limit,
        )
        return _TRADES_COLS, rows

    if cmd == "exposure":
        rows = query_exposure(
            conn,
            gateway=_upper(args.gateway),
            symbol=_upper(args.symbol),
            sort=args.sort,
            limit=args.limit,
        )
        return _EXPOSURE_COLS, rows

    if cmd == "symbols":
        rows = query_symbols(
            conn,
            date_value=args.date,
            from_date=args.from_date,
            to_date=args.to_date,
            sort=args.sort,
            limit=args.limit,
        )
        return _SYMBOLS_COLS, rows

    if cmd == "dates":
        rows = query_dates(
            conn,
            gateway=_upper(getattr(args, "gateway", None)),
            symbol=_upper(getattr(args, "symbol", None)),
            from_date=args.from_date,
            to_date=args.to_date,
            with_totals=args.with_totals,
            limit=args.limit,
        )
        cols = _DATES_TOTALS_COLS if args.with_totals else _DATES_COLS
        return cols, rows

    if cmd == "health":
        rows = query_health(conn, db_path)
        return _HEALTH_COLS, rows

    assert (
        cmd == "reconcile"
    ), f"Unhandled command: {cmd}"  # prune handled before _run_query
    rows = query_reconcile(
        conn,
        gateway=_upper(getattr(args, "gateway", None)),
        symbol=_upper(getattr(args, "symbol", None)),
        from_date=args.from_date,
        to_date=args.to_date,
    )
    if not rows:
        print("OK — no discrepancies found.")
        return _RECONCILE_COLS, []
    return _RECONCILE_COLS, rows


def _upper(val: str | None) -> str | None:
    return val.upper() if val else None


def _run_prune(db_path: Path, args: argparse.Namespace) -> None:
    """Execute or dry-run the 90-day retention prune."""
    import sqlite3

    days: int = args.days
    if days < 1:
        print("[ERROR] --days must be >= 1", file=sys.stderr)
        raise SystemExit(2)

    try:
        conn = _open_writer(db_path)
    except Exception as exc:
        print(f"[ERROR] Could not open clearing DB: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    try:
        if args.dry_run:
            count = conn.execute(
                "SELECT COUNT(*) FROM trade_events WHERE trade_date < date('now', ?)",
                (f"-{days} days",),
            ).fetchone()[0]
            print(
                f"DRY RUN: {count} trade_events rows would be deleted (>{days} days old)."
            )
        else:
            deleted = prune_old_events(conn, retention_days=days)
            print(f"Pruned {deleted} trade_events rows older than {days} days.")
    except sqlite3.Error as exc:
        print(f"[ERROR] Prune failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    import sqlite3

    from edumatcher.config import DATA_DIR

    parser = _build_parser()
    args = parser.parse_args()

    try:
        _validate_args(args)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    if args.datapath is not None:
        dp = Path(args.datapath).expanduser()
        db_path = dp if dp.suffix == ".db" else dp / args.db_name
    else:
        db_path = DATA_DIR / args.db_name

    # prune needs write access; all other verbs are read-only.
    if args.command == "prune":
        _run_prune(db_path, args)
        return
    try:
        conn = open_readonly_connection(db_path)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except sqlite3.Error as exc:
        print(f"[ERROR] Could not open clearing DB: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    try:
        columns, rows = _run_query(conn, args, db_path)
    except (sqlite3.Error, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        conn.close()

    if not args.raw_output:
        rows = _normalize_rows(args.command, rows)

    if args.format == "json":
        _render_json(rows, columns)
        return

    if args.format == "csv":
        _render_csv(rows, columns, no_header=args.no_header)
        return

    _render_table(rows, columns, no_header=args.no_header)


if __name__ == "__main__":
    main()

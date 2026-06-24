"""pm-stats-cli - read-only statistics queries for stats.db."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from edumatcher.config import STATS_DB_FILE
from edumatcher.stats.query import (
    open_readonly_connection,
    query_daily,
    query_dates,
    query_order_events,
    query_order_lifecycle,
    query_snapshots,
    query_symbols,
    query_trades,
    validate_date,
    validate_iso_ts,
)

_FORMATS = ("table", "json", "csv")

_DAILY_DEFAULT_COLUMNS = [
    "date",
    "symbol",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "trade_count",
    "vwap",
]
_DAILY_WIDE_COLUMNS = [
    "date",
    "symbol",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "open_bid",
    "open_ask",
    "close_bid",
    "close_ask",
    "volume",
    "trade_count",
    "vwap",
    "largest_trade_qty",
    "largest_trade_price",
]
_SNAPSHOTS_COLUMNS = ["ts", "symbol", "mid_price", "best_bid", "best_ask", "pct_change"]
_TRADES_COLUMNS = [
    "ts",
    "trade_id",
    "symbol",
    "price",
    "quantity",
    "buy_gateway_id",
    "sell_gateway_id",
]
_ORDER_EVENTS_COLUMNS = [
    "seq",
    "ts",
    "event_type",
    "order_id",
    "gateway_id",
    "symbol",
    "side",
    "order_type",
    "tif",
    "price",
    "quantity",
    "remaining_qty",
    "status",
    "fill_price",
    "fill_qty",
    "trade_id",
    "reason",
    "client_order_id",
    "combo_parent_id",
    "oco_group_id",
    "priority_reset",
]
_SYMBOLS_COLUMNS = ["symbol"]
_DATES_COLUMNS = ["date"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm-stats-cli",
        description="Query EduMatcher statistics DB without writing SQL",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--db",
        default=str(STATS_DB_FILE),
        metavar="PATH",
        help=f"Statistics SQLite DB path (default: {STATS_DB_FILE})",
    )
    parser.add_argument(
        "--format",
        default="table",
        choices=_FORMATS,
        help="Output format (table, json, csv)",
    )
    parser.add_argument(
        "--no-header",
        action="store_true",
        help="Suppress header row for csv output",
    )

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    daily = sub.add_parser("daily", help="Show daily OHLCV summary rows")
    daily.add_argument("--date", metavar="YYYY-MM-DD")
    daily.add_argument("--symbol", metavar="SYMBOL")
    daily.add_argument("--limit", type=int, default=100, metavar="N")
    daily.add_argument(
        "--wide",
        action="store_true",
        help="Include bid/ask and largest-trade columns",
    )

    snapshots = sub.add_parser("snapshots", help="Show intraday price snapshots")
    snapshots.add_argument("--symbol", required=True, metavar="SYMBOL")
    snapshots.add_argument("--date", metavar="YYYY-MM-DD")
    snapshots.add_argument("--from", dest="from_ts", metavar="ISO_TS")
    snapshots.add_argument("--to", dest="to_ts", metavar="ISO_TS")
    snapshots.add_argument("--limit", type=int, default=500, metavar="N")

    trades = sub.add_parser("trades", help="Show matched trades")
    trades.add_argument("--symbol", metavar="SYMBOL")
    trades.add_argument("--date", metavar="YYYY-MM-DD")
    trades.add_argument("--from", dest="from_ts", metavar="ISO_TS")
    trades.add_argument("--to", dest="to_ts", metavar="ISO_TS")
    trades.add_argument("--limit", type=int, default=200, metavar="N")

    order_events = sub.add_parser(
        "order-events", help="Show private order lifecycle events"
    )
    order_events.add_argument("--gateway", required=True, metavar="GATEWAY_ID")
    order_events.add_argument("--symbol", metavar="SYMBOL")
    order_events.add_argument("--event-type", metavar="TYPE")
    order_events.add_argument("--date", metavar="YYYY-MM-DD")
    order_events.add_argument("--from", dest="from_ts", metavar="ISO_TS")
    order_events.add_argument("--to", dest="to_ts", metavar="ISO_TS")
    order_events.add_argument("--limit", type=int, default=500, metavar="N")

    lifecycle = sub.add_parser(
        "order-lifecycle", help="Show all events for one order ID"
    )
    lifecycle.add_argument("--gateway", required=True, metavar="GATEWAY_ID")
    lifecycle.add_argument("--order-id", required=True, metavar="ORDER_ID")

    symbols = sub.add_parser("symbols", help="List symbols present in stats DB")
    symbols.add_argument("--date", metavar="YYYY-MM-DD")

    dates = sub.add_parser("dates", help="List available trading dates")
    dates.add_argument("--symbol", metavar="SYMBOL")

    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if hasattr(args, "limit") and args.limit <= 0:
        raise ValueError("--limit must be > 0")

    if getattr(args, "date", None) is not None:
        validate_date(str(args.date))

    from_ts = getattr(args, "from_ts", None)
    to_ts = getattr(args, "to_ts", None)

    if from_ts is not None:
        validate_iso_ts(str(from_ts))
    if to_ts is not None:
        validate_iso_ts(str(to_ts))


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
        content_width = max((len(_stringify(row.get(col))) for row in rows), default=0)
        widths.append(max(len(col), content_width))

    def _line(values: list[str]) -> str:
        parts = [
            value.ljust(width) for value, width in zip(values, widths, strict=True)
        ]
        return " | ".join(parts)

    if not no_header:
        print(_line(columns))
        print("-+-".join("-" * width for width in widths))

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


def _run_query(
    conn: sqlite3.Connection, args: argparse.Namespace
) -> tuple[list[str], list[dict[str, Any]]]:
    if args.command == "daily":
        rows = query_daily(
            conn,
            date_value=args.date,
            symbol=args.symbol.upper() if args.symbol else None,
            limit=args.limit,
        )
        columns = _DAILY_WIDE_COLUMNS if args.wide else _DAILY_DEFAULT_COLUMNS
        return columns, rows

    if args.command == "snapshots":
        rows = query_snapshots(
            conn,
            symbol=args.symbol.upper(),
            date_value=args.date,
            from_ts=args.from_ts,
            to_ts=args.to_ts,
            limit=args.limit,
        )
        return _SNAPSHOTS_COLUMNS, rows

    if args.command == "trades":
        rows = query_trades(
            conn,
            symbol=args.symbol.upper() if args.symbol else None,
            date_value=args.date,
            from_ts=args.from_ts,
            to_ts=args.to_ts,
            limit=args.limit,
        )
        return _TRADES_COLUMNS, rows

    if args.command == "order-events":
        rows = query_order_events(
            conn,
            gateway_id=args.gateway.upper(),
            symbol=args.symbol.upper() if args.symbol else None,
            event_type=args.event_type.upper() if args.event_type else None,
            date_value=args.date,
            from_ts=args.from_ts,
            to_ts=args.to_ts,
            limit=args.limit,
        )
        return _ORDER_EVENTS_COLUMNS, rows

    if args.command == "order-lifecycle":
        rows = query_order_lifecycle(
            conn,
            gateway_id=args.gateway.upper(),
            order_id=args.order_id,
        )
        return _ORDER_EVENTS_COLUMNS, rows

    if args.command == "symbols":
        rows = query_symbols(conn, date_value=args.date)
        return _SYMBOLS_COLUMNS, rows

    assert args.command == "dates", f"Unhandled command: {args.command}"
    rows = query_dates(conn, symbol=args.symbol.upper() if args.symbol else None)
    return _DATES_COLUMNS, rows


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        _validate_args(args)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    db_path = Path(args.db).expanduser()

    try:
        conn = open_readonly_connection(db_path)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except sqlite3.Error as exc:
        print(f"[ERROR] Could not open SQLite database: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    try:
        columns, rows = _run_query(conn, args)
    except sqlite3.Error as exc:
        print(f"[ERROR] Query failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        conn.close()

    if args.format == "json":
        _render_json(rows, columns)
        return

    if args.format == "csv":
        _render_csv(rows, columns, no_header=args.no_header)
        return

    _render_table(rows, columns, no_header=args.no_header)


if __name__ == "__main__":
    main()

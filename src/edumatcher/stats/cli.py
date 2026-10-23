"""pm-stats-cli - read-only statistics queries for stats.db."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from datetime import tzinfo
from pathlib import Path
from typing import Any, TypedDict

from edumatcher.config import STATS_DB_FILE, STATS_HEALTH_ADDR, resolve_data_path
from edumatcher.healthcheck import (
    PING_TIMEOUT_MS,
    find_process_pids,
    format_bytes,
    ping_health_endpoint,
    run_with_timeout,
)
from edumatcher.stats.event_types import EVENT_TYPES
from edumatcher.stats.main import SCHEMA_VERSION
from edumatcher.stats.query import (
    InvalidCursorError,
    open_readonly_connection,
    query_daily,
    query_dates,
    query_feed_gaps,
    query_index_daily,
    query_index_ids,
    query_index_snapshots,
    query_instruments,
    query_order_events,
    query_order_lifecycle,
    query_price_snapshots,
    query_symbols,
    query_trades,
    resolve_session_timezone,
    to_display_prices,
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
    "turnover",
    "vwap",
    "largest_trade_qty",
    "largest_trade_price",
    "tick_decimals",
]
_SNAPSHOTS_COLUMNS = ["ts", "symbol", "mid_price", "best_bid", "best_ask", "pct_change"]
_TRADES_COLUMNS = [
    "ts",
    "trade_id",
    "symbol",
    "price",
    "quantity",
    "aggressor_side",
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
    "trade_ids",
    "reason",
    "client_tag",
    "combo_parent_id",
    "oco_group_id",
    "priority_reset",
]
_SYMBOLS_COLUMNS = ["symbol"]
_DATES_COLUMNS = ["date"]
_INDEX_DAILY_COLUMNS = [
    "date",
    "index_id",
    "open_level",
    "high_level",
    "low_level",
    "close_level",
    "close_session_state",
    "update_count",
]
_INDEX_DAILY_WIDE_COLUMNS = [
    "date",
    "index_id",
    "open_level",
    "high_level",
    "low_level",
    "close_level",
    "close_session_state",
    "open_aggregate_cap",
    "close_aggregate_cap",
    "update_count",
]
_INDEX_SNAPSHOTS_COLUMNS = [
    "ts",
    "index_id",
    "level",
    "aggregate_cap",
    "divisor",
    "session_state",
    "day_open",
    "day_high",
    "day_low",
]
_INDEX_IDS_COLUMNS = ["index_id"]
_INSTRUMENTS_COLUMNS = [
    "symbol",
    "tick_decimals",
    "tick_size",
    "currency",
    "source",
    "updated_ts",
]
_FEED_GAPS_COLUMNS = [
    "seq",
    "ts",
    "stream",
    "expected_id",
    "received_id",
    "missing_count",
]

_AFTER_HELP = (
    "Opaque cursor from a previous run's truncation notice; fetches the next page"
)

# The integrity/read-write check does a full-file PRAGMA quick_check, which on
# a multi-hundred-MB stats.db can run well past a few seconds -- opt-in via
# --extended rather than in every health call, and bounded so a check that
# never returns cannot hang the CLI indefinitely.
_EXTENDED_HEALTH_TIMEOUT_SEC = 45.0

_STATS_TABLES = (
    "trade_log",
    "order_events",
    "price_snapshots",
    "daily_stats",
    "feed_gaps",
)


class _HealthProcessReport(TypedDict):
    healthy: bool
    pids: list[int]
    detail: str


class _HealthDatabaseStats(TypedDict):
    size_bytes: int
    row_counts: dict[str, int]


class _HealthDatabaseReport(TypedDict):
    healthy: bool
    path: str
    detail: str
    checked: bool
    stats: _HealthDatabaseStats | None


class _HealthZmqReport(TypedDict):
    healthy: bool
    detail: str


class _HealthReport(TypedDict):
    healthy: bool
    process: _HealthProcessReport
    database: _HealthDatabaseReport
    zmq: _HealthZmqReport


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm-stats-cli",
        description="Query EduMatcher statistics DB without writing SQL",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-stats-cli")
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
        help="Suppress header row for table and csv output",
    )
    parser.add_argument(
        "--timezone",
        metavar="TZ",
        default=None,
        help=(
            "Override the session timezone that --date resolves in. By default "
            "the timezone the database was recorded with is used, so this is "
            "rarely needed; overriding with a different value warns, because "
            "--date will then select a different trading day than pm-stats used"
        ),
    )

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    daily = sub.add_parser("daily", help="Show daily OHLCV summary rows")
    daily.add_argument("--date", metavar="YYYY-MM-DD")
    daily.add_argument(
        "--from-date",
        dest="from_date",
        metavar="YYYY-MM-DD",
        help="Start of an inclusive multi-day range (oldest first)",
    )
    daily.add_argument(
        "--to-date",
        dest="to_date",
        metavar="YYYY-MM-DD",
        help="End of an inclusive multi-day range",
    )
    daily.add_argument("--symbol", metavar="SYMBOL")
    daily.add_argument("--limit", type=int, default=100, metavar="N")
    daily.add_argument("--after", metavar="CURSOR", help=_AFTER_HELP)
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
    snapshots.add_argument("--after", metavar="CURSOR", help=_AFTER_HELP)

    trades = sub.add_parser("trades", help="Show matched trades")
    trades.add_argument("--symbol", metavar="SYMBOL")
    trades.add_argument("--date", metavar="YYYY-MM-DD")
    trades.add_argument("--from", dest="from_ts", metavar="ISO_TS")
    trades.add_argument("--to", dest="to_ts", metavar="ISO_TS")
    trades.add_argument("--limit", type=int, default=200, metavar="N")
    trades.add_argument("--after", metavar="CURSOR", help=_AFTER_HELP)

    order_events = sub.add_parser(
        "order-events", help="Show private order lifecycle events"
    )
    order_events.add_argument("--gateway", required=True, metavar="GATEWAY_ID")
    order_events.add_argument("--symbol", metavar="SYMBOL")
    order_events.add_argument(
        "--event-type",
        metavar="TYPE",
        choices=EVENT_TYPES,
        type=str.upper,
        help="One of: " + ", ".join(EVENT_TYPES),
    )
    order_events.add_argument("--date", metavar="YYYY-MM-DD")
    order_events.add_argument("--from", dest="from_ts", metavar="ISO_TS")
    order_events.add_argument("--to", dest="to_ts", metavar="ISO_TS")
    order_events.add_argument("--limit", type=int, default=500, metavar="N")
    order_events.add_argument("--after", metavar="CURSOR", help=_AFTER_HELP)

    lifecycle = sub.add_parser(
        "order-lifecycle", help="Show all events for one order ID"
    )
    lifecycle.add_argument("--gateway", required=True, metavar="GATEWAY_ID")
    lifecycle.add_argument("--order-id", required=True, metavar="ORDER_ID")

    symbols = sub.add_parser("symbols", help="List symbols present in stats DB")
    symbols.add_argument("--date", metavar="YYYY-MM-DD")

    dates = sub.add_parser("dates", help="List available trading dates")
    dates.add_argument("--symbol", metavar="SYMBOL")

    index_daily = sub.add_parser(
        "index-daily", help="Show daily index OHLC summary rows"
    )
    index_daily.add_argument("--date", metavar="YYYY-MM-DD")
    index_daily.add_argument(
        "--from-date",
        dest="from_date",
        metavar="YYYY-MM-DD",
        help="Start of an inclusive multi-day range (oldest first)",
    )
    index_daily.add_argument(
        "--to-date",
        dest="to_date",
        metavar="YYYY-MM-DD",
        help="End of an inclusive multi-day range",
    )
    index_daily.add_argument("--index-id", metavar="INDEX_ID")
    index_daily.add_argument("--limit", type=int, default=100, metavar="N")
    index_daily.add_argument("--after", metavar="CURSOR", help=_AFTER_HELP)
    index_daily.add_argument(
        "--wide",
        action="store_true",
        help="Include open/close aggregate market cap columns",
    )

    index_snapshots = sub.add_parser(
        "index-snapshots", help="Show intraday index level history"
    )
    index_snapshots.add_argument("--index-id", required=True, metavar="INDEX_ID")
    index_snapshots.add_argument("--date", metavar="YYYY-MM-DD")
    index_snapshots.add_argument("--from", dest="from_ts", metavar="ISO_TS")
    index_snapshots.add_argument("--to", dest="to_ts", metavar="ISO_TS")
    index_snapshots.add_argument("--limit", type=int, default=500, metavar="N")
    index_snapshots.add_argument("--after", metavar="CURSOR", help=_AFTER_HELP)

    index_ids = sub.add_parser("index-ids", help="List index IDs present in stats DB")
    index_ids.add_argument("--date", metavar="YYYY-MM-DD")

    instruments = sub.add_parser(
        "instruments",
        help="Show instrument reference data (tick scale per symbol)",
    )
    instruments.add_argument("--symbol", metavar="SYMBOL")

    gaps = sub.add_parser(
        "gaps", help="Show detected feed gaps (trades the recorder never received)"
    )
    gaps.add_argument("--date", metavar="YYYY-MM-DD")
    gaps.add_argument("--from", dest="from_ts", metavar="ISO_TS")
    gaps.add_argument("--to", dest="to_ts", metavar="ISO_TS")
    gaps.add_argument("--limit", type=int, default=500, metavar="N")

    health = sub.add_parser(
        "health",
        help="Check the pm-stats process and stats database read/write health",
    )
    health.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Print nothing; exit 0 when healthy or -1 otherwise",
    )
    health.add_argument(
        "--extended",
        action="store_true",
        help=(
            "Also check stats.db integrity and read/write access (PRAGMA "
            f"quick_check); allowed up to {_EXTENDED_HEALTH_TIMEOUT_SEC:.0f}s "
            "for a large database"
        ),
    )
    health.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=(
            "Describe exactly what was checked, plus database size and row "
            "counts when combined with --extended"
        ),
    )

    return parser


def _find_stats_pids() -> list[int]:
    """Find pm-stats processes without matching this pm-stats-cli process."""
    return find_process_pids("pm-stats")


def _collect_db_stats(conn: sqlite3.Connection, db_path: Path) -> _HealthDatabaseStats:
    """File size plus a row count per table, for --extended --verbose.

    Table names are fixed constants, never user input, so interpolating them
    into the query is safe.
    """
    row_counts = {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in _STATS_TABLES
    }
    return {"size_bytes": db_path.stat().st_size, "row_counts": row_counts}


def _check_database_health(
    db_path: Path, *, collect_stats: bool = False
) -> tuple[bool, str, _HealthDatabaseStats | None]:
    """Check integrity, schema version, and a rolled-back write transaction."""
    if not db_path.exists():
        return False, f"database not found: {db_path}", None
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(db_path), timeout=2.0)
        quick_check = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        if quick_check != "ok":
            return False, f"integrity check failed: {quick_check}", None
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version != SCHEMA_VERSION:
            return False, f"schema version {version}, expected {SCHEMA_VERSION}", None
        conn.execute("BEGIN")
        conn.execute("CREATE TEMP TABLE pm_stats_health_check (value INTEGER)")
        conn.execute("INSERT INTO pm_stats_health_check VALUES (1)")
        conn.rollback()
        stats = _collect_db_stats(conn, db_path) if collect_stats else None
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        return False, f"database read/write check failed: {exc}", None
    finally:
        if conn is not None:
            conn.close()
    return True, "read/write and integrity checks passed", stats


def _run_extended_database_check(
    db_path: Path,
    *,
    collect_stats: bool = False,
    timeout_sec: float = _EXTENDED_HEALTH_TIMEOUT_SEC,
) -> tuple[bool, str, _HealthDatabaseStats | None]:
    """Run `_check_database_health`, bounded by `timeout_sec`."""
    try:
        return run_with_timeout(
            lambda: _check_database_health(db_path, collect_stats=collect_stats),
            timeout_sec,
        )
    except TimeoutError as exc:
        return False, f"database check {exc}", None


def _check_zmq_health(timeout_ms: int = PING_TIMEOUT_MS) -> tuple[bool, str]:
    """Ping pm-stats's health REP socket and confirm it replies."""
    return ping_health_endpoint(STATS_HEALTH_ADDR, timeout_ms)


def _health_report(
    db_path: Path, *, extended: bool = False, collect_stats: bool = False
) -> tuple[bool, _HealthReport]:
    pids = _find_stats_pids()
    zmq_ok, zmq_detail = _check_zmq_health()
    if extended:
        db_ok, db_detail, db_stats = _run_extended_database_check(
            db_path, collect_stats=collect_stats
        )
        db_checked = True
    else:
        db_ok, db_detail, db_stats = (
            True,
            "skipped (pass --extended to check integrity and read/write access)",
            None,
        )
        db_checked = False
    report: _HealthReport = {
        "healthy": bool(pids) and db_ok and zmq_ok,
        "process": {
            "healthy": bool(pids),
            "pids": pids,
            "detail": "pm-stats is running" if pids else "pm-stats process not found",
        },
        "database": {
            "healthy": db_ok,
            "path": str(db_path),
            "detail": db_detail,
            "checked": db_checked,
            "stats": db_stats,
        },
        "zmq": {"healthy": zmq_ok, "detail": zmq_detail},
    }
    return bool(report["healthy"]), report


def _validate_args(args: argparse.Namespace) -> None:
    if hasattr(args, "limit") and args.limit <= 0:
        raise ValueError("--limit must be > 0")

    for attr in ("date", "from_date", "to_date"):
        value = getattr(args, attr, None)
        if value is not None:
            validate_date(str(value))

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
    conn: sqlite3.Connection, args: argparse.Namespace, tz: tzinfo
) -> tuple[list[str], list[dict[str, Any]], str | None]:
    """Return ``(columns, rows, next_cursor)`` for the selected subcommand.

    The cursor is returned rather than discarded so ``main`` can tell the user
    the result was cut short at ``--limit``. Silently truncating is how a
    "count the trades" or "recompute the VWAP" check ends up producing a
    confidently wrong answer.
    """
    if args.command == "daily":
        rows, next_cursor = query_daily(
            conn,
            date_value=args.date,
            symbol=args.symbol.upper() if args.symbol else None,
            limit=args.limit,
            after=args.after,
            from_date=args.from_date,
            to_date=args.to_date,
        )
        columns = _DAILY_WIDE_COLUMNS if args.wide else _DAILY_DEFAULT_COLUMNS
        return columns, to_display_prices(rows, "daily"), next_cursor

    if args.command == "snapshots":
        rows, next_cursor = query_price_snapshots(
            conn,
            symbol=args.symbol.upper(),
            date_value=args.date,
            from_ts=args.from_ts,
            to_ts=args.to_ts,
            limit=args.limit,
            tz=tz,
            after=args.after,
        )
        return _SNAPSHOTS_COLUMNS, to_display_prices(rows, "snapshots"), next_cursor

    if args.command == "trades":
        rows, next_cursor = query_trades(
            conn,
            symbol=args.symbol.upper() if args.symbol else None,
            date_value=args.date,
            from_ts=args.from_ts,
            to_ts=args.to_ts,
            limit=args.limit,
            tz=tz,
            after=args.after,
        )
        return _TRADES_COLUMNS, to_display_prices(rows, "trades"), next_cursor

    if args.command == "order-events":
        rows, next_cursor = query_order_events(
            conn,
            gateway_id=args.gateway.upper(),
            symbol=args.symbol.upper() if args.symbol else None,
            event_type=args.event_type.upper() if args.event_type else None,
            date_value=args.date,
            from_ts=args.from_ts,
            to_ts=args.to_ts,
            limit=args.limit,
            tz=tz,
            after=args.after,
        )
        return _ORDER_EVENTS_COLUMNS, rows, next_cursor

    if args.command == "order-lifecycle":
        rows = query_order_lifecycle(
            conn,
            gateway_id=args.gateway.upper(),
            order_id=args.order_id,
        )
        return _ORDER_EVENTS_COLUMNS, rows, None

    if args.command == "symbols":
        rows = query_symbols(conn, date_value=args.date, tz=tz)
        return _SYMBOLS_COLUMNS, rows, None

    if args.command == "dates":
        rows = query_dates(conn, symbol=args.symbol.upper() if args.symbol else None)
        return _DATES_COLUMNS, rows, None

    if args.command == "index-daily":
        rows, next_cursor = query_index_daily(
            conn,
            date_value=args.date,
            index_id=args.index_id.upper() if args.index_id else None,
            limit=args.limit,
            after=args.after,
            from_date=args.from_date,
            to_date=args.to_date,
        )
        columns = _INDEX_DAILY_WIDE_COLUMNS if args.wide else _INDEX_DAILY_COLUMNS
        return columns, rows, next_cursor

    if args.command == "index-snapshots":
        rows, next_cursor = query_index_snapshots(
            conn,
            index_id=args.index_id.upper(),
            date_value=args.date,
            from_ts=args.from_ts,
            to_ts=args.to_ts,
            limit=args.limit,
            tz=tz,
            after=args.after,
        )
        return _INDEX_SNAPSHOTS_COLUMNS, rows, next_cursor

    if args.command == "instruments":
        rows = query_instruments(
            conn, symbol=args.symbol.upper() if args.symbol else None
        )
        return _INSTRUMENTS_COLUMNS, rows, None

    if args.command == "gaps":
        rows = query_feed_gaps(
            conn,
            date_value=args.date,
            from_ts=args.from_ts,
            to_ts=args.to_ts,
            limit=args.limit,
            tz=tz,
        )
        return _FEED_GAPS_COLUMNS, rows, None

    assert args.command == "index-ids", f"Unhandled command: {args.command}"
    rows = query_index_ids(conn, date_value=args.date, tz=tz)
    return _INDEX_IDS_COLUMNS, rows, None


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        _validate_args(args)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    db_path = resolve_data_path(args.db)

    if args.command == "health":
        try:
            healthy, report = _health_report(
                db_path,
                extended=args.extended,
                collect_stats=args.extended and args.verbose,
            )
        except (OSError, ValueError) as exc:
            healthy = False
            report = _HealthReport(
                healthy=False,
                process={
                    "healthy": False,
                    "pids": [],
                    "detail": str(exc),
                },
                database={
                    "healthy": False,
                    "path": str(db_path),
                    "detail": "health check could not run",
                    "checked": False,
                    "stats": None,
                },
                zmq={"healthy": False, "detail": "health check could not run"},
            )
        if args.quiet:
            raise SystemExit(0 if healthy else -1)
        if args.format == "json":
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            process = report["process"]
            database = report["database"]
            zmq_report = report["zmq"]
            print(
                f"pm-stats process: {'OK' if process['healthy'] else 'FAIL'} - {process['detail']}"
            )
            print(
                f"stats database:  {'OK' if database['healthy'] else 'FAIL'} - {database['detail']}"
            )
            print(
                f"stats ZMQ ping:  {'OK' if zmq_report['healthy'] else 'FAIL'} - {zmq_report['detail']}"
            )
            print(f"health: {'OK' if healthy else 'FAIL'}")
            if args.verbose:
                print()
                print("Checks performed:")
                print("  pm-stats process (pgrep):      yes")
                print("  ZMQ health ping:                yes")
                print(
                    "  Database integrity/read-write: "
                    + ("yes" if database["checked"] else "no (pass --extended)")
                )
                stats = database["stats"]
                if stats is not None:
                    print()
                    print("Database stats:")
                    print(f"  path: {database['path']}")
                    print(f"  size: {format_bytes(stats['size_bytes'])}")
                    for table, count in stats["row_counts"].items():
                        print(f"  {table} rows: {count}")
        raise SystemExit(0 if healthy else 1)

    try:
        conn = open_readonly_connection(db_path)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except sqlite3.Error as exc:
        print(f"[ERROR] Could not open SQLite database: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    try:
        tz, tz_warning = resolve_session_timezone(conn, args.timezone)
    except ValueError as exc:
        conn.close()
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if tz_warning is not None:
        print(f"[WARN] {tz_warning}", file=sys.stderr)

    try:
        columns, rows, next_cursor = _run_query(conn, args, tz)
    except InvalidCursorError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except sqlite3.Error as exc:
        print(f"[ERROR] Query failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        conn.close()

    if args.format == "json":
        _render_json(rows, columns)
    elif args.format == "csv":
        _render_csv(rows, columns, no_header=args.no_header)
    else:
        _render_table(rows, columns, no_header=args.no_header)

    # On stderr so it cannot corrupt a redirected CSV or JSON payload, but is
    # still visible to anyone reading the terminal.
    if next_cursor is not None:
        print(
            f"[WARN] Output truncated at --limit {args.limit}. More rows exist; "
            f"re-run with --after {next_cursor} for the next page.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()

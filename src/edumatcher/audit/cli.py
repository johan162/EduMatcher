"""pm-audit-cli — read-only query tool for EduMatcher audit logs.

Reads the JSONL log files written by ``pm-audit`` directly from disk.
No ZeroMQ connection is made; the tool works even when ``pm-audit`` is not
running as long as the log files exist.

Usage::

    pm-audit-cli [global-options] COMMAND [command-options]

Global options
--------------
  --log-file PATH     Primary audit log file (default: data/audit.log)
  --log-dir  PATH     Directory for rotated log backups (default: log file parent)
  --format   FORMAT   Output format: table (default), json, or csv
  --no-header         Suppress header row for csv output
  --use-index PATH    Use SQLite index for queries (auto-detected if omitted)

Commands
--------
  events      Search log entries by topic, gateway, symbol, time range
  orders      Find order lifecycle events for specific order IDs
  trades      Find trade executions with filters
  topics      List topics present in logs with event counts
  gateways    List gateways and summarise their activity
  timeline    Show raw chronological event stream
  stats       Show summary statistics about log files
  index       Build or update the optional SQLite index
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from edumatcher.audit.formatters import render, render_stats
from edumatcher.audit.indexer import (
    build_index,
    index_is_available,
    open_readonly_index,
    query_index_events,
)
from edumatcher.audit.query import (
    discover_log_files,
    parse_ts,
    query_events,
    query_gateways,
    query_orders,
    query_stats,
    query_timeline,
    query_topics,
    query_trades,
    validate_date,
    validate_iso_ts,
)
from edumatcher.config import AUDIT_LOG_FILE

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FORMATS = ("table", "json", "csv")
_DEFAULT_INDEX_NAME = "audit_index.db"

# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------

_EVENTS_COLS = ["timestamp", "topic", "gateway", "symbol", "order_id", "summary"]
_ORDERS_COLS = [
    "timestamp",
    "order_id",
    "event",
    "gateway",
    "symbol",
    "side",
    "qty",
    "price",
    "status",
]
_TRADES_COLS = [
    "timestamp",
    "trade_id",
    "symbol",
    "price",
    "quantity",
    "buy_gateway",
    "sell_gateway",
    "aggressor",
]
_TOPICS_COLS = ["topic", "count", "first_seen", "last_seen"]
_GATEWAYS_COLS = [
    "gateway_id",
    "events",
    "orders",
    "fills",
    "trades",
    "first_seen",
    "last_seen",
]
_TIMELINE_COLS = ["timestamp", "topic", "gateway", "symbol", "payload"]

# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm-audit-cli",
        description=(
            "Query EduMatcher audit logs without shell pipelines.\n"
            "Reads JSONL files written by pm-audit directly from disk."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-audit-cli")

    parser.add_argument(
        "--log-file",
        default=str(AUDIT_LOG_FILE),
        metavar="PATH",
        help=f"Primary audit log file (default: {AUDIT_LOG_FILE})",
    )
    parser.add_argument(
        "--log-dir",
        default=None,
        metavar="PATH",
        help=(
            "Directory containing rotated log backups.\n"
            "Defaults to the directory containing --log-file."
        ),
    )
    parser.add_argument(
        "--format",
        default="table",
        choices=_FORMATS,
        help="Output format: table (default), json, or csv",
    )
    parser.add_argument(
        "--no-header",
        action="store_true",
        help="Suppress header row for csv output",
    )
    parser.add_argument(
        "--use-index",
        default=None,
        metavar="PATH",
        help=(
            "Path to SQLite index file.\n"
            "Auto-detected from --log-dir when not specified.\n"
            "Ignored for commands that do not support it."
        ),
    )

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    # ------------------------------------------------------------------ events
    ev = sub.add_parser(
        "events",
        help="Search log entries by topic, gateway, symbol, and time range",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    ev.add_argument(
        "--topic", metavar="PREFIX", help="Topic prefix filter (e.g. order.fill)"
    )
    ev.add_argument("--gateway", metavar="GW_ID", help="Filter by gateway ID")
    ev.add_argument("--symbol", metavar="SYMBOL", help="Filter by symbol")
    ev.add_argument("--date", metavar="YYYY-MM-DD", help="Restrict to a trading date")
    ev.add_argument(
        "--from", dest="from_ts", metavar="ISO_TS", help="Start of time range"
    )
    ev.add_argument("--to", dest="to_ts", metavar="ISO_TS", help="End of time range")
    ev.add_argument(
        "--limit",
        type=int,
        default=100,
        metavar="N",
        help="Maximum rows (default: 100)",
    )
    ev.add_argument("--reverse", action="store_true", help="Show newest first")

    # ------------------------------------------------------------------ orders
    od = sub.add_parser(
        "orders",
        help="Find order lifecycle events for specific order IDs or filters",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    od.add_argument(
        "--id",
        dest="order_ids",
        action="append",
        metavar="ORDER_ID",
        help="Order ID to search for (repeatable)",
    )
    od.add_argument("--gateway", metavar="GW_ID", help="Filter by gateway ID")
    od.add_argument("--symbol", metavar="SYMBOL", help="Filter by symbol")
    od.add_argument("--date", metavar="YYYY-MM-DD", help="Restrict to a trading date")
    od.add_argument(
        "--from", dest="from_ts", metavar="ISO_TS", help="Start of time range"
    )
    od.add_argument("--to", dest="to_ts", metavar="ISO_TS", help="End of time range")
    od.add_argument(
        "--limit",
        type=int,
        default=100,
        metavar="N",
        help="Maximum rows (default: 100)",
    )

    # ------------------------------------------------------------------ trades
    tr = sub.add_parser(
        "trades",
        help="Find trade executions with filters",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    tr.add_argument("--symbol", metavar="SYMBOL", help="Filter by symbol")
    tr.add_argument(
        "--gateway", metavar="GW_ID", help="Filter by buyer or seller gateway"
    )
    tr.add_argument("--buy-gateway", metavar="GW_ID", help="Filter by buyer gateway")
    tr.add_argument("--sell-gateway", metavar="GW_ID", help="Filter by seller gateway")
    tr.add_argument(
        "--min-price", type=float, metavar="PRICE", help="Minimum trade price"
    )
    tr.add_argument(
        "--max-price", type=float, metavar="PRICE", help="Maximum trade price"
    )
    tr.add_argument("--min-qty", type=int, metavar="QTY", help="Minimum trade quantity")
    tr.add_argument("--date", metavar="YYYY-MM-DD", help="Trading date")
    tr.add_argument(
        "--from", dest="from_ts", metavar="ISO_TS", help="Start of time range"
    )
    tr.add_argument("--to", dest="to_ts", metavar="ISO_TS", help="End of time range")
    tr.add_argument(
        "--limit",
        type=int,
        default=100,
        metavar="N",
        help="Maximum rows (default: 100)",
    )
    tr.add_argument("--reverse", action="store_true", help="Show newest first")

    # ------------------------------------------------------------------ topics
    tp = sub.add_parser(
        "topics",
        help="List topics present in logs with event counts",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    tp.add_argument("--date", metavar="YYYY-MM-DD", help="Restrict to a trading date")
    tp.add_argument(
        "--from", dest="from_ts", metavar="ISO_TS", help="Start of time range"
    )
    tp.add_argument("--to", dest="to_ts", metavar="ISO_TS", help="End of time range")
    tp.add_argument(
        "--prefix", metavar="PREFIX", help="Filter topics by prefix (e.g. order.)"
    )
    tp.add_argument(
        "--sort",
        default="count",
        choices=("count", "alpha"),
        help="Sort by event count (default) or alphabetically",
    )

    # ---------------------------------------------------------------- gateways
    gw = sub.add_parser(
        "gateways",
        help="List gateways and summarise their audit trail activity",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    gw.add_argument("--date", metavar="YYYY-MM-DD", help="Trading date")
    gw.add_argument(
        "--from", dest="from_ts", metavar="ISO_TS", help="Start of time range"
    )
    gw.add_argument("--to", dest="to_ts", metavar="ISO_TS", help="End of time range")
    gw.add_argument(
        "--min-events",
        type=int,
        metavar="N",
        help="Minimum events to include a gateway",
    )

    # ---------------------------------------------------------------- timeline
    tl = sub.add_parser(
        "timeline",
        help="Show raw chronological event stream for session replay",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    tl.add_argument("--from", dest="from_ts", metavar="ISO_TS", help="Start time")
    tl.add_argument("--to", dest="to_ts", metavar="ISO_TS", help="End time")
    tl.add_argument("--topic", metavar="PREFIX", help="Filter by topic prefix")
    tl.add_argument("--gateway", metavar="GW_ID", help="Filter by gateway")
    tl.add_argument("--symbol", metavar="SYMBOL", help="Filter by symbol")
    tl.add_argument(
        "--limit",
        type=int,
        default=500,
        metavar="N",
        help="Maximum events (default: 500)",
    )

    # ------------------------------------------------------------------- stats
    st = sub.add_parser(
        "stats",
        help="Show summary statistics about audit log files",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    st.add_argument("--verbose", action="store_true", help="Show per-file breakdown")

    # ------------------------------------------------------------------- index
    ix = sub.add_parser(
        "index",
        help="Build or update the optional SQLite index for faster queries",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    ix.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help=f"SQLite database path (default: <log-dir>/{_DEFAULT_INDEX_NAME})",
    )
    ix.add_argument(
        "--days", type=int, default=None, metavar="N", help="Index last N days only"
    )
    ix.add_argument(
        "--from", dest="from_ts", metavar="ISO_TS", help="Start of index range"
    )
    ix.add_argument("--to", dest="to_ts", metavar="ISO_TS", help="End of index range")
    ix.add_argument("--rebuild", action="store_true", help="Rebuild index from scratch")
    ix.add_argument(
        "--incremental",
        action="store_true",
        help="Add only new entries since last index",
    )

    return parser


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


def _validate_args(args: argparse.Namespace) -> None:
    """Validate common flags; raises ``ValueError`` on bad input."""
    if hasattr(args, "limit") and args.limit is not None and args.limit <= 0:
        raise ValueError("--limit must be > 0")

    if getattr(args, "date", None) is not None:
        validate_date(str(args.date))

    for attr in ("from_ts", "to_ts"):
        val = getattr(args, attr, None)
        if val is not None:
            validate_iso_ts(str(val))

    if args.command == "index":
        days = getattr(args, "days", None)
        if days is not None and days <= 0:
            raise ValueError("--days must be > 0")
        if getattr(args, "rebuild", False) and getattr(args, "incremental", False):
            raise ValueError("--rebuild and --incremental are mutually exclusive")


# ---------------------------------------------------------------------------
# Time range resolution
# ---------------------------------------------------------------------------


def _resolve_time_range(
    args: argparse.Namespace,
) -> tuple[datetime | None, datetime | None]:
    from_dt: datetime | None = None
    to_dt: datetime | None = None

    from_ts = getattr(args, "from_ts", None)
    to_ts = getattr(args, "to_ts", None)

    if from_ts is not None:
        from_dt = parse_ts(str(from_ts))
    if to_ts is not None:
        to_dt = parse_ts(str(to_ts))
    return from_dt, to_dt


# ---------------------------------------------------------------------------
# Index path resolution
# ---------------------------------------------------------------------------


def _resolve_index_path(args: argparse.Namespace, log_file: Path) -> Path:
    if args.use_index is not None:
        return Path(args.use_index).expanduser()
    return log_file.parent / _DEFAULT_INDEX_NAME


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _handle_events(
    args: argparse.Namespace,
    log_files: list[Path],
    index_path: Path,
) -> tuple[list[str], list[dict[str, Any]]]:
    from_dt, to_dt = _resolve_time_range(args)

    # Prefer the SQLite index when available
    if index_is_available(index_path):
        try:
            conn = open_readonly_index(index_path)
            rows = query_index_events(
                conn,
                topic_prefix=args.topic,
                gateway=args.gateway.upper() if args.gateway else None,
                symbol=args.symbol.upper() if args.symbol else None,
                from_dt=from_dt,
                to_dt=to_dt,
                date_str=args.date,
                limit=args.limit,
                reverse=getattr(args, "reverse", False),
            )
            conn.close()
            # Map index row fields to events columns
            mapped: list[dict[str, Any]] = []
            for r in rows:
                import json as _json

                payload = r.get("payload", "{}")
                try:
                    p = _json.loads(payload) if isinstance(payload, str) else payload
                except Exception:
                    p = {}
                mapped.append(
                    {
                        "timestamp": r.get("timestamp"),
                        "topic": r.get("topic"),
                        "gateway": r.get("gateway_id"),
                        "symbol": r.get("symbol"),
                        "order_id": r.get("order_id"),
                        "summary": str(p)[:80] if p else "",
                    }
                )
            return _EVENTS_COLS, mapped
        except Exception:
            pass  # Fall through to JSONL

    rows = query_events(
        log_files,
        topic=args.topic,
        gateway=args.gateway.upper() if args.gateway else None,
        symbol=args.symbol.upper() if args.symbol else None,
        from_dt=from_dt,
        to_dt=to_dt,
        date_str=args.date,
        limit=args.limit,
        reverse=getattr(args, "reverse", False),
    )
    return _EVENTS_COLS, rows


def _handle_orders(
    args: argparse.Namespace,
    log_files: list[Path],
) -> tuple[list[str], list[dict[str, Any]]]:
    from_dt, to_dt = _resolve_time_range(args)
    rows = query_orders(
        log_files,
        order_ids=args.order_ids,
        gateway=args.gateway.upper() if args.gateway else None,
        symbol=args.symbol.upper() if args.symbol else None,
        from_dt=from_dt,
        to_dt=to_dt,
        date_str=args.date,
        limit=args.limit,
    )
    return _ORDERS_COLS, rows


def _handle_trades(
    args: argparse.Namespace,
    log_files: list[Path],
) -> tuple[list[str], list[dict[str, Any]]]:
    from_dt, to_dt = _resolve_time_range(args)
    rows = query_trades(
        log_files,
        symbol=args.symbol.upper() if args.symbol else None,
        gateway=args.gateway.upper() if args.gateway else None,
        buy_gateway=args.buy_gateway.upper() if args.buy_gateway else None,
        sell_gateway=args.sell_gateway.upper() if args.sell_gateway else None,
        min_price=args.min_price,
        max_price=args.max_price,
        min_qty=args.min_qty,
        from_dt=from_dt,
        to_dt=to_dt,
        date_str=args.date,
        limit=args.limit,
        reverse=getattr(args, "reverse", False),
    )
    return _TRADES_COLS, rows


def _handle_topics(
    args: argparse.Namespace,
    log_files: list[Path],
) -> tuple[list[str], list[dict[str, Any]]]:
    from_dt, to_dt = _resolve_time_range(args)
    rows = query_topics(
        log_files,
        prefix=args.prefix,
        from_dt=from_dt,
        to_dt=to_dt,
        date_str=args.date,
        sort_by=args.sort,
    )
    return _TOPICS_COLS, rows


def _handle_gateways(
    args: argparse.Namespace,
    log_files: list[Path],
) -> tuple[list[str], list[dict[str, Any]]]:
    from_dt, to_dt = _resolve_time_range(args)
    rows = query_gateways(
        log_files,
        from_dt=from_dt,
        to_dt=to_dt,
        date_str=args.date,
        min_events=args.min_events,
    )
    return _GATEWAYS_COLS, rows


def _handle_timeline(
    args: argparse.Namespace,
    log_files: list[Path],
) -> tuple[list[str], list[dict[str, Any]]]:
    from_dt, to_dt = _resolve_time_range(args)
    rows = query_timeline(
        log_files,
        topic_prefix=args.topic,
        gateway=args.gateway.upper() if args.gateway else None,
        symbol=args.symbol.upper() if args.symbol else None,
        from_dt=from_dt,
        to_dt=to_dt,
        limit=args.limit,
    )
    return _TIMELINE_COLS, rows


def _handle_stats(
    args: argparse.Namespace,
    log_files: list[Path],
) -> None:
    stats = query_stats(log_files, verbose=args.verbose)
    render_stats(stats, verbose=args.verbose)


def _handle_index(
    args: argparse.Namespace,
    log_file: Path,
    log_dir: Path | None,
) -> None:
    output_path = (
        Path(args.output).expanduser()
        if args.output
        else log_file.parent / _DEFAULT_INDEX_NAME
    )

    from_dt: datetime | None = None
    to_dt: datetime | None = None
    if getattr(args, "from_ts", None):
        from_dt = parse_ts(str(args.from_ts))
    if getattr(args, "to_ts", None):
        to_dt = parse_ts(str(args.to_ts))

    print(f"[INDEX] Building audit index at {output_path} …")
    inserted = build_index(
        output_path,
        log_file,
        log_dir,
        from_dt=from_dt,
        to_dt=to_dt,
        days=args.days,
        rebuild=args.rebuild,
        incremental=args.incremental,
    )
    print(f"[INDEX] Done — {inserted:,} rows inserted.")


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        _validate_args(args)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    log_file = Path(args.log_file).expanduser()
    log_dir = Path(args.log_dir).expanduser() if args.log_dir else None

    # stats and index do not need the log files to exist beforehand
    if args.command not in ("stats", "index") and not log_file.exists():
        if log_dir is None or not log_dir.is_dir():
            print(
                f"[ERROR] Audit log not found: {log_file}",
                file=sys.stderr,
            )
            raise SystemExit(1)

    log_files = discover_log_files(log_file, log_dir)
    index_path = _resolve_index_path(args, log_file)

    # --- stats (custom renderer) ---
    if args.command == "stats":
        _handle_stats(args, log_files)
        return

    # --- index (build, no table output) ---
    if args.command == "index":
        _handle_index(args, log_file, log_dir)
        return

    # --- tabular commands ---
    try:
        if args.command == "events":
            columns, rows = _handle_events(args, log_files, index_path)
        elif args.command == "orders":
            columns, rows = _handle_orders(args, log_files)
        elif args.command == "trades":
            columns, rows = _handle_trades(args, log_files)
        elif args.command == "topics":
            columns, rows = _handle_topics(args, log_files)
        elif args.command == "gateways":
            columns, rows = _handle_gateways(args, log_files)
        elif args.command == "timeline":
            columns, rows = _handle_timeline(args, log_files)
        else:
            print(f"[ERROR] Unknown command: {args.command}", file=sys.stderr)
            raise SystemExit(2)
    except Exception as exc:
        print(f"[ERROR] Query failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    render(rows, columns, args.format, no_header=args.no_header)


if __name__ == "__main__":
    main()

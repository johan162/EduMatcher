"""pm-audit-cli — read-only query tool for EduMatcher audit logs.

Reads the JSONL log files written by ``pm-audit`` directly from disk.
No ZeroMQ connection is made; the tool works even when ``pm-audit`` is not
running as long as the log files exist. The one exception is ``health``,
which pings pm-audit's health REP socket to confirm it is alive.

Usage::

    pm-audit-cli [global-options] COMMAND [command-options]

Global options
--------------
  --log-file PATH     Primary audit log file (default: data/audit.log)
  --log-dir  PATH     Directory holding audit/ (default: log file parent)
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
  health      Check the pm-audit process (and, with --extended, its log file)
  archive     Compress closed days' parts into one verified .zst per day

``events`` and ``timeline`` accept ``-f``/``--follow`` to keep printing new
entries as they are appended to the log, polling every ``--interval``
seconds (default 1.0) until interrupted with Ctrl-C.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from compression import zstd
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

from edumatcher.audit.archive import (
    DEFAULT_LEVEL,
    ArchiveBusy,
    ArchiveError,
    apply_retention,
    archive_content_size,
    archive_day,
    archive_lock,
    format_result,
    pending_days,
    session_timezone,
    today_in,
)
from edumatcher.audit.formatters import render, render_stats
from edumatcher.audit.indexer import (
    build_index,
    index_is_available,
    open_readonly_index,
    query_index_events,
)
from edumatcher.audit.query import (
    parse_line,
    discover_day_files,
    discover_log_files,
    is_explicit_file,
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
from edumatcher.config import AUDIT_HEALTH_ADDR, AUDIT_LOG_FILE
from edumatcher.healthcheck import (
    PING_TIMEOUT_MS,
    find_process_pids,
    format_bytes,
    ping_health_endpoint,
    read_last_line,
    run_with_timeout,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FORMATS = ("table", "json", "csv")
_DEFAULT_INDEX_NAME = "audit_index.db"

# The log-file check reads the tail of audit.log and opens it for append; both
# are normally instant, but on a stalled or network-mounted volume either can
# block -- opt-in via --extended rather than in every health call, and bounded
# so a check that never returns cannot hang the CLI indefinitely.
_EXTENDED_HEALTH_TIMEOUT_SEC = 15.0


class _HealthProcessReport(TypedDict):
    healthy: bool
    pids: list[int]
    detail: str


class _HealthLogFileStats(TypedDict):
    size_bytes: int
    parts: int
    parts_bytes: int
    archives: int
    archives_bytes: int
    #: Uncompressed size of the archives, None when one does not record it.
    archives_content_bytes: int | None
    total_size_bytes: int
    last_entry_ts: str | None


class _HealthLogFileReport(TypedDict):
    healthy: bool
    path: str
    detail: str
    checked: bool
    stats: _HealthLogFileStats | None


class _HealthZmqReport(TypedDict):
    healthy: bool
    detail: str


class _HealthReport(TypedDict):
    healthy: bool
    process: _HealthProcessReport
    log_file: _HealthLogFileReport
    zmq: _HealthZmqReport


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
    "reason",
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


#: The commands whose ``--date`` selects a trading day's files.
_DATE_COMMANDS = frozenset({"events", "orders", "trades", "topics", "gateways"})
DATE_HELP = (
    "Read this trading day (session timezone): its archive, or its parts "
    "before it is archived"
)


def build_parser() -> argparse.ArgumentParser:
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
        help=(
            f"Primary audit log file (default: {AUDIT_LOG_FILE}).\n"
            "Reads the live trail: unarchived day parts, then this file.\n"
            "An archive or day part named here is read alone."
        ),
    )
    parser.add_argument(
        "--log-dir",
        default=None,
        metavar="PATH",
        help=(
            "Directory holding the audit/ day parts and archives.\n"
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
    ev.add_argument("--date", metavar="YYYY-MM-DD", help=DATE_HELP)
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
    ev.add_argument(
        "-f",
        "--follow",
        action="store_true",
        help="Watch for new events instead of exiting (Ctrl-C to stop)",
    )
    ev.add_argument(
        "--interval",
        type=float,
        default=1.0,
        metavar="SEC",
        help="Polling interval in seconds for --follow (default: 1.0)",
    )

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
    od.add_argument("--date", metavar="YYYY-MM-DD", help=DATE_HELP)
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
    tr.add_argument("--date", metavar="YYYY-MM-DD", help=DATE_HELP)
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
    tp.add_argument("--date", metavar="YYYY-MM-DD", help=DATE_HELP)
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
    gw.add_argument("--date", metavar="YYYY-MM-DD", help=DATE_HELP)
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
    tl.add_argument(
        "-f",
        "--follow",
        action="store_true",
        help="Watch for new events instead of exiting (Ctrl-C to stop)",
    )
    tl.add_argument(
        "--interval",
        type=float,
        default=1.0,
        metavar="SEC",
        help="Polling interval in seconds for --follow (default: 1.0)",
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

    # ----------------------------------------------------------------- archive
    ar = sub.add_parser(
        "archive",
        help="Compress closed days' parts into one verified .zst archive per day",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    which = ar.add_mutually_exclusive_group(required=True)
    which.add_argument(
        "--date", metavar="YYYY-MM-DD", help="Archive this day (must be before today)"
    )
    which.add_argument(
        "--pending",
        action="store_true",
        help="Archive every closed day that still has parts, oldest first",
    )
    ar.add_argument(
        "--level",
        type=int,
        default=DEFAULT_LEVEL,
        metavar="N",
        help=f"zstd compression level (default: {DEFAULT_LEVEL})",
    )
    ar.add_argument(
        "--keep-days",
        type=int,
        default=0,
        metavar="N",
        help="Afterwards delete archives older than N days (default: 0 = keep all)",
    )

    # ------------------------------------------------------------------ health
    health = sub.add_parser(
        "health",
        help="Check the pm-audit process and audit log file health",
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
            "Also check the audit log file is readable, writable and ends in a "
            f"well-formed entry; allowed up to {_EXTENDED_HEALTH_TIMEOUT_SEC:.0f}s"
        ),
    )
    health.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=(
            "Describe exactly what was checked, plus log file size, day parts, "
            "archives and last entry time when combined with --extended"
        ),
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

    if getattr(args, "follow", False):
        interval = getattr(args, "interval", None)
        if interval is not None and interval <= 0:
            raise ValueError("--interval must be > 0")
        if getattr(args, "reverse", False):
            raise ValueError("--follow and --reverse are mutually exclusive")

    if args.command in _DATE_COMMANDS and getattr(args, "date", None):
        if is_explicit_file(Path(args.log_file)):
            raise ValueError("--date cannot be combined with an archive --log-file")
        if getattr(args, "follow", False):
            raise ValueError("--date and --follow are mutually exclusive")

    if args.command == "archive":
        if args.keep_days < 0:
            raise ValueError("--keep-days must be >= 0")
        low, high = zstd.CompressionParameter.compression_level.bounds()
        if not low <= args.level <= high:
            raise ValueError(f"--level must be between {low} and {high}")

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
        from edumatcher.config import resolve_data_path

        return resolve_data_path(args.use_index)
    return log_file.parent / _DEFAULT_INDEX_NAME


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _handle_events(
    args: argparse.Namespace,
    log_files: list[Path],
    index_path: Path | None,
) -> tuple[list[str], list[dict[str, Any]]]:
    from_dt, to_dt = _resolve_time_range(args)

    # Prefer the SQLite index when available. --follow always reads the live
    # JSONL files instead: the index is a point-in-time snapshot and is not
    # kept current between polls.
    if (
        index_path is not None
        and not getattr(args, "follow", False)
        and index_is_available(index_path)
    ):
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


def _follow_fetch(
    args: argparse.Namespace,
    log_file: Path,
    log_dir: Path | None,
    after_ts: str | None,
    after_skip: int,
) -> list[dict[str, Any]]:
    """Re-discover log files and fetch rows newer than (after_ts, after_skip).

    Called on every --follow poll, so a day close that happens between polls
    (a new day part appearing, or the active file being replaced) is
    picked up automatically — ``discover_log_files`` is just a directory
    listing, which is cheap enough to repeat every tick.
    """
    log_files = discover_log_files(log_file, log_dir)
    # A poll is expected to return a small batch (new events since the last
    # tick); 10,000 is just a generous ceiling, matching the cap query_timeline
    # already uses for the same "essentially unbounded" purpose below.
    if args.command == "events":
        return query_events(
            log_files,
            topic=args.topic,
            gateway=args.gateway.upper() if args.gateway else None,
            symbol=args.symbol.upper() if args.symbol else None,
            limit=10_000,
            after_ts=after_ts,
            after_skip=after_skip,
        )
    return query_timeline(
        log_files,
        topic_prefix=args.topic,
        gateway=args.gateway.upper() if args.gateway else None,
        symbol=args.symbol.upper() if args.symbol else None,
        limit=10_000,
        after_ts=after_ts,
        after_skip=after_skip,
    )


def _run_follow(
    args: argparse.Namespace,
    log_file: Path,
    log_dir: Path | None,
    columns: list[str],
    initial_rows: list[dict[str, Any]],
) -> None:
    """Print *initial_rows*, then poll for and print new rows until Ctrl-C.

    Position is tracked as (timestamp string, count of already-emitted rows
    sharing that timestamp) rather than a byte offset, since a poll always
    re-discovers the log file set from scratch to stay correct across
    rotation.
    """
    render(initial_rows, columns, args.format, no_header=args.no_header)

    if initial_rows:
        after_ts = str(initial_rows[-1]["timestamp"])
        after_skip = sum(1 for r in initial_rows if str(r["timestamp"]) == after_ts)
    else:
        after_ts = None
        after_skip = 0

    try:
        while True:
            time.sleep(args.interval)
            new_rows = _follow_fetch(args, log_file, log_dir, after_ts, after_skip)
            if new_rows:
                render(new_rows, columns, args.format, no_header=True)
                after_ts = str(new_rows[-1]["timestamp"])
                after_skip = sum(1 for r in new_rows if str(r["timestamp"]) == after_ts)
    except KeyboardInterrupt:
        pass


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
# Health check
# ---------------------------------------------------------------------------


def _find_audit_pids() -> list[int]:
    """Find pm-audit processes without matching this pm-audit-cli process."""
    return find_process_pids("pm-audit")


def _collect_log_stats(
    log_file: Path, log_dir: Path | None, last_entry_ts: str | None
) -> _HealthLogFileStats:
    """Active file, day parts and archives, for --extended --verbose."""
    parts = [p for p in discover_log_files(log_file, log_dir) if p != log_file]
    search_dir = log_dir if log_dir is not None else log_file.parent
    archives = sorted((search_dir / "audit").glob("audit-*.log.zst"))
    sizes = [archive_content_size(a) for a in archives]
    size = log_file.stat().st_size
    parts_bytes = sum(p.stat().st_size for p in parts)
    archives_bytes = sum(a.stat().st_size for a in archives)
    return {
        "size_bytes": size,
        "parts": len(parts),
        "parts_bytes": parts_bytes,
        "archives": len(archives),
        "archives_bytes": archives_bytes,
        "archives_content_bytes": (
            None if any(s is None for s in sizes) else sum(s or 0 for s in sizes)
        ),
        "total_size_bytes": size + parts_bytes + archives_bytes,
        "last_entry_ts": last_entry_ts,
    }


def _check_log_file_health(
    log_file: Path, log_dir: Path | None = None, *, collect_stats: bool = False
) -> tuple[bool, str, _HealthLogFileStats | None]:
    """Check the audit log is readable, writable, and ends in a valid entry."""
    if not log_file.exists():
        return False, f"audit log not found: {log_file}", None
    if not log_file.is_file():
        return False, f"audit log is not a regular file: {log_file}", None
    try:
        last_line = read_last_line(log_file)
        last_ts: str | None = None
        if last_line is not None:
            parsed = parse_line(last_line)
            if parsed is None:
                return False, "last audit log entry is malformed", None
            last_ts = parsed[0]
        # Opening for append and writing nothing proves pm-audit could still
        # write here without touching the trail itself.
        with log_file.open("ab"):
            pass
        stats = (
            _collect_log_stats(log_file, log_dir, last_ts) if collect_stats else None
        )
    except OSError as exc:
        return False, f"audit log read/write check failed: {exc}", None
    return True, "read/write and last-entry checks passed", stats


def _run_extended_log_file_check(
    log_file: Path,
    log_dir: Path | None = None,
    *,
    collect_stats: bool = False,
    timeout_sec: float = _EXTENDED_HEALTH_TIMEOUT_SEC,
) -> tuple[bool, str, _HealthLogFileStats | None]:
    """Run `_check_log_file_health`, bounded by `timeout_sec`."""
    try:
        return run_with_timeout(
            lambda: _check_log_file_health(
                log_file, log_dir, collect_stats=collect_stats
            ),
            timeout_sec,
        )
    except TimeoutError as exc:
        return False, f"log file check {exc}", None


def _check_zmq_health(timeout_ms: int = PING_TIMEOUT_MS) -> tuple[bool, str]:
    """Ping pm-audit's health REP socket and confirm it replies."""
    return ping_health_endpoint(AUDIT_HEALTH_ADDR, timeout_ms)


def _health_report(
    log_file: Path,
    log_dir: Path | None = None,
    *,
    extended: bool = False,
    collect_stats: bool = False,
) -> tuple[bool, _HealthReport]:
    pids = _find_audit_pids()
    zmq_ok, zmq_detail = _check_zmq_health()
    if extended:
        file_ok, file_detail, file_stats = _run_extended_log_file_check(
            log_file, log_dir, collect_stats=collect_stats
        )
        file_checked = True
    else:
        file_ok, file_detail, file_stats = (
            True,
            "skipped (pass --extended to check read/write access)",
            None,
        )
        file_checked = False
    report: _HealthReport = {
        "healthy": bool(pids) and file_ok and zmq_ok,
        "process": {
            "healthy": bool(pids),
            "pids": pids,
            "detail": "pm-audit is running" if pids else "pm-audit process not found",
        },
        "log_file": {
            "healthy": file_ok,
            "path": str(log_file),
            "detail": file_detail,
            "checked": file_checked,
            "stats": file_stats,
        },
        "zmq": {"healthy": zmq_ok, "detail": zmq_detail},
    }
    return bool(report["healthy"]), report


def _handle_health(
    args: argparse.Namespace, log_file: Path, log_dir: Path | None
) -> None:
    try:
        healthy, report = _health_report(
            log_file,
            log_dir,
            extended=args.extended,
            collect_stats=args.extended and args.verbose,
        )
    except (OSError, ValueError) as exc:
        healthy = False
        report = _HealthReport(
            healthy=False,
            process={"healthy": False, "pids": [], "detail": str(exc)},
            log_file={
                "healthy": False,
                "path": str(log_file),
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
        file_report = report["log_file"]
        zmq_report = report["zmq"]
        print(
            f"pm-audit process: {'OK' if process['healthy'] else 'FAIL'} - {process['detail']}"
        )
        print(
            f"audit log file:   {'OK' if file_report['healthy'] else 'FAIL'} - {file_report['detail']}"
        )
        print(
            f"audit ZMQ ping:   {'OK' if zmq_report['healthy'] else 'FAIL'} - {zmq_report['detail']}"
        )
        print(f"health: {'OK' if healthy else 'FAIL'}")
        if args.verbose:
            print()
            print("Checks performed:")
            print("  pm-audit process (pgrep):     yes")
            print("  ZMQ health ping:               yes")
            print(
                "  Log file read/write/entry:     "
                + ("yes" if file_report["checked"] else "no (pass --extended)")
            )
            stats = file_report["stats"]
            if stats is not None:
                print()
                print("Log file stats:")
                print(f"  path: {file_report['path']}")
                print(f"  size: {format_bytes(stats['size_bytes'])}")
                print(
                    f"  day parts: {stats['parts']} "
                    f"({format_bytes(stats['parts_bytes'])})"
                )
                content = stats["archives_content_bytes"]
                ratio = (
                    f", {content / stats['archives_bytes']:.1f}:1"
                    if content and stats["archives_bytes"]
                    else ""
                )
                print(
                    f"  archives: {stats['archives']} "
                    f"({format_bytes(stats['archives_bytes'])}{ratio})"
                )
                print(f"  total size: {format_bytes(stats['total_size_bytes'])}")
                print(f"  last entry: {stats['last_entry_ts'] or '(empty log)'}")
    raise SystemExit(0 if healthy else 1)


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------


def _handle_archive(args: argparse.Namespace, audit_dir: Path) -> int:
    """Run ``archive``; the exit code is 0 unless an archive failed."""
    failed = 0
    try:
        today = today_in(session_timezone())
        with archive_lock(audit_dir):
            days = pending_days(audit_dir, today) if args.pending else [args.date]
            for day in days:
                try:
                    result = archive_day(audit_dir, day, today=today, level=args.level)
                except ArchiveError as exc:
                    print(f"[ERROR] {exc}", file=sys.stderr)
                    failed += 1
                    continue
                if result is None:
                    print(f"{day}: no parts to archive")
                else:
                    print(
                        format_result(
                            result,
                            (
                                format_bytes(result.bytes_in),
                                format_bytes(result.bytes_out),
                            ),
                        )
                    )
            if args.keep_days > 0:
                for path in apply_retention(audit_dir, args.keep_days, today):
                    print(f"removed {path.name} (older than {args.keep_days} days)")
    except ArchiveBusy as exc:
        print(f"[archive] {exc}; nothing done")
        return 0
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 1 if failed else 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        _validate_args(args)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    log_file = Path(args.log_file).expanduser()
    log_dir = Path(args.log_dir).expanduser() if args.log_dir else None

    if args.command == "archive":
        search_dir = log_dir if log_dir is not None else log_file.parent
        raise SystemExit(_handle_archive(args, search_dir / "audit"))

    # health reports a missing log file itself (under --extended) rather than
    # refusing to run, and needs none of the log discovery below.
    if args.command == "health":
        _handle_health(args, log_file, log_dir)

    # stats and index do not need the log files to exist beforehand
    if args.command not in ("stats", "index") and not log_file.exists():
        if log_dir is None or not log_dir.is_dir():
            print(
                f"[ERROR] Audit log not found: {log_file}",
                file=sys.stderr,
            )
            raise SystemExit(1)

    log_files = discover_log_files(log_file, log_dir)
    index_path: Path | None = _resolve_index_path(args, log_file)
    if getattr(args, "date", None) and args.command in _DATE_COMMANDS:
        # The day is its files (session timezone), not a UTC time window, and
        # the index covers only the live trail.
        log_files = discover_day_files(log_file, args.date, session_timezone(), log_dir)
        if not log_files:
            print(f"[ERROR] No audit data for {args.date}", file=sys.stderr)
            raise SystemExit(1)
        args.date = None
        index_path = None

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

    if getattr(args, "follow", False):
        _run_follow(args, log_file, log_dir, columns, rows)
        return

    render(rows, columns, args.format, no_header=args.no_header)


if __name__ == "__main__":
    main()

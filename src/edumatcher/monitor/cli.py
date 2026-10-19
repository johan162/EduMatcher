"""pm-monitor-cli - read-only queries of pm-monitor (WP-B6).

What the operator dashboard shows, for a shell: an operator SSH'd into the
container, a CI job, a script. ``pm-opctl-cli`` manages processes (a PID and
a TCP probe); this asks pm-monitor, which knows HUNG from SILENT, the
exchange status, thresholds and history.

Commands
--------
``health``  Is pm-monitor alive? Healthy when a ``health.snapshot`` arrives
            within ``--timeout``: snapshots come from its main loop, so this
            proves the loop runs, not merely that the process exists.
            ``--extended`` also checks ``metrics.db``: integrity, schema, the
            pinned session timezone against the deployed one, write access.
``status``  One snapshot: exchange status, trading summary, every process,
            active threshold breaches. The exit code is the exchange status
            (``EXIT_*`` below), so scripts can act on it.
``events``  The event log from ``metrics.db`` (read-only); ``--follow`` then
            prints live events as pm-monitor publishes them.

Nothing here writes. ``metrics.db`` is opened read-only and every read is a
single short statement, so pm-monitor's WAL checkpoints are never held up.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, get_args

import zmq

from edumatcher.config import METRICS_DB_FILE, resolve_data_path
from edumatcher.healthcheck import find_process_pids, format_bytes, run_with_timeout
from edumatcher.models.generated.health import (
    TOPIC_HEALTH_EVENT,
    TOPIC_HEALTH_SNAPSHOT,
    HealthEvent,
    HealthEventKind,
    HealthSnapshot,
    parse_health_event,
    parse_health_snapshot,
)
from edumatcher.monitor.config import MonitorConfig, load_default_monitor_config

PROG = "pm-monitor-cli"

#: ``status`` exit codes. 2 stays the usage-error code of argparse and of the
#: sibling CLIs, so IMPAIRED is 3.
EXIT_STATUS = {"OPERATIONAL": 0, "DEGRADED": 1, "IMPAIRED": 3, "DOWN": 4}
EXIT_UNREACHABLE = 5
#: ``health -q``: 0 when healthy, -1 (255) otherwise -- as pm-stats-cli.
EXIT_UNHEALTHY = -1

#: Seconds to wait for a snapshot: the bridge's "pm-monitor is down" rule.
DEFAULT_TIMEOUT_SEC = 3.0
#: ``health --extended``: a quick_check of a large metrics.db takes a while.
EXTENDED_HEALTH_TIMEOUT_SEC = 45.0
#: The tables pm-monitor's store creates (monitor/store.py SCHEMA).
METRICS_TABLES = (
    "metrics_meta",
    "series",
    "samples_raw",
    "samples_1m",
    "daily_totals",
    "counter_last",
    "events",
)
EVENT_KINDS: tuple[str, ...] = get_args(HealthEventKind)


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Query pm-monitor: health, exchange status and the event log",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, PROG)
    parser.add_argument(
        "--host",
        default=None,
        metavar="HOST",
        help="pm-monitor host (default: monitor.host of the deployed config)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        metavar="PORT",
        help="pm-monitor PUB port (default: monitor.pub_port, 5611)",
    )
    parser.add_argument(
        "--db",
        default=str(METRICS_DB_FILE),
        metavar="PATH",
        help=f"metrics.db path for events (default: {METRICS_DB_FILE})",
    )
    parser.add_argument(
        "--format",
        default="table",
        choices=("table", "json"),
        help="Output format (table, json)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SEC,
        metavar="SEC",
        help=f"Seconds to wait for a snapshot (default: {DEFAULT_TIMEOUT_SEC:g})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    health = sub.add_parser(
        "health", help="Check that pm-monitor is running and publishing snapshots"
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
            "Also check metrics.db: integrity (PRAGMA quick_check), schema,\n"
            "the pinned session timezone against the deployed one, and write\n"
            f"access; allowed up to {EXTENDED_HEALTH_TIMEOUT_SEC:.0f}s for a large database"
        ),
    )
    health.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=(
            "Also show the pm-monitor PIDs and endpoint, and with --extended\n"
            "metrics.db size, WAL size and row counts"
        ),
    )

    sub.add_parser(
        "status",
        help=(
            "Show the exchange status, every process and active breaches.\n"
            "Exit code: 0 OPERATIONAL, 1 DEGRADED, 3 IMPAIRED, 4 DOWN,\n"
            "5 pm-monitor unreachable"
        ),
    )

    events = sub.add_parser("events", help="Show the event log from metrics.db")
    events.add_argument("--since", metavar="ISO_TS", help="Only events at or after")
    events.add_argument(
        "--kind",
        type=str.upper,
        choices=EVENT_KINDS,
        metavar="KIND",
        help="One of: " + ", ".join(EVENT_KINDS),
    )
    events.add_argument(
        "--subject", metavar="TEXT", help="Only events whose subject contains TEXT"
    )
    events.add_argument(
        "--limit",
        type=int,
        default=50,
        metavar="N",
        help="The newest N matching events (default: 50)",
    )
    events.add_argument(
        "--follow",
        action="store_true",
        help="Then print live events as pm-monitor publishes them (Ctrl-C stops)",
    )
    events.add_argument(
        "--count",
        type=int,
        default=None,
        metavar="N",
        help="With --follow: stop after N live events",
    )
    return parser


# ---------------------------------------------------------------------------
# the live feed
# ---------------------------------------------------------------------------


def _endpoint(args: argparse.Namespace, config: MonitorConfig) -> str:
    host = args.host or config.host
    port = args.port or config.pub_port
    return f"tcp://{host}:{port}"


def _subscriber(endpoint: str, topic: str) -> zmq.Socket[bytes]:
    sock: zmq.Socket[bytes] = zmq.Context.instance().socket(zmq.SUB)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.SUBSCRIBE, topic.encode())
    sock.connect(endpoint)
    return sock


def receive_snapshot(endpoint: str, timeout_sec: float) -> HealthSnapshot | None:
    """The next snapshot pm-monitor publishes, or ``None`` within the timeout.

    A new SUB joins late (ZeroMQ's slow joiner), so this waits for the next
    snapshot rather than expecting one to be queued.
    """
    sock = _subscriber(endpoint, TOPIC_HEALTH_SNAPSHOT)
    try:
        deadline = time.monotonic() + timeout_sec
        while (remaining := deadline - time.monotonic()) > 0:
            if not sock.poll(int(remaining * 1000) + 1):
                break
            try:
                return parse_health_snapshot(sock.recv_multipart())
            except Exception:  # a malformed frame: wait for the next one
                continue
        return None
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


def health_report(
    endpoint: str, timeout_sec: float, config: MonitorConfig
) -> dict[str, Any]:
    """The live check: a snapshot within the timeout."""
    pids = find_process_pids("pm-monitor")
    if not config.enabled:
        return {
            "healthy": False,
            "endpoint": endpoint,
            "pids": pids,
            "detail": "monitoring is disabled (monitor.enabled: false)",
            "snapshot": None,
        }
    snap = receive_snapshot(endpoint, timeout_sec)
    if snap is None:
        return {
            "healthy": False,
            "endpoint": endpoint,
            "pids": pids,
            "detail": f"no snapshot from {endpoint} within {timeout_sec:g} s",
            "snapshot": None,
        }
    return {
        "healthy": True,
        "endpoint": endpoint,
        "pids": pids,
        "detail": (
            f"snapshot seq {snap.seq} at {snap.ts}, {len(snap.processes)} processes, "
            f"exchange {snap.exchange.status}"
        ),
        "snapshot": {"seq": snap.seq, "ts": snap.ts},
    }


def _deployed_session_timezone() -> str:
    from edumatcher.config_artifact import load_compiled_config
    from edumatcher.engine.config_loader import DEFAULT_SESSION_TIMEZONE

    compiled = load_compiled_config()
    return (
        DEFAULT_SESSION_TIMEZONE
        if compiled is None
        else compiled.engine.locale.session_timezone
    )


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def check_database(
    db: Path, session_timezone: str, *, collect_stats: bool = False
) -> dict[str, Any]:
    """``health --extended``: is metrics.db sound and usable by pm-monitor?

    Strictly read-only: the reads go through a ``mode=ro`` connection, and
    write access is judged by the file permissions pm-monitor needs, not by
    writing -- a writable connection closing last could checkpoint the WAL
    while pm-monitor is down.
    """
    result: dict[str, Any] = {"healthy": False, "path": str(db), "stats": None}
    if not db.exists():
        result["detail"] = f"database not found: {db} (has pm-monitor run here?)"
        return result
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2.0)
    try:
        check = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        if check != "ok":
            result["detail"] = f"integrity check failed: {check}"
            return result
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        missing = [t for t in METRICS_TABLES if t not in tables]
        if missing:
            result["detail"] = f"not a pm-monitor database, missing tables: {missing}"
            return result
        row = conn.execute(
            "SELECT value FROM metrics_meta WHERE key = 'session_timezone'"
        ).fetchone()
        pinned = None if row is None else str(row[0])
        if pinned is not None and pinned != session_timezone:
            result["detail"] = (
                f"recorded with session timezone {pinned!r} but the deployed "
                f"config says {session_timezone!r}: pm-monitor will refuse to start"
            )
            return result
        if collect_stats:
            result["stats"] = {
                "size_bytes": _file_size(db),
                "wal_bytes": _file_size(Path(f"{db}-wal")),
                "session_timezone": pinned,
                "row_counts": {
                    t: int(conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0])
                    for t in METRICS_TABLES
                },
            }
    finally:
        conn.close()
    if not (os.access(db, os.W_OK) and os.access(db.parent, os.W_OK)):
        result["detail"] = f"{db} or its directory is not writable by this user"
        return result
    result["healthy"] = True
    result["detail"] = "integrity, schema, timezone and write access ok"
    return result


def _extended(args: argparse.Namespace) -> dict[str, Any]:
    db = resolve_data_path(args.db)
    try:
        result: dict[str, Any] = run_with_timeout(
            lambda: check_database(
                db, _deployed_session_timezone(), collect_stats=args.verbose
            ),
            EXTENDED_HEALTH_TIMEOUT_SEC,
        )
    except TimeoutError as exc:
        detail = f"database check {exc}"
    except (OSError, sqlite3.Error, ValueError) as exc:
        detail = f"database check failed: {exc}"
    else:
        return result
    return {"healthy": False, "path": str(db), "detail": detail, "stats": None}


def _cmd_health(args: argparse.Namespace, config: MonitorConfig) -> int:
    report = health_report(_endpoint(args, config), args.timeout, config)
    if args.extended:
        report["database"] = _extended(args)
        report["healthy"] = report["healthy"] and report["database"]["healthy"]
    healthy = bool(report["healthy"])
    if args.quiet:
        return 0 if healthy else EXIT_UNHEALTHY
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if healthy else 1
    live = "OK" if report["snapshot"] else "FAIL"
    print(f"pm-monitor snapshot: {live} - {report['detail']}")
    database = report.get("database")
    if database is None:
        print("metrics.db:          skipped (pass --extended to check it)")
    else:
        verdict = "OK" if database["healthy"] else "FAIL"
        print(f"metrics.db:          {verdict} - {database['detail']}")
    if args.verbose:
        pids = report["pids"]
        print(
            f"pm-monitor processes (pgrep): {', '.join(map(str, pids)) or 'none here'}"
        )
        print(f"endpoint: {report['endpoint']}")
        stats = None if database is None else database.get("stats")
        if database is not None and stats is not None:
            print(f"database: {database['path']}")
            print(
                f"  size: {format_bytes(stats['size_bytes'])} "
                f"(+ WAL {format_bytes(stats['wal_bytes'])})"
            )
            print(f"  session timezone: {stats['session_timezone']}")
            for table, count in stats["row_counts"].items():
                print(f"  {table} rows: {count}")
    print(f"health: {'OK' if healthy else 'FAIL'}")
    return 0 if healthy else 1


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def _uptime(sec: float) -> str:
    sec = int(sec)
    days, sec = divmod(sec, 86400)
    hours, sec = divmod(sec, 3600)
    minutes, sec = divmod(sec, 60)
    clock = f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{days}d {clock}" if days else clock


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    out = [line.rstrip()]
    out.extend(
        "  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip()
        for row in rows
    )
    return out


def render_status(snap: HealthSnapshot) -> list[str]:
    ex, tr = snap.exchange, snap.trading
    lines = [
        f"exchange {ex.status}   session {ex.session_state or '-'}   "
        f"trading date {ex.trading_date} ({ex.session_timezone})   snapshot {snap.ts}",
        f"orders today {tr.orders.today} ({tr.orders.per_sec_now * 60:.1f}/min now)   "
        f"trades today {tr.trades.today}   reject {tr.reject_pct_5m:.1f} % (5 min)   "
        f"p99 {tr.handle_p99_us:.0f} us   engine busy {tr.busy_pct:.1f} %",
        "",
    ]
    rows = [
        [
            p.key,
            p.state
            + (" (restarted)" if p.restarted_recently else "")
            + (" (starting)" if p.starting else ""),
            str(p.pid) if p.pid else "-",
            _uptime(p.uptime_sec) if p.host else "-",
            format_bytes(p.rss_bytes) if p.host else "-",
            f"{p.cpu_pct:.1f}" if p.host else "-",
            f"{p.loop_lag_ms:.0f}" if p.host else "-",
            f"{p.last_beacon_age_ms / 1000:.1f}" if p.host else "-",
        ]
        for p in snap.processes
    ]
    headers = ["PROCESS", "STATE", "PID", "UPTIME", "RSS", "CPU%", "LAG_MS", "BEACON_S"]
    lines.extend(_table(headers, rows) if rows else ["(no processes)"])
    lines.append("")
    if snap.thresholds:
        lines.append("breaches:")
        lines.extend(
            "  " + line
            for line in _table(
                ["LEVEL", "RULE", "SUBJECT", "VALUE", "THRESHOLD", "SINCE"],
                [
                    [
                        b.level,
                        b.rule,
                        b.subject,
                        f"{b.value:g}",
                        f"{b.threshold:g}",
                        b.since,
                    ]
                    for b in snap.thresholds
                ],
            )
        )
    else:
        lines.append("breaches: none")
    return lines


def _cmd_status(args: argparse.Namespace, config: MonitorConfig) -> int:
    endpoint = _endpoint(args, config)
    snap = receive_snapshot(endpoint, args.timeout)
    if snap is None:
        print(
            f"[ERROR] no snapshot from pm-monitor at {endpoint} within "
            f"{args.timeout:g} s -- is it running? (pm-monitor-cli health -v)",
            file=sys.stderr,
        )
        return EXIT_UNREACHABLE
    if args.format == "json":
        print(json.dumps(snap.to_dict(), indent=2, sort_keys=True))
    else:
        print("\n".join(render_status(snap)))
    return EXIT_STATUS[snap.exchange.status]


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------

_EVENT_COLUMNS = ("seq", "ts", "severity", "kind", "subject", "detail")


def query_events(
    db: Path,
    *,
    since: str | None = None,
    kind: str | None = None,
    subject: str | None = None,
    limit: int = 50,
    seq_range: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    """The newest ``limit`` matching events, oldest first. Read-only, one
    statement, so pm-monitor's writer is never held up. ``seq_range`` is an
    exclusive ``(after, before)`` bound, for filling a gap in a live feed."""
    where: list[str] = []
    params: list[Any] = []
    if seq_range is not None:
        where.append("seq > ? AND seq < ?")
        params.extend(seq_range)
    if since is not None:
        where.append("ts >= ?")
        params.append(since)
    if kind is not None:
        where.append("kind = ?")
        params.append(kind)
    if subject is not None:
        where.append("instr(subject, ?) > 0")
        params.append(subject)
    sql = f"SELECT {', '.join(_EVENT_COLUMNS)} FROM events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY seq DESC LIMIT ?"
    params.append(limit)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA busy_timeout = 2000")
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [dict(zip(_EVENT_COLUMNS, row)) for row in reversed(rows)]


def newest_seq(db: Path) -> int:
    """The newest event's seq in the log; -1 when it is empty."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT max(seq) FROM events").fetchone()
    finally:
        conn.close()
    return -1 if row is None or row[0] is None else int(row[0])


def _event_dict(event: HealthEvent) -> dict[str, Any]:
    return {c: getattr(event, c) for c in _EVENT_COLUMNS}


def _print_events(rows: list[dict[str, Any]], fmt: str, *, header: bool) -> None:
    if fmt == "json":
        for row in rows:
            print(json.dumps(row, sort_keys=True), flush=True)
        return
    table = _table(
        ["SEQ", "TS", "SEV", "KIND", "SUBJECT", "DETAIL"],
        [[str(r["seq"]), r["ts"], r["severity"], r["kind"], r["subject"], r["detail"]]
         for r in rows],
    ) if rows else []  # fmt: skip
    for line in table[0 if header else 1 :]:
        print(line, flush=True)


def _matches(row: dict[str, Any], args: argparse.Namespace) -> bool:
    if args.kind is not None and row["kind"] != args.kind:
        return False
    if args.subject is not None and args.subject not in row["subject"]:
        return False
    return True


def _cmd_events(args: argparse.Namespace, config: MonitorConfig) -> int:
    if args.limit < 1:
        print("[ERROR] --limit must be at least 1", file=sys.stderr)
        return 2
    if args.count is not None and not args.follow:
        print("[ERROR] --count needs --follow", file=sys.stderr)
        return 2
    db = resolve_data_path(args.db)
    # Subscribe before reading the history: an event published in between is
    # then queued rather than lost (and a remaining gap is filled from the
    # database by seq, see _follow).
    sock = (
        _subscriber(_endpoint(args, config), TOPIC_HEALTH_EVENT)
        if args.follow
        else None
    )
    try:
        return _events(args, db, sock)
    finally:
        if sock is not None:
            sock.close()


def _events(args: argparse.Namespace, db: Path, sock: zmq.Socket[bytes] | None) -> int:
    last_seq = -1
    header = True
    if db.exists():
        try:
            # The follow position is the log's newest seq, matching or not:
            # everything up to it has been considered.
            last_seq = newest_seq(db)
            rows = query_events(
                db,
                since=args.since,
                kind=args.kind,
                subject=args.subject,
                limit=args.limit,
            )
        except sqlite3.Error as exc:
            print(f"[ERROR] cannot read {db}: {exc}", file=sys.stderr)
            return 1
        _print_events(rows, args.format, header=True)
        header = not rows
    elif not args.follow:
        print(
            f"[ERROR] {db} does not exist (has pm-monitor run here?)", file=sys.stderr
        )
        return 1
    else:
        print(f"[WARN] {db} does not exist; live events only", file=sys.stderr)
    if sock is None:
        return 0
    return _follow(args, db, sock, last_seq, header=header)


def _follow(
    args: argparse.Namespace,
    db: Path,
    sock: zmq.Socket[bytes],
    last_seq: int,
    *,
    header: bool,
) -> int:
    """Print live events; fill a gap in ``seq`` from metrics.db.

    ``last_seq`` is the newest seq already considered (-1: none) -- printed
    or filtered out. ``header``: no table header has been printed yet.
    """
    shown = 0
    try:
        while args.count is None or shown < args.count:
            if not sock.poll(1000):
                continue
            try:
                event = parse_health_event(sock.recv_multipart())
            except Exception:
                continue
            if event.seq <= last_seq:
                continue  # already in the history
            rows: list[dict[str, Any]] = []
            if last_seq >= 0 and event.seq > last_seq + 1 and db.exists():
                rows = query_events(
                    db,
                    kind=args.kind,
                    subject=args.subject,
                    limit=event.seq - last_seq,
                    seq_range=(last_seq, event.seq),
                )
            row = _event_dict(event)
            if _matches(row, args):
                rows.append(row)
            last_seq = event.seq
            for r in rows:
                if args.count is not None and shown >= args.count:
                    break
                _print_events([r], args.format, header=header)
                header = False
                shown += 1
    except KeyboardInterrupt:
        pass
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = load_default_monitor_config()
    commands = {"health": _cmd_health, "status": _cmd_status, "events": _cmd_events}
    raise SystemExit(commands[args.command](args, config))


if __name__ == "__main__":
    main()

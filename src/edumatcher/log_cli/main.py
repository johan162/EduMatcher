"""pm-log-cli — read-only query/troubleshooting tool for ``log.db``.

Reads the SQLite database written by ``pm-log-srv`` directly; no LALF/TCP
connection is made (§4.1, §9, §15.2), so a busy, slow, or down log server
never prevents troubleshooting with the data it already collected.

Usage::

    pm-log-cli [global-options] COMMAND [command-options]

Commands
--------
  tail        Follow new log_events rows in real time
  query       Filtered historical search
  processes   List connected/recently-connected pm-* processes
  stats       Server + database health summary
  diagnose    Rule-based troubleshooting report (§9.6)
  prune       Manual retention pruning (§6.5)
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from typing import Any

from edumatcher.config import LOG_DB_FILE, resolve_data_path
from edumatcher.log_cli.diagnose import Finding, run_diagnostics
from edumatcher.log_cli import queries
from edumatcher.log_srv.config import DEFAULT_RETENTION_DAYS
from edumatcher.log_srv.schema import open_db

_FORMATS = ("human", "json")

_QUERY_COLS = [
    "seq",
    "client_ts",
    "process",
    "instance",
    "level",
    "logger",
    "message",
]
_PROCESS_COLS = [
    "process",
    "instance",
    "pid",
    "host",
    "connected_at",
    "last_seen_at",
    "log_count",
]

_LEVEL_COLOR = {
    "ERROR": "\033[31m",
    "CRITICAL": "\033[31m",
    "WARNING": "\033[33m",
}
_RESET = "\033[0m"

# Matches the `tail`-only `-<nnn>` shorthand (1-999, e.g. -50) for "show this
# many old lines before switching to live". Rejects -0 and anything with a
# leading zero (e.g. -007) so the shorthand stays unambiguous; --before N
# always works as the explicit, unrestricted spelling.
_BEFORE_SHORTHAND_RE = re.compile(r"^-([1-9][0-9]{0,2})$")


def _rewrite_before_shorthand(argv: list[str]) -> list[str]:
    """Rewrite ``tail -<nnn>`` into ``tail --before <nnn>``.

    argparse has no clean way to accept a bare ``-<number>`` token (it looks
    like a negative-number positional/unknown option), so this is handled as
    a pre-processing pass over sys.argv before the real parser ever sees it.
    Only tokens that appear after a literal "tail" subcommand token are
    rewritten, so "-123" elsewhere (e.g. a --db path, or before the
    subcommand) is left alone.
    """
    try:
        tail_idx = argv.index("tail")
    except ValueError:
        return argv

    rewritten = list(argv)
    i = tail_idx + 1
    while i < len(rewritten):
        token = rewritten[i]
        if token == "--":
            break
        match = _BEFORE_SHORTHAND_RE.match(token)
        if match:
            rewritten[i : i + 1] = ["--before", match.group(1)]
            i += 2
            continue
        i += 1
    return rewritten


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm-log-cli",
        description="Query and troubleshoot EduMatcher's centralized log.db.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-log-cli")

    parser.add_argument(
        "--db",
        default=str(LOG_DB_FILE),
        metavar="PATH",
        help=f"SQLite database path (default: {LOG_DB_FILE})",
    )
    parser.add_argument(
        "--format",
        dest="format",
        default="human",
        choices=_FORMATS,
        help="Output format: human (default) or json",
    )

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def _add_format(p: argparse.ArgumentParser) -> None:
        # --format is accepted both before and after the subcommand (e.g.
        # both "pm-log-cli --format json query" and "pm-log-cli query
        # --format json" work) since argparse subparsers do not inherit
        # arguments defined on the parent parser. This uses a *different*
        # dest ("format_sub") than the top-level "--format" ("format") so
        # the two can never silently clobber each other in the shared
        # namespace regardless of argument order — _resolve_format() below
        # merges them, preferring the subcommand-level value when given.
        p.add_argument(
            "--format",
            dest="format_sub",
            default=None,
            choices=_FORMATS,
            help=argparse.SUPPRESS,
        )

    # ------------------------------------------------------------------ tail
    tl = sub.add_parser("tail", help="Follow new log_events rows in real time")
    tl.add_argument("--process", metavar="NAME", help="Filter by process name")
    tl.add_argument(
        "--level", metavar="LEVEL[,LEVEL...]", help="Filter by one or more levels"
    )
    tl.add_argument("--logger", metavar="PATTERN", help="SQL LIKE pattern on logger")
    tl.add_argument(
        "--interval",
        type=float,
        default=1.0,
        metavar="SEC",
        help="Polling interval in seconds (default: 1.0)",
    )
    tl.add_argument(
        "--before",
        dest="before",
        type=int,
        default=None,
        metavar="NNN",
        help=(
            "Show this many existing rows before switching to live tail "
            "(1-999). Shorthand: -NNN, e.g. -50."
        ),
    )
    _add_format(tl)

    # ----------------------------------------------------------------- query
    qy = sub.add_parser("query", help="Filtered historical search")
    qy.add_argument("--process", metavar="NAME", help="Filter by process name")
    qy.add_argument(
        "--level", metavar="LEVEL[,LEVEL...]", help="Filter by one or more levels"
    )
    qy.add_argument("--logger", metavar="PATTERN", help="SQL LIKE pattern on logger")
    qy.add_argument("--since", metavar="ISO_TS", help="Start of time range")
    qy.add_argument("--until", metavar="ISO_TS", help="End of time range")
    qy.add_argument("--grep", metavar="TEXT", help="Case-insensitive substring search")
    qy.add_argument(
        "--has-exception", action="store_true", help="Only rows with an exception"
    )
    qy.add_argument(
        "--limit",
        type=int,
        default=500,
        metavar="N",
        help="Maximum rows (default: 500)",
    )
    qy.add_argument(
        "--reverse", action="store_true", help="Oldest-first instead of newest-first"
    )
    _add_format(qy)

    # ------------------------------------------------------------- processes
    pr = sub.add_parser(
        "processes", help="List connected/recently-connected pm-* processes"
    )
    pr.add_argument(
        "--active", action="store_true", help="Only currently-connected sessions"
    )
    _add_format(pr)

    # ------------------------------------------------------------------ stats
    st = sub.add_parser("stats", help="Server + database health summary")
    _add_format(st)

    # --------------------------------------------------------------- diagnose
    dg = sub.add_parser("diagnose", help="Rule-based troubleshooting report")
    dg.add_argument(
        "--since", metavar="ISO_TS", help="Restrict to events since this time"
    )
    dg.add_argument("--process", metavar="NAME", help="Restrict to a specific process")
    _add_format(dg)

    # ------------------------------------------------------------------ prune
    pn = sub.add_parser("prune", help="Manually prune log_events older than N days")
    pn.add_argument(
        "--days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        metavar="N",
        help=f"Delete rows older than N days (default: {DEFAULT_RETENTION_DAYS})",
    )

    return parser


def _resolve_format(args: argparse.Namespace) -> str:
    """Prefer a --format given after the subcommand over the top-level one."""
    sub_format = getattr(args, "format_sub", None)
    return sub_format if sub_format is not None else str(args.format)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _print_table(rows: list[dict[str, Any]], columns: list[str]) -> None:
    if not rows:
        print("No matching log events found.")
        return
    widths = [
        max(len(col), max((len(str(r.get(col, ""))) for r in rows), default=0))
        for col in columns
    ]
    print(" | ".join(c.ljust(w) for c, w in zip(columns, widths)))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        cells = []
        for col, w in zip(columns, widths):
            val = row.get(col)
            text = "" if val is None else str(val)
            if col == "level" and text in _LEVEL_COLOR and sys.stdout.isatty():
                text_display = f"{_LEVEL_COLOR[text]}{text}{_RESET}"
                cells.append(text_display + " " * max(0, w - len(text)))
            else:
                cells.append(text.ljust(w))
        print(" | ".join(cells))


def _print_json_rows(rows: list[dict[str, Any]]) -> None:
    import json

    for row in rows:
        print(json.dumps(row))


def _print_findings_human(findings: list[Finding]) -> None:
    if not findings:
        print("No issues detected in the queried window.")
        return
    for f in findings:
        print(f"[{f.severity.upper()}] {f.heuristic}: {f.message}")
        print(f"  Recommendation: {f.recommendation}")
        print(f"  Reproduce with: {f.repro_command}")
        print()


def _print_findings_json(findings: list[Finding]) -> None:
    import json

    print(json.dumps({"findings": [f.to_dict() for f in findings]}, indent=2))


def _print_stats_human(stats: dict[str, Any]) -> None:
    server = stats.get("server", {})
    print("pm-log-srv Statistics")
    print("=" * 40)
    print(f"  Started at:        {server.get('started_at', 'n/a')}")
    print(f"  Total log events:  {server.get('total_log_events', 0):,}")
    print(f"  Total connections: {server.get('total_connections', 0):,}")
    print(f"  Total truncated:   {server.get('total_truncated', 0):,}")
    print(f"  Total errors sent: {server.get('total_errors_sent', 0):,}")
    print(f"  Rows in log.db:    {stats.get('total_rows', 0):,}")
    print(f"  DB file size:      {stats.get('db_size_bytes', 0):,} bytes")
    print()
    print("  By level:")
    for row in stats.get("per_level", []):
        print(f"    {row['level']:<10} {row['n']:,}")
    print()
    print("  By process:")
    for row in stats.get("per_process", []):
        print(f"    {row['process']:<20} {row['n']:,}")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _parse_levels(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [v.strip().upper() for v in raw.split(",") if v.strip()]


def _handle_query(args: argparse.Namespace, conn: Any) -> list[dict[str, Any]]:
    return queries.query_events(
        conn,
        process=args.process,
        levels=_parse_levels(args.level),
        logger_pattern=args.logger,
        since=args.since,
        until=args.until,
        grep=args.grep,
        has_exception=args.has_exception,
        limit=args.limit,
        reverse=args.reverse,
    )


def _handle_tail(args: argparse.Namespace, conn: Any, fmt: str) -> None:
    levels = _parse_levels(args.level)
    before = getattr(args, "before", None)

    if before is not None:
        backfill = queries.query_events(
            conn,
            process=args.process,
            levels=levels,
            logger_pattern=args.logger,
            limit=before,
        )
        if backfill:
            if fmt == "json":
                _print_json_rows(backfill)
            else:
                _print_table(backfill, _QUERY_COLS)
            last_seq = max(r["seq"] for r in backfill)
        else:
            last_seq = queries.max_seq(conn)
    else:
        last_seq = queries.max_seq(conn)

    try:
        while True:
            rows = queries.query_events(
                conn,
                process=args.process,
                levels=levels,
                logger_pattern=args.logger,
                min_seq=last_seq,
                limit=10_000,
            )
            if rows:
                last_seq = max(r["seq"] for r in rows)
                if fmt == "json":
                    _print_json_rows(rows)
                else:
                    _print_table(rows, _QUERY_COLS)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass


def _handle_diagnose(args: argparse.Namespace, conn: Any) -> list[Finding]:
    return run_diagnostics(conn, process_filter=args.process, since=args.since)


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = _build_parser()
    argv = _rewrite_before_shorthand(sys.argv[1:])
    args = parser.parse_args(argv)
    fmt = _resolve_format(args)

    if args.command == "tail":
        before = getattr(args, "before", None)
        if before is not None and not (1 <= before <= 999):
            print(
                "[ERROR] --before/-NNN must be between 1 and 999 " f"(got {before}).",
                file=sys.stderr,
            )
            raise SystemExit(2)

    db_path = resolve_data_path(args.db)

    if args.command != "stats" and not db_path.exists():
        print(
            f"[ERROR] Log database not found: {db_path} (has pm-log-srv ever run?)",
            file=sys.stderr,
        )
        raise SystemExit(1)

    try:
        conn = (
            queries.open_readonly(db_path)
            if args.command != "prune"
            else open_db(db_path)
        )
    except Exception as exc:
        print(f"[ERROR] Failed to open database: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    try:
        if args.command == "tail":
            _handle_tail(args, conn, fmt)
            return

        if args.command == "query":
            rows = _handle_query(args, conn)
            if fmt == "json":
                _print_json_rows(rows)
            else:
                _print_table(rows, _QUERY_COLS)
            return

        if args.command == "processes":
            rows = queries.query_processes(conn, active_only=args.active)
            if fmt == "json":
                _print_json_rows(rows)
            else:
                _print_table(rows, _PROCESS_COLS)
            return

        if args.command == "stats":
            stats = queries.query_stats(conn, db_path)
            if fmt == "json":
                import json

                print(json.dumps(stats, indent=2))
            else:
                _print_stats_human(stats)
            return

        if args.command == "diagnose":
            findings = _handle_diagnose(args, conn)
            if fmt == "json":
                _print_findings_json(findings)
            else:
                _print_findings_human(findings)
            if findings:
                raise SystemExit(3)
            return

        if args.command == "prune":
            deleted = queries.prune_older_than(conn, args.days)
            print(f"Pruned {deleted:,} row(s) older than {args.days} days.")
            return

        print(f"[ERROR] Unknown command: {args.command}", file=sys.stderr)
        raise SystemExit(2)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"[ERROR] Query failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        conn.close()


if __name__ == "__main__":
    main()

"""pm-eod — close a trading day: settle, report, housekeeping.

  pm-eod run --date 2026-11-02     one trading date
  pm-eod run --pending             every closed date not yet done, oldest first
  pm-eod status [-q]               recent runs; -q is a health check (exit 0/1)
  pm-eod balances [--check]        running balances per account
  pm-eod show --date D [--steps]   one date's ledger rows (or its run steps)

Exit codes of ``run``: 0 clean, 1 the day failed (gate, settlement or report),
2 usage error, 3 settled and reported with warnings (housekeeping, or a
settled date's snapshot that changed).
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edumatcher.audit.archive import session_timezone, today_in
from edumatcher.config import DATA_DIR
from edumatcher.eod.ledger import (
    balances,
    check_zero_sum,
    day_amounts,
    day_detail,
    open_ledger_readonly,
    open_scratch_ledger,
    run_for,
    runs,
)
from edumatcher.eod.report import fmt_minor
from edumatcher.eod.roster import RosterError, load_roster
from edumatcher.stats.query import validate_date
from edumatcher.eod.runner import (
    STEPS,
    Options,
    Paths,
    RunLocked,
    RunOutcome,
    backup_step,
    exit_code,
    pending_dates,
    run_day,
    run_lock,
)

_LABEL = {"ok": "ok", "warn": "warn", "fail": "FAIL"}


def _today() -> str:
    return today_in(session_timezone())


def _non_negative(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be 0 or more, not {value}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm-eod",
        description="End-of-day settlement, statements and housekeeping",
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-eod")
    parser.add_argument(
        "--datapath",
        type=Path,
        default=DATA_DIR,
        metavar="DIR",
        help="Data directory (default: the configured one)",
    )
    parser.add_argument("--format", choices=("table", "json", "csv"), default="table")
    parser.add_argument(
        "--no-header", action="store_true", help="No header row for csv/table"
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    run = sub.add_parser("run", help="Settle and close a trading date")
    which = run.add_mutually_exclusive_group()
    which.add_argument("--date", metavar="YYYY-MM-DD")
    which.add_argument(
        "--pending",
        action="store_true",
        help="Every closed date without an ok run, oldest first",
    )
    run.add_argument(
        "--only",
        choices=STEPS,
        help="Run just this step of an already settled date "
        "(not with --redo, --force or --dry-run)",
    )
    run.add_argument(
        "--force",
        action="store_true",
        help="Skip the 'has the day closed?' test, for an exchange without a "
        "scheduler (no CLOSED is ever announced); the snapshot and reconcile "
        "checks still apply",
    )
    run.add_argument(
        "--redo",
        action="store_true",
        help="Recompute this date; drops its settlement and every later date's",
    )
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="Gate and settle into an in-memory copy of the ledger; print the "
        "amounts, write nothing (not with --only)",
    )
    run.add_argument(
        "--log-keep-days",
        type=_non_negative,
        default=14,
        metavar="N",
        help="Delete compressed failover logs older than N days (default: 14)",
    )
    run.add_argument(
        "--backup-keep-days",
        type=_non_negative,
        default=7,
        metavar="N",
        help="Delete backups of dates more than N days before this one (default: 7)",
    )
    run.add_argument(
        "--backup-skip",
        action="append",
        default=[],
        choices=("clearing.db", "stats.db", "eod.db"),
        metavar="NAME",
        help="Leave this database out of the backup (repeatable): "
        "clearing.db, stats.db or eod.db",
    )

    status = sub.add_parser("status", help="Recent runs")
    status.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Print nothing on stdout; exit 0 when no closed date is waiting, 1 when "
        "one is or when there is no clearing.db to judge",
    )
    status.add_argument("--limit", type=int, default=30, metavar="N")

    bal = sub.add_parser("balances", help="Running balance per account")
    bal.add_argument("--date", metavar="YYYY-MM-DD", help="As of this date")
    bal.add_argument("--gateway", metavar="GW_ID")
    bal.add_argument(
        "--check",
        action="store_true",
        help="Verify every settled date sums to zero; exit 1 if not",
    )
    show = sub.add_parser("show", help="One date's ledger rows or run steps")
    show.add_argument("--date", metavar="YYYY-MM-DD", required=True)
    show.add_argument("--gateway", metavar="GW_ID")
    show.add_argument(
        "--steps",
        action="store_true",
        help="Show the run's steps with their full messages instead of the amounts",
    )
    return parser


def _print_outcome(outcome: RunOutcome) -> None:
    print(f"{outcome.trade_date}:")
    for s in outcome.steps:
        print(f"  [{_LABEL[s.status]}] {s.step}: {s.message}")


def _cmd_run(args: argparse.Namespace, paths: Paths) -> int:
    opts = Options(
        force=args.force,
        redo=args.redo,
        only=args.only,
        dry_run=args.dry_run,
        log_keep_days=args.log_keep_days,
        backup_keep_days=args.backup_keep_days,
        backup_skip=tuple(args.backup_skip),
    )
    if not args.date and not args.pending:
        print("pm-eod run: give --date or --pending", file=sys.stderr)
        return 2
    if args.only and args.dry_run:
        # --only skips the gate and settle steps --dry-run stops before, so the
        # step would really run.
        print("pm-eod run: --dry-run cannot be combined with --only", file=sys.stderr)
        return 2
    if args.only and (args.redo or args.force):
        # Both act on the gate and settle steps, which --only skips.
        flag = "--redo" if args.redo else "--force"
        print(f"pm-eod run: {flag} cannot be combined with --only", file=sys.stderr)
        return 2
    try:
        with run_lock(paths.data):
            dates = pending_dates(paths) if args.pending else [args.date]
            if not dates:
                print("nothing pending")
                return 0
            # Each date would back up the same current databases under its own
            # (older) label, so a run of several dates takes one backup, after
            # the last date it got through.
            batch = len(dates) > 1
            day_opts = replace(opts, backup=False) if batch else opts
            worst, last_done = 0, None
            # A dry run settles into one in-memory copy of the ledger, so each
            # date is measured from the previous date's dry result.
            scratch = open_scratch_ledger(paths.ledger) if opts.dry_run else None
            for day in dates:
                outcome = run_day(
                    paths,
                    day,
                    day_opts,
                    today=_today(),
                    now=datetime.now(UTC),
                    scratch=scratch,
                )
                _print_outcome(outcome)
                code = exit_code(outcome)
                if code == 1:
                    if batch:
                        print(f"stopping: later dates wait for {day}")
                    worst = 1
                    break
                worst, last_done = max(worst, code), day
            if batch and last_done and opts.only in (None, "backup"):
                if not opts.dry_run:
                    backup = RunOutcome(
                        last_done, (backup_step(paths, last_done, opts),)
                    )
                    _print_outcome(backup)
                    worst = max(worst, exit_code(backup))
            if scratch is not None:
                scratch.close()
            return worst
    except RunLocked as exc:
        print(f"pm-eod: {exc}", file=sys.stderr)
        return 1


def _emit(
    args: argparse.Namespace, columns: list[str], rows: list[dict[str, Any]]
) -> None:
    if args.format == "json":
        print(json.dumps([{c: r.get(c) for c in columns} for r in rows], indent=2))
    elif args.format == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=columns, extrasaction="ignore")
        if not args.no_header:
            writer.writeheader()
        writer.writerows(rows)
    elif not rows:
        print("No rows found.")
    else:
        widths = [max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in columns]
        if not args.no_header:
            print(" | ".join(c.ljust(w) for c, w in zip(columns, widths, strict=True)))
            print("-+-".join("-" * w for w in widths))
        for r in rows:
            cells = (
                str(r.get(c, "")).ljust(w) for c, w in zip(columns, widths, strict=True)
            )
            print(" | ".join(cells))


def _read_ledger(paths: Paths) -> sqlite3.Connection | None:
    """``eod.db`` read-only, or ``None`` before pm-eod has settled anything.

    The read commands never create the file (or the data directory): pointed
    at the wrong ``--datapath`` they must not leave an empty ledger behind.
    """
    return open_ledger_readonly(paths.ledger) if paths.ledger.exists() else None


def _cmd_status(args: argparse.Namespace, paths: Paths) -> int:
    if not paths.clearing.exists():
        # Nothing to judge is not healthy: a mistyped --datapath must not pass.
        print(f"pm-eod: {paths.clearing} not found", file=sys.stderr)
        if args.quiet:
            return 1
    ledger = _read_ledger(paths)
    try:
        recent = runs(ledger, limit=args.limit) if ledger else []
    finally:
        if ledger:
            ledger.close()
    waiting = pending_dates(paths)
    if args.quiet:
        # A closed day whose run failed is still waiting, so it counts here; a
        # failed run for a date that never closed (a typo) does not.
        return 1 if waiting else 0
    rows = [
        {
            **r,
            "steps": " ".join(
                f"{s['step']}:{s['status']}" for s in json.loads(r["steps_json"])
            ),
        }
        for r in recent
    ]
    _emit(args, ["trade_date", "status", "started_at", "finished_at", "steps"], rows)
    if waiting:
        print(f"pending: {', '.join(waiting)}", file=sys.stderr)
    return 0


def _cmd_balances(args: argparse.Namespace, paths: Paths) -> int:
    ledger = _read_ledger(paths) or open_scratch_ledger(paths.ledger)
    try:
        if args.check:
            bad = check_zero_sum(ledger)
            print(
                f"NOT zero-sum: {', '.join(bad)}"
                if bad
                else "OK - every settled date sums to zero"
            )
            return 1 if bad else 0
        try:
            roster = load_roster(paths.roster)
        except RosterError as exc:
            print(f"pm-eod: {exc}", file=sys.stderr)
            return 1
        got = balances(
            ledger,
            as_of=args.date,
            openings={g: t.opening_minor for g, t in roster.items()},
        )
    finally:
        ledger.close()
    wanted = args.gateway.upper() if args.gateway else None
    rows = [
        {"account": a, "balance": fmt_minor(b)}
        for a, b in sorted(got.items())
        if wanted is None or a == wanted
    ]
    _emit(args, ["account", "balance"], rows)
    return 0


def _cmd_show(args: argparse.Namespace, paths: Paths) -> int:
    ledger = _read_ledger(paths) or open_scratch_ledger(paths.ledger)
    try:
        if args.steps:
            run = run_for(ledger, args.date)
            steps = json.loads(run["steps_json"]) if run else []
            _emit(args, ["step", "status", "message"], steps)
            return 0
        amounts = day_amounts(ledger, args.date)
        detail = day_detail(ledger, args.date)
    finally:
        ledger.close()
    wanted = args.gateway.upper() if args.gateway else None
    rows = [
        {
            "trade_date": args.date,
            "account": a,
            "amount": fmt_minor(amounts[a]),
            "detail": (
                {s: str(v) for s, v in sorted(detail[a].items())}
                if args.format == "json"
                else " ".join(f"{s}={v}" for s, v in sorted(detail[a].items()))
            ),
        }
        for a in sorted(amounts)
        if wanted is None or a == wanted
    ]
    _emit(args, ["trade_date", "account", "amount", "detail"], rows)
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if getattr(args, "date", None) is not None:
        try:
            validate_date(args.date)
        except ValueError as exc:
            print(f"pm-eod: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
    paths = Paths(args.datapath)
    handler = {
        "run": _cmd_run,
        "status": _cmd_status,
        "balances": _cmd_balances,
        "show": _cmd_show,
    }[args.command]
    try:
        code = handler(args, paths)
    except (sqlite3.Error, OSError) as exc:
        # Outside any step (the ledger itself, a damaged clearing.db): no
        # traceback for what an operator can fix, but a failure all the same.
        print(f"pm-eod: {exc}", file=sys.stderr)
        code = 1
    raise SystemExit(code)

"""pm-eod — close a trading day: settle, report, housekeeping.

  pm-eod run --date 2026-11-02     one trading date
  pm-eod run --pending             every closed date not yet done, oldest first
  pm-eod status [-q]               recent runs; -q is a health check (exit 0/1)
  pm-eod balances [--check]        running balances per account

Exit codes of ``run``: 0 clean, 1 the day failed (gate, settlement or report),
2 only housekeeping warnings.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edumatcher.audit.archive import session_timezone, today_in
from edumatcher.clearing.store import validate_date
from edumatcher.config import DATA_DIR
from edumatcher.eod.ledger import balances, check_zero_sum, open_ledger, runs
from edumatcher.eod.report import fmt_minor
from edumatcher.eod.roster import RosterError, load_roster
from edumatcher.eod.runner import (
    STEPS,
    Options,
    Paths,
    RunLocked,
    RunOutcome,
    exit_code,
    pending_dates,
    run_day,
    run_lock,
)

_LABEL = {"ok": "ok", "warn": "warn", "fail": "FAIL"}


def _today() -> str:
    return today_in(session_timezone())


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
        "--only", choices=STEPS, help="Run just this step of an already settled date"
    )
    run.add_argument(
        "--force",
        action="store_true",
        help="Do not require the CLOSED session event (no scheduler)",
    )
    run.add_argument(
        "--redo",
        action="store_true",
        help="Recompute this date; drops its settlement and every later date's",
    )
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="Gate and compute, print the amounts, write nothing",
    )
    run.add_argument("--log-keep-days", type=int, default=14, metavar="N")
    run.add_argument("--backup-keep-days", type=int, default=7, metavar="N")

    status = sub.add_parser("status", help="Recent runs")
    status.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Print nothing; exit 0 when no date is pending and the last run is ok",
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
    )
    if not args.date and not args.pending:
        print("pm-eod run: give --date or --pending", file=sys.stderr)
        return 2
    try:
        with run_lock(paths.data):
            dates = pending_dates(paths) if args.pending else [args.date]
            if not dates:
                print("nothing pending")
                return 0
            worst = 0
            for day in dates:
                outcome = run_day(
                    paths, day, opts, today=_today(), now=datetime.now(UTC)
                )
                _print_outcome(outcome)
                code = exit_code(outcome)
                if code == 1:
                    if len(dates) > 1:
                        print(f"stopping: later dates wait for {day}")
                    return 1
                worst = max(worst, code)
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


def _cmd_status(args: argparse.Namespace, paths: Paths) -> int:
    ledger = open_ledger(paths.ledger)
    try:
        recent = runs(ledger, limit=args.limit)
    finally:
        ledger.close()
    waiting = pending_dates(paths)
    if args.quiet:
        healthy = not waiting and (not recent or recent[0]["status"] == "ok")
        return 0 if healthy else 1
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
    ledger = open_ledger(paths.ledger)
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


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if getattr(args, "date", None) is not None:
        try:
            validate_date(args.date)
        except ValueError as exc:
            print(f"pm-eod: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
    paths = Paths(args.datapath)
    handler = {"run": _cmd_run, "status": _cmd_status, "balances": _cmd_balances}[
        args.command
    ]
    raise SystemExit(handler(args, paths))

"""Run a trading day's close: gate, settle, report, housekeeping.

:func:`run_day` is the whole of ``pm-eod run`` for one date.  Only ``gate`` and
``settle`` (and ``report``, whose files are the deliverable) can fail the day;
housekeeping trouble is reported as a warning and never withholds statements.
"""

from __future__ import annotations

import fcntl
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from edumatcher.clearing.store import (
    closed_trade_dates,
    open_readonly_connection,
    query_close_snapshot_dates,
    query_close_snapshots,
    query_reconcile,
    query_session_events,
)
from edumatcher.eod.assemble import build_day
from edumatcher.eod.housekeeping import (
    StepResult,
    archive_audit,
    backup_databases,
    compress_logs,
)
from edumatcher.eod.ledger import (
    LedgerError,
    last_settled_before,
    open_ledger,
    record_day,
    record_run,
    runs,
    settled_dates,
)
from edumatcher.eod.report import write_day
from edumatcher.eod.roster import RosterError, load_roster
from edumatcher.eod.settle import SettlementError, settle_date
from edumatcher.stats.query import open_readonly_connection as open_stats

STEPS: tuple[str, ...] = ("report", "audit", "logs", "backup")


class RunLocked(Exception):
    """Another pm-eod run is active."""


@dataclass(frozen=True)
class Paths:
    """Every file pm-eod reads or writes, derived from the data directory."""

    data: Path

    @property
    def clearing(self) -> Path:
        return self.data / "clearing.db"

    @property
    def stats(self) -> Path:
        return self.data / "stats.db"

    @property
    def ledger(self) -> Path:
        return self.data / "eod.db"

    @property
    def roster(self) -> Path:
        return self.data / "ref_data" / "roster.yaml"

    @property
    def audit_dir(self) -> Path:
        return self.data / "audit"

    @property
    def logs(self) -> Path:
        return self.data / "logs"

    @property
    def backup(self) -> Path:
        return self.data / "backup"

    @property
    def settlement(self) -> Path:
        return self.data / "settlement"


@dataclass(frozen=True)
class Options:
    force: bool = False
    redo: bool = False
    only: str | None = None
    dry_run: bool = False
    log_keep_days: int = 14
    backup_keep_days: int = 7
    #: File names (``clearing.db`` ...) left out of the backup.
    backup_skip: tuple[str, ...] = ()
    #: False defers the backup to the caller: a run of several dates copies
    #: the same current databases each time, so it takes one at the end.
    backup: bool = True


@dataclass(frozen=True)
class RunOutcome:
    trade_date: str
    steps: tuple[StepResult, ...]


def exit_code(outcome: RunOutcome) -> int:
    """0 clean, 1 the day failed, 2 only housekeeping warnings."""
    statuses = {s.status for s in outcome.steps}
    return 1 if "fail" in statuses else 2 if "warn" in statuses else 0


@contextmanager
def run_lock(data: Path) -> Generator[None, None, None]:
    """Exclusive lock so a scheduler hook and a manual run never overlap."""
    data.mkdir(parents=True, exist_ok=True)
    with (data / ".pm-eod.lock").open("a") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RunLocked("another pm-eod run is active") from exc
        yield


def pending_dates(paths: Paths) -> list[str]:
    """Dates that closed, have a close snapshot and no ``ok`` run, oldest first.

    "Closed" is :func:`~edumatcher.clearing.store.closed_trade_dates`, the same
    rule as the gate: a day that is still trading is not pending, and neither
    is a day whose only phase is the engine's start-up CLOSED (pm-scheduler
    runs ``--pending`` when it starts, often before the open).

    Dates without a snapshot (history from before snapshots existed) are not
    pending: they could never be settled and would block every later day.
    """
    if not paths.clearing.exists():
        return []
    clearing = open_readonly_connection(paths.clearing)
    try:
        closed = closed_trade_dates(clearing)
        snapped = set(query_close_snapshot_dates(clearing))
    finally:
        clearing.close()
    ledger = open_ledger(paths.ledger)
    try:
        done = {
            r["trade_date"]
            for r in runs(ledger, limit=1_000_000)
            if r["status"] == "ok"
        }
    finally:
        ledger.close()
    return sorted((closed & snapped) - done)


def _gate(clearing: sqlite3.Connection, trade_date: str, force: bool) -> StepResult:
    events = query_session_events(
        clearing, event_type="PHASE", from_date=trade_date, to_date=trade_date
    )
    if not force:
        if not events:
            return StepResult(
                "gate", "fail", f"no session phase recorded for {trade_date}"
            )
        # A mid-day restart re-announces CLOSED and trading goes on, and an
        # engine started before the open announces CLOSED too: neither is the
        # close (closed_trade_dates).
        if not closed_trade_dates(clearing, trade_date):
            return StepResult("gate", "fail", f"{trade_date} has not closed yet")
    if not query_close_snapshots(clearing, date_value=trade_date, limit=1):
        return StepResult("gate", "fail", f"no close snapshot for {trade_date}")
    problems = query_reconcile(clearing, from_date=trade_date, to_date=trade_date)
    if problems:
        return StepResult(
            "gate",
            "fail",
            f"clearing does not reconcile for {trade_date} ({len(problems)} discrepancies; "
            "see pm-clearing-cli reconcile)",
        )
    return StepResult("gate", "ok", "closed, snapshot present, reconciled")


def run_day(
    paths: Paths, trade_date: str, opts: Options, *, today: str, now: datetime
) -> RunOutcome:
    steps: list[StepResult] = []
    started = now.isoformat()

    def finish() -> RunOutcome:
        outcome = RunOutcome(trade_date, tuple(steps))
        if opts.only is None and not opts.dry_run:
            failed = {s.step for s in steps if s.status == "fail"}
            status = (
                "failed" if failed - {"report"} else "report-failed" if failed else "ok"
            )
            ledger = open_ledger(paths.ledger)
            try:
                record_run(
                    ledger,
                    trade_date,
                    status,
                    started,
                    datetime.now(now.tzinfo).isoformat(),
                    [
                        {"step": s.step, "status": s.status, "message": s.message}
                        for s in steps
                    ],
                )
            finally:
                ledger.close()
        return outcome

    if not paths.clearing.exists():
        steps.append(StepResult("gate", "fail", f"{paths.clearing} not found"))
        return finish()
    clearing = open_readonly_connection(paths.clearing)
    try:
        if opts.only is None:
            gate = _gate(clearing, trade_date, opts.force)
            steps.append(gate)
            if gate.status == "fail":
                return finish()
            if opts.dry_run:
                return _dry_run(paths, clearing, trade_date, steps)
            steps.append(_settle(paths, clearing, trade_date, opts.redo))
            if steps[-1].status == "fail":
                return finish()
        if opts.only in (None, "report"):
            steps.append(_report(paths, clearing, trade_date))
        if opts.only in (None, "audit"):
            steps.append(archive_audit(paths.audit_dir, today))
        if opts.only in (None, "logs"):
            steps.append(
                compress_logs(paths.logs, now=now, keep_days=opts.log_keep_days)
            )
        if opts.only in (None, "backup"):
            steps.append(
                backup_step(paths, trade_date, opts)
                if opts.backup
                else StepResult(
                    "backup", "ok", "deferred: one backup after the run's last date"
                )
            )
    finally:
        clearing.close()
    return finish()


def backup_step(paths: Paths, trade_date: str, opts: Options) -> StepResult:
    """Back up the databases under ``backup/<trade_date>/``."""
    wanted = [
        db
        for db in (paths.clearing, paths.stats, paths.ledger)
        if db.name not in opts.backup_skip
    ]
    backup = backup_databases(
        wanted, paths.backup, trade_date, keep_days=opts.backup_keep_days
    )
    if opts.backup_skip:
        backup = StepResult(
            backup.step,
            backup.status,
            f"{backup.message}; skipped by request: {', '.join(opts.backup_skip)}",
        )
    return backup


def _dry_run(
    paths: Paths, clearing: sqlite3.Connection, trade_date: str, steps: list[StepResult]
) -> RunOutcome:
    previous = None
    if paths.ledger.exists():  # a dry run never creates eod.db
        ledger = open_ledger(paths.ledger)
        try:
            previous = last_settled_before(ledger, trade_date)
        finally:
            ledger.close()
    try:
        result = settle_date(clearing, trade_date, previous)
    except SettlementError as exc:
        steps.append(StepResult("settle", "fail", str(exc)))
    else:
        lines = ", ".join(
            f"{g} {a / 100:+.2f}" for g, a in sorted(result.amounts_minor.items())
        )
        steps.append(StepResult("settle", "ok", f"would settle: {lines or 'nobody'}"))
    return RunOutcome(trade_date, tuple(steps))


def _settle(
    paths: Paths, clearing: sqlite3.Connection, trade_date: str, redo: bool
) -> StepResult:
    ledger = open_ledger(paths.ledger)
    try:
        settled = set(settled_dates(ledger))
        if not redo and trade_date in settled:
            return StepResult("settle", "ok", "already settled")
        # Dates settle in order: once a later date is settled an earlier one
        # never can be, and its day would be folded into the wrong interval.
        earlier = [
            d for d in pending_dates(paths) if d < trade_date and d not in settled
        ]
        if earlier:
            return StepResult(
                "settle",
                "fail",
                f"{earlier[0]} has closed but is not settled; settle the dates "
                "in order (pm-eod run --pending)",
            )
        try:
            result = settle_date(
                clearing, trade_date, last_settled_before(ledger, trade_date)
            )
            gone = record_day(ledger, trade_date, result, redo=redo)
        except (SettlementError, LedgerError) as exc:
            return StepResult("settle", "fail", str(exc))
        if not redo:
            return StepResult("settle", "ok", "settled")
        return StepResult(
            "settle", "ok", f"redone, dropped {', '.join(gone)}" if gone else "redone"
        )
    finally:
        ledger.close()


def _report(paths: Paths, clearing: sqlite3.Connection, trade_date: str) -> StepResult:
    ledger = open_ledger(paths.ledger)
    stats = open_stats(paths.stats) if paths.stats.exists() else None
    try:
        if trade_date not in settled_dates(ledger):
            return StepResult("report", "fail", f"{trade_date} is not settled")
        report = build_day(
            clearing, ledger, trade_date, load_roster(paths.roster), stats
        )
        out = write_day(paths.settlement, report)
    except (OSError, RosterError, LedgerError, sqlite3.Error) as exc:
        return StepResult("report", "fail", str(exc))
    finally:
        ledger.close()
        if stats is not None:
            stats.close()
    message = f"wrote {out}"
    if report.warnings:
        message += f" ({'; '.join(report.warnings)})"
    return StepResult("report", "ok", message)

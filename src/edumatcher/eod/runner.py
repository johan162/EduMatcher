"""Run a trading day's close: gate, settle, report, housekeeping.

:func:`run_day` is the whole of ``pm-eod run`` for one date.  Only ``gate`` and
``settle`` (and ``report``, whose files are the deliverable) can fail the day;
housekeeping trouble is reported as a warning and never withholds statements.
"""

from __future__ import annotations

import fcntl
import shutil
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
    open_ledger_readonly,
    open_scratch_ledger,
    ok_dates,
    record_day,
    record_run,
    run_for,
    settled_dates,
    settled_baseline,
)
from edumatcher.eod.report import fmt_minor, write_day
from edumatcher.eod.roster import RosterError, load_roster
from edumatcher.eod.settle import EXCHANGE, Settlement, SettlementError, settle_date
from edumatcher.stats.query import open_readonly_connection as open_stats

#: The steps ``--only`` can run on their own: everything after ``settle``.
#: ``gate`` and ``settle`` always run together, as the start of a full run.
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
    """0 clean, 1 the day failed, 3 settled and reported with warnings.

    2 is left to usage errors (argparse's code), so a script can tell "did
    nothing" from "done, but read the warnings".
    """
    statuses = {s.status for s in outcome.steps}
    return 1 if "fail" in statuses else 3 if "warn" in statuses else 0


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
    done: set[str] = set()
    if paths.ledger.exists():  # read-only: status and dry runs create nothing
        ledger = open_ledger_readonly(paths.ledger)
        try:
            done = ok_dates(ledger)
        finally:
            ledger.close()
    return sorted((closed & snapped) - done)


def _gate(clearing: sqlite3.Connection, trade_date: str, force: bool) -> StepResult:
    events = query_session_events(
        clearing, event_type="PHASE", from_date=trade_date, to_date=trade_date
    )
    closed = "not checked (--force)" if force else "closed"
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
    if problems and _raw_trades_pruned(clearing, trade_date):
        # pm-clearing --retention-days deleted the day's trade_events and kept
        # its summaries, so every summary key looks like a discrepancy.
        return StepResult(
            "gate",
            "ok",
            f"{closed}, snapshot present; not reconciled: the day's raw trades "
            "were pruned (pm-clearing --retention-days)",
        )
    if problems:
        return StepResult(
            "gate",
            "fail",
            f"clearing does not reconcile for {trade_date} ({len(problems)} discrepancies; "
            "see pm-clearing-cli reconcile)",
        )
    return StepResult("gate", "ok", f"{closed}, snapshot present, reconciled")


def _raw_trades_pruned(clearing: sqlite3.Connection, trade_date: str) -> bool:
    """True when every ``trade_events`` row of ``trade_date`` has been pruned.

    The prune deletes whole dates from the oldest on, so the date's rows are
    gone exactly when it is older than the oldest row left (or none is left).
    """
    oldest = clearing.execute("SELECT MIN(trade_date) FROM trade_events").fetchone()
    return oldest[0] is None or oldest[0] > trade_date


def _is_settled(paths: Paths, trade_date: str) -> bool:
    if not paths.ledger.exists():
        return False
    ledger = open_ledger_readonly(paths.ledger)
    try:
        return trade_date in settled_dates(ledger)
    finally:
        ledger.close()


def run_day(
    paths: Paths,
    trade_date: str,
    opts: Options,
    *,
    today: str,
    now: datetime,
    scratch: sqlite3.Connection | None = None,
) -> RunOutcome:
    """Run every step of ``pm-eod run`` for one date and record the run.

    A dry run settles into ``scratch`` (:func:`open_scratch_ledger`; one is
    made if none is given), never into ``eod.db``, and stops after settling.
    A caller dry-running several dates passes the same scratch ledger so each
    date is measured from the previous one's dry result.
    """
    steps: list[StepResult] = []
    started = now.isoformat()
    # A settled date is only reported again: nothing is settled, so the gate
    # has nothing to protect, and a check that fails now (raw trades pruned,
    # a later discrepancy) must not turn the day back into a pending one.
    rerun = opts.only is None and not opts.redo and _is_settled(paths, trade_date)

    def finish() -> RunOutcome:
        outcome = RunOutcome(trade_date, tuple(steps))
        if opts.only is None and not opts.dry_run:
            failed = {s.step for s in steps if s.status == "fail"}
            status = (
                "failed" if failed - {"report"} else "report-failed" if failed else "ok"
            )
            ledger = open_ledger(paths.ledger)
            try:
                previous = run_for(ledger, trade_date) if rerun and failed else None
                if previous is not None and previous["status"] == "ok":
                    # The earlier files are still in place (write_day is
                    # atomic); this run's failure is in its output and exit code.
                    return outcome
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
            gate = (
                StepResult(
                    "gate",
                    "ok",
                    "already settled: not checked again (--redo recomputes)",
                )
                if rerun
                else _gate(clearing, trade_date, opts.force)
            )
            steps.append(gate)
            if gate.status == "fail":
                return finish()
            if opts.dry_run:
                ledger = scratch or open_scratch_ledger(paths.ledger)
                try:
                    steps.append(
                        _settle(paths, clearing, ledger, trade_date, opts.redo, True)
                    )
                finally:
                    if scratch is None:
                        ledger.close()
                return RunOutcome(trade_date, tuple(steps))
            ledger = open_ledger(paths.ledger)
            try:
                steps.append(_settle(paths, clearing, ledger, trade_date, opts.redo))
            finally:
                ledger.close()
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


def _settle(
    paths: Paths,
    clearing: sqlite3.Connection,
    ledger: sqlite3.Connection,
    trade_date: str,
    redo: bool,
    dry_run: bool = False,
) -> StepResult:
    """Settle ``trade_date`` into ``ledger`` (a scratch copy for a dry run)."""
    settled = set(settled_dates(ledger))
    if not redo and trade_date in settled:
        return StepResult("settle", "ok", "already settled")
    # Dates settle in order: once a later date is settled an earlier one
    # never can be, and its day would be folded into the wrong interval.
    earlier = [d for d in pending_dates(paths) if d < trade_date and d not in settled]
    if earlier:
        return StepResult(
            "settle",
            "fail",
            f"{earlier[0]} has closed but is not settled; settle the dates "
            "in order (pm-eod run --pending)",
        )
    try:
        result, previous = _settle_against_ledger(clearing, ledger, trade_date)
        gone = record_day(ledger, trade_date, result, redo=redo)
    except (SettlementError, LedgerError, sqlite3.Error) as exc:
        return StepResult("settle", "fail", str(exc))
    if not dry_run:
        # The dropped dates' statements show balances the ledger no longer
        # has; they are written again when those dates are settled again.
        for day in gone:
            shutil.rmtree(paths.settlement / day, ignore_errors=True)
    if dry_run:
        amounts = dict(result.amounts_minor)
        if result.rounding_minor:
            amounts[EXCHANGE] = result.rounding_minor
        lines = ", ".join(
            f"{a} {'+' if v >= 0 else ''}{fmt_minor(v)}"
            for a, v in sorted(amounts.items())
        )
        message = f"would settle: {lines or 'nobody'}"
        if gone:
            message += f"; would drop {', '.join(gone)}"
    else:
        message = (
            "settled"
            if not redo
            else f"redone, dropped {', '.join(gone)}" if gone else "redone"
        )
    if result.rounding_minor:
        # Normally a cent or two; a growing residual is the first sign of an
        # accounting error below the tolerance.
        message += (
            f"; rounding {fmt_minor(result.rounding_minor)} booked to {EXCHANGE}"
            f" (exact total of the day {result.drift})"
        )
    if result.baseline_reset:
        return StepResult(
            "settle",
            "warn",
            f"{message}; clearing.db was replaced after {previous} was settled "
            "(pm-opctl-cli clear --state), so this day is measured from zero",
        )
    if not result.baseline_changed:
        return StepResult("settle", "ok", message)
    # The money is right (the change is in this day), but it belongs to an
    # earlier date: say so, so the operator can choose --redo instead.
    return StepResult(
        "settle",
        "warn",
        f"{message}; the close snapshot of {previous} changed after it was "
        "settled (the date closed again), so the difference is booked on "
        f"{trade_date}; pm-eod run --date {previous} --redo books it on "
        f"{previous} instead",
    )


def _settle_against_ledger(
    clearing: sqlite3.Connection, ledger: sqlite3.Connection, trade_date: str
) -> tuple[Settlement, str | None]:
    """Settle ``trade_date`` from the last settled date's recorded equity."""
    previous = last_settled_before(ledger, trade_date)
    settled = settled_baseline(ledger, previous) if previous else None
    return settle_date(clearing, trade_date, previous, settled), previous


def _report(paths: Paths, clearing: sqlite3.Connection, trade_date: str) -> StepResult:
    ledger = None
    stats = None
    try:
        ledger = open_ledger(paths.ledger)
        stats = open_stats(paths.stats) if paths.stats.exists() else None
        if trade_date not in settled_dates(ledger):
            return StepResult("report", "fail", f"{trade_date} is not settled")
        report = build_day(
            clearing, ledger, trade_date, load_roster(paths.roster), stats
        )
        out = write_day(paths.settlement, report)
    except (OSError, RosterError, LedgerError, sqlite3.Error) as exc:
        return StepResult("report", "fail", str(exc))
    finally:
        if ledger is not None:
            ledger.close()
        if stats is not None:
            stats.close()
    message = f"wrote {out}"
    if report.warnings:
        message += f" ({'; '.join(report.warnings)})"
    return StepResult("report", "ok", message)

"""``pm-log-cli diagnose`` — rule-based troubleshooting heuristics (§9.6).

Seven fixed, documented, SQL-aggregate-plus-threshold heuristics — no
statistical or ML model — so "why did it flag this" always has a
one-sentence, inspectable answer, per the design doc's explicit non-goal
(§3.2) for this feature. Each :class:`Finding` cites the exact
``pm-log-cli query`` invocation that would reproduce it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

# Default thresholds — §9.6's table.
DEFAULT_ERROR_SPIKE_MULTIPLIER = 5.0
DEFAULT_REPEATED_WARNING_THRESHOLD = 20
DEFAULT_SILENCE_THRESHOLD_SEC = 30
DEFAULT_CLOCK_SKEW_THRESHOLD_SEC = 2.0


@dataclass
class Finding:
    heuristic: str
    severity: str  # "info" | "warning" | "error"
    message: str
    recommendation: str
    repro_command: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "heuristic": self.heuristic,
            "severity": self.severity,
            "message": self.message,
            "recommendation": self.recommendation,
            "repro_command": self.repro_command,
            "details": self.details,
        }


def _parse_ts(ts: str) -> datetime:
    # log_events timestamps are UTC ISO-8601 with milliseconds, "Z" suffix.
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _since_iso(seconds: float) -> str:
    dt = datetime.now(tz=timezone.utc) - timedelta(seconds=seconds)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Heuristic 1: error-rate spike
# ---------------------------------------------------------------------------


def _check_error_spike(
    conn: sqlite3.Connection,
    *,
    process_filter: str | None,
    multiplier: float,
) -> list[Finding]:
    findings: list[Finding] = []
    recent_cutoff = _since_iso(5 * 60)
    baseline_cutoff = _since_iso(65 * 60)

    where = "process = ?" if process_filter else "1=1"
    params_base: list[Any] = [process_filter] if process_filter else []

    processes = conn.execute(
        f"SELECT DISTINCT process FROM log_events WHERE {where}", params_base
    ).fetchall()

    for (proc,) in processes:
        recent = conn.execute(
            "SELECT COUNT(*) FROM log_events "
            "WHERE process = ? AND level IN ('ERROR','CRITICAL') AND client_ts >= ?",
            (proc, recent_cutoff),
        ).fetchone()[0]
        baseline_total = conn.execute(
            "SELECT COUNT(*) FROM log_events "
            "WHERE process = ? AND level IN ('ERROR','CRITICAL') "
            "AND client_ts >= ? AND client_ts < ?",
            (proc, baseline_cutoff, recent_cutoff),
        ).fetchone()[0]
        baseline_per_5min = baseline_total / 12.0  # 60 min / 5 min buckets

        if recent >= 3 and (
            baseline_per_5min == 0 or recent > baseline_per_5min * multiplier
        ):
            findings.append(
                Finding(
                    heuristic="error_rate_spike",
                    severity="error",
                    message=(
                        f"{proc} logged {recent} ERROR/CRITICAL in the last 5 minutes "
                        f"vs. a baseline of ~{baseline_per_5min:.1f}"
                    ),
                    recommendation=(
                        f"Check {proc}'s connection/dependencies and review recent "
                        f"tracebacks."
                    ),
                    repro_command=(
                        f"pm-log-cli query --process {proc} --level ERROR --has-exception"
                    ),
                    details={
                        "process": proc,
                        "recent": recent,
                        "baseline_per_5min": baseline_per_5min,
                    },
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Heuristic 2: repeated identical warning
# ---------------------------------------------------------------------------


def _check_repeated_warning(
    conn: sqlite3.Connection,
    *,
    process_filter: str | None,
    since: str | None,
    threshold: int,
) -> list[Finding]:
    clauses = ["level IN ('WARNING','ERROR','CRITICAL')"]
    params: list[Any] = []
    if process_filter:
        clauses.append("process = ?")
        params.append(process_filter)
    if since:
        clauses.append("client_ts >= ?")
        params.append(since)
    where = " AND ".join(clauses)

    rows = conn.execute(
        f"SELECT process, logger, message, COUNT(*) AS n FROM log_events "
        f"WHERE {where} GROUP BY process, logger, message "
        f"HAVING n >= ? ORDER BY n DESC",
        [*params, threshold],
    ).fetchall()

    findings: list[Finding] = []
    for proc, logger, message, n in rows:
        short_msg = message if len(message) <= 60 else message[:57] + "..."
        findings.append(
            Finding(
                heuristic="repeated_warning",
                severity="warning",
                message=f'{proc} logged "{short_msg}" {n} times in the queried window',
                recommendation=(
                    f"Investigate why {logger} keeps repeating this message; "
                    "it may indicate a stuck retry loop or a persistent misconfiguration."
                ),
                repro_command=(
                    f"pm-log-cli query --process {proc} --logger {logger!r} --grep {short_msg[:30]!r}"
                ),
                details={"process": proc, "logger": logger, "count": n},
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Heuristic 3: process silence after prior activity
# ---------------------------------------------------------------------------


def _check_process_silence(
    conn: sqlite3.Connection,
    *,
    process_filter: str | None,
    silence_threshold_sec: int,
) -> list[Finding]:
    """Separate a process that is quiet from one that has stopped talking.

    ``last_seen_at`` advances only on LOG frames, so on its own it cannot
    tell the two apart — which is why this used to warn about every
    event-driven process that simply had nothing to report. LALF clients
    send HB on an idle connection, and ``last_heartbeat_at`` records it, so
    a quiet process that is still heartbeating is now reported as the
    non-event it is.
    """
    where = "disconnected_at IS NULL"
    params: list[Any] = []
    if process_filter:
        where += " AND process = ?"
        params.append(process_filter)

    rows = conn.execute(
        "SELECT process, session, last_seen_at, last_heartbeat_at "
        f"FROM processes WHERE {where}",
        params,
    ).fetchall()

    now = datetime.now(tz=timezone.utc)
    findings: list[Finding] = []
    quiet: list[str] = []
    for proc, session, last_seen_at, last_heartbeat_at in rows:
        try:
            log_idle = (now - _parse_ts(last_seen_at)).total_seconds()
        except ValueError:
            continue
        if log_idle < silence_threshold_sec:
            continue

        # A row predating the heartbeat column has no evidence either way,
        # so fall back to treating the last log as the last contact.
        contact_idle = log_idle
        if last_heartbeat_at:
            try:
                contact_idle = min(
                    log_idle, (now - _parse_ts(last_heartbeat_at)).total_seconds()
                )
            except ValueError:
                pass

        if contact_idle >= silence_threshold_sec:
            findings.append(
                Finding(
                    heuristic="process_silence",
                    severity="warning",
                    message=(
                        f"{proc} (session {session}) has not logged or heartbeated "
                        f"in {contact_idle:.0f}s despite an open connection"
                    ),
                    recommendation=(
                        f"It may be stuck; check whether the {proc} process is still responsive."
                    ),
                    repro_command="pm-log-cli processes --active",
                    details={
                        "process": proc,
                        "session": session,
                        "idle_sec": log_idle,
                        "heartbeat_idle_sec": contact_idle,
                    },
                )
            )
        else:
            quiet.append(proc)

    # One line, not one per process: on a healthy system every event-driven
    # process is quiet most of the time, and a page of "all fine" entries
    # buries the findings that do need reading.
    if quiet:
        findings.append(
            Finding(
                heuristic="process_silence",
                severity="info",
                message=(
                    f"{len(quiet)} process(es) connected and heartbeating with "
                    f"nothing to log for over {silence_threshold_sec}s: "
                    + ", ".join(sorted(quiet))
                ),
                recommendation=(
                    "No action needed: these are alive and simply have nothing "
                    "to report. Expected for event-driven processes between "
                    "client connections."
                ),
                repro_command="pm-log-cli processes --active",
                details={"processes": sorted(quiet), "count": len(quiet)},
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Heuristic 4: clock skew
# ---------------------------------------------------------------------------


def _check_clock_skew(
    conn: sqlite3.Connection,
    *,
    process_filter: str | None,
    since: str | None,
    threshold_sec: float,
) -> list[Finding]:
    clauses = ["1=1"]
    params: list[Any] = []
    if process_filter:
        clauses.append("process = ?")
        params.append(process_filter)
    if since:
        clauses.append("client_ts >= ?")
        params.append(since)
    where = " AND ".join(clauses)

    rows = conn.execute(
        f"SELECT process, client_ts, server_ts FROM log_events WHERE {where}",
        params,
    ).fetchall()

    by_process: dict[str, list[float]] = {}
    for proc, client_ts, server_ts in rows:
        try:
            c = _parse_ts(client_ts)
            s = _parse_ts(server_ts)
        except ValueError:
            continue
        by_process.setdefault(proc, []).append((s - c).total_seconds())

    findings: list[Finding] = []
    for proc, skews in by_process.items():
        if not skews:
            continue
        skews_sorted = sorted(skews)
        median = skews_sorted[len(skews_sorted) // 2]
        if abs(median) >= threshold_sec:
            findings.append(
                Finding(
                    heuristic="clock_skew",
                    severity="warning",
                    message=(
                        f"{proc}'s log timestamps are consistently ~{median:.1f}s "
                        f"{'behind' if median > 0 else 'ahead of'} pm-log-srv's clock"
                    ),
                    recommendation=(
                        "Verify the two machines' clocks are synchronized if running "
                        "cross-host (see EduMatcher-Cross-host-connection.md)."
                    ),
                    repro_command=f"pm-log-cli query --process {proc} --format json",
                    details={
                        "process": proc,
                        "median_skew_sec": median,
                        "sample_size": len(skews),
                    },
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Heuristic 5: truncated-message rate
# ---------------------------------------------------------------------------


def _check_truncated_rate(
    conn: sqlite3.Connection,
    *,
    process_filter: str | None,
    since: str | None,
) -> list[Finding]:
    clauses = ["truncated = 1"]
    params: list[Any] = []
    if process_filter:
        clauses.append("process = ?")
        params.append(process_filter)
    if since:
        clauses.append("client_ts >= ?")
        params.append(since)
    where = " AND ".join(clauses)

    rows = conn.execute(
        f"SELECT process, COUNT(*) AS n FROM log_events WHERE {where} GROUP BY process",
        params,
    ).fetchall()

    findings: list[Finding] = []
    for proc, n in rows:
        findings.append(
            Finding(
                heuristic="truncated_messages",
                severity="warning",
                message=f"{proc} sent {n} oversized log message(s) that were truncated",
                recommendation=(
                    "If this recurs, consider raising log_server.max_message_bytes."
                ),
                repro_command=f"pm-log-cli query --process {proc} --format json",
                details={"process": proc, "count": n},
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Heuristic 6: exception clustering by logger
# ---------------------------------------------------------------------------


def _check_exception_clustering(
    conn: sqlite3.Connection,
    *,
    process_filter: str | None,
    since: str | None,
) -> list[Finding]:
    clauses = ["has_exception = 1"]
    params: list[Any] = []
    if process_filter:
        clauses.append("process = ?")
        params.append(process_filter)
    if since:
        clauses.append("client_ts >= ?")
        params.append(since)
    where = " AND ".join(clauses)

    total = conn.execute(
        f"SELECT COUNT(*) FROM log_events WHERE {where}", params
    ).fetchone()[0]
    if total < 3:
        return []

    top = conn.execute(
        f"SELECT logger, COUNT(*) AS n FROM log_events WHERE {where} "
        f"GROUP BY logger ORDER BY n DESC LIMIT 1",
        params,
    ).fetchone()
    if top is None:
        return []
    logger, n = top

    return [
        Finding(
            heuristic="exception_clustering",
            severity="warning",
            message=f"Most exceptions in this window come from {logger} ({n} of {total})",
            recommendation="Start troubleshooting there.",
            repro_command=f"pm-log-cli query --logger {logger!r} --has-exception --format json",
            details={"logger": logger, "count": n, "total": total},
        )
    ]


# ---------------------------------------------------------------------------
# Heuristic 7: likely fallback-to-file event (§8.6)
# ---------------------------------------------------------------------------


#: Disconnects that carry their own explanation. A client that sent EXIT
#: shut down deliberately, and a session rejected during the handshake
#: never became a running process — neither is a vanished process.
_EXPECTED_DISCONNECT_REASONS = frozenset({"client_exit", "hello_timeout"})


def _check_fallback_to_file(
    conn: sqlite3.Connection,
    *,
    process_filter: str | None,
    silence_threshold_sec: int,
) -> list[Finding]:
    """Report a process that dropped off and never came back.

    Only each process's *latest* session can qualify: an earlier one is
    proof of nothing, because the existence of a later session row proves
    the process reconnected. Looking at every session — and asking
    ``log_events`` rather than ``processes`` whether it returned — is what
    made this heuristic fire hundreds of times for a single process that
    simply never logs anything.
    """
    # One row per process: the newest session by connected_at. SQLite's
    # bare-column-with-MAX guarantee picks that row's other columns; the
    # outer query then keeps only those that are closed.
    where = "disconnected_at IS NOT NULL"
    params: list[Any] = []
    if process_filter:
        where += " AND process = ?"
        params.append(process_filter)

    rows = conn.execute(
        "SELECT process, session, disconnected_at, disconnect_reason FROM ("
        "  SELECT process, session, disconnected_at, disconnect_reason,"
        "         MAX(connected_at) AS _latest"
        "  FROM processes GROUP BY process"
        f") WHERE {where}",
        params,
    ).fetchall()

    findings: list[Finding] = []
    now = datetime.now(tz=timezone.utc)
    for proc, session, disconnected_at, reason in rows:
        try:
            disc = _parse_ts(disconnected_at)
        except ValueError:
            continue
        if (now - disc).total_seconds() < silence_threshold_sec:
            continue
        if reason in _EXPECTED_DISCONNECT_REASONS:
            continue

        # Rows written before disconnect_reason existed carry no evidence,
        # so say what is actually known rather than guessing a cause.
        if reason:
            summary = (
                f"{proc} disconnected from pm-log-srv at {disconnected_at} without "
                f"sending EXIT (reason: {reason}) and has not reconnected"
            )
        else:
            summary = (
                f"{proc} disconnected from pm-log-srv at {disconnected_at} and has "
                f"not reconnected; the reason was not recorded, because this "
                f"database predates disconnect-reason tracking"
            )
        findings.append(
            Finding(
                heuristic="fallback_to_file",
                severity="warning",
                message=summary,
                recommendation=(
                    f"The process either exited abnormally or failed over to file "
                    f"logging (§8.6 of the design doc). Check whether {proc} is "
                    f"still running, then check logs/{proc}.log for anything it "
                    f"logged after that point — those records never reached this "
                    f"database."
                ),
                repro_command="pm-log-cli processes --format json",
                details={
                    "process": proc,
                    "session": session,
                    "disconnected_at": disconnected_at,
                    "disconnect_reason": reason,
                },
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_diagnostics(
    conn: sqlite3.Connection,
    *,
    process_filter: str | None = None,
    since: str | None = None,
    error_spike_multiplier: float = DEFAULT_ERROR_SPIKE_MULTIPLIER,
    repeated_warning_threshold: int = DEFAULT_REPEATED_WARNING_THRESHOLD,
    silence_threshold_sec: int = DEFAULT_SILENCE_THRESHOLD_SEC,
    clock_skew_threshold_sec: float = DEFAULT_CLOCK_SKEW_THRESHOLD_SEC,
) -> list[Finding]:
    """Run all seven heuristics (§9.6) and return every finding, in order."""
    findings: list[Finding] = []
    findings.extend(
        _check_error_spike(
            conn, process_filter=process_filter, multiplier=error_spike_multiplier
        )
    )
    findings.extend(
        _check_repeated_warning(
            conn,
            process_filter=process_filter,
            since=since,
            threshold=repeated_warning_threshold,
        )
    )
    findings.extend(
        _check_process_silence(
            conn,
            process_filter=process_filter,
            silence_threshold_sec=silence_threshold_sec,
        )
    )
    findings.extend(
        _check_clock_skew(
            conn,
            process_filter=process_filter,
            since=since,
            threshold_sec=clock_skew_threshold_sec,
        )
    )
    findings.extend(
        _check_truncated_rate(conn, process_filter=process_filter, since=since)
    )
    findings.extend(
        _check_exception_clustering(conn, process_filter=process_filter, since=since)
    )
    findings.extend(
        _check_fallback_to_file(
            conn,
            process_filter=process_filter,
            silence_threshold_sec=silence_threshold_sec,
        )
    )
    return findings

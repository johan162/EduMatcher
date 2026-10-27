"""pm-audit starts the archiver child after a day closes and at start-up (Z4)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from edumatcher.audit.archive import format_result, parse_ratio, ArchiveResult
from edumatcher.audit.main import AuditProcess
from edumatcher.audit.query import discover_log_files
from edumatcher.monitor.activity import WATCHED_INCREASES

_OK = "print('2026-10-24: 1 part(s), 10.0MB -> 750.0KB (13.5:1)')"


def _process(root: Path, snippet: str = _OK) -> tuple[AuditProcess, list[int]]:
    with (
        patch("edumatcher.audit.main.make_subscriber"),
        patch("edumatcher.audit.main.make_replier"),
    ):
        proc = AuditProcess(root / "audit.log", False, keep_days=7)
    spawned: list[int] = []

    def command() -> list[str]:
        spawned.append(1)
        return [sys.executable, "-c", snippet]

    proc._archiver_command = command
    return proc, spawned


def _wait(proc: AuditProcess) -> None:
    child = proc._archiver
    assert child is not None
    child.wait(timeout=10)
    proc._service_archiver()


def _cross_midnight(proc: AuditProcess) -> None:
    clock = [datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)]
    proc._now = lambda: clock[0]
    proc._add_to_buffer("2026-10-24", "[2026-10-24T12:00:00.000+00:00] a")
    clock[0] += timedelta(days=1)
    proc._close_ended_day()


def _sample(proc: AuditProcess, name: str) -> float:
    return next(s.value for s in proc.metric_samples() if s.name == name)


def test_no_day_closed_means_no_archiver(tmp_path: Path) -> None:
    proc, spawned = _process(tmp_path)
    proc._service_archiver()
    assert spawned == [] and proc._archiver is None
    proc._file.close()


def test_a_closed_day_starts_one_archiver_and_counts_its_result(
    tmp_path: Path,
) -> None:
    proc, spawned = _process(tmp_path)
    _cross_midnight(proc)
    proc._service_archiver()
    proc._service_archiver()  # still running or reaped: never a second one
    _wait(proc)
    assert spawned == [1]
    assert _sample(proc, "audit.archives") == 1
    assert _sample(proc, "audit.archive_ratio") == 13.5
    assert _sample(proc, "audit.archive_errors") == 0
    proc._file.close()


def test_a_day_closing_while_it_runs_is_archived_by_the_next_run(
    tmp_path: Path,
) -> None:
    proc, spawned = _process(tmp_path, "import time; time.sleep(0.3)")
    _cross_midnight(proc)
    proc._service_archiver()
    assert proc._archiver is not None
    proc._want_archive()  # another day closes meanwhile
    proc._service_archiver()
    assert spawned == [1]  # not while the first still runs
    _wait(proc)
    assert spawned == [1, 1]
    _wait(proc)
    proc._file.close()


def test_a_failing_archiver_counts_an_error_and_leaves_the_parts_readable(
    tmp_path: Path,
) -> None:
    proc, _ = _process(tmp_path, "import sys; sys.stderr.write('boom'); sys.exit(1)")
    _cross_midnight(proc)
    proc._service_archiver()
    _wait(proc)
    assert _sample(proc, "audit.archive_errors") == 1
    assert _sample(proc, "audit.archives") == 0
    assert [p.name for p in discover_log_files(tmp_path / "audit.log")][:1] == [
        "audit-2026-10-24.1.log"
    ]
    proc._file.close()


def test_the_archiver_that_cannot_start_is_an_error_not_a_crash(
    tmp_path: Path,
) -> None:
    proc, _ = _process(tmp_path)
    _cross_midnight(proc)
    with patch("edumatcher.audit.main.subprocess.Popen", side_effect=OSError("no")):
        proc._service_archiver()
    assert _sample(proc, "audit.archive_errors") == 1
    proc._file.close()


def test_start_up_asks_for_an_archive_run(tmp_path: Path) -> None:
    proc, spawned = _process(tmp_path)
    proc._running = False
    with patch.object(proc, "_receive"):
        proc.run()
    assert proc._archive_wanted is True and spawned == []


def test_the_real_command_runs_pending_with_the_retention_and_low_priority(
    tmp_path: Path,
) -> None:
    with (
        patch("edumatcher.audit.main.make_subscriber"),
        patch("edumatcher.audit.main.make_replier"),
    ):
        proc = AuditProcess(tmp_path / "audit.log", False, keep_days=7)
    cmd = proc._archiver_command()
    assert cmd[:3] == ["nice", "-n", "10"]
    assert cmd[cmd.index("--log-file") + 1] == str(tmp_path / "audit.log")
    assert cmd[-4:] == ["archive", "--pending", "--keep-days", "7"]
    proc._file.close()


def test_the_result_line_round_trips_and_other_lines_do_not_parse() -> None:
    line = format_result(ArchiveResult("2026-10-24", 3, 1350, 100), ("1.3KB", "100B"))
    assert parse_ratio(line) == 13.5
    assert parse_ratio("removed audit-2026-09-01.log.zst (older than 30 days)") is None
    assert parse_ratio("2026-10-24: no parts to archive") is None


def test_archive_errors_are_a_watched_monitor_increase() -> None:
    assert WATCHED_INCREASES["audit.archive_errors"] == "audit_archive_errors"


def test_a_real_archiver_replaces_the_closed_day_with_one_zst(
    tmp_path: Path,
) -> None:
    """End to end with the real child: day closes, parts become the archive."""
    with (
        patch("edumatcher.audit.main.make_subscriber"),
        patch("edumatcher.audit.main.make_replier"),
    ):
        proc = AuditProcess(tmp_path / "audit.log", False)
    proc._archiver_command = lambda: [
        c for c in AuditProcess._archiver_command(proc) if c not in ("nice", "-n", "10")
    ]
    _cross_midnight(proc)
    proc._service_archiver()
    _wait(proc)
    names = sorted(p.name for p in (tmp_path / "audit").iterdir())
    assert names == ["audit-2026-10-24.log.zst", ".archive.lock"] or names == [
        ".archive.lock",
        "audit-2026-10-24.log.zst",
    ]
    assert _sample(proc, "audit.archives") == 1
    assert _sample(proc, "audit.archive_errors") == 0
    proc._file.close()

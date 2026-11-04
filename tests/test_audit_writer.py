"""Day-closing audit writer: AuditFile and its use by AuditProcess (Z2)."""

from __future__ import annotations

import re
import threading
import time
from typing import Any
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from edumatcher.audit.main import AuditProcess
from edumatcher.audit.query import discover_log_files
from edumatcher.audit.writer import (
    RECORDER_START_PREFIX,
    AuditFile,
    file_day,
    header_line,
)

STOCKHOLM = ZoneInfo("Europe/Stockholm")


def _lines(path: Path) -> list[str]:
    """A file's records; every non-empty file starts with the header.  A
    recorder-start marker (A6) is not a record."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if lines:
        assert lines[0].startswith("# edumatcher-audit format=1 pm-audit="), lines[0]
    return [ln for ln in lines[1:] if not ln.startswith(RECORDER_START_PREFIX)]


def _parts(root: Path) -> list[str]:
    return sorted(p.name for p in (root / "audit").glob("*"))


class TestAuditFile:
    def test_a_later_day_closes_the_earlier_one(self, tmp_path: Path) -> None:
        f = AuditFile(tmp_path / "audit.log", 1 << 20, timezone.utc)
        f.write("2026-10-24", ["a", "b"])
        f.write("2026-10-25", ["c"])
        f.close()
        assert _lines(tmp_path / "audit" / "audit-2026-10-24.1.log") == ["a", "b"]
        assert _lines(tmp_path / "audit.log") == ["c"]

    def test_size_rollover_numbers_parts_and_never_renames(
        self, tmp_path: Path
    ) -> None:
        f = AuditFile(tmp_path / "audit.log", 10, timezone.utc)
        for n in range(3):
            f.write("2026-10-24", [f"line-{n}-xxxx"])
        f.close()
        assert _parts(tmp_path) == [
            "audit-2026-10-24.1.log",
            "audit-2026-10-24.2.log",
            "audit-2026-10-24.3.log",
        ]
        assert _lines(tmp_path / "audit" / "audit-2026-10-24.1.log") == ["line-0-xxxx"]
        assert _lines(tmp_path / "audit" / "audit-2026-10-24.3.log") == ["line-2-xxxx"]
        assert (tmp_path / "audit.log").read_text() == ""

    def test_the_next_number_follows_the_highest_existing_one(
        self, tmp_path: Path
    ) -> None:
        parts = tmp_path / "audit"
        parts.mkdir()
        (parts / "audit-2026-10-24.7.log").write_text("old\n")
        f = AuditFile(tmp_path / "audit.log", 1 << 20, timezone.utc)
        f.write("2026-10-24", ["a"])
        f.roll()
        f.close()
        assert (parts / "audit-2026-10-24.7.log").read_text() == "old\n"
        assert _lines(parts / "audit-2026-10-24.8.log") == ["a"]

    def test_an_empty_file_is_not_rolled(self, tmp_path: Path) -> None:
        f = AuditFile(tmp_path / "audit.log", 1 << 20, timezone.utc)
        f.roll()
        f.close_days_before("2030-01-01")
        f.close()
        assert not (tmp_path / "audit").exists()

    def test_restart_after_midnight_closes_yesterdays_file(
        self, tmp_path: Path
    ) -> None:
        log = tmp_path / "audit.log"
        log.write_text("[2026-10-24T21:00:00.000+00:00] [x] {}\n")  # 23:00 Stockholm
        f = AuditFile(log, 1 << 20, STOCKHOLM)
        f.close_days_before("2026-10-25")
        f.close()
        assert _parts(tmp_path) == ["audit-2026-10-24.1.log"]
        assert log.read_text() == ""

    def test_the_day_of_a_leftover_file_is_its_session_date(
        self, tmp_path: Path
    ) -> None:
        log = tmp_path / "audit.log"
        # 01:30 on the 25th, after the header a previous pm-audit wrote.
        log.write_text(f"{header_line()}\n[2026-10-24T23:30:00.000+00:00] [x] {{}}\n")
        f = AuditFile(log, 1 << 20, STOCKHOLM)
        f.write("2026-10-25", ["next"])
        f.close()
        assert discover_log_files(log) == [log]
        assert _lines(log)[-1] == "next"

    def test_a_failing_roll_keeps_every_line_and_is_retried(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "audit").write_text("")  # a file, so the parts dir cannot be made
        called: list[int] = []
        f = AuditFile(
            tmp_path / "audit.log",
            1 << 20,
            timezone.utc,
            on_day_closed=lambda: called.append(1),
        )
        f.write("2026-10-24", ["a"])
        f.write("2026-10-25", ["b"])  # the day close fails: appended instead
        f.close_days_before("2026-10-26")  # fails again, does not raise
        assert _lines(tmp_path / "audit.log") == ["a", "b"] and called == []

        (tmp_path / "audit").unlink()
        f.write("2026-10-25", ["c"])
        f.close()
        assert called == [1]
        assert _lines(tmp_path / "audit" / "audit-2026-10-24.1.log") == ["a", "b"]
        assert _lines(tmp_path / "audit.log") == ["c"]


def _process(root: Path, tz: tzinfo, clock: list[datetime]) -> AuditProcess:
    with (
        patch("edumatcher.audit.main.make_subscriber"),
        patch("edumatcher.audit.main.make_replier"),
    ):
        proc = AuditProcess(root / "audit.log", False, buffer_size=1000, session_tz=tz)
    proc._now = lambda: clock[0]
    return proc


def _record(proc: AuditProcess, n: int) -> None:
    now = proc._now()
    day = now.astimezone(proc._session_tz).date().isoformat()
    proc._add_to_buffer(day, f"[{now.isoformat(timespec='milliseconds')}] n={n}")


class TestAuditProcessDay:
    def test_one_flush_straddling_midnight_splits_by_receive_date(
        self, tmp_path: Path
    ) -> None:
        clock = [datetime(2026, 10, 24, 21, 59, 59, 990000, tzinfo=timezone.utc)]
        proc = _process(tmp_path, STOCKHOLM, clock)
        _record(proc, 1)  # 23:59:59.990 Stockholm
        clock[0] += timedelta(milliseconds=20)  # 00:00:00.010
        _record(proc, 2)
        proc._flush_buffer()  # flushed late, carrying both days
        proc._file.close()
        old = _lines(tmp_path / "audit" / "audit-2026-10-24.1.log")
        assert len(old) == 1 and old[0].endswith("n=1")
        assert _lines(tmp_path / "audit.log")[0].endswith("n=2")

    def test_an_idle_midnight_is_closed_without_a_new_line(
        self, tmp_path: Path
    ) -> None:
        clock = [datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)]
        proc = _process(tmp_path, STOCKHOLM, clock)
        _record(proc, 1)
        clock[0] = datetime(2026, 10, 24, 22, 5, tzinfo=timezone.utc)  # 00:05 on 25th
        proc._close_ended_day()
        proc._file.close()
        assert _parts(tmp_path) == ["audit-2026-10-24.1.log"]
        assert (tmp_path / "audit.log").read_text() == ""

    def test_the_day_check_leaves_todays_buffer_to_the_flush_settings(
        self, tmp_path: Path
    ) -> None:
        clock = [datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)]
        proc = _process(tmp_path, STOCKHOLM, clock)
        _record(proc, 1)
        proc._close_ended_day()
        assert (tmp_path / "audit.log").read_text() == ""
        assert len(proc._buffer) == 1
        proc._flush_buffer()
        proc._file.close()

    def test_shutdown_writes_a_line_received_while_stopping(
        self, tmp_path: Path
    ) -> None:
        clock = [datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)]
        proc = _process(tmp_path, timezone.utc, clock)

        def receive() -> None:
            while proc._running:
                time.sleep(0.01)
            time.sleep(0.2)  # still finishing the message in hand
            _record(proc, 1)

        proc._receive = receive
        threading.Timer(0.1, proc._stop).start()
        proc.run()
        assert _lines(tmp_path / "audit.log")[0].endswith("n=1")

    def test_start_up_closes_a_day_that_ended_while_down(self, tmp_path: Path) -> None:
        (tmp_path / "audit.log").write_text("[2026-10-23T10:00:00.000+00:00] [x] {}\n")
        clock = [datetime(2026, 10, 25, 8, 0, tzinfo=timezone.utc)]
        proc = _process(tmp_path, timezone.utc, clock)
        proc._file.close()
        assert _parts(tmp_path) == ["audit-2026-10-23.1.log"]

    def test_the_dst_change_day_is_one_day(self, tmp_path: Path) -> None:
        """Stockholm leaves DST 2026-10-25 01:00 UTC: that day has 25 hours."""
        times = [
            datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc),  # 00:00 CEST on 25th
            datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc),  # 02:30 CEST
            datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc),  # 02:30 CET again
            datetime(2026, 10, 25, 22, 59, tzinfo=timezone.utc),  # 23:59 CET
            datetime(2026, 10, 25, 23, 0, tzinfo=timezone.utc),  # 00:00 on the 26th
        ]
        clock = [times[0]]
        proc = _process(tmp_path, STOCKHOLM, clock)
        for n, t in enumerate(times):
            clock[0] = t
            _record(proc, n)
        proc._flush_buffer()
        proc._file.close()
        assert len(_lines(tmp_path / "audit" / "audit-2026-10-25.1.log")) == 4
        assert len(_lines(tmp_path / "audit.log")) == 1

    def test_no_line_lost_or_duplicated_under_concurrent_receive_and_timer(
        self, tmp_path: Path
    ) -> None:
        clock = [datetime(2026, 10, 24, 23, 59, 59, tzinfo=timezone.utc)]
        proc = _process(tmp_path, timezone.utc, clock)
        proc._file._max_bytes = 2000  # force size rollovers as well
        total = 3000
        stop = threading.Event()

        def timer() -> None:
            while not stop.is_set():
                proc._flush_buffer()
                proc._close_ended_day()

        t = threading.Thread(target=timer)
        t.start()
        for n in range(total):
            if n == total // 2:
                clock[0] += timedelta(seconds=2)  # crosses midnight
            _record(proc, n)
        stop.set()
        t.join()
        proc._flush_buffer()
        proc._file.close()

        got: list[str] = []
        for path in discover_log_files(tmp_path / "audit.log"):
            got += _lines(path)
        assert [int(x.rsplit("n=", 1)[1]) for x in got] == list(range(total))
        for path in (tmp_path / "audit").glob("audit-2026-10-24.*.log"):
            assert all("2026-10-24T" in x for x in _lines(path))


def test_each_file_starts_with_a_header_its_day_reads_past(tmp_path: Path) -> None:
    """The header names the format; file_day still takes the first record's
    stamp, and query.parse_line skips the header."""
    from edumatcher.audit.query import parse_line

    path = tmp_path / "audit.log"
    f = AuditFile(path, max_bytes=10_000, tz=STOCKHOLM)
    rec = '[2026-03-29T22:30:00.000+00:00] [order.new] [seq=1] {"id": "o1"}'
    f.write("2026-03-30", [rec])
    f.close()
    header, first = path.read_text(encoding="utf-8").splitlines()
    assert re.fullmatch(r"# edumatcher-audit format=1 pm-audit=\S+ started=\S+", header)
    assert file_day(path, STOCKHOLM) == "2026-03-30"  # 00:30 local, not the header's
    assert parse_line(header) is None
    assert parse_line(first) is not None


class TestDurability:
    """How much of what was received survives a crash, and what the trail says
    about the recorder itself (A6)."""

    def test_fsync_runs_on_the_first_flush_then_at_most_once_per_interval(
        self, tmp_path: Path
    ) -> None:
        clock = [100.0]
        f = AuditFile(
            tmp_path / "audit.log",
            1 << 20,
            timezone.utc,
            fsync_interval=1.0,
            clock=lambda: clock[0],
        )
        with patch("edumatcher.audit.writer.os.fsync") as fsync:
            f.write("2026-10-24", ["a"])
            f.write("2026-10-24", ["b"])
            assert fsync.call_count == 1
            clock[0] += 1.5
            f.write("2026-10-24", ["c"])
            assert fsync.call_count == 2

    def test_a_quiet_tail_is_synced_once_due_without_another_write(
        self, tmp_path: Path
    ) -> None:
        """Synced only on a write, the last lines before a quiet spell (the
        close of the day before an idle night) stayed in the page cache until
        the next write, however long that took (review 2026-11-05)."""
        clock = [100.0]
        f = AuditFile(
            tmp_path / "audit.log",
            1 << 20,
            timezone.utc,
            fsync_interval=1.0,
            clock=lambda: clock[0],
        )
        with patch("edumatcher.audit.writer.os.fsync") as fsync:
            f.write("2026-10-24", ["a"])  # synced: the first
            clock[0] += 0.5
            f.write("2026-10-24", ["b"])  # not yet due
            assert not f.sync_due()
            clock[0] += 0.6
            assert f.sync_due()
            f.sync_if_due()
            assert fsync.call_count == 2
            clock[0] += 10
            assert not f.sync_due()  # nothing written since
            f.sync_if_due()
            assert fsync.call_count == 2

    def test_a_zero_interval_syncs_every_flush(self, tmp_path: Path) -> None:
        f = AuditFile(tmp_path / "audit.log", 1 << 20, timezone.utc, fsync_interval=0)
        with patch("edumatcher.audit.writer.os.fsync") as fsync:
            for line in ("a", "b", "c"):
                f.write("2026-10-24", [line])
            assert fsync.call_count == 3

    def test_a_started_recorder_marks_where_it_began_once(self, tmp_path: Path) -> None:
        f = AuditFile(
            tmp_path / "audit.log", 1 << 20, timezone.utc, announce_start=True
        )
        f.write("2026-10-24", ["a"])
        f.write("2026-10-24", ["b"])
        f.close()
        lines = (tmp_path / "audit.log").read_text().splitlines()
        assert lines[0].startswith("# edumatcher-audit format=1")
        assert lines[1].startswith("# edumatcher-audit recorder-start ")
        assert lines[2:] == ["a", "b"]

    def test_a_restart_into_a_non_empty_file_is_marked_too(
        self, tmp_path: Path
    ) -> None:
        first = AuditFile(tmp_path / "audit.log", 1 << 20, timezone.utc)
        first.write("2026-10-24", ["a"])
        first.close()
        second = AuditFile(
            tmp_path / "audit.log", 1 << 20, timezone.utc, announce_start=True
        )
        second.write("2026-10-24", ["b"])
        second.close()
        lines = (tmp_path / "audit.log").read_text().splitlines()
        assert lines[-2].startswith("# edumatcher-audit recorder-start ")
        assert lines[-1] == "b"

    def test_a_plain_file_writes_no_marker(self, tmp_path: Path) -> None:
        f = AuditFile(tmp_path / "audit.log", 1 << 20, timezone.utc)
        f.write("2026-10-24", ["a"])
        f.close()
        assert _lines(tmp_path / "audit.log") == ["a"]


def test_the_receive_loop_syncs_a_quiet_tail(tmp_path: Path) -> None:
    """With no line arriving, the loop's poll timeout is the only thing that
    runs: it must sync what an earlier flush left unsynced."""
    clock = [datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)]
    proc = _process(tmp_path, timezone.utc, clock)
    mono = [100.0]
    proc._file._clock = lambda: mono[0]
    _record(proc, 1)
    proc._flush_buffer()  # the first write: synced
    mono[0] += 0.5
    _record(proc, 2)
    proc._flush_buffer()  # not yet due

    polls = [0]

    def idle_poll(timeout: int) -> list[Any]:
        polls[0] += 1
        mono[0] += timeout / 1000
        if polls[0] == 5:
            proc._running = False
        return []

    with (
        patch("edumatcher.audit.main.zmq.Poller") as poller,
        patch("edumatcher.audit.writer.os.fsync") as fsync,
    ):
        poller.return_value.poll.side_effect = idle_poll
        proc._eod_seen = True  # nothing to drain after the loop
        proc._running = True
        proc._receive()
    assert fsync.call_count >= 1
    proc._file.close()

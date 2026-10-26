"""Day-closing audit writer: AuditFile and its use by AuditProcess (Z2)."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from edumatcher.audit.main import AuditProcess
from edumatcher.audit.query import discover_log_files
from edumatcher.audit.writer import AuditFile

STOCKHOLM = ZoneInfo("Europe/Stockholm")


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


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
        log.write_text("[2026-10-24T23:30:00.000+00:00] [x] {}\n")  # 01:30 on the 25th
        f = AuditFile(log, 1 << 20, STOCKHOLM)
        f.write("2026-10-25", ["next"])
        f.close()
        assert discover_log_files(log) == [log]
        assert _lines(log)[-1] == "next"


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

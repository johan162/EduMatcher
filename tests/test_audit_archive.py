"""Daily zstd archives: ``archive_day`` and ``pm-audit-cli archive`` (Z3)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from compression import zstd

from edumatcher.audit.archive import (
    ArchiveBusy,
    ArchiveError,
    ArchiveResult,
    apply_retention,
    archive_day,
    archive_lock,
    pending_days,
)
from edumatcher.audit.cli import main as cli_main
from edumatcher.audit.query import discover_log_files, iter_entries


class _Usage(NamedTuple):
    total: int
    used: int
    free: int


DAY = "2026-10-24"
TODAY = "2026-10-25"
STEPS = ["compressed", "verified", "renamed", "deleted"]


def _line(n: int, day: str = DAY) -> str:
    return f'[{day}T10:00:{n % 60:02d}.000+00:00] [order.new] {{"id": "{n}"}}\n'


def _make_parts(audit_dir: Path, day: str = DAY, parts: int = 3) -> bytes:
    """Write ``parts`` closed parts; return their concatenation."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    whole = b""
    n = 0
    for i in range(1, parts + 1):
        text = "".join(_line(n + k, day) for k in range(50))
        n += 50
        (audit_dir / f"audit-{day}.{i}.log").write_text(text)
        whole += text.encode()
    return whole


def _archive_bytes(audit_dir: Path, day: str = DAY) -> bytes:
    with zstd.open(audit_dir / f"audit-{day}.log.zst", "rb") as fh:
        return fh.read()


def _names(audit_dir: Path) -> list[str]:
    return sorted(p.name for p in audit_dir.iterdir() if p.name != ".archive.lock")


class TestArchiveDay:
    def test_round_trips_byte_for_byte_and_removes_the_parts(
        self, tmp_path: Path
    ) -> None:
        whole = _make_parts(tmp_path)
        result = archive_day(tmp_path, DAY, today=TODAY)
        assert result is not None and result.parts == 3
        assert result.bytes_in == len(whole)
        assert _archive_bytes(tmp_path) == whole
        assert _names(tmp_path) == [f"audit-{DAY}.log.zst"]

    def test_refuses_today_and_the_future(self, tmp_path: Path) -> None:
        _make_parts(tmp_path, TODAY)
        with pytest.raises(ArchiveError, match="not closed yet"):
            archive_day(tmp_path, TODAY, today=TODAY)
        assert len(_names(tmp_path)) == 3

    def test_a_day_without_parts_is_a_no_op(self, tmp_path: Path) -> None:
        assert archive_day(tmp_path, DAY, today=TODAY) is None

    def test_parts_are_concatenated_in_number_order(self, tmp_path: Path) -> None:
        tmp_path.mkdir(exist_ok=True)
        for n in (10, 2, 1):  # 10 sorts before 2 as text
            (tmp_path / f"audit-{DAY}.{n}.log").write_text(f"part {n}\n")
        archive_day(tmp_path, DAY, today=TODAY)
        assert _archive_bytes(tmp_path) == b"part 1\npart 2\npart 10\n"

    @pytest.mark.parametrize("crash_after", STEPS)
    def test_a_crash_after_any_step_recovers_on_rerun(
        self, tmp_path: Path, crash_after: str
    ) -> None:
        whole = _make_parts(tmp_path)

        def crash(step: str) -> None:
            if step == crash_after:
                raise KeyboardInterrupt(step)

        with pytest.raises(KeyboardInterrupt):
            archive_day(tmp_path, DAY, today=TODAY, on_step=crash)
        # Never neither: either the parts or the archive survive the crash.
        names = _names(tmp_path)
        assert any(n.endswith(".zst") or n.endswith(".log") for n in names)

        archive_day(tmp_path, DAY, today=TODAY)

        assert _names(tmp_path) == [f"audit-{DAY}.log.zst"]
        assert _archive_bytes(tmp_path) == whole

    def test_a_corrupt_leftover_part_file_is_redone(self, tmp_path: Path) -> None:
        whole = _make_parts(tmp_path)
        (tmp_path / f"audit-{DAY}.log.zst.part").write_bytes(b"garbage")
        archive_day(tmp_path, DAY, today=TODAY)
        assert _archive_bytes(tmp_path) == whole
        assert _names(tmp_path) == [f"audit-{DAY}.log.zst"]

    def test_a_crash_midway_through_deleting_the_parts_loses_nothing(
        self, tmp_path: Path
    ) -> None:
        whole = _make_parts(tmp_path)

        def crash(step: str) -> None:
            if step == "renamed":
                raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            archive_day(tmp_path, DAY, today=TODAY, on_step=crash)
        (tmp_path / f"audit-{DAY}.1.log").unlink()  # the first part was deleted

        result = archive_day(tmp_path, DAY, today=TODAY)

        assert result is not None and result.parts == 2
        assert _names(tmp_path) == [f"audit-{DAY}.log.zst"]
        assert _archive_bytes(tmp_path) == whole

    def test_parts_written_after_the_archive_are_appended_to_it(
        self, tmp_path: Path
    ) -> None:
        whole = _make_parts(tmp_path)
        archive_day(tmp_path, DAY, today=TODAY)
        late = _line(7).encode()
        (tmp_path / f"audit-{DAY}.1.log").write_bytes(late)  # the day reopened

        archive_day(tmp_path, DAY, today=TODAY)

        assert _names(tmp_path) == [f"audit-{DAY}.log.zst"]
        assert _archive_bytes(tmp_path) == whole + late

    def test_an_archive_that_does_not_hold_the_parts_is_kept_not_remade(
        self, tmp_path: Path
    ) -> None:
        whole = _make_parts(tmp_path)
        (tmp_path / f"audit-{DAY}.log.zst").write_bytes(zstd.compress(b"earlier\n"))
        archive_day(tmp_path, DAY, today=TODAY)
        assert _archive_bytes(tmp_path) == b"earlier\n" + whole

    def test_an_unreadable_archive_next_to_parts_is_refused_and_both_are_kept(
        self, tmp_path: Path
    ) -> None:
        whole = _make_parts(tmp_path)
        broken = zstd.compress(whole)[:20]
        (tmp_path / f"audit-{DAY}.log.zst").write_bytes(broken)
        with pytest.raises(ArchiveError, match="unreadable"):
            archive_day(tmp_path, DAY, today=TODAY)
        assert (tmp_path / f"audit-{DAY}.log.zst").read_bytes() == broken
        assert len(_names(tmp_path)) == 4

    def test_a_write_error_while_compressing_drops_the_temp_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_parts(tmp_path)

        def no_space(_fd: int) -> None:
            raise OSError(28, "No space left on device")

        monkeypatch.setattr("edumatcher.audit.archive.os.fsync", no_space)
        with pytest.raises(OSError):
            archive_day(tmp_path, DAY, today=TODAY)
        assert _names(tmp_path) == [f"audit-{DAY}.{n}.log" for n in (1, 2, 3)]

    def test_low_free_space_refuses_and_keeps_the_parts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_parts(tmp_path)
        monkeypatch.setattr(shutil, "disk_usage", lambda _p: _Usage(100, 100, 1))
        with pytest.raises(ArchiveError, match="free space"):
            archive_day(tmp_path, DAY, today=TODAY)
        assert len(_names(tmp_path)) == 3

    def test_failed_verification_keeps_parts_and_drops_the_temp_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_parts(tmp_path)
        import edumatcher.audit.archive as mod

        monkeypatch.setattr(mod, "_digest_archive", lambda _p: ("bad", 0))
        with pytest.raises(ArchiveError, match="verification"):
            archive_day(tmp_path, DAY, today=TODAY)
        assert _names(tmp_path) == [f"audit-{DAY}.{n}.log" for n in (1, 2, 3)]

    def test_the_live_trail_never_repeats_a_line_across_the_crash_window(
        self, tmp_path: Path
    ) -> None:
        """Archive renamed but parts not yet deleted: still one copy to read."""
        _make_parts(tmp_path / "audit")
        log = tmp_path / "audit.log"
        log.write_text(_line(999, TODAY))

        def crash(step: str) -> None:
            if step == "renamed":
                raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            archive_day(tmp_path / "audit", DAY, today=TODAY, on_step=crash)
        assert discover_log_files(log) == [log]
        assert len(list(iter_entries(discover_log_files(log)))) == 1


class TestLockAndSelection:
    def test_a_held_lock_is_reported_as_busy(self, tmp_path: Path) -> None:
        with archive_lock(tmp_path):
            with pytest.raises(ArchiveBusy):
                with archive_lock(tmp_path):
                    pass
        with archive_lock(tmp_path):  # released again
            pass

    def test_pending_days_are_closed_days_with_parts_oldest_first(
        self, tmp_path: Path
    ) -> None:
        _make_parts(tmp_path, "2026-10-23", 1)
        _make_parts(tmp_path, "2026-10-22", 2)
        _make_parts(tmp_path, TODAY, 1)
        (tmp_path / "audit-2026-10-21.log.zst").write_bytes(b"")
        assert pending_days(tmp_path, TODAY) == ["2026-10-22", "2026-10-23"]

    def test_retention_removes_old_archives_only(self, tmp_path: Path) -> None:
        for d in ("2026-10-01", "2026-10-20", "2026-10-24"):
            (tmp_path / f"audit-{d}.log.zst").write_bytes(b"")
        (tmp_path / "audit-2026-10-01.1.log").write_text("part\n")
        removed = apply_retention(tmp_path, 7, TODAY)
        assert [p.name for p in removed] == ["audit-2026-10-01.log.zst"]
        assert _names(tmp_path) == [
            "audit-2026-10-01.1.log",
            "audit-2026-10-20.log.zst",
            "audit-2026-10-24.log.zst",
        ]


class TestCli:
    def _run(self, monkeypatch: pytest.MonkeyPatch, root: Path, *argv: str) -> int:
        monkeypatch.setattr(
            "sys.argv", ["pm-audit-cli", "--log-file", str(root / "audit.log"), *argv]
        )
        monkeypatch.setattr("edumatcher.audit.cli.today_in", lambda _tz: TODAY)
        with pytest.raises(SystemExit) as exc:
            cli_main()
        return int(exc.value.code or 0)

    def test_archive_date_replaces_the_parts_with_one_verified_zst(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        whole = _make_parts(tmp_path / "audit")
        assert self._run(monkeypatch, tmp_path, "archive", "--date", DAY) == 0
        assert _archive_bytes(tmp_path / "audit") == whole
        assert _names(tmp_path / "audit") == [f"audit-{DAY}.log.zst"]
        assert f"{DAY}: 3 part(s)" in capsys.readouterr().out

    def test_pending_archives_every_closed_day_and_applies_retention(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        audit = tmp_path / "audit"
        _make_parts(audit, "2026-10-22", 1)
        _make_parts(audit, TODAY, 1)
        (audit / "audit-2026-09-01.log.zst").write_bytes(b"")
        code = self._run(
            monkeypatch, tmp_path, "archive", "--pending", "--keep-days", "30"
        )
        assert code == 0
        assert _names(audit) == [
            "audit-2026-10-22.log.zst",
            f"audit-{TODAY}.1.log",
        ]

    def test_today_is_refused_with_a_non_zero_exit(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _make_parts(tmp_path / "audit", TODAY, 1)
        assert self._run(monkeypatch, tmp_path, "archive", "--date", TODAY) == 1
        assert "not closed yet" in capsys.readouterr().err

    def test_a_day_the_active_log_still_holds_is_not_archived(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """pm-audit was down at midnight: audit.log is still DAY's last part."""
        _make_parts(tmp_path / "audit")
        (tmp_path / "audit.log").write_text(_line(999))
        assert self._run(monkeypatch, tmp_path, "archive", "--pending") == 0
        assert self._run(monkeypatch, tmp_path, "archive", "--date", DAY) == 1
        assert "not closed yet" in capsys.readouterr().err
        assert len(_names(tmp_path / "audit")) == 3

    def test_an_os_error_on_one_day_does_not_stop_the_next(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        audit = tmp_path / "audit"
        _make_parts(audit, "2026-10-22", 1)
        _make_parts(audit, "2026-10-23", 1)
        real = archive_day

        def flaky(audit_dir: Path, day: str, **kw: Any) -> ArchiveResult | None:
            if day == "2026-10-22":
                raise PermissionError(13, "Permission denied")
            return real(audit_dir, day, **kw)

        monkeypatch.setattr("edumatcher.audit.cli.archive_day", flaky)
        assert self._run(monkeypatch, tmp_path, "archive", "--pending") == 1
        assert _names(audit) == ["audit-2026-10-22.1.log", "audit-2026-10-23.log.zst"]

    def test_a_second_run_while_locked_exits_cleanly(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _make_parts(tmp_path / "audit")
        with archive_lock(tmp_path / "audit"):
            code = self._run(monkeypatch, tmp_path, "archive", "--pending")
        assert code == 0
        assert len(_names(tmp_path / "audit")) == 3

    def test_needs_date_or_pending(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        assert self._run(monkeypatch, tmp_path, "archive") == 2

    def test_a_bad_level_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        assert (
            self._run(monkeypatch, tmp_path, "archive", "--pending", "--level", "99")
            == 2
        )

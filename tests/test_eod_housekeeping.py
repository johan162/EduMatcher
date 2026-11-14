"""Housekeeping steps: audit archive safety net, log compression, DB backups."""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from compression import zstd

from edumatcher.audit.archive import archive_lock
from edumatcher.eod import housekeeping
from edumatcher.eod.housekeeping import (
    archive_audit,
    backup_databases,
    compress_logs,
)

NOW = datetime(2026, 7, 2, 18, 0, tzinfo=UTC)


def age(path: Path, hours: float) -> None:
    ts = (NOW - timedelta(hours=hours)).timestamp()
    os.utime(path, (ts, ts))


class TestArchiveAudit:
    def _parts(self, audit: Path) -> None:
        audit.mkdir()
        (audit / "audit-2026-06-30.1.log").write_text("a\nb\n")
        (audit / "audit-2026-07-02.1.log").write_text("c\n")

    def test_archives_closed_days_and_leaves_today(self, tmp_path: Path) -> None:
        audit = tmp_path / "audit"
        self._parts(audit)
        result = archive_audit(audit, today="2026-07-02")
        assert result.status == "ok"
        assert (audit / "audit-2026-06-30.log.zst").is_file()
        assert not (audit / "audit-2026-06-30.1.log").exists()
        assert (audit / "audit-2026-07-02.1.log").exists()
        assert "2026-06-30" in result.message

    def test_nothing_pending(self, tmp_path: Path) -> None:
        result = archive_audit(tmp_path / "audit", today="2026-07-02")
        assert result.status == "ok" and "nothing" in result.message

    def test_a_busy_lock_is_a_warning(self, tmp_path: Path) -> None:
        audit = tmp_path / "audit"
        self._parts(audit)
        with archive_lock(audit):
            result = archive_audit(audit, today="2026-07-02")
        assert result.status == "warn"
        assert (audit / "audit-2026-06-30.1.log").exists()


class TestCompressLogs:
    def test_old_file_is_compressed_and_emptied_in_place(self, tmp_path: Path) -> None:
        logs = tmp_path / "logs"
        logs.mkdir()
        f = logs / "engine.log"
        f.write_text("line 1\nline 2\n")
        age(f, 5)
        result = compress_logs(logs, now=NOW, keep_days=30)
        assert result.status == "ok"
        assert f.exists() and f.stat().st_size == 0  # a writer's fd stays valid
        (z,) = logs.glob("engine.*.log.zst")
        assert z.name == "engine.20260702.log.zst"
        with zstd.open(z, "rb") as fh:
            assert fh.read() == b"line 1\nline 2\n"

    def test_a_recently_written_file_is_left_alone(self, tmp_path: Path) -> None:
        logs = tmp_path / "logs"
        logs.mkdir()
        f = logs / "engine.log"
        f.write_text("x\n")
        age(f, 0.1)
        compress_logs(logs, now=NOW, keep_days=30)
        assert f.read_text() == "x\n" and not list(logs.glob("*.zst"))

    def test_empty_files_are_ignored(self, tmp_path: Path) -> None:
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "e.log").write_text("")
        age(logs / "e.log", 5)
        compress_logs(logs, now=NOW, keep_days=30)
        assert not list(logs.glob("*.zst"))

    def test_a_second_compression_the_same_day_gets_a_new_name(
        self, tmp_path: Path
    ) -> None:
        logs = tmp_path / "logs"
        logs.mkdir()
        for text in ("one\n", "two\n"):
            (logs / "e.log").write_text(text)
            age(logs / "e.log", 5)
            compress_logs(logs, now=NOW, keep_days=30)
        assert sorted(p.name for p in logs.glob("*.zst")) == [
            "e.20260702.1.log.zst",
            "e.20260702.log.zst",
        ]

    def test_a_file_that_grows_meanwhile_is_not_truncated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logs = tmp_path / "logs"
        logs.mkdir()
        f = logs / "e.log"
        f.write_text("old\n")
        age(f, 5)
        real = housekeeping._verified_zstd

        def grow(*args: object, **kw: object) -> None:
            real(*args, **kw)  # type: ignore[arg-type]
            with f.open("a") as fh:
                fh.write("late\n")

        monkeypatch.setattr(housekeeping, "_verified_zstd", grow)
        result = compress_logs(logs, now=NOW, keep_days=30)
        assert result.status == "warn"
        assert f.read_text() == "old\nlate\n"
        assert not list(logs.glob("*.zst*"))

    def test_an_append_just_before_the_truncation_is_kept(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logs = tmp_path / "logs"
        logs.mkdir()
        f = logs / "e.log"
        f.write_text("old\n")
        age(f, 5)
        real_open = Path.open

        def late_writer(self: Path, mode: str = "r", *a: Any, **k: Any) -> Any:
            if self == f and mode == "r+b":
                with real_open(self, "a") as fh:  # after the second stat
                    fh.write("late\n")
            return real_open(self, mode, *a, **k)

        monkeypatch.setattr(Path, "open", late_writer)
        result = compress_logs(logs, now=NOW, keep_days=30)
        monkeypatch.undo()
        assert result.status == "warn"
        assert f.read_text() == "old\nlate\n"
        assert not list(logs.glob("*.zst*"))

    def test_retention_removes_only_old_archives(self, tmp_path: Path) -> None:
        logs = tmp_path / "logs"
        logs.mkdir()
        old, young = logs / "a.log.zst", logs / "b.log.zst"
        for p in (old, young):
            p.write_text("x")
        age(old, 24 * 40)
        age(young, 24 * 2)
        compress_logs(logs, now=NOW, keep_days=30)
        assert not old.exists() and young.exists()

    def test_missing_directory_is_fine(self, tmp_path: Path) -> None:
        assert compress_logs(tmp_path / "none", now=NOW, keep_days=30).status == "ok"


def make_db(path: Path, rows: int = 3) -> None:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(rows)])
    conn.commit()
    conn.close()


class TestBackupDatabases:
    def test_backup_is_compressed_and_restorable(self, tmp_path: Path) -> None:
        db = tmp_path / "clearing.db"
        make_db(db)
        result = backup_databases([db], tmp_path / "backup", "2026-07-01", keep_days=7)
        assert result.status == "ok"
        z = tmp_path / "backup" / "2026-07-01" / "clearing.db.zst"
        restored = tmp_path / "restored.db"
        with zstd.open(z, "rb") as src, restored.open("wb") as dst:
            dst.write(src.read())
        conn = sqlite3.connect(restored)
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 3
        conn.close()
        assert [p.name for p in z.parent.iterdir()] == ["clearing.db.zst"]

    def test_missing_databases_are_skipped_and_named(self, tmp_path: Path) -> None:
        db = tmp_path / "clearing.db"
        make_db(db)
        result = backup_databases(
            [db, tmp_path / "stats.db"], tmp_path / "b", "2026-07-01", keep_days=7
        )
        assert result.status == "ok" and "stats.db" in result.message

    def test_a_failed_backup_keeps_the_previous_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db = tmp_path / "clearing.db"
        make_db(db, rows=3)
        backup_databases([db], tmp_path / "b", "2026-07-01", keep_days=7)
        z = tmp_path / "b" / "2026-07-01" / "clearing.db.zst"
        good = z.read_bytes()
        make_db_more = sqlite3.connect(db)
        make_db_more.execute("INSERT INTO t VALUES (99)")
        make_db_more.commit()
        make_db_more.close()

        def boom(*_a: object, **_k: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(housekeeping, "_verified_zstd", boom)
        result = backup_databases([db], tmp_path / "b", "2026-07-01", keep_days=7)
        assert result.status == "warn" and "clearing.db" in result.message
        assert z.read_bytes() == good
        assert [p.name for p in z.parent.iterdir()] == ["clearing.db.zst"]

    def test_an_unreadable_database_is_a_warning_not_an_exception(
        self, tmp_path: Path
    ) -> None:
        bad = tmp_path / "bad.db"
        bad.write_bytes(b"this is not sqlite" * 100)
        result = backup_databases([bad], tmp_path / "b", "2026-07-01", keep_days=7)
        assert result.status == "warn"

    def test_retention_prunes_old_date_directories_only(self, tmp_path: Path) -> None:
        root = tmp_path / "b"
        for name in ("2026-06-01", "2026-06-28", "notes"):
            (root / name).mkdir(parents=True)
        db = tmp_path / "x.db"
        make_db(db)
        backup_databases([db], root, "2026-07-01", keep_days=7)
        assert sorted(p.name for p in root.iterdir()) == [
            "2026-06-28",
            "2026-07-01",
            "notes",
        ]


class TestBackupCheck:
    def test_the_copy_is_checked_with_quick_check(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db = tmp_path / "clearing.db"
        make_db(db)
        seen: list[str] = []
        real = sqlite3.connect

        def connect(*a: Any, **k: Any) -> sqlite3.Connection:
            conn = real(*a, **k)
            conn.set_trace_callback(seen.append)
            return conn

        monkeypatch.setattr(sqlite3, "connect", connect)
        result = backup_databases([db], tmp_path / "b", "2026-07-01", keep_days=7)
        assert result.status == "ok"
        assert any("quick_check" in s for s in seen)
        assert not any("integrity_check" in s for s in seen)

    def test_a_corrupt_page_is_still_refused(self, tmp_path: Path) -> None:
        db = tmp_path / "clearing.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE t (x TEXT)")
        conn.executemany("INSERT INTO t VALUES (?)", [("x" * 500,)] * 200)
        conn.commit()
        page = conn.execute("PRAGMA page_size").fetchone()[0]
        conn.close()
        raw = bytearray(db.read_bytes())
        raw[page * 3 : page * 3 + 64] = b"\xff" * 64  # a b-tree page header
        db.write_bytes(bytes(raw))
        result = backup_databases([db], tmp_path / "b", "2026-07-01", keep_days=7)
        assert result.status == "warn" and "clearing.db" in result.message
        assert not (tmp_path / "b" / "2026-07-01" / "clearing.db.zst").exists()

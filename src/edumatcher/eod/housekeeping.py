"""The day's housekeeping: audit archive safety net, log compression, DB backups.

Every step returns a :class:`StepResult` and turns the failures it can foresee
(a busy lock, a full disk, an unreadable database) into a ``warn`` result
instead of an exception, so one stuck chore never stops the others and never
withholds the day's statements.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol

from compression import zstd

from edumatcher.audit.archive import (
    ArchiveBusy,
    ArchiveError,
    DEFAULT_LEVEL,
    archive_day,
    archive_lock,
    pending_days,
)

_CHUNK = 1 << 20
_DATE_DIR_LEN = len("YYYY-MM-DD")


class _Readable(Protocol):
    def read(self, size: int = ..., /) -> bytes: ...


@dataclass(frozen=True)
class StepResult:
    step: str
    status: Literal["ok", "warn", "fail"]
    message: str


def _human(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


def _sha(stream: _Readable) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(_CHUNK):
        digest.update(chunk)
    return digest.hexdigest()


def _verified_zstd(source: Path, target: Path, size: int | None = None) -> None:
    """Compress the first ``size`` bytes of ``source`` (all if None) to ``target``.

    ``target`` is written under a ``.part`` name, decompressed again and
    compared with what was read, fsynced and renamed into place; on any failure
    the ``.part`` file is removed and nothing at ``target`` changes.
    """
    part = target.with_name(target.name + ".part")
    part.unlink(missing_ok=True)
    try:
        read_digest, left = hashlib.sha256(), size
        with (
            source.open("rb") as src,
            zstd.open(part, "wb", level=DEFAULT_LEVEL) as dst,
        ):
            while chunk := src.read(_CHUNK if left is None else min(_CHUNK, left)):
                read_digest.update(chunk)
                dst.write(chunk)
                if left is not None:
                    left -= len(chunk)
                    if left == 0:
                        break
        with zstd.open(part, "rb") as check:
            if _sha(check) != read_digest.hexdigest():
                raise OSError(f"verification of {target.name} failed")
        with part.open("rb") as fh:
            os.fsync(fh.fileno())
        part.replace(target)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def archive_audit(audit_dir: Path, today: str) -> StepResult:
    """Archive every closed day that ``pm-audit`` has not got to yet.

    Days before ``today`` only: the day that just closed is archived by
    ``pm-audit`` itself after midnight.
    """
    try:
        with archive_lock(audit_dir):
            done = []
            for day in pending_days(audit_dir, today):
                if archive_day(audit_dir, day, today=today):
                    done.append(day)
    except ArchiveBusy:
        return StepResult("audit", "warn", "another archive run holds the lock")
    except (ArchiveError, OSError) as exc:
        return StepResult("audit", "warn", f"archive failed: {exc}")
    if not done:
        return StepResult("audit", "ok", "nothing pending")
    return StepResult("audit", "ok", f"archived {', '.join(done)}")


def _free_name(directory: Path, stem: str, stamp: str) -> Path:
    candidate = directory / f"{stem}.{stamp}.log.zst"
    counter = 0
    while candidate.exists():
        counter += 1
        candidate = directory / f"{stem}.{stamp}.{counter}.log.zst"
    return candidate


def compress_logs(
    logs_dir: Path,
    *,
    now: datetime,
    keep_days: int,
    min_age: timedelta = timedelta(hours=1),
) -> StepResult:
    """Compress idle failover logs and delete old archives.

    A failover log is held open for appending by the process that writes it, so
    the file is never deleted: its content is compressed to a dated ``.zst`` and
    the file is then truncated in place (the writer's append position follows).
    A file that changes while it is being compressed is left for the next run;
    the size is checked last on the handle that truncates, so only a write in
    the microseconds between that check and the truncation could be lost.
    """
    if not logs_dir.is_dir():
        return StepResult("logs", "ok", "no log directory")
    compressed, skipped, warnings = 0, 0, []
    for path in sorted(logs_dir.glob("*.log")):
        try:
            before = path.stat()
            if before.st_size == 0 or (
                now.timestamp() - before.st_mtime < min_age.total_seconds()
            ):
                continue
            stamp = datetime.fromtimestamp(before.st_mtime, UTC).strftime("%Y%m%d")
            target = _free_name(logs_dir, path.stem, stamp)
            _verified_zstd(path, target, before.st_size)
            after = path.stat()
            changed = (after.st_size, after.st_mtime_ns) != (
                before.st_size,
                before.st_mtime_ns,
            )
            if not changed:
                with path.open("r+b") as fh:
                    # Checked again on the handle that truncates: a line
                    # appended since the stat above would otherwise be lost.
                    changed = os.fstat(fh.fileno()).st_size != before.st_size
                    if not changed:
                        fh.truncate(0)
            if changed:
                target.unlink()
                skipped += 1
                continue
            compressed += 1
        except OSError as exc:
            warnings.append(f"{path.name}: {exc}")
    cutoff = now.timestamp() - keep_days * 86400
    removed = 0
    for old in logs_dir.glob("*.log.zst"):
        try:
            if old.stat().st_mtime < cutoff:
                old.unlink()
                removed += 1
        except OSError as exc:
            warnings.append(f"{old.name}: {exc}")
    message = f"compressed {compressed}, removed {removed} old"
    if skipped:
        message += f", {skipped} changed while compressing"
    if warnings:
        return StepResult("logs", "warn", f"{message}; {'; '.join(warnings)}")
    return StepResult("logs", "warn" if skipped else "ok", message)


def backup_databases(
    databases: Sequence[Path], dest_root: Path, trade_date: str, *, keep_days: int
) -> StepResult:
    """Back up each existing database to ``dest_root/<date>/<name>.zst``.

    SQLite's online backup gives a consistent copy while the writer runs; the
    copy is checked (``quick_check``), compressed and verified before it replaces an
    earlier backup of the same date.  Date directories older than ``keep_days``
    are removed.
    """
    target_dir = dest_root / trade_date
    target_dir.mkdir(parents=True, exist_ok=True)
    done, missing, warnings, size_in, size_out = [], [], [], 0, 0
    for db in databases:
        if not db.exists():
            missing.append(db.name)
            continue
        copy = target_dir / f"{db.name}.copy"
        try:
            _online_copy(db, copy)
            _verified_zstd(copy, target_dir / f"{db.name}.zst")
            size_in += copy.stat().st_size
            size_out += (target_dir / f"{db.name}.zst").stat().st_size
            done.append(db.name)
        except (OSError, sqlite3.Error) as exc:
            warnings.append(f"{db.name}: {exc}")
        finally:
            copy.unlink(missing_ok=True)
    _prune_backups(dest_root, trade_date, keep_days)
    message = f"backed up {', '.join(done) or 'nothing'}"
    if size_in:
        message += f" ({_human(size_in)} -> {_human(size_out)})"
    if missing:
        message += f"; not present: {', '.join(missing)}"
    if warnings:
        return StepResult("backup", "warn", f"{message}; failed: {'; '.join(warnings)}")
    return StepResult("backup", "ok", message)


def _online_copy(source: Path, copy: Path) -> None:
    copy.unlink(missing_ok=True)
    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(copy))
    try:
        src.backup(dst)
        # quick_check verifies every page and record but skips comparing each
        # index with its table: a copy of a healthy database cannot get that
        # wrong, and the full check took most of the backup's time.
        verdict = dst.execute("PRAGMA quick_check").fetchone()[0]
        if verdict != "ok":
            raise sqlite3.DatabaseError(f"quick check: {verdict}")
    finally:
        dst.close()
        src.close()


def _prune_backups(dest_root: Path, trade_date: str, keep_days: int) -> None:
    cutoff = (date.fromisoformat(trade_date) - timedelta(days=keep_days)).isoformat()
    for entry in dest_root.iterdir():
        if entry.is_dir() and len(entry.name) == _DATE_DIR_LEN and entry.name < cutoff:
            try:
                date.fromisoformat(entry.name)
            except ValueError:
                continue
            shutil.rmtree(entry, ignore_errors=True)

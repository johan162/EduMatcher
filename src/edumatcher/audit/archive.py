"""Daily zstd archives of the audit trail (docs-design/EduMatcher-Zstd-Audit.md §3.3).

``archive_day`` turns the closed parts ``audit-D.N.log`` of one day into one
verified ``audit-D.log.zst``.  Every step is crash-safe: a crash leaves the
parts (before the rename) or the archive plus the parts (between the rename
and the delete), never neither, and a re-run finishes the job.  Parts found
beside an archive that are not its tail (the day was reopened after it was
archived) are appended to it, so no archived line is ever dropped.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import shutil
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import BinaryIO, cast

from compression import zstd

DEFAULT_LEVEL = 9
#: Free space required next to the parts, as a share of their total size.
#: zstd on this JSON is ~13:1 (docs-design §Insights, Z3); this leaves a wide margin.
MIN_FREE_SHARE = 0.25
_CHUNK = 1 << 20
_PART_RE = re.compile(r"^audit-(\d{4}-\d{2}-\d{2})\.(\d+)\.log$")
_ARCHIVE_RE = re.compile(r"^audit-(\d{4}-\d{2}-\d{2})\.log\.zst$")
_LOCK_NAME = ".archive.lock"


class ArchiveError(RuntimeError):
    """An archive could not be made; the day's parts are left untouched."""


class ArchiveBusy(ArchiveError):
    """Another archive run holds the lock."""


@dataclass(frozen=True)
class ArchiveResult:
    day: str
    parts: int
    bytes_in: int
    bytes_out: int

    @property
    def ratio(self) -> float:
        return self.bytes_in / self.bytes_out if self.bytes_out else 0.0


_RESULT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}: .*\((\d+(?:\.\d+)?):1\)$")


def format_result(result: ArchiveResult, human: tuple[str, str]) -> str:
    """The one line ``pm-audit-cli archive`` prints per archived day.

    ``human`` is the formatted (input, output) size.  ``parse_ratio`` reads the
    line back, which is how pm-audit learns the ratio from its child process.
    """
    return (
        f"{result.day}: {result.parts} part(s), {human[0]} -> {human[1]} "
        f"({result.ratio:.1f}:1)"
    )


def parse_ratio(line: str) -> float | None:
    """The ratio on a ``format_result`` line, or None for any other line."""
    m = _RESULT_RE.match(line.strip())
    return float(m.group(1)) if m else None


def session_timezone() -> tzinfo:
    """The engine config's ``locale.session_timezone`` (as pm-stats reads it)."""
    from edumatcher.config_artifact import load_compiled_config
    from edumatcher.engine.config_loader import DEFAULT_SESSION_TIMEZONE
    from edumatcher.stats.trading_day import resolve_timezone

    compiled = load_compiled_config()
    name = (
        DEFAULT_SESSION_TIMEZONE
        if compiled is None
        else compiled.engine.locale.session_timezone
    )
    tz = resolve_timezone(name)
    if tz is None:
        raise ValueError(
            f"engine config locale.session_timezone: unknown timezone {name!r}"
        )
    return tz


def today_in(tz: tzinfo) -> str:
    return datetime.now(tz).date().isoformat()


def _parts_of(audit_dir: Path, day: str) -> list[Path]:
    found: list[tuple[int, Path]] = []
    for p in audit_dir.glob(f"audit-{day}.*.log"):
        if m := _PART_RE.match(p.name):
            found.append((int(m.group(2)), p))
    return [p for _, p in sorted(found)]


def _open_source(path: Path) -> BinaryIO:
    """A part, or an existing archive's decompressed content."""
    if path.suffix == ".zst":
        return cast(BinaryIO, zstd.ZstdFile(path, "rb"))
    return path.open("rb")


def _chunks(sources: list[Path], skip: int = 0) -> Iterator[bytes]:
    """The sources read as one stream, without its first ``skip`` bytes."""
    for source in sources:
        with _open_source(source) as fh:
            while chunk := fh.read(_CHUNK):
                if skip >= len(chunk):
                    skip -= len(chunk)
                    continue
                yield chunk[skip:]
                skip = 0


def _digest(sources: list[Path], skip: int = 0) -> tuple[str, int, int]:
    """SHA-256, line count and byte count of the sources read as one stream."""
    sha = hashlib.sha256()
    lines = size = 0
    for chunk in _chunks(sources, skip):
        sha.update(chunk)
        lines += chunk.count(b"\n")
        size += len(chunk)
    return sha.hexdigest(), lines, size


def _digest_archive(archive: Path) -> tuple[str, int]:
    """SHA-256 and line count of a zstd file's content (any file name)."""
    sha = hashlib.sha256()
    lines = 0
    with zstd.ZstdFile(archive, "rb") as fh:
        while chunk := fh.read(_CHUNK):
            sha.update(chunk)
            lines += chunk.count(b"\n")
    return sha.hexdigest(), lines


def _archive_ends_with(archive: Path, parts_size: int, parts_sha: str) -> bool:
    """True when the archive's content ends with the parts' bytes.

    That is a crash during the parts' deletion: the archive was verified
    against every part before any was deleted, so what is left is its tail.
    """
    total = _digest([archive])[2]
    if total < parts_size:
        return False
    return _digest([archive], skip=total - parts_size)[0] == parts_sha


def archive_content_size(archive: Path) -> int | None:
    """Uncompressed size from the frame header, or None if it does not say."""
    with archive.open("rb") as fh:
        head = fh.read(18)
    try:
        return zstd.get_frame_info(head).decompressed_size
    except zstd.ZstdError:
        return None


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def archive_lock(audit_dir: Path) -> Generator[None, None, None]:
    """Exclusive lock so the automatic and a manual run never overlap."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    with (audit_dir / _LOCK_NAME).open("a") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ArchiveBusy("another archive run holds the lock") from exc
        yield


def archive_day(
    audit_dir: Path,
    day: str,
    *,
    today: str,
    level: int = DEFAULT_LEVEL,
    on_step: Callable[[str], None] = lambda _step: None,
) -> ArchiveResult | None:
    """Archive ``day``'s parts; None when there is nothing left to do.

    ``today`` is the first day not yet closed: days before it are archivable.
    ``on_step`` is called after each step ("compressed", "verified",
    "renamed", "deleted"); tests raise from it to simulate a crash there.
    The caller holds ``archive_lock``.
    """
    if day >= today:
        raise ArchiveError(f"{day} is not closed yet: only days before {today} are")
    parts = _parts_of(audit_dir, day)
    archive = audit_dir / f"audit-{day}.log.zst"
    tmp = archive.with_name(archive.name + ".part")
    tmp.unlink(missing_ok=True)
    if not parts:
        return None

    # An archive is never deleted here: once renamed into place it holds
    # verified lines that may exist nowhere else.
    sources = parts
    if archive.exists():
        parts_sha, _, parts_size = _digest(parts)
        try:
            leftover = _archive_ends_with(archive, parts_size, parts_sha)
        except (zstd.ZstdError, EOFError) as exc:
            raise ArchiveError(
                f"{archive.name} is unreadable ({exc}); it and the parts of {day} "
                "are left for an operator"
            ) from exc
        if leftover:
            # A crash while deleting the parts: finish the deletion.
            _delete(parts)
            on_step("deleted")
            return ArchiveResult(day, len(parts), parts_size, archive.stat().st_size)
        # Parts written after the day was archived: the new archive is the
        # old one's content followed by them.
        sources = [archive, *parts]

    sha, lines, size = _digest(sources)

    free = shutil.disk_usage(audit_dir).free
    if free < size * MIN_FREE_SHARE:
        raise ArchiveError(
            f"not enough free space for {day}: {free} bytes free, "
            f"{int(size * MIN_FREE_SHARE)} needed"
        )

    # The pledged size puts the uncompressed size in the frame header, so
    # `archive_content_size` can report the ratio without decompressing.
    compressor = zstd.ZstdCompressor(level=level)
    compressor.set_pledged_input_size(size)
    try:
        with tmp.open("wb") as raw:
            for chunk in _chunks(sources):
                raw.write(compressor.compress(chunk))
            raw.write(compressor.flush(zstd.ZstdCompressor.FLUSH_FRAME))
            raw.flush()
            os.fsync(raw.fileno())
        on_step("compressed")
        if _digest_archive(tmp) != (sha, lines):
            raise ArchiveError(f"verification of the archive for {day} failed")
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    on_step("verified")

    out = tmp.stat().st_size
    os.replace(tmp, archive)
    _fsync_dir(audit_dir)
    on_step("renamed")

    _delete(parts)
    on_step("deleted")
    return ArchiveResult(day, len(parts), size, out)


def _delete(parts: list[Path]) -> None:
    for part in parts:
        part.unlink()


def pending_days(audit_dir: Path, today: str) -> list[str]:
    """Days before ``today`` that still have parts, oldest first."""
    days = {
        m.group(1)
        for p in audit_dir.glob("audit-*.log")
        if (m := _PART_RE.match(p.name))
    }
    return sorted(d for d in days if d < today)


def apply_retention(audit_dir: Path, keep_days: int, today: str) -> list[Path]:
    """Delete archives older than ``keep_days`` days; never touches parts."""
    cutoff = (date.fromisoformat(today) - timedelta(days=keep_days)).isoformat()
    removed: list[Path] = []
    for p in sorted(audit_dir.glob("audit-*.log.zst")):
        if (m := _ARCHIVE_RE.match(p.name)) and m.group(1) < cutoff:
            p.unlink()
            removed.append(p)
    return removed

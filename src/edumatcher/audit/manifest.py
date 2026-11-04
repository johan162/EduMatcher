"""The evidence manifest: a hash chain over the archived days of the audit trail.

``audit/manifest.jsonl`` is append-only.  Each line is one JSON object whose
``prev`` is the SHA-256 of the line before it (``GENESIS`` for the first), so
altering or removing any entry breaks every entry after it.  Two kinds:

``day``      a day's archive as it was made: line count, byte count and the
             SHA-256 of its uncompressed content.  A day reopened after it was
             archived appends a second entry; the latest one is current.
``retired``  retention removed that day's archive; its last hash stays.

What this proves, and what it does not: the chain makes an edit *evident* to
anyone holding an earlier head hash (``pm-audit-cli verify`` prints it).  It
cannot detect that the newest entries were cut off, or that the whole chain
was rewritten, unless the head hash was kept somewhere the writer cannot reach.
Keeping it there is the operator's step.
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from edumatcher.cli_version import package_version

MANIFEST_NAME = "manifest.jsonl"
GENESIS = "0" * 64
KIND_DAY = "day"
KIND_RETIRED = "retired"


@dataclass(frozen=True)
class Problem:
    """One thing ``verify`` found wrong; ``day`` is None for the chain itself."""

    day: str | None
    message: str


def _line_hash(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def _raw_lines(audit_dir: Path) -> list[str]:
    path = audit_dir / MANIFEST_NAME
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def read_entries(audit_dir: Path) -> list[dict[str, Any]]:
    """Every parseable entry, in order (``verify`` reports the rest)."""
    entries: list[dict[str, Any]] = []
    for line in _raw_lines(audit_dir):
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


def head_hash(audit_dir: Path) -> str:
    """Hash of the newest line: the value to keep outside this host."""
    lines = _raw_lines(audit_dir)
    return _line_hash(lines[-1]) if lines else GENESIS


def _append(audit_dir: Path, entry: dict[str, Any]) -> None:
    entry["prev"] = head_hash(audit_dir)
    entry["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entry["pm_audit"] = package_version()
    line = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    audit_dir.mkdir(parents=True, exist_ok=True)
    with (audit_dir / MANIFEST_NAME).open("ab+") as fh:
        # A crash mid-append left a line without its newline: end it, or this
        # entry joins it and both read as one invalid line.  The torn line
        # stays (verify reports it) and is what ``prev`` above chains to.
        if fh.seek(0, os.SEEK_END) > 0:
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b"\n":
                fh.write(b"\n")
        fh.write(line.encode("utf-8") + b"\n")
        fh.flush()
        os.fsync(fh.fileno())
    fd = os.open(audit_dir, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _current(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The newest entry of each day."""
    return {e["day"]: e for e in entries if isinstance(e.get("day"), str)}


def record_day(audit_dir: Path, day: str, sha256: str, lines: int, size: int) -> None:
    """Append ``day``'s archive unless the newest entry already says this."""
    current = _current(read_entries(audit_dir)).get(day)
    if current is not None and (
        current.get("kind") == KIND_DAY and current.get("sha256") == sha256
    ):
        return
    _append(
        audit_dir,
        {
            "kind": KIND_DAY,
            "day": day,
            "sha256": sha256,
            "lines": lines,
            "bytes": size,
        },
    )


def record_retired(audit_dir: Path, day: str) -> None:
    """Note that retention removed ``day``'s archive (before it is unlinked)."""
    current = _current(read_entries(audit_dir)).get(day)
    if current is not None and current.get("kind") == KIND_RETIRED:
        return
    _append(
        audit_dir,
        {
            "kind": KIND_RETIRED,
            "day": day,
            "sha256": current.get("sha256", "") if current is not None else "",
        },
    )


def _archive_days(audit_dir: Path) -> list[str]:
    return sorted(
        p.name[len("audit-") : -len(".log.zst")] for p in _archives(audit_dir)
    )


def _archives(audit_dir: Path) -> list[Path]:
    return sorted(audit_dir.glob("audit-????-??-??.log.zst"))


def verify(audit_dir: Path, day: str | None = None) -> list[Problem]:
    """Check the chain, then each current day against its archive.

    With ``day`` the chain is still checked whole, but only that day's
    archive is read.
    """
    # archive imports this module, hence the late import
    from edumatcher.audit.archive import _digest_archive

    problems: list[Problem] = []
    entries: list[dict[str, Any]] = []
    expected = GENESIS
    for n, line in enumerate(_raw_lines(audit_dir), start=1):
        try:
            entry = json.loads(line)
            if not isinstance(entry, dict):
                raise ValueError("not an object")
        except ValueError:
            problems.append(
                Problem(None, f"manifest line {n} is not valid JSON (torn or edited)")
            )
            expected = _line_hash(line)
            continue
        if entry.get("prev") != expected:
            problems.append(
                Problem(
                    entry.get("day"),
                    f"chain broken at manifest line {n}: an earlier entry was "
                    "changed or removed",
                )
            )
        expected = _line_hash(line)
        entries.append(entry)

    current = _current(entries)
    for d in [day] if day is not None else sorted(current):
        entry = current.get(d)
        archive = audit_dir / f"audit-{d}.log.zst"
        if entry is None:
            if archive.exists():
                problems.append(Problem(d, "archive has no manifest entry"))
            continue
        if entry.get("kind") == KIND_RETIRED:
            continue
        if not archive.exists():
            if not list(audit_dir.glob(f"audit-{d}.*.log")):
                problems.append(Problem(d, "archive is missing (not retired)"))
            continue
        try:
            sha, lines = _digest_archive(archive)
        except Exception as exc:  # unreadable zstd is a finding, not a crash
            problems.append(Problem(d, f"archive is unreadable: {exc}"))
            continue
        if sha != entry.get("sha256") or lines != entry.get("lines"):
            problems.append(
                Problem(d, "archive content differs from the manifest entry")
            )
    if day is None:
        for d in _archive_days(audit_dir):
            if d not in current:
                problems.append(Problem(d, "archive has no manifest entry"))
    return problems

"""The run's audit trail, read as the engine published it.

pm-audit has one SUB socket on the engine's PUB socket, so the files, oldest
first, hold every engine message in publish order -- including the inbound
commands, which the engine republishes before acting on them. A line is::

    [ts] [topic] [seq=N msg=ULID cause=ULID chain=ULID] {json}

Lines are split by hand, not by ``edumatcher.audit.query.parse_line``: a run
holds ~15 M lines, most of them book snapshots a check may skip unparsed.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

from edumatcher.audit.query import discover_log_files, open_log_file


class Line(NamedTuple):
    topic: str
    chain: str
    #: The JSON payload, not yet parsed.
    body: str
    #: When pm-audit wrote the line (ISO, millisecond precision).
    ts: str
    #: The engine's per-topic sequence (None on a line without one).
    seq: int | None = None


def audit_files(data_dir: Path) -> list[Path]:
    """The run's audit files, oldest first (empty when there is none): the
    daily archives, then the live trail. ``discover_log_files`` leaves the
    archives out, but a run that crossed midnight starts in one."""
    archives = sorted((data_dir / "audit").glob("audit-????-??-??.log.zst"))
    return archives + discover_log_files(data_dir / "audit.log")


def lines(files: list[Path]) -> Iterator[Line]:
    for path in files:
        for raw in open_log_file(path):
            if not raw.startswith("["):
                continue
            a = raw.find("] [", 1)
            b = raw.find("] [", a + 3)
            c = raw.find("] ", b + 3)
            if a < 0 or b < 0 or c < 0:
                continue
            meta = raw[b + 3 : c]
            chain = meta[meta.rfind("chain=") + 6 :]
            seq = None
            if meta.startswith("seq="):
                end = meta.find(" ")
                seq = int(meta[4 : end if end > 0 else None])
            yield Line(raw[a + 3 : b], chain, raw[c + 2 :], raw[1:a], seq)

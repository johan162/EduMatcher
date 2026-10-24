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

from edumatcher.audit.query import discover_log_files


class Line(NamedTuple):
    topic: str
    chain: str
    #: The JSON payload, not yet parsed.
    body: str


def audit_files(data_dir: Path) -> list[Path]:
    """The run's audit files, oldest first (empty when there is none)."""
    return discover_log_files(data_dir / "audit.log")


def lines(files: list[Path]) -> Iterator[Line]:
    for path in files:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if not raw.startswith("["):
                    continue
                a = raw.find("] [", 1)
                b = raw.find("] [", a + 3)
                c = raw.find("] ", b + 3)
                if a < 0 or b < 0 or c < 0:
                    continue
                meta = raw[b + 3 : c]
                chain = meta[meta.rfind("chain=") + 6 :]
                yield Line(raw[a + 3 : b], chain, raw[c + 2 :])

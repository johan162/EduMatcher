"""The audit trail's file writer: one active file, closed into day parts.

``audit.log`` holds the lines of one trading day.  It is closed into
``<dir>/audit/audit-YYYY-MM-DD.N.log`` when it reaches ``max_bytes`` or when
a line of a later day arrives; ``N`` is the next free number for that date,
so a part is never renamed again and nothing is ever deleted here.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from datetime import datetime, tzinfo
from pathlib import Path

_PART_NUMBER_RE = re.compile(r"\.(\d+)\.log$")

log = logging.getLogger(__name__)


def file_day(path: Path, tz: tzinfo) -> str | None:
    """Session date of an audit file, from its first line's stamp (None if empty).

    Every line of ``audit.log`` was received on one day, so the first line
    names it.
    """
    try:
        with path.open("rb") as fh:
            first = fh.readline().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return None
    if not first:
        return None
    try:
        stamp = datetime.fromisoformat(first[1 : first.index("]")])
    except ValueError:
        stamp = datetime.fromtimestamp(path.stat().st_mtime, tz)
    return stamp.astimezone(tz).date().isoformat()


class AuditFile:
    """Append-only writer with size and date rollover.

    Not thread-safe: the caller serialises ``write`` and the close calls.
    """

    def __init__(
        self,
        path: Path,
        max_bytes: int,
        tz: tzinfo,
        on_day_closed: Callable[[], None] = lambda: None,
    ) -> None:
        #: Called when a roll closes a day that has ended (not on a size roll).
        self._on_day_closed = on_day_closed
        self._path = path
        self._parts_dir = path.parent / "audit"
        self._max_bytes = max_bytes
        self._tz = tz
        path.parent.mkdir(parents=True, exist_ok=True)
        #: The date every line in ``audit.log`` was received on, or None when
        #: the file is empty.
        self._day = file_day(path, tz)
        self._fh = path.open("ab")
        self._size = path.stat().st_size

    def write(self, day: str, lines: list[str]) -> None:
        """Append ``lines``, all received on ``day``; closes an earlier day first."""
        if self._day is not None and day > self._day and self._try_roll():
            self._on_day_closed()
        if self._day is None:
            self._day = day
        data = ("\n".join(lines) + "\n").encode("utf-8")
        self._fh.write(data)
        self._fh.flush()
        self._size += len(data)
        if self._size >= self._max_bytes:
            self._try_roll()

    def close_days_before(self, today: str) -> None:
        """Close ``audit.log`` if it holds a day before ``today`` (idle midnight)."""
        if self._day is not None and self._day < today and self._try_roll():
            self._on_day_closed()

    def _try_roll(self) -> bool:
        """``roll``, but a failure keeps appending to ``audit.log`` (no line is
        held back or lost); the next write or day check tries again."""
        try:
            self.roll()
        except OSError as exc:
            log.error("cannot close %s as a day part: %s", self._path, exc)
            return False
        return True

    def roll(self) -> None:
        """Close ``audit.log`` as the next part of its day and start a new one.

        On failure ``audit.log`` stays open and unchanged.
        """
        if self._day is None or self._size == 0:
            return
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._parts_dir.mkdir(parents=True, exist_ok=True)
        part = self._parts_dir / f"audit-{self._day}.{self._next_part_number()}.log"
        self._fh.close()
        try:
            os.replace(self._path, part)
        finally:
            self._fh = self._path.open("ab")
        self._size = 0
        self._day = None

    def _next_part_number(self) -> int:
        numbers = [
            int(m.group(1))
            for p in self._parts_dir.glob(f"audit-{self._day}.*.log")
            if (m := _PART_NUMBER_RE.search(p.name))
        ]
        return max(numbers, default=0) + 1

    def close(self) -> None:
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._fh.close()

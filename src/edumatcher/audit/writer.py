"""The audit trail's file writer: one active file, closed into day parts.

``audit.log`` holds the lines of one trading day.  It is closed into
``<dir>/audit/audit-YYYY-MM-DD.N.log`` when it reaches ``max_bytes`` or when
a line of a later day arrives; ``N`` is the next free number for that date,
so a part is never renamed again and nothing is ever deleted here.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from datetime import datetime, tzinfo
from pathlib import Path

_PART_NUMBER_RE = re.compile(r"\.(\d+)\.log$")


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
        self._day = self._day_of_existing_file()
        self._fh = path.open("ab")
        self._size = path.stat().st_size

    def _day_of_existing_file(self) -> str | None:
        """Date of a file left by an earlier run, from its first line's stamp."""
        try:
            with self._path.open("rb") as fh:
                first = fh.readline().decode("utf-8", errors="replace")
        except FileNotFoundError:
            return None
        if not first:
            return None
        try:
            stamp = datetime.fromisoformat(first[1 : first.index("]")])
        except ValueError:
            stamp = datetime.fromtimestamp(self._path.stat().st_mtime, self._tz)
        return stamp.astimezone(self._tz).date().isoformat()

    def write(self, day: str, lines: list[str]) -> None:
        """Append ``lines``, all received on ``day``; closes an earlier day first."""
        if self._day is not None and day > self._day:
            self.roll()
            self._on_day_closed()
        if self._day is None:
            self._day = day
        data = ("\n".join(lines) + "\n").encode("utf-8")
        self._fh.write(data)
        self._fh.flush()
        self._size += len(data)
        if self._size >= self._max_bytes:
            self.roll()

    def close_days_before(self, today: str) -> None:
        """Close ``audit.log`` if it holds a day before ``today`` (idle midnight)."""
        if self._day is not None and self._day < today:
            self.roll()
            self._on_day_closed()

    def roll(self) -> None:
        """Close ``audit.log`` as the next part of its day and start a new one."""
        if self._day is None or self._size == 0:
            return
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._fh.close()
        self._parts_dir.mkdir(parents=True, exist_ok=True)
        part = self._parts_dir / f"audit-{self._day}.{self._next_part_number()}.log"
        os.replace(self._path, part)
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

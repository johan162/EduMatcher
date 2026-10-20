"""The one timestamp format of the ``health`` family."""

from __future__ import annotations

from datetime import datetime, timezone


def iso_utc(epoch_sec: float) -> str:
    """ISO-8601 UTC with milliseconds and a ``Z``, as every health timestamp."""
    return (
        datetime.fromtimestamp(epoch_sec, timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )

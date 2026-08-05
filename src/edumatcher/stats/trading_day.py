"""Trading-date and timestamp-bound helpers for the statistics store.

Two conventions govern every date in ``stats.db``, and they are deliberately
different from each other:

``ts`` columns
    ISO-8601 text, always UTC, always carrying an explicit ``+00:00`` offset.
    These are *instants*.

``date`` columns (``daily_stats``, ``index_daily_stats``)
    The **trading date** — the calendar date in the exchange's session
    timezone that an instant belongs to. This is not the UTC date and not
    the recorder host's local date. An evening session, or any session that
    straddles 00:00 UTC, must roll up into the single trading day the
    participants actually traded, which is the same reasoning behind
    ``clearing/ledger.py::trade_date`` (finding CL-M3).

The session timezone comes from ``pm-stats --timezone`` (default ``UTC``),
matching ``pm-clearing --timezone``. Both processes must be started with the
same value or their daily rollups will not reconcile.

Comparing bounds against stored text
------------------------------------
Date and range filters compare against ``ts`` as *text*, so a bound has to be
rendered in a form that sorts correctly against what is stored. Two stored
precisions exist: ``price_snapshots.ts`` is second-precision
(``2026-06-14T09:00:00+00:00``) while every other ``ts`` is millisecond
precision (``2026-06-14T09:00:00.000+00:00``).

Because ``'+'`` (0x2B) sorts before ``'.'`` (0x2E), a bound rendered *without*
a fractional part sorts at or before every same-second row in either format,
and a bound rendered *with* one sorts after the second-precision form of the
same second — which is arithmetically correct, since ``09:00:00.500`` really
is later than ``09:00:00``. :func:`canonical_ts` therefore emits a fractional
part only when it is non-zero, and that single rule makes text comparison
agree with instant comparison across both stored precisions.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone, tzinfo

__all__ = [
    "canonical_ts",
    "normalise_ts_bound",
    "resolve_timezone",
    "timezone_name",
    "trading_date",
    "trading_day_bounds",
]


def resolve_timezone(name: str) -> tzinfo | None:
    """Resolve an IANA timezone name to a ``tzinfo``, or ``None`` if unknown.

    ``UTC`` maps to the builtin :data:`timezone.utc` so the common case has no
    tzdata dependency; any other name is looked up via :mod:`zoneinfo`.
    """
    if name.upper() == "UTC":
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        return None


def timezone_name(tz: tzinfo) -> str:
    """Return the IANA name of *tz*, as accepted by :func:`resolve_timezone`.

    Used to persist the session timezone in ``stats_meta`` so readers can
    resolve it without being told.
    """
    return str(tz)


def canonical_ts(moment: datetime) -> str:
    """Render an aware datetime as UTC text that sorts against stored ``ts``.

    See the module docstring for why the fractional part is conditional.
    """
    utc = moment.astimezone(timezone.utc)
    if utc.microsecond:
        return utc.isoformat(timespec="milliseconds")
    return utc.isoformat(timespec="seconds")


def trading_date(epoch_sec: float, tz: tzinfo) -> str:
    """Return the ``YYYY-MM-DD`` trading date an instant belongs to."""
    return datetime.fromtimestamp(epoch_sec, tz=tz).strftime("%Y-%m-%d")


def trading_day_bounds(date_str: str, tz: tzinfo) -> tuple[str, str]:
    """Return half-open ``[start, end)`` UTC bounds for one trading date.

    Half-open rather than inclusive so the two ends cannot both match an
    instant at midnight, and so the bounds stay correct on a DST boundary
    where a trading day is 23 or 25 hours long.
    """
    day = datetime.strptime(date_str, "%Y-%m-%d").date()
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return canonical_ts(start), canonical_ts(end)


def normalise_ts_bound(raw: str, tz: tzinfo) -> str:
    """Parse a user-supplied ISO timestamp and render it as a comparable bound.

    Accepts a ``Z`` suffix and any UTC offset, converting both to UTC. A value
    with no offset at all is read as *session-local* time, consistent with
    ``--date`` being a trading date in the session timezone.

    Raises :class:`ValueError` if *raw* is not a parseable ISO timestamp.
    """
    candidate = raw.strip()
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    moment = datetime.fromisoformat(candidate)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz)
    return canonical_ts(moment)

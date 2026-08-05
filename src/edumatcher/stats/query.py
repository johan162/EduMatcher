"""Read-only query helpers for pm-stats-cli and the REST API gateway."""

from __future__ import annotations

import base64
import json
import logging
import sqlite3
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from urllib.parse import quote
from typing import Any

from edumatcher.stats.trading_day import (
    normalise_ts_bound,
    resolve_timezone,
    trading_day_bounds,
)

log = logging.getLogger(__name__)


class InvalidCursorError(ValueError):
    """Raised when an ``after`` cursor is malformed or unparseable."""


def _execute_fetchall(
    conn: sqlite3.Connection, sql: str, params: list[Any] | tuple[Any, ...]
) -> list[sqlite3.Row]:
    log.debug("executing SQL: %s | params=%s", sql, list(params))
    rows = conn.execute(sql, params).fetchall()
    log.debug("SQL returned %d row(s)", len(rows))
    return rows


# ---------------------------------------------------------------------------
# Keyset ("seek") pagination cursors
#
# Every list endpoint orders by a primary sort key (usually ``ts``) plus a
# tiebreaker to make the ordering total: ``seq`` for order_events (already a
# real column), or SQLite's implicit ``rowid`` (insertion order) for the
# other tables, none of which are ``WITHOUT ROWID``. A cursor is an opaque,
# base64-encoded JSON object carrying the last-seen row's sort key and
# tiebreaker; the next page re-queries with ``(sort_key, tiebreaker) >
# (cursor.sort_key, cursor.tiebreaker)`` so pages never skip or repeat rows,
# even if new rows are inserted between fetches (unlike OFFSET).
# ---------------------------------------------------------------------------


def encode_cursor(fields: dict[str, Any]) -> str:
    """Build an opaque pagination cursor from the last row of a page."""
    raw = json.dumps(fields, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> dict[str, Any]:
    """Parse an opaque pagination cursor produced by :func:`encode_cursor`."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        fields = json.loads(raw)
    except Exception as exc:
        raise InvalidCursorError(f"Malformed pagination cursor: {cursor!r}") from exc
    if not isinstance(fields, dict):
        raise InvalidCursorError(f"Malformed pagination cursor: {cursor!r}")
    return fields


def _decode_two_field_cursor(
    cursor: str, primary_key: str, tiebreaker_key: str
) -> tuple[str, int]:
    """Decode a cursor expected to carry exactly *primary_key*/*tiebreaker_key*.

    *primary_key* (a ``ts`` string) and *tiebreaker_key* (a ``seq``/``rowid``
    integer) are type-checked here: an untyped, wrong-typed value would
    otherwise flow straight into a SQL comparison, where SQLite's dynamic
    typing can silently produce a query that "succeeds" but returns the
    wrong (often empty) page instead of a clear error.
    """
    fields = decode_cursor(cursor)
    if primary_key not in fields or tiebreaker_key not in fields:
        raise InvalidCursorError(
            f"Cursor is missing required field(s) {primary_key!r}/{tiebreaker_key!r}"
        )
    primary = fields[primary_key]
    tiebreaker = fields[tiebreaker_key]
    if not isinstance(primary, str):
        raise InvalidCursorError(f"Cursor field {primary_key!r} has an unexpected type")
    if not isinstance(tiebreaker, int) or isinstance(tiebreaker, bool):
        raise InvalidCursorError(
            f"Cursor field {tiebreaker_key!r} has an unexpected type"
        )
    return primary, tiebreaker


def open_readonly_connection(db_path: Path) -> sqlite3.Connection:
    """Open stats SQLite DB in read-only mode.

    ``busy_timeout`` matters even for a reader: with WAL the recorder and this
    connection no longer block each other for normal traffic, but a checkpoint
    still takes a brief exclusive lock, and failing instantly on it would turn
    a routine query into a spurious error.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Statistics DB not found: {db_path}")
    resolved_path = db_path.resolve()
    # The path must be percent-encoded before it is pasted into a URI. A path
    # containing '?' otherwise terminates the path component early: SQLite
    # reads the remainder as query parameters, opens a *different* file, and
    # discards mode=ro — so a read-only helper silently returns a writable
    # handle to the wrong database.
    uri = f"file:{quote(str(resolved_path))}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    log.info("opened read-only stats DB connection path=%s", resolved_path)
    return conn


#: Columns holding integer ticks, by table, for :func:`to_display_prices`.
#: ``vwap`` and ``mid_price`` are in there too: both are derived and stored as
#: floats, but they are floats *of ticks*, so they scale the same way.
TICK_COLUMNS: dict[str, tuple[str, ...]] = {
    "daily": (
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "open_bid",
        "open_ask",
        "close_bid",
        "close_ask",
        "vwap",
        "largest_trade_price",
        # turnover is sum(price_ticks * qty), so dividing by the tick scale
        # yields sum(price_money * qty) — the money notional exactly, not a
        # half-converted number. Converting it keeps the row self-consistent:
        # turnover / volume == vwap in whichever unit system the reader is in.
        "turnover",
    ),
    "trades": ("price",),
    "snapshots": ("mid_price", "best_bid", "best_ask"),
}


def to_display_prices(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """Return *rows* with tick columns converted to display money.

    Storage is exact integer ticks; humans and charts want ``150.25``. The
    conversion happens here, at the read boundary, using each row's own
    ``tick_decimals`` — never a global assumption — which mirrors how
    ``pm-clearing-cli`` presents its integer-minor-unit archive.

    ``turnover`` converts too. It is ``sum(price_ticks * qty)``, so dividing
    by the tick scale gives ``sum(price_money * qty)`` — the money notional
    exactly. Leaving it out would make a row disagree with itself, since
    ``turnover / volume`` must equal ``vwap`` in whichever unit the reader is
    looking at.
    """
    fields = TICK_COLUMNS.get(kind)
    if not fields:
        return rows
    converted: list[dict[str, Any]] = []
    for row in rows:
        tick_decimals = row.get("tick_decimals")
        if tick_decimals is None:
            converted.append(row)
            continue
        scale = float(10 ** int(tick_decimals))
        out = dict(row)
        for field in fields:
            value = out.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out[field] = value / scale
        converted.append(out)
    return converted


def read_meta(conn: sqlite3.Connection, key: str) -> str | None:
    """Return one ``stats_meta`` value, or ``None`` if absent.

    Tolerates the table being missing so a caller can still read a database
    produced before ``stats_meta`` existed instead of failing outright.
    """
    try:
        row = conn.execute(
            "SELECT value FROM stats_meta WHERE key = ?", (key,)
        ).fetchone()
    except sqlite3.Error:
        return None
    return None if row is None else str(row[0])


def resolve_session_timezone(
    conn: sqlite3.Connection, override: str | None = None
) -> tuple[tzinfo, str | None]:
    """Resolve the session timezone for a read.

    Returns ``(tz, warning)``. The timezone recorded in the database wins by
    default, so a reader cannot silently disagree with the recorder about
    which trading day a ``--date`` refers to. An explicit *override* is
    honoured but produces a warning when it contradicts the file — that
    combination is almost always a mistake, and its symptom (too few rows, or
    none) looks identical to there being no data.

    Raises :class:`ValueError` if *override* is not a known timezone.
    """
    recorded = read_meta(conn, "session_timezone")
    if override is not None:
        chosen = resolve_timezone(override)
        if chosen is None:
            raise ValueError(f"Unknown timezone: {override}")
        if recorded is not None and recorded != override:
            return chosen, (
                f"--timezone {override} differs from the session timezone this "
                f"database was recorded with ({recorded}); --date will resolve "
                f"to a different trading day than pm-stats used"
            )
        return chosen, None
    if recorded is None:
        return timezone.utc, None
    resolved = resolve_timezone(recorded)
    if resolved is None:
        return timezone.utc, (
            f"database records an unknown session timezone {recorded!r}; "
            f"falling back to UTC"
        )
    return resolved, None


def validate_date(raw: str) -> None:
    """Validate a trading date, requiring the exact stored ``YYYY-MM-DD`` form.

    ``strptime`` alone would accept ``2026-6-4``, which then never equals the
    zero-padded text in ``daily_stats.date`` — the query would succeed and
    return nothing rather than reporting the malformed input.
    """
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"Invalid date format: {raw} (expected YYYY-MM-DD)") from exc
    if parsed.strftime("%Y-%m-%d") != raw:
        raise ValueError(f"Invalid date format: {raw} (expected YYYY-MM-DD)")


def validate_iso_ts(raw: str) -> None:
    """Validate an ISO timestamp bound using the same parser the queries use."""
    try:
        normalise_ts_bound(raw, timezone.utc)
    except ValueError as exc:
        raise ValueError(
            f"Invalid timestamp format: {raw} (expected ISO timestamp)"
        ) from exc


def _apply_time_filters(
    sql: str,
    params: list[Any],
    *,
    date_value: str | None,
    from_ts: str | None,
    to_ts: str | None,
    tz: tzinfo,
) -> str:
    """Append trading-date and ISO-bound filters to *sql*, extending *params*.

    ``date_value`` is a trading date, so it resolves to the half-open UTC
    instant range that date covers in the session timezone — not to
    ``substr(ts, 1, 10)``, which is a *UTC* date and disagrees with
    ``daily_stats.date`` for any session timezone other than UTC. The range
    form is also index-friendly, which ``substr`` was not.
    """
    if date_value is not None:
        day_start, day_end = trading_day_bounds(date_value, tz)
        sql += " AND ts >= ? AND ts < ?"
        params.extend([day_start, day_end])
    if from_ts is not None:
        sql += " AND ts >= ?"
        params.append(normalise_ts_bound(from_ts, tz))
    if to_ts is not None:
        sql += " AND ts <= ?"
        params.append(normalise_ts_bound(to_ts, tz))
    return sql


def query_instruments(
    conn: sqlite3.Connection, *, symbol: str | None = None
) -> list[dict[str, Any]]:
    """Return instrument reference data — tick scale per symbol.

    ``currency`` is always NULL: EduMatcher has no currency model. The column
    is reserved so a consumer can see the field is absent rather than assume
    one.
    """
    sql = (
        "SELECT symbol, tick_decimals, tick_size, currency, source, updated_ts "
        "FROM instruments"
    )
    params: list[Any] = []
    if symbol is not None:
        sql += " WHERE symbol = ?"
        params.append(symbol)
    sql += " ORDER BY symbol ASC"
    rows = _execute_fetchall(conn, sql, params)
    return [dict(row) for row in rows]


def query_feed_gaps(
    conn: sqlite3.Connection,
    *,
    date_value: str | None,
    from_ts: str | None,
    to_ts: str | None,
    limit: int,
    tz: tzinfo,
) -> list[dict[str, Any]]:
    """Return recorded feed gaps, newest last.

    An empty result means no gap was *detected*, which is a weaker statement
    than "nothing was lost" — see the completeness discussion in the user
    guide for what detection does and does not cover.
    """
    sql = (
        "SELECT seq, ts, stream, expected_id, received_id, missing_count "
        "FROM feed_gaps WHERE 1=1"
    )
    params: list[Any] = []
    sql = _apply_time_filters(
        sql, params, date_value=date_value, from_ts=from_ts, to_ts=to_ts, tz=tz
    )
    sql += " ORDER BY ts ASC, seq ASC LIMIT ?"
    params.append(limit)
    rows = _execute_fetchall(conn, sql, params)
    return [dict(row) for row in rows]


def latest_daily_date(conn: sqlite3.Connection) -> str | None:
    rows = _execute_fetchall(conn, "SELECT MAX(date) AS d FROM daily_stats", [])
    row = rows[0] if rows else None
    if row is None:
        return None
    value = row["d"]
    return str(value) if value is not None else None


def query_daily(
    conn: sqlite3.Connection,
    *,
    date_value: str | None,
    symbol: str | None,
    limit: int,
    after: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return up to *limit* daily rows plus a next-page cursor (or ``None``).

    Two shapes, chosen by whether a range was asked for:

    **Single date** (``from_date``/``to_date`` both omitted) — the historical
    behaviour, unchanged. ``(date, symbol)`` is the table's primary key, so
    within the one resolved date ``symbol`` alone is a unique, sortable
    tiebreaker. When the caller omits ``date``, the *first* page resolves and
    pins the latest available date into its ``next_cursor``; subsequent pages
    reuse that pinned date (rather than re-resolving "latest" each time) so a
    day rollover mid-pagination can't silently switch the result set out from
    under a caller partway through walking it. An explicit ``date`` always
    takes precedence over any pinned cursor date.

    **Date range** (either bound given) — rows across every date in the range,
    oldest first, which is what a multi-day chart needs and what no amount of
    single-date querying could produce without one request per calendar day.
    Ordering and the keyset both widen to ``(date, symbol)``. An explicit
    ``date`` still wins if somebody passes both.
    """
    ranged = date_value is None and (from_date is not None or to_date is not None)

    cursor_symbol: str | None = None
    cursor_date: str | None = None
    if after is not None:
        fields = decode_cursor(after)
        if "symbol" not in fields:
            raise InvalidCursorError("Cursor is missing required field 'symbol'")
        if not isinstance(fields["symbol"], str):
            raise InvalidCursorError("Cursor field 'symbol' has an unexpected type")
        cursor_symbol = fields["symbol"]
        raw_cursor_date = fields.get("date")
        if raw_cursor_date is not None:
            if not isinstance(raw_cursor_date, str):
                raise InvalidCursorError("Cursor field 'date' has an unexpected type")
            cursor_date = raw_cursor_date

    if ranged:
        return _query_daily_range(
            conn,
            symbol=symbol,
            limit=limit,
            from_date=from_date,
            to_date=to_date,
            cursor_date=cursor_date,
            cursor_symbol=cursor_symbol,
        )

    selected_date = date_value or cursor_date or latest_daily_date(conn)
    if selected_date is None:
        return [], None

    sql = (
        "SELECT date, symbol, open_price, high_price, low_price, close_price, "
        "open_bid, open_ask, close_bid, close_ask, volume, trade_count, "
        "turnover, vwap, largest_trade_qty, largest_trade_price, tick_decimals "
        "FROM daily_stats WHERE date = ?"
    )
    params: list[Any] = [selected_date]
    if symbol is not None:
        sql += " AND symbol = ?"
        params.append(symbol)
    if cursor_symbol is not None:
        sql += " AND symbol > ?"
        params.append(cursor_symbol)

    # date is pinned by WHERE date = ?, so symbol alone orders the page.
    sql += " ORDER BY symbol ASC LIMIT ?"
    params.append(limit)

    rows = _execute_fetchall(conn, sql, params)
    results = [dict(row) for row in rows]
    next_cursor = None
    if len(results) == limit:
        next_cursor = encode_cursor(
            {"symbol": results[-1]["symbol"], "date": selected_date}
        )
    return results, next_cursor


_DAILY_COLUMNS = (
    "SELECT date, symbol, open_price, high_price, low_price, close_price, "
    "open_bid, open_ask, close_bid, close_ask, volume, trade_count, "
    "turnover, vwap, largest_trade_qty, largest_trade_price, tick_decimals "
    "FROM daily_stats"
)


def _query_daily_range(
    conn: sqlite3.Connection,
    *,
    symbol: str | None,
    limit: int,
    from_date: str | None,
    to_date: str | None,
    cursor_date: str | None,
    cursor_symbol: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Daily rows spanning several dates, oldest first.

    Both bounds are inclusive and either may be omitted for an open-ended
    range. Ordering is ascending so a chart can consume pages in the order it
    plots them; the keyset is ``(date, symbol)`` because ``symbol`` alone is
    only unique *within* a date.
    """
    sql = f"{_DAILY_COLUMNS} WHERE 1=1"
    params: list[Any] = []

    if symbol is not None:
        sql += " AND symbol = ?"
        params.append(symbol)
    if from_date is not None:
        sql += " AND date >= ?"
        params.append(from_date)
    if to_date is not None:
        sql += " AND date <= ?"
        params.append(to_date)
    if cursor_date is not None and cursor_symbol is not None:
        sql += " AND (date > ? OR (date = ? AND symbol > ?))"
        params.extend([cursor_date, cursor_date, cursor_symbol])

    sql += " ORDER BY date ASC, symbol ASC LIMIT ?"
    params.append(limit)

    rows = _execute_fetchall(conn, sql, params)
    results = [dict(row) for row in rows]
    next_cursor = None
    if len(results) == limit:
        last = results[-1]
        next_cursor = encode_cursor({"date": last["date"], "symbol": last["symbol"]})
    return results, next_cursor


def query_price_snapshots(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    date_value: str | None,
    from_ts: str | None,
    to_ts: str | None,
    limit: int,
    tz: tzinfo,
    after: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return up to *limit* price snapshots plus a next-page cursor.

    ``price_snapshots``' primary key is ``(ts, symbol)``, but multiple
    symbols can share a ``ts`` — since this query is already scoped to one
    ``symbol``, ``rowid`` (insertion order) still serves as the tiebreaker
    for any same-``ts`` rows within that single symbol.
    """
    sql = (
        "SELECT rowid AS _rowid, ts, symbol, mid_price, best_bid, best_ask, "
        "pct_change, tick_decimals FROM price_snapshots WHERE symbol = ?"
    )
    params: list[Any] = [symbol]

    sql = _apply_time_filters(
        sql, params, date_value=date_value, from_ts=from_ts, to_ts=to_ts, tz=tz
    )
    if after is not None:
        after_ts, after_rowid = _decode_two_field_cursor(after, "ts", "rowid")
        sql += " AND (ts > ? OR (ts = ? AND rowid > ?))"
        params.extend([after_ts, after_ts, after_rowid])

    sql += " ORDER BY ts ASC, rowid ASC LIMIT ?"
    params.append(limit)

    rows = _execute_fetchall(conn, sql, params)
    results = [dict(row) for row in rows]
    next_cursor = None
    if len(results) == limit:
        last = results[-1]
        next_cursor = encode_cursor({"ts": last["ts"], "rowid": last["_rowid"]})
    for result in results:
        del result["_rowid"]
    return results, next_cursor


def query_trades(
    conn: sqlite3.Connection,
    *,
    symbol: str | None,
    date_value: str | None,
    from_ts: str | None,
    to_ts: str | None,
    limit: int,
    tz: tzinfo,
    after: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return up to *limit* trades plus a next-page cursor (or ``None``).

    ``trade_log``'s primary key is ``trade_id`` alone (not ordered by time),
    so SQLite's implicit ``rowid`` (insertion order) is used as the
    tiebreaker for same-``ts`` rows, exposed as ``_rowid`` in each result
    row and consumed via the opaque ``after`` cursor on the next call.
    """
    sql = (
        "SELECT rowid AS _rowid, ts, trade_id, symbol, price, quantity, "
        "tick_decimals, buy_gateway_id, sell_gateway_id, aggressor_side "
        "FROM trade_log WHERE 1=1"
    )
    params: list[Any] = []

    if symbol is not None:
        sql += " AND symbol = ?"
        params.append(symbol)
    sql = _apply_time_filters(
        sql, params, date_value=date_value, from_ts=from_ts, to_ts=to_ts, tz=tz
    )
    if after is not None:
        after_ts, after_rowid = _decode_two_field_cursor(after, "ts", "rowid")
        sql += " AND (ts > ? OR (ts = ? AND rowid > ?))"
        params.extend([after_ts, after_ts, after_rowid])

    sql += " ORDER BY ts ASC, rowid ASC LIMIT ?"
    params.append(limit)

    rows = _execute_fetchall(conn, sql, params)
    results = [dict(row) for row in rows]
    next_cursor = None
    if len(results) == limit:
        last = results[-1]
        next_cursor = encode_cursor({"ts": last["ts"], "rowid": last["_rowid"]})
    for result in results:
        del result["_rowid"]
    return results, next_cursor


def query_order_events(
    conn: sqlite3.Connection,
    *,
    gateway_id: str,
    symbol: str | None,
    event_type: str | None,
    date_value: str | None,
    from_ts: str | None,
    to_ts: str | None,
    limit: int,
    tz: tzinfo,
    after: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return up to *limit* order events plus a next-page cursor (or ``None``).

    ``order_events.seq`` is an ``AUTOINCREMENT`` primary key — already a
    stable, monotonic tiebreaker for same-``ts`` rows, so no ``rowid``
    aliasing is needed here (``seq`` *is* the rowid).
    """
    sql = "SELECT * FROM order_events WHERE gateway_id = ?"
    params: list[Any] = [gateway_id]
    if symbol is not None:
        sql += " AND symbol = ?"
        params.append(symbol)
    if event_type is not None:
        sql += " AND event_type = ?"
        params.append(event_type)
    sql = _apply_time_filters(
        sql, params, date_value=date_value, from_ts=from_ts, to_ts=to_ts, tz=tz
    )
    if after is not None:
        after_ts, after_seq = _decode_two_field_cursor(after, "ts", "seq")
        sql += " AND (ts > ? OR (ts = ? AND seq > ?))"
        params.extend([after_ts, after_ts, after_seq])
    sql += " ORDER BY ts ASC, seq ASC LIMIT ?"
    params.append(limit)
    rows = _execute_fetchall(conn, sql, params)
    results = [dict(row) for row in rows]
    next_cursor = None
    if len(results) == limit:
        last = results[-1]
        next_cursor = encode_cursor({"ts": last["ts"], "seq": last["seq"]})
    return results, next_cursor


def query_order_lifecycle(
    conn: sqlite3.Connection,
    *,
    gateway_id: str,
    order_id: str,
) -> list[dict[str, Any]]:
    rows = _execute_fetchall(
        conn,
        "SELECT * FROM order_events WHERE gateway_id = ? AND order_id = ? "
        "ORDER BY ts ASC, seq ASC",
        (gateway_id, order_id),
    )
    return [dict(row) for row in rows]


def query_symbols(
    conn: sqlite3.Connection,
    *,
    date_value: str | None,
    tz: tzinfo,
) -> list[dict[str, Any]]:
    """List symbols present in the stats DB, optionally for one trading date.

    All three branches of the UNION resolve *the same* trading date:
    ``daily_stats.date`` stores it directly, while the two ``ts`` tables are
    matched against the UTC instant range that date covers in the session
    timezone. Filtering the ``ts`` tables on ``substr(ts, 1, 10)`` instead
    would mix a UTC date into a union with a trading date and report symbols
    from two different days.
    """
    if date_value is None:
        sql = (
            "SELECT symbol FROM daily_stats "
            "UNION SELECT symbol FROM price_snapshots "
            "UNION SELECT symbol FROM trade_log "
            "ORDER BY symbol ASC"
        )
        params: list[Any] = []
    else:
        day_start, day_end = trading_day_bounds(date_value, tz)
        sql = (
            "SELECT symbol FROM daily_stats WHERE date = ? "
            "UNION SELECT symbol FROM price_snapshots WHERE ts >= ? AND ts < ? "
            "UNION SELECT symbol FROM trade_log WHERE ts >= ? AND ts < ? "
            "ORDER BY symbol ASC"
        )
        params = [date_value, day_start, day_end, day_start, day_end]

    rows = _execute_fetchall(conn, sql, params)
    return [dict(row) for row in rows]


def query_dates(
    conn: sqlite3.Connection,
    *,
    symbol: str | None,
) -> list[dict[str, Any]]:
    sql = "SELECT DISTINCT date FROM daily_stats"
    params: list[Any] = []
    if symbol is not None:
        sql += " WHERE symbol = ?"
        params.append(symbol)
    sql += " ORDER BY date DESC"

    rows = _execute_fetchall(conn, sql, params)
    return [dict(row) for row in rows]


def latest_index_daily_date(conn: sqlite3.Connection) -> str | None:
    rows = _execute_fetchall(conn, "SELECT MAX(date) AS d FROM index_daily_stats", [])
    row = rows[0] if rows else None
    if row is None:
        return None
    value = row["d"]
    return str(value) if value is not None else None


def query_index_daily(
    conn: sqlite3.Connection,
    *,
    date_value: str | None,
    index_id: str | None,
    limit: int,
    after: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return up to *limit* index-daily rows plus a next-page cursor.

    Mirrors :func:`query_daily`, including its date-range mode: pass either
    bound to get rows across dates, oldest first, keyed on
    ``(date, index_id)``. Without a range the single-date behaviour below is
    unchanged.

    ``(date, index_id)`` is the table's primary key, so within the single
    resolved date this query is scoped to, ``index_id`` alone is already a
    unique, sortable tiebreaker — no ``rowid`` needed.

    When the caller omits ``date``, the *first* page resolves and pins the
    latest available date into its ``next_cursor``; subsequent pages reuse
    that pinned date (rather than re-resolving "latest" each time) so a
    day rollover mid-pagination can't silently switch the result set out
    from under a caller partway through walking it. An explicit ``date``
    always takes precedence over any pinned cursor date.
    """
    ranged = date_value is None and (from_date is not None or to_date is not None)

    cursor_index_id: str | None = None
    cursor_date: str | None = None
    if after is not None:
        fields = decode_cursor(after)
        if "index_id" not in fields:
            raise InvalidCursorError("Cursor is missing required field 'index_id'")
        if not isinstance(fields["index_id"], str):
            raise InvalidCursorError("Cursor field 'index_id' has an unexpected type")
        cursor_index_id = fields["index_id"]
        raw_cursor_date = fields.get("date")
        if raw_cursor_date is not None:
            if not isinstance(raw_cursor_date, str):
                raise InvalidCursorError("Cursor field 'date' has an unexpected type")
            cursor_date = raw_cursor_date

    if ranged:
        return _query_index_daily_range(
            conn,
            index_id=index_id,
            limit=limit,
            from_date=from_date,
            to_date=to_date,
            cursor_date=cursor_date,
            cursor_index_id=cursor_index_id,
        )

    selected_date = date_value or cursor_date or latest_index_daily_date(conn)
    if selected_date is None:
        return [], None

    sql = (
        "SELECT date, index_id, open_level, high_level, low_level, close_level, "
        "close_session_state, open_aggregate_cap, close_aggregate_cap, update_count "
        "FROM index_daily_stats WHERE date = ?"
    )
    params: list[Any] = [selected_date]
    if index_id is not None:
        sql += " AND index_id = ?"
        params.append(index_id)
    if cursor_index_id is not None:
        sql += " AND index_id > ?"
        params.append(cursor_index_id)

    # date is pinned by WHERE date = ?, so index_id alone orders the page.
    sql += " ORDER BY index_id ASC LIMIT ?"
    params.append(limit)

    rows = _execute_fetchall(conn, sql, params)
    results = [dict(row) for row in rows]
    next_cursor = None
    if len(results) == limit:
        next_cursor = encode_cursor(
            {"index_id": results[-1]["index_id"], "date": selected_date}
        )
    return results, next_cursor


_INDEX_DAILY_COLUMNS = (
    "SELECT date, index_id, open_level, high_level, low_level, close_level, "
    "close_session_state, open_aggregate_cap, close_aggregate_cap, update_count "
    "FROM index_daily_stats"
)


def _query_index_daily_range(
    conn: sqlite3.Connection,
    *,
    index_id: str | None,
    limit: int,
    from_date: str | None,
    to_date: str | None,
    cursor_date: str | None,
    cursor_index_id: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Index-daily rows spanning several dates, oldest first.

    The index counterpart of :func:`_query_daily_range`; see there for why the
    keyset widens to two columns.
    """
    sql = f"{_INDEX_DAILY_COLUMNS} WHERE 1=1"
    params: list[Any] = []

    if index_id is not None:
        sql += " AND index_id = ?"
        params.append(index_id)
    if from_date is not None:
        sql += " AND date >= ?"
        params.append(from_date)
    if to_date is not None:
        sql += " AND date <= ?"
        params.append(to_date)
    if cursor_date is not None and cursor_index_id is not None:
        sql += " AND (date > ? OR (date = ? AND index_id > ?))"
        params.extend([cursor_date, cursor_date, cursor_index_id])

    sql += " ORDER BY date ASC, index_id ASC LIMIT ?"
    params.append(limit)

    rows = _execute_fetchall(conn, sql, params)
    results = [dict(row) for row in rows]
    next_cursor = None
    if len(results) == limit:
        last = results[-1]
        next_cursor = encode_cursor(
            {"date": last["date"], "index_id": last["index_id"]}
        )
    return results, next_cursor


def query_index_snapshots(
    conn: sqlite3.Connection,
    *,
    index_id: str,
    date_value: str | None,
    from_ts: str | None,
    to_ts: str | None,
    limit: int,
    tz: tzinfo,
    after: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return up to *limit* index snapshots plus a next-page cursor.

    ``index_level_snapshots``' primary key is ``(ts, index_id)``, but
    multiple indexes can share a ``ts`` — since this query is already
    scoped to one ``index_id``, ``rowid`` (insertion order) still serves as
    the tiebreaker for any same-``ts`` rows within that single index.
    """
    sql = (
        "SELECT rowid AS _rowid, ts, index_id, level, aggregate_cap, divisor, "
        "session_state, day_open, day_high, day_low "
        "FROM index_level_snapshots WHERE index_id = ?"
    )
    params: list[Any] = [index_id]

    sql = _apply_time_filters(
        sql, params, date_value=date_value, from_ts=from_ts, to_ts=to_ts, tz=tz
    )
    if after is not None:
        after_ts, after_rowid = _decode_two_field_cursor(after, "ts", "rowid")
        sql += " AND (ts > ? OR (ts = ? AND rowid > ?))"
        params.extend([after_ts, after_ts, after_rowid])

    sql += " ORDER BY ts ASC, rowid ASC LIMIT ?"
    params.append(limit)

    rows = _execute_fetchall(conn, sql, params)
    results = [dict(row) for row in rows]
    next_cursor = None
    if len(results) == limit:
        last = results[-1]
        next_cursor = encode_cursor({"ts": last["ts"], "rowid": last["_rowid"]})
    for result in results:
        del result["_rowid"]
    return results, next_cursor


def query_index_ids(
    conn: sqlite3.Connection,
    *,
    date_value: str | None,
    tz: tzinfo,
) -> list[dict[str, Any]]:
    """List index IDs present in the stats DB, optionally for one trading date.

    Resolves the trading date consistently across both branches of the UNION —
    see :func:`query_symbols` for why.
    """
    if date_value is None:
        sql = (
            "SELECT index_id FROM index_daily_stats "
            "UNION SELECT index_id FROM index_level_snapshots "
            "ORDER BY index_id ASC"
        )
        params: list[Any] = []
    else:
        day_start, day_end = trading_day_bounds(date_value, tz)
        sql = (
            "SELECT index_id FROM index_daily_stats WHERE date = ? "
            "UNION SELECT index_id FROM index_level_snapshots "
            "WHERE ts >= ? AND ts < ? "
            "ORDER BY index_id ASC"
        )
        params = [date_value, day_start, day_end]

    rows = _execute_fetchall(conn, sql, params)
    return [dict(row) for row in rows]

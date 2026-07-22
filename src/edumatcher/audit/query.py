"""Audit log JSONL parser and filter helpers for pm-audit-cli.

Reads audit log files written by ``pm-audit`` in the format::

    [2026-07-08T09:30:00.123+00:00] [trade.executed] {"id": "...", ...}

Files are read as plain text (active log) or decompressed gzip (rotated
backups ending in ``.gz``).  All filtering is applied during streaming so
large log files are never fully loaded into memory.
"""

from __future__ import annotations

import gzip
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, cast

# ---------------------------------------------------------------------------
# Line format
# ---------------------------------------------------------------------------

# [2026-07-08T09:30:00.123+00:00] [trade.executed] {...}
_LINE_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\]\s+\[(?P<topic>[^\]]+)\]\s+(?P<payload>\{.*\})\s*$"
)


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def parse_ts(value: str) -> datetime:
    """Parse a ``YYYY-MM-DD`` or ISO-8601 string to an *aware* UTC datetime."""
    value = value.strip()
    try:
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass
    raise ValueError(
        f"Cannot parse timestamp {value!r}. "
        "Use YYYY-MM-DD or ISO-8601 (e.g. 2026-07-08T09:30:00+00:00)."
    )


def validate_date(value: str) -> None:
    """Raise ``ValueError`` if *value* is not a valid ``YYYY-MM-DD`` string."""
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"Invalid date {value!r}. Expected YYYY-MM-DD.") from exc


def validate_iso_ts(value: str) -> None:
    """Raise ``ValueError`` if *value* is not a parseable timestamp."""
    parse_ts(value)  # raises ValueError on failure


def date_to_range(date_str: str) -> tuple[datetime, datetime]:
    """Return (start_of_day, end_of_day) UTC datetimes for a YYYY-MM-DD string."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return dt, end


# ---------------------------------------------------------------------------
# Log file discovery
# ---------------------------------------------------------------------------


def discover_log_files(log_file: Path, log_dir: Path | None = None) -> list[Path]:
    """Return all relevant log files in chronological order (oldest first).

    The active log comes last; rotated backups (``audit.log.1``,
    ``audit.log.2``, ``audit.log.2.gz``, …) are sorted by numeric suffix.
    """
    files: list[tuple[int, Path]] = []

    search_dir = log_dir if log_dir is not None else log_file.parent
    stem = log_file.name  # e.g. "audit.log"

    if search_dir.is_dir():
        for candidate in search_dir.iterdir():
            name = candidate.name
            # Match "audit.log.1" or "audit.log.2.gz"
            if name.startswith(stem + ".") and name != stem:
                suffix = name[len(stem) + 1 :]
                suffix_clean = (
                    suffix.rstrip(".gz") if suffix.endswith(".gz") else suffix
                )
                try:
                    idx = int(suffix_clean)
                    files.append((idx, candidate))
                except ValueError:
                    pass

    # Sort descending by index (highest = oldest for RotatingFileHandler)
    files.sort(key=lambda t: t[0], reverse=True)
    ordered: list[Path] = [p for _, p in files]

    if log_file.exists():
        ordered.append(log_file)

    return ordered


# ---------------------------------------------------------------------------
# JSONL line iterator
# ---------------------------------------------------------------------------


def _open_file(path: Path) -> Iterator[str]:
    """Yield raw text lines from a plain or gzip-compressed file."""
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            yield from fh
    else:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            yield from fh


def _parse_line(
    raw: str,
) -> tuple[str, str, dict[str, Any]] | None:
    """Return ``(timestamp_str, topic, payload_dict)`` or ``None`` for bad lines."""
    m = _LINE_RE.match(raw.rstrip("\n"))
    if m is None:
        return None
    try:
        payload: dict[str, Any] = json.loads(m.group("payload"))
    except json.JSONDecodeError:
        return None
    return m.group("ts"), m.group("topic"), payload


# ---------------------------------------------------------------------------
# AuditEntry — typed result row
# ---------------------------------------------------------------------------


class AuditEntry:
    """A single parsed audit log line."""

    __slots__ = (
        "timestamp",
        "topic",
        "payload",
        "gateway_id",
        "symbol",
        "order_id",
        "trade_id",
    )

    def __init__(
        self,
        timestamp: str,
        topic: str,
        payload: dict[str, Any],
    ) -> None:
        self.timestamp = timestamp
        self.topic = topic
        self.payload = payload
        self.gateway_id: str | None = self._extract_gateway()
        self.symbol: str | None = payload.get("symbol") or payload.get("s")
        self.order_id: str | None = (
            payload.get("order_id") or payload.get("id")
            if "trade" not in topic
            else None
        )
        self.trade_id: str | None = payload.get("trade_id") or (
            payload.get("id") if "trade" in topic else None
        )

    def _extract_gateway(self) -> str | None:
        p = self.payload
        return (
            p.get("gateway_id") or p.get("buy_gateway_id") or p.get("sell_gateway_id")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "topic": self.topic,
            "gateway": self.gateway_id,
            "symbol": self.symbol,
            "order_id": self.order_id,
            "trade_id": self.trade_id,
            "payload": self.payload,
        }


# ---------------------------------------------------------------------------
# Core streaming iterator with filters
# ---------------------------------------------------------------------------


def iter_entries(
    log_files: list[Path],
    *,
    topic_prefix: str | None = None,
    gateway: str | None = None,
    symbol: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    limit: int | None = None,
) -> Iterator[AuditEntry]:
    """Stream :class:`AuditEntry` objects from *log_files* with optional filters.

    Filtering is applied during iteration so memory usage stays proportional
    to *limit*, not to file size.
    """
    count = 0
    for path in log_files:
        if not path.exists():
            continue
        for raw in _open_file(path):
            parsed = _parse_line(raw)
            if parsed is None:
                continue
            ts_str, topic, payload = parsed

            # Topic prefix filter
            if topic_prefix and not topic.startswith(topic_prefix):
                continue

            # Time range filter — parse only when a range is active
            if from_dt is not None or to_dt is not None:
                try:
                    entry_dt = parse_ts(ts_str)
                except ValueError:
                    continue
                if from_dt is not None and entry_dt < from_dt:
                    continue
                if to_dt is not None and entry_dt > to_dt:
                    continue

            entry = AuditEntry(ts_str, topic, payload)

            # Gateway filter
            if gateway is not None and entry.gateway_id != gateway:
                # Also check buy/sell gateway for trade entries
                p = entry.payload
                if (
                    p.get("buy_gateway_id") != gateway
                    and p.get("sell_gateway_id") != gateway
                ):
                    continue

            # Symbol filter
            if symbol is not None and entry.symbol != symbol:
                continue

            yield entry
            count += 1
            if limit is not None and count >= limit:
                return


# ---------------------------------------------------------------------------
# Command query functions
# ---------------------------------------------------------------------------


def query_events(
    log_files: list[Path],
    *,
    topic: str | None = None,
    gateway: str | None = None,
    symbol: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    date_str: str | None = None,
    limit: int = 100,
    reverse: bool = False,
) -> list[dict[str, Any]]:
    """Return event rows for the ``events`` command."""
    if date_str:
        from_dt, to_dt = date_to_range(date_str)

    entries = list(
        iter_entries(
            log_files,
            topic_prefix=topic,
            gateway=gateway,
            symbol=symbol,
            from_dt=from_dt,
            to_dt=to_dt,
            limit=None if reverse else limit,
        )
    )

    if reverse:
        entries = entries[-limit:]
        entries.reverse()

    rows: list[dict[str, Any]] = []
    for e in entries:
        rows.append(
            {
                "timestamp": e.timestamp,
                "topic": e.topic,
                "gateway": e.gateway_id,
                "symbol": e.symbol,
                "order_id": e.order_id,
                "summary": _summarise(e),
            }
        )
    return rows


def _summarise(entry: AuditEntry) -> str:
    """Return a short human-readable summary of an audit entry."""
    p = entry.payload
    t = entry.topic
    if t == "trade.executed":
        return f"{p.get('symbol', '')} {p.get('quantity', '')}@{p.get('price', '')}"
    if t.startswith("order.fill"):
        fq = p.get("filled_qty", p.get("quantity", ""))
        fp = p.get("fill_price", p.get("price", ""))
        return f"FILL {fq}@{fp}"
    if t.startswith("order.ack"):
        return (
            f"ACK {p.get('status', '')} {p.get('order_type', '')} {p.get('side', '')}"
        )
    if t.startswith("order.new"):
        return f"{p.get('order_type', '')} {p.get('side', '')} {p.get('quantity', '')}@{p.get('price', '')}"
    if t.startswith("order.cancel"):
        return f"CANCEL {p.get('status', '')}"
    if t.startswith("session."):
        return str(p.get("state", p.get("phase", "")))
    return ""


def query_orders(
    log_files: list[Path],
    *,
    order_ids: list[str] | None = None,
    gateway: str | None = None,
    symbol: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    date_str: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return order event rows for the ``orders`` command."""
    if date_str:
        from_dt, to_dt = date_to_range(date_str)

    ids_set = set(order_ids) if order_ids else None

    rows: list[dict[str, Any]] = []
    for entry in iter_entries(
        log_files,
        topic_prefix="order.",
        gateway=gateway,
        symbol=symbol,
        from_dt=from_dt,
        to_dt=to_dt,
        limit=None,
    ):
        p = entry.payload
        oid = p.get("order_id") or p.get("id")
        if ids_set is not None and oid not in ids_set:
            continue
        rows.append(
            {
                "timestamp": entry.timestamp,
                "order_id": oid,
                "event": entry.topic.split(".")[-1],
                "gateway": entry.gateway_id,
                "symbol": entry.symbol,
                "side": p.get("side"),
                "qty": p.get("quantity")
                or p.get("filled_qty")
                or p.get("remaining_qty"),
                "price": p.get("price") or p.get("fill_price"),
                "status": p.get("status"),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def query_trades(
    log_files: list[Path],
    *,
    symbol: str | None = None,
    gateway: str | None = None,
    buy_gateway: str | None = None,
    sell_gateway: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    min_qty: int | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    date_str: str | None = None,
    limit: int = 100,
    reverse: bool = False,
) -> list[dict[str, Any]]:
    """Return trade rows for the ``trades`` command."""
    if date_str:
        from_dt, to_dt = date_to_range(date_str)

    all_rows: list[dict[str, Any]] = []

    for entry in iter_entries(
        log_files,
        topic_prefix="trade.executed",
        symbol=symbol,
        from_dt=from_dt,
        to_dt=to_dt,
        limit=None,
    ):
        p = entry.payload
        bg = p.get("buy_gateway_id", "")
        sg = p.get("sell_gateway_id", "")

        if gateway and bg != gateway and sg != gateway:
            continue
        if buy_gateway and bg != buy_gateway:
            continue
        if sell_gateway and sg != sell_gateway:
            continue

        price = p.get("price")
        qty = p.get("quantity")

        if min_price is not None and (price is None or float(price) < min_price):
            continue
        if max_price is not None and (price is None or float(price) > max_price):
            continue
        if min_qty is not None and (qty is None or int(qty) < min_qty):
            continue

        all_rows.append(
            {
                "timestamp": entry.timestamp,
                "trade_id": p.get("trade_id") or p.get("id"),
                "symbol": entry.symbol,
                "price": price,
                "quantity": qty,
                "buy_gateway": bg,
                "sell_gateway": sg,
                "aggressor": p.get("aggressor_side"),
            }
        )

    if reverse:
        all_rows.reverse()

    return all_rows[:limit]


def query_topics(
    log_files: list[Path],
    *,
    prefix: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    date_str: str | None = None,
    sort_by: str = "count",
) -> list[dict[str, Any]]:
    """Return topic count rows for the ``topics`` command."""
    if date_str:
        from_dt, to_dt = date_to_range(date_str)

    counts: dict[str, int] = {}
    first_seen: dict[str, str] = {}
    last_seen: dict[str, str] = {}

    for entry in iter_entries(
        log_files,
        topic_prefix=prefix,
        from_dt=from_dt,
        to_dt=to_dt,
        limit=None,
    ):
        t = entry.topic
        counts[t] = counts.get(t, 0) + 1
        if t not in first_seen:
            first_seen[t] = entry.timestamp
        last_seen[t] = entry.timestamp

    rows = [
        {
            "topic": t,
            "count": counts[t],
            "first_seen": first_seen[t],
            "last_seen": last_seen[t],
        }
        for t in counts
    ]

    if sort_by == "alpha":
        rows.sort(key=lambda r: cast(str, r["topic"]))
    else:
        rows.sort(key=lambda r: cast(int, r["count"]), reverse=True)

    return rows


def query_gateways(
    log_files: list[Path],
    *,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    date_str: str | None = None,
    min_events: int | None = None,
) -> list[dict[str, Any]]:
    """Return gateway activity rows for the ``gateways`` command."""
    if date_str:
        from_dt, to_dt = date_to_range(date_str)

    events: dict[str, int] = {}
    orders: dict[str, int] = {}
    fills: dict[str, int] = {}
    trades: dict[str, int] = {}
    first_seen: dict[str, str] = {}
    last_seen: dict[str, str] = {}

    for entry in iter_entries(
        log_files,
        from_dt=from_dt,
        to_dt=to_dt,
        limit=None,
    ):
        gw_ids: set[str] = set()
        if entry.gateway_id:
            gw_ids.add(entry.gateway_id)
        bg = entry.payload.get("buy_gateway_id")
        sg = entry.payload.get("sell_gateway_id")
        if bg:
            gw_ids.add(str(bg))
        if sg:
            gw_ids.add(str(sg))

        for gw in gw_ids:
            events[gw] = events.get(gw, 0) + 1
            if gw not in first_seen:
                first_seen[gw] = entry.timestamp
            last_seen[gw] = entry.timestamp

            if entry.topic.startswith("order.new"):
                orders[gw] = orders.get(gw, 0) + 1
            elif entry.topic.startswith("order.fill"):
                fills[gw] = fills.get(gw, 0) + 1
            elif entry.topic == "trade.executed":
                trades[gw] = trades.get(gw, 0) + 1

    rows = [
        {
            "gateway_id": gw,
            "events": events[gw],
            "orders": orders.get(gw, 0),
            "fills": fills.get(gw, 0),
            "trades": trades.get(gw, 0),
            "first_seen": first_seen[gw],
            "last_seen": last_seen[gw],
        }
        for gw in sorted(events)
    ]

    if min_events is not None:
        rows = [r for r in rows if cast(int, r["events"]) >= min_events]

    rows.sort(key=lambda r: cast(int, r["events"]), reverse=True)
    return rows


def query_timeline(
    log_files: list[Path],
    *,
    topic_prefix: str | None = None,
    gateway: str | None = None,
    symbol: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Return chronological raw event rows for the ``timeline`` command."""
    rows: list[dict[str, Any]] = []
    for entry in iter_entries(
        log_files,
        topic_prefix=topic_prefix,
        gateway=gateway,
        symbol=symbol,
        from_dt=from_dt,
        to_dt=to_dt,
        limit=limit,
    ):
        rows.append(
            {
                "timestamp": entry.timestamp,
                "topic": entry.topic,
                "gateway": entry.gateway_id,
                "symbol": entry.symbol,
                "payload": json.dumps(entry.payload),
            }
        )
    return rows


def query_stats(
    log_files: list[Path],
    *,
    verbose: bool = False,
) -> dict[str, Any]:
    """Return summary statistics for the ``stats`` command."""
    total_events = 0
    total_bytes = 0
    compressed_bytes = 0
    oldest: str | None = None
    newest: str | None = None
    topics: set[str] = set()
    gateways: set[str] = set()
    file_stats: list[dict[str, Any]] = []

    for path in log_files:
        if not path.exists():
            continue
        file_events = 0
        file_bytes = path.stat().st_size
        total_bytes += file_bytes
        if path.suffix == ".gz":
            compressed_bytes += file_bytes

        for entry in iter_entries([path], limit=None):
            file_events += 1
            if oldest is None:
                oldest = entry.timestamp
            newest = entry.timestamp
            topics.add(entry.topic)
            if entry.gateway_id:
                gateways.add(entry.gateway_id)

        total_events += file_events
        if verbose:
            file_stats.append(
                {
                    "file": str(path),
                    "events": file_events,
                    "size_bytes": file_bytes,
                }
            )

    return {
        "total_events": total_events,
        "total_bytes": total_bytes,
        "compressed_bytes": compressed_bytes,
        "file_count": len(log_files),
        "oldest_event": oldest,
        "newest_event": newest,
        "topic_count": len(topics),
        "gateway_count": len(gateways),
        "files": file_stats if verbose else [],
    }

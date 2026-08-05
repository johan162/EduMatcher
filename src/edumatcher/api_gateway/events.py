"""Mapping from engine PUB topics to WebSocket event envelopes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

ORDER_ACK_PREFIX = "order.ack."
ORDER_FILL_PREFIX = "order.fill."
ORDER_AMENDED_PREFIX = "order.amended."
ORDER_CANCELLED_PREFIX = "order.cancelled."
ORDER_EXPIRED_PREFIX = "order.expired."
SYSTEM_SYMBOLS_PREFIX = "system.symbols."

PRIVATE_PREFIXES = (
    ORDER_ACK_PREFIX,
    ORDER_FILL_PREFIX,
    ORDER_AMENDED_PREFIX,
    ORDER_CANCELLED_PREFIX,
    ORDER_EXPIRED_PREFIX,
    "order.orders.",
    "combo.ack.",
    "combo.status.",
    "oco.ack.",
    "oco.cancelled.",
    "quote.ack.",
    "quote.status.",
    "risk.kill_switch_ack.",
    "system.gateway_auth.",
    SYSTEM_SYMBOLS_PREFIX,
    "system.quote_bootstrap.",
    "system.quote_legs.",
    "system.session_status.",
)


def now_iso() -> str:
    """Return an RFC3339-ish UTC timestamp for outgoing envelopes."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def gateway_from_topic(topic: str) -> str | None:
    """Extract the trailing gateway id from a private engine topic."""
    for prefix in PRIVATE_PREFIXES:
        if topic.startswith(prefix):
            return topic[len(prefix) :]
    return None


def websocket_type(topic: str) -> str:
    """Translate an engine topic to the stable public WebSocket type."""
    if topic.startswith("risk.kill_switch_ack."):
        return "mass_cancel.ack"
    if topic == "trade.executed":
        return "trade"
    if topic.startswith("book."):
        return "book"
    if topic.startswith("depth."):
        return "depth"
    if topic == "session.state":
        return "session"
    if topic.startswith("circuit_breaker."):
        return "circuit_breaker"
    if topic.startswith("auction.result."):
        return "auction"
    parts = topic.split(".")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return topic


def envelope(
    topic: str, payload: dict[str, Any], *, seq: int | None = None
) -> dict[str, Any]:
    """Build the uniform JSON event envelope used by both WebSockets.

    ``topic`` and ``seq`` are additive: ``type``, ``ts``, ``data`` and
    ``gateway_id`` keep their existing meanings, so a client written against
    the previous envelope keeps working and simply ignores the new fields.

    ``topic`` is the engine topic the event came from and is what ``seq``
    counts within — a client tracking gaps must key on ``topic``, not on
    ``type``, because one type (``depth``) spans many topics (``depth.AAPL``,
    ``depth.MSFT``) each with its own independent sequence.
    """
    body: dict[str, Any] = {
        "type": websocket_type(topic),
        "topic": topic,
        "ts": now_iso(),
        "data": payload,
    }
    if seq is not None:
        body["seq"] = seq
    gateway_id = gateway_from_topic(topic)
    if gateway_id is not None:
        body["gateway_id"] = gateway_id
    return body


def market_data_symbol(topic: str, payload: dict[str, Any]) -> str | None:
    """Find the symbol associated with a public market-data event."""
    if topic.startswith("book.") or topic.startswith("depth."):
        return topic.split(".", 1)[1]
    if topic.startswith("auction.result."):
        return topic[len("auction.result.") :].upper()
    raw_symbol = payload.get("symbol")
    return str(raw_symbol).upper() if raw_symbol else None

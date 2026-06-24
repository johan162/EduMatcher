"""Mapping from engine PUB topics to WebSocket event envelopes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

PRIVATE_PREFIXES = (
    "order.ack.",
    "order.fill.",
    "order.amended.",
    "order.cancelled.",
    "order.expired.",
    "order.orders.",
    "combo.ack.",
    "combo.status.",
    "oco.ack.",
    "oco.cancelled.",
    "quote.ack.",
    "quote.status.",
    "risk.kill_switch_ack.",
    "system.symbols.",
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
    parts = topic.split(".")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return topic


def envelope(topic: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Build the uniform JSON event envelope used by both WebSockets."""
    body: dict[str, Any] = {
        "type": websocket_type(topic),
        "ts": now_iso(),
        "data": payload,
    }
    gateway_id = gateway_from_topic(topic)
    if gateway_id is not None:
        body["gateway_id"] = gateway_id
    return body


def market_data_symbol(topic: str, payload: dict[str, Any]) -> str | None:
    """Find the symbol associated with a public market-data event."""
    if topic.startswith("book.") or topic.startswith("depth."):
        return topic.split(".", 1)[1]
    raw_symbol = payload.get("symbol")
    return str(raw_symbol).upper() if raw_symbol else None


def market_data_channel(topic: str) -> str | None:
    """Return the client channel name for a public market-data topic."""
    if topic.startswith("book."):
        return "book"
    if topic == "trade.executed":
        return "trades"
    if topic.startswith("depth."):
        return "depth"
    if topic == "session.state":
        return "session"
    if topic.startswith("circuit_breaker."):
        return "circuit_breaker"
    return None

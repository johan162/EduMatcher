"""Mapping from engine PUB topics to WebSocket event envelopes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED
from edumatcher.models.generated.order import (
    PREFIX_ORDER_ACK,
    PREFIX_ORDER_AMENDED,
    PREFIX_ORDER_CANCELLED,
    PREFIX_ORDER_EXPIRED,
    PREFIX_ORDER_FILL,
)

ORDER_ACK_PREFIX = PREFIX_ORDER_ACK
ORDER_FILL_PREFIX = PREFIX_ORDER_FILL
ORDER_AMENDED_PREFIX = PREFIX_ORDER_AMENDED
ORDER_CANCELLED_PREFIX = PREFIX_ORDER_CANCELLED
ORDER_EXPIRED_PREFIX = PREFIX_ORDER_EXPIRED
SYSTEM_SYMBOLS_PREFIX = "system.symbols."

#: Synthetic admin-monitor-only event (see models.message.make_admin_action_msg).
#: Deliberately NOT in PRIVATE_PREFIXES: it isn't addressed to the trading
#: gateway named in its topic suffix the way order/quote acks are, and must
#: never reach that gateway's own private stream. EngineClient._handle_event
#: checks this prefix before the private/market-data split so it only ever
#: reaches admin monitor sinks.
ADMIN_ACTION_PREFIX = "admin.action."

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


def new_command_id() -> str:
    """A correlation id for one asynchronous command.

    Only issued for commands whose ack carries no natural identifier — mass
    cancel and session transition. Orders correlate on ``order_id``, combos on
    ``combo_id``, halts on ``symbol``; giving those a second id would invite
    confusion about which one is authoritative.
    """
    return f"cmd-{uuid.uuid4().hex}"


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
    if topic.startswith(ADMIN_ACTION_PREFIX):
        return "admin.action"
    if topic.startswith("risk.kill_switch_ack."):
        return "mass_cancel.ack"
    if topic == TOPIC_TRADE_EXECUTED:
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
    topic: str,
    payload: dict[str, Any],
    *,
    seq: int | None = None,
    stream_seq: int | None = None,
) -> dict[str, Any]:
    """Build the uniform JSON event envelope used by both WebSockets.

    ``topic`` and ``seq`` are additive: ``type``, ``ts``, ``data`` and
    ``gateway_id`` keep their existing meanings, so a client written against
    the previous envelope keeps working and simply ignores the new fields.

    ``topic`` is the engine topic the event came from and is what ``seq``
    counts within — a client tracking gaps must key on ``topic``, not on
    ``type``, because one type (``depth``) spans many topics (``depth.AAPL``,
    ``depth.MSFT``) each with its own independent sequence.

    ``stream_seq`` is present on private events only. Those reach a client
    unfiltered, so one counter across the whole gateway stream is contiguous
    and is simpler to check than one counter per topic. Market data has no
    equivalent because subscribers filter.
    """
    body: dict[str, Any] = {
        "type": websocket_type(topic),
        "topic": topic,
        "ts": now_iso(),
        "data": payload,
    }
    if seq is not None:
        body["seq"] = seq
    if stream_seq is not None:
        body["stream_seq"] = stream_seq
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

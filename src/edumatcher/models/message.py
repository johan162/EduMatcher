"""
Message envelope helpers for ZeroMQ pub/sub and push/pull.

All messages are multipart ZMQ frames:
  frame[0]: topic (bytes) — used for PUB/SUB filtering
  frame[1]: JSON payload  (bytes)

Topic conventions
-----------------
  order.new          — gateway → engine (PUSH/PULL, but we still include a topic for audit)
  order.cancel       — gateway → engine
    system.gateway_connect   — gateway → engine: authenticate gateway_id
    system.gateway_auth.{GW_ID} — engine → all: auth accepted/rejected (connect)
    system.gateway_disconnect — gateway → engine: graceful disconnect
    system.gateway_bye.{GW_ID} — engine → all: disconnect broadcast
  order.ack.{GW_ID}  — engine → gateway: accepted or rejected
  order.fill.{GW_ID} — engine → gateway: partial or full fill
  order.cancelled.{GW_ID} — engine → gateway: cancel confirmed
  order.expired.{GW_ID}   — engine → gateway: DAY order expired at shutdown
  trade.executed     — engine → all subscribers
  book.{SYMBOL}      — engine → all subscribers
"""

from __future__ import annotations

import time
from typing import Any

from edumatcher.models.feed_schema import (
    GatewayAuthPayload,
    GatewayByePayload,
    SessionStatePayload,
    SystemEodPayload,
    TradeExecutedPayload,
)

# PERF improvement #6: Use orjson instead of stdlib json.
#
# orjson is a C-extension JSON serializer that is ~9-10x faster than
# json.dumps().encode() for the dict sizes used in our message envelopes
# (~10-15 keys).  With 2-4 encode() calls per order on the hot path,
# switching from json (~2.1µs/call) to orjson (~0.22µs/call) saves
# ~4-7µs per aggressive order.  orjson.dumps() returns bytes directly,
# eliminating the extra .encode() step required by stdlib json.
#
# For decode (inbound messages from gateways), orjson.loads() is similarly
# faster, but decode is not on the latency-critical path since the gateway
# already parsed the user command before sending.
try:
    import orjson as _json_mod

    def _dumps(obj: dict[str, Any]) -> bytes:
        return _json_mod.dumps(obj)

    def _loads(data: bytes) -> dict[str, Any]:
        return _json_mod.loads(data)  # type: ignore[no-any-return]

except ImportError:
    # Fallback to stdlib json if orjson is not installed (e.g. minimal envs)
    import json as _json_fallback

    def _dumps(obj: dict[str, Any]) -> bytes:
        return _json_fallback.dumps(obj).encode()

    def _loads(data: bytes) -> dict[str, Any]:
        return _json_fallback.loads(data)  # type: ignore[no-any-return]


def encode(topic: str, payload: dict[str, Any]) -> list[bytes]:
    """Return a two-frame ZMQ multipart message."""
    return [topic.encode(), _dumps(payload)]


def decode(frames: list[bytes]) -> tuple[str, dict[str, Any]]:
    """Parse a two-frame ZMQ multipart message."""
    topic = frames[0].decode()
    payload = _loads(frames[1])
    return topic, payload


def dumps(payload: dict[str, Any]) -> bytes:
    """Public JSON serializer for payloads used in fast-path message publishing."""
    return _dumps(payload)


def make_order_new_msg(order_dict: dict[str, Any]) -> list[bytes]:
    return encode("order.new", order_dict)


def make_gateway_connect_msg(gateway_id: str) -> list[bytes]:
    return encode("system.gateway_connect", {"gateway_id": gateway_id})


def make_gateway_auth_msg(
    gateway_id: str,
    accepted: bool,
    reason: str = "",
    description: str = "",
) -> list[bytes]:
    typed = GatewayAuthPayload(
        gateway_id=gateway_id,
        accepted=accepted,
        reason=reason,
        description=description,
    )
    topic = f"system.gateway_auth.{typed.gateway_id}"
    payload = typed.to_dict()
    return encode(topic, payload)


def make_order_cancel_msg(order_id: str, gateway_id: str) -> list[bytes]:
    return encode("order.cancel", {"order_id": order_id, "gateway_id": gateway_id})


def make_order_amend_msg(
    order_id: str,
    gateway_id: str,
    price: float | None = None,
    qty: int | None = None,
) -> list[bytes]:
    payload: dict[str, Any] = {"order_id": order_id, "gateway_id": gateway_id}
    if price is not None:
        payload["price"] = price
    if qty is not None:
        payload["qty"] = qty
    return encode("order.amend", payload)


def make_amended_msg(
    gateway_id: str,
    order_id: str,
    price: float | None,
    qty: int,
    remaining_qty: int,
    priority_reset: bool,
) -> list[bytes]:
    topic = f"order.amended.{gateway_id}"
    return encode(
        topic,
        {
            "order_id": order_id,
            "price": price,
            "qty": qty,
            "remaining_qty": remaining_qty,
            "priority_reset": priority_reset,
        },
    )


def make_ack_msg(
    gateway_id: str,
    order_id: str,
    accepted: bool,
    reason: str = "",
    order: dict[str, Any] | None = None,
) -> list[bytes]:
    topic = f"order.ack.{gateway_id}"
    payload: dict[str, Any] = {
        "order_id": order_id,
        "accepted": accepted,
        "reason": reason,
    }
    if order:
        payload.update(
            {
                "symbol": order.get("symbol"),
                "side": order.get("side"),
                "order_type": order.get("order_type"),
                "tif": order.get("tif"),
                "qty": order.get("quantity"),
                "price": order.get("price"),
            }
        )
        if order.get("client_tag") is not None:
            payload["client_tag"] = order["client_tag"]
    return encode(topic, payload)


def make_fill_msg(
    gateway_id: str,
    order_id: str,
    fill_qty: int,
    fill_price: float,
    remaining_qty: int,
    status: str,
    order: dict[str, Any] | None = None,
) -> list[bytes]:
    topic = f"order.fill.{gateway_id}"
    payload: dict[str, Any] = {
        "order_id": order_id,
        "fill_qty": fill_qty,
        "fill_price": fill_price,
        "remaining_qty": remaining_qty,
        "status": status,
    }
    if order:
        payload.update(
            {
                "symbol": order.get("symbol"),
                "side": order.get("side"),
                "order_type": order.get("order_type"),
                "tif": order.get("tif"),
                "qty": order.get("quantity"),
                "price": order.get("price"),
            }
        )
        if order.get("client_tag") is not None:
            payload["client_tag"] = order["client_tag"]
    return encode(topic, payload)


def make_cancelled_msg(
    gateway_id: str,
    order_id: str,
    client_tag: str | None = None,
) -> list[bytes]:
    topic = f"order.cancelled.{gateway_id}"
    payload: dict[str, Any] = {"order_id": order_id}
    if client_tag is not None:
        payload["client_tag"] = client_tag
    return encode(topic, payload)


def make_expired_msg(
    gateway_id: str,
    order_id: str,
    client_tag: str | None = None,
) -> list[bytes]:
    topic = f"order.expired.{gateway_id}"
    payload: dict[str, Any] = {"order_id": order_id}
    if client_tag is not None:
        payload["client_tag"] = client_tag
    return encode(topic, payload)


def make_trade_msg(trade_dict: dict[str, Any]) -> list[bytes]:
    typed = TradeExecutedPayload.from_dict(trade_dict)
    return encode("trade.executed", typed.to_dict())


def make_book_msg(symbol: str, book_snapshot: dict[str, Any]) -> list[bytes]:
    return encode(f"book.{symbol}", book_snapshot)


def make_orders_request_msg(gateway_id: str) -> list[bytes]:
    return encode("order.orders_request", {"gateway_id": gateway_id})


def make_orders_msg(gateway_id: str, orders: list[dict[str, Any]]) -> list[bytes]:
    topic = f"order.orders.{gateway_id}"
    return encode(topic, {"orders": orders})


def make_book_snapshot_request_msg(symbol: str) -> list[bytes]:
    return encode("book.snapshot_request", {"symbol": symbol})


def make_eod_msg(books: list[dict[str, Any]]) -> list[bytes]:
    """
    End-of-day broadcast — engine sends this before shutting down.
    ``books`` is a list of book snapshots (one per symbol), each containing
    the current best bid/ask so subscribers can record closing prices.
    """
    typed = SystemEodPayload.from_dict({"books": books})
    return encode("system.eod", typed.to_dict())


def make_symbols_request_msg(gateway_id: str) -> list[bytes]:
    return encode("system.symbols_request", {"gateway_id": gateway_id})


def make_symbols_msg(
    gateway_id: str,
    symbols: list[str],
    symbol_meta: dict[str, Any] | None = None,
) -> list[bytes]:
    topic = f"system.symbols.{gateway_id}"
    payload: dict[str, Any] = {"symbols": symbols}
    if symbol_meta is not None:
        payload["symbol_meta"] = symbol_meta
    return encode(topic, payload)


def make_quote_bootstrap_request_msg(gateway_id: str, symbol: str = "") -> list[bytes]:
    """Gateway -> engine: request active quote bootstrap state."""
    return encode(
        "system.quote_bootstrap_request",
        {"gateway_id": gateway_id, "symbol": symbol.upper()},
    )


def make_quote_bootstrap_msg(
    gateway_id: str, quotes: list[dict[str, Any]]
) -> list[bytes]:
    """Engine -> gateway: reply with active quote bootstrap state."""
    topic = f"system.quote_bootstrap.{gateway_id}"
    return encode(topic, {"quotes": quotes})


def make_quote_legs_request_msg(
    gateway_id: str, symbol: str = "", show: str = "ALL"
) -> list[bytes]:
    """Gateway -> engine: request quote leg snapshot (QLEGS)."""
    return encode(
        "system.quote_legs_request",
        {"gateway_id": gateway_id, "symbol": symbol.upper(), "show": show.upper()},
    )


def make_quote_legs_msg(
    gateway_id: str,
    legs: list[dict[str, Any]],
    *,
    show_requested: str = "ACTIVE",
    complete: bool = True,
    recent: list[dict[str, Any]] | None = None,
) -> list[bytes]:
    """Engine -> gateway: reply with quote legs snapshot.

    *legs* is the currently-active per-leg detail (qty, remaining, status)
    — populated when *show_requested* is ``"ACTIVE"`` or ``"ALL"``.

    *recent* is a bounded, most-recently-removed-first list of quote-level
    summaries (quote_id, symbol, leg order ids, final quote_status, removal
    *reason*, and *removed_at_ns*) drawn from the engine's in-memory,
    per-gateway inactivation history — populated when *show_requested* is
    ``"RECENT"`` or ``"ALL"``. Unlike *legs*, recent rows do not carry live
    qty/remaining/status: that detail is not retained once an order leaves
    the book. This history does not survive an engine restart.

    *complete* is ``True`` when the reply fully answers what was requested
    (always true for ``ACTIVE``; also true for ``RECENT``/``ALL`` now that
    real history is tracked, modulo the history buffer's bound).
    """
    topic = f"system.quote_legs.{gateway_id}"
    return encode(
        topic,
        {
            "legs": legs,
            "show_requested": show_requested,
            "complete": complete,
            "recent": recent or [],
        },
    )


# ------------------------------------------------------------------
# Session-status query (read current state without advancing it)
# ------------------------------------------------------------------


def make_session_state_request_msg(gateway_id: str) -> list[bytes]:
    """Operator → engine: request the current session state."""
    return encode("system.session_state_request", {"gateway_id": gateway_id})


def make_session_status_msg(
    gateway_id: str,
    state: str,
    sessions_enabled: bool,
) -> list[bytes]:
    """Engine → operator: reply with the current session state."""
    topic = f"system.session_status.{gateway_id}"
    return encode(topic, {"state": state, "sessions_enabled": sessions_enabled})


# ------------------------------------------------------------------
# Session schedule query
# ------------------------------------------------------------------


def make_session_schedule_request_msg(gateway_id: str) -> list[bytes]:
    """Operator → engine: request the session schedule configuration."""
    return encode("system.session_schedule_request", {"gateway_id": gateway_id})


def make_session_schedule_msg(
    gateway_id: str,
    sessions_enabled: bool,
    schedule: dict[str, str] | None,
) -> list[bytes]:
    """Engine → operator: reply with the session schedule configuration."""
    topic = f"system.session_schedule.{gateway_id}"
    return encode(
        topic,
        {
            "sessions_enabled": sessions_enabled,
            "schedule": schedule or {},
        },
    )


# ------------------------------------------------------------------
# Gateway-list query
# ------------------------------------------------------------------


def make_gateways_request_msg(gateway_id: str) -> list[bytes]:
    """Operator → engine: request the list of configured gateways."""
    return encode("system.gateways_request", {"gateway_id": gateway_id})


def make_gateways_msg(
    gateway_id: str,
    gateways: list[dict[str, Any]],
) -> list[bytes]:
    """Engine → operator: reply with configured gateways and connection status."""
    topic = f"system.gateways.{gateway_id}"
    return encode(topic, {"gateways": gateways})


# ------------------------------------------------------------------
# Daily volume query
# ------------------------------------------------------------------


def make_volume_request_msg(gateway_id: str) -> list[bytes]:
    """Operator → engine: request daily traded volume."""
    return encode("system.volume_request", {"gateway_id": gateway_id})


def make_volume_msg(
    gateway_id: str,
    symbols: dict[str, dict[str, Any]],
    total_qty: int,
    total_value: float,
    total_trades: int,
) -> list[bytes]:
    """Engine → operator: reply with daily volume data."""
    topic = f"system.volume.{gateway_id}"
    return encode(
        topic,
        {
            "symbols": symbols,
            "total_qty": total_qty,
            "total_value": total_value,
            "total_trades": total_trades,
        },
    )


# ------------------------------------------------------------------
# Combo-order messages
# ------------------------------------------------------------------


def make_combo_order_msg(combo_dict: dict[str, Any]) -> list[bytes]:
    """Gateway → engine: submit a combo order."""
    return encode("order.combo", combo_dict)


def make_combo_cancel_msg(combo_id: str, gateway_id: str) -> list[bytes]:
    """Gateway → engine: cancel a combo and all its child legs."""
    return encode(
        "order.combo_cancel",
        {
            "combo_id": combo_id,
            "gateway_id": gateway_id,
        },
    )


def make_combo_ack_msg(
    gateway_id: str,
    combo_id: str,
    accepted: bool,
    reason: str = "",
    combo: dict[str, Any] | None = None,
) -> list[bytes]:
    """Engine → gateway: combo accepted or rejected."""
    topic = f"combo.ack.{gateway_id}"
    payload: dict[str, Any] = {
        "combo_id": combo_id,
        "accepted": accepted,
        "reason": reason,
    }
    if combo:
        payload["combo"] = combo
    return encode(topic, payload)


def make_combo_status_msg(
    gateway_id: str,
    combo_id: str,
    status: str,
    details: dict[str, Any] | None = None,
) -> list[bytes]:
    """Engine → gateway: combo status transition (MATCHED / FAILED / etc.)."""
    topic = f"combo.status.{gateway_id}"
    payload: dict[str, Any] = {
        "combo_id": combo_id,
        "status": status,
    }
    if details:
        payload["details"] = details
    return encode(topic, payload)


# ---------------------------------------------------------------------------
# Session / auction messages
# ---------------------------------------------------------------------------


def make_session_transition_msg(to_state: str) -> list[bytes]:
    """Scheduler → engine: request session state transition."""
    return encode("session.transition", {"to_state": to_state})


def make_session_state_msg(state: str, prev_state: str = "") -> list[bytes]:
    """Engine → all: broadcast current session state."""
    typed = SessionStatePayload(state=state, prev_state=prev_state)
    return encode("session.state", typed.to_dict())


def make_auction_result_msg(
    symbol: str,
    eq_price: float | None,
    eq_qty: int,
    trades_count: int,
    imbalance_side: str,
    imbalance_qty: int,
) -> list[bytes]:
    """Engine → all: auction uncross result for one symbol."""
    return encode(
        f"auction.result.{symbol}",
        {
            "symbol": symbol,
            "eq_price": eq_price,
            "eq_qty": eq_qty,
            "trades_count": trades_count,
            "imbalance_side": imbalance_side,
            "imbalance_qty": imbalance_qty,
        },
    )


# ------------------------------------------------------------------
# OCO-order messages
# ------------------------------------------------------------------


def make_oco_order_msg(payload: dict[str, Any]) -> list[bytes]:
    """Gateway → engine: submit an OCO (One-Cancels-Other) pair."""
    return encode("order.oco", payload)


def make_oco_cancel_msg(oco_id: str, gateway_id: str) -> list[bytes]:
    """Gateway → engine: cancel an OCO pair and both its legs."""
    return encode("order.oco_cancel", {"oco_id": oco_id, "gateway_id": gateway_id})


def make_oco_ack_msg(
    gateway_id: str,
    oco_id: str,
    accepted: bool,
    reason: str = "",
    order_id_1: str = "",
    order_id_2: str = "",
) -> list[bytes]:
    """Engine → gateway: OCO pair accepted or rejected."""
    topic = f"oco.ack.{gateway_id}"
    payload: dict[str, Any] = {
        "oco_id": oco_id,
        "accepted": accepted,
        "reason": reason,
        "order_id_1": order_id_1,
        "order_id_2": order_id_2,
    }
    return encode(topic, payload)


def make_oco_cancelled_msg(
    gateway_id: str, oco_id: str, cancelled_order_id: str, reason: str = ""
) -> list[bytes]:
    """Engine → gateway: OCO sibling cancelled because the other leg was actioned."""
    topic = f"oco.cancelled.{gateway_id}"
    return encode(
        topic,
        {
            "oco_id": oco_id,
            "cancelled_order_id": cancelled_order_id,
            "reason": reason,
        },
    )


# ------------------------------------------------------------------
# MM quote / risk-control messages
# ------------------------------------------------------------------


def make_quote_new_msg(payload: dict[str, Any]) -> list[bytes]:
    """Gateway → engine: submit/replace two-sided quote for one symbol."""
    return encode("quote.new", payload)


def make_quote_cancel_msg(gateway_id: str, symbol: str) -> list[bytes]:
    """Gateway → engine: cancel active quote for one symbol."""
    return encode("quote.cancel", {"gateway_id": gateway_id, "symbol": symbol})


def make_quote_ack_msg(
    gateway_id: str,
    quote_id: str,
    accepted: bool,
    reason: str = "",
    bid_order_id: str = "",
    ask_order_id: str = "",
) -> list[bytes]:
    """Engine → gateway: quote accepted or rejected."""
    topic = f"quote.ack.{gateway_id}"
    return encode(
        topic,
        {
            "quote_id": quote_id,
            "accepted": accepted,
            "reason": reason,
            "bid_order_id": bid_order_id,
            "ask_order_id": ask_order_id,
        },
    )


def make_quote_status_msg(
    gateway_id: str,
    quote_id: str,
    status: str,
    reason: str = "",
) -> list[bytes]:
    """Engine → gateway: quote lifecycle transition."""
    topic = f"quote.status.{gateway_id}"
    return encode(
        topic,
        {
            "quote_id": quote_id,
            "status": status,
            "reason": reason,
        },
    )


def make_gateway_disconnect_msg(gateway_id: str, reason: str = "") -> list[bytes]:
    """Gateway → engine: graceful disconnect notification."""
    return encode(
        "system.gateway_disconnect",
        {
            "gateway_id": gateway_id,
            "reason": reason,
        },
    )


def make_gateway_bye_msg(gateway_id: str, reason: str = "") -> list[bytes]:
    """
    Engine → all subscribers: gateway lifecycle *disconnect* broadcast.

    The PUB-side counterpart to ``system.gateway_auth.{id}`` (connect).  The
    inbound ``system.gateway_disconnect`` is a gateway→engine PULL message and
    never reaches PUB subscribers such as clearing; this broadcast republishes
    the disconnect on the public feed so downstream consumers can close the
    matching session.
    """
    typed = GatewayByePayload(gateway_id=gateway_id, reason=reason)
    return encode(f"system.gateway_bye.{typed.gateway_id}", typed.to_dict())


def make_kill_switch_msg(gateway_id: str, symbol: str = "") -> list[bytes]:
    """Gateway/admin → engine: cancel open risk-bearing exposure."""
    return encode("risk.kill_switch", {"gateway_id": gateway_id, "symbol": symbol})


def make_kill_switch_ack_msg(
    gateway_id: str,
    accepted: bool,
    reason: str = "",
    cancelled_orders: int = 0,
    cancelled_quotes: int = 0,
) -> list[bytes]:
    """Engine → gateway/admin: kill-switch result summary."""
    topic = f"risk.kill_switch_ack.{gateway_id}"
    return encode(
        topic,
        {
            "accepted": accepted,
            "reason": reason,
            "cancelled_orders": cancelled_orders,
            "cancelled_quotes": cancelled_quotes,
        },
    )


def make_circuit_breaker_halt_all_msg(gateway_id: str) -> list[bytes]:
    """Admin → engine: halt trading for all known symbols."""
    return encode("risk.circuit_breaker_halt_all", {"gateway_id": gateway_id})


def make_circuit_breaker_halt_all_ack_msg(
    gateway_id: str,
    accepted: bool,
    reason: str = "",
    halted_symbols: int = 0,
    cancelled_quotes: int = 0,
) -> list[bytes]:
    """Engine → admin: global circuit-breaker halt result summary."""
    topic = f"risk.circuit_breaker_halt_all_ack.{gateway_id}"
    return encode(
        topic,
        {
            "accepted": accepted,
            "reason": reason,
            "halted_symbols": halted_symbols,
            "cancelled_quotes": cancelled_quotes,
        },
    )


def make_circuit_breaker_resume_all_msg(gateway_id: str) -> list[bytes]:
    """Admin → engine: resume trading for all symbols halted by global CB halt."""
    return encode("risk.circuit_breaker_resume_all", {"gateway_id": gateway_id})


def make_circuit_breaker_resume_all_ack_msg(
    gateway_id: str,
    accepted: bool,
    reason: str = "",
    resumed_symbols: int = 0,
) -> list[bytes]:
    """Engine → admin: global circuit-breaker resume result summary."""
    topic = f"risk.circuit_breaker_resume_all_ack.{gateway_id}"
    return encode(
        topic,
        {
            "accepted": accepted,
            "reason": reason,
            "resumed_symbols": resumed_symbols,
        },
    )


# ---------------------------------------------------------------------------
# Per-symbol halt / resume
# ---------------------------------------------------------------------------


def make_symbol_halt_msg(gateway_id: str, symbol: str) -> list[bytes]:
    """Admin → engine: halt trading on a single symbol (ADMIN role required)."""
    return encode(
        "risk.symbol_halt",
        {"gateway_id": gateway_id, "symbol": symbol.upper()},
    )


def make_symbol_halt_ack_msg(
    gateway_id: str,
    symbol: str,
    accepted: bool,
    reason: str = "",
    cancelled_quotes: int = 0,
) -> list[bytes]:
    """Engine → admin: per-symbol halt result."""
    return encode(
        f"risk.symbol_halt_ack.{gateway_id}",
        {
            "accepted": accepted,
            "symbol": symbol,
            "reason": reason,
            "cancelled_quotes": cancelled_quotes,
        },
    )


def make_symbol_resume_msg(gateway_id: str, symbol: str) -> list[bytes]:
    """Admin → engine: resume trading on a single halted symbol (ADMIN role required)."""
    return encode(
        "risk.symbol_resume",
        {"gateway_id": gateway_id, "symbol": symbol.upper()},
    )


def make_symbol_resume_ack_msg(
    gateway_id: str,
    symbol: str,
    accepted: bool,
    reason: str = "",
) -> list[bytes]:
    """Engine → admin: per-symbol resume result."""
    return encode(
        f"risk.symbol_resume_ack.{gateway_id}",
        {
            "accepted": accepted,
            "symbol": symbol,
            "reason": reason,
        },
    )


# ---------------------------------------------------------------------------
# Symbol-scoped mass cancel (across all gateways)
# ---------------------------------------------------------------------------


def make_cancel_symbol_msg(gateway_id: str, symbol: str) -> list[bytes]:
    """Admin → engine: cancel all resting orders for *symbol* across every gateway."""
    return encode(
        "risk.cancel_symbol",
        {"gateway_id": gateway_id, "symbol": symbol.upper()},
    )


def make_cancel_symbol_ack_msg(
    gateway_id: str,
    symbol: str,
    accepted: bool,
    reason: str = "",
    cancelled_orders: int = 0,
    cancelled_quotes: int = 0,
) -> list[bytes]:
    """Engine → admin: symbol-level mass-cancel result."""
    return encode(
        f"risk.cancel_symbol_ack.{gateway_id}",
        {
            "accepted": accepted,
            "symbol": symbol,
            "reason": reason,
            "cancelled_orders": cancelled_orders,
            "cancelled_quotes": cancelled_quotes,
        },
    )


# ---------------------------------------------------------------------------
# Halt-status snapshot (request / reply)
# ---------------------------------------------------------------------------


def make_halt_status_request_msg(gateway_id: str) -> list[bytes]:
    """Any process → engine: request current halt state for all symbols."""
    return encode("system.halt_status_request", {"gateway_id": gateway_id})


def make_halt_status_msg(
    gateway_id: str,
    halted: list[dict[str, Any]],
) -> list[bytes]:
    """Engine → requester: snapshot of currently halted symbols.

    Each entry in *halted* has:
      ``symbol`` (str), ``resume_at_ns`` (int | None),
      ``level`` (str | None), ``resumption_mode`` (str | None).
    An empty list means no symbols are currently halted.
    """
    topic = f"system.halt_status.{gateway_id}"
    return encode(topic, {"halted": halted})


def make_position_request_msg(gateway_id: str) -> list[bytes]:
    """Any process → engine: request current position snapshot for *gateway_id*.

    The engine replies on ``system.position_snapshot.<GW_ID>``.
    """
    return encode("system.position_request", {"gateway_id": gateway_id})


def make_position_snapshot_msg(
    gateway_id: str,
    positions: list[dict[str, Any]],
) -> list[bytes]:
    """Engine → requester: per-symbol position snapshot for *gateway_id*.

    Each entry in *positions* has:
      ``symbol`` (str), ``net_qty`` (int, positive = long / negative = short),
      ``avg_cost`` (float display price, 0.0 if flat).
    Only symbols with a non-zero net position are included.
    An empty list means the gateway is flat across all symbols.
    """
    topic = f"system.position_snapshot.{gateway_id}"
    return encode(topic, {"positions": positions})


# ------------------------------------------------------------------
# Index messages
# ------------------------------------------------------------------


def make_index_update_msg(
    index_id: str,
    level: float,
    aggregate_cap: float,
    divisor: float,
    session_state: str,
    day_open: float | None = None,
    day_high: float | None = None,
    day_low: float | None = None,
) -> list[bytes]:
    """pm-index → subscribers: current index level broadcast."""
    payload: dict[str, Any] = {
        "index_id": index_id,
        "level": level,
        "aggregate_cap": aggregate_cap,
        "divisor": divisor,
        "session_state": session_state,
        "timestamp": time.time(),
    }
    if day_open is not None:
        payload["day_open"] = day_open
        payload["day_high"] = day_high
        payload["day_low"] = day_low
    return encode("index.update", payload)


def make_index_history_request_msg(
    gateway_id: str,
    index_id: str,
    from_ts: float,
    to_ts: float,
    types: list[str] | None = None,
    max_records: int = 10_000,
) -> list[bytes]:
    """Gateway/operator → pm-index: request structural/audit index records.

    pm-index's history is a structural audit log only (INIT, CORP_ACTION,
    ADD_CONSTITUENT, DELIST) — it no longer stores level or EOD ticks.
    Omitting *types* returns all structural record types. For index
    level/EOD time-series history, query pm-stats instead.
    """
    return encode(
        "index.history_request",
        {
            "gateway_id": gateway_id,
            "index_id": index_id,
            "from_ts": from_ts,
            "to_ts": to_ts,
            "types": types or ["INIT", "CORP_ACTION", "ADD_CONSTITUENT", "DELIST"],
            "max_records": max_records,
        },
    )


def make_index_history_msg(
    gateway_id: str,
    index_id: str,
    records: list[dict[str, Any]],
    warnings: list[str] | None = None,
) -> list[bytes]:
    """pm-index → requestor: history response."""
    payload: dict[str, Any] = {"index_id": index_id, "records": records}
    if warnings:
        payload["warnings"] = warnings
    return encode(f"index.history.{gateway_id}", payload)


def make_index_corp_action_msg(
    action: str,
    index_id: str,
    symbol: str,
    gateway_id: str,
    params: dict[str, Any],
) -> list[bytes]:
    """Operator → pm-index: apply a corporate action."""
    return encode(
        "index.corp_action",
        {
            "action": action,
            "index_id": index_id,
            "symbol": symbol,
            "gateway_id": gateway_id,
            **params,
        },
    )


def make_index_constituent_change_msg(
    change_type: str,
    index_id: str,
    symbol: str,
    gateway_id: str,
    shares_outstanding: int | None = None,
    initial_price: float | None = None,
) -> list[bytes]:
    """Operator → pm-index: add or delist a constituent."""
    payload: dict[str, Any] = {
        "change_type": change_type,
        "index_id": index_id,
        "symbol": symbol,
        "gateway_id": gateway_id,
    }
    if shares_outstanding is not None:
        payload["shares_outstanding"] = shares_outstanding
    if initial_price is not None:
        payload["initial_price"] = initial_price
    return encode("index.constituent_change", payload)


def make_index_corp_action_ack_msg(
    gateway_id: str,
    accepted: bool,
    reason: str = "",
    index_id: str = "",
    level: float | None = None,
    divisor: float | None = None,
) -> list[bytes]:
    """pm-index → requestor: corporate action ack."""
    payload: dict[str, Any] = {
        "accepted": accepted,
        "reason": reason,
        "timestamp": time.time(),
    }
    if index_id:
        payload["index_id"] = index_id
    if level is not None:
        payload["level"] = level
    if divisor is not None:
        payload["divisor"] = divisor
    return encode(f"index.corp_action_ack.{gateway_id}", payload)


def make_index_constituent_change_ack_msg(
    gateway_id: str,
    accepted: bool,
    reason: str = "",
    index_id: str = "",
    level: float | None = None,
    divisor: float | None = None,
) -> list[bytes]:
    """pm-index → requestor: constituent change ack."""
    payload: dict[str, Any] = {
        "accepted": accepted,
        "reason": reason,
        "timestamp": time.time(),
    }
    if index_id:
        payload["index_id"] = index_id
    if level is not None:
        payload["level"] = level
    if divisor is not None:
        payload["divisor"] = divisor
    return encode(f"index.constituent_change_ack.{gateway_id}", payload)


def make_index_error_msg(gateway_id: str, reason: str) -> list[bytes]:
    """pm-index → requestor: generic index error reply."""
    return encode(
        f"index.error.{gateway_id}",
        {"accepted": False, "reason": reason, "timestamp": time.time()},
    )


def make_depth_msg(symbol: str, depth: dict[str, Any]) -> list[bytes]:
    """Engine → subscribers: depth ladder snapshot."""
    return encode(f"book.depth.{symbol}", depth)

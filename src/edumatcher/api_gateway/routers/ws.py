"""WebSocket endpoints for private events and public market data."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from edumatcher.api_gateway.events import market_data_symbol, now_iso
from edumatcher.api_gateway.schemas import ALWAYS_ON_CHANNELS, MarketDataControl
from edumatcher.api_gateway.sessions import SessionRegistry

router = APIRouter(prefix="/api/v1", tags=["websockets"])

#: Stands in for "every symbol" inside a subscription pair.
_ANY_SYMBOL = "*"


class Subscription:
    """What one market-data socket has asked for.

    Held as a set of ``(symbol, channel)`` pairs rather than as a symbol set
    and a channel set. The two-set form could only ever express their cross
    product, so "book for every symbol, depth for AAPL only" — the ordinary
    shape of a terminal with an overview grid and one focused symbol — was not
    expressible: asking for depth on AAPL also asked for it on everything else
    already subscribed. Pairs make each rule independent.

    A consequence worth stating: accumulating two flat-form subscribes no
    longer produces the cross product of the union. ``{AAPL, [book]}`` then
    ``{MSFT, [depth]}`` now yields exactly those two rules, not four. That is
    the defect being fixed, but it is a behaviour change for any client that
    relied on the old widening.
    """

    def __init__(self) -> None:
        self._pairs: set[tuple[str, str]] = set()

    def apply(self, control: MarketDataControl) -> list[dict[str, Any]]:
        """Add or remove rules. Returns items that contributed nothing."""
        rejected: list[dict[str, Any]] = []
        for item in control.as_items():
            if not item.channels:
                rejected.append(
                    {
                        "symbols": item.symbols,
                        "channels": [],
                        "reason": "no_channels",
                    }
                )
                continue
            symbols = {s.upper() for s in item.symbols if s} or {_ANY_SYMBOL}
            if _ANY_SYMBOL in symbols:
                symbols = {_ANY_SYMBOL}
            pairs = {(sym, ch) for sym in symbols for ch in item.channels}
            if control.action == "subscribe":
                self._pairs |= pairs
            else:
                self._pairs -= pairs
                # Unsubscribing a named symbol cannot cancel a wildcard rule;
                # say so rather than leaving the client wondering why events
                # keep arriving.
                for _, ch in pairs:
                    if (_ANY_SYMBOL, ch) in self._pairs and _ANY_SYMBOL not in symbols:
                        rejected.append(
                            {
                                "symbols": sorted(symbols),
                                "channels": [ch],
                                "reason": "wildcard_still_subscribed",
                            }
                        )
                        break
        return rejected

    def matches(self, symbol: str | None, channel: str | None) -> bool:
        if channel is None:
            return False
        if (_ANY_SYMBOL, channel) in self._pairs:
            return True
        return symbol is not None and (symbol, channel) in self._pairs

    def describe(self, rejected: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """The effective subscription, in both the new and the legacy shape."""
        by_symbol: dict[str, list[str]] = {}
        for sym, ch in sorted(self._pairs):
            by_symbol.setdefault(sym, []).append(ch)
        return {
            "items": [
                {"symbols": [sym], "channels": sorted(chans)}
                for sym, chans in sorted(by_symbol.items())
            ],
            # Retained so a client parsing the previous ack still finds what it
            # expects. Lossy by construction: it cannot represent per-symbol
            # channels, which is the whole reason `items` exists.
            "symbols": sorted(s for s, _ in self._pairs if s != _ANY_SYMBOL),
            "channels": sorted({c for _, c in self._pairs}),
            "always": list(ALWAYS_ON_CHANNELS),
            "rejected": rejected or [],
        }


async def _authenticate_ws(websocket: WebSocket) -> tuple[str, str | None]:
    """Read the first WS frame and resolve it as an API key."""
    try:
        message = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
    except TimeoutError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise
    except ValueError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise WebSocketDisconnect(code=status.WS_1008_POLICY_VIOLATION) from None
    api_key = str(message.get("api_key", "")) if isinstance(message, dict) else ""
    registry: SessionRegistry = websocket.app.state.sessions
    credential = registry.get(api_key)
    if credential is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise WebSocketDisconnect(code=status.WS_1008_POLICY_VIOLATION)
    return api_key, credential.gateway_id


@router.websocket("/events")
async def private_events(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        _, gateway_id = await _authenticate_ws(websocket)
        if gateway_id is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        accepted, reason = await websocket.app.state.engine.authenticate(
            gateway_id,
            timeout=websocket.app.state.config.timeouts.engine_auth_sec,
        )
        if not accepted:
            await websocket.send_json({"type": "error", "data": {"message": reason}})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        engine = websocket.app.state.engine
        # Register the sink *before* the snapshot is taken and sent. Doing it
        # after would drop every event that landed in between — the gap a
        # reconnecting client is least able to notice, because the snapshot
        # would look complete. Registering first means the worst case is a
        # duplicate: an event both included in the snapshot and delivered
        # live. Order state is idempotent, so applying it twice is harmless,
        # whereas missing it is not.
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        engine.add_sink(gateway_id, queue)
        try:
            await websocket.send_json(
                {
                    "type": "authenticated",
                    "gateway_id": gateway_id,
                    "stream_seq": engine.stream_seq(gateway_id),
                }
            )
            # The snapshot removes the reconnect round-trip to GET /orders and
            # the race it opens. `stream_seq` is the point the snapshot is
            # accurate as of: anything numbered above it arrives live.
            cache = engine.get_caches(gateway_id)
            await websocket.send_json(
                {
                    "type": "orders.snapshot",
                    "gateway_id": gateway_id,
                    "stream_seq": engine.stream_seq(gateway_id),
                    "ts": now_iso(),
                    "data": {
                        "orders": list(cache.orders.values()),
                        "positions": dict(cache.positions),
                        "quote_legs": list(cache.quote_legs.values()),
                    },
                }
            )
        except Exception:
            engine.remove_sink(gateway_id, queue)
            raise
        try:
            while True:
                event = await queue.get()
                await websocket.send_json(event)
        finally:
            websocket.app.state.engine.remove_sink(gateway_id, queue)
    except (WebSocketDisconnect, TimeoutError):
        return


@router.websocket("/admin/monitor")
async def admin_monitor(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        _, gateway_id = await _authenticate_ws(websocket)
        if gateway_id is None:
            await websocket.send_json(
                {"type": "error", "data": {"message": "ADMIN role required"}}
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        engine = websocket.app.state.engine
        accepted, reason = await engine.authenticate(
            gateway_id,
            timeout=websocket.app.state.config.timeouts.engine_auth_sec,
        )
        if not accepted:
            await websocket.send_json({"type": "error", "data": {"message": reason}})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        role = await engine.resolve_role(
            gateway_id, websocket.app.state.config.timeouts.engine_reply_sec
        )
        if role != "ADMIN":
            await websocket.send_json(
                {"type": "error", "data": {"message": "ADMIN role required"}}
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await websocket.send_json({"type": "authenticated"})
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=512)
        engine.add_admin_sink(queue)
        try:
            while True:
                event = await queue.get()
                await websocket.send_json(event)
        finally:
            engine.remove_admin_sink(queue)
    except (WebSocketDisconnect, TimeoutError):
        return


@router.websocket("/market-data")
async def market_data(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        await _authenticate_ws(websocket)
        await websocket.send_json({"type": "authenticated"})
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=512)
        websocket.app.state.engine.add_market_data_sink(queue)
        subscription = Subscription()
        try:
            sender = asyncio.create_task(
                _send_market_data(websocket, queue, subscription)
            )
            receiver = asyncio.create_task(
                _receive_market_controls(websocket, subscription)
            )
            done, pending = await asyncio.wait(
                {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
        finally:
            websocket.app.state.engine.remove_market_data_sink(queue)
    except (WebSocketDisconnect, TimeoutError):
        return


async def _receive_market_controls(
    websocket: WebSocket,
    subscription: Subscription,
) -> None:
    while True:
        try:
            raw = await websocket.receive_json()
        except ValueError as exc:
            await websocket.send_json({"type": "error", "data": {"message": str(exc)}})
            continue
        try:
            control = MarketDataControl.model_validate(raw)
        except ValidationError as exc:
            await websocket.send_json({"type": "error", "data": {"message": str(exc)}})
            continue
        rejected = subscription.apply(control)
        await websocket.send_json(
            {"type": "subscription", "data": subscription.describe(rejected)}
        )


async def _send_market_data(
    websocket: WebSocket,
    queue: asyncio.Queue[dict[str, Any]],
    subscription: Subscription,
) -> None:
    while True:
        event = await queue.get()
        event_type = str(event.get("type", ""))
        data = event.get("data", {})
        topic_channel = _event_channel(event_type)
        symbol = market_data_symbol(
            _topic_from_event(event), data if isinstance(data, dict) else {}
        )
        # Venue-wide status bypasses the subscription entirely — see
        # ALWAYS_ON_CHANNELS for why, and `describe()["always"]` for how a
        # client learns that it will receive these without asking.
        if topic_channel in ALWAYS_ON_CHANNELS:
            await websocket.send_json(event)
        elif subscription.matches(symbol, topic_channel):
            await websocket.send_json(event)


def _event_channel(event_type: str) -> str | None:
    if event_type == "trade":
        return "trades"
    if event_type == "auction":
        return "auction"
    if event_type in {"book", "depth", "session", "circuit_breaker"}:
        return event_type
    return None


def _topic_from_event(event: dict[str, Any]) -> str:
    event_type = str(event.get("type", ""))
    data = event.get("data", {})
    symbol = str(data.get("symbol", "")) if isinstance(data, dict) else ""
    if event_type == "book" and symbol:
        return f"book.{symbol}"
    if event_type == "depth" and symbol:
        return f"depth.{symbol}"
    if event_type == "trade":
        return "trade.executed"
    if event_type == "session":
        return "session.state"
    if event_type == "circuit_breaker":
        return "circuit_breaker.event"
    if event_type == "auction" and symbol:
        return f"auction.result.{symbol}"
    return event_type

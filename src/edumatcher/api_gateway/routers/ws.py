"""WebSocket endpoints for private events and public market data."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from edumatcher.api_gateway.events import market_data_symbol
from edumatcher.api_gateway.schemas import MarketDataControl
from edumatcher.api_gateway.sessions import SessionRegistry

router = APIRouter(prefix="/api/v1", tags=["websockets"])


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
        await websocket.send_json({"type": "authenticated", "gateway_id": gateway_id})
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        websocket.app.state.engine.add_sink(gateway_id, queue)
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
        symbols: set[str] = set()
        channels: set[str] = set()
        try:
            sender = asyncio.create_task(
                _send_market_data(websocket, queue, symbols, channels)
            )
            receiver = asyncio.create_task(
                _receive_market_controls(websocket, symbols, channels)
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
    symbols: set[str],
    channels: set[str],
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
        requested_symbols = {symbol.upper() for symbol in control.symbols}
        requested_channels = set(control.channels)
        if control.action == "subscribe":
            symbols.update(requested_symbols)
            channels.update(requested_channels)
        else:
            symbols.difference_update(requested_symbols)
            channels.difference_update(requested_channels)
        await websocket.send_json(
            {
                "type": "subscription",
                "data": {"symbols": sorted(symbols), "channels": sorted(channels)},
            }
        )


async def _send_market_data(
    websocket: WebSocket,
    queue: asyncio.Queue[dict[str, Any]],
    symbols: set[str],
    channels: set[str],
) -> None:
    while True:
        event = await queue.get()
        event_type = str(event.get("type", ""))
        data = event.get("data", {})
        topic_channel = _event_channel(event_type)
        symbol = market_data_symbol(
            _topic_from_event(event), data if isinstance(data, dict) else {}
        )
        if topic_channel in {"session", "circuit_breaker"}:
            await websocket.send_json(event)
        elif topic_channel in channels and (not symbols or symbol in symbols):
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

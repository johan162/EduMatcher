"""Each wait matches its own reply (API gateway review C4).

Quote and symbol-command waits matched on ``symbol``, a field every
concurrent request on that symbol shares, although the acks carry a
per-request ``quote_id`` / ``command_id``. Two requests in flight on one
symbol could each receive the other's verdict.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.api_gateway.engine_client import EngineClient
from edumatcher.models.message import (
    decode,
    make_quote_ack_msg,
    make_symbol_halt_ack_msg,
)
from edumatcher.models.price import clear_tick_registry, register_tick_decimals
from tests.api_gateway_harness import call, make_app

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _symbols_loaded() -> Iterator[None]:
    clear_tick_registry()
    register_tick_decimals("AAPL", 2)
    yield
    clear_tick_registry()


def _engine() -> EngineClient:
    with (
        patch(
            "edumatcher.api_gateway.engine_client.make_pusher",
            return_value=MagicMock(closed=False),
        ),
        patch(
            "edumatcher.api_gateway.engine_client.make_subscriber",
            return_value=MagicMock(),
        ),
    ):
        engine = EngineClient(
            "tcp://127.0.0.1:1", "tcp://127.0.0.1:2", asyncio.get_running_loop()
        )
    engine._authenticated.add("GW01")
    engine._role_cache["GW01"] = "ADMIN"
    return engine


def _sent(engine: EngineClient) -> list[tuple[str, dict[str, Any]]]:
    push: Any = engine._push
    return [decode(c.args[0]) for c in push.send_multipart.call_args_list]


async def _until_sent(engine: EngineClient, count: int) -> None:
    for _ in range(200):
        if len(_sent(engine)) >= count:
            return
        await asyncio.sleep(0.005)
    raise AssertionError("requests never sent")


def _quote(quote_id: str) -> dict[str, Any]:
    return {
        "symbol": "AAPL",
        "bid_price": 187.2,
        "bid_qty": 5,
        "ask_price": 187.3,
        "ask_qty": 5,
        "quote_id": quote_id,
    }


async def test_two_quotes_on_one_symbol_each_get_their_own_ack() -> None:
    engine = _engine()
    app = make_app(engine)
    first = asyncio.create_task(
        call(app, "POST", "/api/v1/quotes?wait=ack", body=_quote("Q-1"))
    )
    await _until_sent(engine, 1)
    second = asyncio.create_task(
        call(app, "POST", "/api/v1/quotes?wait=ack", body=_quote("Q-2"))
    )
    await _until_sent(engine, 2)

    # Answered in reverse order: Q-2 refused, then Q-1 accepted.
    engine._handle_event(
        *decode(make_quote_ack_msg("GW01", "Q-2", False, "crossed", symbol="AAPL"))
    )
    engine._handle_event(
        *decode(make_quote_ack_msg("GW01", "Q-1", True, symbol="AAPL"))
    )
    (_, _, one), (_, _, two) = await asyncio.wait_for(
        asyncio.gather(first, second), timeout=2.0
    )

    assert (one["quote_id"], one["accepted"]) == ("Q-1", True)
    assert (two["quote_id"], two["accepted"]) == ("Q-2", False)


async def test_two_halts_of_one_symbol_each_get_their_own_ack() -> None:
    engine = _engine()
    app = make_app(engine)
    first = asyncio.create_task(call(app, "POST", "/api/v1/admin/symbols/AAPL/halt"))
    await _until_sent(engine, 1)
    second = asyncio.create_task(call(app, "POST", "/api/v1/admin/symbols/AAPL/halt"))
    await _until_sent(engine, 2)
    (_, cmd_1), (_, cmd_2) = _sent(engine)

    engine._handle_event(
        *decode(
            make_symbol_halt_ack_msg(
                "GW01", "AAPL", False, "already halted", command_id=cmd_2["command_id"]
            )
        )
    )
    engine._handle_event(
        *decode(
            make_symbol_halt_ack_msg(
                "GW01", "AAPL", True, command_id=cmd_1["command_id"]
            )
        )
    )
    (status_1, _, _), (status_2, _, body_2) = await asyncio.wait_for(
        asyncio.gather(first, second), timeout=2.0
    )

    assert status_1 == 200
    assert (status_2, body_2["error"]["code"]) == (409, "HALT_REJECTED")

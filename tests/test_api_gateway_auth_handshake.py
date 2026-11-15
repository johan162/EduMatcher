"""The engine handshake survives a late reply (API gateway review H3).

An engine accept that arrived after ``engine_auth_sec`` used to resolve
nothing: the gateway never learnt the id was connected, never heartbeated it,
and its next ``gateway_connect`` was refused as "already connected" for good,
because the engine never expires a session that never heartbeated (L029).
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.api_gateway.engine_client import EngineClient
from edumatcher.models.message import (
    decode,
    make_gateway_connect_msg,
    make_gateway_heartbeat_msg,
    make_symbols_request_msg,
)
from edumatcher.models.generated.system import topic_gateway_auth

pytestmark = pytest.mark.anyio

AUTH = topic_gateway_auth("GW01")


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
        return EngineClient(
            "tcp://127.0.0.1:1", "tcp://127.0.0.1:2", asyncio.get_running_loop()
        )


def _sent_topics(engine: EngineClient) -> list[str]:
    push: Any = engine._push
    return [decode(call.args[0])[0] for call in push.send_multipart.call_args_list]


CONNECT = decode(make_gateway_connect_msg("GW01"))[0]
HEARTBEAT = decode(make_gateway_heartbeat_msg("GW01"))[0]
SYMBOLS_REQUEST = decode(make_symbols_request_msg("GW01"))[0]


async def test_a_late_accept_is_adopted() -> None:
    engine = _engine()

    assert await engine.authenticate("GW01", timeout=0.05) == (
        False,
        "Engine authentication timed out",
    )
    engine._handle_event(AUTH, {"accepted": True, "reason": ""})
    await asyncio.sleep(0)  # done-callbacks run on the next loop tick

    assert "GW01" in engine.active_gateways()
    assert _sent_topics(engine).count(HEARTBEAT) == 1
    # The symbols snapshot is asked for, as after an in-time accept.
    assert SYMBOLS_REQUEST in _sent_topics(engine)


async def test_after_adoption_no_second_connect_is_sent() -> None:
    engine = _engine()
    await engine.authenticate("GW01", timeout=0.05)
    engine._handle_event(AUTH, {"accepted": True, "reason": ""})
    await asyncio.sleep(0)  # done-callbacks run on the next loop tick

    assert await engine.authenticate("GW01", timeout=0.05) == (True, "")
    assert _sent_topics(engine).count(CONNECT) == 1


async def test_a_late_refusal_changes_nothing() -> None:
    engine = _engine()
    await engine.authenticate("GW01", timeout=0.05)
    engine._handle_event(AUTH, {"accepted": False, "reason": "no such gateway"})

    assert "GW01" not in engine.active_gateways()
    await engine.authenticate("GW01", timeout=0.05)
    assert _sent_topics(engine).count(CONNECT) == 2


async def test_no_waiter_is_left_behind() -> None:
    engine = _engine()
    await engine.authenticate("GW01", timeout=0.05)
    engine._handle_event(AUTH, {"accepted": True, "reason": ""})
    await asyncio.sleep(0)  # done-callbacks run on the next loop tick
    assert AUTH not in engine._pending

    other = _engine()
    await other.authenticate("GW01", timeout=0.05)
    await other.authenticate("GW01", timeout=0.05)
    # The second attempt replaced the first one's waiter: one, not two.
    assert len(other._pending[AUTH]) == 1


async def test_a_new_attempt_still_adopts_the_first_connects_accept() -> None:
    """The engine answers the first connect with an accept and the second with
    "already connected"; the accept is what counts."""
    engine = _engine()
    await engine.authenticate("GW01", timeout=0.05)
    attempt = asyncio.create_task(engine.authenticate("GW01", timeout=1.0))
    await asyncio.sleep(0)
    engine._handle_event(AUTH, {"accepted": True, "reason": ""})
    await asyncio.sleep(0)  # done-callbacks run on the next loop tick
    engine._handle_event(
        AUTH, {"accepted": False, "reason": "Gateway already connected: GW01"}
    )

    assert (await attempt)[0] is True
    assert "GW01" in engine.active_gateways()


async def test_an_auth_timeout_is_counted() -> None:
    engine = _engine()
    await engine.authenticate("GW01", timeout=0.05)
    assert engine.engine_timeouts == 1

"""The API gateway tells the engine each ID it holds is still alive, and
forgets an ID the engine has closed so the next request re-authenticates."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.api_gateway.engine_client import EngineClient
from edumatcher.models.message import decode


@pytest.fixture
def client() -> Iterator[EngineClient]:
    loop = asyncio.new_event_loop()
    try:
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
            yield EngineClient("tcp://127.0.0.1:1", "tcp://127.0.0.1:2", loop)
    finally:
        loop.close()


def _sent_topics(client: EngineClient) -> list[str]:
    push = cast(MagicMock, client._push)
    return [decode(c.args[0])[0] for c in push.send_multipart.call_args_list]


def test_send_heartbeat_emits_gateway_heartbeat(client: EngineClient) -> None:
    client.send_heartbeat("GW01")

    push = cast(MagicMock, client._push)
    topic, payload = decode(push.send_multipart.call_args.args[0])
    assert topic == "system.gateway_heartbeat"
    assert payload == {"gateway_id": "GW01", "interval_sec": 60}


def test_gateway_bye_forgets_the_authenticated_id(client: EngineClient) -> None:
    client._authenticated.add("GW01")

    client._handle_event("system.gateway_bye.GW01", {"gateway_id": "GW01"})

    assert "GW01" not in client.active_gateways()

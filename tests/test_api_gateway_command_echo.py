"""Re-published commands must reach no client stream.

`_handle_event` routes by topic and its last branch is a *fallthrough*: any
topic whose suffix names no gateway lands in market data and is fanned out to
every market-data subscriber. Every command topic is a fixed topic with the
gateway id in the payload, not the suffix -- so once the engine began
re-publishing commands for the audit trail, that fallthrough would have
broadcast one trader's order intent, client tag included, to all of them.

The existing comment on the admin branch says exactly this about
`admin.action.`; these tests say it about commands, and would have failed
before the routing branch was added.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.api_gateway.engine_client import EngineClient
from edumatcher.api_gateway.events import COMMAND_TOPICS


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


class TestCommandTopicsAreNotBroadcast:
    @pytest.mark.parametrize(
        "topic",
        ["order.new", "order.cancel", "order.amend", "quote.new", "risk.kill_switch"],
    )
    def test_a_command_reaches_no_market_data_sink(
        self, client: EngineClient, topic: str
    ) -> None:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        client._market_data_sinks.add(queue)
        client._handle_event(
            topic, {"gateway_id": "GW01", "id": "O1", "client_tag": "blotter-88"}
        )
        assert queue.empty()

    def test_a_command_reaches_no_private_sink(self, client: EngineClient) -> None:
        """Not even the sending gateway's: it already knows what it sent, and
        the ack is what answers it."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        client._sinks["GW01"].add(queue)
        client._handle_event("order.new", {"gateway_id": "GW01", "id": "O1"})
        assert queue.empty()

    def test_a_command_reaches_no_admin_sink(self, client: EngineClient) -> None:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        client._admin_sinks.add(queue)
        client._handle_event("order.new", {"gateway_id": "GW01", "id": "O1"})
        assert queue.empty()

    def test_ordinary_market_data_still_flows(self, client: EngineClient) -> None:
        """The guard against a fix that silences everything."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        client._market_data_sinks.add(queue)
        client._handle_event("trade.executed", {"symbol": "AAPL"})
        assert not queue.empty()

    def test_an_ack_still_reaches_its_gateway(self, client: EngineClient) -> None:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        client._sinks["GW01"].add(queue)
        client._handle_event("order.ack.GW01", {"order_id": "O1"})
        assert not queue.empty()


class TestCommandTopicsComeFromTheSpec:
    def test_the_set_is_not_empty(self) -> None:
        assert len(COMMAND_TOPICS) > 20

    def test_it_holds_the_commands_and_the_queries(self) -> None:
        assert {"order.new", "order.cancel", "risk.kill_switch"} <= COMMAND_TOPICS
        assert "book.snapshot_request" in COMMAND_TOPICS

    def test_it_holds_no_published_event(self) -> None:
        """A topic the engine publishes must never be filtered out of client
        streams by this set."""
        for topic in ("trade.executed", "session.state", "index.update"):
            assert topic not in COMMAND_TOPICS

    def test_no_wildcard_topic_is_a_command(self) -> None:
        """The set is matched by equality, so a wildcard entry would silently
        never match and the leak would reopen."""
        assert not any("{" in topic for topic in COMMAND_TOPICS)

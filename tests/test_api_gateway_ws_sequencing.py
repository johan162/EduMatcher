"""Per-topic sequencing, drop visibility, and per-symbol subscriptions.

Three things are pinned here:

* every WS event carries a per-topic ``seq``, so a client can tell a dropped
  event from a quiet market — previously it could not, and neither could the
  operator, because the drop counter was DEBUG-gated;
* the subscription model expresses per-symbol channels, which the flat
  symbols x channels form structurally could not;
* the additions are additive, so a client written against the old envelope
  still works.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.api_gateway.engine_client import EngineClient
from edumatcher.api_gateway.events import envelope
from edumatcher.api_gateway.routers.ws import Subscription
from edumatcher.api_gateway.schemas import ALWAYS_ON_CHANNELS, MarketDataControl


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


def _drain(queue: asyncio.Queue[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def test_envelope_additions_are_additive() -> None:
    """A client written against the previous envelope must keep working."""
    body = envelope("trade.executed", {"symbol": "AAPL"}, seq=7)
    # Unchanged keys, unchanged meanings.
    assert body["type"] == "trade"
    assert body["data"] == {"symbol": "AAPL"}
    assert "ts" in body
    # New keys.
    assert body["topic"] == "trade.executed"
    assert body["seq"] == 7


def test_envelope_without_seq_omits_it() -> None:
    assert "seq" not in envelope("trade.executed", {})


# ---------------------------------------------------------------------------
# Sequencing
# ---------------------------------------------------------------------------


def test_seq_is_monotonic_per_topic(client: EngineClient) -> None:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=64)
    client.add_market_data_sink(queue)

    for _ in range(3):
        client._handle_event("depth.AAPL", {"symbol": "AAPL"})
        client._handle_event("depth.MSFT", {"symbol": "MSFT"})

    events = _drain(queue)
    aapl = [e["seq"] for e in events if e["topic"] == "depth.AAPL"]
    msft = [e["seq"] for e in events if e["topic"] == "depth.MSFT"]
    # Independent counters, each starting at 1 — not one shared counter, which
    # would interleave and look gappy to a client watching only one symbol.
    assert aapl == [1, 2, 3]
    assert msft == [1, 2, 3]


def test_a_dropped_event_still_consumes_its_sequence_number(
    client: EngineClient,
) -> None:
    """This is the property the whole change exists for.

    The queue is bounded and written with put_nowait, so a slow consumer loses
    events. If a dropped event did not consume a sequence number the client
    would see 1,2,3 and conclude nothing was lost.
    """
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2)
    client.add_market_data_sink(queue)

    for _ in range(4):
        client._handle_event("trade.executed", {"symbol": "AAPL"})

    delivered = [e["seq"] for e in _drain(queue)]
    assert delivered == [1, 2], "queue holds 2; the rest are dropped"
    # The next delivery jumps, which is exactly what makes the loss visible.
    client._handle_event("trade.executed", {"symbol": "AAPL"})
    assert _drain(queue)[0]["seq"] == 5


def test_drops_are_counted_outside_debug(
    client: EngineClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Counted with a plain int and logged at WARNING.

    _dbg_count is gated on DEBUG being enabled, so the previous counter was
    absent in a normal run — the loss was invisible from both ends.
    """
    import logging

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
    client.add_market_data_sink(queue)

    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            client._handle_event("trade.executed", {"symbol": "AAPL"})

    assert client.dropped_events["market_data"] == 2
    assert "sink full" in caplog.text


def test_every_sink_sees_the_same_seq_for_one_event(client: EngineClient) -> None:
    """Sequenced once per event, not once per sink."""
    md: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=8)
    admin: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=8)
    client.add_market_data_sink(md)
    client.add_admin_sink(admin)

    client._handle_event("trade.executed", {"symbol": "AAPL"})

    assert _drain(md)[0]["seq"] == _drain(admin)[0]["seq"] == 1


def test_private_topics_are_sequenced_per_gateway(client: EngineClient) -> None:
    """order.ack.GW01 and order.ack.GW02 are different topics, so a gateway's
    own stream is contiguous even though another gateway is also active."""
    q1: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=8)
    client.add_sink("GW01", q1)

    client._handle_event("order.ack.GW01", {"order_id": "A"})
    client._handle_event("order.ack.GW02", {"order_id": "B"})
    client._handle_event("order.ack.GW01", {"order_id": "C"})

    assert [e["seq"] for e in _drain(q1)] == [1, 2]


# ---------------------------------------------------------------------------
# Subscription model
# ---------------------------------------------------------------------------


def _sub(**kwargs: Any) -> MarketDataControl:
    return MarketDataControl.model_validate({"action": "subscribe", **kwargs})


def test_flat_form_still_works() -> None:
    """The original wire form is unchanged for a single control frame."""
    s = Subscription()
    s.apply(_sub(symbols=["AAPL"], channels=["book", "trades"]))
    assert s.matches("AAPL", "book")
    assert s.matches("AAPL", "trades")
    assert not s.matches("MSFT", "book")


def test_empty_symbols_means_every_symbol() -> None:
    s = Subscription()
    s.apply(_sub(channels=["trades"]))
    assert s.matches("AAPL", "trades")
    assert s.matches("ANYTHING", "trades")
    assert not s.matches("AAPL", "depth")


def test_per_symbol_channels_the_flat_form_could_not_express() -> None:
    """The motivating case: overview for everything, depth for one symbol."""
    s = Subscription()
    s.apply(
        _sub(
            items=[
                {"symbols": ["*"], "channels": ["book", "trades"]},
                {"symbols": ["AAPL"], "channels": ["depth"]},
            ]
        )
    )
    assert s.matches("MSFT", "book")
    assert s.matches("AAPL", "depth")
    assert not s.matches("MSFT", "depth"), "depth must not leak to other symbols"


def test_accumulated_subscribes_no_longer_widen_into_a_cross_product() -> None:
    """Behaviour change, deliberately: two flat subscribes used to yield four
    rules because symbols and channels were separate accumulating sets."""
    s = Subscription()
    s.apply(_sub(symbols=["AAPL"], channels=["book"]))
    s.apply(_sub(symbols=["MSFT"], channels=["depth"]))
    assert s.matches("AAPL", "book")
    assert s.matches("MSFT", "depth")
    assert not s.matches("AAPL", "depth")
    assert not s.matches("MSFT", "book")


def test_unsubscribe_removes_only_the_named_pairs() -> None:
    s = Subscription()
    s.apply(_sub(items=[{"symbols": ["AAPL", "MSFT"], "channels": ["book", "depth"]}]))
    s.apply(
        MarketDataControl.model_validate(
            {"action": "unsubscribe", "symbols": ["AAPL"], "channels": ["depth"]}
        )
    )
    assert not s.matches("AAPL", "depth")
    assert s.matches("AAPL", "book")
    assert s.matches("MSFT", "depth")


def test_unsubscribing_a_symbol_under_a_wildcard_is_reported() -> None:
    """Silently continuing to deliver would look like a bug to the client."""
    s = Subscription()
    s.apply(_sub(channels=["trades"]))
    rejected = s.apply(
        MarketDataControl.model_validate(
            {"action": "unsubscribe", "symbols": ["AAPL"], "channels": ["trades"]}
        )
    )
    assert s.matches("AAPL", "trades"), "the wildcard rule still stands"
    assert rejected and rejected[0]["reason"] == "wildcard_still_subscribed"


def test_an_item_with_no_channels_is_rejected_not_ignored() -> None:
    s = Subscription()
    rejected = s.apply(_sub(items=[{"symbols": ["AAPL"], "channels": []}]))
    assert rejected and rejected[0]["reason"] == "no_channels"


def test_symbols_are_case_normalised() -> None:
    s = Subscription()
    s.apply(_sub(symbols=["aapl"], channels=["book"]))
    assert s.matches("AAPL", "book")


def test_ack_reports_items_legacy_fields_and_always_on_channels() -> None:
    s = Subscription()
    s.apply(_sub(items=[{"symbols": ["AAPL"], "channels": ["depth"]}]))
    described = s.describe()

    assert described["items"] == [{"symbols": ["AAPL"], "channels": ["depth"]}]
    # Legacy keys retained so an existing client parsing the ack still works.
    assert described["symbols"] == ["AAPL"]
    assert described["channels"] == ["depth"]
    # And the undocumented always-on behaviour is now discoverable.
    assert described["always"] == list(ALWAYS_ON_CHANNELS)


def test_session_and_circuit_breaker_are_not_subscribable() -> None:
    """They bypass the subscription in _send_market_data; matches() must not
    claim otherwise, or the ack and the delivery would disagree."""
    s = Subscription()
    for channel in ALWAYS_ON_CHANNELS:
        assert not s.matches("AAPL", channel)


def test_nothing_matches_before_any_subscribe() -> None:
    s = Subscription()
    assert not s.matches("AAPL", "book")
    assert not s.matches(None, "trades")
    assert not s.matches("AAPL", None)


def test_control_frame_still_rejects_unknown_fields() -> None:
    """StrictModel: a typo must be an error, not a silent no-op."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MarketDataControl.model_validate(
            {"action": "subscribe", "symbol": "AAPL", "channels": ["book"]}
        )
    with pytest.raises(ValidationError):
        MarketDataControl.model_validate(
            {"action": "subscribe", "items": [{"symbols": ["A"], "channels": ["nope"]}]}
        )


def test_healthz_exposes_drop_counters(client: EngineClient) -> None:
    assert client.dropped_events == {}
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
    client.add_market_data_sink(queue)
    for _ in range(3):
        client._handle_event("trade.executed", {"symbol": "AAPL"})
    # A plain dict of ints, JSON-serialisable straight into /healthz.
    assert client.dropped_events["market_data"] == 2

"""pm-alf-console correlates quote.ack to its request by `quote_id`.

`quote.ack` carries only `quote_id`, `accepted`, `reason`, `bid_order_id` and
`ask_order_id` — no symbol, no prices, no sizes. The console needs all of those
to print the acknowledgement and to seed `quote_leg_cache`, so it remembers the
request it sent and re-attaches the detail when the ack arrives.

It used to pick the request by **send order**. That assumes one ack per
quote.new, in order; ZeroMQ PUB/SUB drops silently once a subscriber falls
behind, and a single lost ack leaves the queue permanently off by one — every
later ack then printed another quote's symbol and prices to the operator, and
cached the wrong symbol against real order ids. Matching on the `quote_id` the
console sends cannot desynchronise.

Fixture mirrors test_alf_console_position_query.py: Gateway.__init__ calls
make_subscriber() three times and make_pusher() twice, so each needs its own
mock to tell which socket a call landed on.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch


def _make_gateway(gw_id: str = "GW01"):
    from edumatcher.alf_console.main import Gateway

    fake_push = MagicMock()
    fake_index_push = MagicMock()
    sub_calls = [
        MagicMock(name="sub"),
        MagicMock(name="index_sub"),
        MagicMock(name="dc_sub"),
    ]
    push_calls = [fake_push, fake_index_push]

    with (
        patch(
            "edumatcher.alf_console.main.make_pusher",
            side_effect=lambda _addr: push_calls.pop(0),
        ),
        patch(
            "edumatcher.alf_console.main.make_subscriber",
            side_effect=lambda _addr, *_t: sub_calls.pop(0),
        ),
    ):
        gw = Gateway(gw_id)
    return gw, fake_push


def _quote(gw, symbol: str, bid: float, ask: float, qty: int = 100) -> str:
    """Send one QUOTE and return the quote_id the console minted for it."""
    before = set(gw._pending_quote_by_id)
    gw._send_quote(
        {
            "SYM": symbol,
            "BID": str(bid),
            "ASK": str(ask),
            "BID_QTY": str(qty),
            "ASK_QTY": str(qty),
        }
    )
    new = set(gw._pending_quote_by_id) - before
    assert len(new) == 1, "one quote sent should index exactly one id"
    return new.pop()


def _ack(quote_id: str, bid_order_id: str, ask_order_id: str) -> dict[str, Any]:
    return {
        "accepted": True,
        "quote_id": quote_id,
        "bid_order_id": bid_order_id,
        "ask_order_id": ask_order_id,
    }


class TestQuoteAckCorrelation:
    def test_the_console_sends_a_quote_id_even_when_the_operator_gives_none(
        self,
    ) -> None:
        gw, push = _make_gateway()
        _quote(gw, "AAPL", 99.0, 101.0)

        import json

        frames = push.send_multipart.call_args[0][0]
        payload = json.loads(frames[1])
        assert payload["quote_id"], "quote.new must carry an id to correlate on"
        assert payload["symbol"] == "AAPL"

    def test_an_operator_supplied_quote_id_is_preserved(self) -> None:
        gw, push = _make_gateway()
        gw._send_quote(
            {
                "SYM": "AAPL",
                "BID": "99.0",
                "ASK": "101.0",
                "BID_QTY": "100",
                "ASK_QTY": "100",
                "QUOTE_ID": "my-own-id",
            }
        )
        import json

        payload = json.loads(push.send_multipart.call_args[0][0][1])
        assert payload["quote_id"] == "my-own-id"
        assert "my-own-id" in gw._pending_quote_by_id

    def test_ack_is_matched_by_id_when_an_earlier_ack_is_lost(self) -> None:
        """The failure the send-order queue could not survive."""
        gw, _push = _make_gateway()
        q_aapl = _quote(gw, "AAPL", 99.0, 101.0, qty=100)
        _ = _quote(gw, "MSFT", 49.0, 51.0, qty=200)  # q_msft deliberately ignored
        q_tsla = _quote(gw, "TSLA", 199.0, 201.0, qty=300)

        # MSFT's ack never arrives.
        gw._handle_event("quote.ack.GW01", _ack(q_aapl, "bid-aapl", "ask-aapl"))
        gw._handle_event("quote.ack.GW01", _ack(q_tsla, "bid-tsla", "ask-tsla"))

        # TSLA's legs must be cached against TSLA, not MSFT.
        assert gw.quote_leg_cache["bid-tsla"]["symbol"] == "TSLA"
        assert gw.quote_leg_cache["ask-tsla"]["symbol"] == "TSLA"
        assert gw.quote_leg_cache["bid-aapl"]["symbol"] == "AAPL"
        # Nothing was cached under MSFT — it never got an ack.
        assert not any(
            entry.get("symbol") == "MSFT" for entry in gw.quote_leg_cache.values()
        )

    def test_out_of_order_acks_land_on_the_right_symbols(self) -> None:
        gw, _push = _make_gateway()
        q_aapl = _quote(gw, "AAPL", 99.0, 101.0)
        q_msft = _quote(gw, "MSFT", 49.0, 51.0)

        # Acked in reverse order — send order would swap them.
        gw._handle_event("quote.ack.GW01", _ack(q_msft, "bid-msft", "ask-msft"))
        gw._handle_event("quote.ack.GW01", _ack(q_aapl, "bid-aapl", "ask-aapl"))

        assert gw.quote_leg_cache["bid-msft"]["symbol"] == "MSFT"
        assert gw.quote_leg_cache["bid-aapl"]["symbol"] == "AAPL"

    def test_an_ack_with_an_unknown_id_falls_back_to_send_order(self) -> None:
        """A quote sent by some other means, or an engine-minted id."""
        gw, _push = _make_gateway()
        _quote(gw, "AAPL", 99.0, 101.0)

        gw._handle_event(
            "quote.ack.GW01", _ack("an-id-this-console-never-sent", "bid-x", "ask-x")
        )

        # Fell back to the one outstanding request, so the symbol is still right.
        assert gw.quote_leg_cache["bid-x"]["symbol"] == "AAPL"

    def test_unmatched_ack_is_counted_under_debug_logging(self) -> None:
        """`_dbg_count` is a deliberate no-op unless DEBUG is enabled, so the
        counter has to be observed with the logger turned up — same contract
        as TestDebugCountInfrastructure in test_clearing_advanced_integration.
        """
        gw, _push = _make_gateway()
        _quote(gw, "AAPL", 99.0, 101.0)

        console_logger = logging.getLogger("edumatcher.alf_console.main")
        previous = console_logger.level
        console_logger.setLevel(logging.DEBUG)
        try:
            gw._handle_event(
                "quote.ack.GW01", _ack("an-id-never-sent", "bid-y", "ask-y")
            )
            assert gw._debug_counts.get("quote_ack_unmatched_id", 0) == 1
        finally:
            console_logger.setLevel(previous)

    def test_a_matched_ack_does_not_raise_the_unmatched_counter(self) -> None:
        gw, _push = _make_gateway()
        qid = _quote(gw, "AAPL", 99.0, 101.0)

        console_logger = logging.getLogger("edumatcher.alf_console.main")
        previous = console_logger.level
        console_logger.setLevel(logging.DEBUG)
        try:
            gw._handle_event("quote.ack.GW01", _ack(qid, "bid-z", "ask-z"))
            assert gw._debug_counts.get("quote_ack_unmatched_id", 0) == 0
        finally:
            console_logger.setLevel(previous)

    def test_matching_by_id_consumes_the_fallback_entry_too(self) -> None:
        """Otherwise a later id-less ack would pair against a stale request."""
        gw, _push = _make_gateway()
        q_aapl = _quote(gw, "AAPL", 99.0, 101.0)
        _quote(gw, "MSFT", 49.0, 51.0)

        gw._handle_event("quote.ack.GW01", _ack(q_aapl, "bid-aapl", "ask-aapl"))

        # AAPL's request is gone from both structures; MSFT's remains.
        assert len(gw._pending_quote_requests) == 1
        assert gw._pending_quote_requests[0]["symbol"] == "MSFT"

    def test_the_pending_index_is_bounded(self) -> None:
        gw, _push = _make_gateway()
        for i in range(gw._pending_quote_cap * 3):
            _quote(gw, "AAPL", 99.0 + (i % 5) * 0.01, 101.0 + (i % 5) * 0.01)

        assert len(gw._pending_quote_by_id) <= gw._pending_quote_cap

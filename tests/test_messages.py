"""
Tests for models/message.py — all encode/decode helpers.
"""

from __future__ import annotations

from edumatcher.models.message import (
    decode,
    encode,
    make_amended_msg,
    make_auction_result_msg,
    make_book_msg,
    make_book_snapshot_request_msg,
    make_cancelled_msg,
    make_combo_ack_msg,
    make_combo_cancel_msg,
    make_combo_order_msg,
    make_combo_status_msg,
    make_eod_msg,
    make_expired_msg,
    make_fill_msg,
    make_gateway_auth_msg,
    make_gateway_connect_msg,
    make_gateway_disconnect_msg,
    make_ack_msg,
    make_circuit_breaker_halt_all_ack_msg,
    make_circuit_breaker_halt_all_msg,
    make_circuit_breaker_resume_all_ack_msg,
    make_circuit_breaker_resume_all_msg,
    make_kill_switch_ack_msg,
    make_kill_switch_msg,
    make_depth_msg,
    make_index_constituent_change_ack_msg,
    make_index_constituent_change_msg,
    make_index_corp_action_ack_msg,
    make_index_corp_action_msg,
    make_index_error_msg,
    make_index_history_msg,
    make_index_history_request_msg,
    make_index_update_msg,
    make_order_amend_msg,
    make_order_cancel_msg,
    make_order_new_msg,
    make_orders_msg,
    make_orders_request_msg,
    make_session_state_msg,
    make_session_transition_msg,
    make_symbols_msg,
    make_symbols_request_msg,
    make_quote_new_msg,
    make_quote_cancel_msg,
    make_quote_ack_msg,
    make_quote_status_msg,
    make_trade_msg,
    make_oco_order_msg,
    make_oco_cancel_msg,
)
from edumatcher.models.feed_schema import TradeExecutedPayload
from edumatcher.models.generated import system as _gen_system


class TestIndexMessages:
    def test_make_index_update_msg(self) -> None:
        topic, payload = _rt(
            make_index_update_msg(
                index_id="EDU100",
                level=1048.73,
                aggregate_cap=7_350_000_000_000.0,
                divisor=7_007_100_000.0,
                session_state="CONTINUOUS",
                day={"open": 1042.10, "high": 1056.30, "low": 1040.05},
            )
        )
        assert topic == "index.update"
        assert payload["index_id"] == "EDU100"
        assert payload["session_state"] == "CONTINUOUS"
        assert payload["day"] == {
            "open": 1042.10,
            "high": 1056.30,
            "low": 1040.05,
        }

    def test_make_index_update_msg_omits_the_day_when_there_is_none(self) -> None:
        """Before the session's first level there is no open, high or low.

        The three used to be flat keys under one ``if day_open is not None``
        guard; they are one nullable record in 5.2e, so the absence is a
        single fact rather than a convention three keys had to keep (design
        section 16.2).
        """
        _topic, payload = _rt(
            make_index_update_msg(
                index_id="EDU100",
                level=1048.73,
                aggregate_cap=7_350_000_000_000.0,
                divisor=7_007_100_000.0,
                session_state="PRE_OPEN",
            )
        )
        assert "day" not in payload
        assert "day_open" not in payload

    def test_make_index_history_request_msg(self) -> None:
        topic, payload = _rt(
            make_index_history_request_msg(
                gateway_id="GW01",
                index_id="EDU100",
                from_ts=1000.0,
                to_ts=2000.0,
                types=["INIT", "CORP_ACTION"],
            )
        )
        assert topic == "index.history_request"
        assert payload["gateway_id"] == "GW01"
        assert payload["index_id"] == "EDU100"

    def test_make_index_history_request_msg_omits_types_by_default(self) -> None:
        """The default is the server's, and is no longer copied client-side.

        This asserted a hard-coded four-type set until 5.2f, and the set was
        wrong: pm-index's own default is ``sorted(STRUCTURAL_RECORD_TYPES)``,
        which also contains REBALANCE. Every caller taking the builder's
        default therefore silently never saw a rebalance record (design
        section 20.4). Omitting the key means the server applies its own
        default and the two cannot part again.

        The original intent — never ask for LEVEL/EOD, which pm-index no
        longer stores — now holds structurally: the server's default is drawn
        from STRUCTURAL_RECORD_TYPES, which contains neither.
        """
        from edumatcher.index.history import STRUCTURAL_RECORD_TYPES

        _topic, payload = _rt(
            make_index_history_request_msg(
                gateway_id="GW01",
                index_id="EDU100",
                from_ts=1000.0,
                to_ts=2000.0,
            )
        )
        assert "types" not in payload
        assert "LEVEL" not in STRUCTURAL_RECORD_TYPES
        assert "EOD" not in STRUCTURAL_RECORD_TYPES
        assert "REBALANCE" in STRUCTURAL_RECORD_TYPES

    def test_make_index_history_msg(self) -> None:
        topic, payload = _rt(
            make_index_history_msg(
                gateway_id="GW01",
                index_id="EDU100",
                records=[{"type": "CORP_ACTION", "timestamp": 1.0}],
            )
        )
        assert topic == "index.history.GW01"
        assert payload["index_id"] == "EDU100"
        assert len(payload["records"]) == 1

    def test_make_index_corp_action_msg(self) -> None:
        topic, payload = _rt(
            make_index_corp_action_msg(
                action="SPLIT",
                index_id="EDU100",
                symbol="AAPL",
                gateway_id="GW_ADMIN",
                params={"ratio_numerator": 2, "ratio_denominator": 1},
            )
        )
        assert topic == "index.corp_action"
        assert payload["action"] == "SPLIT"
        assert payload["ratio_numerator"] == 2

    def test_make_index_constituent_change_msg(self) -> None:
        topic, payload = _rt(
            make_index_constituent_change_msg(
                change_type="ADD",
                index_id="EDU100",
                symbol="AMZN",
                gateway_id="GW_ADMIN",
                shares_outstanding=10,
                initial_price=195.0,
            )
        )
        assert topic == "index.constituent_change"
        assert payload["change_type"] == "ADD"
        assert payload["symbol"] == "AMZN"

    def test_make_index_ack_and_error_msgs(self) -> None:
        topic1, payload1 = _rt(
            make_index_corp_action_ack_msg(
                gateway_id="GW_ADMIN",
                accepted=True,
                index_id="EDU100",
                level=1000.0,
                divisor=10.0,
            )
        )
        assert topic1 == "index.corp_action_ack.GW_ADMIN"
        assert payload1["accepted"] is True

        topic2, payload2 = _rt(
            make_index_constituent_change_ack_msg(
                gateway_id="GW_ADMIN",
                accepted=False,
                reason="bad",
                index_id="EDU100",
            )
        )
        assert topic2 == "index.constituent_change_ack.GW_ADMIN"
        assert payload2["accepted"] is False
        assert payload2["reason"] == "bad"

        topic3, payload3 = _rt(make_index_error_msg("GW_ADMIN", "oops"))
        assert topic3 == "index.error.GW_ADMIN"
        assert payload3["reason"] == "oops"


def _rt(frames: list[bytes]) -> tuple[str, dict]:
    """Round-trip: encode then decode."""
    return decode(frames)


def _depth_payload() -> dict:
    """A full ``depth`` payload, as ``OrderBook.depth_snapshot`` produces it."""
    return {
        "symbol": "AAPL",
        "mid_price_ticks": 9525,
        "mid_price": 95.25,
        "tolerance_ticks": 100,
        "bid_depth": 150,
        "ask_depth": 80,
        "imbalance": 0.3,
        "microprice": 95.3,
        "cost_to_move": 7620.0,
    }


class TestEncodeDecodeRoundtrip:
    def test_encode_decode_basic(self) -> None:
        frames = encode("my.topic", {"key": "value", "n": 42})
        topic, payload = decode(frames)
        assert topic == "my.topic"
        assert payload == {"key": "value", "n": 42}

    def test_encode_produces_two_frames(self) -> None:
        frames = encode("t", {})
        assert len(frames) == 2
        assert frames[0] == b"t"

    def test_decode_empty_payload(self) -> None:
        frames = encode("t", {})
        _, payload = decode(frames)
        assert payload == {}


class TestOrderMessages:
    def test_make_order_new_msg(self) -> None:
        d = {"symbol": "AAPL", "side": "BUY"}
        topic, payload = _rt(make_order_new_msg(d))
        assert topic == "order.new"
        assert payload["symbol"] == "AAPL"

    def test_make_order_cancel_msg(self) -> None:
        topic, payload = _rt(make_order_cancel_msg("ORD1", "GW01"))
        assert topic == "order.cancel"
        assert payload["order_id"] == "ORD1"
        assert payload["gateway_id"] == "GW01"

    def test_make_order_amend_msg_price_and_qty(self) -> None:
        topic, payload = _rt(make_order_amend_msg("ORD1", "GW01", price=150.0, qty=200))
        assert topic == "order.amend"
        assert payload["price"] == 150.0
        assert payload["qty"] == 200

    def test_make_order_amend_msg_price_only(self) -> None:
        _, payload = _rt(make_order_amend_msg("ORD1", "GW01", price=99.0))
        assert "price" in payload
        assert "qty" not in payload

    def test_make_order_amend_msg_qty_only(self) -> None:
        _, payload = _rt(make_order_amend_msg("ORD1", "GW01", qty=50))
        assert "qty" in payload
        assert "price" not in payload

    def test_make_amended_msg(self) -> None:
        topic, payload = _rt(make_amended_msg("GW01", "ORD1", 150.0, 100, 80, True))
        assert topic == "order.amended.GW01"
        assert payload["price"] == 150.0
        assert payload["priority_reset"] is True

    def test_make_ack_msg_rejected(self) -> None:
        topic, payload = _rt(make_ack_msg("GW01", "ORD1", False, "bad symbol"))
        assert topic == "order.ack.GW01"
        assert payload["accepted"] is False
        assert payload["reason"] == "bad symbol"

    def test_make_ack_msg_with_order(self) -> None:
        order = {
            "symbol": "AAPL",
            "side": "BUY",
            "order_type": "LIMIT",
            "tif": "DAY",
            "quantity": 100,
            "price": 150.0,
        }
        topic, payload = _rt(make_ack_msg("GW01", "ORD1", True, order=order))
        assert payload["symbol"] == "AAPL"
        assert payload["qty"] == 100

    def test_make_fill_msg(self) -> None:
        topic, payload = _rt(make_fill_msg("GW01", "ORD1", 50, 150.0, 50, "PARTIAL"))
        assert topic == "order.fill.GW01"
        assert payload["fill_qty"] == 50
        assert payload["fill_price"] == 150.0

    def test_make_fill_msg_with_order(self) -> None:
        order = {
            "symbol": "AAPL",
            "side": "BUY",
            "order_type": "LIMIT",
            "tif": "DAY",
            "quantity": 100,
            "price": 150.0,
        }
        _, payload = _rt(
            make_fill_msg("GW01", "ORD1", 100, 150.0, 0, "FILLED", order=order)
        )
        assert payload["symbol"] == "AAPL"

    def test_make_cancelled_msg(self) -> None:
        topic, payload = _rt(make_cancelled_msg("GW01", "ORD1"))
        assert topic == "order.cancelled.GW01"
        assert payload["order_id"] == "ORD1"

    def test_make_expired_msg(self) -> None:
        topic, payload = _rt(make_expired_msg("GW02", "ORD99"))
        assert topic == "order.expired.GW02"
        assert payload["order_id"] == "ORD99"


class TestSystemMessages:
    def test_make_gateway_connect_msg(self) -> None:
        topic, payload = _rt(make_gateway_connect_msg("GW01"))
        assert topic == "system.gateway_connect"
        assert payload["gateway_id"] == "GW01"

    def test_make_gateway_auth_accepted(self) -> None:
        topic, payload = _rt(make_gateway_auth_msg("GW01", True, description="Test GW"))
        assert topic == "system.gateway_auth.GW01"
        assert payload["accepted"] is True
        assert payload["description"] == "Test GW"

    def test_make_gateway_auth_rejected(self) -> None:
        topic, payload = _rt(make_gateway_auth_msg("GW01", False, reason="not allowed"))
        assert payload["accepted"] is False
        assert payload["reason"] == "not allowed"

    def test_make_symbols_request_msg(self) -> None:
        topic, payload = _rt(make_symbols_request_msg("GW01"))
        assert topic == "system.symbols_request"
        assert payload["gateway_id"] == "GW01"

    def test_make_symbols_msg(self) -> None:
        topic, payload = _rt(
            make_symbols_msg(
                "GW01",
                [
                    {"symbol": "AAPL", "tick_decimals": 2},
                    {"symbol": "MSFT", "tick_decimals": 2},
                ],
            )
        )
        assert topic == "system.symbols.GW01"
        assert [e["symbol"] for e in payload["symbols"]] == ["AAPL", "MSFT"]

    def test_symbols_carries_its_metadata_inline(self) -> None:
        """One collection, not two.

        `symbols` was a list of strings beside a `symbol_meta` map keyed by
        those same strings. Each entry now carries its own symbol, so the two
        can no longer disagree about which instruments exist.
        """
        _topic, payload = _rt(
            make_symbols_msg(
                "GW01",
                [{"symbol": "AAPL", "tick_decimals": 2, "mm_max_spread_ticks": 10}],
            )
        )
        assert payload["symbols"] == [
            {"symbol": "AAPL", "tick_decimals": 2, "mm_max_spread_ticks": 10}
        ]
        assert "symbol_meta" not in payload

    def test_make_orders_request_msg(self) -> None:
        topic, payload = _rt(make_orders_request_msg("GW01"))
        assert topic == "order.orders_request"

    def test_make_orders_msg(self) -> None:
        topic, payload = _rt(make_orders_msg("GW01", [{"id": "O1"}]))
        assert topic == "order.orders.GW01"
        assert len(payload["orders"]) == 1

    def test_make_eod_msg(self) -> None:
        topic, payload = _rt(
            make_eod_msg(
                [{"symbol": "AAPL", "tick_decimals": 2, "bids": [], "asks": []}]
            )
        )
        assert topic == "system.eod"
        assert len(payload["books"]) == 1

    def test_make_eod_msg_matches_the_generated_record(self) -> None:
        topic, payload = _rt(
            make_eod_msg(
                [
                    {
                        "symbol": "AAPL",
                        "tick_decimals": 2,
                        "last_price": 150.75,
                        "bids": [{"price": 150.7, "qty": 10, "count": 1}],
                        "asks": [{"price": 150.8, "qty": 12, "count": 1}],
                    }
                ]
            )
        )
        typed = _gen_system.Eod.from_dict(payload)
        assert topic == "system.eod"
        assert typed.books[0].symbol == "AAPL"
        assert typed.books[0].last_price == 150.75

    def test_make_book_snapshot_request_msg(self) -> None:
        topic, payload = _rt(make_book_snapshot_request_msg("AAPL"))
        assert topic == "book.snapshot_request"
        assert payload["symbol"] == "AAPL"


class TestMarketDataMessages:
    def test_make_trade_msg(self) -> None:
        topic, payload = _rt(
            make_trade_msg(
                {
                    "id": "1",
                    "symbol": "AAPL",
                    "buy_order_id": "B1",
                    "sell_order_id": "S1",
                    "buy_gateway_id": "GW1",
                    "sell_gateway_id": "GW2",
                    "price": 150.0,
                    "tick_decimals": 2,
                    "quantity": 10,
                    "aggressor_side": "BUY",
                    "timestamp": 1_700_000_000.0,
                }
            )
        )
        assert topic == "trade.executed"
        assert payload["price"] == 150.0

    def test_make_trade_msg_matches_feed_schema(self) -> None:
        typed = TradeExecutedPayload(
            id="1",
            symbol="AAPL",
            buy_order_id="B1",
            sell_order_id="S1",
            buy_gateway_id="GW1",
            sell_gateway_id="GW2",
            price=150.75,
            quantity=10,
            aggressor_side="BUY",
            timestamp=1_700_000_000.5,
            tick_decimals=2,
        )
        topic, payload = _rt(make_trade_msg(typed.to_dict()))
        roundtrip = TradeExecutedPayload.from_dict(payload)
        assert topic == "trade.executed"
        assert roundtrip == typed

    def test_make_book_msg(self) -> None:
        # Adoption validates the snapshot, so it must be a full book shape.
        snapshot = {
            "symbol": "AAPL",
            "tick_decimals": 2,
            "bids": [],
            "asks": [],
            "last_price": None,
            "last_qty": None,
            "last_buy_price": None,
            "last_sell_price": None,
            "recent_trades": [],
        }
        topic, payload = _rt(make_book_msg("AAPL", snapshot))
        assert topic == "book.AAPL"
        assert "bids" in payload


class TestSessionMessages:
    def test_make_session_transition_msg(self) -> None:
        topic, payload = _rt(make_session_transition_msg("CONTINUOUS"))
        assert topic == "session.transition"
        assert payload["to_state"] == "CONTINUOUS"

    def test_make_session_state_msg_no_prev(self) -> None:
        topic, payload = _rt(make_session_state_msg("CONTINUOUS"))
        assert topic == "session.state"
        assert "prev_state" not in payload

    def test_make_session_state_msg_with_prev(self) -> None:
        topic, payload = _rt(make_session_state_msg("CONTINUOUS", "OPENING_AUCTION"))
        assert payload["prev_state"] == "OPENING_AUCTION"

    def test_make_session_state_msg_matches_the_generated_class(self) -> None:
        """Was ``SessionStatePayload``, a hand-written copy of what is now
        generated. Keeping both would have been two definitions of one wire
        shape, free to drift."""
        from edumatcher.models.generated.session import SessionState

        topic, payload = _rt(make_session_state_msg("CONTINUOUS", "OPENING_AUCTION"))
        typed = SessionState.from_dict(payload)
        assert topic == "session.state"
        assert typed.state == "CONTINUOUS"
        assert typed.prev_state == "OPENING_AUCTION"

    def test_make_auction_result_msg(self) -> None:
        topic, payload = _rt(
            make_auction_result_msg("AAPL", 150.0, 1000, 5, "BUY", 200, "SCHEDULED")
        )
        assert topic == "auction.result.AAPL"
        assert payload["eq_price"] == 150.0
        assert payload["eq_qty"] == 1000
        # The three uncross origins are otherwise indistinguishable.
        assert payload["reason"] == "SCHEDULED"

    def test_make_auction_result_msg_no_price(self) -> None:
        topic, payload = _rt(
            make_auction_result_msg("AAPL", None, 0, 0, "", 0, "REOPEN")
        )
        assert payload["eq_price"] is None


class TestComboMessages:
    def test_make_combo_order_msg(self) -> None:
        # Adoption routes this through the validating generated builder, so the
        # payload must be a real submission shape (>=2 legs), not a stub.
        combo = {
            "combo_id": "PAIR1",
            "gateway_id": "GW01",
            "combo_type": "AON",
            "tif": "DAY",
            "legs": [
                {
                    "symbol": "AAPL",
                    "side": "BUY",
                    "order_type": "LIMIT",
                    "quantity": 10,
                    "price": 100,
                    "stop_price": None,
                    "smp_action": None,
                },
                {
                    "symbol": "MSFT",
                    "side": "SELL",
                    "order_type": "LIMIT",
                    "quantity": 10,
                    "price": 200,
                    "stop_price": None,
                    "smp_action": None,
                },
            ],
        }
        topic, payload = _rt(make_combo_order_msg(combo))
        assert topic == "order.combo"
        assert payload["combo_id"] == "PAIR1"

    def test_make_combo_cancel_msg(self) -> None:
        topic, payload = _rt(make_combo_cancel_msg("PAIR1", "GW01"))
        assert topic == "order.combo_cancel"
        assert payload["combo_id"] == "PAIR1"

    def test_make_combo_ack_accepted(self) -> None:
        topic, payload = _rt(make_combo_ack_msg("GW01", "PAIR1", True))
        assert topic == "combo.ack.GW01"
        assert payload["accepted"] is True

    def test_make_combo_ack_carries_no_state_dump(self) -> None:
        """The ack used to embed a whole ``ComboOrder.to_dict()``.

        Nothing read it — alf_console, alf_gwy, pm-stats and the api_gateway
        event stream all take only these three keys — and it was the last place
        an index-keyed map reached a wire.
        """
        _topic, payload = _rt(make_combo_ack_msg("GW01", "PAIR1", True))
        assert set(payload) == {"combo_id", "accepted", "reason"}

    def test_make_combo_status_msg(self) -> None:
        topic, payload = _rt(make_combo_status_msg("GW01", "PAIR1", "MATCHED"))
        assert topic == "combo.status.GW01"
        assert payload["status"] == "MATCHED"

    def test_make_combo_status_msg_with_a_reason(self) -> None:
        """The ``details`` map became a top-level ``reason`` in 6.1a.

        It only ever carried one key, always "reason", and both consumers
        unwrapped it on arrival with ``details.get("reason")``. Design section
        15.4 excludes maps because a spec appearing to need one is describing
        a message that should have been simpler; this was the thinnest
        possible instance.
        """
        _topic, payload = _rt(
            make_combo_status_msg("GW01", "PAIR1", "FAILED", reason="x")
        )
        assert payload["reason"] == "x"
        assert "details" not in payload

    def test_make_combo_status_msg_omits_an_empty_reason(self) -> None:
        """What the old ``if details:`` guard did, said as a presence regime."""
        _topic, payload = _rt(make_combo_status_msg("GW01", "PAIR1", "MATCHED"))
        assert "reason" not in payload


class TestOcoMessages:
    def test_make_oco_order_msg(self) -> None:
        # Adoption validates the OCO pair, so both legs must be present.
        oco = {
            "oco_id": "OCO1",
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quantity": 10,
            "tif": "DAY",
            "leg1": {
                "side": "BUY",
                "order_type": "LIMIT",
                "price": 100,
                "stop_price": None,
                "trail_offset": None,
            },
            "leg2": {
                "side": "BUY",
                "order_type": "STOP",
                "price": None,
                "stop_price": 90,
                "trail_offset": None,
            },
        }
        topic, payload = _rt(make_oco_order_msg(oco))
        assert topic == "order.oco"
        assert payload["oco_id"] == "OCO1"

    def test_make_oco_cancel_msg(self) -> None:
        topic, payload = _rt(make_oco_cancel_msg("OCO1", "GW01"))
        assert topic == "order.oco_cancel"
        assert payload["oco_id"] == "OCO1"
        assert payload["gateway_id"] == "GW01"


class TestMMQuoteAndRiskMessages:
    def test_make_quote_new_msg(self) -> None:
        topic, payload = _rt(
            make_quote_new_msg(
                {
                    "gateway_id": "GW01",
                    "symbol": "AAPL",
                    "bid_price": 100,
                    "bid_qty": 10,
                    "ask_price": 101,
                    "ask_qty": 10,
                    "tif": "DAY",
                }
            )
        )
        assert topic == "quote.new"
        assert payload["symbol"] == "AAPL"

    def test_make_quote_cancel_msg(self) -> None:
        topic, payload = _rt(make_quote_cancel_msg("GW01", "AAPL"))
        assert topic == "quote.cancel"
        assert payload["gateway_id"] == "GW01"

    def test_make_quote_ack_msg(self) -> None:
        topic, payload = _rt(
            make_quote_ack_msg("GW01", "Q1", True, bid_order_id="B1", ask_order_id="S1")
        )
        assert topic == "quote.ack.GW01"
        assert payload["quote_id"] == "Q1"
        assert payload["accepted"] is True

    def test_make_quote_status_msg(self) -> None:
        topic, payload = _rt(make_quote_status_msg("GW01", "Q1", "ACTIVE"))
        assert topic == "quote.status.GW01"
        assert payload["status"] == "ACTIVE"

    def test_make_gateway_disconnect_msg(self) -> None:
        topic, payload = _rt(make_gateway_disconnect_msg("GW01", "shutdown"))
        assert topic == "system.gateway_disconnect"
        assert payload["reason"] == "shutdown"

    def test_gateway_auth_and_bye_match_the_generated_records(self) -> None:
        t1, p1 = _rt(make_gateway_auth_msg("GW01", True, reason="ok", description="d"))
        t2, p2 = _rt(make_gateway_disconnect_msg("GW01", "bye"))
        # gateway_disconnect is inbound (gateway -> engine), while gateway_bye
        # is the PUB broadcast consumed by clearing.
        from edumatcher.models.message import make_gateway_bye_msg

        t3, p3 = _rt(make_gateway_bye_msg("GW01", "bye"))

        auth = _gen_system.GatewayAuth.from_dict(p1)
        bye = _gen_system.GatewayBye.from_dict(p3)
        assert t1 == "system.gateway_auth.GW01"
        assert auth.accepted is True
        assert t2 == "system.gateway_disconnect"
        assert t3 == "system.gateway_bye.GW01"
        assert bye.reason == "bye"

    def test_make_kill_switch_msg(self) -> None:
        topic, payload = _rt(make_kill_switch_msg("GW01", "AAPL"))
        assert topic == "risk.kill_switch"
        assert payload["symbol"] == "AAPL"

    def test_make_kill_switch_ack_msg(self) -> None:
        topic, payload = _rt(
            make_kill_switch_ack_msg(
                "GW01",
                True,
                cancelled_orders=3,
                cancelled_quotes=1,
            )
        )
        assert topic == "risk.kill_switch_ack.GW01"
        assert payload["cancelled_orders"] == 3

    def test_make_circuit_breaker_halt_all_msg(self) -> None:
        topic, payload = _rt(make_circuit_breaker_halt_all_msg("GW01"))
        assert topic == "risk.circuit_breaker_halt_all"
        assert payload["gateway_id"] == "GW01"

    def test_make_circuit_breaker_halt_all_ack_msg(self) -> None:
        topic, payload = _rt(
            make_circuit_breaker_halt_all_ack_msg(
                "GW01",
                True,
                halted_symbols=12,
                cancelled_quotes=8,
            )
        )
        assert topic == "risk.circuit_breaker_halt_all_ack.GW01"
        assert payload["accepted"] is True
        assert payload["halted_symbols"] == 12
        assert payload["cancelled_quotes"] == 8

    def test_make_circuit_breaker_resume_all_msg(self) -> None:
        topic, payload = _rt(make_circuit_breaker_resume_all_msg("GW01"))
        assert topic == "risk.circuit_breaker_resume_all"
        assert payload["gateway_id"] == "GW01"

    def test_make_circuit_breaker_resume_all_ack_msg(self) -> None:
        topic, payload = _rt(
            make_circuit_breaker_resume_all_ack_msg(
                "GW01",
                True,
                resumed_symbols=5,
            )
        )
        assert topic == "risk.circuit_breaker_resume_all_ack.GW01"
        assert payload["accepted"] is True
        assert payload["resumed_symbols"] == 5

    def test_make_depth_msg(self) -> None:
        """Topic must be depth.{symbol}, matching the engine and subscribers.

        It was book.depth.AAPL, which no subscriber listened for — and which
        a `book.` prefix subscription swallows, making pm-stats invent a
        phantom symbol called "depth.AAPL".
        """
        topic, payload = _rt(make_depth_msg("AAPL", _depth_payload()))
        assert topic == "depth.AAPL"
        assert payload["mid_price_ticks"] == 9525

    def test_depth_topic_is_not_swallowed_by_a_book_subscription(self) -> None:
        topic, _ = _rt(make_depth_msg("AAPL", _depth_payload()))
        assert not topic.startswith("book.")

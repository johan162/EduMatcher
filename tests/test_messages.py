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
from edumatcher.models.feed_schema import (
    GatewayAuthPayload,
    GatewayByePayload,
    SessionStatePayload,
    SystemEodPayload,
    TradeExecutedPayload,
)


class TestIndexMessages:
    def test_make_index_update_msg(self) -> None:
        topic, payload = _rt(
            make_index_update_msg(
                index_id="EDU100",
                level=1048.73,
                aggregate_cap=7_350_000_000_000.0,
                divisor=7_007_100_000.0,
                session_state="CONTINUOUS",
                day_open=1042.10,
                day_high=1056.30,
                day_low=1040.05,
            )
        )
        assert topic == "index.update"
        assert payload["index_id"] == "EDU100"
        assert payload["session_state"] == "CONTINUOUS"
        assert payload["day_open"] == 1042.10

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

    def test_make_index_history_request_msg_defaults_to_structural_types(self) -> None:
        """pm-index's history is a structural/audit log only — the default
        request must never ask for LEVEL/EOD, which are no longer stored.
        """
        _topic, payload = _rt(
            make_index_history_request_msg(
                gateway_id="GW01",
                index_id="EDU100",
                from_ts=1000.0,
                to_ts=2000.0,
            )
        )
        assert "LEVEL" not in payload["types"]
        assert "EOD" not in payload["types"]
        assert set(payload["types"]) == {
            "INIT",
            "CORP_ACTION",
            "ADD_CONSTITUENT",
            "DELIST",
        }

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
        topic, payload = _rt(make_symbols_msg("GW01", ["AAPL", "MSFT"]))
        assert topic == "system.symbols.GW01"
        assert payload["symbols"] == ["AAPL", "MSFT"]

    def test_make_symbols_msg_with_symbol_meta(self) -> None:
        topic, payload = _rt(
            make_symbols_msg(
                "GW01",
                ["AAPL"],
                symbol_meta={"AAPL": {"tick_size": 0.01, "mm_max_spread_ticks": 10}},
            )
        )
        assert topic == "system.symbols.GW01"
        assert payload["symbols"] == ["AAPL"]
        assert payload["symbol_meta"]["AAPL"]["tick_size"] == 0.01

    def test_make_orders_request_msg(self) -> None:
        topic, payload = _rt(make_orders_request_msg("GW01"))
        assert topic == "order.orders_request"

    def test_make_orders_msg(self) -> None:
        topic, payload = _rt(make_orders_msg("GW01", [{"id": "O1"}]))
        assert topic == "order.orders.GW01"
        assert len(payload["orders"]) == 1

    def test_make_eod_msg(self) -> None:
        topic, payload = _rt(make_eod_msg([{"symbol": "AAPL"}]))
        assert topic == "system.eod"
        assert len(payload["books"]) == 1

    def test_make_eod_msg_matches_feed_schema(self) -> None:
        topic, payload = _rt(
            make_eod_msg(
                [
                    {
                        "symbol": "AAPL",
                        "last_price": 150.75,
                        "bids": [{"price": 150.7, "qty": 10, "count": 1}],
                        "asks": [{"price": 150.8, "qty": 12, "count": 1}],
                    }
                ]
            )
        )
        typed = SystemEodPayload.from_dict(payload)
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
        topic, payload = _rt(make_book_msg("AAPL", {"bids": [], "asks": []}))
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

    def test_make_session_state_msg_matches_feed_schema(self) -> None:
        topic, payload = _rt(make_session_state_msg("CONTINUOUS", "OPENING_AUCTION"))
        typed = SessionStatePayload.from_dict(payload)
        assert topic == "session.state"
        assert typed.state == "CONTINUOUS"
        assert typed.prev_state == "OPENING_AUCTION"

    def test_make_auction_result_msg(self) -> None:
        topic, payload = _rt(
            make_auction_result_msg("AAPL", 150.0, 1000, 5, "BUY", 200)
        )
        assert topic == "auction.result.AAPL"
        assert payload["eq_price"] == 150.0
        assert payload["eq_qty"] == 1000

    def test_make_auction_result_msg_no_price(self) -> None:
        topic, payload = _rt(make_auction_result_msg("AAPL", None, 0, 0, "", 0))
        assert payload["eq_price"] is None


class TestComboMessages:
    def test_make_combo_order_msg(self) -> None:
        topic, payload = _rt(make_combo_order_msg({"combo_id": "PAIR1"}))
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

    def test_make_combo_ack_with_combo(self) -> None:
        topic, payload = _rt(
            make_combo_ack_msg("GW01", "PAIR1", True, combo={"legs": 2})
        )
        assert payload["combo"] == {"legs": 2}

    def test_make_combo_status_msg(self) -> None:
        topic, payload = _rt(make_combo_status_msg("GW01", "PAIR1", "MATCHED"))
        assert topic == "combo.status.GW01"
        assert payload["status"] == "MATCHED"

    def test_make_combo_status_msg_with_details(self) -> None:
        topic, payload = _rt(
            make_combo_status_msg("GW01", "PAIR1", "FAILED", details={"reason": "x"})
        )
        assert payload["details"] == {"reason": "x"}


class TestOcoMessages:
    def test_make_oco_order_msg(self) -> None:
        topic, payload = _rt(make_oco_order_msg({"oco_id": "OCO1"}))
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
            make_quote_new_msg({"gateway_id": "GW01", "symbol": "AAPL"})
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

    def test_gateway_auth_and_bye_match_feed_schema(self) -> None:
        t1, p1 = _rt(make_gateway_auth_msg("GW01", True, reason="ok", description="d"))
        t2, p2 = _rt(make_gateway_disconnect_msg("GW01", "bye"))
        # gateway_disconnect is inbound (gateway -> engine), while gateway_bye
        # is the PUB broadcast consumed by clearing.
        from edumatcher.models.message import make_gateway_bye_msg

        t3, p3 = _rt(make_gateway_bye_msg("GW01", "bye"))

        auth = GatewayAuthPayload.from_dict(p1)
        bye = GatewayByePayload.from_dict(p3)
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
        topic, payload = _rt(make_depth_msg("AAPL", {"bids": [[10000, 10]]}))
        assert topic == "book.depth.AAPL"
        assert payload["bids"][0][0] == 10000

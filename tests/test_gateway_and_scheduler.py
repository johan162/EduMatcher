"""
Tests for Gateway helpers, _SysStdoutProxy, scheduler functions, audit, stats receive.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gateway(gw_id: str = "GW01"):
    from edumatcher.gateway.main import Gateway

    fake_push = MagicMock()
    fake_sub = MagicMock()
    with patch("edumatcher.gateway.main.make_pusher", return_value=fake_push):
        with patch("edumatcher.gateway.main.make_subscriber", return_value=fake_sub):
            gw = Gateway(gw_id)
    return gw


@pytest.fixture
def stats_proc(tmp_path: Path):
    """StatsProcess with fake ZMQ sockets; _conn closed after each test."""
    from edumatcher.stats.main import StatsProcess

    fake_sub = MagicMock()
    fake_push = MagicMock()
    with (
        patch("edumatcher.stats.main.make_subscriber", return_value=fake_sub),
        patch("edumatcher.stats.main.make_pusher", return_value=fake_push),
    ):
        proc = StatsProcess(db_path=tmp_path / "stats.db")
    yield proc
    proc._conn.close()


# ---------------------------------------------------------------------------
# _SysStdoutProxy
# ---------------------------------------------------------------------------


class TestSysStdoutProxy:
    def test_write(self, capsys) -> None:
        from edumatcher.gateway.main import _SysStdoutProxy

        proxy = _SysStdoutProxy()
        proxy.write("hello")
        captured = capsys.readouterr()
        assert "hello" in captured.out

    def test_flush_no_error(self) -> None:
        from edumatcher.gateway.main import _SysStdoutProxy

        proxy = _SysStdoutProxy()
        proxy.flush()  # should not raise

    def test_fileno(self) -> None:
        from edumatcher.gateway.main import _SysStdoutProxy
        import sys

        proxy = _SysStdoutProxy()
        assert proxy.fileno() == sys.stdout.fileno()

    def test_isatty(self) -> None:
        from edumatcher.gateway.main import _SysStdoutProxy

        proxy = _SysStdoutProxy()
        result = proxy.isatty()
        assert isinstance(result, bool)

    def test_encoding(self) -> None:
        from edumatcher.gateway.main import _SysStdoutProxy

        proxy = _SysStdoutProxy()
        assert isinstance(proxy.encoding, str)

    def test_errors(self) -> None:
        from edumatcher.gateway.main import _SysStdoutProxy

        proxy = _SysStdoutProxy()
        assert isinstance(proxy.errors, str)


# ---------------------------------------------------------------------------
# Gateway._kv and _handle_event
# ---------------------------------------------------------------------------


class TestGatewayHelpers:
    def test_kv_parses_pairs(self) -> None:
        from edumatcher.gateway.main import Gateway

        result = Gateway._kv(["SYM=AAPL", "SIDE=BUY", "QTY=100"])
        assert result == {"SYM": "AAPL", "SIDE": "BUY", "QTY": "100"}

    def test_kv_ignores_no_equals(self) -> None:
        from edumatcher.gateway.main import Gateway

        result = Gateway._kv(["BAREWORD", "K=V"])
        assert "BAREWORD" not in result
        assert result["K"] == "V"

    def test_kv_uppercases_keys(self) -> None:
        from edumatcher.gateway.main import Gateway

        result = Gateway._kv(["sym=aapl"])
        assert "SYM" in result

    def test_status_command_prints_summary(self, capsys) -> None:
        gw = _make_gateway()
        gw._known_symbols = ["AAPL"]
        gw.order_cache["ORD-001"] = {
            "status": "NEW",
            "id": "ORD-001",
            "symbol": "AAPL",
            "side": "BUY",
            "type": "LIMIT",
            "tif": "DAY",
            "qty": 100,
            "remaining": 100,
            "price": 150.0,
            "time": "00:00:00",
        }

        gw._parse_and_send("STATUS")

        captured = capsys.readouterr()
        assert "Gateway status" in captured.out
        assert "Use ORDERS for detailed order inspection" in captured.out

    def test_handle_event_ack_accepted(self) -> None:
        gw = _make_gateway()
        order_id = "ORD-001"
        gw.order_cache[order_id] = {"status": "PENDING"}
        gw._handle_event(
            "order.ack.GW01",
            {"order_id": order_id, "accepted": True},
        )
        assert gw.order_cache[order_id]["status"] == "NEW"

    def test_handle_event_ack_rejected(self) -> None:
        gw = _make_gateway()
        order_id = "ORD-002"
        gw.order_cache[order_id] = {"status": "PENDING"}
        gw._handle_event(
            "order.ack.GW01",
            {"order_id": order_id, "accepted": False, "reason": "bad order"},
        )
        assert gw.order_cache[order_id]["status"] == "REJECTED"

    def test_handle_event_fill(self) -> None:
        gw = _make_gateway()
        order_id = "ORD-003"
        gw.order_cache[order_id] = {"remaining": 100, "status": "NEW"}
        gw._handle_event(
            "order.fill.GW01",
            {
                "order_id": order_id,
                "fill_qty": 50,
                "fill_price": 100.0,
                "remaining_qty": 50,
                "status": "PARTIAL",
                "symbol": "AAPL",
                "side": "BUY",
            },
        )
        assert gw.order_cache[order_id]["remaining"] == 50

    def test_handle_event_cancelled(self) -> None:
        gw = _make_gateway()
        order_id = "ORD-004"
        gw.order_cache[order_id] = {"status": "NEW"}
        gw._handle_event("order.cancelled.GW01", {"order_id": order_id})
        assert gw.order_cache[order_id]["status"] == "CANCELLED"

    def test_handle_event_amended(self) -> None:
        gw = _make_gateway()
        order_id = "ORD-005"
        gw.order_cache[order_id] = {"price": 100.0, "qty": 100, "remaining": 100}
        gw._handle_event(
            "order.amended.GW01",
            {
                "order_id": order_id,
                "price": 105.0,
                "qty": 100,
                "remaining_qty": 100,
                "priority_reset": True,
            },
        )
        assert gw.order_cache[order_id]["price"] == 105.0

    def test_handle_event_expired(self) -> None:
        gw = _make_gateway()
        order_id = "ORD-006"
        gw.order_cache[order_id] = {"status": "NEW"}
        gw._handle_event("order.expired.GW01", {"order_id": order_id})
        assert gw.order_cache[order_id]["status"] == "EXPIRED"

    def test_handle_event_symbols(self) -> None:
        gw = _make_gateway()
        gw._handle_event("system.symbols.GW01", {"symbols": ["AAPL", "MSFT"]})
        assert "AAPL" in gw._known_symbols

    def test_handle_event_symbols_empty(self) -> None:
        gw = _make_gateway()
        gw._handle_event("system.symbols.GW01", {"symbols": []})
        assert gw._known_symbols == []

    def test_handle_event_orders(self) -> None:
        gw = _make_gateway()
        import time as _time

        gw._handle_event(
            "order.orders.GW01",
            {
                "orders": [
                    {
                        "id": "ORD-007",
                        "symbol": "AAPL",
                        "side": "BUY",
                        "order_type": "LIMIT",
                        "tif": "DAY",
                        "quantity": 100,
                        "remaining_qty": 100,
                        "price": 150.0,
                        "status": "NEW",
                        "timestamp": _time.time(),
                    }
                ]
            },
        )
        assert "ORD-007" in gw.order_cache

    def test_handle_event_combo_ack_accepted(self) -> None:
        gw = _make_gateway()
        gw._handle_event("combo.ack.GW01", {"combo_id": "C01", "accepted": True})
        # Should not raise

    def test_handle_event_combo_ack_rejected(self) -> None:
        gw = _make_gateway()
        gw._handle_event(
            "combo.ack.GW01",
            {"combo_id": "C01", "accepted": False, "reason": "bad combo"},
        )

    def test_handle_event_combo_status(self) -> None:
        gw = _make_gateway()
        gw._handle_event(
            "combo.status.GW01",
            {"combo_id": "C01", "status": "MATCHED", "details": {}},
        )

    def test_handle_event_combo_status_failed(self) -> None:
        gw = _make_gateway()
        gw._handle_event(
            "combo.status.GW01",
            {"combo_id": "C01", "status": "FAILED", "details": {"reason": "no match"}},
        )

    def test_handle_event_oco_ack_accepted(self) -> None:
        gw = _make_gateway()
        gw._handle_event(
            "oco.ack.GW01",
            {
                "oco_id": "OCO01",
                "accepted": True,
                "order_id_1": "ORD-L1",
                "order_id_2": "ORD-L2",
            },
        )

    def test_handle_event_oco_ack_rejected(self) -> None:
        gw = _make_gateway()
        gw._handle_event(
            "oco.ack.GW01",
            {"oco_id": "OCO01", "accepted": False, "reason": "bad oco"},
        )

    def test_handle_event_oco_cancelled(self) -> None:
        gw = _make_gateway()
        gw._handle_event(
            "oco.cancelled.GW01",
            {
                "oco_id": "OCO01",
                "cancelled_order_id": "ORD-L2-xxx",
                "reason": "sibling filled",
            },
        )

    def test_handle_event_trade_executed(self) -> None:
        gw = _make_gateway()
        gw._handle_event(
            "trade.executed",
            {"symbol": "AAPL", "price": 152.0, "quantity": 100},
        )
        assert gw._last_prices.get("AAPL") == 152.0

    def test_handle_event_quote_ack(self) -> None:
        gw = _make_gateway()
        gw._handle_event(
            "quote.ack.GW01",
            {
                "quote_id": "Q1",
                "accepted": True,
                "bid_order_id": "B1",
                "ask_order_id": "S1",
            },
        )

    def test_handle_event_orders_tracks_quote_legs(self) -> None:
        gw = _make_gateway()
        import time as _time

        gw._handle_event(
            "order.orders.GW01",
            {
                "orders": [
                    {
                        "id": "BID-001",
                        "symbol": "AAPL",
                        "side": "BUY",
                        "order_type": "LIMIT",
                        "tif": "DAY",
                        "quantity": 500,
                        "remaining_qty": 500,
                        "price": 150.0,
                        "status": "NEW",
                        "timestamp": _time.time(),
                        "origin": "QUOTE",
                        "quote_id": "Q123",
                    }
                ]
            },
        )
        assert "BID-001" in gw.quote_leg_cache
        assert gw.quote_leg_cache["BID-001"]["quote_id"] == "Q123"

    def test_handle_event_fill_updates_quote_leg_projection(self) -> None:
        gw = _make_gateway()
        gw._handle_event(
            "quote.ack.GW01",
            {
                "quote_id": "Q123",
                "accepted": True,
                "bid_order_id": "BID-123",
                "ask_order_id": "ASK-123",
            },
        )
        gw._handle_event(
            "order.fill.GW01",
            {
                "order_id": "BID-123",
                "fill_qty": 100,
                "fill_price": 149.9,
                "remaining_qty": 400,
                "status": "PARTIAL",
                "symbol": "AAPL",
                "side": "BUY",
                "qty": 500,
            },
        )
        assert gw.quote_leg_cache["BID-123"]["filled"] == 100
        assert gw.quote_leg_cache["BID-123"]["status"] == "PARTIAL"

    def test_handle_event_quote_status_marks_quote_legs(self) -> None:
        gw = _make_gateway()
        gw._handle_event(
            "quote.ack.GW01",
            {
                "quote_id": "Q900",
                "accepted": True,
                "bid_order_id": "BID-900",
                "ask_order_id": "ASK-900",
            },
        )
        gw._handle_event(
            "quote.status.GW01",
            {"quote_id": "Q900", "status": "CANCELLED", "reason": ""},
        )
        assert gw.quote_leg_cache["BID-900"]["quote_status"] == "CANCELLED"

    def test_handle_event_kill_switch_ack(self) -> None:
        gw = _make_gateway()
        gw._handle_event(
            "risk.kill_switch_ack.GW01",
            {"accepted": True, "cancelled_orders": 2, "cancelled_quotes": 1},
        )


# ---------------------------------------------------------------------------
# Gateway._update_position
# ---------------------------------------------------------------------------


class TestGatewayUpdatePosition:
    def test_buy_from_flat(self) -> None:
        gw = _make_gateway()
        gw._update_position("AAPL", "BUY", 100, 100.0)
        pos = gw._positions["AAPL"]
        assert pos["net_qty"] == 100
        assert pos["avg_cost"] == pytest.approx(100.0)

    def test_sell_from_flat(self) -> None:
        gw = _make_gateway()
        gw._update_position("AAPL", "SELL", 100, 100.0)
        pos = gw._positions["AAPL"]
        assert pos["net_qty"] == -100

    def test_close_long_position_realizes_pnl(self) -> None:
        gw = _make_gateway()
        gw._update_position("AAPL", "BUY", 100, 100.0)
        gw._update_position("AAPL", "SELL", 100, 110.0)
        pos = gw._positions["AAPL"]
        assert pos["net_qty"] == 0
        assert pos["realized_pnl"] == pytest.approx(1000.0)

    def test_close_short_position_realizes_pnl(self) -> None:
        gw = _make_gateway()
        gw._update_position("AAPL", "SELL", 100, 110.0)
        gw._update_position("AAPL", "BUY", 100, 100.0)
        pos = gw._positions["AAPL"]
        assert pos["realized_pnl"] == pytest.approx(1000.0)

    def test_zero_avg_cost_on_flat(self) -> None:
        gw = _make_gateway()
        gw._update_position("AAPL", "BUY", 100, 100.0)
        gw._update_position("AAPL", "SELL", 100, 100.0)
        assert gw._positions["AAPL"]["avg_cost"] == 0.0

    def test_flip_through_zero(self) -> None:
        gw = _make_gateway()
        gw._update_position("AAPL", "BUY", 100, 100.0)
        # Sell 300 → flip to -200 (flipped through zero, abs(new) > abs(old))
        gw._update_position("AAPL", "SELL", 300, 105.0)
        pos = gw._positions["AAPL"]
        assert pos["net_qty"] == -200
        # After flip where abs(new_qty) > abs(old_qty), avg_cost = fill price
        assert pos["avg_cost"] == pytest.approx(105.0)

    def test_add_to_long_updates_avg_cost(self) -> None:
        gw = _make_gateway()
        gw._update_position("AAPL", "BUY", 100, 100.0)
        gw._update_position("AAPL", "BUY", 100, 110.0)
        pos = gw._positions["AAPL"]
        assert pos["net_qty"] == 200
        assert pos["avg_cost"] == pytest.approx(105.0)

    def test_print_positions_with_active(self) -> None:
        gw = _make_gateway()
        gw._update_position("AAPL", "BUY", 100, 100.0)
        gw._last_prices["AAPL"] = 105.0
        # Should not raise
        gw._print_positions()

    def test_print_positions_with_flat_realized(self) -> None:
        gw = _make_gateway()
        gw._update_position("AAPL", "BUY", 100, 100.0)
        gw._update_position("AAPL", "SELL", 100, 110.0)
        # position is flat but realized_pnl != 0
        gw._print_positions()

    def test_print_positions_empty(self) -> None:
        gw = _make_gateway()
        gw._print_positions()


# ---------------------------------------------------------------------------
# Gateway._parse_and_send
# ---------------------------------------------------------------------------


class TestGatewayParseAndSend:
    def test_help_command(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("HELP")  # Should not raise

    def test_exit_sets_running_false(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("EXIT")
        assert gw._running is False

    def test_quit_sets_running_false(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("QUIT")
        assert gw._running is False

    def test_pos_command(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("POS")  # Calls _print_positions — should not raise

    def test_orders_command(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("ORDERS")  # Calls _print_orders — should not raise

    def test_qlegs_command(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("QLEGS|SHOW=ALL")  # should not raise

    def test_qlegs_invalid_show(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("QLEGS|SHOW=INVALID")  # validation error path

    def test_symbols_command(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("SYMBOLS")
        assert gw.push_sock.send_multipart.called

    def test_quote_command(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "QUOTE|SYM=AAPL|BID=149.50|ASK=150.50|BID_QTY=100|ASK_QTY=120|TIF=DAY"
        )
        assert gw.push_sock.send_multipart.called

    def test_quote_cancel_command(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("QUOTE_CANCEL|SYM=AAPL")
        assert gw.push_sock.send_multipart.called

    def test_kill_command(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("KILL|SYM=AAPL")
        assert gw.push_sock.send_multipart.called

    def test_cancel_by_id(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("CANCEL|ID=ORD-001")
        assert gw.push_sock.send_multipart.called

    def test_cancel_missing_id(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("CANCEL")  # No ID — prints error, no send

    def test_cancel_by_combo_id(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("CANCEL|COMBO_ID=C01")
        assert gw.push_sock.send_multipart.called

    def test_cancel_by_oco_id(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("CANCEL|OCO_ID=OCO01")
        assert gw.push_sock.send_multipart.called

    def test_amend_price(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("AMEND|ID=ORD-001|PRICE=105.00")
        assert gw.push_sock.send_multipart.called

    def test_amend_missing_id(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("AMEND|PRICE=105.00")  # No ID — error

    def test_amend_no_fields(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("AMEND|ID=ORD-001")  # No PRICE or QTY — error

    def test_new_limit_order(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00")
        assert gw.push_sock.send_multipart.called

    def test_new_combo_order(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "NEW|TYPE=COMBO|COMBO_ID=C01|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=2"
            "|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=150.00|LEG0.TYPE=LIMIT"
            "|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=100|LEG1.PRICE=200.00|LEG1.TYPE=LIMIT"
        )
        # Should attempt send

    def test_new_oco_order(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "NEW|TYPE=OCO|OCO_ID=OCO01|SYM=AAPL|QTY=100|TIF=DAY"
            "|LEG1_SIDE=SELL|LEG1_TYPE=LIMIT|LEG1_PRICE=160.00"
            "|LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=140.00"
        )
        assert gw.push_sock.send_multipart.called

    def test_unknown_command(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("FOOBAR")  # Unknown cmd — prints error

    def test_new_market_order(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100")
        assert gw.push_sock.send_multipart.called

    def test_new_stop_order(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("NEW|SYM=AAPL|SIDE=BUY|TYPE=STOP|QTY=100|STOP=148.00")
        assert gw.push_sock.send_multipart.called

    def test_new_iceberg_order(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "NEW|SYM=AAPL|SIDE=BUY|TYPE=ICEBERG|QTY=1000|PRICE=150.00|VISIBLE=100"
        )
        assert gw.push_sock.send_multipart.called


# ---------------------------------------------------------------------------
# Gateway._send_new validation paths
# ---------------------------------------------------------------------------


class TestGatewaySendNewValidation:
    def test_limit_missing_price(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100")
        # Error: LIMIT requires PRICE=
        gw.push_sock.send_multipart.assert_not_called()

    def test_stop_missing_stop_price(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("NEW|SYM=AAPL|SIDE=BUY|TYPE=STOP|QTY=100")
        gw.push_sock.send_multipart.assert_not_called()

    def test_stop_limit_missing_price(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("NEW|SYM=AAPL|SIDE=BUY|TYPE=STOP_LIMIT|QTY=100|STOP=148.00")
        gw.push_sock.send_multipart.assert_not_called()

    def test_iceberg_missing_visible(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("NEW|SYM=AAPL|SIDE=BUY|TYPE=ICEBERG|QTY=1000|PRICE=150.00")
        gw.push_sock.send_multipart.assert_not_called()

    def test_iceberg_visible_ge_qty(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "NEW|SYM=AAPL|SIDE=BUY|TYPE=ICEBERG|QTY=100|PRICE=150.00|VISIBLE=100"
        )
        gw.push_sock.send_multipart.assert_not_called()

    def test_trailing_stop_missing_trail(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("NEW|SYM=AAPL|SIDE=BUY|TYPE=TRAILING_STOP|QTY=100")
        gw.push_sock.send_multipart.assert_not_called()

    def test_parse_error_bad_side(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("NEW|SYM=AAPL|SIDE=INVALID|TYPE=LIMIT|QTY=100|PRICE=150.00")
        gw.push_sock.send_multipart.assert_not_called()


# ---------------------------------------------------------------------------
# Gateway._send_oco validation paths
# ---------------------------------------------------------------------------


class TestGatewaySendOCO:
    def test_oco_missing_oco_id(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "NEW|TYPE=OCO|SYM=AAPL|QTY=100"
            "|LEG1_SIDE=SELL|LEG1_TYPE=LIMIT|LEG1_PRICE=160.00"
            "|LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=140.00"
        )
        gw.push_sock.send_multipart.assert_not_called()

    def test_oco_missing_sym(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "NEW|TYPE=OCO|OCO_ID=OCO01|QTY=100"
            "|LEG1_SIDE=SELL|LEG1_TYPE=LIMIT|LEG1_PRICE=160.00"
            "|LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=140.00"
        )
        gw.push_sock.send_multipart.assert_not_called()

    def test_oco_missing_legs(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("NEW|TYPE=OCO|OCO_ID=OCO01|SYM=AAPL|QTY=100")
        gw.push_sock.send_multipart.assert_not_called()

    def test_oco_bad_qty(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "NEW|TYPE=OCO|OCO_ID=OCO01|SYM=AAPL|QTY=NOTANINT"
            "|LEG1_SIDE=SELL|LEG1_TYPE=LIMIT|LEG1_PRICE=160.00"
            "|LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=140.00"
        )
        gw.push_sock.send_multipart.assert_not_called()


# ---------------------------------------------------------------------------
# Gateway._send_combo validation paths
# ---------------------------------------------------------------------------


class TestGatewaySendCombo:
    def test_combo_missing_combo_id(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "NEW|TYPE=COMBO|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=2"
            "|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=150.00|LEG0.TYPE=LIMIT"
            "|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=100|LEG1.PRICE=200.00|LEG1.TYPE=LIMIT"
        )
        gw.push_sock.send_multipart.assert_not_called()

    def test_combo_bad_leg_count(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "NEW|TYPE=COMBO|COMBO_ID=C01|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=1"
            "|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=150.00|LEG0.TYPE=LIMIT"
        )
        gw.push_sock.send_multipart.assert_not_called()

    def test_combo_bad_combo_type(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "NEW|TYPE=COMBO|COMBO_ID=C01|COMBO_TYPE=INVALID|TIF=DAY|LEG_COUNT=2"
            "|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=150.00|LEG0.TYPE=LIMIT"
            "|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=100|LEG1.PRICE=200.00|LEG1.TYPE=LIMIT"
        )
        gw.push_sock.send_multipart.assert_not_called()

    def test_combo_bad_leg_count_non_int(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "NEW|TYPE=COMBO|COMBO_ID=C01|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=NOTINT"
            "|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=150.00|LEG0.TYPE=LIMIT"
        )
        gw.push_sock.send_multipart.assert_not_called()


# ---------------------------------------------------------------------------
# scheduler/main.py — _run_scheduled and _run_now
# ---------------------------------------------------------------------------


class TestSchedulerRunScheduled:
    def test_all_past_times_skips_all(self) -> None:
        from datetime import datetime as _dt
        from edumatcher.scheduler.main import _run_scheduled

        fake_sock = MagicMock()
        schedule = [("00:00", "PRE_OPEN"), ("01:00", "OPENING_AUCTION")]
        # Pin "now" to noon so both schedule entries are always in the past
        fixed_now = _dt(2000, 1, 1, 12, 0, 0)
        with (
            patch("edumatcher.scheduler.main.time.sleep"),
            patch("edumatcher.scheduler.main.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = fixed_now
            _run_scheduled(fake_sock, schedule)
        # Since all times are past, no messages should be sent
        fake_sock.send_multipart.assert_not_called()

    def test_run_now_sends_all_transitions(self) -> None:
        from edumatcher.scheduler.main import _run_now

        fake_sock = MagicMock()
        with patch("edumatcher.scheduler.main.time.sleep"):
            _run_now(fake_sock)
        assert fake_sock.send_multipart.call_count == 5  # 5 session states


# ---------------------------------------------------------------------------
# audit/main.py — AuditProcess constructors and _receive dispatch
# ---------------------------------------------------------------------------


class TestAuditProcess:
    def test_init_creates_logger(self, tmp_path: Path) -> None:
        from edumatcher.audit.main import AuditProcess

        fake_sub = MagicMock()
        with patch("edumatcher.audit.main.make_subscriber", return_value=fake_sub):
            proc = AuditProcess(log_path=tmp_path / "audit.log", to_terminal=False)
        assert proc.logger is not None

    def test_init_with_terminal_flag(self, tmp_path: Path) -> None:
        from edumatcher.audit.main import AuditProcess

        fake_sub = MagicMock()
        with patch("edumatcher.audit.main.make_subscriber", return_value=fake_sub):
            proc = AuditProcess(log_path=tmp_path / "audit.log", to_terminal=True)
        assert proc.logger is not None

    def test_stop_sets_running_false(self, tmp_path: Path) -> None:
        from edumatcher.audit.main import AuditProcess

        fake_sub = MagicMock()
        with patch("edumatcher.audit.main.make_subscriber", return_value=fake_sub):
            proc = AuditProcess(log_path=tmp_path / "audit.log", to_terminal=False)
        proc._stop()
        assert proc._running is False


# ---------------------------------------------------------------------------
# stats/main.py — remaining receive paths
# ---------------------------------------------------------------------------


class TestStatsReceivePaths:
    def test_on_book_bid_only(self, stats_proc) -> None:
        proc = stats_proc
        payload = {
            "bids": [{"price": 100.0, "qty": 100}],
            "asks": [],
            "last_price": None,
        }
        proc._on_book("AAPL", payload)
        # No ask — should not crash, mid uses bid only

    def test_on_book_ask_only(self, stats_proc) -> None:
        proc = stats_proc
        payload = {
            "bids": [],
            "asks": [{"price": 101.0, "qty": 100}],
            "last_price": None,
        }
        proc._on_book("AAPL", payload)

    def test_on_eod_empty_books(self, stats_proc) -> None:
        proc = stats_proc
        # Add some accumulator data first
        proc._accum_for("AAPL")
        proc._on_eod({"books": []})
        # Should not crash

    def test_on_eod_with_books(self, stats_proc) -> None:
        proc = stats_proc
        proc._on_eod(
            {
                "books": [
                    {
                        "symbol": "AAPL",
                        "bids": [{"price": 150.0, "qty": 100}],
                        "asks": [{"price": 151.0, "qty": 100}],
                    }
                ]
            }
        )

    def test_stop_sets_running_false(self, stats_proc) -> None:
        proc = stats_proc
        proc._stop()
        assert proc._running is False


# ---------------------------------------------------------------------------
# Additional gateway coverage
# ---------------------------------------------------------------------------


class TestGatewayPrintOrders:
    def test_print_orders_empty(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "ORDERS"
        )  # Empty cache — should print "No outstanding orders"

    def test_print_orders_with_entries(self) -> None:
        gw = _make_gateway()
        gw.order_cache["ORD-001"] = {
            "id": "ORD-001",
            "symbol": "AAPL",
            "side": "BUY",
            "type": "LIMIT",
            "tif": "DAY",
            "qty": 100,
            "remaining": 100,
            "price": 150.0,
            "status": "NEW",
            "time": "10:00:00",
        }
        gw._parse_and_send("ORDERS")  # Should print table with entry

    def test_oco_with_trail_offset(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "NEW|TYPE=OCO|OCO_ID=OCO02|SYM=AAPL|QTY=100|TIF=DAY"
            "|LEG1_SIDE=SELL|LEG1_TYPE=TRAILING_STOP|LEG1_TRAIL=2.00"
            "|LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=140.00"
        )
        assert gw.push_sock.send_multipart.called

    def test_oco_with_stop_price_in_leg(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "NEW|TYPE=OCO|OCO_ID=OCO03|SYM=AAPL|QTY=100|TIF=DAY"
            "|LEG1_SIDE=SELL|LEG1_TYPE=STOP_LIMIT|LEG1_STOP=155.00|LEG1_PRICE=154.50"
            "|LEG2_SIDE=SELL|LEG2_TYPE=LIMIT|LEG2_PRICE=170.00"
        )
        assert gw.push_sock.send_multipart.called

    def test_combo_sends_successfully(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "NEW|TYPE=COMBO|COMBO_ID=C01|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=2"
            "|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=150.00|LEG0.TYPE=LIMIT"
            "|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=100|LEG1.PRICE=200.00|LEG1.TYPE=LIMIT"
        )
        assert gw.push_sock.send_multipart.called

    def test_combo_leg_missing_sym(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "NEW|TYPE=COMBO|COMBO_ID=C01|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=2"
            "|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=150.00|LEG0.TYPE=LIMIT"
            "|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=100|LEG1.PRICE=200.00|LEG1.TYPE=LIMIT"
        )
        gw.push_sock.send_multipart.assert_not_called()


class TestGatewayCompleterEdgeCases:
    def _completer(self):
        from edumatcher.gateway.main import GatewayCompleter

        return GatewayCompleter(known_symbols=["AAPL", "MSFT"])

    def _document(self, text):
        from prompt_toolkit.document import Document

        return Document(text)

    def test_leg_type_completions(self) -> None:
        completer = self._completer()
        doc = self._document("NEW|TYPE=COMBO|LEG0.TYPE=")
        results = list(completer.get_completions(doc, None))
        texts = [c.text for c in results]
        # LEG{i}.TYPE= should suggest LIMIT, MARKET, etc.
        assert "LIMIT" in texts or "STOP" in texts

    def test_combo_completions_with_leg_count(self) -> None:
        from edumatcher.gateway.main import GatewayCompleter

        result = GatewayCompleter._combo_completions(
            parts=["NEW", "TYPE=COMBO", "LEG_COUNT=3"],
            already_keys={"TYPE", "LEG_COUNT"},
            partial_key="",
        )
        # With LEG_COUNT=3, should suggest LEG0/1/2 fields
        leg_keys = [r for r in result if r.startswith("LEG")]
        assert len(leg_keys) > 0

    def test_combo_completions_invalid_leg_count(self) -> None:
        from edumatcher.gateway.main import GatewayCompleter

        # Invalid LEG_COUNT should default to 2
        result = GatewayCompleter._combo_completions(
            parts=["NEW", "TYPE=COMBO", "LEG_COUNT=INVALID"],
            already_keys={"TYPE", "LEG_COUNT"},
            partial_key="",
        )
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# clearing/main.py — _stop
# ---------------------------------------------------------------------------


class TestClearingStop:
    def test_stop_sets_running_false(self, tmp_path: Path) -> None:
        from edumatcher.clearing.main import ClearingProcess

        fake_sock = MagicMock()
        with (
            patch("edumatcher.clearing.main.make_subscriber", return_value=fake_sock),
            patch("edumatcher.clearing.main.DATA_DIR", tmp_path),
            patch(
                "edumatcher.clearing.main.CLEARING_REPORT_FILE", tmp_path / "report.csv"
            ),
        ):
            proc = ClearingProcess()
        proc._stop()
        assert proc._running is False


# ---------------------------------------------------------------------------
# stats/main.py — _stop and run paths
# ---------------------------------------------------------------------------


class TestStatsStop:
    def test_stop_sets_running_false(self, stats_proc) -> None:
        proc = stats_proc
        proc._stop()
        assert proc._running is False

    def test_on_eod_with_symbol_no_accumulator(self, stats_proc) -> None:
        proc = stats_proc
        # _on_eod with symbol not yet in accumulator should create it
        proc._on_eod({"books": [{"symbol": "AAPL", "bids": [], "asks": []}]})


# ---------------------------------------------------------------------------
# Additional _run_scheduled coverage with future times (mocked)
# ---------------------------------------------------------------------------


class TestSchedulerRunScheduledFuture:
    def test_sends_transition_for_future_time(self) -> None:
        from datetime import datetime
        from edumatcher.scheduler.main import _run_scheduled

        fake_sock = MagicMock()
        # Mock _time_today to return a time 1 second in the future
        future_time = datetime.now().replace(microsecond=0)
        import time as _time

        call_count = [0]
        original_monotonic = _time.monotonic

        def fake_monotonic():
            c = call_count[0]
            call_count[0] += 1
            if c < 2:
                return original_monotonic()
            # After 2 calls, advance clock past deadline
            return original_monotonic() + 100.0

        with (
            patch("edumatcher.scheduler.main._time_today", return_value=future_time),
            patch("edumatcher.scheduler.main.datetime") as mock_dt,
            patch(
                "edumatcher.scheduler.main.time.monotonic", side_effect=fake_monotonic
            ),
            patch("edumatcher.scheduler.main.time.sleep"),
        ):
            # Set now to be 1 second before future_time
            from datetime import timedelta

            mock_dt.now.return_value = future_time - timedelta(seconds=1)
            _run_scheduled(fake_sock, [("12:00", "CONTINUOUS")])

        assert fake_sock.send_multipart.called


# ---------------------------------------------------------------------------
# Additional GatewayCompleter edge cases to cover remaining lines
# ---------------------------------------------------------------------------


class TestGatewayCompleterMoreEdgeCases:
    def _completer(self):
        from edumatcher.gateway.main import GatewayCompleter

        return GatewayCompleter(known_symbols=["AAPL", "MSFT"])

    def _document(self, text):
        from prompt_toolkit.document import Document

        return Document(text)

    def test_new_without_type_suggests_all_fields(self) -> None:
        # "NEW|SYM=AAPL|" — TYPE not known yet → else branch (line with FIELD_COMPLETIONS)
        completer = self._completer()
        doc = self._document("NEW|SYM=AAPL|")
        results = list(completer.get_completions(doc, None))
        texts = [c.text for c in results]
        # Should suggest field names like "TYPE=", "SIDE=", etc.
        assert any("=" in t for t in texts)

    def test_unknown_value_key_returns_empty(self) -> None:
        # "NEW|UNKNOWNFIELD=..." — key doesn't match any known → candidates = []
        completer = self._completer()
        doc = self._document("NEW|UNKNOWNFIELD=")
        results = list(completer.get_completions(doc, None))
        # No completions for unknown field values
        assert results == []

    def test_combo_type_value_completions(self) -> None:
        completer = self._completer()
        doc = self._document("NEW|TYPE=COMBO|COMBO_TYPE=")
        results = list(completer.get_completions(doc, None))
        texts = [c.text for c in results]
        assert "AON" in texts

    def test_qlegs_show_value_completion(self) -> None:
        completer = self._completer()
        doc = self._document("QLEGS|SHOW=")
        results = list(completer.get_completions(doc, None))
        texts = [c.text for c in results]
        assert "ACTIVE" in texts

    def test_qlegs_field_completion(self) -> None:
        completer = self._completer()
        doc = self._document("QLEGS|")
        results = list(completer.get_completions(doc, None))
        texts = [c.text for c in results]
        assert "SHOW=" in texts


# ---------------------------------------------------------------------------
# Gateway._send_combo with invalid leg fields
# ---------------------------------------------------------------------------


class TestGatewaySendComboLegError:
    def test_combo_leg_invalid_side(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "NEW|TYPE=COMBO|COMBO_ID=C01|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=2"
            "|LEG0.SYM=AAPL|LEG0.SIDE=INVALID|LEG0.QTY=100|LEG0.PRICE=150.00|LEG0.TYPE=LIMIT"
            "|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=100|LEG1.PRICE=200.00|LEG1.TYPE=LIMIT"
        )
        # Invalid side → parse error → no send
        gw.push_sock.send_multipart.assert_not_called()

    def test_combo_leg_too_many_legs(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "NEW|TYPE=COMBO|COMBO_ID=C01|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=11"
            "|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=150.00|LEG0.TYPE=LIMIT"
        )
        gw.push_sock.send_multipart.assert_not_called()

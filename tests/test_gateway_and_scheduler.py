"""
Tests for Gateway helpers, _SysStdoutProxy, scheduler functions, audit, stats receive.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.table import Table

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gateway(gw_id: str = "GW01"):
    from edumatcher.alf_console.main import Gateway

    fake_push = MagicMock()
    fake_sub = MagicMock()
    with patch("edumatcher.alf_console.main.make_pusher", return_value=fake_push):
        with patch(
            "edumatcher.alf_console.main.make_subscriber", return_value=fake_sub
        ):
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
        from edumatcher.alf_console.main import _SysStdoutProxy

        proxy = _SysStdoutProxy()
        proxy.write("hello")
        captured = capsys.readouterr()
        assert "hello" in captured.out

    def test_flush_no_error(self) -> None:
        from edumatcher.alf_console.main import _SysStdoutProxy

        proxy = _SysStdoutProxy()
        proxy.flush()  # should not raise

    def test_fileno(self) -> None:
        from edumatcher.alf_console.main import _SysStdoutProxy
        import sys

        proxy = _SysStdoutProxy()
        assert proxy.fileno() == sys.stdout.fileno()

    def test_isatty(self) -> None:
        from edumatcher.alf_console.main import _SysStdoutProxy

        proxy = _SysStdoutProxy()
        result = proxy.isatty()
        assert isinstance(result, bool)

    def test_encoding(self) -> None:
        from edumatcher.alf_console.main import _SysStdoutProxy

        proxy = _SysStdoutProxy()
        assert isinstance(proxy.encoding, str)

    def test_errors(self) -> None:
        from edumatcher.alf_console.main import _SysStdoutProxy

        proxy = _SysStdoutProxy()
        assert isinstance(proxy.errors, str)


# ---------------------------------------------------------------------------
# Gateway._kv and _handle_event
# ---------------------------------------------------------------------------


class TestGatewayHelpers:
    def test_kv_parses_pairs(self) -> None:
        from edumatcher.alf_console.main import Gateway

        result = Gateway._kv(["SYM=AAPL", "SIDE=BUY", "QTY=100"])
        assert result == {"SYM": "AAPL", "SIDE": "BUY", "QTY": "100"}

    def test_kv_ignores_no_equals(self) -> None:
        from edumatcher.alf_console.main import Gateway

        result = Gateway._kv(["BAREWORD", "K=V"])
        assert "BAREWORD" not in result
        assert result["K"] == "V"

    def test_kv_uppercases_keys(self) -> None:
        from edumatcher.alf_console.main import Gateway

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

    def test_handle_event_symbols_with_meta(self) -> None:
        gw = _make_gateway()
        payload = {
            "symbols": ["AAPL", "MSFT"],
            "symbol_meta": {
                "AAPL": {
                    "tick_size": 0.01,
                    "enforce_mm_obligation": True,
                    "mm_max_spread_ticks": 10,
                    "mm_min_qty": 100,
                },
                "MSFT": {
                    "tick_size": 0.05,
                    "enforce_mm_obligation": False,
                    "mm_max_spread_ticks": 12,
                    "mm_min_qty": 50,
                },
            },
        }

        with patch("edumatcher.alf_console.main.console.print") as mock_print:
            gw._handle_event("system.symbols.GW01", payload)

        assert gw._known_symbol_meta["AAPL"]["tick_size"] == 0.01
        table = mock_print.call_args[0][0]
        assert isinstance(table, Table)
        assert [column.header for column in table.columns] == [
            "#",
            "Symbol",
            "Tick",
            "MM Enforced",
            "Max Spread",
            "Min Qty",
        ]
        assert table.columns[1]._cells == ["AAPL", "MSFT"]
        assert table.columns[2]._cells == ["0.01", "0.05"]
        assert table.columns[3]._cells == ["YES", "NO"]
        assert table.columns[4]._cells == ["10", "12"]
        assert table.columns[5]._cells == ["100", "50"]

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

    def test_handle_event_index_update_sets_default_index_id(self) -> None:
        gw = _make_gateway()
        gw._handle_event(
            "index.update",
            {
                "index_id": "EDU100",
                "level": 1025.0,
                "session_state": "CONTINUOUS",
            },
        )
        assert gw._default_index_id == "EDU100"
        assert gw._last_index_update is not None

    def test_parse_index_history_uses_index_socket(self) -> None:
        gw = _make_gateway()
        gw._default_index_id = "EDU100"
        gw._parse_and_send("INDEX|HISTORY")
        assert gw._index_push_sock.send_multipart.called

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
        from edumatcher.alf_console.display import print_positions

        gw = _make_gateway()
        gw._update_position("AAPL", "BUY", 100, 100.0)
        gw._last_prices["AAPL"] = 105.0
        # Should not raise
        print_positions(gw._positions, gw._last_prices)

    def test_print_positions_with_flat_realized(self) -> None:
        from edumatcher.alf_console.display import print_positions

        gw = _make_gateway()
        gw._update_position("AAPL", "BUY", 100, 100.0)
        gw._update_position("AAPL", "SELL", 100, 110.0)
        # position is flat but realized_pnl != 0
        print_positions(gw._positions, gw._last_prices)

    def test_print_positions_empty(self) -> None:
        from edumatcher.alf_console.display import print_positions

        gw = _make_gateway()
        print_positions(gw._positions, gw._last_prices)


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
    def test_all_past_times_catch_engine_up_to_last_state(self) -> None:
        # Regression for scheduler review finding H1
        # (docs-design/EduMatcher-scheduler-review.md): engine session
        # transitions are sequential and dependent, so a scheduler that starts
        # after every scheduled time has passed must still drive the engine to
        # the most-recent-past state instead of silently skipping every entry
        # (which would leave the engine stuck in its startup state).
        from datetime import datetime as _dt
        from edumatcher.models.message import decode
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

        # The engine must be caught up to the most-recent-past state rather
        # than left untouched.
        assert fake_sock.send_multipart.called, (
            "scheduler skipped all past transitions and sent nothing — "
            "engine would be stuck in its startup state"
        )
        sent_states = [
            decode(call.args[0])[1]["to_state"]
            for call in fake_sock.send_multipart.call_args_list
        ]
        assert sent_states[-1] == "OPENING_AUCTION"

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
        assert proc._to_terminal is False

    def test_init_with_terminal_flag(self, tmp_path: Path) -> None:
        from edumatcher.audit.main import AuditProcess

        fake_sub = MagicMock()
        with patch("edumatcher.audit.main.make_subscriber", return_value=fake_sub):
            proc = AuditProcess(log_path=tmp_path / "audit.log", to_terminal=True)
        assert proc.logger is not None
        assert proc._to_terminal is True

    def test_stop_sets_running_false(self, tmp_path: Path) -> None:
        from edumatcher.audit.main import AuditProcess

        fake_sub = MagicMock()
        with patch("edumatcher.audit.main.make_subscriber", return_value=fake_sub):
            proc = AuditProcess(log_path=tmp_path / "audit.log", to_terminal=False)
        proc._stop()
        assert proc._running is False

    def test_build_parser_logging_flags(self) -> None:
        from edumatcher.audit.main import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["-vv", "--quiet", "--log-level", "ERROR"])
        assert args.verbose == 2
        assert args.quiet is True
        assert args.log_level == "ERROR"


class TestAlfConsoleMain:
    def test_build_parser_logging_flags(self) -> None:
        from edumatcher.alf_console.main import _build_parser

        parser = _build_parser()
        args = parser.parse_args(
            ["--id", "GW01", "-vv", "--quiet", "--log-level", "ERROR"]
        )
        assert args.id == "GW01"
        assert args.verbose == 2
        assert args.quiet is True
        assert args.log_level == "ERROR"

    def test_configure_logging_defaults_to_warning(self) -> None:
        from argparse import Namespace
        import logging

        from edumatcher.alf_console.main import _configure_logging

        args = Namespace(log_level=None, verbose=0, quiet=False)
        assert _configure_logging(args) == logging.WARNING


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
        from edumatcher.alf_console.main import GatewayCompleter

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
        from edumatcher.alf_console.main import GatewayCompleter

        result = GatewayCompleter._combo_completions(
            parts=["NEW", "TYPE=COMBO", "LEG_COUNT=3"],
            already_keys={"TYPE", "LEG_COUNT"},
            partial_key="",
        )
        # With LEG_COUNT=3, should suggest LEG0/1/2 fields
        leg_keys = [r for r in result if r.startswith("LEG")]
        assert len(leg_keys) > 0

    def test_combo_completions_invalid_leg_count(self) -> None:
        from edumatcher.alf_console.main import GatewayCompleter

        # Invalid LEG_COUNT should default to 2
        result = GatewayCompleter._combo_completions(
            parts=["NEW", "TYPE=COMBO", "LEG_COUNT=INVALID"],
            already_keys={"TYPE", "LEG_COUNT"},
            partial_key="",
        )
        assert isinstance(result, list)


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
        from edumatcher.alf_console.main import GatewayCompleter

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


# ---------------------------------------------------------------------------
# New completer coverage: QUOTE, QUOTE_CANCEL, KILL, INDEX branches
# ---------------------------------------------------------------------------


class TestGatewayCompleterNewBranches:
    def _completer(self):
        from edumatcher.alf_console.main import GatewayCompleter

        return GatewayCompleter(known_symbols=["AAPL", "MSFT"])

    def _doc(self, text):
        from prompt_toolkit.document import Document

        return Document(text)

    def test_quote_field_completions(self) -> None:
        c = self._completer()
        results = list(c.get_completions(self._doc("QUOTE|"), None))
        texts = [r.text for r in results]
        assert "SYM=" in texts
        assert "BID=" in texts
        assert "ASK=" in texts
        assert "BID_QTY=" in texts
        assert "ASK_QTY=" in texts
        assert "TIF=" in texts
        assert "QUOTE_ID=" in texts

    def test_quote_field_completions_deduplicates(self) -> None:
        # SYM already entered — should not appear again
        c = self._completer()
        results = list(c.get_completions(self._doc("QUOTE|SYM=AAPL|"), None))
        texts = [r.text for r in results]
        assert "SYM=" not in texts
        assert "BID=" in texts

    def test_quote_cancel_field_completions(self) -> None:
        c = self._completer()
        results = list(c.get_completions(self._doc("QUOTE_CANCEL|"), None))
        texts = [r.text for r in results]
        assert "SYM=" in texts

    def test_quote_cancel_sym_already_entered(self) -> None:
        c = self._completer()
        results = list(c.get_completions(self._doc("QUOTE_CANCEL|SYM=AAPL|"), None))
        texts = [r.text for r in results]
        assert "SYM=" not in texts

    def test_kill_field_completions(self) -> None:
        c = self._completer()
        results = list(c.get_completions(self._doc("KILL|"), None))
        texts = [r.text for r in results]
        assert "SYM=" in texts

    def test_kill_sym_already_entered(self) -> None:
        c = self._completer()
        results = list(c.get_completions(self._doc("KILL|SYM=AAPL|"), None))
        texts = [r.text for r in results]
        assert "SYM=" not in texts

    def test_index_suggests_history_first(self) -> None:
        c = self._completer()
        results = list(c.get_completions(self._doc("INDEX|"), None))
        texts = [r.text for r in results]
        assert "HISTORY" in texts

    def test_index_after_history_suggests_kv_fields(self) -> None:
        c = self._completer()
        results = list(c.get_completions(self._doc("INDEX|HISTORY|"), None))
        texts = [r.text for r in results]
        assert "INDEX=" in texts
        assert "FROM=" in texts
        assert "TO=" in texts

    def test_index_after_history_deduplicates(self) -> None:
        c = self._completer()
        results = list(
            c.get_completions(self._doc("INDEX|HISTORY|FROM=2024-01-01|"), None)
        )
        texts = [r.text for r in results]
        assert "FROM=" not in texts
        assert "TO=" in texts

    def test_smp_value_completions(self) -> None:
        c = self._completer()
        results = list(
            c.get_completions(
                self._doc("NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00|SMP="),
                None,
            )
        )
        texts = [r.text for r in results]
        assert "NONE" in texts
        assert "CANCEL_AGGRESSOR" in texts


# ---------------------------------------------------------------------------
# order.orders: update existing entry
# ---------------------------------------------------------------------------


class TestOrderOrdersUpdatesExisting:
    def test_updates_existing_order_status(self) -> None:
        import time as _time

        gw = _make_gateway()
        # Pre-populate with PENDING status (as if we just sent the order)
        gw.order_cache["ORD-999"] = {
            "id": "ORD-999",
            "symbol": "AAPL",
            "side": "BUY",
            "type": "LIMIT",
            "tif": "DAY",
            "qty": 100,
            "remaining": 100,
            "price": 150.0,
            "status": "PENDING",
            "time": "10:00:00",
        }
        # Engine snapshot arrives with updated state
        gw._handle_event(
            "order.orders.GW01",
            {
                "orders": [
                    {
                        "id": "ORD-999",
                        "symbol": "AAPL",
                        "side": "BUY",
                        "order_type": "LIMIT",
                        "tif": "DAY",
                        "quantity": 100,
                        "remaining_qty": 40,
                        "price": 150.0,
                        "status": "PARTIAL",
                        "timestamp": _time.time(),
                    }
                ]
            },
        )
        assert gw.order_cache["ORD-999"]["status"] == "PARTIAL"
        assert gw.order_cache["ORD-999"]["remaining"] == 40
        # 'time' should be preserved from the original insertion
        assert gw.order_cache["ORD-999"]["time"] == "10:00:00"

    def test_skips_entry_with_no_id(self) -> None:
        gw = _make_gateway()
        # Should not raise even if 'id' is absent
        gw._handle_event(
            "order.orders.GW01",
            {"orders": [{"symbol": "AAPL", "status": "NEW"}]},
        )


# ---------------------------------------------------------------------------
# order.amended: None-safety
# ---------------------------------------------------------------------------


class TestOrderAmendedNoneSafety:
    def test_amended_partial_payload_does_not_corrupt_cache(self) -> None:
        gw = _make_gateway()
        gw.order_cache["ORD-A1"] = {
            "price": 100.0,
            "qty": 100,
            "remaining": 100,
        }
        # Only price is in payload; qty and remaining_qty absent
        gw._handle_event(
            "order.amended.GW01",
            {"order_id": "ORD-A1", "price": 105.0, "priority_reset": False},
        )
        assert gw.order_cache["ORD-A1"]["price"] == 105.0
        # remaining should NOT have been overwritten with None
        assert gw.order_cache["ORD-A1"]["remaining"] == 100

    def test_amended_all_fields_present(self) -> None:
        gw = _make_gateway()
        gw.order_cache["ORD-A2"] = {
            "price": 100.0,
            "qty": 200,
            "remaining": 200,
        }
        gw._handle_event(
            "order.amended.GW01",
            {
                "order_id": "ORD-A2",
                "price": 110.0,
                "qty": 150,
                "remaining_qty": 150,
                "priority_reset": True,
            },
        )
        assert gw.order_cache["ORD-A2"]["price"] == 110.0
        assert gw.order_cache["ORD-A2"]["qty"] == 150
        assert gw.order_cache["ORD-A2"]["remaining"] == 150


# ---------------------------------------------------------------------------
# _authenticated flag
# ---------------------------------------------------------------------------


class TestGatewayAuthenticatedFlag:
    def test_authenticated_flag_starts_false(self) -> None:
        gw = _make_gateway()
        assert gw._authenticated is False

    def test_status_shows_not_authenticated_before_run(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("STATUS")
        # Should not raise; flag is False → "no" in table


# ---------------------------------------------------------------------------
# stop_price stored in order_cache
# ---------------------------------------------------------------------------


class TestOrderCacheStopPrice:
    def test_stop_order_records_stop_price(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("NEW|SYM=AAPL|SIDE=BUY|TYPE=STOP|QTY=100|STOP=148.00")
        cached = next(
            (v for v in gw.order_cache.values() if v.get("type") == "STOP"), None
        )
        assert cached is not None
        assert cached["stop_price"] == 148.0

    def test_stop_limit_order_records_both_prices(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "NEW|SYM=AAPL|SIDE=BUY|TYPE=STOP_LIMIT|QTY=100|STOP=148.00|PRICE=147.50"
        )
        cached = next(
            (v for v in gw.order_cache.values() if v.get("type") == "STOP_LIMIT"),
            None,
        )
        assert cached is not None
        assert cached["stop_price"] == 148.0
        assert cached["price"] == 147.5


# ---------------------------------------------------------------------------
# _print_quote_legs display paths
# ---------------------------------------------------------------------------


class TestPrintQuoteLegs:
    def _gw_with_legs(self):
        gw = _make_gateway()
        gw._handle_event(
            "quote.ack.GW01",
            {
                "quote_id": "Q-PRINT",
                "accepted": True,
                "bid_order_id": "BID-PRINT",
                "ask_order_id": "ASK-PRINT",
            },
        )
        return gw

    def test_print_all_legs(self) -> None:
        gw = self._gw_with_legs()
        gw._parse_and_send("QLEGS|SHOW=ALL")  # Should not raise

    def test_print_active_legs(self) -> None:
        gw = self._gw_with_legs()
        gw._parse_and_send("QLEGS|SHOW=ACTIVE")

    def test_print_recent_legs(self) -> None:
        gw = self._gw_with_legs()
        gw._parse_and_send("QLEGS|SHOW=RECENT")

    def test_print_legs_filtered_by_symbol(self) -> None:
        gw = self._gw_with_legs()
        gw._parse_and_send("QLEGS|SYM=MSFT|SHOW=ALL")  # no legs → "No quote legs" msg

    def test_print_legs_no_legs_at_all(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("QLEGS|SHOW=ALL")  # empty cache — prints "No quote legs"


# ---------------------------------------------------------------------------
# _print_quote_bootstrap display
# ---------------------------------------------------------------------------


class TestPrintQuoteBootstrap:
    def test_qboot_sends_request(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("QBOOT|SYM=AAPL")
        assert gw.push_sock.send_multipart.called

    def test_qboot_no_sym_also_sends(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("QBOOT")
        assert gw.push_sock.send_multipart.called

    def test_handle_event_quote_bootstrap_empty(self) -> None:
        gw = _make_gateway()
        gw._handle_event("system.quote_bootstrap.GW01", {"quotes": []})

    def test_handle_event_quote_bootstrap_with_data(self) -> None:
        gw = _make_gateway()
        gw._handle_event(
            "system.quote_bootstrap.GW01",
            {
                "quotes": [
                    {
                        "quote_id": "Q1",
                        "symbol": "AAPL",
                        "state": "ACTIVE",
                        "bid_price": 149.5,
                        "ask_price": 150.5,
                        "bid_remaining_qty": 500,
                        "ask_remaining_qty": 500,
                    }
                ]
            },
        )

    def test_handle_event_quote_bootstrap_malformed(self) -> None:
        gw = _make_gateway()
        gw._handle_event("system.quote_bootstrap.GW01", {"quotes": "not-a-list"})


# ---------------------------------------------------------------------------
# _print_current_index and _print_index_history
# ---------------------------------------------------------------------------


class TestIndexDisplay:
    def test_index_command_no_data(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("INDEX")  # No data yet — prints "No index data"

    def test_index_command_with_data(self) -> None:
        import time as _time

        gw = _make_gateway()
        gw._last_index_update = {
            "index_id": "EDU100",
            "level": 1050.0,
            "session_state": "CONTINUOUS",
            "timestamp": _time.time(),
            "day_open": 1000.0,
            "day_high": 1060.0,
            "day_low": 995.0,
        }
        gw._parse_and_send("INDEX")  # Should print level with change %

    def test_index_command_no_day_open(self) -> None:
        import time as _time

        gw = _make_gateway()
        gw._last_index_update = {
            "index_id": "EDU100",
            "level": 1050.0,
            "session_state": "CONTINUOUS",
            "timestamp": _time.time(),
        }
        gw._parse_and_send("INDEX")  # No day_open — no change % shown

    def test_index_history_command_no_default_id(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("INDEX|HISTORY")  # No default index_id → error msg

    def test_index_history_command_with_default_id(self) -> None:
        gw = _make_gateway()
        gw._default_index_id = "EDU100"
        gw._parse_and_send("INDEX|HISTORY")
        assert gw._index_push_sock.send_multipart.called

    def test_index_history_command_with_explicit_id_and_dates(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("INDEX|HISTORY|INDEX=EDU100|FROM=2024-01-01|TO=2024-06-30")
        assert gw._index_push_sock.send_multipart.called

    def test_index_history_bad_date_falls_back_to_default(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("INDEX|HISTORY|INDEX=EDU100|FROM=NOTADATE")
        # Bad date → falls back to 30-day default window
        assert gw._index_push_sock.send_multipart.called

    def test_handle_event_index_history_empty(self) -> None:
        gw = _make_gateway()
        gw._handle_event("index.history.GW01", {"records": []})

    def test_handle_event_index_history_with_records(self) -> None:
        import time as _time

        gw = _make_gateway()
        gw._handle_event(
            "index.history.GW01",
            {
                "records": [
                    {
                        "type": "LEVEL",
                        "timestamp": _time.time(),
                        "level": 1025.5,
                        "session_state": "CONTINUOUS",
                    },
                    {
                        "type": "EOD",
                        "timestamp": _time.time(),
                        "level": 1030.0,
                        "session_state": "CLOSED",
                    },
                ]
            },
        )

    def test_handle_event_index_history_malformed(self) -> None:
        gw = _make_gateway()
        gw._handle_event("index.history.GW01", {"records": "not-a-list"})

    def test_handle_event_index_error(self) -> None:
        gw = _make_gateway()
        gw._handle_event("index.error.GW01", {"reason": "unknown index"})


# ---------------------------------------------------------------------------
# Quote ACK rejected path
# ---------------------------------------------------------------------------


class TestQuoteAckRejected:
    def test_quote_ack_rejected_prints_reason(self) -> None:
        gw = _make_gateway()
        gw._handle_event(
            "quote.ack.GW01",
            {"quote_id": "Q-REJ", "accepted": False, "reason": "spread too wide"},
        )
        # Should not raise; quote_leg_cache unchanged
        assert "Q-REJ" not in gw.quote_leg_cache


# ---------------------------------------------------------------------------
# _record_fill_for_quote_leg: new quote leg created from fill (no prior ack)
# ---------------------------------------------------------------------------


class TestRecordFillForQuoteLegNewEntry:
    def test_fill_creates_new_quote_leg_if_not_in_cache(self) -> None:
        gw = _make_gateway()
        # Simulate a fill for an order_id that was never ACK'd (e.g. reconnect)
        gw._quote_id_by_order_id["ORPHAN-001"] = "Q-ORPHAN"
        gw._handle_event(
            "order.fill.GW01",
            {
                "order_id": "ORPHAN-001",
                "fill_qty": 50,
                "fill_price": 150.0,
                "remaining_qty": 50,
                "status": "PARTIAL",
                "symbol": "AAPL",
                "side": "BUY",
                "qty": 100,
            },
        )
        assert "ORPHAN-001" in gw.quote_leg_cache
        assert gw.quote_leg_cache["ORPHAN-001"]["filled"] == 50


# ---------------------------------------------------------------------------
# kill_switch_ack rejected path
# ---------------------------------------------------------------------------


class TestKillSwitchAckRejected:
    def test_kill_switch_ack_rejected(self) -> None:
        gw = _make_gateway()
        gw._handle_event(
            "risk.kill_switch_ack.GW01",
            {"accepted": False, "reason": "not allowed"},
        )  # should not raise


# ---------------------------------------------------------------------------
# _parse_date helper
# ---------------------------------------------------------------------------


class TestParseDate:
    def test_none_returns_none(self) -> None:
        from edumatcher.alf_console.main import Gateway

        assert Gateway._parse_date(None) is None

    def test_empty_string_returns_none(self) -> None:
        from edumatcher.alf_console.main import Gateway

        assert Gateway._parse_date("") is None

    def test_invalid_format_returns_none(self) -> None:
        from edumatcher.alf_console.main import Gateway

        assert Gateway._parse_date("not-a-date") is None

    def test_valid_date_returns_float(self) -> None:
        from edumatcher.alf_console.main import Gateway

        result = Gateway._parse_date("2024-01-15")
        assert isinstance(result, float)
        assert result > 0


# ---------------------------------------------------------------------------
# _send_quote validation
# ---------------------------------------------------------------------------


class TestSendQuoteValidation:
    def test_quote_zero_bid_qty_rejected(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("QUOTE|SYM=AAPL|BID=149.50|ASK=150.50|BID_QTY=0|ASK_QTY=100")
        gw.push_sock.send_multipart.assert_not_called()

    def test_quote_bid_ge_ask_rejected(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "QUOTE|SYM=AAPL|BID=150.50|ASK=150.50|BID_QTY=100|ASK_QTY=100"
        )
        gw.push_sock.send_multipart.assert_not_called()

    def test_quote_missing_bid_rejected(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("QUOTE|SYM=AAPL|ASK=150.50|BID_QTY=100|ASK_QTY=100")
        gw.push_sock.send_multipart.assert_not_called()

    def test_quote_with_quote_id(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send(
            "QUOTE|SYM=AAPL|BID=149.50|ASK=150.50|BID_QTY=100|ASK_QTY=100|QUOTE_ID=Q99"
        )
        assert gw.push_sock.send_multipart.called


# ---------------------------------------------------------------------------
# _print_symbols_table via handle_event (symbols with no meta)
# ---------------------------------------------------------------------------


class TestSymbolsNoMeta:
    def test_handle_event_symbols_no_meta(self) -> None:
        gw = _make_gateway()
        # No symbol_meta key at all → should use empty dict fallback
        gw._handle_event("system.symbols.GW01", {"symbols": ["AAPL", "MSFT"]})
        assert "AAPL" in gw._known_symbols


# ---------------------------------------------------------------------------
# Targeted coverage: completer value/field branches + misc event paths
# ---------------------------------------------------------------------------


class TestCompleterValueBranches:
    """Hit the specific value-completion elif branches that were uncovered."""

    def _completer(self):
        from edumatcher.alf_console.main import GatewayCompleter

        return GatewayCompleter(known_symbols=["AAPL", "MSFT"])

    def _doc(self, text):
        from prompt_toolkit.document import Document

        return Document(text)

    # ---- top-level partial command (lines 219-223) ----
    def test_partial_toplevel_command_completes(self) -> None:
        c = self._completer()
        results = list(c.get_completions(self._doc("NE"), None))
        texts = [r.text for r in results]
        assert "NEW" in texts

    def test_partial_toplevel_command_q(self) -> None:
        c = self._completer()
        results = list(c.get_completions(self._doc("Q"), None))
        texts = [r.text for r in results]
        assert any(t.startswith("Q") for t in texts)

    # ---- SIDE= value completion (line 238) ----
    def test_side_value_completion(self) -> None:
        c = self._completer()
        results = list(c.get_completions(self._doc("NEW|SIDE="), None))
        texts = [r.text for r in results]
        assert "BUY" in texts
        assert "SELL" in texts

    # ---- TYPE= (no leg prefix) value completion (line 242) ----
    def test_type_value_completion(self) -> None:
        c = self._completer()
        results = list(c.get_completions(self._doc("NEW|TYPE="), None))
        texts = [r.text for r in results]
        assert "LIMIT" in texts
        assert "COMBO" in texts
        assert "OCO" in texts

    # ---- LEG{i}.TYPE= value completion (line 244) ----
    def test_leg_type_value_completion(self) -> None:
        c = self._completer()
        results = list(c.get_completions(self._doc("NEW|TYPE=COMBO|LEG0.TYPE="), None))
        texts = [r.text for r in results]
        assert "LIMIT" in texts
        assert "STOP" in texts

    # ---- TIF= value completion (line 249) ----
    def test_tif_value_completion(self) -> None:
        c = self._completer()
        results = list(c.get_completions(self._doc("NEW|TIF="), None))
        texts = [r.text for r in results]
        assert "DAY" in texts
        assert "GTC" in texts

    # ---- SMP= value completion (line 273) ----
    def test_smp_via_leg_value_completion(self) -> None:
        c = self._completer()
        # "LEG0.SMP=" — field == "SMP" branch
        results = list(c.get_completions(self._doc("NEW|TYPE=COMBO|LEG0.SMP="), None))
        texts = [r.text for r in results]
        assert "NONE" in texts

    # ---- else branch: unknown field → empty candidates + for loop (283-285) ----
    def test_status_pipe_no_completions(self) -> None:
        c = self._completer()
        results = list(c.get_completions(self._doc("STATUS|"), None))
        # STATUS has no field completions → empty list
        assert results == []

    # ---- CANCEL field completions (301-305) ----
    def test_cancel_field_completions(self) -> None:
        c = self._completer()
        results = list(c.get_completions(self._doc("CANCEL|"), None))
        texts = [r.text for r in results]
        assert "ID=" in texts
        assert "COMBO_ID=" in texts
        assert "OCO_ID=" in texts

    # ---- QLEGS field completions (307-311) ----
    def test_qlegs_field_completions_initial(self) -> None:
        c = self._completer()
        results = list(c.get_completions(self._doc("QLEGS|"), None))
        texts = [r.text for r in results]
        assert "SYM=" in texts
        assert "SHOW=" in texts

    # ---- QBOOT field completion (line 313) ----
    def test_qboot_field_completion(self) -> None:
        c = self._completer()
        results = list(c.get_completions(self._doc("QBOOT|"), None))
        texts = [r.text for r in results]
        assert "SYM=" in texts

    # ---- INDEX|HISTORY key-value fields (line 343) ----
    def test_index_history_kv_completions(self) -> None:
        c = self._completer()
        results = list(c.get_completions(self._doc("INDEX|HISTORY|"), None))
        texts = [r.text for r in results]
        assert "INDEX=" in texts
        assert "FROM=" in texts
        assert "TO=" in texts

    # ---- _oco_completions (385-401) via NEW|TYPE=OCO ----
    def test_oco_field_completions(self) -> None:
        c = self._completer()
        results = list(c.get_completions(self._doc("NEW|TYPE=OCO|"), None))
        texts = [r.text for r in results]
        assert "OCO_ID=" in texts
        assert "SYM=" in texts
        assert "LEG1_SIDE=" in texts

    def test_oco_field_completions_deduplicates(self) -> None:
        c = self._completer()
        results = list(c.get_completions(self._doc("NEW|TYPE=OCO|OCO_ID=MYOCO|"), None))
        texts = [r.text for r in results]
        assert "OCO_ID=" not in texts
        assert "SYM=" in texts


class TestOrderCancelledQuoteLeg:
    """Line 866-868: order.cancelled when the ID is also in quote_leg_cache."""

    def test_cancelled_clears_quote_leg_too(self) -> None:
        gw = _make_gateway()
        order_id = "ORD-Q99"
        gw.order_cache[order_id] = {"status": "NEW"}
        gw.quote_leg_cache[order_id] = {
            "status": "NEW",
            "remaining": 100,
            "last_event_time": "10:00:00",
        }
        gw._handle_event("order.cancelled.GW01", {"order_id": order_id})
        assert gw.order_cache[order_id]["status"] == "CANCELLED"
        assert gw.quote_leg_cache[order_id]["status"] == "CANCELLED"
        assert gw.quote_leg_cache[order_id]["remaining"] == 0


class TestQuoteAckBidAlreadyInCache:
    """Lines 930-931: quote.ack when bid/ask order IDs are already in quote_leg_cache."""

    def test_quote_ack_updates_existing_leg_in_cache(self) -> None:
        gw = _make_gateway()
        # Pre-populate (e.g. from order.orders bootstrap)
        gw.quote_leg_cache["BID-PRELOADED"] = {
            "quote_id": "OLD_Q",
            "leg_side": "?",
            "symbol": "AAPL",
        }
        gw._handle_event(
            "quote.ack.GW01",
            {
                "quote_id": "NEW_Q",
                "accepted": True,
                "bid_order_id": "BID-PRELOADED",
                "ask_order_id": "ASK-NEW",
            },
        )
        # Existing entry should have quote_id and leg_side updated
        assert gw.quote_leg_cache["BID-PRELOADED"]["quote_id"] == "NEW_Q"
        assert gw.quote_leg_cache["BID-PRELOADED"]["leg_side"] == "BUY"


class TestQuoteStatusWithReason:
    """Line 1037-1038: quote.status where reason is non-empty."""

    def test_quote_status_with_reason_string(self) -> None:
        gw = _make_gateway()
        gw._handle_event(
            "quote.status.GW01",
            {"quote_id": "Q-R", "status": "CANCELLED", "reason": "kill switch"},
        )  # should not raise


class TestQuoteCancelMissingSym:
    """Line 1302-1303: QUOTE_CANCEL without SYM= prints error."""

    def test_quote_cancel_missing_sym(self) -> None:
        gw = _make_gateway()
        gw._parse_and_send("QUOTE_CANCEL")
        gw.push_sock.send_multipart.assert_not_called()


class TestIndexDisplayEdgeCases:
    """Lines 1691, 1742: _print_current_index and _print_index_history with missing ts."""

    def test_index_no_timestamp_uses_now(self) -> None:
        gw = _make_gateway()
        # No 'timestamp' key → else branch in _print_current_index
        gw._last_index_update = {
            "index_id": "EDU100",
            "level": 1000.0,
            "session_state": "CONTINUOUS",
            # no 'timestamp'
            "day_open": 980.0,
            "day_high": 1010.0,
            "day_low": 975.0,
        }
        gw._parse_and_send("INDEX")  # should not raise

    def test_index_history_record_no_timestamp(self) -> None:
        gw = _make_gateway()
        # Record with no timestamp → ts_txt = "?"
        gw._handle_event(
            "index.history.GW01",
            {
                "records": [
                    {"type": "LEVEL", "level": 1000.0, "session_state": "CONTINUOUS"}
                ]
            },
        )

    def test_index_history_record_no_level(self) -> None:
        import time as _time

        gw = _make_gateway()
        # Record with no level → level_txt = "-"
        gw._handle_event(
            "index.history.GW01",
            {
                "records": [
                    {
                        "type": "LEVEL",
                        "timestamp": _time.time(),
                        "session_state": "CONTINUOUS",
                        # no 'level'
                    }
                ]
            },
        )


class TestSymbolsTableNonBoolMeta:
    """Lines 780-803: _print_symbols_table when enforce_mm is not a bool."""

    def test_symbols_with_non_bool_enforce_mm(self) -> None:
        gw = _make_gateway()
        payload = {
            "symbols": ["AAPL"],
            "symbol_meta": {
                "AAPL": {
                    "tick_size": 0.01,
                    "enforce_mm_obligation": "yes",  # not a bool → "—" in table
                    "mm_max_spread_ticks": None,
                    "mm_min_qty": None,
                }
            },
        }
        gw._handle_event("system.symbols.GW01", payload)
        assert "AAPL" in gw._known_symbols

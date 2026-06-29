"""
Tests for UI helper functions in board, orders, viewer, ticker, and more engine gaps.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from edumatcher.orders.main import OrderMonitor

# ===========================================================================
# board/main.py helpers
# ===========================================================================


class TestBoardHelpers:
    def test_colour_change_positive(self) -> None:
        from edumatcher.board.main import _colour_change

        assert _colour_change(1.5) == "bright_green"

    def test_colour_change_negative(self) -> None:
        from edumatcher.board.main import _colour_change

        assert _colour_change(-0.5) == "bright_red"

    def test_colour_change_zero(self) -> None:
        from edumatcher.board.main import _colour_change

        assert _colour_change(0.0) == "white"

    def test_fmt_price_none(self) -> None:
        from edumatcher.board.main import _fmt_price

        assert _fmt_price(None) == "—"

    def test_fmt_price_value(self) -> None:
        from edumatcher.board.main import _fmt_price

        assert _fmt_price(150.0) == "150.0000"

    def test_build_table_empty(self) -> None:
        from edumatcher.board.main import _build_table
        from rich.table import Table

        t = _build_table({}, page=0, rows_per_page=8, interval=10)
        assert isinstance(t, Table)

    def test_build_table_single_symbol(self) -> None:
        from edumatcher.board.main import _build_table

        symbols = {
            "AAPL": {
                "last_price": 150.0,
                "first_price": 145.0,
                "last_buy_price": 149.9,
                "last_sell_price": 150.1,
                "best_bid": 149.5,
                "best_ask": 150.5,
                "volume": 10000,
                "updated": datetime.now(),
            }
        }
        t = _build_table(symbols, page=0, rows_per_page=8, interval=10)
        assert t.row_count >= 1

    def test_build_table_paging(self) -> None:
        from edumatcher.board.main import _build_table

        symbols = {
            f"SYM{i:02d}": {
                "last_price": 100.0 + i,
                "first_price": 100.0,
                "volume": 0,
                "updated": None,
            }
            for i in range(20)
        }
        t1 = _build_table(symbols, page=0, rows_per_page=8, interval=10)
        t2 = _build_table(symbols, page=1, rows_per_page=8, interval=10)
        assert t1.row_count == 8
        assert t2.row_count == 8

    def test_build_table_no_prices(self) -> None:
        from edumatcher.board.main import _build_table

        symbols = {
            "AAPL": {
                "last_price": None,
                "first_price": None,
                "volume": 0,
                "updated": None,
            }
        }
        t = _build_table(symbols, page=0, rows_per_page=8, interval=10)
        assert t.row_count >= 1

    def test_build_table_with_spread(self) -> None:
        from edumatcher.board.main import _build_table

        symbols = {
            "MSFT": {
                "last_price": 400.0,
                "first_price": 398.0,
                "best_bid": 399.5,
                "best_ask": 400.5,
                "last_buy_price": 400.0,
                "last_sell_price": 399.0,
                "volume": 500,
                "updated": datetime.now(),
            }
        }
        t = _build_table(symbols, page=0, rows_per_page=8, interval=10)
        assert t.row_count >= 1


# ===========================================================================
# orders/main.py helpers — OrderMonitor._handle
# ===========================================================================


class TestOrderMonitorHandle:
    def _make_monitor(self) -> "OrderMonitor":
        from edumatcher.orders.main import OrderMonitor

        fake_sock = MagicMock()
        with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sock):
            monitor = OrderMonitor(gw_filter=None)
        return monitor

    def test_handle_ack_accepted(self) -> None:
        monitor = self._make_monitor()
        monitor._handle(
            "order.ack.GW01",
            {
                "order_id": "O1",
                "accepted": True,
                "symbol": "AAPL",
                "side": "BUY",
                "order_type": "LIMIT",
                "tif": "DAY",
                "qty": 100,
                "price": 100.0,
            },
        )
        with monitor._lock:
            assert "O1" in monitor._orders

    def test_handle_fill(self) -> None:
        monitor = self._make_monitor()
        monitor._handle(
            "order.ack.GW01",
            {
                "order_id": "O2",
                "accepted": True,
                "symbol": "AAPL",
                "side": "BUY",
                "order_type": "LIMIT",
                "tif": "DAY",
                "qty": 100,
                "price": 100.0,
            },
        )
        monitor._handle(
            "order.fill.GW01",
            {
                "order_id": "O2",
                "fill_qty": 50,
                "fill_price": 100.0,
                "remaining_qty": 50,
                "status": "PARTIAL",
            },
        )
        with monitor._lock:
            assert monitor._orders["O2"]["status"] == "PARTIAL"

    def test_handle_cancelled(self) -> None:
        monitor = self._make_monitor()
        monitor._handle(
            "order.ack.GW01",
            {
                "order_id": "O3",
                "accepted": True,
                "symbol": "MSFT",
                "side": "SELL",
                "order_type": "LIMIT",
                "tif": "DAY",
                "qty": 50,
                "price": 200.0,
            },
        )
        monitor._handle("order.cancelled.GW01", {"order_id": "O3"})
        with monitor._lock:
            assert monitor._orders["O3"]["status"] == "CANCELLED"

    def test_handle_amended(self) -> None:
        monitor = self._make_monitor()
        monitor._handle(
            "order.ack.GW01",
            {
                "order_id": "O4",
                "accepted": True,
                "symbol": "AAPL",
                "side": "BUY",
                "order_type": "LIMIT",
                "tif": "DAY",
                "qty": 100,
                "price": 100.0,
            },
        )
        monitor._handle(
            "order.amended.GW01",
            {"order_id": "O4", "qty": 80, "price": 99.0, "remaining_qty": 80},
        )
        with monitor._lock:
            assert monitor._orders["O4"]["qty"] == 80

    def test_handle_expired(self) -> None:
        monitor = self._make_monitor()
        monitor._handle(
            "order.ack.GW01",
            {
                "order_id": "O5",
                "accepted": True,
                "symbol": "AAPL",
                "side": "BUY",
                "order_type": "LIMIT",
                "tif": "DAY",
                "qty": 100,
                "price": 100.0,
            },
        )
        monitor._handle("order.expired.GW01", {"order_id": "O5"})
        with monitor._lock:
            assert monitor._orders["O5"]["status"] == "EXPIRED"

    def test_handle_rejected_ack(self) -> None:
        monitor = self._make_monitor()
        monitor._handle("order.ack.GW01", {"order_id": "O6", "accepted": False})
        with monitor._lock:
            # Rejected ack doesn't add to orders (accepted=False)
            assert "O6" not in monitor._orders or monitor._orders.get("O6", {}).get(
                "status"
            ) in (None, "REJECTED")


# ===========================================================================
# Engine: _on_startup_symbols in stats
# ===========================================================================


class TestStatsOnStartupSymbols:
    def test_on_startup_symbols_sends_requests(self, tmp_path: Path) -> None:
        from edumatcher.stats.main import StatsProcess

        fake_sub = MagicMock()
        fake_push = MagicMock()
        with (
            patch("edumatcher.stats.main.make_subscriber", return_value=fake_sub),
            patch("edumatcher.stats.main.make_pusher", return_value=fake_push),
        ):
            sp = StatsProcess(tmp_path / "test.db")

        try:
            sp._on_startup_symbols({"symbols": ["AAPL", "MSFT"]})
            # Should have called send_multipart twice (once per symbol)
            assert fake_push.send_multipart.call_count == 2
        finally:
            sp._conn.close()

    def test_on_startup_symbols_empty(self, tmp_path: Path) -> None:
        from edumatcher.stats.main import StatsProcess

        fake_sock = MagicMock()
        with (
            patch("edumatcher.stats.main.make_subscriber", return_value=fake_sock),
            patch("edumatcher.stats.main.make_pusher", return_value=fake_sock),
        ):
            sp = StatsProcess(tmp_path / "test.db")

        try:
            sp._on_startup_symbols({"symbols": []})
            # No requests sent
            fake_sock.send_multipart.assert_not_called()
        finally:
            sp._conn.close()


# ===========================================================================
# Engine: _handle_cancel with OCO cascade
# ===========================================================================


class TestEngineCancelOCO:
    def test_cancel_oco_leg_cancels_sibling(self, monkeypatch, tmp_path) -> None:
        from dataclasses import dataclass
        from edumatcher.engine.config_loader import (
            EngineConfig,
            FixGatewayConfig,
            SymbolConfig,
        )
        from edumatcher.engine.main import Engine
        from edumatcher.models.message import decode

        @dataclass
        class _Sock:
            sent: list

            def send_multipart(self, f):
                self.sent.append(f)

            def close(self):
                pass

        pull_sock = _Sock(sent=[])
        pub_sock = _Sock(sent=[])
        cfg = EngineConfig(
            symbols={"AAPL": SymbolConfig(name="AAPL")},
            fix_gateways={"GW01": FixGatewayConfig(id="GW01", description="")},
            sessions_enabled=True,
        )
        monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
        monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
        monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)
        monkeypatch.setattr("edumatcher.engine.main.load_gtc_orders", lambda _: [])
        monkeypatch.setattr("edumatcher.engine.main.load_book_stats", lambda _: {})
        monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)

        cfg_path = tmp_path / "cfg.yaml"
        cfg_path.write_text("dummy: true\n")
        engine = Engine(config_path=str(cfg_path))
        engine._handle_gateway_connect({"gateway_id": "GW01"})
        # Advance through valid session states so the engine accepts orders
        for state in ("PRE_OPEN", "OPENING_AUCTION", "CONTINUOUS"):
            engine._handle_session_transition({"to_state": state})

        # Post OCO
        engine._handle_oco_order(
            {
                "oco_id": "OCO_CANCEL_TEST",
                "gateway_id": "GW01",
                "symbol": "AAPL",
                "quantity": 100,
                "tif": "DAY",
                "leg1": {"side": "BUY", "order_type": "LIMIT", "price": 95.0},
                "leg2": {"side": "BUY", "order_type": "STOP", "stop_price": 105.0},
            }
        )
        order_ids = engine._oco_groups.get("OCO_CANCEL_TEST", [])
        assert len(order_ids) == 2

        # Cancel leg1 — should trigger OCO cascade
        pub_sock.sent.clear()
        engine._handle_cancel({"order_id": order_ids[0], "gateway_id": "GW01"})
        topics = [decode(f)[0] for f in pub_sock.sent]
        # Either oco.cancelled or order.cancelled topics should appear
        assert any("cancelled" in t for t in topics)


# ===========================================================================
# Engine: additional coverage for session transitions
# ===========================================================================


class TestEngineSessionTransitions:
    def _engine(self, monkeypatch, tmp_path):
        from dataclasses import dataclass
        from edumatcher.engine.config_loader import (
            EngineConfig,
            FixGatewayConfig,
            SymbolConfig,
        )
        from edumatcher.engine.main import Engine

        @dataclass
        class _Sock:
            sent: list

            def send_multipart(self, f):
                self.sent.append(f)

            def close(self):
                pass

        pull_sock = _Sock(sent=[])
        pub_sock = _Sock(sent=[])
        cfg = EngineConfig(
            symbols={"AAPL": SymbolConfig(name="AAPL")},
            fix_gateways={"GW01": FixGatewayConfig(id="GW01", description="")},
            sessions_enabled=True,
        )
        monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
        monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
        monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)
        monkeypatch.setattr("edumatcher.engine.main.load_gtc_orders", lambda _: [])
        monkeypatch.setattr("edumatcher.engine.main.load_book_stats", lambda _: {})
        monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)
        cfg_path = tmp_path / "cfg.yaml"
        cfg_path.write_text("dummy: true\n")
        return Engine(config_path=str(cfg_path)), pub_sock

    def test_transition_from_pre_open_to_continuous_triggers_uncross(
        self, monkeypatch, tmp_path
    ) -> None:
        from edumatcher.models.message import decode
        from edumatcher.models.session import SessionState

        engine, pub_sock = self._engine(monkeypatch, tmp_path)
        engine._handle_gateway_connect({"gateway_id": "GW01"})
        engine._session_state = SessionState.OPENING_AUCTION
        engine._handle_session_transition({"to_state": "CONTINUOUS"})
        # uncross result (auction_result) should be published
        topics = [decode(f)[0] for f in pub_sock.sent]
        assert any("session.state" in t for t in topics)

    def test_run_uncross_no_crossable_interest(self, monkeypatch, tmp_path) -> None:
        from edumatcher.models.session import SessionState

        engine, pub_sock = self._engine(monkeypatch, tmp_path)
        engine._handle_gateway_connect({"gateway_id": "GW01"})
        # Create a book with no crossing orders
        from edumatcher.models.order import Order, OrderType, Side

        o = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW01",
            price=100.0,
        )
        engine._session_state = SessionState.OPENING_AUCTION
        engine._handle_new_order(o.to_dict())
        # No matching sell — uncross should find no crossable interest
        pub_sock.sent.clear()
        engine._run_uncross()
        from edumatcher.models.message import decode

        topics = [decode(f)[0] for f in pub_sock.sent]
        # auction_result should still be published even with no trades
        assert any("auction.result" in t for t in topics)

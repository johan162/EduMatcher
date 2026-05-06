"""
Tests for messaging/bus.py, engine _shutdown, and remaining engine gaps.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from edumatcher.engine.config_loader import (
    EngineConfig,
    FixGatewayConfig,
    SymbolConfig,
)
from edumatcher.engine.main import Engine
from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType
from edumatcher.models.message import decode
from edumatcher.models.order import Order, OrderType, Side, SmpAction, TIF
from edumatcher.models.session import SessionState

# ---------------------------------------------------------------------------
# messaging/bus.py
# ---------------------------------------------------------------------------


class TestMessagingBus:
    def test_get_context_returns_instance(self) -> None:
        from edumatcher.messaging.bus import get_context

        ctx = get_context()
        assert ctx is not None

    def test_get_context_singleton(self) -> None:
        from edumatcher.messaging.bus import get_context

        ctx1 = get_context()
        ctx2 = get_context()
        assert ctx1 is ctx2

    def test_make_puller_creates_socket(self) -> None:
        from edumatcher.messaging.bus import make_puller
        import zmq

        fake_sock = MagicMock(spec=zmq.Socket)
        fake_ctx = MagicMock()
        fake_ctx.socket.return_value = fake_sock
        with patch("edumatcher.messaging.bus.get_context", return_value=fake_ctx):
            make_puller("tcp://127.0.0.1:9999")
        fake_ctx.socket.assert_called_once_with(zmq.PULL)
        fake_sock.bind.assert_called_once_with("tcp://127.0.0.1:9999")

    def test_make_publisher_creates_socket(self) -> None:
        from edumatcher.messaging.bus import make_publisher
        import zmq

        fake_sock = MagicMock(spec=zmq.Socket)
        fake_ctx = MagicMock()
        fake_ctx.socket.return_value = fake_sock
        with patch("edumatcher.messaging.bus.get_context", return_value=fake_ctx):
            make_publisher("tcp://127.0.0.1:9998")
        fake_ctx.socket.assert_called_once_with(zmq.PUB)
        fake_sock.bind.assert_called_once_with("tcp://127.0.0.1:9998")

    def test_make_pusher_creates_socket(self) -> None:
        from edumatcher.messaging.bus import make_pusher
        import zmq

        fake_sock = MagicMock(spec=zmq.Socket)
        fake_ctx = MagicMock()
        fake_ctx.socket.return_value = fake_sock
        with patch("edumatcher.messaging.bus.get_context", return_value=fake_ctx):
            make_pusher("tcp://127.0.0.1:9997")
        fake_ctx.socket.assert_called_once_with(zmq.PUSH)
        fake_sock.connect.assert_called_once_with("tcp://127.0.0.1:9997")

    def test_make_subscriber_with_topics(self) -> None:
        from edumatcher.messaging.bus import make_subscriber
        import zmq

        fake_sock = MagicMock(spec=zmq.Socket)
        fake_ctx = MagicMock()
        fake_ctx.socket.return_value = fake_sock
        with patch("edumatcher.messaging.bus.get_context", return_value=fake_ctx):
            make_subscriber("tcp://127.0.0.1:9996", "book.", "trade.")
        fake_ctx.socket.assert_called_once_with(zmq.SUB)
        fake_sock.connect.assert_called_once_with("tcp://127.0.0.1:9996")
        # Two setsockopt calls for the two topics
        assert fake_sock.setsockopt.call_count == 2

    def test_make_subscriber_no_topics_subscribes_all(self) -> None:
        from edumatcher.messaging.bus import make_subscriber
        import zmq

        fake_sock = MagicMock(spec=zmq.Socket)
        fake_ctx = MagicMock()
        fake_ctx.socket.return_value = fake_sock
        with patch("edumatcher.messaging.bus.get_context", return_value=fake_ctx):
            make_subscriber("tcp://127.0.0.1:9995")
        fake_sock.setsockopt.assert_called_once_with(zmq.SUBSCRIBE, b"")


# ---------------------------------------------------------------------------
# Shared engine factory
# ---------------------------------------------------------------------------


@dataclass
class _Sock:
    sent: list
    closed: bool = False

    def send_multipart(self, f: list) -> None:
        self.sent.append(f)

    def close(self) -> None:
        self.closed = True


def _make_engine(
    monkeypatch,
    tmp_path,
    symbols=("AAPL",),
    gateways=("GW01",),
    verbose=False,
    gtc_orders=None,
) -> tuple[Engine, _Sock]:
    pull_sock = _Sock(sent=[])
    pub_sock = _Sock(sent=[])
    cfg = EngineConfig(
        symbols={sym: SymbolConfig(name=sym) for sym in symbols},
        fix_gateways={gw: FixGatewayConfig(id=gw, description="") for gw in gateways},
    )
    monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
    monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
    monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)
    monkeypatch.setattr(
        "edumatcher.engine.main.load_gtc_orders", lambda _: list(gtc_orders or [])
    )
    monkeypatch.setattr("edumatcher.engine.main.load_book_stats", lambda _: {})
    monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text("dummy: true\n")
    engine = Engine(verbose=verbose, config_path=str(cfg_path))
    return engine, pub_sock


def _connect(e: Engine, gw="GW01") -> None:
    e._handle_gateway_connect({"gateway_id": gw})


def _order(
    symbol="AAPL",
    side=Side.BUY,
    order_type=OrderType.LIMIT,
    qty=100,
    price=100.0,
    gateway_id="GW01",
    tif=TIF.DAY,
    smp=SmpAction.NONE,
) -> dict:
    o = Order.create(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=qty,
        gateway_id=gateway_id,
        tif=tif,
        price=price,
        smp_action=smp,
    )
    return o.to_dict()


def _ack_id(pub_sock: _Sock) -> str:
    for frames in reversed(pub_sock.sent):
        topic, payload = decode(frames)
        if "ack" in topic and payload.get("accepted"):
            return str(payload.get("order_id", ""))
    return ""


# ---------------------------------------------------------------------------
# Engine _shutdown
# ---------------------------------------------------------------------------


class TestEngineShutdown:
    def test_shutdown_expires_day_orders(self, monkeypatch, tmp_path) -> None:
        saved = []
        monkeypatch.setattr(
            "edumatcher.engine.main.save_gtc_orders",
            lambda orders, path: saved.extend(orders),
        )
        monkeypatch.setattr(
            "edumatcher.engine.main.save_gtc_combos",
            lambda combos, path: None,
        )
        monkeypatch.setattr(
            "edumatcher.engine.main.save_book_stats",
            lambda books, path: None,
        )

        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        # Add a DAY order
        engine._handle_new_order(_order(tif=TIF.DAY))
        pub_sock.sent.clear()
        engine._shutdown()
        topics = [decode(f)[0] for f in pub_sock.sent]
        # DAY order should be expired
        assert any("expired" in t for t in topics)

    def test_shutdown_saves_gtc_orders(self, monkeypatch, tmp_path) -> None:
        saved: list = []
        monkeypatch.setattr(
            "edumatcher.engine.main.save_gtc_orders",
            lambda orders, path: saved.extend(orders),
        )
        monkeypatch.setattr("edumatcher.engine.main.save_gtc_combos", lambda *_: None)
        monkeypatch.setattr("edumatcher.engine.main.save_book_stats", lambda *_: None)

        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_new_order(_order(tif=TIF.GTC))
        engine._shutdown()
        assert len(saved) == 1

    def test_shutdown_publishes_eod(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr("edumatcher.engine.main.save_gtc_orders", lambda *_: None)
        monkeypatch.setattr("edumatcher.engine.main.save_gtc_combos", lambda *_: None)
        monkeypatch.setattr("edumatcher.engine.main.save_book_stats", lambda *_: None)

        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_new_order(_order())
        pub_sock.sent.clear()
        engine._shutdown()
        topics = [decode(f)[0] for f in pub_sock.sent]
        assert any("system.eod" in t for t in topics)

    def test_shutdown_closes_sockets(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr("edumatcher.engine.main.save_gtc_orders", lambda *_: None)
        monkeypatch.setattr("edumatcher.engine.main.save_gtc_combos", lambda *_: None)
        monkeypatch.setattr("edumatcher.engine.main.save_book_stats", lambda *_: None)

        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        engine._shutdown()
        # pub_sock should be marked as closed
        assert pub_sock.closed


# ---------------------------------------------------------------------------
# Engine SMP CANCEL_BOTH
# ---------------------------------------------------------------------------


class TestSMPCancelBoth:
    def test_smp_cancel_both_cancels_aggressor_and_resting(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_new_order(
            _order(side=Side.SELL, price=100.0, smp=SmpAction.CANCEL_BOTH)
        )
        pub_sock.sent.clear()
        engine._handle_new_order(
            _order(side=Side.BUY, price=100.0, smp=SmpAction.CANCEL_BOTH)
        )
        topics = [decode(f)[0] for f in pub_sock.sent]
        assert any("cancelled" in t for t in topics)


# ---------------------------------------------------------------------------
# Engine OCO STOP_LIMIT validation
# ---------------------------------------------------------------------------


class TestOCOStopLimitValidation:
    def test_stop_limit_leg_missing_stop_price(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_oco_order(
            {
                "oco_id": "O1",
                "gateway_id": "GW01",
                "symbol": "AAPL",
                "quantity": 100,
                "tif": "DAY",
                "leg1": {"side": "BUY", "order_type": "LIMIT", "price": 95.0},
                "leg2": {
                    "side": "BUY",
                    "order_type": "STOP_LIMIT",
                    "price": 105.0,
                },  # missing stop_price
            }
        )
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False


# ---------------------------------------------------------------------------
# Engine verbose combo paths
# ---------------------------------------------------------------------------


class TestVerboseCombo:
    def test_verbose_combo_accepted_logs(self, monkeypatch, tmp_path, capsys) -> None:
        engine, pub_sock = _make_engine(
            monkeypatch, tmp_path, symbols=("AAPL", "MSFT"), verbose=True
        )
        _connect(engine)
        combo = ComboOrder.create(
            combo_id="VC01",
            gateway_id="GW01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=10,
                    price=100.0,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=5,
                    price=200.0,
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())
        out = capsys.readouterr().out
        assert "COMBO" in out

    def test_verbose_cascade_cancel_logs(self, monkeypatch, tmp_path, capsys) -> None:
        engine, pub_sock = _make_engine(
            monkeypatch, tmp_path, symbols=("AAPL", "MSFT"), verbose=True
        )
        _connect(engine)
        combo = ComboOrder.create(
            combo_id="VC02",
            gateway_id="GW01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=10,
                    price=100.0,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=5,
                    price=200.0,
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())
        capsys.readouterr()  # clear
        engine._handle_combo_cancel({"gateway_id": "GW01", "combo_id": "VC02"})
        out = capsys.readouterr().out
        assert "CANCELLED" in out or "COMBO" in out


# ---------------------------------------------------------------------------
# Engine verbose OCO paths
# ---------------------------------------------------------------------------


class TestVerboseOCO:
    def test_verbose_oco_accepted_logs(self, monkeypatch, tmp_path, capsys) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, verbose=True)
        _connect(engine)
        engine._handle_oco_order(
            {
                "oco_id": "VO01",
                "gateway_id": "GW01",
                "symbol": "AAPL",
                "quantity": 100,
                "tif": "DAY",
                "leg1": {"side": "BUY", "order_type": "LIMIT", "price": 95.0},
                "leg2": {"side": "BUY", "order_type": "STOP", "stop_price": 105.0},
            }
        )
        out = capsys.readouterr().out
        assert "OCO" in out

    def test_verbose_oco_cancel_logs(self, monkeypatch, tmp_path, capsys) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, verbose=True)
        _connect(engine)
        engine._handle_oco_order(
            {
                "oco_id": "VO02",
                "gateway_id": "GW01",
                "symbol": "AAPL",
                "quantity": 100,
                "tif": "DAY",
                "leg1": {"side": "BUY", "order_type": "LIMIT", "price": 95.0},
                "leg2": {"side": "BUY", "order_type": "STOP", "stop_price": 105.0},
            }
        )
        capsys.readouterr()
        engine._handle_oco_cancel({"gateway_id": "GW01", "oco_id": "VO02"})
        out = capsys.readouterr().out
        assert "OCO" in out


# ---------------------------------------------------------------------------
# Engine: _expire_tif with combo child
# ---------------------------------------------------------------------------


class TestExpireTIFWithCombo:
    def test_expire_combo_child_fails_parent(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
        _connect(engine)
        # Post a combo with ATO legs during OPENING_AUCTION
        engine._session_state = SessionState.OPENING_AUCTION
        combo = ComboOrder.create(
            combo_id="ATO_COMBO",
            gateway_id="GW01",
            combo_type=ComboType.AON,
            tif=TIF.ATO,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=10,
                    price=100.0,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=5,
                    price=200.0,
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())
        pub_sock.sent.clear()
        # Expire all ATO orders
        engine._expire_tif(TIF.ATO)
        topics = [decode(f)[0] for f in pub_sock.sent]
        assert any("expired" in t or "combo.status" in t for t in topics)


# ---------------------------------------------------------------------------
# Engine: handle_cancel with OCO leg
# ---------------------------------------------------------------------------


class TestCancelOCOLeg:
    def test_cancel_oco_leg_cascades(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_oco_order(
            {
                "oco_id": "OC_CASCADE",
                "gateway_id": "GW01",
                "symbol": "AAPL",
                "quantity": 100,
                "tif": "DAY",
                "leg1": {"side": "BUY", "order_type": "LIMIT", "price": 95.0},
                "leg2": {"side": "BUY", "order_type": "STOP", "stop_price": 105.0},
            }
        )
        order_ids = engine._oco_groups.get("OC_CASCADE", [])
        assert len(order_ids) == 2
        pub_sock.sent.clear()
        # Cancel one leg — the other should be cancelled via OCO cascade
        engine._handle_cancel({"order_id": order_ids[0], "gateway_id": "GW01"})
        topics = [decode(f)[0] for f in pub_sock.sent]
        assert any("cancelled" in t for t in topics)


# ---------------------------------------------------------------------------
# Engine: _handle_new_order buy trailing stop with last_price
# ---------------------------------------------------------------------------


class TestTrailingStopBuy:
    def test_buy_trailing_stop_with_prior_price(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._book("AAPL").last_trade_price = 100.0
        o = Order.create(
            symbol="AAPL",
            side=Side.BUY,  # BUY trailing stop
            order_type=OrderType.TRAILING_STOP,
            quantity=100,
            gateway_id="GW01",
            tif=TIF.DAY,
            trail_offset=5.0,
        )
        engine._handle_new_order(o.to_dict())
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is True

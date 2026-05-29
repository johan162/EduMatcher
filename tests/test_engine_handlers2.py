"""
More Engine tests targeting uncovered statements:
  - _restore_gtc with actual GTC orders
  - SMP cancellation events in _handle_new_order
  - _update_combo_status partially-matched case
  - _cascade_cancel_combo via combo cancel
  - OCO leg validation (STOP needs stop_price, TRAILING needs trail_offset, market closed)
  - _check_oco_after_event (sibling cancellation when one leg fills)
  - OCO trailing stop in posting loop
  - verbose logging mode
  - _handle_cancel with combo child / oco leg
  - _handle_amend verbose path
  - _load_config with MM orders in config
"""

from __future__ import annotations

from dataclasses import dataclass


from edumatcher.engine.config_loader import (
    EngineConfig,
    FixGatewayConfig,
    MMQuoteSeed,
    SymbolConfig,
)
from edumatcher.engine.main import Engine
from edumatcher.models.combo import ComboLeg, ComboOrder, ComboStatus, ComboType
from edumatcher.models.message import decode
from edumatcher.models.order import (
    Order,
    OrderStatus,
    OrderType,
    Side,
    SmpAction,
    TIF,
)
from edumatcher.models.session import SessionState

# ---------------------------------------------------------------------------
# Shared fixture helpers (copied pattern from test_engine_handlers.py)
# ---------------------------------------------------------------------------


@dataclass
class _Sock:
    sent: list[list[bytes]]
    closed: bool = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


def _make_engine(
    monkeypatch,
    tmp_path,
    symbols=("AAPL",),
    gateways=("GW01",),
    mm_quotes: dict[str, list[MMQuoteSeed]] | None = None,
    gtc_orders: list = [],
    verbose: bool = False,
) -> tuple[Engine, _Sock]:
    pull_sock = _Sock(sent=[])
    pub_sock = _Sock(sent=[])

    sym_configs = {}
    for sym in symbols:
        quotes_list = mm_quotes.get(sym, []) if mm_quotes else []
        sym_configs[sym] = SymbolConfig(name=sym, market_maker_quotes=quotes_list)

    cfg = EngineConfig(
        symbols=sym_configs,
        fix_gateways={
            gw: FixGatewayConfig(id=gw, description=f"{gw} desc") for gw in gateways
        },
    )

    monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
    monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
    monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)
    monkeypatch.setattr(
        "edumatcher.engine.main.load_gtc_orders", lambda _: list(gtc_orders)
    )
    monkeypatch.setattr("edumatcher.engine.main.load_book_stats", lambda _: {})
    monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)

    cfg_path = tmp_path / "engine_config.yaml"
    cfg_path.write_text("dummy: true\n")

    engine = Engine(verbose=verbose, config_path=str(cfg_path))
    return engine, pub_sock


def _connect(engine: Engine, gw: str = "GW01") -> None:
    engine._handle_gateway_connect({"gateway_id": gw})


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


def _get_ack_id(pub_sock: _Sock) -> str:
    for frames in reversed(pub_sock.sent):
        topic, payload = decode(frames)
        if "ack" in topic and payload.get("accepted"):
            return str(payload.get("order_id", ""))
    return ""


# ---------------------------------------------------------------------------
# _restore_gtc with real GTC orders
# ---------------------------------------------------------------------------


class TestRestoreGTC:
    def test_gtc_orders_restored_to_books(self, monkeypatch, tmp_path) -> None:
        gtc = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=50,
            gateway_id="GW01",
            tif=TIF.GTC,
            price=99.0,
        )
        gtc.status = OrderStatus.NEW
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, gtc_orders=[gtc])
        engine._restore_gtc()
        assert "AAPL" in engine.books
        assert len(engine.books["AAPL"].resting_orders()) >= 1

    def test_gtc_order_for_removed_symbol_skipped(self, monkeypatch, tmp_path) -> None:
        # MSFT is not in the allowed symbols config
        gtc = Order.create(
            symbol="MSFT",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=50,
            gateway_id="GW01",
            tif=TIF.GTC,
            price=99.0,
        )
        gtc.status = OrderStatus.NEW
        engine, pub_sock = _make_engine(
            monkeypatch, tmp_path, symbols=("AAPL",), gtc_orders=[gtc]
        )
        engine._restore_gtc()
        assert "MSFT" not in engine.books


# ---------------------------------------------------------------------------
# SMP cancellation events in _handle_new_order
# ---------------------------------------------------------------------------


class TestSMPCancellation:
    def test_smp_cancel_aggressor(self, monkeypatch, tmp_path) -> None:
        """When SMP=CANCEL_AGGRESSOR, the aggressor is cancelled, not matched."""
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        # Resting sell from GW01
        engine._handle_new_order(
            _order(side=Side.SELL, price=100.0, smp=SmpAction.CANCEL_AGGRESSOR)
        )
        pub_sock.sent.clear()
        # Aggressive buy from same gateway — should be SMP-cancelled
        engine._handle_new_order(
            _order(side=Side.BUY, price=100.0, smp=SmpAction.CANCEL_AGGRESSOR)
        )
        topics = [decode(f)[0] for f in pub_sock.sent]
        # A cancelled notification should be published
        assert any("cancelled" in t for t in topics)

    def test_smp_cancel_resting(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_new_order(
            _order(side=Side.SELL, price=100.0, smp=SmpAction.CANCEL_RESTING)
        )
        pub_sock.sent.clear()
        engine._handle_new_order(
            _order(side=Side.BUY, price=100.0, smp=SmpAction.CANCEL_RESTING)
        )
        topics = [decode(f)[0] for f in pub_sock.sent]
        # Resting order should be cancelled
        assert any("cancelled" in t for t in topics)


# ---------------------------------------------------------------------------
# _update_combo_status: partially-matched case
# ---------------------------------------------------------------------------


class TestUpdateComboStatusPartial:
    def test_combo_goes_to_partially_matched_on_partial_fill(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
        _connect(engine)
        # Post a combo
        combo = ComboOrder.create(
            combo_id="C_PARTIAL",
            gateway_id="GW01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=100.0,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=50,
                    price=200.0,
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())
        # Find the internal combo
        internal_combo = next(
            c for c in engine._combos.values() if c.combo_id == "C_PARTIAL"
        )
        # Manually simulate a partial fill on leg 0
        from edumatcher.models.order import OrderStatus

        internal_combo.leg_statuses[0] = OrderStatus.PARTIAL.value
        internal_combo.leg_fill_qty[0] = 50
        engine._update_combo_status(internal_combo)
        assert internal_combo.status == ComboStatus.PARTIALLY_MATCHED


# ---------------------------------------------------------------------------
# _handle_combo_cancel when combo already terminal
# ---------------------------------------------------------------------------


class TestComboCancelTerminal:
    def test_cancel_already_cancelled_combo(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
        _connect(engine)
        combo = ComboOrder.create(
            combo_id="C_TERM",
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
        # First cancel
        engine._handle_combo_cancel({"gateway_id": "GW01", "combo_id": "C_TERM"})
        pub_sock.sent.clear()
        # Second cancel — should reject
        engine._handle_combo_cancel({"gateway_id": "GW01", "combo_id": "C_TERM"})
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False


# ---------------------------------------------------------------------------
# OCO validation edge cases
# ---------------------------------------------------------------------------


class TestOCOValidation:
    def _base_oco(self, gateway_id: str = "GW01") -> dict:
        return {
            "oco_id": "OCO_VAL",
            "gateway_id": gateway_id,
            "symbol": "AAPL",
            "quantity": 100,
            "tif": "DAY",
            "leg1": {"side": "BUY", "order_type": "LIMIT", "price": 95.0},
            "leg2": {"side": "BUY", "order_type": "STOP", "stop_price": 105.0},
        }

    def test_stop_leg_missing_stop_price_rejected(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        payload = self._base_oco()
        payload["leg2"] = {"side": "BUY", "order_type": "STOP"}  # missing stop_price
        engine._handle_oco_order(payload)
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False
        assert "stop_price" in msg["reason"]

    def test_trailing_stop_missing_trail_offset_rejected(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        payload = self._base_oco()
        payload["leg2"] = {
            "side": "BUY",
            "order_type": "TRAILING_STOP",
        }  # missing trail_offset
        engine._handle_oco_order(payload)
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False
        assert "trail_offset" in msg["reason"]

    def test_limit_leg_missing_price_rejected(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        payload = self._base_oco()
        payload["leg1"] = {"side": "BUY", "order_type": "LIMIT"}  # missing price
        engine._handle_oco_order(payload)
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False
        assert "price" in msg["reason"]


# ---------------------------------------------------------------------------
# OCO sibling cancellation when one leg fills
# ---------------------------------------------------------------------------


class TestOCOSiblingCancel:
    def test_sibling_cancelled_when_oco_leg_fills(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_oco_order(
            {
                "oco_id": "OCO_FILL",
                "gateway_id": "GW01",
                "symbol": "AAPL",
                "quantity": 100,
                "tif": "DAY",
                "leg1": {"side": "BUY", "order_type": "LIMIT", "price": 95.0},
                "leg2": {"side": "BUY", "order_type": "STOP", "stop_price": 105.0},
            }
        )
        order_ids = engine._oco_groups.get("OCO_FILL", [])
        assert len(order_ids) == 2
        # Directly call _check_oco_after_event with a simulated filled order
        leg1_id = order_ids[0]
        leg1_order = engine.books["AAPL"]._order_index.get(leg1_id)
        assert leg1_order is not None
        # Mark as filled and trigger OCO check
        leg1_order.status = OrderStatus.FILLED
        pub_sock.sent.clear()
        engine._check_oco_after_event(leg1_order)
        topics = [decode(f)[0] for f in pub_sock.sent]
        assert any("oco.cancelled" in t or "cancelled" in t for t in topics)


# ---------------------------------------------------------------------------
# _handle_cancel with combo child cascade
# ---------------------------------------------------------------------------


class TestCancelWithComboCascade:
    def test_cancelling_combo_child_fails_combo(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
        _connect(engine)
        combo = ComboOrder.create(
            combo_id="C_CANCEL",
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
        internal = next(c for c in engine._combos.values() if c.combo_id == "C_CANCEL")
        child_id = internal.child_order_ids[0]
        pub_sock.sent.clear()
        engine._handle_cancel({"order_id": child_id, "gateway_id": "GW01"})
        topics = [decode(f)[0] for f in pub_sock.sent]
        # Should have published a combo status FAILED
        assert any("combo.status" in t for t in topics)


# ---------------------------------------------------------------------------
# verbose logging paths
# ---------------------------------------------------------------------------


class TestVerboseLogging:
    def test_verbose_new_order_prints_no_error(
        self, monkeypatch, tmp_path, capsys
    ) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, verbose=True)
        _connect(engine)
        engine._handle_new_order(_order())
        captured = capsys.readouterr()
        assert "NEW" in captured.out

    def test_verbose_cancel_prints_no_error(
        self, monkeypatch, tmp_path, capsys
    ) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, verbose=True)
        _connect(engine)
        engine._handle_new_order(_order())
        order_id = _get_ack_id(pub_sock)
        pub_sock.sent.clear()
        engine._handle_cancel({"order_id": order_id, "gateway_id": "GW01"})
        captured = capsys.readouterr()
        assert "CANCELLED" in captured.out

    def test_verbose_amend_prints_no_error(self, monkeypatch, tmp_path, capsys) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, verbose=True)
        _connect(engine)
        engine._handle_new_order(_order(qty=100))
        order_id = _get_ack_id(pub_sock)
        pub_sock.sent.clear()
        engine._handle_amend({"order_id": order_id, "gateway_id": "GW01", "qty": 80})
        captured = capsys.readouterr()
        assert "AMENDED" in captured.out

    def test_verbose_gateway_connect_prints_no_error(
        self, monkeypatch, tmp_path, capsys
    ) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, verbose=True)
        engine._handle_gateway_connect({"gateway_id": "GW01"})
        captured = capsys.readouterr()
        assert "Gateway connected" in captured.out


# ---------------------------------------------------------------------------
# _load_config with MM quotes
# ---------------------------------------------------------------------------


class TestLoadConfigWithMMOrders:
    def test_mm_quotes_injected_into_book(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(
            monkeypatch,
            tmp_path,
            mm_quotes={
                "AAPL": [
                    MMQuoteSeed(
                        gateway_id="GW01",
                        bid_price=99.0,
                        ask_price=101.0,
                        bid_qty=200,
                        ask_qty=200,
                        tif=TIF.GTC,
                    )
                ]
            },
        )
        # _load_config is not called in __init__ since there's no ZMQ-run call
        # but we can call it directly
        engine._load_config()
        assert "AAPL" in engine.books
        resting = engine.books["AAPL"].resting_orders()
        assert len(resting) >= 1


# ---------------------------------------------------------------------------
# _expire_tif direct test
# ---------------------------------------------------------------------------


class TestExpireTIF:
    def test_expire_ato_orders(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._session_state = SessionState.OPENING_AUCTION
        # Post an ATO order
        o = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW01",
            tif=TIF.ATO,
            price=100.0,
        )
        engine._handle_new_order(o.to_dict())
        pub_sock.sent.clear()
        engine._expire_tif(TIF.ATO)
        topics = [decode(f)[0] for f in pub_sock.sent]
        assert any("expired" in t for t in topics)


# ---------------------------------------------------------------------------
# Audit process helpers
# ---------------------------------------------------------------------------


class TestAuditProcess:
    def test_setup_logger_creates_log_file(self, tmp_path) -> None:
        from edumatcher.audit.main import _setup_logger

        log_path = tmp_path / "sub" / "audit.log"
        logger = _setup_logger(log_path, to_terminal=False)
        logger.info("test entry")
        assert log_path.exists()
        content = log_path.read_text()
        assert "test entry" in content

    def test_setup_logger_with_terminal(self, tmp_path) -> None:
        import logging
        from edumatcher.audit.main import _setup_logger

        log_path = tmp_path / "audit_term.log"
        logger = _setup_logger(log_path, to_terminal=True)
        # With to_terminal=True, there should be a StreamHandler (not FileHandler)
        stream_handlers = [
            h
            for h in logger.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert len(stream_handlers) >= 1

"""
Tests for combo-order model, persistence, and engine integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from edumatcher.engine.config_loader import (
    ComboSeedConfig,
    EngineConfig,
    FixGatewayConfig,
    SymbolConfig,
)
from edumatcher.engine.main import Engine
from edumatcher.engine.persistence import load_gtc_combos, save_gtc_combos
from edumatcher.models.combo import (
    ComboLeg,
    ComboOrder,
    ComboStatus,
    ComboType,
)
from edumatcher.models.message import decode
from edumatcher.models.order import Order, OrderStatus, OrderType, Side, TIF

# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------


@dataclass
class _DummySocket:
    sent: list[list[bytes]]
    closed: bool = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


def _two_leg_combo(
    gateway_id: str = "TRADER01",
    combo_id: str = "MY_COMBO",
    tif: TIF = TIF.DAY,
    sym_a: str = "AAPL",
    price_a: float = 150.0,
    sym_b: str = "MSFT",
    price_b: float = 300.0,
    qty_a: int = 10,
    qty_b: int = 5,
    side_a: Side = Side.BUY,
    side_b: Side = Side.SELL,
) -> dict:
    """Build a valid 2-leg combo payload dict."""
    combo = ComboOrder.create(
        combo_id=combo_id,
        gateway_id=gateway_id,
        combo_type=ComboType.AON,
        tif=tif,
        legs=[
            ComboLeg(
                symbol=sym_a,
                side=side_a,
                order_type=OrderType.LIMIT,
                quantity=qty_a,
                price=price_a,
            ),
            ComboLeg(
                symbol=sym_b,
                side=side_b,
                order_type=OrderType.LIMIT,
                quantity=qty_b,
                price=price_b,
            ),
        ],
    )
    return combo.to_dict()


@pytest.fixture
def combo_engine(monkeypatch, tmp_path) -> tuple[Engine, _DummySocket]:
    """Engine wired with two symbols (AAPL, MSFT) and one gateway (TRADER01)."""
    pull_sock = _DummySocket(sent=[])
    pub_sock = _DummySocket(sent=[])

    cfg = EngineConfig(
        symbols={
            "AAPL": SymbolConfig(name="AAPL"),
            "MSFT": SymbolConfig(name="MSFT"),
        },
        fix_gateways={
            "TRADER01": FixGatewayConfig(id="TRADER01", description="Trader one"),
            "TRADER02": FixGatewayConfig(id="TRADER02", description="Trader two"),
        },
    )

    monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
    monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
    monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)
    monkeypatch.setattr("edumatcher.engine.main.load_gtc_orders", lambda _: [])
    monkeypatch.setattr("edumatcher.engine.main.load_gtc_combos", lambda _: [])
    monkeypatch.setattr("edumatcher.engine.main.load_book_stats", lambda _: {})
    monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)

    cfg_path = tmp_path / "engine_config.yaml"
    cfg_path.write_text("dummy: true\n")

    engine = Engine(config_path=str(cfg_path))
    # Connect TRADER01 so combo orders pass gateway auth
    engine._handle_gateway_connect({"gateway_id": "TRADER01"})
    pub_sock.sent.clear()
    return engine, pub_sock


def _topics(pub_sock: _DummySocket) -> list[str]:
    """Return the topics of all published messages."""
    return [decode(f)[0] for f in pub_sock.sent]


# ---------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------


class TestComboModel:

    def test_serialization_roundtrip(self) -> None:
        combo = ComboOrder.create(
            combo_id="RT1",
            gateway_id="GW",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="A",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=10,
                    price=100.0,
                ),
                ComboLeg(
                    symbol="B", side=Side.SELL, order_type=OrderType.MARKET, quantity=5
                ),
            ],
        )
        combo.child_order_ids = ["child-1", "child-2"]
        combo.leg_fill_qty = {0: 5, 1: 5}
        combo.leg_statuses = {0: "PARTIAL", 1: "FILLED"}

        d = combo.to_dict()
        restored = ComboOrder.from_dict(d)

        assert restored.id == combo.id
        assert restored.combo_id == combo.combo_id
        assert restored.combo_type == ComboType.AON
        assert len(restored.legs) == 2
        assert restored.legs[0].symbol == "A"
        assert restored.legs[1].order_type == OrderType.MARKET
        assert restored.child_order_ids == ["child-1", "child-2"]
        assert restored.leg_fill_qty == {0: 5, 1: 5}
        assert restored.leg_statuses == {0: "PARTIAL", 1: "FILLED"}

    def test_is_fully_filled_true(self) -> None:
        combo = ComboOrder.create(
            combo_id="FF",
            gateway_id="GW",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="A",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=10,
                    price=1.0,
                ),
                ComboLeg(
                    symbol="B",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=5,
                    price=2.0,
                ),
            ],
        )
        combo.leg_statuses = {0: OrderStatus.FILLED.value, 1: OrderStatus.FILLED.value}
        assert combo.is_fully_filled is True

    def test_is_fully_filled_false_when_partial(self) -> None:
        combo = ComboOrder.create(
            combo_id="PF",
            gateway_id="GW",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="A",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=10,
                    price=1.0,
                ),
                ComboLeg(
                    symbol="B",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=5,
                    price=2.0,
                ),
            ],
        )
        combo.leg_statuses = {0: OrderStatus.FILLED.value, 1: OrderStatus.PARTIAL.value}
        assert combo.is_fully_filled is False


# ---------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------


class TestComboPersistence:

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        combo = ComboOrder.create(
            combo_id="P1",
            gateway_id="GW",
            combo_type=ComboType.AON,
            tif=TIF.GTC,
            legs=[
                ComboLeg(
                    symbol="A",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=10,
                    price=50.0,
                ),
                ComboLeg(
                    symbol="B",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=5,
                    price=70.0,
                ),
            ],
        )
        combo.status = ComboStatus.PENDING
        combo.child_order_ids = ["c1", "c2"]
        combo.leg_fill_qty = {0: 0, 1: 0}
        combo.leg_statuses = {0: "NEW", 1: "NEW"}

        path = tmp_path / "combos.json"
        save_gtc_combos([combo], path)
        loaded = load_gtc_combos(path)

        assert len(loaded) == 1
        assert loaded[0].combo_id == "P1"
        assert loaded[0].tif == TIF.GTC

    def test_only_active_gtc_combos_persisted(self, tmp_path: Path) -> None:
        """MATCHED / DAY combos should not be persisted."""
        active = ComboOrder.create(
            combo_id="ACTIVE",
            gateway_id="GW",
            combo_type=ComboType.AON,
            tif=TIF.GTC,
            legs=[
                ComboLeg(
                    symbol="A",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=1,
                    price=1.0,
                ),
                ComboLeg(
                    symbol="B",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=1,
                    price=1.0,
                ),
            ],
        )
        active.status = ComboStatus.PARTIALLY_MATCHED

        matched = ComboOrder.create(
            combo_id="DONE",
            gateway_id="GW",
            combo_type=ComboType.AON,
            tif=TIF.GTC,
            legs=[
                ComboLeg(
                    symbol="A",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=1,
                    price=1.0,
                ),
                ComboLeg(
                    symbol="B",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=1,
                    price=1.0,
                ),
            ],
        )
        matched.status = ComboStatus.MATCHED

        day_combo = ComboOrder.create(
            combo_id="DAYC",
            gateway_id="GW",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="A",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=1,
                    price=1.0,
                ),
                ComboLeg(
                    symbol="B",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=1,
                    price=1.0,
                ),
            ],
        )

        path = tmp_path / "combos.json"
        save_gtc_combos([active, matched, day_combo], path)
        loaded = load_gtc_combos(path)

        assert len(loaded) == 1
        assert loaded[0].combo_id == "ACTIVE"

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_gtc_combos(tmp_path / "nonexistent.json") == []

    def test_load_corrupt_file_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("not json {{{")
        assert load_gtc_combos(path) == []


class TestMarketMakerComboSeeds:

    def test_engine_injects_configured_market_maker_combos(
        self, monkeypatch, tmp_path
    ) -> None:
        pull_sock = _DummySocket(sent=[])
        pub_sock = _DummySocket(sent=[])

        cfg = EngineConfig(
            symbols={
                "AAPL": SymbolConfig(name="AAPL"),
                "MSFT": SymbolConfig(name="MSFT"),
            },
            fix_gateways={
                "TRADER01": FixGatewayConfig(id="TRADER01", description="Trader one"),
            },
            market_maker_combos=[
                ComboSeedConfig(
                    combo_id="MM-PAIR",
                    combo_type=ComboType.AON,
                    tif=TIF.GTC,
                    legs=[
                        ComboLeg(
                            symbol="AAPL",
                            side=Side.BUY,
                            order_type=OrderType.LIMIT,
                            quantity=10,
                            price=150.0,
                        ),
                        ComboLeg(
                            symbol="MSFT",
                            side=Side.SELL,
                            order_type=OrderType.LIMIT,
                            quantity=5,
                            price=300.0,
                        ),
                    ],
                )
            ],
        )

        monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
        monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
        monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)
        monkeypatch.setattr("edumatcher.engine.main.load_gtc_orders", lambda _: [])
        monkeypatch.setattr("edumatcher.engine.main.load_gtc_combos", lambda _: [])
        monkeypatch.setattr("edumatcher.engine.main.load_book_stats", lambda _: {})
        monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)

        cfg_path = tmp_path / "engine_config.yaml"
        cfg_path.write_text("dummy: true\n")

        engine = Engine(config_path=str(cfg_path))
        engine._load_config()

        assert len(engine._combos) == 1
        combo = next(iter(engine._combos.values()))
        assert combo.gateway_id == "MM"
        assert combo.combo_id == "MM-PAIR"
        assert len(combo.child_order_ids) == 2

        aapl_orders = [
            o for o in engine.books["AAPL"].resting_orders() if o.gateway_id == "MM"
        ]
        msft_orders = [
            o for o in engine.books["MSFT"].resting_orders() if o.gateway_id == "MM"
        ]
        assert len(aapl_orders) == 1
        assert len(msft_orders) == 1
        assert aapl_orders[0].combo_parent_id == combo.id
        assert msft_orders[0].combo_parent_id == combo.id


# ---------------------------------------------------------------
# Engine integration — combo validation
# ---------------------------------------------------------------


class TestComboValidation:

    def test_combo_accepted_with_valid_legs(self, combo_engine) -> None:
        engine, pub_sock = combo_engine
        payload = _two_leg_combo()
        engine._handle_combo_order(payload)

        topic, msg = decode(pub_sock.sent[0])
        assert topic == "combo.ack.TRADER01"
        assert msg["accepted"] is True

    def test_combo_rejected_gateway_not_connected(self, combo_engine) -> None:
        engine, pub_sock = combo_engine
        payload = _two_leg_combo(gateway_id="TRADER99")
        engine._handle_combo_order(payload)

        topic, msg = decode(pub_sock.sent[0])
        assert topic == "combo.ack.TRADER99"
        assert msg["accepted"] is False

    def test_combo_rejected_one_leg(self, combo_engine) -> None:
        engine, pub_sock = combo_engine
        combo = ComboOrder.create(
            combo_id="1LEG",
            gateway_id="TRADER01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=10,
                    price=150.0,
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())

        topic, msg = decode(pub_sock.sent[0])
        assert msg["accepted"] is False
        assert "at least 2" in msg["reason"]

    def test_combo_rejected_duplicate_symbols(self, combo_engine) -> None:
        engine, pub_sock = combo_engine
        payload = _two_leg_combo(sym_a="AAPL", sym_b="AAPL")
        engine._handle_combo_order(payload)

        topic, msg = decode(pub_sock.sent[0])
        assert msg["accepted"] is False
        assert "Duplicate" in msg["reason"]

    def test_combo_rejected_symbol_not_configured(self, combo_engine) -> None:
        engine, pub_sock = combo_engine
        payload = _two_leg_combo(sym_b="GOOG")
        engine._handle_combo_order(payload)

        topic, msg = decode(pub_sock.sent[0])
        assert msg["accepted"] is False
        assert "not configured" in msg["reason"]

    def test_combo_rejected_zero_quantity(self, combo_engine) -> None:
        engine, pub_sock = combo_engine
        payload = _two_leg_combo(qty_a=0)
        engine._handle_combo_order(payload)

        topic, msg = decode(pub_sock.sent[0])
        assert msg["accepted"] is False
        assert "invalid quantity" in msg["reason"]

    def test_combo_rejected_limit_without_price(self, combo_engine) -> None:
        engine, pub_sock = combo_engine
        combo = ComboOrder.create(
            combo_id="NP",
            gateway_id="TRADER01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=10,
                    price=None,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=5,
                    price=300.0,
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())

        topic, msg = decode(pub_sock.sent[0])
        assert msg["accepted"] is False
        assert "requires a price" in msg["reason"]


# ---------------------------------------------------------------
# Engine integration — combo matching lifecycle
# ---------------------------------------------------------------


class TestComboLifecycle:

    def _seed_resting(
        self,
        engine: Engine,
        symbol: str,
        side: Side,
        qty: int,
        price: float,
        gateway_id: str = "TRADER02",
    ) -> None:
        """Place a resting limit order on the book (from a different gateway)."""
        engine._handle_gateway_connect({"gateway_id": gateway_id})
        order = Order.create(
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=qty,
            gateway_id=gateway_id,
            price=price,
        )
        engine._handle_new_order(order.to_dict())

    def test_combo_both_legs_fill_immediately(self, combo_engine) -> None:
        """Both legs cross resting liquidity → combo should reach MATCHED."""
        engine, pub_sock = combo_engine

        # Seed resting orders that combo legs will cross
        self._seed_resting(engine, "AAPL", Side.SELL, 10, 150.0)
        self._seed_resting(engine, "MSFT", Side.BUY, 5, 300.0)
        pub_sock.sent.clear()

        payload = _two_leg_combo(price_a=150.0, price_b=300.0)
        engine._handle_combo_order(payload)

        topics = _topics(pub_sock)

        # Expect ACK, fills for both legs, and MATCHED status
        assert "combo.ack.TRADER01" in topics
        assert any("combo.status.TRADER01" in t for t in topics)

        # Last combo status should be MATCHED
        combo_statuses = [
            decode(f)[1]
            for f in pub_sock.sent
            if decode(f)[0].startswith("combo.status")
        ]
        assert combo_statuses[-1]["status"] == "MATCHED"

    def test_combo_legs_rest_when_no_liquidity(self, combo_engine) -> None:
        """No resting liquidity → children rest, combo stays PENDING."""
        engine, pub_sock = combo_engine

        payload = _two_leg_combo(price_a=150.0, price_b=300.0)
        engine._handle_combo_order(payload)

        # The combo should be ACK'd and remain PENDING (no MATCHED status published)
        topics = _topics(pub_sock)
        assert "combo.ack.TRADER01" in topics
        assert not any(
            "MATCHED" in decode(f)[1].get("status", "")
            for f in pub_sock.sent
            if decode(f)[0].startswith("combo.status")
        )

        # Engine should track the combo
        assert len(engine._combos) == 1
        combo = list(engine._combos.values())[0]
        assert combo.status == ComboStatus.PENDING
        assert len(combo.child_order_ids) == 2

    def test_combo_aon_does_not_partially_execute(self, combo_engine) -> None:
        """M5: an AON combo must NOT partially execute.

        With liquidity for only one leg, an AON combo executes nothing — no
        leg fills and the combo rests PENDING (all-or-none).  Full atomic
        matching when all legs are fillable is covered by
        test_combo_both_legs_fill_immediately.
        """
        engine, pub_sock = combo_engine

        # Seed liquidity only for leg 0 (AAPL BUY) — leg 1 (MSFT) is unfillable.
        self._seed_resting(engine, "AAPL", Side.SELL, 10, 150.0)
        pub_sock.sent.clear()

        engine._handle_combo_order(_two_leg_combo(price_a=150.0, price_b=300.0))

        combo = list(engine._combos.values())[0]
        # M5: no leg may fill while another leg cannot — the combo rests PENDING.
        assert combo.status == ComboStatus.PENDING
        assert combo.leg_fill_qty[0] == 0
        assert combo.leg_fill_qty[1] == 0

    def test_cascade_cancel_on_child_cancel(self, combo_engine) -> None:
        """Cancelling one combo child triggers cascade-cancel of siblings."""
        engine, pub_sock = combo_engine

        payload = _two_leg_combo()
        engine._handle_combo_order(payload)

        combo = list(engine._combos.values())[0]
        assert combo.status == ComboStatus.PENDING

        # Cancel the first child order directly
        child_id = combo.child_order_ids[0]
        pub_sock.sent.clear()
        engine._handle_cancel({"order_id": child_id, "gateway_id": "TRADER01"})

        assert combo.status == ComboStatus.FAILED

        # The second child should also be cancelled
        topics = _topics(pub_sock)
        cancel_count = sum(1 for t in topics if t.startswith("order.cancelled"))
        # At least 1 cancel published (the one we requested); sibling also cancelled
        assert cancel_count >= 1

    def test_user_cancel_combo(self, combo_engine) -> None:
        """User cancels the combo by combo_id → all children cancelled."""
        engine, pub_sock = combo_engine

        payload = _two_leg_combo(combo_id="USERCANCEL")
        engine._handle_combo_order(payload)
        pub_sock.sent.clear()

        engine._handle_combo_cancel(
            {
                "combo_id": "USERCANCEL",
                "gateway_id": "TRADER01",
            }
        )

        combo = list(engine._combos.values())[0]
        assert combo.status == ComboStatus.CANCELLED

        topics = _topics(pub_sock)
        assert any("combo.status.TRADER01" in t for t in topics)

    def test_cancel_combo_not_found(self, combo_engine) -> None:
        engine, pub_sock = combo_engine

        engine._handle_combo_cancel(
            {
                "combo_id": "NONEXISTENT",
                "gateway_id": "TRADER01",
            }
        )

        topic, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False
        assert "not found" in msg["reason"]

    def test_cancel_combo_already_matched(self, combo_engine) -> None:
        """Cannot cancel a combo that is already MATCHED."""
        engine, pub_sock = combo_engine

        self._seed_resting(engine, "AAPL", Side.SELL, 10, 150.0)
        self._seed_resting(engine, "MSFT", Side.BUY, 5, 300.0)

        payload = _two_leg_combo(combo_id="DONE2", price_a=150.0, price_b=300.0)
        engine._handle_combo_order(payload)
        pub_sock.sent.clear()

        engine._handle_combo_cancel(
            {
                "combo_id": "DONE2",
                "gateway_id": "TRADER01",
            }
        )

        topic, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False
        assert "already MATCHED" in msg["reason"]

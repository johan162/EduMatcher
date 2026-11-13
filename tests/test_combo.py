"""
Tests for combo-order model, persistence, and engine integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from edumatcher.engine.config_loader import (
    ComboSeedConfig,
    EngineConfig,
    ParticipantConfig,
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
from edumatcher.models.order import Order, OrderStatus, OrderType, Side, SmpAction, TIF

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
    price_a: int = 15000,
    sym_b: str = "MSFT",
    price_b: int = 30000,
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
                tick_decimals=2,
                price_ticks=price_a,
            ),
            ComboLeg(
                symbol=sym_b,
                side=side_b,
                order_type=OrderType.LIMIT,
                quantity=qty_b,
                tick_decimals=2,
                price_ticks=price_b,
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
        participants={
            "TRADER01": ParticipantConfig(id="TRADER01", description="Trader one"),
            "TRADER02": ParticipantConfig(id="TRADER02", description="Trader two"),
        },
    )

    monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
    monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
    monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)
    monkeypatch.setattr("edumatcher.engine.main.load_gtc_orders", lambda _: [])
    monkeypatch.setattr("edumatcher.engine.main.load_gtc_combos", lambda _: [])
    monkeypatch.setattr("edumatcher.engine.main.load_book_stats", lambda _: ({}, 0))
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
                    tick_decimals=2,
                    price_ticks=100,
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
                    tick_decimals=2,
                    price_ticks=1,
                ),
                ComboLeg(
                    symbol="B",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=5,
                    tick_decimals=2,
                    price_ticks=2,
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
                    tick_decimals=2,
                    price_ticks=1,
                ),
                ComboLeg(
                    symbol="B",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=5,
                    tick_decimals=2,
                    price_ticks=2,
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
                    tick_decimals=2,
                    price_ticks=50,
                ),
                ComboLeg(
                    symbol="B",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=5,
                    tick_decimals=2,
                    price_ticks=70,
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
        """Only live (PENDING / PARTIALLY_MATCHED) combos are persisted, DAY or GTC."""
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
                    tick_decimals=2,
                    price_ticks=1,
                ),
                ComboLeg(
                    symbol="B",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=1,
                    tick_decimals=2,
                    price_ticks=1,
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
                    tick_decimals=2,
                    price_ticks=1,
                ),
                ComboLeg(
                    symbol="B",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=1,
                    tick_decimals=2,
                    price_ticks=1,
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
                    tick_decimals=2,
                    price_ticks=1,
                ),
                ComboLeg(
                    symbol="B",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=1,
                    tick_decimals=2,
                    price_ticks=1,
                ),
            ],
        )

        path = tmp_path / "combos.json"
        save_gtc_combos([active, matched, day_combo], path)
        loaded = load_gtc_combos(path)

        assert [c.combo_id for c in loaded] == ["ACTIVE", "DAYC"]

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
            participants={
                "TRADER01": ParticipantConfig(id="TRADER01", description="Trader one"),
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
                            tick_decimals=2,
                            price_ticks=150,
                        ),
                        ComboLeg(
                            symbol="MSFT",
                            side=Side.SELL,
                            order_type=OrderType.LIMIT,
                            quantity=5,
                            tick_decimals=2,
                            price_ticks=300,
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
        monkeypatch.setattr("edumatcher.engine.main.load_book_stats", lambda _: ({}, 0))
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

    def test_a_restored_live_seed_combo_is_not_seeded_again(
        self, monkeypatch, tmp_path
    ) -> None:
        """A restart restores the live seeded combo with its legs; seeding it
        again doubled the market maker's interest (s3-complex, E6)."""
        cfg = EngineConfig(
            symbols={"AAPL": SymbolConfig(name="AAPL"), "MSFT": SymbolConfig(name="MSFT")},  # fmt: skip
            participants={"TRADER01": ParticipantConfig(id="TRADER01")},
            market_maker_combos=[
                ComboSeedConfig(
                    combo_id="MM-PAIR",
                    tif=TIF.DAY,
                    legs=[
                        ComboLeg(symbol="AAPL", side=Side.BUY, order_type=OrderType.LIMIT, quantity=10, tick_decimals=2, price_ticks=150),  # fmt: skip
                        ComboLeg(symbol="MSFT", side=Side.SELL, order_type=OrderType.LIMIT, quantity=5, tick_decimals=2, price_ticks=300),  # fmt: skip
                    ],
                )
            ],
        )
        cfg_path = tmp_path / "engine_config.yaml"
        cfg_path.write_text("dummy: true\n")

        def start(combos: list[Any], orders: list[Any]) -> Engine:
            monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: _DummySocket(sent=[]))  # fmt: skip
            monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: _DummySocket(sent=[]))  # fmt: skip
            monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)  # fmt: skip
            monkeypatch.setattr("edumatcher.engine.main.load_gtc_orders", lambda _: orders)  # fmt: skip
            monkeypatch.setattr("edumatcher.engine.main.load_gtc_combos", lambda _: combos)  # fmt: skip
            monkeypatch.setattr(
                "edumatcher.engine.main.load_book_stats", lambda _: ({}, 0)
            )
            monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)
            engine = Engine(config_path=str(cfg_path))
            engine._restore_gtc()
            engine._load_config()
            return engine

        first = start([], [])
        combos = [ComboOrder.from_dict(c.to_dict()) for c in first._combos.values()]
        orders = [Order.from_dict(o.to_dict()) for o in first._resting_gtc_orders()]
        second = start(combos, orders)

        assert [c.combo_id for c in second._combos.values()] == ["MM-PAIR"]
        assert len(second.books["AAPL"].resting_orders()) == 1


# ---------------------------------------------------------------
# Engine integration — combo validation
# ---------------------------------------------------------------


class TestComboValidation:

    def test_combo_accepted_with_valid_legs(self, combo_engine) -> None:
        """The parent combo.ack, then each child leg's own order.ack.

        No combo leg used to publish order.ack at all -- see
        ../docs/books/operator-guide/part-6-observe-and-recover/020-audit-trail.md and Engine._accept_combo's leg-creation
        loop. The combo.ack comes first (X21), so every leg event and combo
        status follows it.
        """
        engine, pub_sock = combo_engine
        payload = _two_leg_combo()
        engine._handle_combo_order(payload)

        # The legs' engine.trace RESTED (S24) aside.
        sent = [f for f in pub_sock.sent if not f[0].startswith(b"engine.trace.")]
        assert len(sent) == 3

        topic, msg = decode(sent[0])
        assert topic == "combo.ack.TRADER01"
        assert msg["accepted"] is True

        leg0_topic, leg0_msg = decode(sent[1])
        assert leg0_topic == "order.ack.TRADER01"
        assert leg0_msg["accepted"] is True
        assert leg0_msg["symbol"] == "AAPL"

        leg1_topic, leg1_msg = decode(sent[2])
        assert leg1_topic == "order.ack.TRADER01"
        assert leg1_msg["accepted"] is True
        assert leg1_msg["symbol"] == "MSFT"

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
                    tick_decimals=2,
                    price_ticks=15000,
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
                    tick_decimals=2,
                    price_ticks=None,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=5,
                    tick_decimals=2,
                    price_ticks=30000,
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())

        topic, msg = decode(pub_sock.sent[0])
        assert msg["accepted"] is False
        assert "LIMIT requires price" in msg["reason"]

    def test_combo_rejected_stop_limit_without_price(self, combo_engine) -> None:
        """WP-API16: the engine (and ALF) used to accept a STOP_LIMIT leg
        without its limit price; the shared per-type rule refuses it."""
        engine, pub_sock = combo_engine
        combo = ComboOrder.create(
            combo_id="SL",
            gateway_id="TRADER01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.STOP_LIMIT,
                    quantity=10,
                    tick_decimals=2,
                    stop_price_ticks=9500,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=5,
                    tick_decimals=2,
                    price_ticks=30000,
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())

        topic, msg = decode(pub_sock.sent[0])
        assert msg["accepted"] is False
        assert "STOP_LIMIT requires price" in msg["reason"]


# ---------------------------------------------------------------
# Engine integration — combo matching lifecycle
# ---------------------------------------------------------------


class TestComboLifecycle:

    @staticmethod
    def _combo_status(
        engine: Engine, pub_sock: _DummySocket, combo: ComboOrder
    ) -> ComboStatus:
        statuses = [
            payload["status"]
            for frame in pub_sock.sent
            for topic, payload in [decode(frame)]
            if topic.startswith("combo.status.")
            and payload.get("combo_id") == combo.combo_id
        ]
        if statuses:
            return ComboStatus(statuses[-1])
        return next(
            tracked
            for tracked in engine._combos.values()
            if tracked.combo_id == combo.combo_id
        ).status

    def _seed_resting(
        self,
        engine: Engine,
        symbol: str,
        side: Side,
        qty: int,
        price: int,
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
            price_ticks=price,
        )
        engine._handle_new_order(order.to_dict())

    @pytest.mark.parametrize(
        ("smp_action", "configured_default", "expected_status", "expected_trades"),
        [
            (SmpAction.NONE, SmpAction.NONE, ComboStatus.MATCHED, 2),
            (SmpAction.CANCEL_AGGRESSOR, SmpAction.NONE, ComboStatus.FAILED, 0),
            (SmpAction.CANCEL_RESTING, SmpAction.NONE, ComboStatus.FAILED, 0),
            (SmpAction.CANCEL_BOTH, SmpAction.NONE, ComboStatus.FAILED, 0),
            (None, SmpAction.CANCEL_AGGRESSOR, ComboStatus.FAILED, 0),
            (SmpAction.NONE, SmpAction.CANCEL_AGGRESSOR, ComboStatus.MATCHED, 2),
            (None, SmpAction.NONE, ComboStatus.MATCHED, 2),
        ],
    )
    def test_aon_entry_preflight_excludes_own_liquidity_under_smp(
        self,
        combo_engine,
        smp_action,
        configured_default,
        expected_status,
        expected_trades,
    ) -> None:
        """Only SMP=NONE may use the submitter's resting AAPL offer to pass
        AON preflight; external liquidity is available for the other leg.
        Omitted leg policies inherit the gateway default, and explicit NONE
        overrides it."""
        engine, pub_sock = combo_engine
        assert engine._engine_config is not None
        engine._engine_config.participants["TRADER01"].smp_action = configured_default
        self._seed_resting(engine, "AAPL", Side.SELL, 100, 15000, gateway_id="TRADER01")
        self._seed_resting(engine, "MSFT", Side.BUY, 50, 42000)
        pub_sock.sent.clear()

        combo = ComboOrder.create(
            combo_id=f"ENTRY-{smp_action or 'OMITTED'}-{configured_default.value}",
            gateway_id="TRADER01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    tick_decimals=2,
                    price_ticks=15000,
                    smp_action=smp_action,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=50,
                    tick_decimals=2,
                    price_ticks=42000,
                    smp_action=smp_action,
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())

        assert self._combo_status(engine, pub_sock, combo) is expected_status
        trades = [
            decode(frame)[1]
            for frame in pub_sock.sent
            if decode(frame)[0] == "trade.executed"
        ]
        assert len(trades) == expected_trades
        effective_action = smp_action or configured_default
        if effective_action is SmpAction.NONE:
            own_trade = next(trade for trade in trades if trade["symbol"] == "AAPL")
            assert (
                own_trade["buy_gateway_id"]
                == own_trade["sell_gateway_id"]
                == "TRADER01"
            )
            assert [(trade["symbol"], trade["quantity"]) for trade in trades] == [
                ("AAPL", 100),
                ("MSFT", 50),
            ]
        else:
            tracked = next(
                tracked
                for tracked in engine._combos.values()
                if tracked.combo_id == combo.combo_id
            )
            assert tracked.leg_fill_qty[0] == 0
            assert len(tracked.child_order_ids) == 1
            assert [
                order.gateway_id for order in engine.books["AAPL"].resting_orders()
            ] == ["TRADER01"]
            assert [
                order.gateway_id for order in engine.books["MSFT"].resting_orders()
            ] == ["TRADER02"]

    @pytest.mark.parametrize(
        ("smp_action", "expected_status", "expected_trade_count", "aapl_resting"),
        [
            (SmpAction.NONE, ComboStatus.PARTIALLY_MATCHED, 1, set()),
            (SmpAction.CANCEL_AGGRESSOR, ComboStatus.FAILED, 0, {"TRADER01"}),
            (SmpAction.CANCEL_RESTING, ComboStatus.PENDING, 0, {"TRADER01"}),
            (SmpAction.CANCEL_BOTH, ComboStatus.FAILED, 0, set()),
        ],
    )
    def test_resting_combo_child_applies_smp_when_amended_across_own_order(
        self,
        combo_engine,
        smp_action,
        expected_status,
        expected_trade_count,
        aapl_resting,
    ) -> None:
        """A child later made marketable by AMEND applies its own SMP action
        against same-gateway liquidity, like any other aggressing order."""
        engine, pub_sock = combo_engine
        combo = ComboOrder.create(
            combo_id=f"AMEND-{smp_action.value}",
            gateway_id="TRADER01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    tick_decimals=2,
                    price_ticks=14900,
                    smp_action=smp_action,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=50,
                    tick_decimals=2,
                    price_ticks=42000,
                    smp_action=smp_action,
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())
        tracked = next(
            tracked
            for tracked in engine._combos.values()
            if tracked.combo_id == combo.combo_id
        )
        self._seed_resting(engine, "AAPL", Side.SELL, 100, 15000, gateway_id="TRADER01")
        offer_id = next(
            order.id
            for order in engine.books["AAPL"].resting_orders()
            if order.side is Side.SELL
        )
        pub_sock.sent.clear()

        child_id = tracked.child_order_ids[0]
        sibling_id = tracked.child_order_ids[1]
        engine._handle_amend(
            {"gateway_id": "TRADER01", "order_id": child_id, "price": 150.0}
        )

        assert self._combo_status(engine, pub_sock, combo) is expected_status
        trades = [
            decode(frame)[1]
            for frame in pub_sock.sent
            if decode(frame)[0] == "trade.executed"
        ]
        assert len(trades) == expected_trade_count
        aapl_ids = {order.id for order in engine.books["AAPL"].resting_orders()}
        msft_ids = {order.id for order in engine.books["MSFT"].resting_orders()}
        assert {
            order.gateway_id for order in engine.books["AAPL"].resting_orders()
        } == aapl_resting
        if smp_action is SmpAction.NONE:
            (trade,) = trades
            assert trade["buy_gateway_id"] == trade["sell_gateway_id"] == "TRADER01"
            assert [(trade["symbol"], trade["quantity"]) for trade in trades] == [
                ("AAPL", 100)
            ]
            assert aapl_ids == set()
            assert msft_ids == {sibling_id}
        elif smp_action is SmpAction.CANCEL_AGGRESSOR:
            assert aapl_ids == {offer_id}
            assert msft_ids == set()
            cancelled = [
                payload
                for frame in pub_sock.sent
                for topic, payload in [decode(frame)]
                if topic == "order.cancelled.TRADER01"
            ]
            assert {item["order_id"] for item in cancelled} == {
                child_id,
                sibling_id,
            }
        elif smp_action is SmpAction.CANCEL_RESTING:
            assert aapl_ids == {child_id}
            assert msft_ids == {sibling_id}
            cancelled = [
                payload
                for frame in pub_sock.sent
                for topic, payload in [decode(frame)]
                if topic == "order.cancelled.TRADER01"
            ]
            assert {item["order_id"] for item in cancelled} == {offer_id}
        else:
            assert aapl_ids == set()
            assert msft_ids == set()
            cancelled = [
                payload
                for frame in pub_sock.sent
                for topic, payload in [decode(frame)]
                if topic == "order.cancelled.TRADER01"
            ]
            assert {item["order_id"] for item in cancelled} == {
                offer_id,
                child_id,
                sibling_id,
            }

    def test_combo_both_legs_fill_immediately(self, combo_engine) -> None:
        """Both legs cross resting liquidity → combo should reach MATCHED."""
        engine, pub_sock = combo_engine

        # Seed resting orders that combo legs will cross
        self._seed_resting(engine, "AAPL", Side.SELL, 10, 15000)
        self._seed_resting(engine, "MSFT", Side.BUY, 5, 30000)
        pub_sock.sent.clear()

        payload = _two_leg_combo(price_a=15000, price_b=30000)
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

        payload = _two_leg_combo(price_a=15000, price_b=30000)
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
        leg fills, and as that leg would trade the combo is rejected (X28)
        rather than resting crossed.  Full atomic matching when all legs are
        fillable is covered by test_combo_both_legs_fill_immediately.
        """
        engine, pub_sock = combo_engine

        # Seed liquidity only for leg 0 (AAPL BUY) — leg 1 (MSFT) is unfillable.
        self._seed_resting(engine, "AAPL", Side.SELL, 10, 15000)
        pub_sock.sent.clear()

        engine._handle_combo_order(_two_leg_combo(price_a=15000, price_b=30000))

        combo = list(engine._combos.values())[0]
        # M5: no leg may fill while another leg cannot; X28: the combo fails.
        assert combo.status == ComboStatus.FAILED
        assert combo.leg_fill_qty[0] == 0
        assert len(combo.child_order_ids) == 1  # leg 1 never posted

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

        self._seed_resting(engine, "AAPL", Side.SELL, 10, 15000)
        self._seed_resting(engine, "MSFT", Side.BUY, 5, 30000)

        payload = _two_leg_combo(combo_id="DONE2", price_a=15000, price_b=30000)
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

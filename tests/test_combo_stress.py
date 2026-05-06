"""
Stress tests for combo orders — high volume, no deadlock.

Verifies:
- 100 rapid sequential combos are processed atomically with zero deadlock
- Circular-dependency combos (A→B, B→A) process sequentially, no hangs
- 10-leg combo processes correctly
- Mixed combo + single-leg traffic under load
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from edumatcher.engine.config_loader import (
    EngineConfig,
    FixGatewayConfig,
    SymbolConfig,
)
from edumatcher.engine.main import Engine
from edumatcher.models.combo import ComboLeg, ComboOrder, ComboStatus, ComboType
from edumatcher.models.message import decode
from edumatcher.models.order import Order, OrderType, Side, TIF

# ---------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------


@dataclass
class _DummySocket:
    sent: list[list[bytes]] = field(default_factory=list)
    closed: bool = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


def _make_symbols(n: int) -> dict[str, SymbolConfig]:
    """Generate n distinct symbols: SYM00, SYM01, ..."""
    return {f"SYM{i:02d}": SymbolConfig(name=f"SYM{i:02d}") for i in range(n)}


@pytest.fixture
def stress_engine(monkeypatch, tmp_path) -> tuple[Engine, _DummySocket]:
    """Engine with 20 symbols and 4 gateways for stress testing."""
    pull_sock = _DummySocket()
    pub_sock = _DummySocket()

    cfg = EngineConfig(
        symbols=_make_symbols(20),
        fix_gateways={
            f"GW{i:02d}": FixGatewayConfig(id=f"GW{i:02d}", description=f"Gateway {i}")
            for i in range(4)
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
    for i in range(4):
        engine._handle_gateway_connect({"gateway_id": f"GW{i:02d}"})
    pub_sock.sent.clear()
    return engine, pub_sock


# ---------------------------------------------------------------
# Stress tests
# ---------------------------------------------------------------


class TestComboStress:

    def test_100_rapid_combos_no_deadlock(self, stress_engine) -> None:
        """Submit 100 combos sequentially — all should be ACK'd, zero hangs."""
        engine, pub_sock = stress_engine

        for i in range(100):
            combo = ComboOrder.create(
                combo_id=f"RAPID-{i:03d}",
                gateway_id="GW00",
                combo_type=ComboType.AON,
                tif=TIF.DAY,
                legs=[
                    ComboLeg(
                        symbol=f"SYM{(i * 2) % 20:02d}",
                        side=Side.BUY,
                        order_type=OrderType.LIMIT,
                        quantity=10,
                        price=100.0,
                    ),
                    ComboLeg(
                        symbol=f"SYM{(i * 2 + 1) % 20:02d}",
                        side=Side.SELL,
                        order_type=OrderType.LIMIT,
                        quantity=10,
                        price=100.0,
                    ),
                ],
            )
            engine._handle_combo_order(combo.to_dict())

        # All 100 combos should be tracked
        assert len(engine._combos) == 100

        # All ACKs should be accepted
        ack_msgs = [
            decode(f)[1] for f in pub_sock.sent if decode(f)[0].startswith("combo.ack")
        ]
        assert len(ack_msgs) == 100
        assert all(m["accepted"] is True for m in ack_msgs)

    def test_circular_dependency_combos_no_deadlock(self, stress_engine) -> None:
        """
        Combo A: BUY SYM00, SELL SYM01
        Combo B: BUY SYM01, SELL SYM00

        These should process sequentially without deadlock.
        """
        engine, pub_sock = stress_engine

        combo_a = ComboOrder.create(
            combo_id="CIRC-A",
            gateway_id="GW00",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="SYM00",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=50.0,
                ),
                ComboLeg(
                    symbol="SYM01",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=50.0,
                ),
            ],
        )
        combo_b = ComboOrder.create(
            combo_id="CIRC-B",
            gateway_id="GW01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="SYM01",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=50.0,
                ),
                ComboLeg(
                    symbol="SYM00",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=50.0,
                ),
            ],
        )

        # Process both — no hang expected (single-threaded, sequential)
        engine._handle_combo_order(combo_a.to_dict())
        engine._handle_combo_order(combo_b.to_dict())

        assert len(engine._combos) == 2
        # Both should be ACK'd
        ack_msgs = [
            decode(f)[1] for f in pub_sock.sent if decode(f)[0].startswith("combo.ack")
        ]
        assert len(ack_msgs) == 2
        assert all(m["accepted"] is True for m in ack_msgs)

    def test_circular_combos_cross_fill(self, stress_engine) -> None:
        """
        Combo A legs rest. Combo B's legs cross Combo A's legs.
        Both combos should reach MATCHED.
        """
        engine, pub_sock = stress_engine

        combo_a = ComboOrder.create(
            combo_id="CROSS-A",
            gateway_id="GW00",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="SYM00",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=50.0,
                ),
                ComboLeg(
                    symbol="SYM01",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=50.0,
                ),
            ],
        )
        engine._handle_combo_order(combo_a.to_dict())

        combo_b = ComboOrder.create(
            combo_id="CROSS-B",
            gateway_id="GW01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="SYM00",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=50.0,
                ),
                ComboLeg(
                    symbol="SYM01",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=50.0,
                ),
            ],
        )
        engine._handle_combo_order(combo_b.to_dict())

        # Both should reach MATCHED (B's legs fill A's resting legs)
        combos = list(engine._combos.values())
        matched = [c for c in combos if c.status == ComboStatus.MATCHED]
        assert len(matched) == 2

    def test_10_leg_combo(self, stress_engine) -> None:
        """Maximum 10-leg combo is accepted and children posted."""
        engine, pub_sock = stress_engine

        legs = [
            ComboLeg(
                symbol=f"SYM{i:02d}",
                side=Side.BUY if i % 2 == 0 else Side.SELL,
                order_type=OrderType.LIMIT,
                quantity=10 + i,
                price=100.0 + i,
            )
            for i in range(10)
        ]

        combo = ComboOrder.create(
            combo_id="MAX-LEGS",
            gateway_id="GW00",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=legs,
        )
        engine._handle_combo_order(combo.to_dict())

        assert len(engine._combos) == 1
        tracked = list(engine._combos.values())[0]
        assert len(tracked.child_order_ids) == 10
        assert tracked.status == ComboStatus.PENDING

        ack_msgs = [
            decode(f)[1] for f in pub_sock.sent if decode(f)[0].startswith("combo.ack")
        ]
        assert ack_msgs[0]["accepted"] is True

    def test_10_leg_combo_all_fill(self, stress_engine) -> None:
        """10-leg combo fills all legs immediately when liquidity exists."""
        engine, pub_sock = stress_engine

        # Seed opposing liquidity for all 10 symbols
        for i in range(10):
            side = Side.SELL if i % 2 == 0 else Side.BUY
            order = Order.create(
                symbol=f"SYM{i:02d}",
                side=side,
                order_type=OrderType.LIMIT,
                quantity=10 + i,
                gateway_id="GW03",
                price=100.0 + i,
            )
            engine._handle_new_order(order.to_dict())
        pub_sock.sent.clear()

        legs = [
            ComboLeg(
                symbol=f"SYM{i:02d}",
                side=Side.BUY if i % 2 == 0 else Side.SELL,
                order_type=OrderType.LIMIT,
                quantity=10 + i,
                price=100.0 + i,
            )
            for i in range(10)
        ]

        combo = ComboOrder.create(
            combo_id="MAX-FILL",
            gateway_id="GW00",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=legs,
        )
        engine._handle_combo_order(combo.to_dict())

        tracked = list(engine._combos.values())[0]
        assert tracked.status == ComboStatus.MATCHED

    def test_mixed_combos_and_singles_under_load(self, stress_engine) -> None:
        """
        Interleave 50 combos with 100 single-leg orders.
        All should process without error.
        """
        engine, pub_sock = stress_engine

        for i in range(50):
            # Submit a combo
            combo = ComboOrder.create(
                combo_id=f"MIX-{i:03d}",
                gateway_id=f"GW{i % 4:02d}",
                combo_type=ComboType.AON,
                tif=TIF.DAY,
                legs=[
                    ComboLeg(
                        symbol=f"SYM{(i * 2) % 20:02d}",
                        side=Side.BUY,
                        order_type=OrderType.LIMIT,
                        quantity=5,
                        price=50.0,
                    ),
                    ComboLeg(
                        symbol=f"SYM{(i * 2 + 1) % 20:02d}",
                        side=Side.SELL,
                        order_type=OrderType.LIMIT,
                        quantity=5,
                        price=50.0,
                    ),
                ],
            )
            engine._handle_combo_order(combo.to_dict())

            # Submit 2 single-leg orders
            for j in range(2):
                order = Order.create(
                    symbol=f"SYM{(i + j) % 20:02d}",
                    side=Side.BUY if j == 0 else Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=10,
                    gateway_id=f"GW{(i + j) % 4:02d}",
                    price=50.0,
                )
                engine._handle_new_order(order.to_dict())

        # 50 combos tracked
        assert len(engine._combos) == 50

        # All combos ACK'd
        ack_msgs = [
            decode(f)[1] for f in pub_sock.sent if decode(f)[0].startswith("combo.ack")
        ]
        assert len(ack_msgs) == 50
        assert all(m["accepted"] is True for m in ack_msgs)

    def test_cascade_cancel_under_volume(self, stress_engine) -> None:
        """Submit 20 combos then cancel them all — cascade works under load."""
        engine, pub_sock = stress_engine

        for i in range(20):
            combo = ComboOrder.create(
                combo_id=f"CANCEL-{i:02d}",
                gateway_id="GW00",
                combo_type=ComboType.AON,
                tif=TIF.DAY,
                legs=[
                    ComboLeg(
                        symbol=f"SYM{(i * 2) % 20:02d}",
                        side=Side.BUY,
                        order_type=OrderType.LIMIT,
                        quantity=10,
                        price=100.0,
                    ),
                    ComboLeg(
                        symbol=f"SYM{(i * 2 + 1) % 20:02d}",
                        side=Side.SELL,
                        order_type=OrderType.LIMIT,
                        quantity=10,
                        price=100.0,
                    ),
                ],
            )
            engine._handle_combo_order(combo.to_dict())

        pub_sock.sent.clear()

        # Cancel all 20 combos
        for i in range(20):
            engine._handle_combo_cancel(
                {
                    "combo_id": f"CANCEL-{i:02d}",
                    "gateway_id": "GW00",
                }
            )

        # All should be CANCELLED
        cancelled = [
            c for c in engine._combos.values() if c.status == ComboStatus.CANCELLED
        ]
        assert len(cancelled) == 20

    def test_many_combos_same_symbol_pair(self, stress_engine) -> None:
        """
        50 combos all targeting the same symbol pair (different gateways).
        Ensures no internal state corruption.
        """
        engine, pub_sock = stress_engine

        for i in range(50):
            combo = ComboOrder.create(
                combo_id=f"SAME-{i:03d}",
                gateway_id=f"GW{i % 4:02d}",
                combo_type=ComboType.AON,
                tif=TIF.DAY,
                legs=[
                    ComboLeg(
                        symbol="SYM00",
                        side=Side.BUY,
                        order_type=OrderType.LIMIT,
                        quantity=1,
                        price=100.0,
                    ),
                    ComboLeg(
                        symbol="SYM01",
                        side=Side.SELL,
                        order_type=OrderType.LIMIT,
                        quantity=1,
                        price=100.0,
                    ),
                ],
            )
            engine._handle_combo_order(combo.to_dict())

        assert len(engine._combos) == 50
        # All children should be resting
        sym00_resting = list(engine.books["SYM00"].resting_orders())
        sym01_resting = list(engine.books["SYM01"].resting_orders())
        assert len(sym00_resting) == 50
        assert len(sym01_resting) == 50

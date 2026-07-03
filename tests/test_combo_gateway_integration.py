"""
Integration tests for combo orders: gateway parse → engine → fills.

These tests validate the full pipeline from FIX-like text parsing in the gateway
through to combo lifecycle events published by the engine.
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
from edumatcher.alf_console.main import Gateway
from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType
from edumatcher.models.message import decode
from edumatcher.models.order import Order, OrderType, Side, TIF

# ---------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------


@dataclass
class _DummySocket:
    sent: list[list[bytes]] = field(default_factory=list)
    closed: bool = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def combo_engine(monkeypatch, tmp_path) -> tuple[Engine, _DummySocket]:
    """Engine with AAPL, MSFT, GOOG symbols and two gateways."""
    pull_sock = _DummySocket()
    pub_sock = _DummySocket()

    cfg = EngineConfig(
        symbols={
            "AAPL": SymbolConfig(name="AAPL"),
            "MSFT": SymbolConfig(name="MSFT"),
            "GOOG": SymbolConfig(name="GOOG"),
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
    engine._handle_gateway_connect({"gateway_id": "TRADER01"})
    engine._handle_gateway_connect({"gateway_id": "TRADER02"})
    pub_sock.sent.clear()
    return engine, pub_sock


def _topics(pub_sock: _DummySocket) -> list[str]:
    return [decode(f)[0] for f in pub_sock.sent]


def _messages_by_topic(pub_sock: _DummySocket, prefix: str) -> list[dict]:
    return [decode(f)[1] for f in pub_sock.sent if decode(f)[0].startswith(prefix)]


def _seed_resting(
    engine: Engine,
    symbol: str,
    side: Side,
    qty: int,
    price: float,
    gateway_id: str = "TRADER02",
) -> None:
    """Place a resting limit order on the book."""
    order = Order.create(
        symbol=symbol,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=qty,
        gateway_id=gateway_id,
        price=price,
    )
    engine._handle_new_order(order.to_dict())


# ---------------------------------------------------------------
# Gateway parser tests (unit-level — parsing only, no ZMQ)
# ---------------------------------------------------------------


class TestGatewayComboParser:
    """Test that Gateway._send_combo() correctly parses FIX-like combo strings."""

    def _parse_combo_via_gateway(self, monkeypatch, line: str) -> list[list[bytes]]:
        """
        Create a Gateway with mocked sockets, call _parse_and_send, return sent frames.
        """
        sent: list[list[bytes]] = []

        class _FakePush:
            def send_multipart(self, frames):
                sent.append(frames)

        class _FakeSub:
            pass

        gw = Gateway.__new__(Gateway)
        gw.gateway_id = "TRADER01"
        gw.order_cache = {}
        gw._known_symbols = ["AAPL", "MSFT", "GOOG"]
        gw._running = True
        gw.push_sock = _FakePush()
        gw.sub_sock = _FakeSub()

        gw._parse_and_send(line)
        return sent

    def test_parse_valid_two_leg_combo(self, monkeypatch) -> None:
        line = (
            "NEW|TYPE=COMBO|COMBO_ID=PAIR-001|COMBO_TYPE=AON|TIF=GTC|LEG_COUNT=2|"
            "LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=150.00|"
            "LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=50|LEG1.PRICE=300.00"
        )
        sent = self._parse_combo_via_gateway(monkeypatch, line)
        assert len(sent) == 1

        topic, payload = decode(sent[0])
        assert topic == "order.combo"
        assert payload["combo_id"] == "PAIR-001"
        assert payload["combo_type"] == "AON"
        assert payload["tif"] == "GTC"
        assert len(payload["legs"]) == 2
        assert payload["legs"][0]["symbol"] == "AAPL"
        assert payload["legs"][0]["side"] == "BUY"
        assert payload["legs"][0]["quantity"] == 100
        assert payload["legs"][1]["symbol"] == "MSFT"
        assert payload["legs"][1]["side"] == "SELL"

    def test_parse_three_leg_combo(self, monkeypatch) -> None:
        line = (
            "NEW|TYPE=COMBO|COMBO_ID=TRI|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=3|"
            "LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=200|LEG0.PRICE=210.00|"
            "LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=100|LEG1.PRICE=415.00|"
            "LEG2.SYM=GOOG|LEG2.SIDE=SELL|LEG2.QTY=50|LEG2.PRICE=170.00"
        )
        sent = self._parse_combo_via_gateway(monkeypatch, line)
        assert len(sent) == 1

        topic, payload = decode(sent[0])
        assert len(payload["legs"]) == 3
        assert payload["legs"][2]["symbol"] == "GOOG"

    def test_parse_combo_missing_combo_id_sends_nothing(self, monkeypatch) -> None:
        line = "NEW|TYPE=COMBO|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=2|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=10|LEG0.PRICE=100|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=10|LEG1.PRICE=200"
        sent = self._parse_combo_via_gateway(monkeypatch, line)
        assert sent == []

    def test_parse_combo_invalid_leg_count_sends_nothing(self, monkeypatch) -> None:
        line = (
            "NEW|TYPE=COMBO|COMBO_ID=X|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=1|"
            "LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=10|LEG0.PRICE=100"
        )
        sent = self._parse_combo_via_gateway(monkeypatch, line)
        assert sent == []

    def test_parse_cancel_combo_sends_correct_topic(self, monkeypatch) -> None:
        line = "CANCEL|COMBO_ID=MY_COMBO"
        sent = self._parse_combo_via_gateway(monkeypatch, line)
        assert len(sent) == 1

        topic, payload = decode(sent[0])
        assert topic == "order.combo_cancel"
        assert payload["combo_id"] == "MY_COMBO"
        assert payload["gateway_id"] == "TRADER01"


# ---------------------------------------------------------------
# End-to-end: gateway parse → engine → lifecycle
# ---------------------------------------------------------------


class TestComboEndToEnd:
    """Test full combo flow: parse at gateway → engine processes → fills/status."""

    def test_combo_accepted_and_children_posted(self, combo_engine) -> None:
        """Valid combo → ACK + children resting on respective books."""
        engine, pub_sock = combo_engine

        combo = ComboOrder.create(
            combo_id="E2E-001",
            gateway_id="TRADER01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=150.0,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=50,
                    price=300.0,
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())

        topics = _topics(pub_sock)
        assert "combo.ack.TRADER01" in topics
        ack = _messages_by_topic(pub_sock, "combo.ack")[0]
        assert ack["accepted"] is True

        # Children should be on the books
        assert "AAPL" in engine.books
        assert "MSFT" in engine.books
        aapl_resting = list(engine.books["AAPL"].resting_orders())
        msft_resting = list(engine.books["MSFT"].resting_orders())
        assert any(o.combo_parent_id is not None for o in aapl_resting)
        assert any(o.combo_parent_id is not None for o in msft_resting)

    def test_combo_fills_both_legs_against_liquidity(self, combo_engine) -> None:
        """Combo with matching liquidity → both fills → MATCHED."""
        engine, pub_sock = combo_engine

        # Seed opposing liquidity
        _seed_resting(engine, "AAPL", Side.SELL, 100, 150.0)
        _seed_resting(engine, "MSFT", Side.BUY, 50, 300.0)
        pub_sock.sent.clear()

        combo = ComboOrder.create(
            combo_id="FILL-001",
            gateway_id="TRADER01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=150.0,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=50,
                    price=300.0,
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())

        statuses = _messages_by_topic(pub_sock, "combo.status")
        assert any(s["status"] == "MATCHED" for s in statuses)

        # Fills should have been published
        fills = _messages_by_topic(pub_sock, "order.fill")
        assert len(fills) >= 2  # At least one fill per leg

    def test_combo_partial_then_complete_on_later_order(self, combo_engine) -> None:
        """Only one leg has liquidity initially → PARTIALLY_MATCHED → later MATCHED."""
        engine, pub_sock = combo_engine

        _seed_resting(engine, "AAPL", Side.SELL, 100, 150.0)
        pub_sock.sent.clear()

        combo = ComboOrder.create(
            combo_id="PARTIAL-001",
            gateway_id="TRADER01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=150.0,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=50,
                    price=300.0,
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())

        tracked = list(engine._combos.values())[0]
        assert tracked.status.value == "PARTIALLY_MATCHED"

        # Now a buyer arrives on MSFT
        pub_sock.sent.clear()
        filler = Order.create(
            symbol="MSFT",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=50,
            gateway_id="TRADER02",
            price=300.0,
        )
        engine._handle_new_order(filler.to_dict())

        assert tracked.status.value == "MATCHED"
        statuses = _messages_by_topic(pub_sock, "combo.status")
        assert any(s["status"] == "MATCHED" for s in statuses)

    def test_cascade_cancel_when_child_cancelled(self, combo_engine) -> None:
        """Cancelling one child triggers cascade-cancel of the sibling."""
        engine, pub_sock = combo_engine

        combo = ComboOrder.create(
            combo_id="CASCADE-001",
            gateway_id="TRADER01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=150.0,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=50,
                    price=300.0,
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())
        tracked = list(engine._combos.values())[0]
        child_id_0 = tracked.child_order_ids[0]
        pub_sock.sent.clear()

        # Cancel the first child directly
        engine._handle_cancel({"order_id": child_id_0, "gateway_id": "TRADER01"})

        assert tracked.status.value == "FAILED"
        statuses = _messages_by_topic(pub_sock, "combo.status")
        assert any(s["status"] == "FAILED" for s in statuses)

        # Sibling should also have been cancelled
        cancels = _messages_by_topic(pub_sock, "order.cancelled")
        assert len(cancels) >= 1

    def test_user_cancel_by_combo_id(self, combo_engine) -> None:
        """Cancel via COMBO_ID cancels all children atomically."""
        engine, pub_sock = combo_engine

        combo = ComboOrder.create(
            combo_id="USERCANCEL",
            gateway_id="TRADER01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=150.0,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=50,
                    price=300.0,
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())
        pub_sock.sent.clear()

        engine._handle_combo_cancel(
            {
                "combo_id": "USERCANCEL",
                "gateway_id": "TRADER01",
            }
        )

        tracked = list(engine._combos.values())[0]
        assert tracked.status.value == "CANCELLED"

        cancels = _messages_by_topic(pub_sock, "order.cancelled")
        assert len(cancels) == 2  # Both children cancelled

    def test_cancel_combo_wrong_gateway_rejected(self, combo_engine) -> None:
        """TRADER02 cannot cancel TRADER01's combo."""
        engine, pub_sock = combo_engine

        combo = ComboOrder.create(
            combo_id="OWNERSHIP",
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
        pub_sock.sent.clear()

        engine._handle_combo_cancel(
            {
                "combo_id": "OWNERSHIP",
                "gateway_id": "TRADER02",
            }
        )

        acks = _messages_by_topic(pub_sock, "combo.ack")
        assert acks[0]["accepted"] is False
        assert "not found" in acks[0]["reason"].lower()

    def test_combo_day_order_expires_at_shutdown_cascades(self, combo_engine) -> None:
        """DAY combo children expire at shutdown → cascade-cancel."""
        engine, pub_sock = combo_engine

        combo = ComboOrder.create(
            combo_id="DAY-EXPIRE",
            gateway_id="TRADER01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=150.0,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=50,
                    price=300.0,
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())
        pub_sock.sent.clear()

        # Simulate shutdown — expire DAY orders
        engine._shutdown()

        tracked = list(engine._combos.values())[0]
        assert tracked.status.value in ("FAILED", "CANCELLED")

    def test_three_leg_combo_all_fill(self, combo_engine) -> None:
        """3-leg combo where all legs find liquidity → MATCHED."""
        engine, pub_sock = combo_engine

        _seed_resting(engine, "AAPL", Side.SELL, 200, 210.0)
        _seed_resting(engine, "MSFT", Side.BUY, 100, 415.0)
        _seed_resting(engine, "GOOG", Side.BUY, 50, 170.0)
        pub_sock.sent.clear()

        combo = ComboOrder.create(
            combo_id="TRI-FILL",
            gateway_id="TRADER01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=200,
                    price=210.0,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=415.0,
                ),
                ComboLeg(
                    symbol="GOOG",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=50,
                    price=170.0,
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())

        tracked = list(engine._combos.values())[0]
        assert tracked.status.value == "MATCHED"

    def test_combo_gtc_persisted_and_restored(self, combo_engine, tmp_path) -> None:
        """GTC combo survives shutdown + restore cycle."""
        engine, pub_sock = combo_engine

        combo = ComboOrder.create(
            combo_id="GTC-PERSIST",
            gateway_id="TRADER01",
            combo_type=ComboType.AON,
            tif=TIF.GTC,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=150.0,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=50,
                    price=300.0,
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())

        tracked = list(engine._combos.values())[0]
        assert tracked.status.value == "PENDING"
        assert tracked.tif == TIF.GTC

        # Persist
        from edumatcher.engine.persistence import save_gtc_combos, load_gtc_combos

        path = tmp_path / "gtc_combos.json"
        save_gtc_combos(list(engine._combos.values()), path)

        # Reload
        loaded = load_gtc_combos(path)
        assert len(loaded) == 1
        assert loaded[0].combo_id == "GTC-PERSIST"
        assert loaded[0].tif == TIF.GTC
        assert len(loaded[0].child_order_ids) == 2

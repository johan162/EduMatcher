"""
Tests for MAX_ORDER_QTY / MAX_ORDER_VALUE — the per-symbol order-size and
notional caps (G12).

Covers the three layers the control spans: the pure check
(``engine/order_limits.py``), the config resolution that merges a symbol's
override over its risk level's defaults (``engine/config_loader.py``), and
the two engine entry points that enforce it (``_validate_new_order`` for a
new order, ``_handle_amend`` for an amend).

The engine fixture drives the message handlers directly — no real ZMQ
sockets — the same way ``tests/test_instrument_halt.py`` does.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from edumatcher.engine.config_loader import (
    EngineConfig,
    FixGatewayConfig,
    SymbolConfig,
    load_engine_config,
)
from edumatcher.engine.main import Engine
from edumatcher.engine.order_limits import OrderLimitsConfig, validate_order_limits
from edumatcher.models.message import decode
from edumatcher.models.order import Order, OrderType, Side, TIF
from edumatcher.models.price import register_tick_decimals

# ──────────────────────────────────────────────────────────────────────────────
# The pure check
# ──────────────────────────────────────────────────────────────────────────────


class TestValidateOrderLimits:
    def test_no_caps_configured_passes(self) -> None:
        assert validate_order_limits(1_000_000, 999.0, OrderLimitsConfig()) is None

    def test_qty_at_the_cap_passes(self) -> None:
        limits = OrderLimitsConfig(max_order_qty=100)
        assert validate_order_limits(100, 10.0, limits) is None

    def test_qty_over_the_cap_rejects(self) -> None:
        limits = OrderLimitsConfig(max_order_qty=100)
        result = validate_order_limits(101, 10.0, limits)
        assert result is not None
        code, reason = result
        assert code == "MAX_ORDER_QTY"
        assert "101" in reason and "100" in reason

    def test_value_at_the_cap_passes(self) -> None:
        limits = OrderLimitsConfig(max_order_value=1000.0)
        assert validate_order_limits(100, 10.0, limits) is None

    def test_value_over_the_cap_rejects(self) -> None:
        limits = OrderLimitsConfig(max_order_value=999.0)
        result = validate_order_limits(100, 10.0, limits)
        assert result is not None
        assert result[0] == "MAX_ORDER_VALUE"

    def test_priceless_order_skips_the_value_check(self) -> None:
        limits = OrderLimitsConfig(max_order_value=1.0)
        assert validate_order_limits(100, None, limits) is None

    def test_priceless_order_still_faces_the_qty_cap(self) -> None:
        limits = OrderLimitsConfig(max_order_qty=50, max_order_value=1.0)
        result = validate_order_limits(100, None, limits)
        assert result is not None
        assert result[0] == "MAX_ORDER_QTY"

    def test_qty_is_checked_before_value(self) -> None:
        limits = OrderLimitsConfig(max_order_qty=50, max_order_value=1.0)
        result = validate_order_limits(100, 10.0, limits)
        assert result is not None
        assert result[0] == "MAX_ORDER_QTY"


# ──────────────────────────────────────────────────────────────────────────────
# Config resolution
# ──────────────────────────────────────────────────────────────────────────────


_BASE_YAML = """
symbols:
{symbols}
risk_controls:
  default_level: CORE
  levels:
    CORE:
{level}
gateways:
  alf:
    - id: TRADER01
      role: TRADER
"""


def _write_config(tmp_path, *, symbols: str, level: str = "      collar: {}\n"):
    path = tmp_path / "engine_config.yaml"
    path.write_text(_BASE_YAML.format(symbols=symbols, level=level))
    return load_engine_config(path)


class TestConfigResolution:
    def test_absent_everywhere_means_no_limits(self, tmp_path) -> None:
        cfg = _write_config(tmp_path, symbols="  AAPL:\n    tick_decimals: 2\n")
        assert cfg.symbols["AAPL"].order_limits is None

    def test_level_defaults_reach_the_symbol(self, tmp_path) -> None:
        cfg = _write_config(
            tmp_path,
            symbols="  AAPL:\n    tick_decimals: 2\n",
            level=(
                "      order_limits:\n"
                "        max_order_qty: 100000\n"
                "        max_order_value: 5000000\n"
            ),
        )
        limits = cfg.symbols["AAPL"].order_limits
        assert limits == OrderLimitsConfig(
            max_order_qty=100000, max_order_value=5000000.0
        )

    def test_symbol_override_wins_per_key(self, tmp_path) -> None:
        """The symbol overrides one cap and inherits the other, exactly as a
        per-symbol ``collar`` override merges over its level's bands."""
        cfg = _write_config(
            tmp_path,
            symbols=(
                "  AAPL:\n"
                "    tick_decimals: 2\n"
                "    order_limits:\n"
                "      max_order_qty: 5000\n"
            ),
            level=(
                "      order_limits:\n"
                "        max_order_qty: 100000\n"
                "        max_order_value: 5000000\n"
            ),
        )
        limits = cfg.symbols["AAPL"].order_limits
        assert limits == OrderLimitsConfig(
            max_order_qty=5000, max_order_value=5000000.0
        )

    def test_symbol_only_needs_no_level_block(self, tmp_path) -> None:
        cfg = _write_config(
            tmp_path,
            symbols=(
                "  AAPL:\n"
                "    tick_decimals: 2\n"
                "    order_limits:\n"
                "      max_order_value: 250000\n"
            ),
        )
        limits = cfg.symbols["AAPL"].order_limits
        assert limits == OrderLimitsConfig(max_order_qty=None, max_order_value=250000.0)

    def test_empty_block_is_the_same_as_no_block(self, tmp_path) -> None:
        cfg = _write_config(
            tmp_path,
            symbols="  AAPL:\n    tick_decimals: 2\n    order_limits: {}\n",
        )
        assert cfg.symbols["AAPL"].order_limits is None

    @pytest.mark.parametrize(
        "block, message",
        [
            ("    order_limits: 5\n", "must be a mapping"),
            (
                "    order_limits:\n      max_order_qty: 0\n",
                "max_order_qty must be > 0",
            ),
            (
                "    order_limits:\n      max_order_qty: -1\n",
                "max_order_qty must be > 0",
            ),
            (
                "    order_limits:\n      max_order_qty: nope\n",
                "max_order_qty must be an integer",
            ),
            (
                "    order_limits:\n      max_order_value: 0\n",
                "max_order_value must be > 0",
            ),
            (
                "    order_limits:\n      max_order_value: nope\n",
                "max_order_value must be a number",
            ),
        ],
    )
    def test_invalid_symbol_values_are_rejected(
        self, tmp_path, block: str, message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            _write_config(tmp_path, symbols=f"  AAPL:\n    tick_decimals: 2\n{block}")

    def test_level_block_must_be_a_mapping(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="order_limits' must be a mapping"):
            _write_config(
                tmp_path,
                symbols="  AAPL:\n    tick_decimals: 2\n",
                level="      order_limits: 5\n",
            )


# ──────────────────────────────────────────────────────────────────────────────
# Engine enforcement
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class _DummySocket:
    sent: list[list[bytes]]
    closed: bool = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def engine(monkeypatch, tmp_path) -> tuple[Engine, _DummySocket]:
    """AAPL capped at 1,000 shares / 100,000 notional; MSFT uncapped."""
    pull_sock = _DummySocket(sent=[])
    pub_sock = _DummySocket(sent=[])

    register_tick_decimals("AAPL", 2)
    register_tick_decimals("MSFT", 2)

    cfg = EngineConfig(
        symbols={
            "AAPL": SymbolConfig(
                name="AAPL",
                tick_decimals=2,
                order_limits=OrderLimitsConfig(
                    max_order_qty=1000, max_order_value=100_000.0
                ),
            ),
            "MSFT": SymbolConfig(name="MSFT", tick_decimals=2),
        },
        fix_gateways={"TRADER01": FixGatewayConfig(id="TRADER01")},
    )

    monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
    monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
    monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)
    monkeypatch.setattr("edumatcher.engine.main.load_gtc_orders", lambda _: [])
    monkeypatch.setattr("edumatcher.engine.main.load_book_stats", lambda _: {})
    monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)

    cfg_path = tmp_path / "engine_config.yaml"
    cfg_path.write_text("dummy: true\n")

    eng = Engine(config_path=str(cfg_path))
    # run() calls _load_config(); this fixture drives the handlers directly, so
    # wire the caps the way _load_config() would. TestConfigWiring below covers
    # that wiring itself.
    eng._order_limits["AAPL"] = OrderLimitsConfig(
        max_order_qty=1000, max_order_value=100_000.0
    )
    eng._handle_gateway_connect({"gateway_id": "TRADER01"})
    pub_sock.sent.clear()
    return eng, pub_sock


def _order_dict(
    *,
    symbol: str = "AAPL",
    side: Side = Side.BUY,
    order_type: OrderType = OrderType.LIMIT,
    qty: int = 100,
    price: int | None = 1000,
    tif: TIF = TIF.DAY,
) -> dict:
    """``price`` is in integer ticks; 1000 ticks is 10.00 on a 2-decimal symbol."""
    return Order.create(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=qty,
        gateway_id="TRADER01",
        tif=tif,
        price=price,
    ).to_dict()


def _last_ack(pub: _DummySocket) -> dict:
    """The most recent order.ack, ignoring anything published after it.

    An accepted MARKET order against an empty book is acked and then
    immediately cancelled for INSUFFICIENT_LIQUIDITY, so the last frame on
    the wire is not always the ack.
    """
    for frame in reversed(pub.sent):
        topic, msg = decode(frame)
        if topic.startswith("order.ack."):
            return msg
    raise AssertionError(
        f"no order.ack published; topics={[decode(f)[0] for f in pub.sent]}"
    )


def _last_topic(pub: _DummySocket) -> str:
    return decode(pub.sent[-1])[0]


class TestNewOrderEnforcement:
    def test_order_within_both_caps_is_accepted(self, engine) -> None:
        eng, pub = engine
        eng._handle_new_order(_order_dict(qty=1000, price=1000))
        assert _last_ack(pub)["accepted"] is True

    def test_qty_over_cap_rejects_with_max_order_qty(self, engine) -> None:
        eng, pub = engine
        eng._handle_new_order(_order_dict(qty=1001, price=1000))
        msg = _last_ack(pub)
        assert msg["accepted"] is False
        assert msg["reject_code"] == "MAX_ORDER_QTY"

    def test_notional_over_cap_rejects_with_max_order_value(self, engine) -> None:
        eng, pub = engine
        # 1000 shares at 150.00 = 150,000 > the 100,000 cap, and the quantity
        # cap is untouched — so this can only be the notional check firing.
        eng._handle_new_order(_order_dict(qty=1000, price=15000))
        msg = _last_ack(pub)
        assert msg["accepted"] is False
        assert msg["reject_code"] == "MAX_ORDER_VALUE"

    def test_market_order_skips_the_notional_cap(self, engine) -> None:
        eng, pub = engine
        eng._handle_new_order(
            _order_dict(order_type=OrderType.MARKET, qty=1000, price=None)
        )
        assert _last_ack(pub)["accepted"] is True

    def test_market_order_still_faces_the_qty_cap(self, engine) -> None:
        eng, pub = engine
        eng._handle_new_order(
            _order_dict(order_type=OrderType.MARKET, qty=1001, price=None)
        )
        msg = _last_ack(pub)
        assert msg["accepted"] is False
        assert msg["reject_code"] == "MAX_ORDER_QTY"

    def test_uncapped_symbol_accepts_anything(self, engine) -> None:
        eng, pub = engine
        eng._handle_new_order(_order_dict(symbol="MSFT", qty=10_000_000, price=15000))
        assert _last_ack(pub)["accepted"] is True


class TestAmendEnforcement:
    """An amend faces the same caps a new order would — otherwise the control
    is bypassed by entering small and amending up."""

    @staticmethod
    def _rest(eng, pub, *, qty: int = 100, price: int = 1000) -> str:
        payload = _order_dict(qty=qty, price=price)
        eng._handle_new_order(payload)
        assert _last_ack(pub)["accepted"] is True
        pub.sent.clear()
        return payload["id"]

    def test_amend_raising_qty_over_cap_is_rejected(self, engine) -> None:
        eng, pub = engine
        order_id = self._rest(eng, pub)
        eng._handle_amend({"gateway_id": "TRADER01", "order_id": order_id, "qty": 1001})
        msg = _last_ack(pub)
        assert msg["accepted"] is False
        assert msg["reject_code"] == "MAX_ORDER_QTY"

    def test_amend_raising_price_over_notional_cap_is_rejected(self, engine) -> None:
        eng, pub = engine
        # 1,000 shares at 10.00 = 10,000, comfortably inside the cap.
        order_id = self._rest(eng, pub, qty=1000, price=1000)
        # Repricing to 150.00 makes it 150,000 — the quantity never changed,
        # so only the notional check can reject this.
        eng._handle_amend(
            {"gateway_id": "TRADER01", "order_id": order_id, "price": 150.00}
        )
        msg = _last_ack(pub)
        assert msg["accepted"] is False
        assert msg["reject_code"] == "MAX_ORDER_VALUE"

    def test_amend_within_the_caps_is_accepted(self, engine) -> None:
        eng, pub = engine
        order_id = self._rest(eng, pub)
        eng._handle_amend({"gateway_id": "TRADER01", "order_id": order_id, "qty": 500})
        assert _last_topic(pub).startswith("order.amended.")


class TestReferenceBundle:
    def test_symbol_and_level_limits_reach_the_reference_bundle(self, engine) -> None:
        eng, _ = engine
        assert eng._engine_config is not None
        eng._engine_config.risk_control_levels = {
            "CORE": {
                "collar": {},
                "order_limits": {"max_order_qty": 100000, "max_order_value": 5000000},
            }
        }
        eng._rebuild_reference_cache()
        assert eng._reference_cache is not None
        bundle = eng._reference_cache

        by_symbol = {s["symbol"]: s for s in bundle["symbols"]}
        assert by_symbol["AAPL"]["order_limits"] == {
            "max_order_qty": 1000,
            "max_order_value": 100_000.0,
        }
        assert "order_limits" not in by_symbol["MSFT"]

        levels = {lvl["name"]: lvl for lvl in bundle["risk"]["levels"]}
        assert levels["CORE"]["order_limits"] == {
            "max_order_qty": 100000,
            "max_order_value": 5000000,
        }


class TestConfigWiring:
    """_load_config() moves the loader's resolved caps onto the engine."""

    def test_load_config_populates_order_limits(self, engine) -> None:
        eng, _ = engine
        eng._order_limits.clear()
        eng._load_config()
        assert eng._order_limits["AAPL"] == OrderLimitsConfig(
            max_order_qty=1000, max_order_value=100_000.0
        )
        assert "MSFT" not in eng._order_limits

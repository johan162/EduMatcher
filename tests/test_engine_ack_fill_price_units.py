"""``order.ack.price`` and ``order.fill.price`` are display money, always.

Both fields are declared ``unit: display_price`` in ``spec/messages/order.yaml``
while the inbound ``order.new.price`` they derive from is in ticks. The engine's
hot path used to echo the tick value straight through, so on a 2-decimal symbol
a 100.00 limit was acked at 10000 and the *aggressor's* fill reported 10000
while the passive leg of the very same match reported 100.00 — one field, two
units, decided by which side of the trade you were on.

These tests pin the unit at the publish site. They are unit assertions, not
formatting ones: a regression here does not look like a bug, it looks like a
price.

The engine-*inbound* half of the same rule -- that the wire carries integer
ticks and converting is the submitting gateway's job -- is
``tests/test_wire_price_units.py``. Together they say the unit of a price
never depends on which direction it is travelling.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.engine_harness import SYMBOL, connect, make_engine, msgs, order_payload
from edumatcher.models.order import OrderType, Side

_LIMIT = 100.0  # 10000 ticks on a 2-decimal symbol


@pytest.fixture
def engine_and_sock(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine, "GW01", "GW02")
    return engine, pub


class TestOrderAckPriceUnit:
    def test_ack_echoes_the_limit_in_display_money(self, engine_and_sock: Any) -> None:
        engine, pub = engine_and_sock
        engine._handle_new_order(
            order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=_LIMIT)
        )
        acks = msgs(pub, "order.ack.GW01")
        assert [a["price"] for a in acks] == [_LIMIT]

    def test_a_market_order_acks_without_a_price(self, engine_and_sock: Any) -> None:
        """No limit price to convert, and none invented — the hot path's
        None branch, which is the one a naive ``from_ticks`` call would crash on."""
        engine, pub = engine_and_sock
        engine._handle_new_order(order_payload(Side.BUY, OrderType.MARKET, 100, "GW01"))
        acks = msgs(pub, "order.ack.GW01")
        assert len(acks) == 1
        assert acks[0].get("price") is None


class TestOrderFillPriceUnit:
    def test_both_legs_of_one_match_report_the_same_unit(
        self, engine_and_sock: Any
    ) -> None:
        """The bug's signature: aggressor and passive disagreeing by 10^decimals."""
        engine, pub = engine_and_sock
        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 100, "GW02", price=_LIMIT)
        )
        engine._handle_new_order(
            order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=_LIMIT)
        )

        taker = msgs(pub, "order.fill.GW01")
        maker = msgs(pub, "order.fill.GW02")
        assert len(taker) == 1 and len(maker) == 1
        assert taker[0]["liquidity_flag"] == "TAKER"
        assert maker[0]["liquidity_flag"] == "MAKER"
        assert taker[0]["price"] == maker[0]["price"] == _LIMIT

    def test_fill_price_and_order_price_share_a_scale(
        self, engine_and_sock: Any
    ) -> None:
        """``fill_price`` was always display money; ``price`` now agrees with it."""
        engine, pub = engine_and_sock
        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 100, "GW02", price=_LIMIT)
        )
        engine._handle_new_order(
            order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=_LIMIT)
        )

        fill = msgs(pub, "order.fill.GW01")[0]
        assert fill["fill_price"] == fill["price"] == _LIMIT
        assert fill["symbol"] == SYMBOL

    def test_a_single_level_fill_reports_the_exact_level_price(
        self, engine_and_sock: Any
    ) -> None:
        """The per-order VWAP was summed in display floats, so 23 @ 108.67
        came back as 108.66999999999999 (108.67 * 23 / 23). Summed in ticks,
        a fill at one level is exactly that level's price."""
        engine, pub = engine_and_sock
        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 23, "GW02", price=108.67)
        )
        engine._handle_new_order(
            order_payload(Side.BUY, OrderType.LIMIT, 23, "GW01", price=108.67)
        )

        fills = msgs(pub, "order.fill.GW01") + msgs(pub, "order.fill.GW02")
        assert [f["fill_price"] for f in fills] == [108.67, 108.67]

    def test_a_sweep_reports_its_vwap_correctly_rounded(
        self, engine_and_sock: Any
    ) -> None:
        """1 @ 108.60 + 4 @ 108.61 is 108.608 exactly. Dividing by the
        quantity and then by the tick scale rounds twice and gave
        108.60799999999999; one division of the two integers does not."""
        engine, pub = engine_and_sock
        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 1, "GW02", price=108.60)
        )
        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 4, "GW02", price=108.61)
        )
        engine._handle_new_order(
            order_payload(Side.BUY, OrderType.LIMIT, 5, "GW01", price=108.61)
        )

        (taker,) = msgs(pub, "order.fill.GW01")
        assert taker["fill_price"] == 108.608

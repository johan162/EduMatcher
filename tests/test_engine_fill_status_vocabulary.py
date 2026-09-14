"""``order.fill.status`` says the same thing on every path that publishes it.

It did not. The field was the one status the message spec left as an
unconstrained string, and the engine has eight places that publish a fill: six
derived the value from ``OrderStatus`` and sent ``PARTIAL``, while the
continuous-matching hot path and ``_publish_amend_rematch`` sent
``PARTIAL_FILL``. A fill on a quote leg therefore reported a different status
from a fill on an ordinary order, on one field of one message, and every
consumer passed the difference straight through -- the ALF ``FILL`` line, the
REST order cache, and the trader GUI, which cast it into a union that does not
contain it.

These tests drive the two paths that used to disagree and assert they agree,
and then put every published fill through the generated validator, which is
where the enum declaration actually bites.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.models.generated.order import (
    _ORDER_FILL_STATUS_VALUES,
    OrderFill,
)
from edumatcher.models.message import fill_status
from edumatcher.models.order import OrderType, Side
from tests.engine_harness import (
    SYMBOL,
    connect,
    make_engine,
    msgs,
    order_payload,
    submit_quote,
)
from edumatcher.models.generated.order import topic_order_fill


def fills(pub_sock: Any, gateway_id: str) -> list[dict[str, Any]]:
    return msgs(pub_sock, topic_order_fill(gateway_id))


def _sell(qty: int, price: float) -> dict[str, Any]:
    return order_payload(
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        qty=qty,
        gateway_id="TRADER01",
        price=price,
        symbol=SYMBOL,
    )


def _buy(qty: int, price: float) -> dict[str, Any]:
    return order_payload(
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        qty=qty,
        gateway_id="TRADER01",
        price=price,
        symbol=SYMBOL,
    )


class TestTheHelper:
    def test_it_answers_the_two_values_the_enum_declares(self) -> None:
        assert fill_status(50) == "PARTIAL"
        assert fill_status(0) == "FILLED"

    def test_both_answers_are_on_the_enum(self) -> None:
        """The declaration and the producer cannot drift apart silently."""
        assert set(_ORDER_FILL_STATUS_VALUES) == {fill_status(1), fill_status(0)}

    def test_partial_fill_is_no_longer_one_of_them(self) -> None:
        assert "PARTIAL_FILL" not in _ORDER_FILL_STATUS_VALUES


class TestEveryPathAgrees:
    """The two paths whose vocabularies used to differ, side by side."""

    def test_an_ordinary_fill_and_a_quote_leg_fill_use_one_vocabulary(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        engine, pub_sock = make_engine(
            monkeypatch, tmp_path, gateways=("TRADER01", "MM01"), mm_gateways=("MM01",)
        )
        connect(engine, "TRADER01", "MM01")

        # A resting order for the quote's bid leg to cross into, so the leg
        # partially fills on submission -- _handle_quote_new's publish site.
        engine._handle_new_order(_sell(40, 100.0))
        submit_quote(engine, "MM01", bid_price=100.0, ask_price=101.0, bid_qty=100)

        leg_fills = fills(pub_sock, "MM01")
        assert leg_fills, "the quote leg should have crossed the resting sell"
        assert {f["status"] for f in leg_fills} == {"PARTIAL"}

        # And an ordinary aggressor, which is the hot path.
        engine._handle_new_order(_buy(150, 101.0))
        taker = [f for f in fills(pub_sock, "TRADER01") if f["remaining_qty"] > 0]
        assert taker, "the buy should have partially filled against the quote's ask"
        assert {f["status"] for f in taker} == {"PARTIAL"}

    def test_every_published_fill_passes_the_generated_validator(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """The check the enum declaration buys. ``make_fill_msg`` publishes
        unchecked for speed, so nothing validates these in production -- this
        is where a status off the enum is caught instead."""
        engine, pub_sock = make_engine(
            monkeypatch, tmp_path, gateways=("TRADER01", "MM01"), mm_gateways=("MM01",)
        )
        connect(engine, "TRADER01", "MM01")
        engine._handle_new_order(_sell(40, 100.0))
        submit_quote(engine, "MM01", bid_price=100.0, ask_price=101.0, bid_qty=100)
        engine._handle_new_order(_buy(150, 101.0))

        published = fills(pub_sock, "MM01") + fills(pub_sock, "TRADER01")
        assert published, "the scenario published no fills at all"
        for payload in published:
            OrderFill.from_dict(payload).validate()

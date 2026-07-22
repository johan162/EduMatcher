"""
Adversarial input tests: payloads that are WELL-FORMED but hostile or
nonsensical.  The existing negative tests (test_negative_input_validation)
cover malformed payloads at the gateway boundary; this suite attacks the
ENGINE's own boundary, which must defend itself regardless of which
gateway forwarded the message (review findings A4, M7, M12; H1's timestamp
spoofing lives in test_engine_review_highs.py).

All tests assert what a correct engine must do, so several are EXPECTED TO
FAIL until the boundary-validation layer (review recommendation A4) lands.
"""

from __future__ import annotations

from edumatcher.models.order import OrderType, Side

from tests.engine_harness import (
    SYMBOL,
    connect,
    make_engine,
    msgs,
    order_payload,
)
from tests.engine_invariants import assert_book_invariants


class TestDuplicateOrderId:
    def test_replayed_order_message_does_not_double_the_liquidity(
        self, monkeypatch, tmp_path
    ) -> None:
        """A gateway retry / replayed message must not create liquidity twice.

        Today the engine silently accepts the duplicate: _order_symbol is
        overwritten and a SECOND heap entry with the same order id rests,
        doubling the visible quantity (review A4).
        """
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine)

        payload = order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.0)
        engine._handle_new_order(payload)
        engine._handle_new_order(dict(payload))  # replay, same order id

        book = engine.books[SYMBOL]
        resting_total = sum(book._bid_qty.values())
        assert resting_total == 100, (
            f"ADV: replaying one order.new message doubled resting liquidity "
            f"({resting_total} resting for a single 100-lot order) — duplicate "
            f"order ids must be rejected"
        )

        rejects = [
            m
            for m in msgs(pub, "order.ack.GW01")
            if m["order_id"] == payload["id"] and m.get("accepted") is False
        ]
        assert rejects, "ADV: the duplicate submission must be NACKed"


class TestNonPositiveQuantity:
    def test_zero_quantity_order_is_rejected_not_swallowed(
        self, monkeypatch, tmp_path
    ) -> None:
        """qty=0 passes the (nonexistent) engine validation, is ACKed
        accepted=True, matches nothing, rests nothing, notifies nothing
        (review M7)."""
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine)

        payload = order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.0)
        payload["quantity"] = 0
        payload["remaining_qty"] = 0
        engine._handle_new_order(payload)

        rejects = [
            m
            for m in msgs(pub, "order.ack.GW01")
            if m["order_id"] == payload["id"] and m.get("accepted") is False
        ]
        assert rejects, (
            "ADV: zero-quantity order must be rejected with a reasoned NACK "
            "(it was ACKed accepted=True and then silently dropped)"
        )


class TestMalformedIceberg:
    def test_visible_qty_exceeding_quantity_is_rejected_or_normalized(
        self, monkeypatch, tmp_path
    ) -> None:
        """visible_qty > quantity produces displayed_qty > remaining_qty and
        an inflated level index (review M7).  A correct engine rejects it or
        clamps the peak; either way the book invariants must hold."""
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine)

        payload = order_payload(
            Side.SELL,
            OrderType.ICEBERG,
            100,
            "GW01",
            price=100.0,
            visible_qty=100,
        )
        payload["visible_qty"] = 250
        payload["displayed_qty"] = 250
        engine._handle_new_order(payload)

        book = engine.books[SYMBOL]
        rejected = any(
            m["order_id"] == payload["id"] and m.get("accepted") is False
            for m in msgs(pub, "order.ack.GW01")
        )
        if not rejected:
            resting = book.get_order(payload["id"])
            assert resting is not None
            assert (resting.displayed_qty or 0) <= resting.remaining_qty, (
                f"ADV: iceberg accepted with displayed_qty="
                f"{resting.displayed_qty} > remaining_qty={resting.remaining_qty}"
            )
        assert_book_invariants(book, context="iceberg visible_qty > quantity")


class TestAmendPayloadTypes:
    def test_float_amend_quantity_is_rejected_or_coerced(
        self, monkeypatch, tmp_path
    ) -> None:
        """order.amend qty arrives from JSON and is applied unconverted; a
        float propagates into quantity/remaining_qty (review M12)."""
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine)

        payload = order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.0)
        engine._handle_new_order(payload)

        engine._handle_amend(
            {"order_id": payload["id"], "gateway_id": "GW01", "qty": 150.5}
        )

        resting = engine.books[SYMBOL].get_order(payload["id"])
        assert resting is not None
        assert isinstance(resting.quantity, int) and isinstance(
            resting.remaining_qty, int
        ), (
            f"ADV: float amend quantity leaked into the book "
            f"(quantity={resting.quantity!r}, remaining={resting.remaining_qty!r}) "
            f"— amend payloads must be validated/coerced like prices are"
        )

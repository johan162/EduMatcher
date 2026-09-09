"""Engine-side handling of the operator force-uncross (``reopen``).

Covers ``Engine._handle_force_uncross`` and the ``ADMIN_MANUAL`` branch of
``_run_uncross``: a targeted, single-symbol reopen that clears any halt and,
optionally, asserts the print price when a failed auction discovered none.
See docs-design/EduMatcher-Market-Order-in-Pre-opening.md section 15.
"""

from __future__ import annotations

from typing import Any

from edumatcher.models.order import Order, OrderStatus, OrderType, Side, TIF
from edumatcher.models.price import to_ticks

from tests.engine_harness import SYMBOL, FakeSock, all_msgs, connect, make_engine, msgs

ADMIN = "ADM"
_ACK = f"risk.force_uncross_ack.{ADMIN}"
_RESULT = f"auction.result.{SYMBOL}"


def _engine(monkeypatch, tmp_path):
    engine, pub = make_engine(
        monkeypatch,
        tmp_path,
        gateways=(ADMIN, "GW01", "GW02"),
        admin_gateways=(ADMIN,),
    )
    connect(engine, ADMIN, "GW01", "GW02")
    pub.sent.clear()
    return engine, pub


def _rest(engine: Any, side: Side, price: float, qty: int, oid: str) -> None:
    """Put one resting limit order on the book, without matching."""
    engine._book(SYMBOL).process(
        Order(
            id=oid,
            symbol=SYMBOL,
            side=side,
            order_type=OrderType.LIMIT,
            price=to_ticks(price, SYMBOL),
            quantity=qty,
            remaining_qty=qty,
            gateway_id="GW01",
            tif=TIF.DAY,
            timestamp=0,
            status=OrderStatus.NEW,
        ),
        match=False,
    )


def _acks(pub: FakeSock) -> list[dict[str, Any]]:
    return msgs(pub, _ACK)


def test_non_admin_is_rejected(monkeypatch, tmp_path) -> None:
    engine, pub = _engine(monkeypatch, tmp_path)
    engine._handle_force_uncross({"gateway_id": "GW01", "symbol": SYMBOL})
    ack = msgs(pub, "risk.force_uncross_ack.GW01")[-1]
    assert ack["accepted"] is False
    assert "ADMIN" in ack["reason"]


def test_unknown_symbol_is_rejected(monkeypatch, tmp_path) -> None:
    engine, pub = _engine(monkeypatch, tmp_path)
    engine._handle_force_uncross({"gateway_id": ADMIN, "symbol": "ZZZ"})
    ack = _acks(pub)[-1]
    assert ack["accepted"] is False
    assert "Unknown symbol" in ack["reason"]


def test_dry_run_returns_indicative_and_mutates_nothing(monkeypatch, tmp_path) -> None:
    engine, pub = _engine(monkeypatch, tmp_path)
    _rest(engine, Side.BUY, 100.0, 100, "b1")
    _rest(engine, Side.SELL, 99.0, 100, "s1")

    engine._handle_force_uncross(
        {"gateway_id": ADMIN, "symbol": SYMBOL, "dry_run": True}
    )

    ack = _acks(pub)[-1]
    assert ack["accepted"] is True
    assert ack["dry_run"] is True
    assert ack["indicative_price"] is not None
    assert ack["indicative_qty"] == 100

    # No uncross ran: nothing printed and the book still holds both orders.
    assert msgs(pub, _RESULT) == []
    assert len(list(engine._book(SYMBOL).resting_orders())) == 2


def test_dry_run_of_a_non_crossing_book_reports_null(monkeypatch, tmp_path) -> None:
    engine, pub = _engine(monkeypatch, tmp_path)
    _rest(engine, Side.BUY, 98.0, 100, "b1")
    _rest(engine, Side.SELL, 101.0, 100, "s1")

    engine._handle_force_uncross(
        {"gateway_id": ADMIN, "symbol": SYMBOL, "dry_run": True}
    )
    ack = _acks(pub)[-1]
    assert ack["accepted"] is True
    assert ack["indicative_price"] is None
    assert ack["indicative_qty"] == 0


def test_natural_reopen_prints_at_equilibrium(monkeypatch, tmp_path) -> None:
    engine, pub = _engine(monkeypatch, tmp_path)
    _rest(engine, Side.BUY, 100.0, 100, "b1")
    _rest(engine, Side.SELL, 99.0, 100, "s1")

    engine._handle_force_uncross({"gateway_id": ADMIN, "symbol": SYMBOL})

    ack = _acks(pub)[-1]
    assert ack["accepted"] is True
    assert ack["dry_run"] is False
    assert ack["printed_price"] is not None
    assert ack["traded_qty"] == 100

    result = msgs(pub, _RESULT)[-1]
    assert result["reason"] == "ADMIN_MANUAL"
    assert result["eq_qty"] == 100
    # The crossing interest is consumed.
    assert list(engine._book(SYMBOL).resting_orders()) == []


def test_manual_price_prints_at_the_asserted_price(monkeypatch, tmp_path) -> None:
    engine, pub = _engine(monkeypatch, tmp_path)
    # Bid above the offer: they cross. Forcing 100 prints there, not at any
    # midpoint the natural scan might pick.
    _rest(engine, Side.BUY, 101.0, 100, "b1")
    _rest(engine, Side.SELL, 100.0, 100, "s1")

    engine._handle_force_uncross(
        {"gateway_id": ADMIN, "symbol": SYMBOL, "price": 100.0, "note": "manual open"}
    )

    ack = _acks(pub)[-1]
    assert ack["accepted"] is True
    assert ack["printed_price"] == 100.0
    assert ack["traded_qty"] == 100
    assert msgs(pub, _RESULT)[-1]["eq_price"] == 100.0


def test_manual_price_on_a_failed_auction_prints_nothing(monkeypatch, tmp_path) -> None:
    engine, pub = _engine(monkeypatch, tmp_path)
    # One-sided book: no counterparty, so no natural equilibrium exists.
    _rest(engine, Side.BUY, 100.0, 100, "b1")

    engine._handle_force_uncross(
        {"gateway_id": ADMIN, "symbol": SYMBOL, "price": 100.0}
    )

    ack = _acks(pub)[-1]
    assert ack["accepted"] is True
    assert ack["printed_price"] is None
    assert ack["traded_qty"] == 0
    # The lone bid survives — nothing crossed it.
    assert len(list(engine._book(SYMBOL).resting_orders())) == 1


def test_reopen_clears_the_halt_and_publishes_a_resume(monkeypatch, tmp_path) -> None:
    engine, pub = _engine(monkeypatch, tmp_path)
    engine._halted_symbols[SYMBOL] = True
    _rest(engine, Side.BUY, 100.0, 100, "b1")
    _rest(engine, Side.SELL, 99.0, 100, "s1")

    engine._handle_force_uncross({"gateway_id": ADMIN, "symbol": SYMBOL})

    assert engine._halted_symbols[SYMBOL] is False
    topics = [t for t, _ in all_msgs(pub)]
    assert any(t.startswith("circuit_breaker.resume") for t in topics)
    # The uncross still ran once the halt was cleared.
    assert _acks(pub)[-1]["traded_qty"] == 100


def test_invalid_price_is_rejected(monkeypatch, tmp_path) -> None:
    engine, pub = _engine(monkeypatch, tmp_path)
    engine._handle_force_uncross({"gateway_id": ADMIN, "symbol": SYMBOL, "price": -5.0})
    ack = _acks(pub)[-1]
    assert ack["accepted"] is False
    assert "positive" in ack["reason"]

"""Engine-side publication of the indicative uncross during a call phase.

Covers ``Engine._flush_auction_indicative`` (T-M1): the imbalance indicator a
venue disseminates *while* an auction collects orders, as opposed to the
``auction.result`` it publishes once the uncross has happened. An imbalance
nobody can see before the uncross is an imbalance nobody can offset, and the
opening and closing auctions are where the largest volume of the day prints.
"""

from __future__ import annotations

import time
from typing import Any

from edumatcher.models.order import Order, OrderStatus, OrderType, Side, TIF
from edumatcher.models.price import to_ticks
from edumatcher.models.session import SessionState

from tests.engine_harness import SYMBOL, FakeSock, make_engine, msgs


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
        # Rest it without matching, which is what a call phase does.
        match=False,
    )


def _indicatives(pub: FakeSock) -> list[dict[str, Any]]:
    return msgs(pub, f"auction.indicative.{SYMBOL}")


def _force_due(engine: Any) -> None:
    """Make the interval elapsed, so the next flush publishes."""
    engine._last_auction_indicative = (
        time.monotonic() - engine.auction_indicative_interval_sec - 0.001
    )


def test_publishes_during_a_call_phase(monkeypatch, tmp_path) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    engine._session_state = SessionState.OPENING_AUCTION
    _rest(engine, Side.BUY, 100.0, 500, "b1")
    _rest(engine, Side.SELL, 99.0, 300, "s1")

    _force_due(engine)
    engine._flush_auction_indicative()

    published = _indicatives(pub)
    assert len(published) == 1
    assert published[0]["phase"] == "OPENING_AUCTION"
    # 300 would match; the 200 unfilled buy interest is the surplus.
    assert published[0]["eq_qty"] == 300
    assert published[0]["imbalance_side"] == "BUY"
    assert published[0]["imbalance_qty"] == 200


def test_silent_outside_a_call_phase(monkeypatch, tmp_path) -> None:
    """Continuous trading has no auction for an indicative to describe."""
    engine, pub = make_engine(monkeypatch, tmp_path)
    engine._session_state = SessionState.CONTINUOUS
    _rest(engine, Side.BUY, 100.0, 500, "b1")
    _rest(engine, Side.SELL, 99.0, 300, "s1")

    _force_due(engine)
    engine._flush_auction_indicative()

    assert _indicatives(pub) == []


def test_reports_a_book_that_would_not_cross(monkeypatch, tmp_path) -> None:
    """ "Nothing would trade yet" is a reading, not an absence of one.

    A client must be able to tell it apart from a price of zero, so the
    price is published as null rather than defaulted.
    """
    engine, pub = make_engine(monkeypatch, tmp_path)
    engine._session_state = SessionState.CLOSING_AUCTION
    # Bid below the offer: the two do not overlap.
    _rest(engine, Side.BUY, 98.0, 500, "b1")
    _rest(engine, Side.SELL, 101.0, 300, "s1")

    _force_due(engine)
    engine._flush_auction_indicative()

    published = _indicatives(pub)
    assert len(published) == 1
    assert published[0]["eq_price"] is None
    assert published[0]["eq_qty"] == 0


def test_republishes_an_unchanged_book(monkeypatch, tmp_path) -> None:
    """Every interval, including when nothing moved.

    Suppressing an unchanged reading would leave a client unable to tell a
    stable indicative from a stalled feed — the ambiguity T-M4 exists to
    remove everywhere else on this screen.
    """
    engine, pub = make_engine(monkeypatch, tmp_path)
    engine._session_state = SessionState.OPENING_AUCTION
    _rest(engine, Side.BUY, 100.0, 500, "b1")
    _rest(engine, Side.SELL, 99.0, 500, "s1")

    for _ in range(3):
        _force_due(engine)
        engine._flush_auction_indicative()

    assert len(_indicatives(pub)) == 3


def test_throttled_to_the_configured_interval(monkeypatch, tmp_path) -> None:
    # Bounded cost regardless of how heavy order entry gets: one pass over
    # the books per interval, not one message per book change.
    engine, pub = make_engine(monkeypatch, tmp_path)
    engine._session_state = SessionState.OPENING_AUCTION
    engine.auction_indicative_interval_sec = 3600.0
    _rest(engine, Side.BUY, 100.0, 500, "b1")

    _force_due(engine)
    engine._flush_auction_indicative()
    engine._flush_auction_indicative()
    engine._flush_auction_indicative()

    assert len(_indicatives(pub)) == 1


def test_skips_a_halted_symbol(monkeypatch, tmp_path) -> None:
    """A halt is its own reopening auction, with its own corridor.

    The circuit-breaker path already publishes an indicative for it. Two
    sources describing one symbol would eventually disagree.
    """
    engine, pub = make_engine(monkeypatch, tmp_path)
    engine._session_state = SessionState.OPENING_AUCTION
    engine._halted_symbols[SYMBOL] = True
    _rest(engine, Side.BUY, 100.0, 500, "b1")
    _rest(engine, Side.SELL, 99.0, 300, "s1")

    _force_due(engine)
    engine._flush_auction_indicative()

    assert _indicatives(pub) == []

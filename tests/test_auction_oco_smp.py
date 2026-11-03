from __future__ import annotations

import random

import pytest

from edumatcher.engine.auction import compute_equilibrium, execute_uncross
from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import Order, OrderStatus, OrderType, Side, SmpAction
from edumatcher.models.price import to_ticks
from edumatcher.models.session import SessionState
from tests.engine_harness import SYMBOL, connect, make_engine, msgs


def _rest(
    book: OrderBook,
    side: Side,
    price: float,
    gateway: str,
    *,
    qty: int = 10,
    smp: SmpAction = SmpAction.NONE,
) -> Order:
    order = Order.create(
        symbol=book.symbol,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=qty,
        gateway_id=gateway,
        price_ticks=to_ticks(price, book.symbol),
        smp_action=smp,
    )
    book.process(order, match=False)
    return order


def test_oco_sibling_cannot_fill_in_same_uncross(monkeypatch, tmp_path) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    engine._session_state = SessionState.OPENING_AUCTION
    book = engine._book(SYMBOL)
    _rest(book, Side.BUY, 101, "GW02", qty=20)
    engine._handle_oco_order(
        {
            "oco_id": "OCO-AUCTION",
            "gateway_id": "GW01",
            "symbol": SYMBOL,
            "quantity": 10,
            "tif": "DAY",
            "leg1": {"side": "SELL", "order_type": "LIMIT", "price_ticks": 10000},
            "leg2": {"side": "SELL", "order_type": "LIMIT", "price_ticks": 10100},
        }
    )
    (ack,) = msgs(pub, "oco.ack.GW01")
    assert ack["accepted"], ack
    assert compute_equilibrium(book).eq_qty == 10
    engine._run_uncross(reason="SCHEDULED")
    trades = msgs(pub, "trade.executed")
    assert sum(t["quantity"] for t in trades) == 10
    assert {t["sell_order_id"] for t in trades} == {ack["order_id_1"]}
    assert ack["order_id_2"] not in {o.id for o in book.resting_orders()}
    assert any(
        m["cancelled_order_id"] == ack["order_id_2"]
        for m in msgs(pub, "oco.cancelled.GW01")
    )


@pytest.mark.parametrize(
    ("policy", "cancelled"),
    [
        (SmpAction.CANCEL_AGGRESSOR, Side.BUY),
        (SmpAction.CANCEL_RESTING, Side.SELL),
        (SmpAction.CANCEL_BOTH, None),
    ],
)
def test_auction_smp_excludes_self_match_and_resolves_orders(
    monkeypatch, tmp_path, policy: SmpAction, cancelled: Side | None
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    book = engine._book(SYMBOL)
    bid = _rest(book, Side.BUY, 101, "GW01", smp=policy)
    ask = _rest(book, Side.SELL, 100, "GW01")
    assert compute_equilibrium(book).eq_qty == 0
    engine._run_uncross(reason="SCHEDULED")
    assert msgs(pub, "trade.executed") == []
    assert bid.status == (
        OrderStatus.CANCELLED if cancelled in (Side.BUY, None) else OrderStatus.NEW
    )
    assert ask.status == (
        OrderStatus.CANCELLED if cancelled in (Side.SELL, None) else OrderStatus.NEW
    )
    assert all(
        order.cancel_reason == "SELF_MATCH_PREVENTED"
        for order in (bid, ask)
        if order.status == OrderStatus.CANCELLED
    )


def test_auction_uses_ask_smp_when_bid_allows_self_match() -> None:
    book = OrderBook(SYMBOL)
    bid = _rest(book, Side.BUY, 101, "GW01")
    ask = _rest(book, Side.SELL, 100, "GW01", smp=SmpAction.CANCEL_AGGRESSOR)
    indicative = compute_equilibrium(book)
    assert indicative.eq_qty == 0
    # Nothing prints, so no equilibrium is published -- but the crossing
    # price is still reported so the uncross can resolve the self-match.
    assert indicative.eq_price is None
    assert indicative.resolve_price is not None
    trades, events = execute_uncross(book, indicative.resolve_price)
    assert trades == []
    assert ask in events and ask.status == OrderStatus.CANCELLED
    assert bid.status == OrderStatus.NEW


def test_opposing_oco_legs_never_trade_each_other(monkeypatch, tmp_path) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    engine._session_state = SessionState.OPENING_AUCTION
    engine._handle_oco_order(
        {
            "oco_id": "OPPOSING",
            "gateway_id": "GW01",
            "symbol": SYMBOL,
            "quantity": 10,
            "tif": "DAY",
            "leg1": {"side": "BUY", "order_type": "LIMIT", "price_ticks": 10100},
            "leg2": {"side": "SELL", "order_type": "LIMIT", "price_ticks": 10000},
        }
    )
    (ack,) = msgs(pub, "oco.ack.GW01")
    assert ack["accepted"], ack
    book = engine._book(SYMBOL)
    assert compute_equilibrium(book).eq_qty == 0
    engine._run_uncross(reason="SCHEDULED")
    assert msgs(pub, "trade.executed") == []
    assert book.resting_orders() == []


@pytest.mark.parametrize("with_oco", [False, True])
def test_indicative_matches_random_multi_gateway_uncross(with_oco: bool) -> None:
    rng = random.Random(73)
    for iteration in range(50):
        book = OrderBook(SYMBOL)
        resting: list[Order] = []
        for side in (Side.BUY, Side.SELL):
            for _ in range(5):
                resting.append(
                    _rest(
                        book,
                        side,
                        rng.choice((99.0, 100.0, 101.0)),
                        rng.choice(("GW01", "GW02", "GW03")),
                        qty=rng.randint(1, 15),
                        smp=rng.choice(tuple(SmpAction)),
                    )
                )
        if with_oco:
            # Pair up same-gateway orders into OCO groups and wire the
            # engine's sibling-cancel cascade onto the bare book.
            by_gateway: dict[str, list[Order]] = {}
            for order in resting:
                by_gateway.setdefault(order.gateway_id, []).append(order)
            for n, (gateway, orders) in enumerate(by_gateway.items()):
                for i in range(0, len(orders) - 1, 2):
                    # Unique per iteration: the suite-wide auction invariant
                    # accumulates fills across the whole test.
                    orders[i].oco_group_id = orders[i + 1].oco_group_id = (
                        f"OCO-{iteration}-{gateway}-{n}-{i}"
                    )

            def cascade(order: Order, _resting: list[Order] = resting) -> None:
                for sibling in _resting:
                    if (
                        sibling.id != order.id
                        and sibling.gateway_id == order.gateway_id
                        and sibling.oco_group_id == order.oco_group_id
                        and sibling.oco_group_id is not None
                    ):
                        book.cancel_order(sibling.id)

            book.on_oco_leg_done = cascade
        indicative = compute_equilibrium(book)
        trades, _ = execute_uncross(
            book, indicative.resolve_price or to_ticks(100, SYMBOL)
        )
        assert sum(t.quantity for t in trades) == indicative.eq_qty


def test_smp_cancelled_oco_leg_takes_its_sibling_out_of_the_indicative(
    monkeypatch, tmp_path
) -> None:
    """An SMP cancel ends an OCO leg, so the sibling must not count as
    indicative liquidity either -- the uncross cancels it too."""
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    engine._session_state = SessionState.OPENING_AUCTION
    engine._handle_oco_order(
        {
            "oco_id": "OCO-SMP",
            "gateway_id": "GW01",
            "symbol": SYMBOL,
            "quantity": 10,
            "tif": "DAY",
            "leg1": {"side": "SELL", "order_type": "LIMIT", "price_ticks": 10000},
            "leg2": {"side": "BUY", "order_type": "LIMIT", "price_ticks": 10000},
        }
    )
    (ack,) = msgs(pub, "oco.ack.GW01")
    assert ack["accepted"], ack
    book = engine._book(SYMBOL)
    _rest(book, Side.BUY, 101, "GW01", smp=SmpAction.CANCEL_RESTING)
    _rest(book, Side.SELL, 100, "GW02")
    _rest(book, Side.SELL, 100, "GW02")

    indicative = compute_equilibrium(book)
    engine._run_uncross(reason="SCHEDULED")
    traded = sum(t["quantity"] for t in msgs(pub, "trade.executed"))
    assert traded == 10
    assert indicative.eq_qty == traded


def test_fully_self_matched_auction_publishes_no_equilibrium_price(
    monkeypatch, tmp_path
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    engine._session_state = SessionState.OPENING_AUCTION
    book = engine._book(SYMBOL)
    _rest(book, Side.BUY, 101, "GW01", smp=SmpAction.CANCEL_BOTH)
    _rest(book, Side.SELL, 100, "GW01")

    engine._flush_auction_indicative()
    (indicative,) = msgs(pub, f"auction.indicative.{SYMBOL}")
    assert indicative["eq_price"] is None and indicative["eq_qty"] == 0

    engine._run_uncross(reason="SCHEDULED")
    (result,) = msgs(pub, f"auction.result.{SYMBOL}")
    assert result["eq_price"] is None and result["eq_qty"] == 0
    # The uncross still ran: the self-matched interest is gone from the book.
    assert book.resting_orders() == []

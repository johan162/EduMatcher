"""Stop-trigger cascades: every execution is reported, and nothing dead trades.

Regression tests for two engine bugs found by the simulation forensics
(docs-design/EduMatcher-Sim-Forensics-Workplan.md §9):

X1 — a stop triggered in a cascade that filled part of its quantity and had
     the rest cancelled got an ``order.cancelled`` but no ``order.fill``. The
     quote-submit, OCO, combo and auction-uncross paths published fills by the
     order's *final* status, so "filled, then cancelled" lost the fill (the
     new-order path had been fixed for this as "finding #5").
X3 — when a quote leg filled, its sibling was pulled only after the whole
     dispatch, so a stop triggered by that fill could still trade against the
     sibling the engine had just reported as cancelled.
"""

from __future__ import annotations

from typing import Any

from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType
from edumatcher.models.order import OrderType, Side, TIF
from edumatcher.models.session import SessionState
from tests.engine_harness import (
    SYMBOL,
    all_msgs,
    connect,
    make_engine,
    msgs,
    order_payload,
    resting_ids,
    submit_quote,
    terminal_notifications_for,
)


def new_order(engine: Any, **kw: Any) -> str:
    payload = order_payload(**kw)
    engine._handle_new_order(payload)
    return str(payload["id"])


def sell_stop(engine: Any, qty: int, stop: float, gw: str = "GW03") -> str:
    return new_order(
        engine,
        side=Side.SELL,
        order_type=OrderType.STOP,
        qty=qty,
        gateway_id=gw,
        stop_price=stop,
    )


def assert_every_trade_side_has_its_fill(pub: Any) -> None:
    """The B1 oracle of the forensics tool, inside one engine run."""
    fills: dict[tuple[str, str], int] = {}
    for topic, p in all_msgs(pub):
        if topic.startswith("order.fill."):
            for trade_id in p["trade_ids"]:
                key = (p["order_id"], trade_id)
                fills[key] = fills.get(key, 0) + 1
    for t in msgs(pub, "trade.executed"):
        for oid in (t["buy_order_id"], t["sell_order_id"]):
            assert fills.get((oid, t["id"])) == 1, (oid, t["id"])


def fill_then_cancel(pub: Any, gw: str, order_id: str, qty: int) -> None:
    """*order_id* was told it filled *qty*, then that the rest was cancelled."""
    notes = terminal_notifications_for(pub, gw, order_id)
    assert [(topic.split(".")[1], p.get("fill_qty")) for topic, p in notes] == [
        ("fill", qty),
        ("cancelled", None),
    ]
    assert notes[1][1]["cancel_reason"] == "INSUFFICIENT_LIQUIDITY"


# --- X1 ----------------------------------------------------------------------


def test_x1_a_stop_triggered_by_a_quote_is_told_about_its_partial_fill(
    monkeypatch, tmp_path
) -> None:
    """The sim's case: MM01's crossing bid triggers a sell stop, which sells
    what the bid has left and is then cancelled for lack of liquidity."""
    engine, pub = make_engine(
        monkeypatch,
        tmp_path,
        gateways=("GW02", "GW03", "MM01"),
        mm_gateways=("MM01",),
    )
    connect(engine, "GW02", "GW03", "MM01")
    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=20, gateway_id="GW02", price=100.0)  # fmt: skip
    stop = sell_stop(engine, qty=300, stop=100.0)

    submit_quote(engine, "MM01", bid_price=100.0, ask_price=101.0, bid_qty=200)

    fill_then_cancel(pub, "GW03", stop, 180)
    assert_every_trade_side_has_its_fill(pub)


def test_x1_a_stop_triggered_by_an_oco_leg_is_told_about_its_partial_fill(
    monkeypatch, tmp_path
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=20, gateway_id="GW02", price=100.0)  # fmt: skip
    stop = sell_stop(engine, qty=300, stop=100.0)

    engine._handle_oco_order(
        {
            "oco_id": "OCO1",
            "gateway_id": "GW01",
            "symbol": SYMBOL,
            "quantity": 200,
            "tif": "DAY",
            "tick_decimals": 2,
            "leg1": {"side": "BUY", "order_type": "LIMIT", "price_ticks": 10000},
            "leg2": {"side": "SELL", "order_type": "STOP", "stop_price_ticks": 9000},
        }
    )

    fill_then_cancel(pub, "GW03", stop, 180)
    assert_every_trade_side_has_its_fill(pub)


def test_x1_a_stop_triggered_by_a_combo_leg_is_told_about_its_partial_fill(
    monkeypatch, tmp_path
) -> None:
    """AON: both legs must be fully fillable up front, so the stop trades
    with a separate bid at 99 after the AAPL leg's print at 100."""
    engine, pub = make_engine(monkeypatch, tmp_path, symbols=(SYMBOL, "MSFT"))
    connect(engine)
    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=20, gateway_id="GW02", price=100.0)  # fmt: skip
    new_order(engine, side=Side.BUY, order_type=OrderType.LIMIT, qty=50, gateway_id="GW01", price=99.0)  # fmt: skip
    new_order(engine, side=Side.BUY, order_type=OrderType.LIMIT, qty=10, gateway_id="GW02", price=105.0, symbol="MSFT")  # fmt: skip
    stop = sell_stop(engine, qty=300, stop=100.0)

    combo = ComboOrder.create(
        combo_id="C1",
        gateway_id="GW01",
        combo_type=ComboType.AON,
        tif=TIF.DAY,
        legs=[
            ComboLeg(symbol=SYMBOL, side=Side.BUY, order_type=OrderType.LIMIT, quantity=20, tick_decimals=2, price_ticks=10000),  # fmt: skip
            ComboLeg(symbol="MSFT", side=Side.SELL, order_type=OrderType.LIMIT, quantity=10, tick_decimals=2, price_ticks=10500),  # fmt: skip
        ],
    )
    engine._handle_combo_order(combo.to_dict())

    fill_then_cancel(pub, "GW03", stop, 50)
    assert_every_trade_side_has_its_fill(pub)


def test_x1_a_stop_triggered_by_the_uncross_is_told_about_its_fill_and_cancel(
    monkeypatch, tmp_path
) -> None:
    """The auction path published fills by final status and no cancel at
    all: the stop's owner heard nothing."""
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    engine._session_state = SessionState.OPENING_AUCTION
    new_order(engine, side=Side.BUY, order_type=OrderType.LIMIT, qty=100, gateway_id="GW01", price=100.0)  # fmt: skip
    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=100, gateway_id="GW02", price=100.0)  # fmt: skip
    new_order(engine, side=Side.BUY, order_type=OrderType.LIMIT, qty=50, gateway_id="GW01", price=99.0)  # fmt: skip
    stop = sell_stop(engine, qty=300, stop=100.0)

    engine._run_uncross(reason="SCHEDULED")

    fill_then_cancel(pub, "GW03", stop, 50)
    assert_every_trade_side_has_its_fill(pub)


# --- X3 ----------------------------------------------------------------------


def test_x3_a_stop_triggered_by_a_quote_fill_cannot_trade_with_the_pulled_sibling(
    monkeypatch, tmp_path
) -> None:
    """The sim's case: a seller hits MM01's bid, the quote is inactivated and
    its ask pulled; a buy stop triggered by that very trade must buy from the
    next ask, not from the leg MM01 was just told is cancelled."""
    engine, pub = make_engine(
        monkeypatch,
        tmp_path,
        gateways=("GW01", "GW02", "GW03", "MM01"),
        mm_gateways=("MM01",),
    )
    connect(engine, "GW01", "GW02", "GW03", "MM01")
    submit_quote(engine, "MM01", bid_price=100.0, ask_price=100.5)
    (ack,) = msgs(pub, "quote.ack.MM01")
    ask_leg = ack["ask_order_id"]
    behind = new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=100, gateway_id="GW01", price=101.0)  # fmt: skip
    stop = new_order(engine, side=Side.BUY, order_type=OrderType.STOP, qty=50, gateway_id="GW03", stop_price=100.0)  # fmt: skip

    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=30, gateway_id="GW02", price=100.0)  # fmt: skip

    trades = msgs(pub, "trade.executed")
    assert all(ask_leg not in (t["buy_order_id"], t["sell_order_id"]) for t in trades)
    (stop_trade,) = [t for t in trades if t["buy_order_id"] == stop]
    assert (stop_trade["sell_order_id"], stop_trade["price"]) == (behind, 101.0)
    # The pulled leg is cancelled exactly once, for the documented reason,
    # and never filled.
    notes = terminal_notifications_for(pub, "MM01", ask_leg)
    assert [(topic, p.get("cancel_reason")) for topic, p in notes] == [
        ("order.cancelled.MM01", "QUOTE_LEG_FILLED")
    ]
    assert ask_leg not in resting_ids(engine.books[SYMBOL])
    assert_every_trade_side_has_its_fill(pub)


def test_x3_quote_kept_live_by_policy_still_trades_with_the_stop(
    monkeypatch, tmp_path
) -> None:
    """INACTIVATE_ON_FULL_FILL keeps the quote after a partial fill, so the
    ask legitimately stays in the book and the stop may buy from it."""
    from edumatcher.models.quote import QuoteRefreshPolicy

    engine, pub = make_engine(
        monkeypatch,
        tmp_path,
        gateways=("GW02", "GW03", "MM01"),
        mm_gateways=("MM01",),
    )
    assert engine._engine_config is not None
    engine._engine_config.fix_gateways["MM01"].quote_refresh_policy = (
        QuoteRefreshPolicy.INACTIVATE_ON_FULL_FILL
    )
    connect(engine, "GW02", "GW03", "MM01")
    submit_quote(engine, "MM01", bid_price=100.0, ask_price=100.5)
    (ack,) = msgs(pub, "quote.ack.MM01")
    stop = new_order(engine, side=Side.BUY, order_type=OrderType.STOP, qty=50, gateway_id="GW03", stop_price=100.0)  # fmt: skip

    new_order(engine, side=Side.SELL, order_type=OrderType.LIMIT, qty=30, gateway_id="GW02", price=100.0)  # fmt: skip

    (stop_trade,) = [
        t for t in msgs(pub, "trade.executed") if t["buy_order_id"] == stop
    ]
    assert stop_trade["sell_order_id"] == ack["ask_order_id"]
    assert stop_trade["price"] == 100.5
    assert_every_trade_side_has_its_fill(pub)

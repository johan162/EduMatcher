"""A quote that trades on entry follows its gateway's refresh policy.

Regression tests for X8a (docs-design/EduMatcher-Sim-Forensics-Workplan.md
§9): a quote whose bid filled on entry published INACTIVE_BID_FILLED, the
fill, then quote.ack and quote.status ACTIVE, and rested its ask -- against
the participant guide (INACTIVATE_ON_ANY_FILL: "sibling leg cancelled,
quote removed"). The bid's fill inactivated the quote before the ask was
posted, so the sibling cancel found nothing to cancel.
"""

from __future__ import annotations

from typing import Any

from edumatcher.models.order import OrderType, Side
from edumatcher.models.quote import QuoteRefreshPolicy
from tests.engine_harness import (
    SYMBOL,
    all_msgs,
    connect,
    make_engine,
    order_payload,
    submit_quote,
)

MM = "GW03"


def setup(monkeypatch: Any, tmp_path: Any, policy: QuoteRefreshPolicy) -> Any:
    engine, pub = make_engine(monkeypatch, tmp_path, mm_gateways=(MM,))
    connect(engine)
    assert engine._engine_config is not None
    engine._engine_config.fix_gateways[MM].quote_refresh_policy = policy
    return engine, pub


def rest(engine: Any, side: Side, qty: int, price: float) -> None:
    engine._handle_new_order(order_payload(side, OrderType.LIMIT, qty, "GW01", price=price))  # fmt: skip


def mm_story(pub: Any, start: int) -> list[tuple[str, Any]]:
    """The market maker's messages from *start*: quote acks and statuses,
    and its legs' fills and cancels (by leg side)."""
    out: list[tuple[str, Any]] = []
    legs: dict[str, str] = {}
    for topic, p in all_msgs(pub)[start:]:
        if topic == f"quote.ack.{MM}":
            legs = {p["bid_order_id"]: "bid", p["ask_order_id"]: "ask"}
            out.append(("ack", p["accepted"]))
        elif topic == f"quote.status.{MM}":
            out.append(("status", p["status"]))
        elif topic == f"order.fill.{MM}":
            out.append(("fill", legs.get(p["order_id"], p["order_id"])))
        elif topic == f"order.cancelled.{MM}":
            out.append(("cancelled", (legs.get(p["order_id"], p["order_id"]), p.get("cancel_reason"))))  # fmt: skip
    return out


def mm_resting(engine: Any) -> list[tuple[str, int]]:
    return sorted(
        (o.side.value, o.remaining_qty)
        for o in engine.books[SYMBOL].resting_orders()
        if o.gateway_id == MM
    )


def test_x8a_a_bid_filled_on_entry_inactivates_the_quote_and_never_rests_the_ask(
    monkeypatch, tmp_path
) -> None:
    engine, pub = setup(monkeypatch, tmp_path, QuoteRefreshPolicy.INACTIVATE_ON_ANY_FILL)  # fmt: skip
    rest(engine, Side.SELL, 100, 100.0)
    n = len(pub.sent)
    submit_quote(engine, MM, 100.0, 101.0)
    story = mm_story(pub, n)
    assert story[:2] == [("ack", True), ("status", "ACTIVE")]
    assert [e for e in story if e[0] == "status"][-1] == ("status", "INACTIVE_BID_FILLED")  # fmt: skip
    assert ("cancelled", ("ask", "QUOTE_LEG_FILLED")) in story
    assert mm_resting(engine) == []
    assert engine._quote_index.get(MM, SYMBOL) is None


def test_x8a_a_partly_filled_bid_rests_its_remainder_but_not_the_ask(
    monkeypatch, tmp_path
) -> None:
    """INACTIVATE_ON_ANY_FILL keeps the hit leg's remainder live (as for a
    resting leg) and cancels only the sibling."""
    engine, pub = setup(monkeypatch, tmp_path, QuoteRefreshPolicy.INACTIVATE_ON_ANY_FILL)  # fmt: skip
    rest(engine, Side.SELL, 40, 100.0)
    submit_quote(engine, MM, 100.0, 101.0)
    assert mm_resting(engine) == [("BUY", 60)]


def test_x8a_an_ask_filled_on_entry_cancels_the_resting_bid_and_ends_inactive(
    monkeypatch, tmp_path
) -> None:
    engine, pub = setup(monkeypatch, tmp_path, QuoteRefreshPolicy.INACTIVATE_ON_ANY_FILL)  # fmt: skip
    rest(engine, Side.BUY, 100, 101.0)
    n = len(pub.sent)
    submit_quote(engine, MM, 99.0, 101.0)
    story = mm_story(pub, n)
    assert story[:2] == [("ack", True), ("status", "ACTIVE")]
    assert [e for e in story if e[0] == "status"][-1] == ("status", "INACTIVE_ASK_FILLED")  # fmt: skip
    assert ("cancelled", ("bid", "QUOTE_LEG_FILLED")) in story
    assert mm_resting(engine) == []


def test_x8a_on_full_fill_policy_a_partial_entry_fill_keeps_the_quote_active(
    monkeypatch, tmp_path
) -> None:
    engine, pub = setup(monkeypatch, tmp_path, QuoteRefreshPolicy.INACTIVATE_ON_FULL_FILL)  # fmt: skip
    rest(engine, Side.SELL, 40, 100.0)
    n = len(pub.sent)
    submit_quote(engine, MM, 100.0, 101.0)
    story = mm_story(pub, n)
    assert story[:2] == [("ack", True), ("status", "ACTIVE")]
    assert [e for e in story if e[0] == "status"] == [("status", "ACTIVE")]
    assert mm_resting(engine) == [("BUY", 60), ("SELL", 100)]
    assert engine._quote_index.get(MM, SYMBOL) is not None


def test_x8a_the_quote_history_records_both_legs(monkeypatch, tmp_path) -> None:
    engine, pub = setup(monkeypatch, tmp_path, QuoteRefreshPolicy.INACTIVATE_ON_ANY_FILL)  # fmt: skip
    rest(engine, Side.SELL, 100, 100.0)
    submit_quote(engine, MM, 100.0, 101.0)
    (recent,) = engine._quote_index.recent_for_gateway(MM, SYMBOL)
    assert recent.reason == "INACTIVE_BID_FILLED"
    assert recent.bid_leg is not None and recent.ask_leg is not None
    assert recent.ask_leg.status == "CANCELLED"

"""A combo leg that ends while the combo is being accepted fails the combo.

Regression tests for X21 of the simulation forensics
(docs-design/EduMatcher-Sim-Forensics-Workplan.md §9): the engine registered
a combo only after posting all its children, so a child rejected or cancelled
on entry ran a combo follow-up that found no combo. The combo stayed PENDING
with its other legs resting, and could never match. Now ``combo.ack`` comes
first, as the participant guide says, a leg ending without filling fails the
combo like a later cancel would, and legs after it are never posted.
"""

from __future__ import annotations

from typing import Any

from edumatcher.models.combo import ComboStatus
from edumatcher.models.order import OrderType, Side
from tests.engine_harness import all_msgs, connect, make_engine, msgs, order_payload

AAPL_IOC = {"symbol": "AAPL", "side": "BUY", "order_type": "IOC", "quantity": 5, "price_ticks": 10000}  # fmt: skip
MSFT_LIMIT = {"symbol": "MSFT", "side": "BUY", "order_type": "LIMIT", "quantity": 5, "price_ticks": 10000}  # fmt: skip


def sell(engine: Any, symbol: str, gw: str, qty: int = 5) -> None:
    engine._handle_new_order(
        order_payload(
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            qty=qty,
            gateway_id=gw,
            price=100.0,
            symbol=symbol,
        )
    )


def combo(engine: Any, legs: list[dict[str, Any]]) -> Any:
    engine._handle_combo_order(
        {
            "combo_id": "C1",
            "gateway_id": "GW01",
            "combo_type": "AON",
            "tif": "DAY",
            "legs": legs,
        }
    )
    return next(c for c in engine._combos.values() if c.combo_id == "C1")


def combo_topics(pub: Any) -> list[str]:
    """GW01's combo and order messages, in publication order."""
    return [
        t.removesuffix(".GW01") + (f"({p['status']})" if t.startswith("combo.status") else "")  # fmt: skip
        for t, p in all_msgs(pub)
        if t.endswith(".GW01") and t.split(".")[0] in ("combo", "order")
    ]


def resting(engine: Any) -> set[str]:
    return {o.id for book in engine.books.values() for o in book.resting_orders()}


def test_a_leg_rejected_on_acceptance_fails_the_combo(monkeypatch, tmp_path) -> None:  # fmt: skip
    """Leg 1's IOC is rejected on its halted symbol: leg 0, already
    resting, is cancelled and the combo FAILS instead of staying PENDING."""
    engine, pub = make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
    connect(engine)
    engine._halted_symbols["AAPL"] = True

    c = combo(engine, [MSFT_LIMIT, AAPL_IOC])

    assert combo_topics(pub) == [
        "combo.ack",
        "order.ack",
        "order.ack",
        "order.cancelled",
        "combo.status(FAILED)",
    ]
    (status,) = msgs(pub, "combo.status.GW01")
    assert status["reason"] == "Leg 1 (AAPL) REJECTED"
    assert c.status is ComboStatus.FAILED
    assert resting(engine) == set()


def test_legs_after_a_failed_one_are_never_posted(monkeypatch, tmp_path) -> None:
    """Leg 0 is rejected; leg 1 would only be acked and cancelled."""
    engine, pub = make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
    connect(engine)
    engine._halted_symbols["AAPL"] = True

    c = combo(engine, [AAPL_IOC, MSFT_LIMIT])

    assert combo_topics(pub) == ["combo.ack", "order.ack", "combo.status(FAILED)"]
    assert len(c.child_order_ids) == 1
    assert resting(engine) == set()


def test_an_aon_combo_held_back_with_an_ioc_leg_fails(monkeypatch, tmp_path) -> None:
    """MSFT has no seller, so the AON combo posts without matching and
    its AAPL IOC is rejected: the probe that found X21."""
    engine, pub = make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
    connect(engine)
    sell(engine, "AAPL", "GW02")

    c = combo(engine, [MSFT_LIMIT, AAPL_IOC])

    assert c.status is ComboStatus.FAILED
    assert msgs(pub, "trade.executed") == []
    assert {o.gateway_id for o in engine.books["AAPL"].resting_orders()} == {"GW02"}
    assert engine.books["MSFT"].resting_orders() == []


def test_a_leg_cancelled_by_smp_on_acceptance_fails_the_combo(monkeypatch, tmp_path) -> None:  # fmt: skip
    """Leg 0 crosses GW01's own AAPL offer and SMP cancels it."""
    engine, pub = make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
    connect(engine)
    sell(engine, "AAPL", "GW01")
    sell(engine, "MSFT", "GW02")

    c = combo(
        engine,
        [
            {**AAPL_IOC, "order_type": "LIMIT", "smp_action": "CANCEL_AGGRESSOR"},
            MSFT_LIMIT,
        ],
    )

    assert c.status is ComboStatus.FAILED
    assert len(c.child_order_ids) == 1
    assert msgs(pub, "trade.executed") == []
    assert {o.gateway_id for o in engine.books["MSFT"].resting_orders()} == {"GW02"}


def test_a_combo_that_fills_on_entry_is_acked_first_and_matched_once(
    monkeypatch, tmp_path
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
    connect(engine)
    sell(engine, "AAPL", "GW02")
    sell(engine, "MSFT", "GW02")

    c = combo(engine, [{**AAPL_IOC, "order_type": "LIMIT"}, MSFT_LIMIT])

    assert combo_topics(pub) == [
        "combo.ack",
        "order.ack",
        "order.fill",
        "combo.status(PARTIALLY_MATCHED)",
        "order.ack",
        "order.fill",
        "combo.status(MATCHED)",
    ]
    assert c.status is ComboStatus.MATCHED


# --- X28: an all-or-none combo is accepted only if it can fill in full ------

AAPL_LIMIT = {**AAPL_IOC, "order_type": "LIMIT"}


def test_an_aon_combo_that_cannot_fill_in_full_fails_on_entry(monkeypatch, tmp_path) -> None:  # fmt: skip
    """AAPL has a seller, MSFT none. The engine used to rest both legs
    unmatched, the AAPL leg crossed with the seller (X28, 1 670 combos on
    the 2026-10-29 run); now the leg that would trade rejects the combo:
    leg 0 is rejected as a FOK short of liquidity would be, and leg 1 is
    never posted."""
    engine, pub = make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
    connect(engine)
    sell(engine, "AAPL", "GW02")

    c = combo(engine, [AAPL_LIMIT, MSFT_LIMIT])

    assert combo_topics(pub) == ["combo.ack", "order.ack", "combo.status(FAILED)"]
    (ack,) = msgs(pub, "order.ack.GW01")
    assert (ack["accepted"], ack["reject_code"]) == (False, "INSUFFICIENT_LIQUIDITY")
    assert c.status is ComboStatus.FAILED
    assert msgs(pub, "trade.executed") == []
    assert {o.gateway_id for o in engine.books["AAPL"].resting_orders()} == {"GW02"}
    assert engine.books["MSFT"].resting_orders() == []


def test_an_aon_combo_with_no_leg_that_would_trade_rests(monkeypatch, tmp_path) -> None:  # fmt: skip
    """A pair at passive limit prices waits for liquidity, as before."""
    engine, pub = make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
    connect(engine)

    c = combo(engine, [AAPL_LIMIT, MSFT_LIMIT])

    assert c.status is ComboStatus.PENDING
    assert resting(engine) == set(c.child_order_ids) and len(c.child_order_ids) == 2


def test_an_aon_combo_rests_while_its_legs_cannot_match(monkeypatch, tmp_path) -> None:  # fmt: skip
    """With no matching there is no liquidity to judge: the legs rest as
    interest, as any limit order does in a call phase."""
    engine, pub = make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
    connect(engine)
    sell(engine, "AAPL", "GW02")
    engine._halted_symbols.update(AAPL=True, MSFT=True)

    c = combo(engine, [AAPL_LIMIT, MSFT_LIMIT])

    assert c.status is ComboStatus.PENDING
    assert resting(engine) >= set(c.child_order_ids) and len(c.child_order_ids) == 2


def test_a_seeded_aon_combo_rests_as_market_maker_interest(monkeypatch, tmp_path) -> None:  # fmt: skip
    """market_maker_combos are AON and meant to rest, matching on or not."""
    from edumatcher.models.combo import ComboOrder

    engine, pub = make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
    connect(engine)
    seed = ComboOrder.from_submission_dict(
        {"combo_id": "S1", "gateway_id": "GW01", "combo_type": "AON", "tif": "GTC", "legs": [AAPL_LIMIT, MSFT_LIMIT]}  # fmt: skip
    )

    assert engine._accept_combo(seed, publish_ack=False, is_seed=True)

    assert seed.status is ComboStatus.PENDING
    assert len(seed.child_order_ids) == 2

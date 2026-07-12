"""
Cross-flow guarantee suite: every engine-level guarantee, parametrized over
every flow that can produce an execution.

Systemic gap this closes (review §10, root cause of H3/H4/H5/H9/C5): the
old tests were siloed per flow, so a guard implemented in one handler and
forgotten in another was invisible.  Here each GUARANTEE is one test,
parametrized over FLOW constructors — adding a new entry path to the
matrix automatically subjects it to every guarantee, and a guard added to
only one handler fails the others loudly.

Flows (each produces exactly ONE trade: GW01 buys 100 @ 101.00 from GW02):
  order          — plain limit order via _handle_new_order
  quote          — MM quote whose bid crosses (GW01 is MARKET_MAKER)
  oco            — OCO whose leg 1 crosses
  combo          — combo whose AAPL leg crosses (MSFT leg rests)
  stop_triggered — GW01 stop that triggers off a first trade, then executes
  auction        — both sides rest in PRE_OPEN, uncross on transition

Expected state today (review findings in parentheses):
  fills_published    fails for combo* / market-remainder cases  (C4-family)
  fill_msgs_unique   fails for quote/combo/oco multi-level      (H5)
  positions_updated  fails for quote/oco/combo                  (H3)
  drop_copy          fails for quote/oco/combo/auction          (H4)
  no_preopen_match   fails for quote/combo                      (H9)
"""

from __future__ import annotations

from typing import Any, Callable

import pytest

from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType
from edumatcher.models.order import OrderType, Side, TIF

from tests.engine_harness import (
    SYMBOL,
    FakeDropCopy,
    connect,
    make_engine,
    msgs,
    order_payload,
    submit_quote,
)

QTY = 100
PRICE = 101.0
PRICE_TICKS = 10100


# ---------------------------------------------------------------------------
# Flow constructors.  Each returns the aggressing GW01 order id (or None if
# the flow cannot expose one) after producing exactly one 100 @ 101.00 trade
# between GW01 (buy) and GW02 (sell).
# ---------------------------------------------------------------------------


def _rest_gw02_ask(engine, price: float = PRICE, qty: int = QTY) -> dict[str, Any]:
    p = order_payload(Side.SELL, OrderType.LIMIT, qty, "GW02", price=price)
    engine._handle_new_order(p)
    return p


def flow_order(engine, pub) -> str | None:
    _rest_gw02_ask(engine)
    p = order_payload(Side.BUY, OrderType.LIMIT, QTY, "GW01", price=PRICE)
    engine._handle_new_order(p)
    return p["id"]


def flow_quote(engine, pub) -> str | None:
    _rest_gw02_ask(engine)
    submit_quote(engine, "GW01", bid_price=PRICE, ask_price=PRICE + 1.0, bid_qty=QTY)
    acks = [m for m in msgs(pub, "quote.ack.GW01") if m.get("accepted")]
    return acks[0]["bid_order_id"] if acks else None


def flow_oco(engine, pub) -> str | None:
    _rest_gw02_ask(engine)
    engine._handle_oco_order(
        {
            "oco_id": "OCO-XF",
            "gateway_id": "GW01",
            "symbol": SYMBOL,
            "quantity": QTY,
            "tif": "DAY",
            "leg1": {"side": "BUY", "order_type": "LIMIT", "price": PRICE},
            "leg2": {"side": "SELL", "order_type": "LIMIT", "price": 130.0},
        }
    )
    acks = [m for m in msgs(pub, "oco.ack.GW01") if m.get("accepted")]
    return acks[0]["order_id_1"] if acks else None


def flow_combo(engine, pub) -> str | None:
    _rest_gw02_ask(engine)
    combo = ComboOrder.create(
        combo_id="CMB-XF",
        gateway_id="GW01",
        combo_type=ComboType.AON,
        tif=TIF.DAY,
        legs=[
            ComboLeg(
                symbol=SYMBOL,
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                quantity=QTY,
                price=PRICE_TICKS,
            ),
            ComboLeg(
                symbol="MSFT",
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                quantity=10,
                price=5000,  # rests, never trades
            ),
        ],
    )
    engine._handle_combo_order(combo.to_dict())
    acks = [m for m in msgs(pub, "combo.ack.GW01") if m.get("accepted")]
    if not acks:
        return None
    child_ids = acks[0].get("combo", {}).get("child_order_ids", [])
    return child_ids[0] if child_ids else None


def flow_stop_triggered(engine, pub) -> str | None:
    # Liquidity: trigger level (100.00) and execution level (101.00).
    _rest_gw02_ask(engine, price=100.0, qty=50)
    _rest_gw02_ask(engine, price=PRICE, qty=QTY)
    # GW01 stop: converts to MARKET when a trade prints at/above 100.00.
    stop = order_payload(
        Side.BUY, OrderType.STOP, QTY, "GW01", stop_price=100.0
    )
    engine._handle_new_order(stop)
    # GW03 takes the 100.00 level → trade @100 triggers GW01's stop, which
    # then executes 100 @ 101.00 (50 remain at the trigger level? no — GW03
    # takes all 50, so the stop's market order fills at the 101.00 level).
    engine._handle_new_order(
        order_payload(Side.BUY, OrderType.LIMIT, 50, "GW03", price=100.0)
    )
    return stop["id"]


def flow_auction(engine, pub) -> str | None:
    # sessions_enabled engines start CLOSED; collect in PRE_OPEN, uncross
    # on the transition into CONTINUOUS.
    engine._handle_session_transition({"to_state": "PRE_OPEN"})
    _rest_gw02_ask(engine)
    p = order_payload(Side.BUY, OrderType.LIMIT, QTY, "GW01", price=PRICE)
    engine._handle_new_order(p)
    engine._handle_session_transition({"to_state": "CONTINUOUS"})
    return p["id"]


FLOWS: dict[str, Callable] = {
    "order": flow_order,
    "quote": flow_quote,
    "oco": flow_oco,
    "combo": flow_combo,
    "stop_triggered": flow_stop_triggered,
    "auction": flow_auction,
}

FLOW_PARAMS = list(FLOWS.keys())


def _run_flow(monkeypatch, tmp_path, flow_name: str):
    engine, pub = make_engine(
        monkeypatch,
        tmp_path,
        symbols=(SYMBOL, "MSFT"),
        mm_gateways=("GW01",),
        sessions_enabled=(flow_name == "auction"),
    )
    drop = FakeDropCopy()
    engine._drop_copy = drop
    connect(engine)
    aggressor_id = FLOWS[flow_name](engine, pub)
    return engine, pub, drop, aggressor_id


def _gw01_trades(pub) -> list[dict[str, Any]]:
    return [
        t
        for t in msgs(pub, "trade.executed")
        if t["buy_gateway_id"] == "GW01" and t["symbol"] == SYMBOL
    ]


# ---------------------------------------------------------------------------
# G0 — sanity: every flow really produces the trade under test.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flow_name", FLOW_PARAMS)
def test_g0_flow_produces_the_trade(monkeypatch, tmp_path, flow_name) -> None:
    engine, pub, drop, _ = _run_flow(monkeypatch, tmp_path, flow_name)
    trades = _gw01_trades(pub)
    assert len(trades) == 1, f"flow '{flow_name}' should print exactly one GW01 trade"
    assert trades[0]["quantity"] == QTY
    assert trades[0]["price"] == PRICE


# ---------------------------------------------------------------------------
# G1 — every execution produces a fill notification for BOTH counterparties.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flow_name", FLOW_PARAMS)
def test_g1_both_counterparties_receive_fill_messages(
    monkeypatch, tmp_path, flow_name
) -> None:
    engine, pub, drop, aggressor_id = _run_flow(monkeypatch, tmp_path, flow_name)
    assert _gw01_trades(pub), "precondition"

    gw01_fills = msgs(pub, "order.fill.GW01")
    gw02_fills = [
        m for m in msgs(pub, "order.fill.GW02") if m.get("symbol", SYMBOL) == SYMBOL
    ]
    assert gw01_fills, (
        f"[{flow_name}] trade printed but the aggressor (GW01) received no "
        f"order.fill message"
    )
    assert gw02_fills, (
        f"[{flow_name}] trade printed but the passive side (GW02) received no "
        f"order.fill message"
    )
    if aggressor_id is not None:
        mine = [m for m in gw01_fills if m["order_id"] == aggressor_id]
        assert mine, (
            f"[{flow_name}] no fill message references the aggressing order "
            f"{aggressor_id[:8]}"
        )


# ---------------------------------------------------------------------------
# G2 — fill messages for one order are never duplicated.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flow_name", FLOW_PARAMS)
def test_g2_fill_messages_are_unique_per_order(
    monkeypatch, tmp_path, flow_name
) -> None:
    engine, pub, drop, _ = _run_flow(monkeypatch, tmp_path, flow_name)
    assert _gw01_trades(pub), "precondition"

    for gw in ("GW01", "GW02"):
        per_order: dict[str, list[tuple]] = {}
        for m in msgs(pub, f"order.fill.{gw}"):
            sig = (m.get("fill_qty"), m.get("remaining_qty"), m.get("fill_price"))
            per_order.setdefault(m["order_id"], []).append(sig)
        for oid, sigs in per_order.items():
            assert len(sigs) == len(set(sigs)), (
                f"[{flow_name}] duplicate fill messages for order {oid[:8]} "
                f"on {gw}: {sigs}"
            )


# ---------------------------------------------------------------------------
# G3 — the position ledger reflects the execution for BOTH counterparties.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flow_name", FLOW_PARAMS)
def test_g3_positions_updated_for_both_sides(
    monkeypatch, tmp_path, flow_name
) -> None:
    engine, pub, drop, _ = _run_flow(monkeypatch, tmp_path, flow_name)
    assert _gw01_trades(pub), "precondition"

    gw01 = engine._gateway_positions.get("GW01", {}).get(SYMBOL, 0)
    gw02 = engine._gateway_positions.get("GW02", {}).get(SYMBOL, 0)
    assert gw01 == QTY, (
        f"[{flow_name}] buyer position not updated (expected +{QTY}, got {gw01})"
    )
    # GW02 may have sold at 100.00 AND 101.00 in the stop flow.
    assert gw02 <= -QTY, (
        f"[{flow_name}] seller position not updated (expected <= -{QTY}, got {gw02})"
    )


# ---------------------------------------------------------------------------
# G4 — every fill reaches the drop-copy feed.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flow_name", FLOW_PARAMS)
def test_g4_fills_reach_drop_copy(monkeypatch, tmp_path, flow_name) -> None:
    engine, pub, drop, _ = _run_flow(monkeypatch, tmp_path, flow_name)
    assert _gw01_trades(pub), "precondition"

    fill_gws = {gw for gw, ev, _ in drop.events if ev == "order.fill"}
    assert "GW01" in fill_gws and "GW02" in fill_gws, (
        f"[{flow_name}] trade printed but drop copy carries fills only for "
        f"{sorted(fill_gws) or 'nobody'} — clearing/risk feed is incomplete"
    )


# ---------------------------------------------------------------------------
# G5 — no flow may match while the session is in a no-matching phase.
# ---------------------------------------------------------------------------

_PREOPEN_FLOWS = ["order", "quote", "oco", "combo"]


@pytest.mark.parametrize("flow_name", _PREOPEN_FLOWS)
def test_g5_no_flow_matches_during_pre_open(
    monkeypatch, tmp_path, flow_name
) -> None:
    engine, pub = make_engine(
        monkeypatch,
        tmp_path,
        symbols=(SYMBOL, "MSFT"),
        mm_gateways=("GW01",),
        sessions_enabled=True,
    )
    connect(engine)
    engine._handle_session_transition({"to_state": "PRE_OPEN"})

    FLOWS[flow_name](engine, pub)

    trades = msgs(pub, "trade.executed")
    assert trades == [], (
        f"[{flow_name}] {len(trades)} trade(s) executed during PRE_OPEN — "
        f"no continuous matching may occur outside CONTINUOUS, whichever "
        f"flow carried the order"
    )

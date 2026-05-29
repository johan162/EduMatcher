from __future__ import annotations

from edumatcher.models.mm_obligation import MMPState, MarketMakerObligation
from edumatcher.models.quote import QuoteEntry, QuoteIndex


def test_quote_index_put_and_get() -> None:
    idx = QuoteIndex()
    q = QuoteEntry(
        quote_id="Q1",
        gateway_id="GW01",
        symbol="AAPL",
        bid_order_id="B1",
        ask_order_id="S1",
    )
    replaced = idx.put(q)
    assert replaced is None
    got = idx.get("GW01", "AAPL")
    assert got is not None
    assert got.quote_id == "Q1"


def test_quote_index_replace_existing_entry() -> None:
    idx = QuoteIndex()
    q1 = QuoteEntry(
        quote_id="Q1",
        gateway_id="GW01",
        symbol="AAPL",
        bid_order_id="B1",
        ask_order_id="S1",
    )
    q2 = QuoteEntry(
        quote_id="Q2",
        gateway_id="GW01",
        symbol="AAPL",
        bid_order_id="B2",
        ask_order_id="S2",
    )
    idx.put(q1)
    old = idx.put(q2)
    assert old is not None
    assert old.quote_id == "Q1"
    current = idx.get("GW01", "AAPL")
    assert current is not None
    assert current.quote_id == "Q2"


def test_quote_counterpart_order_id() -> None:
    q = QuoteEntry(
        quote_id="Q1",
        gateway_id="GW01",
        symbol="AAPL",
        bid_order_id="B1",
        ask_order_id="S1",
    )
    assert q.counterpart_order_id("BUY") == "S1"
    assert q.counterpart_order_id("SELL") == "B1"


def test_quote_index_cancel_for_gateway() -> None:
    idx = QuoteIndex()
    idx.put(QuoteEntry("Q1", "GW01", "AAPL", "B1", "S1"))
    idx.put(QuoteEntry("Q2", "GW01", "MSFT", "B2", "S2"))
    idx.put(QuoteEntry("Q3", "GW02", "AAPL", "B3", "S3"))

    removed = idx.cancel_all_for_gateway("GW01")
    assert len(removed) == 2
    assert idx.active_count() == 1


def test_mmp_state_records_and_activates() -> None:
    obligation = MarketMakerObligation(
        gateway_id="GW01",
        symbol="AAPL",
        mmp_fill_count=2,
        mmp_window_ns=100,
        max_requote_delay_ns=50,
    )
    state = MMPState(gateway_id="GW01", symbol="AAPL")

    assert state.record_fill(obligation, now=1000) is False
    assert state.record_fill(obligation, now=1050) is True

    state.activate_mmp(obligation, now=1100)
    assert state.mmp_active is True
    assert state.requote_deadline == 1150

    state.reset_mmp()
    assert state.mmp_active is False
    assert state.requote_deadline is None

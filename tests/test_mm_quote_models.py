from __future__ import annotations

from edumatcher.models.mm_obligation import MMPState, MarketMakerObligation
from edumatcher.models.quote import (
    QuoteEntry,
    QuoteHistoryEntry,
    QuoteIndex,
    QuoteLegSnapshot,
)


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


def test_quote_index_cancel_for_symbol_and_has_symbol() -> None:
    idx = QuoteIndex()
    idx.put(QuoteEntry("Q1", "GW01", "AAPL", "B1", "S1"))
    idx.put(QuoteEntry("Q2", "GW02", "AAPL", "B2", "S2"))
    idx.put(QuoteEntry("Q3", "GW01", "MSFT", "B3", "S3"))

    assert idx.has_symbol("AAPL") is True
    removed = idx.cancel_all_for_symbol("AAPL")
    assert len(removed) == 2
    assert idx.has_symbol("AAPL") is False
    assert idx.active_count() == 1


def test_remove_records_history_with_reason() -> None:
    idx = QuoteIndex()
    idx.put(QuoteEntry("Q1", "GW01", "AAPL", "B1", "S1"))

    removed = idx.remove("GW01", "AAPL", reason="Cancelled by participant")
    assert removed is not None
    assert removed.quote_id == "Q1"

    recent = idx.recent_for_gateway("GW01")
    assert len(recent) == 1
    assert isinstance(recent[0], QuoteHistoryEntry)
    assert recent[0].entry.quote_id == "Q1"
    assert recent[0].reason == "Cancelled by participant"
    assert recent[0].removed_at_ns > 0


def test_remove_missing_entry_records_no_history() -> None:
    idx = QuoteIndex()
    removed = idx.remove("GW01", "AAPL", reason="Kill switch")
    assert removed is None
    assert idx.recent_for_gateway("GW01") == []


def test_cancel_all_for_gateway_records_history_for_each_entry() -> None:
    idx = QuoteIndex()
    idx.put(QuoteEntry("Q1", "GW01", "AAPL", "B1", "S1"))
    idx.put(QuoteEntry("Q2", "GW01", "MSFT", "B2", "S2"))

    idx.cancel_all_for_gateway("GW01", reason="Gateway disconnected")

    recent = idx.recent_for_gateway("GW01")
    assert len(recent) == 2
    assert {h.entry.quote_id for h in recent} == {"Q1", "Q2"}
    assert all(h.reason == "Gateway disconnected" for h in recent)


def test_cancel_all_for_symbol_records_history_for_each_entry() -> None:
    idx = QuoteIndex()
    idx.put(QuoteEntry("Q1", "GW01", "AAPL", "B1", "S1"))
    idx.put(QuoteEntry("Q2", "GW02", "AAPL", "B2", "S2"))

    idx.cancel_all_for_symbol("AAPL", reason="Circuit breaker halt")

    assert len(idx.recent_for_gateway("GW01")) == 1
    assert len(idx.recent_for_gateway("GW02")) == 1


def test_recent_for_gateway_filters_by_symbol() -> None:
    idx = QuoteIndex()
    idx.put(QuoteEntry("Q1", "GW01", "AAPL", "B1", "S1"))
    idx.put(QuoteEntry("Q2", "GW01", "MSFT", "B2", "S2"))
    idx.cancel_all_for_gateway("GW01", reason="Kill switch")

    aapl_only = idx.recent_for_gateway("GW01", "AAPL")
    assert len(aapl_only) == 1
    assert aapl_only[0].entry.symbol == "AAPL"


def test_recent_for_gateway_most_recent_first() -> None:
    idx = QuoteIndex()
    idx.put(QuoteEntry("Q1", "GW01", "AAPL", "B1", "S1"))
    idx.remove("GW01", "AAPL", reason="first")
    idx.put(QuoteEntry("Q2", "GW01", "AAPL", "B3", "S3"))
    idx.remove("GW01", "AAPL", reason="second")

    recent = idx.recent_for_gateway("GW01")
    assert [h.reason for h in recent] == ["second", "first"]


def test_recent_for_gateway_unknown_gateway_returns_empty() -> None:
    idx = QuoteIndex()
    assert idx.recent_for_gateway("NOPE") == []


def test_history_is_bounded_by_maxlen() -> None:
    idx = QuoteIndex(history_maxlen=2)
    for i in range(5):
        idx.put(QuoteEntry(f"Q{i}", "GW01", "AAPL", f"B{i}", f"S{i}"))
        idx.remove("GW01", "AAPL", reason=f"reason-{i}")

    recent = idx.recent_for_gateway("GW01")
    assert len(recent) == 2
    # Oldest entries were evicted; only the last two removals remain,
    # most-recent first.
    assert [h.reason for h in recent] == ["reason-4", "reason-3"]


def test_remove_default_reason_is_empty_string() -> None:
    idx = QuoteIndex()
    idx.put(QuoteEntry("Q1", "GW01", "AAPL", "B1", "S1"))
    idx.remove("GW01", "AAPL")

    recent = idx.recent_for_gateway("GW01")
    assert recent[0].reason == ""


def test_recent_history_defaults_to_no_leg_snapshots() -> None:
    idx = QuoteIndex()
    idx.put(QuoteEntry("Q1", "GW01", "AAPL", "B1", "S1"))
    idx.remove("GW01", "AAPL", reason="Cancelled by participant")

    recent = idx.recent_for_gateway("GW01")
    assert recent[0].bid_leg is None
    assert recent[0].ask_leg is None


def test_attach_leg_snapshots_enriches_existing_history_entry() -> None:
    idx = QuoteIndex()
    idx.put(QuoteEntry("Q1", "GW01", "AAPL", "B1", "S1"))
    idx.remove("GW01", "AAPL", reason="Cancelled by participant")

    bid_leg = QuoteLegSnapshot(
        order_id="B1", qty=500, remaining=500, filled=0, status="CANCELLED"
    )
    ask_leg = QuoteLegSnapshot(
        order_id="S1", qty=500, remaining=200, filled=300, status="CANCELLED"
    )
    attached = idx.attach_leg_snapshots("GW01", "Q1", bid_leg, ask_leg)
    assert attached is True

    recent = idx.recent_for_gateway("GW01")
    assert recent[0].bid_leg == bid_leg
    assert recent[0].ask_leg == ask_leg
    # Other fields on the entry are preserved, not clobbered.
    assert recent[0].reason == "Cancelled by participant"
    assert recent[0].entry.quote_id == "Q1"


def test_attach_leg_snapshots_unknown_gateway_returns_false() -> None:
    idx = QuoteIndex()
    leg = QuoteLegSnapshot(
        order_id="B1", qty=100, remaining=0, filled=100, status="FILLED"
    )
    assert idx.attach_leg_snapshots("NOPE", "Q1", leg, None) is False


def test_attach_leg_snapshots_unknown_quote_id_returns_false() -> None:
    idx = QuoteIndex()
    idx.put(QuoteEntry("Q1", "GW01", "AAPL", "B1", "S1"))
    idx.remove("GW01", "AAPL", reason="Cancelled by participant")

    leg = QuoteLegSnapshot(
        order_id="B1", qty=100, remaining=0, filled=100, status="FILLED"
    )
    assert idx.attach_leg_snapshots("GW01", "Q_NOT_THERE", leg, None) is False


def test_attach_leg_snapshots_targets_most_recent_matching_quote_id() -> None:
    """If a gateway requoted the same quote_id twice (unusual but not
    forbidden), attach_leg_snapshots must patch the most-recently-recorded
    matching entry, not an older one further back in the history.
    """
    idx = QuoteIndex()
    idx.put(QuoteEntry("Q1", "GW01", "AAPL", "B1", "S1"))
    idx.remove("GW01", "AAPL", reason="first removal")
    idx.put(QuoteEntry("Q1", "GW01", "AAPL", "B2", "S2"))
    idx.remove("GW01", "AAPL", reason="second removal")

    leg = QuoteLegSnapshot(
        order_id="B2", qty=100, remaining=0, filled=100, status="FILLED"
    )
    idx.attach_leg_snapshots("GW01", "Q1", leg, None)

    recent = idx.recent_for_gateway("GW01")
    assert recent[0].reason == "second removal"
    assert recent[0].bid_leg == leg
    assert recent[1].reason == "first removal"
    assert recent[1].bid_leg is None


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

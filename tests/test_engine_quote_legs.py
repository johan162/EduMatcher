"""
Tests for:

- `Engine._handle_quote_legs_request` (`system.quote_legs_request` ->
  `system.quote_legs.{GW_ID}`) — previously had no dispatch handler at all,
  so the request was silently dropped and callers only ever timed out.
- `Engine._dispatch_pull_message`'s fallback branch for topics that match no
  registered handler — previously such a topic just fell off the end of the
  if/elif chain with no log line and no counter increment.

See docs/user-guide/270-messages.md (`system.quote_legs_request` /
`system.quote_legs.{GW_ID}`) for the documented contract these tests pin
down.
"""

from __future__ import annotations

from tests.engine_harness import SYMBOL, connect, make_engine, msgs, submit_quote


def test_quote_legs_request_active_returns_both_legs(monkeypatch, tmp_path):
    engine, pub_sock = make_engine(monkeypatch, tmp_path, mm_gateways=("GW01",))
    connect(engine, "GW01")
    submit_quote(engine, "GW01", bid_price=100.0, ask_price=101.0, quote_id="Q1")
    pub_sock.sent.clear()

    engine._handle_quote_legs_request(
        {"gateway_id": "GW01", "symbol": "", "show": "ACTIVE"}
    )

    replies = msgs(pub_sock, "system.quote_legs.GW01")
    assert len(replies) == 1
    payload = replies[0]
    assert payload["show_requested"] == "ACTIVE"
    assert payload["complete"] is True

    legs = payload["legs"]
    assert len(legs) == 2
    assert {leg["leg_side"] for leg in legs} == {"BUY", "SELL"}
    for leg in legs:
        assert leg["quote_id"] == "Q1"
        assert leg["symbol"] == SYMBOL
        assert leg["order_id"]
        assert leg["qty"] > 0
        assert leg["remaining"] >= 0
        assert leg["filled"] >= 0
        assert leg["status"]
        assert leg["quote_status"] == "ACTIVE"


def test_quote_legs_request_all_still_returns_active_legs_but_flags_incomplete(
    monkeypatch, tmp_path
):
    """pm-mm-bot's real callers always send show="ALL" (never "ACTIVE") — the
    engine only tracks currently-active quote legs (no retained history), so
    it must still reply with what it has instead of dropping the request,
    while being honest that "ALL" wasn't fully honored.
    """
    engine, pub_sock = make_engine(monkeypatch, tmp_path, mm_gateways=("GW01",))
    connect(engine, "GW01")
    submit_quote(engine, "GW01", bid_price=100.0, ask_price=101.0, quote_id="Q1")
    pub_sock.sent.clear()

    engine._handle_quote_legs_request(
        {"gateway_id": "GW01", "symbol": "", "show": "ALL"}
    )

    payload = msgs(pub_sock, "system.quote_legs.GW01")[0]
    assert payload["show_requested"] == "ALL"
    assert payload["complete"] is False
    assert len(payload["legs"]) == 2  # active legs, not an empty/dropped reply


def test_quote_legs_request_no_active_quote_returns_empty_not_dropped(
    monkeypatch, tmp_path
):
    engine, pub_sock = make_engine(monkeypatch, tmp_path, mm_gateways=("GW01",))
    connect(engine, "GW01")
    pub_sock.sent.clear()

    engine._handle_quote_legs_request(
        {"gateway_id": "GW01", "symbol": "", "show": "ACTIVE"}
    )

    replies = msgs(pub_sock, "system.quote_legs.GW01")
    assert len(replies) == 1
    assert replies[0]["legs"] == []
    assert replies[0]["complete"] is True


def test_quote_legs_request_unconnected_gateway_returns_empty_not_dropped(
    monkeypatch, tmp_path
):
    engine, pub_sock = make_engine(monkeypatch, tmp_path, mm_gateways=("GW01",))
    # Deliberately skip connect(engine, "GW01").
    engine._handle_quote_legs_request(
        {"gateway_id": "GW01", "symbol": "", "show": "ACTIVE"}
    )

    replies = msgs(pub_sock, "system.quote_legs.GW01")
    assert len(replies) == 1
    assert replies[0]["legs"] == []


def test_quote_legs_request_symbol_filter(monkeypatch, tmp_path):
    engine, pub_sock = make_engine(
        monkeypatch, tmp_path, symbols=("AAPL", "MSFT"), mm_gateways=("GW01",)
    )
    connect(engine, "GW01")
    submit_quote(
        engine, "GW01", bid_price=100.0, ask_price=101.0, quote_id="Q1", symbol="AAPL"
    )
    submit_quote(
        engine, "GW01", bid_price=200.0, ask_price=201.0, quote_id="Q2", symbol="MSFT"
    )
    pub_sock.sent.clear()

    engine._handle_quote_legs_request(
        {"gateway_id": "GW01", "symbol": "AAPL", "show": "ACTIVE"}
    )

    payload = msgs(pub_sock, "system.quote_legs.GW01")[0]
    assert {leg["symbol"] for leg in payload["legs"]} == {"AAPL"}


def test_dispatch_pull_message_unknown_topic_is_logged_not_dropped(
    monkeypatch, tmp_path, caplog
):
    """An unregistered topic must never vanish silently: it's logged at
    WARNING (visible by default) and counted, instead of the if/elif chain
    just falling through with no trace at all.
    """
    engine, _pub_sock = make_engine(monkeypatch, tmp_path)
    assert engine._unknown_topic_count == 0

    with caplog.at_level("WARNING"):
        engine._dispatch_pull_message("system.totally_made_up_topic", {"foo": "bar"})

    assert engine._unknown_topic_count == 1
    assert "system.totally_made_up_topic" in caplog.text

    # A second unknown topic keeps counting rather than resetting or raising.
    engine._dispatch_pull_message("another.bogus.topic", {})
    assert engine._unknown_topic_count == 2


def test_dispatch_pull_message_known_topic_still_dispatches(monkeypatch, tmp_path):
    """Sanity check that extracting the if/elif chain out of run() into
    _dispatch_pull_message() didn't change behavior for a known topic.
    """
    engine, pub_sock = make_engine(monkeypatch, tmp_path, mm_gateways=("GW01",))
    connect(engine, "GW01")
    pub_sock.sent.clear()

    engine._dispatch_pull_message(
        "system.quote_bootstrap_request", {"gateway_id": "GW01", "symbol": ""}
    )

    assert msgs(pub_sock, "system.quote_bootstrap.GW01")


def test_dispatch_pull_message_handler_exception_still_counted_as_error_not_unknown(
    monkeypatch, tmp_path
):
    """A *registered* handler that raises should keep incrementing the
    existing `_error_count` path, not the new `_unknown_topic_count` path —
    the two failure modes (no handler vs. handler raised) must stay distinct.
    """
    engine, _pub_sock = make_engine(monkeypatch, tmp_path)
    assert engine._error_count == 0
    assert engine._unknown_topic_count == 0

    # order.new with a payload missing required fields raises inside the
    # handler rather than being validated away, which is enough to exercise
    # the except branch without needing a purpose-built broken handler.
    engine._dispatch_pull_message("order.new", {})

    assert engine._error_count == 1
    assert engine._unknown_topic_count == 0

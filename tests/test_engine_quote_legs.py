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

from edumatcher.models.order import OrderType, Side, TIF
from tests.engine_harness import (
    SYMBOL,
    connect,
    make_engine,
    msgs,
    order_payload,
    submit_quote,
)


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
    assert payload["recent"] == []

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


def test_quote_legs_request_all_returns_active_legs_and_is_complete(
    monkeypatch, tmp_path
):
    """pm-mm-bot's real callers always send show="ALL" (never "ACTIVE").
    ALL now returns both the active legs and the (possibly empty) recent
    history, and is honestly marked complete=True.
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
    assert payload["complete"] is True
    assert len(payload["legs"]) == 2  # active legs, not an empty/dropped reply
    assert payload["recent"] == []  # nothing inactivated yet


def test_quote_legs_request_recent_returns_cancelled_quote_history(
    monkeypatch, tmp_path
):
    """After a quote is cancelled, SHOW=RECENT must report it — this is the
    core RECENT/ALL fix: history that used to be silently dropped.
    """
    engine, pub_sock = make_engine(monkeypatch, tmp_path, mm_gateways=("GW01",))
    connect(engine, "GW01")
    submit_quote(engine, "GW01", bid_price=100.0, ask_price=101.0, quote_id="Q1")
    pub_sock.sent.clear()

    engine._handle_quote_cancel({"gateway_id": "GW01", "symbol": SYMBOL})
    pub_sock.sent.clear()

    engine._handle_quote_legs_request(
        {"gateway_id": "GW01", "symbol": "", "show": "RECENT"}
    )

    payload = msgs(pub_sock, "system.quote_legs.GW01")[0]
    assert payload["show_requested"] == "RECENT"
    assert payload["complete"] is True
    assert payload["legs"] == []  # RECENT alone does not include active legs

    recent = payload["recent"]
    assert len(recent) == 1
    assert recent[0]["quote_id"] == "Q1"
    assert recent[0]["symbol"] == SYMBOL
    assert recent[0]["reason"] == "Cancelled by participant"
    assert recent[0]["quote_status"] == "CANCELLED"
    assert recent[0]["removed_at_ns"] > 0


def test_quote_legs_request_recent_includes_per_leg_snapshot_on_cancel(
    monkeypatch, tmp_path
):
    """RECENT rows carry real per-leg detail (qty/remaining/filled/status),
    not just the quote-level summary — this is the widened design from
    docs-design/EduMatcher-QLEGS-RECENT.md.
    """
    engine, pub_sock = make_engine(monkeypatch, tmp_path, mm_gateways=("GW01",))
    connect(engine, "GW01")
    submit_quote(
        engine,
        "GW01",
        bid_price=100.0,
        ask_price=101.0,
        bid_qty=500,
        ask_qty=500,
        quote_id="Q1",
    )
    pub_sock.sent.clear()

    engine._handle_quote_cancel({"gateway_id": "GW01", "symbol": SYMBOL})
    pub_sock.sent.clear()

    engine._handle_quote_legs_request(
        {"gateway_id": "GW01", "symbol": "", "show": "RECENT"}
    )

    payload = msgs(pub_sock, "system.quote_legs.GW01")[0]
    recent = payload["recent"][0]

    for leg_key in ("bid_leg", "ask_leg"):
        leg = recent[leg_key]
        assert leg is not None
        assert leg["order_id"]
        assert leg["qty"] == 500
        assert leg["remaining"] == 500  # never filled — cancelled while fully resting
        assert leg["filled"] == 0
        assert leg["status"] == "CANCELLED"
    assert recent["bid_leg"]["order_id"] != recent["ask_leg"]["order_id"]


def test_quote_legs_request_recent_fill_driven_leg_snapshot_reflects_fill(
    monkeypatch, tmp_path
):
    """For a fill-driven inactivation, the filled leg's snapshot reports its
    actual fill quantity/remaining/status, and the sibling leg (cancelled as
    a side effect) reports its own cancelled-while-resting state.
    """
    engine, pub_sock = make_engine(
        monkeypatch,
        tmp_path,
        gateways=("GW01", "TAKER"),
        mm_gateways=("GW01",),
    )
    connect(engine, "GW01", "TAKER")
    submit_quote(
        engine,
        "GW01",
        bid_price=100.0,
        ask_price=101.0,
        bid_qty=500,
        ask_qty=500,
        quote_id="Q1",
    )

    # Partial fill: taker only takes 100 of the 500 resting on the ask.
    engine._handle_new_order(
        order_payload(
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            qty=100,
            gateway_id="TAKER",
            price=101.0,
            tif=TIF.DAY,
        )
    )
    pub_sock.sent.clear()

    engine._handle_quote_legs_request(
        {"gateway_id": "GW01", "symbol": "", "show": "RECENT"}
    )

    payload = msgs(pub_sock, "system.quote_legs.GW01")[0]
    recent = payload["recent"][0]
    assert recent["reason"] == "INACTIVE_ASK_FILLED"

    ask_leg = recent["ask_leg"]
    assert ask_leg is not None
    assert ask_leg["qty"] == 500
    assert ask_leg["filled"] == 100
    assert ask_leg["remaining"] == 400
    assert ask_leg["status"] == "PARTIAL"

    bid_leg = recent["bid_leg"]
    assert bid_leg is not None
    assert bid_leg["qty"] == 500
    assert bid_leg["filled"] == 0
    assert bid_leg["remaining"] == 500
    assert bid_leg["status"] == "CANCELLED"


def test_quote_legs_request_all_includes_both_active_and_recent(monkeypatch, tmp_path):
    """ALL after a cancel+new-quote cycle returns the new active quote's legs
    plus the old quote's history — both halves of "ALL" are now real.
    """
    engine, pub_sock = make_engine(
        monkeypatch, tmp_path, symbols=("AAPL", "MSFT"), mm_gateways=("GW01",)
    )
    connect(engine, "GW01")
    submit_quote(
        engine, "GW01", bid_price=100.0, ask_price=101.0, quote_id="Q1", symbol="AAPL"
    )
    engine._handle_quote_cancel({"gateway_id": "GW01", "symbol": "AAPL"})
    submit_quote(
        engine, "GW01", bid_price=200.0, ask_price=201.0, quote_id="Q2", symbol="MSFT"
    )
    pub_sock.sent.clear()

    engine._handle_quote_legs_request(
        {"gateway_id": "GW01", "symbol": "", "show": "ALL"}
    )

    payload = msgs(pub_sock, "system.quote_legs.GW01")[0]
    assert payload["complete"] is True
    assert len(payload["legs"]) == 2
    assert {leg["symbol"] for leg in payload["legs"]} == {"MSFT"}
    assert len(payload["recent"]) == 1
    assert payload["recent"][0]["quote_id"] == "Q1"


def test_quote_legs_request_recent_symbol_filter(monkeypatch, tmp_path):
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
    engine._handle_quote_cancel({"gateway_id": "GW01", "symbol": "AAPL"})
    engine._handle_quote_cancel({"gateway_id": "GW01", "symbol": "MSFT"})
    pub_sock.sent.clear()

    engine._handle_quote_legs_request(
        {"gateway_id": "GW01", "symbol": "AAPL", "show": "RECENT"}
    )

    payload = msgs(pub_sock, "system.quote_legs.GW01")[0]
    recent = payload["recent"]
    assert len(recent) == 1
    assert recent[0]["quote_id"] == "Q1"
    assert recent[0]["symbol"] == "AAPL"


def test_quote_legs_request_recent_reflects_fill_driven_inactivation(
    monkeypatch, tmp_path
):
    """A quote inactivated by a leg fill (not an explicit cancel) also lands
    in RECENT, with the INACTIVE_*_FILLED status as its reason.
    """
    engine, pub_sock = make_engine(
        monkeypatch,
        tmp_path,
        gateways=("GW01", "TAKER"),
        mm_gateways=("GW01",),
    )
    connect(engine, "GW01", "TAKER")
    submit_quote(engine, "GW01", bid_price=100.0, ask_price=101.0, quote_id="Q1")

    # A marketable BUY at the quote's ask price fills the ask leg, which
    # (with the default INACTIVATE_ON_ANY_FILL policy) inactivates the
    # whole quote and cancels the sibling bid leg.
    engine._handle_new_order(
        order_payload(
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            qty=100,
            gateway_id="TAKER",
            price=101.0,
            tif=TIF.DAY,
        )
    )
    pub_sock.sent.clear()

    engine._handle_quote_legs_request(
        {"gateway_id": "GW01", "symbol": "", "show": "RECENT"}
    )

    payload = msgs(pub_sock, "system.quote_legs.GW01")[0]
    recent = payload["recent"]
    assert len(recent) == 1
    assert recent[0]["quote_id"] == "Q1"
    assert recent[0]["reason"] == "INACTIVE_ASK_FILLED"


def test_quote_legs_request_unconnected_gateway_recent_returns_empty_complete(
    monkeypatch, tmp_path
):
    engine, pub_sock = make_engine(monkeypatch, tmp_path, mm_gateways=("GW01",))
    # Deliberately skip connect(engine, "GW01").
    engine._handle_quote_legs_request(
        {"gateway_id": "GW01", "symbol": "", "show": "RECENT"}
    )

    replies = msgs(pub_sock, "system.quote_legs.GW01")
    assert len(replies) == 1
    assert replies[0]["legs"] == []
    assert replies[0]["recent"] == []
    assert replies[0]["complete"] is True


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

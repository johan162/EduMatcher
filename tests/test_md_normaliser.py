from __future__ import annotations

from edumatcher.md_gateway.normaliser import EngineNormaliser


def test_normalise_book_emits_change_fields() -> None:
    n = EngineNormaliser()
    payload = {
        "bids": [{"price": 150.1, "qty": 100}],
        "asks": [{"price": 150.2, "qty": 90}],
        "last_price": 150.15,
        "last_qty": 10,
    }
    fields = n.normalise_book("AAPL", payload)
    assert fields is not None
    assert fields["BID"] == "150.1"
    assert fields["ASK"] == "150.2"


def test_normalise_book_none_when_unchanged() -> None:
    n = EngineNormaliser()
    payload = {
        "bids": [{"price": 150.1, "qty": 100}],
        "asks": [{"price": 150.2, "qty": 90}],
    }
    assert n.normalise_book("AAPL", payload) is not None
    assert n.normalise_book("AAPL", payload) is None


def test_normalise_book_marks_a_withdrawn_bid_side_explicitly() -> None:
    """An emptied side must be announced, not merely left unmentioned.

    Omitting ``BID`` means "unchanged" to a client merging deltas, so before
    this was fixed a lifted bid left the stale price on screen forever while a
    reconnecting client's fresh SNAP correctly showed none.
    """
    n = EngineNormaliser()
    n.normalise_book(
        "AAPL",
        {
            "bids": [{"price": 150.1, "qty": 100}],
            "asks": [{"price": 150.2, "qty": 90}],
        },
    )

    fields = n.normalise_book(
        "AAPL", {"bids": [], "asks": [{"price": 150.2, "qty": 90}]}
    )

    assert fields is not None
    assert fields["BID"] == ""
    assert fields["BIDSZ"] == "0"
    assert "ASK" not in fields, "the untouched side should stay silent"


def test_normalise_book_withdrawal_agrees_with_a_fresh_snapshot() -> None:
    """A merged delta stream and a fresh SNAP must describe the same book."""
    n = EngineNormaliser()
    n.normalise_book("AAPL", {"bids": [{"price": 150.1, "qty": 100}], "asks": []})
    n.normalise_book("AAPL", {"bids": [], "asks": []})

    assert "BID" not in n.top_snapshot_fields("AAPL")


def test_normalise_book_marks_a_withdrawn_ask_side_explicitly() -> None:
    n = EngineNormaliser()
    n.normalise_book(
        "AAPL",
        {
            "bids": [{"price": 150.1, "qty": 100}],
            "asks": [{"price": 150.2, "qty": 90}],
        },
    )

    fields = n.normalise_book(
        "AAPL", {"bids": [{"price": 150.1, "qty": 100}], "asks": []}
    )

    assert fields is not None
    assert fields["ASK"] == ""
    assert fields["ASKSZ"] == "0"
    assert "BID" not in fields


def test_normalise_book_does_not_re_announce_an_already_empty_side() -> None:
    """Withdrawal is an edge, not a state — repeating it would be noise."""
    n = EngineNormaliser()
    n.normalise_book("AAPL", {"bids": [{"price": 150.1, "qty": 100}], "asks": []})
    assert n.normalise_book("AAPL", {"bids": [], "asks": []}) is not None
    assert n.normalise_book("AAPL", {"bids": [], "asks": []}) is None


def test_normalise_book_readmits_a_side_after_withdrawal() -> None:
    n = EngineNormaliser()
    n.normalise_book("AAPL", {"bids": [{"price": 150.1, "qty": 100}], "asks": []})
    n.normalise_book("AAPL", {"bids": [], "asks": []})

    fields = n.normalise_book(
        "AAPL", {"bids": [{"price": 149.9, "qty": 50}], "asks": []}
    )

    assert fields is not None
    assert fields["BID"] == "149.9"
    assert fields["BIDSZ"] == "50"


def _book(
    bid: float = 150.1,
    ask: float = 150.2,
    last: float | None = None,
    last_qty: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "bids": [{"price": bid, "qty": 100}],
        "asks": [{"price": ask, "qty": 90}],
    }
    if last is not None:
        payload["last_price"] = last
        payload["last_qty"] = last_qty if last_qty is not None else 10
    return payload


def test_md_carries_the_new_last_after_a_trade() -> None:
    """A trade must reach TOP subscribers, not just the TRADE channel.

    The gateway keeps its current top-of-book in step with trades so a SNAP is
    immediately right. That must not also mark the price as already sent: doing
    so suppressed LAST from the next MD, leaving a continuously-connected
    client on its original SNAP price forever.
    """
    n = EngineNormaliser()
    n.normalise_book("AAPL", _book(last=150.11))
    n.normalise_trade(
        {"symbol": "AAPL", "price": 151.5, "quantity": 25, "aggressor_side": "BUY"}
    )

    fields = n.normalise_book("AAPL", _book(last=151.5, last_qty=25))

    assert fields is not None, "the book republish after a trade must produce an MD"
    assert fields["LAST"] == "151.5"
    assert fields["LASTSZ"] == "25"


def test_streamed_and_reconnected_clients_agree_on_last() -> None:
    """The divergence this guards against: same feed, two different prices."""
    n = EngineNormaliser()
    n.normalise_book("AAPL", _book(last=150.11))
    n.normalise_trade(
        {"symbol": "AAPL", "price": 151.5, "quantity": 25, "aggressor_side": "BUY"}
    )
    delta = n.normalise_book("AAPL", _book(last=151.5, last_qty=25))

    # What a client merging deltas ends up with, versus what a fresh
    # subscriber is handed in its SNAP.
    assert delta is not None
    assert delta["LAST"] == n.top_snapshot_fields("AAPL")["LAST"]


def test_snapshot_reports_a_trade_before_the_next_book_republish() -> None:
    """Book snapshots are throttled, so the SNAP path cannot wait for one."""
    n = EngineNormaliser()
    n.normalise_book("AAPL", _book(last=150.11))
    n.normalise_trade(
        {"symbol": "AAPL", "price": 151.5, "quantity": 25, "aggressor_side": "BUY"}
    )

    assert n.top_snapshot_fields("AAPL")["LAST"] == "151.5"


def test_last_is_not_re_sent_once_delivered() -> None:
    """Fixing the suppression must not turn into re-sending an unchanged field."""
    n = EngineNormaliser()
    n.normalise_book("AAPL", _book(last=150.11))
    n.normalise_trade(
        {"symbol": "AAPL", "price": 151.5, "quantity": 25, "aggressor_side": "BUY"}
    )
    n.normalise_book("AAPL", _book(last=151.5, last_qty=25))

    assert n.normalise_book("AAPL", _book(last=151.5, last_qty=25)) is None


def test_a_book_change_still_reports_only_what_moved() -> None:
    n = EngineNormaliser()
    n.normalise_book("AAPL", _book(bid=150.1, ask=150.2, last=150.11))

    fields = n.normalise_book("AAPL", _book(bid=150.15, ask=150.2, last=150.11))

    assert fields is not None
    assert fields["BID"] == "150.15"
    assert "ASK" not in fields
    assert "LAST" not in fields


def test_several_trades_between_republishes_report_the_latest() -> None:
    """Book publishes are throttled; TRADE carries every print, TOP the latest."""
    n = EngineNormaliser()
    n.normalise_book("AAPL", _book(last=150.11))
    for px in (151.0, 151.25, 151.5):
        n.normalise_trade(
            {"symbol": "AAPL", "price": px, "quantity": 5, "aggressor_side": "BUY"}
        )

    fields = n.normalise_book("AAPL", _book(last=151.5, last_qty=5))

    assert fields is not None
    assert fields["LAST"] == "151.5"


def test_trade_updates_last_cache() -> None:
    n = EngineNormaliser()
    sym, fields = n.normalise_trade(
        {
            "symbol": "AAPL",
            "price": 151.0,
            "quantity": 25,
            "aggressor_side": "BUY",
        }
    )
    assert sym == "AAPL"
    assert fields["PX"] == "151.0"
    snap = n.top_snapshot_fields("AAPL")
    assert snap["LAST"] == "151.0"
    assert snap["LASTSZ"] == "25"


def test_state_snapshots() -> None:
    n = EngineNormaliser()
    sym, fields = n.normalise_session_state(
        {"state": "PRE_OPEN", "prev_state": "CLOSED"}
    )
    assert sym == "*"
    assert fields["SESSION"] == "PRE_OPEN"
    halt_sym, halt_fields = n.normalise_halt("AAPL")
    assert halt_sym == "AAPL"
    assert halt_fields["SESSION"] == "HALTED"


# ---------------------------------------------------------------------------
# AUCTION channel
# ---------------------------------------------------------------------------


def test_normalise_auction_result_full_cross() -> None:
    n = EngineNormaliser()
    sym, fields = n.normalise_auction_result(
        {
            "symbol": "AAPL",
            "eq_price": 150.10,
            "eq_qty": 48200,
            "trades_count": 37,
            "imbalance_side": "BUY",
            "imbalance_qty": 1400,
        }
    )
    assert sym == "AAPL"
    assert fields["EQPX"] == "150.1"
    assert fields["EQQTY"] == "48200"
    assert fields["TRADES"] == "37"
    assert fields["IMBSIDE"] == "BUY"
    assert fields["IMBQTY"] == "1400"


def test_normalise_auction_result_no_cross_omits_eqpx_and_imbside() -> None:
    n = EngineNormaliser()
    sym, fields = n.normalise_auction_result(
        {
            "symbol": "TSLA",
            "eq_price": None,
            "eq_qty": 0,
            "trades_count": 0,
            "imbalance_side": "",
            "imbalance_qty": 0,
        }
    )
    assert sym == "TSLA"
    assert "EQPX" not in fields
    assert "IMBSIDE" not in fields
    assert fields["EQQTY"] == "0"
    assert fields["TRADES"] == "0"
    assert fields["IMBQTY"] == "0"


def test_normalise_auction_result_balanced_cross_omits_imbside_only() -> None:
    n = EngineNormaliser()
    sym, fields = n.normalise_auction_result(
        {
            "symbol": "MSFT",
            "eq_price": 421.00,
            "eq_qty": 15000,
            "trades_count": 12,
            "imbalance_side": "",
            "imbalance_qty": 0,
        }
    )
    assert sym == "MSFT"
    assert fields["EQPX"] == "421.0"
    assert "IMBSIDE" not in fields
    assert fields["IMBQTY"] == "0"


def test_normalise_auction_result_eq_price_zero_is_kept() -> None:
    """A legitimate eq_price of 0.0 must not be dropped like a missing value."""
    n = EngineNormaliser()
    _, fields = n.normalise_auction_result(
        {
            "symbol": "PENNY",
            "eq_price": 0.0,
            "eq_qty": 100,
            "trades_count": 1,
            "imbalance_side": "",
            "imbalance_qty": 0,
        }
    )
    assert fields["EQPX"] == "0.0"


# ---------------------------------------------------------------------------
# CB channel
# ---------------------------------------------------------------------------


def test_normalise_cb_halt_automatic_trigger() -> None:
    n = EngineNormaliser()
    sym, fields = n.normalise_cb_halt(
        "AAPL",
        {
            "symbol": "AAPL",
            "trigger_price": 148.20,
            "reference_price": 150.10,
            "resume_at_ns": 1_784_560_800_000_000_000,
            "halt_source": "CB",
            "level": "L2",
        },
    )
    assert sym == "AAPL"
    assert fields["STATUS"] == "HALTED"
    assert fields["LEVEL"] == "L2"
    assert fields["TRIGGERPX"] == "148.2"
    assert fields["REFPX"] == "150.1"
    assert fields["SRC"] == "CB"
    # RESUMEAT is ISO-8601 text, matching every other CALF timestamp field,
    # not a raw nanosecond integer.
    assert fields["RESUMEAT"] == "2026-07-20T15:20:00.000Z"


def test_normalise_cb_halt_admin_all_omits_price_and_resume_fields() -> None:
    n = EngineNormaliser()
    _, fields = n.normalise_cb_halt(
        "TSLA",
        {
            "symbol": "TSLA",
            "trigger_price": None,
            "reference_price": None,
            "resume_at_ns": None,
            "halt_source": "ADMIN",
            "level": "ADMIN_ALL",
        },
    )
    assert fields["STATUS"] == "HALTED"
    assert fields["LEVEL"] == "ADMIN_ALL"
    assert fields["SRC"] == "ADMIN"
    assert "TRIGGERPX" not in fields
    assert "REFPX" not in fields
    assert "RESUMEAT" not in fields


def test_normalise_cb_halt_admin_symbol() -> None:
    n = EngineNormaliser()
    _, fields = n.normalise_cb_halt(
        "MSFT",
        {
            "symbol": "MSFT",
            "trigger_price": None,
            "reference_price": None,
            "resume_at_ns": None,
            "halt_source": "ADMIN",
            "level": "ADMIN_SYMBOL",
        },
    )
    assert fields["LEVEL"] == "ADMIN_SYMBOL"
    assert fields["SRC"] == "ADMIN"


def test_normalise_cb_resume_omits_halt_only_fields() -> None:
    n = EngineNormaliser()
    n.normalise_cb_halt(
        "AAPL",
        {
            "trigger_price": 148.20,
            "reference_price": 150.10,
            "resume_at_ns": 1_784_560_800_000_000_000,
            "halt_source": "CB",
            "level": "L2",
        },
    )
    sym, fields = n.normalise_cb_resume("AAPL", {"halt_source": "CB"})
    assert sym == "AAPL"
    assert fields == {"STATUS": "ACTIVE", "SRC": "CB"}


def test_cb_halt_and_resume_report_the_same_source() -> None:
    """SRC says what put the symbol into the halt, not how it comes out.

    Every halt reopens through an uncross — the halt period is the reopening
    auction's call phase — so there is nothing to vary on the way out. What a
    client does need is whether a breaker or an operator halted the symbol,
    and that must read the same going in and coming out.
    """
    n = EngineNormaliser()
    halt_sym, halt_fields = n.normalise_cb_halt(
        "AAPL", {"halt_source": "ADMIN", "level": "L1"}
    )
    resume_sym, resume_fields = n.normalise_cb_resume("AAPL", {"halt_source": "ADMIN"})
    assert halt_fields["SRC"] == resume_fields["SRC"] == "ADMIN"
    assert halt_sym == resume_sym == "AAPL"


def test_cb_snapshot_fields_defaults_to_active_with_no_history() -> None:
    n = EngineNormaliser()
    fields = n.cb_snapshot_fields("NEWSYM")
    assert fields == {"STATUS": "ACTIVE"}


def test_cb_snapshot_fields_reflects_current_halt() -> None:
    n = EngineNormaliser()
    n.normalise_cb_halt(
        "AAPL",
        {
            "trigger_price": 148.20,
            "reference_price": 150.10,
            "resume_at_ns": 1_784_560_800_000_000_000,
            "halt_source": "CB",
            "level": "L2",
        },
    )
    fields = n.cb_snapshot_fields("AAPL")
    assert fields["STATUS"] == "HALTED"
    assert fields["LEVEL"] == "L2"
    assert fields["TRIGGERPX"] == "148.2"


def test_cb_snapshot_fields_reflects_resume_after_halt() -> None:
    n = EngineNormaliser()
    n.normalise_cb_halt("AAPL", {"halt_source": "CB", "level": "L1"})
    n.normalise_cb_resume("AAPL", {"halt_source": "CB"})
    fields = n.cb_snapshot_fields("AAPL")
    assert fields == {"STATUS": "ACTIVE", "SRC": "CB"}


def test_normalise_cb_halt_symbol_uppercased() -> None:
    n = EngineNormaliser()
    sym, _ = n.normalise_cb_halt("aapl", {"level": "L1"})
    assert sym == "AAPL"


# ---------------------------------------------------------------------------
# Per-symbol session state
#
# A CB halt expires purely on elapsed time — CircuitBreakerState.should_resume
# consults no session at all — so a halt can outlive the phase it started in.
# These pin what a symbol's state says when that happens.
# ---------------------------------------------------------------------------


def test_resume_rejoins_the_current_session_not_continuous() -> None:
    # L2's default halt is 15 minutes; one triggered a few minutes before the
    # close expires after it. Saying CONTINUOUS there tells every client the
    # symbol is trading on a closed exchange.
    n = EngineNormaliser()
    n.normalise_session_state({"state": "CONTINUOUS"})
    n.normalise_halt("AAPL")
    n.normalise_session_state({"state": "CLOSED", "prev_state": "CLOSING_AUCTION"})

    _, fields = n.normalise_resume("AAPL")

    assert fields["SESSION"] == "CLOSED"
    assert fields["PREV"] == "HALTED"


def test_resume_returns_to_trading_when_the_exchange_is_still_open() -> None:
    n = EngineNormaliser()
    n.normalise_session_state({"state": "CONTINUOUS"})
    n.normalise_halt("AAPL")

    _, fields = n.normalise_resume("AAPL")

    assert fields["SESSION"] == "CONTINUOUS"


def test_a_symbol_that_halted_once_still_follows_later_transitions() -> None:
    # symbol_state was written by the halt and then never updated, so every
    # later SNAP reported the session as of that halt for the rest of the day.
    n = EngineNormaliser()
    n.normalise_session_state({"state": "CONTINUOUS"})
    n.normalise_halt("AAPL")
    n.normalise_resume("AAPL")

    n.normalise_session_state({"state": "CLOSING_AUCTION"})
    n.apply_session_to_symbols({"AAPL"})

    assert n.state_snapshot_fields("AAPL") == {"SESSION": "CLOSING_AUCTION"}


def test_transition_reports_each_symbols_previous_state() -> None:
    n = EngineNormaliser()
    n.normalise_session_state({"state": "CONTINUOUS"})
    n.apply_session_to_symbols({"AAPL", "MSFT"})

    n.normalise_session_state({"state": "CLOSING_AUCTION"})
    updates = dict(n.apply_session_to_symbols({"AAPL", "MSFT"}))

    assert updates["AAPL"] == {"SESSION": "CLOSING_AUCTION", "PREV": "CONTINUOUS"}
    assert updates["MSFT"] == {"SESSION": "CLOSING_AUCTION", "PREV": "CONTINUOUS"}


def test_a_halted_symbol_is_left_halted_across_a_transition() -> None:
    # The halt outlives the phase it began in; the engine publishes an explicit
    # resume when it ends, and that is what should move the symbol on.
    n = EngineNormaliser()
    n.normalise_session_state({"state": "CONTINUOUS"})
    n.normalise_halt("AAPL")

    n.normalise_session_state({"state": "CLOSING_AUCTION"})
    updates = dict(n.apply_session_to_symbols({"AAPL", "MSFT"}))

    assert "AAPL" not in updates
    assert n.state_snapshot_fields("AAPL") == {"SESSION": "HALTED"}


def test_a_transition_emits_nothing_for_symbols_already_in_that_state() -> None:
    n = EngineNormaliser()
    n.normalise_session_state({"state": "CONTINUOUS"})
    n.apply_session_to_symbols({"AAPL"})

    assert n.apply_session_to_symbols({"AAPL"}) == []


# ---------------------------------------------------------------------------
# Auction origin
# ---------------------------------------------------------------------------


def test_auction_carries_the_reason_it_fired() -> None:
    # A reopening uncross and the closing uncross are otherwise identical on
    # the wire, so a client cannot label either one.
    n = EngineNormaliser()
    _, fields = n.normalise_auction_result(
        {"symbol": "AAPL", "eq_price": 149.85, "eq_qty": 12400, "reason": "REOPEN"}
    )
    assert fields["REASON"] == "REOPEN"


def test_auction_omits_reason_when_the_engine_sent_none() -> None:
    n = EngineNormaliser()
    _, fields = n.normalise_auction_result({"symbol": "AAPL", "eq_qty": 0})
    assert "REASON" not in fields


# ---------------------------------------------------------------------------
# ACE corridor expansions
# ---------------------------------------------------------------------------


def _halt(n: EngineNormaliser) -> None:
    n.normalise_cb_halt(
        "AAPL",
        {
            "level": "L1",
            "trigger_price": 122.0,
            "reference_price": 100.0,
            "resume_at_ns": 1_800_000_000_000_000_000,
            "halt_source": "CB",
            "corridor_low": 90.0,
            "corridor_high": 110.0,
            "expansion": 0,
        },
    )


def test_halt_publishes_the_corridor_the_symbol_may_reopen_inside() -> None:
    n = EngineNormaliser()
    _halt(n)
    fields = n.cb_snapshot_fields("AAPL")

    assert fields["CORRLO"] == "90.0"
    assert fields["CORRHI"] == "110.0"
    assert fields["EXP"] == "0"


def test_an_extension_moves_the_resume_time_and_widens_the_corridor() -> None:
    # Without this a client keeps a RESUMEAT that has already passed and
    # reports the symbol as overdue to reopen.
    n = EngineNormaliser()
    _halt(n)
    _, fields = n.normalise_cb_extend(
        "AAPL",
        {
            "indicative_price": 122.0,
            "indicative_qty": 500,
            "imbalance_side": "BUY",
            "resume_at_ns": 1_800_000_120_000_000_000,
            "corridor_low": 80.0,
            "corridor_high": 120.0,
            "expansion": 1,
        },
    )

    assert fields["STATUS"] == "HALTED"
    assert (fields["CORRLO"], fields["CORRHI"], fields["EXP"]) == ("80.0", "120.0", "1")
    assert fields["RESUMEAT"] == "2027-01-15T08:02:00.000Z"
    assert (fields["INDICPX"], fields["INDICQTY"], fields["IMB"]) == (
        "122.0",
        "500",
        "BUY",
    )


def test_an_extension_keeps_the_detail_of_the_halt_it_continues() -> None:
    # An extension is the same halt, not a new one, so the trigger and level
    # must survive it — the engine does not resend them.
    n = EngineNormaliser()
    _halt(n)
    _, fields = n.normalise_cb_extend("AAPL", {"corridor_low": 80.0, "expansion": 1})

    assert fields["LEVEL"] == "L1"
    assert fields["TRIGGERPX"] == "122.0"
    assert fields["REFPX"] == "100.0"


def test_the_snapshot_carries_the_corridor_but_not_a_stale_indicative() -> None:
    # A late subscriber must learn where the symbol may reopen; it must not be
    # told a price computed for a book that has since kept moving.
    n = EngineNormaliser()
    _halt(n)
    n.normalise_cb_extend(
        "AAPL",
        {
            "indicative_price": 122.0,
            "corridor_low": 80.0,
            "corridor_high": 120.0,
            "expansion": 1,
        },
    )
    snap = n.cb_snapshot_fields("AAPL")

    assert snap["CORRHI"] == "120.0"
    assert snap["EXP"] == "1"
    assert "INDICPX" not in snap
    assert "IMB" not in snap


def test_a_backstop_resume_says_the_price_was_imposed() -> None:
    # A clamped print is not a discovered price; a client showing it as one
    # would misrepresent the close.
    n = EngineNormaliser()
    _halt(n)
    _, fields = n.normalise_cb_resume(
        "AAPL",
        {
            "halt_source": "CB",
            "reason": "CLOSING_BACKSTOP",
            "clamped": True,
            "print_price": 120.0,
        },
    )

    assert fields["STATUS"] == "ACTIVE"
    assert fields["REASON"] == "CLOSING_BACKSTOP"
    assert fields["CLAMPED"] == "1"
    assert fields["PRINTPX"] == "120.0"


def test_an_ordinary_resume_carries_no_backstop_fields() -> None:
    n = EngineNormaliser()
    _halt(n)
    _, fields = n.normalise_cb_resume("AAPL", {"halt_source": "CB"})

    assert "REASON" not in fields
    assert "CLAMPED" not in fields
    assert "PRINTPX" not in fields
    # And the corridor is gone with the halt it described.
    assert "CORRLO" not in n.cb_snapshot_fields("AAPL")

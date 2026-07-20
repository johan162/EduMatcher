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
            "resumption_mode": "AUCTION",
            "level": "L2",
        },
    )
    assert sym == "AAPL"
    assert fields["STATUS"] == "HALTED"
    assert fields["LEVEL"] == "L2"
    assert fields["TRIGGERPX"] == "148.2"
    assert fields["REFPX"] == "150.1"
    assert fields["MODE"] == "AUCTION"
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
            "resumption_mode": "MANUAL",
            "level": "ADMIN_ALL",
        },
    )
    assert fields["STATUS"] == "HALTED"
    assert fields["LEVEL"] == "ADMIN_ALL"
    assert fields["MODE"] == "MANUAL"
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
            "resumption_mode": "MANUAL",
            "level": "ADMIN_SYMBOL",
        },
    )
    assert fields["LEVEL"] == "ADMIN_SYMBOL"
    assert fields["MODE"] == "MANUAL"


def test_normalise_cb_resume_omits_halt_only_fields() -> None:
    n = EngineNormaliser()
    n.normalise_cb_halt(
        "AAPL",
        {
            "trigger_price": 148.20,
            "reference_price": 150.10,
            "resume_at_ns": 1_784_560_800_000_000_000,
            "resumption_mode": "AUCTION",
            "level": "L2",
        },
    )
    sym, fields = n.normalise_cb_resume("AAPL", {"mode": "AUCTION"})
    assert sym == "AAPL"
    assert fields == {"STATUS": "ACTIVE", "MODE": "AUCTION"}


def test_normalise_cb_resume_mode_field_normalizes_engine_inconsistency() -> None:
    """The engine's resume payload uses `mode`, its halt payload uses
    `resumption_mode` -- the CALF wire uses MODE for both, so a client never
    needs to know about this internal inconsistency."""
    n = EngineNormaliser()
    halt_sym, halt_fields = n.normalise_cb_halt(
        "AAPL", {"resumption_mode": "CONTINUOUS", "level": "L1"}
    )
    resume_sym, resume_fields = n.normalise_cb_resume("AAPL", {"mode": "CONTINUOUS"})
    assert halt_fields["MODE"] == resume_fields["MODE"] == "CONTINUOUS"
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
            "resumption_mode": "AUCTION",
            "level": "L2",
        },
    )
    fields = n.cb_snapshot_fields("AAPL")
    assert fields["STATUS"] == "HALTED"
    assert fields["LEVEL"] == "L2"
    assert fields["TRIGGERPX"] == "148.2"


def test_cb_snapshot_fields_reflects_resume_after_halt() -> None:
    n = EngineNormaliser()
    n.normalise_cb_halt("AAPL", {"resumption_mode": "AUCTION", "level": "L1"})
    n.normalise_cb_resume("AAPL", {"mode": "AUCTION"})
    fields = n.cb_snapshot_fields("AAPL")
    assert fields == {"STATUS": "ACTIVE", "MODE": "AUCTION"}


def test_normalise_cb_halt_symbol_uppercased() -> None:
    n = EngineNormaliser()
    sym, _ = n.normalise_cb_halt("aapl", {"level": "L1"})
    assert sym == "AAPL"

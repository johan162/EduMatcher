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

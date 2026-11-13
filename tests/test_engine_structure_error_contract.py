"""An OCO, combo or quote request gets exactly one answer, whatever breaks.

The pre-beta review's E3 gave plain orders a reject when their handler
raised; the structure handlers were left out because the generic reject is
addressed by ``order_id``, which an OCO (``oco_id``), a combo (``combo_id``)
and a quote (``quote_id``) do not carry. So a malformed ``tif`` on an OCO,
or any bug inside those handlers, answered nobody (review 2026-11, C3), and
one such failure was reachable from a well-formed request (C4). The
contract these tests pin:

* a failure before the structure's accept ack answers with that ack,
  ``accepted=false``;
* a failure after it cancels whatever the structure already put on the book,
  ends the structure (combo FAILED, quote CANCELLED, OCO unlinked) and sends
  no second, contradicting ack.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from edumatcher.engine.order_book import OrderBook
from edumatcher.models.combo import ComboStatus
from edumatcher.models.order import OrderType, Side
from edumatcher.models.price import to_ticks
from tests.engine_harness import (
    SYMBOL,
    all_msgs,
    assert_engine_links,
    connect,
    make_engine,
    msgs,
    order_payload,
    submit_quote,
)

OTHER = "MSFT"
MM = "GW03"


def _oco_payload(**over: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "oco_id": "B1", "gateway_id": "GW01", "symbol": SYMBOL, "quantity": 5,
        "tif": "DAY",
        "leg1": {"side": "SELL", "order_type": "LIMIT", "price_ticks": 10100},
        "leg2": {"side": "SELL", "order_type": "STOP", "stop_price_ticks": 9900},
    }  # fmt: skip
    payload.update(over)
    return payload


def _combo_payload(**over: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "combo_id": "C1", "gateway_id": "GW01", "combo_type": "AON", "tif": "DAY",
        "legs": [
            {"symbol": SYMBOL, "side": "BUY", "order_type": "LIMIT",
             "quantity": 5, "price_ticks": to_ticks(50.0, SYMBOL)},
            {"symbol": OTHER, "side": "SELL", "order_type": "LIMIT",
             "quantity": 5, "price_ticks": to_ticks(150.0, OTHER)},
        ],
    }  # fmt: skip
    payload.update(over)
    return payload


def _resting(engine: Any) -> list[Any]:
    return [o for b in engine.books.values() for o in b.resting_orders()]


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    eng, _pub = make_engine(
        monkeypatch, tmp_path, symbols=(SYMBOL, OTHER), mm_gateways=(MM,)
    )
    connect(eng)
    return eng


def _since(engine: Any, n: int) -> list[tuple[str, dict[str, Any]]]:
    return all_msgs(engine.pub_sock)[n:]


# --- malformed payloads: one refusal, nothing posted ----------------------


@pytest.mark.parametrize(
    "bad", [{"tif": "FOREVER"}, {"quantity": "ten"}, {"symbol": None}]
)
def test_a_malformed_oco_is_refused_with_its_own_ack(
    engine: Any, bad: dict[str, Any]
) -> None:
    n = len(engine.pub_sock.sent)
    engine._dispatch_pull_message("order.oco", _oco_payload(**bad))
    published = _since(engine, n)
    assert [t for t, _ in published] == ["oco.ack.GW01"]
    ((_, ack),) = published
    assert ack["accepted"] is False and "Invalid" in ack["reason"]
    assert _resting(engine) == [] and not engine._oco_groups
    assert engine._error_count == 0


@pytest.mark.parametrize("bad", [{"combo_type": "ALL"}, {"tif": 7}, {"legs": "none"}])
def test_a_malformed_combo_is_refused_with_its_own_ack(
    engine: Any, bad: dict[str, Any]
) -> None:
    n = len(engine.pub_sock.sent)
    engine._dispatch_pull_message("order.combo", _combo_payload(**bad))
    published = _since(engine, n)
    assert [t for t, _ in published] == ["combo.ack.GW01"]
    ((_, ack),) = published
    assert ack["accepted"] is False and "Invalid" in ack["reason"]
    assert _resting(engine) == [] and not engine._combos
    assert engine._error_count == 0


# --- a handler bug before the accept ack: the structure's ack, refused ----


def test_an_oco_handler_error_before_the_ack_answers_with_oco_ack(engine: Any) -> None:
    engine._resolve_smp_action = lambda *_a, **_k: 1 / 0
    n = len(engine.pub_sock.sent)
    engine._dispatch_pull_message("order.oco", _oco_payload())
    acks = [p for t, p in _since(engine, n) if t == "oco.ack.GW01"]
    assert [a["accepted"] for a in acks] == [False]
    assert acks[0]["oco_id"] == "B1" and "Internal error" in acks[0]["reason"]
    assert engine._error_count == 1


def test_a_combo_handler_error_before_the_ack_answers_with_combo_ack(
    engine: Any,
) -> None:
    engine._collar_breach = lambda *_a, **_k: 1 / 0
    n = len(engine.pub_sock.sent)
    engine._dispatch_pull_message("order.combo", _combo_payload())
    acks = [p for t, p in _since(engine, n) if t == "combo.ack.GW01"]
    assert [a["accepted"] for a in acks] == [False]
    assert acks[0]["combo_id"] == "C1" and "Internal error" in acks[0]["reason"]


def test_a_quote_handler_error_before_the_ack_answers_with_quote_ack(
    engine: Any,
) -> None:
    engine._resolve_smp_action = lambda *_a, **_k: 1 / 0
    n = len(engine.pub_sock.sent)
    engine._dispatch_pull_message(
        "quote.new",
        {"gateway_id": MM, "symbol": SYMBOL, "quote_id": "Q9", "bid_price_ticks": 9900,
         "ask_price_ticks": 10100, "bid_qty": 10, "ask_qty": 10, "tif": "DAY"},
    )  # fmt: skip
    acks = [p for t, p in _since(engine, n) if t == f"quote.ack.{MM}"]
    assert [a["accepted"] for a in acks] == [False]
    assert acks[0]["quote_id"] == "Q9" and acks[0]["symbol"] == SYMBOL


@pytest.mark.parametrize(
    "topic, payload, ack_topic, id_key",
    [
        ("quote.cancel", {"gateway_id": MM, "symbol": SYMBOL, "request_tag": "r1"},
         f"quote.cancel_ack.{MM}", "symbol"),
        ("order.oco_cancel", {"gateway_id": "GW01", "oco_id": "B1", "request_tag": "r2"},
         "oco.cancel_ack.GW01", "oco_id"),
        ("order.combo_cancel", {"gateway_id": "GW01", "combo_id": "C1", "request_tag": "r3"},
         "combo.cancel_ack.GW01", "combo_id"),
    ],
)  # fmt: skip
def test_a_structure_cancel_handler_error_answers_with_its_cancel_ack(
    engine: Any, topic: str, payload: dict[str, Any], ack_topic: str, id_key: str
) -> None:
    engine._gateway_status = lambda *_a, **_k: 1 / 0
    n = len(engine.pub_sock.sent)
    engine._dispatch_pull_message(topic, payload)
    acks = [p for t, p in _since(engine, n) if t == ack_topic]
    assert len(acks) == 1
    ack = acks[0]
    assert ack["accepted"] is False
    assert ack["reject_code"] == "INTERNAL_ERROR"
    assert ack["request_tag"] == payload["request_tag"]
    assert ack[id_key] == payload[id_key]


# --- a handler bug after the accept ack: clean up, no second ack ----------


def _raise_on_process(
    monkeypatch: pytest.MonkeyPatch, engine: Any, symbol: str, nth: int = 2
) -> None:
    """The *nth* ``process`` call on *symbol*'s book raises, so the handler
    breaks after the accept ack went out and after an earlier leg posted."""
    engine._book(symbol)
    real = OrderBook.process
    calls = {"n": 0}

    def flaky(self: OrderBook, order: Any, **kw: Any) -> Any:
        if self.symbol == symbol:
            calls["n"] += 1
            if calls["n"] == nth:
                raise RuntimeError("book broke")
        return real(self, order, **kw)

    monkeypatch.setattr(OrderBook, "process", flaky)


def test_an_oco_error_after_the_ack_cancels_the_posted_leg_and_unlinks(
    engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _raise_on_process(monkeypatch, engine, SYMBOL)
    n = len(engine.pub_sock.sent)
    engine._dispatch_pull_message("order.oco", _oco_payload())
    published = _since(engine, n)
    acks = [p for t, p in published if t == "oco.ack.GW01"]
    assert [a["accepted"] for a in acks] == [True]  # no contradicting second ack
    leg1, leg2 = acks[0]["order_id_1"], acks[0]["order_id_2"]
    cancelled = {p["order_id"] for t, p in published if t == "order.cancelled.GW01"}
    assert cancelled == {leg1, leg2}
    assert _resting(engine) == [] and not engine._oco_groups
    assert leg1 not in engine._order_symbol and leg2 not in engine._order_symbol
    assert engine._error_count == 1
    assert_engine_links(engine)


def test_a_combo_error_after_the_ack_fails_the_combo(
    engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _raise_on_process(monkeypatch, engine, OTHER, nth=1)
    n = len(engine.pub_sock.sent)
    engine._dispatch_pull_message("order.combo", _combo_payload())
    published = _since(engine, n)
    acks = [p for t, p in published if t == "combo.ack.GW01"]
    assert [a["accepted"] for a in acks] == [True]
    (combo,) = engine._combos.values()
    assert combo.status is ComboStatus.FAILED
    statuses = [p for t, p in published if t == "combo.status.GW01"]
    assert [s["status"] for s in statuses] == ["FAILED"]
    assert "Internal error" in statuses[0]["reason"]
    cancelled = {p["order_id"] for t, p in published if t == "order.cancelled.GW01"}
    assert cancelled == set(combo.child_order_ids)
    assert _resting(engine) == [] and not engine._order_to_combo
    assert_engine_links(engine)


def test_a_quote_error_after_the_ack_ends_the_quote(
    engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _raise_on_process(monkeypatch, engine, SYMBOL)
    n = len(engine.pub_sock.sent)
    engine._dispatch_pull_message(
        "quote.new",
        {"gateway_id": MM, "symbol": SYMBOL, "quote_id": "Q1", "bid_price_ticks": 9900,
         "ask_price_ticks": 10100, "bid_qty": 10, "ask_qty": 10, "tif": "DAY"},
    )  # fmt: skip
    published = _since(engine, n)
    acks = [p for t, p in published if t == f"quote.ack.{MM}"]
    assert [a["accepted"] for a in acks] == [True]
    statuses = [p["status"] for t, p in published if t == f"quote.status.{MM}"]
    assert statuses == ["ACTIVE", "CANCELLED"]
    cancelled = {p["order_id"] for t, p in published if t == f"order.cancelled.{MM}"}
    assert cancelled == {acks[0]["bid_order_id"], acks[0]["ask_order_id"]}
    assert engine._quote_index.get(MM, SYMBOL) is None
    assert _resting(engine) == []
    # The market maker can quote again at once.
    submit_quote(engine, MM, 99.0, 101.0, quote_id="Q2")
    assert msgs(engine.pub_sock, f"quote.ack.{MM}")[-1]["accepted"] is True


# --- C4: a trailing-stop leg needs a reference price ----------------------


def _trailing_oco() -> dict[str, Any]:
    return _oco_payload(
        leg2={"side": "SELL", "order_type": "TRAILING_STOP", "trail_offset_ticks": 100}
    )


def test_a_trailing_oco_leg_without_a_reference_is_refused_whole(engine: Any) -> None:
    n = len(engine.pub_sock.sent)
    engine._dispatch_pull_message("order.oco", _trailing_oco())
    published = _since(engine, n)
    assert [t for t, _ in published] == ["oco.ack.GW01"]
    ack = published[0][1]
    assert ack["accepted"] is False and "STOP=" in ack["reason"]
    assert _resting(engine) == [] and not engine._oco_groups
    assert engine._error_count == 0


def test_a_trailing_oco_leg_with_a_reference_is_accepted(engine: Any) -> None:
    engine._handle_new_order(
        order_payload(Side.SELL, OrderType.LIMIT, 5, "GW02", price=100.0)
    )
    engine._handle_new_order(order_payload(Side.BUY, OrderType.MARKET, 5, "GW01"))
    assert engine.books[SYMBOL].last_trade_price == 10000
    engine._dispatch_pull_message("order.oco", _trailing_oco())
    ack = msgs(engine.pub_sock, "oco.ack.GW01")[-1]
    assert ack["accepted"] is True
    trailing = engine.books[SYMBOL].get_order(ack["order_id_2"])
    assert trailing is not None and trailing.stop_price_ticks == 10000 - 100

"""WP-API17 (Q8): every structure cancel gets its own, attributable ack.

``oco.cancel_ack``, ``combo.cancel_ack`` and ``quote.cancel_ack`` answer each
OCO, combo and quote cancel -- accepted or refused -- echoing the request's
``request_tag``. Before, a refusal rode the *submit* ack (``oco.ack`` etc.,
indistinguishable from a submit's outcome) and a successful OCO cancel had no
group-level reply at all, so a caller could not wait for its own outcome.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType
from edumatcher.models.generated.registry import TOPIC_REGISTRY
from edumatcher.models.order import OrderType, Side, TIF
from tests.engine_harness import connect, make_engine, msgs, submit_quote

GW = "GW01"


def _order_ack_reject_codes() -> set[str]:
    fields = TOPIC_REGISTRY["order.ack.{gateway_id}"]["fields"]
    (field,) = [f for f in fields if f["name"] == "reject_code"]
    return set(field["values"])


def _engine(monkeypatch: Any, tmp_path: Any) -> tuple[Any, Any]:
    engine, pub = make_engine(
        monkeypatch, tmp_path, symbols=("AAPL", "MSFT"), mm_gateways=(GW,)
    )
    connect(engine, GW)
    return engine, pub


def _submit_oco(engine: Any) -> None:
    engine._handle_oco_order(
        {
            "oco_id": "OCO1",
            "gateway_id": GW,
            "symbol": "AAPL",
            "quantity": 10,
            "tif": "DAY",
            "tick_decimals": 2,
            "leg1": {"side": "SELL", "order_type": "LIMIT", "price_ticks": 11000},
            "leg2": {"side": "SELL", "order_type": "STOP", "stop_price_ticks": 9000},
        }
    )


def _submit_combo(engine: Any) -> None:
    combo = ComboOrder.create(
        combo_id="C1",
        gateway_id=GW,
        combo_type=ComboType.AON,
        tif=TIF.DAY,
        legs=[
            ComboLeg(symbol="AAPL", side=Side.BUY, order_type=OrderType.LIMIT,
                     quantity=10, tick_decimals=2, price_ticks=9000),
            ComboLeg(symbol="MSFT", side=Side.SELL, order_type=OrderType.LIMIT,
                     quantity=5, tick_decimals=2, price_ticks=50000),
        ],
    )  # fmt: skip
    engine._handle_combo_order(combo.to_dict())


def _only(pub: Any, topic: str) -> dict[str, Any]:
    (message,) = msgs(pub, topic)
    return message


# --- OCO ------------------------------------------------------------------------


def test_an_oco_cancel_is_acked_with_its_tag_and_legs(monkeypatch, tmp_path):
    engine, pub = _engine(monkeypatch, tmp_path)
    _submit_oco(engine)
    pub.sent.clear()
    engine._handle_oco_cancel({"oco_id": "OCO1", "gateway_id": GW, "request_tag": "t1"})
    ack = _only(pub, f"oco.cancel_ack.{GW}")
    assert (ack["accepted"], ack["oco_id"], ack["request_tag"]) == (True, "OCO1", "t1")
    assert len(ack["cancelled_order_ids"]) == 2
    assert "reject_code" not in ack
    assert msgs(pub, f"oco.ack.{GW}") == []  # the submit ack means submit only


def test_an_unknown_oco_cancel_is_refused_on_the_cancel_ack(monkeypatch, tmp_path):
    engine, pub = _engine(monkeypatch, tmp_path)
    engine._handle_oco_cancel({"oco_id": "NOPE", "gateway_id": GW, "request_tag": "t2"})
    ack = _only(pub, f"oco.cancel_ack.{GW}")
    assert (ack["accepted"], ack["reject_code"], ack["request_tag"]) == (
        False, "ORDER_NOT_FOUND", "t2",
    )  # fmt: skip
    assert ack["cancelled_order_ids"] == []
    assert msgs(pub, f"oco.ack.{GW}") == []


# --- combo ----------------------------------------------------------------------


def test_a_combo_cancel_is_acked_and_still_reports_its_status(monkeypatch, tmp_path):
    engine, pub = _engine(monkeypatch, tmp_path)
    _submit_combo(engine)
    pub.sent.clear()
    engine._handle_combo_cancel(
        {"combo_id": "C1", "gateway_id": GW, "request_tag": "c1"}
    )
    ack = _only(pub, f"combo.cancel_ack.{GW}")
    assert (ack["accepted"], ack["combo_id"], ack["request_tag"]) == (True, "C1", "c1")
    assert len(ack["cancelled_order_ids"]) == 2
    # The lifecycle event is state, not a reply: it is still published.
    assert [m["status"] for m in msgs(pub, f"combo.status.{GW}")] == ["CANCELLED"]
    assert msgs(pub, f"combo.ack.{GW}") == []


def test_a_finished_combo_cancel_is_refused_as_terminal(monkeypatch, tmp_path):
    engine, pub = _engine(monkeypatch, tmp_path)
    _submit_combo(engine)
    engine._handle_combo_cancel({"combo_id": "C1", "gateway_id": GW})
    pub.sent.clear()
    engine._handle_combo_cancel({"combo_id": "C1", "gateway_id": GW})
    ack = _only(pub, f"combo.cancel_ack.{GW}")
    assert (ack["accepted"], ack["reject_code"]) == (False, "ORDER_ALREADY_TERMINAL")
    assert "request_tag" not in ack


# --- quote ----------------------------------------------------------------------


def test_a_quote_cancel_is_acked_with_the_quote_and_its_legs(monkeypatch, tmp_path):
    engine, pub = _engine(monkeypatch, tmp_path)
    submit_quote(engine, GW, bid_price=99.0, ask_price=101.0, quote_id="Q7")
    pub.sent.clear()
    engine._handle_quote_cancel(
        {"gateway_id": GW, "symbol": "AAPL", "request_tag": "q1"}
    )
    ack = _only(pub, f"quote.cancel_ack.{GW}")
    assert (ack["accepted"], ack["symbol"], ack["quote_id"], ack["request_tag"]) == (
        True, "AAPL", "Q7", "q1",
    )  # fmt: skip
    assert len(ack["cancelled_order_ids"]) == 2
    assert msgs(pub, f"quote.ack.{GW}") == []


def test_cancelling_no_quote_is_refused_as_not_found(monkeypatch, tmp_path):
    engine, pub = _engine(monkeypatch, tmp_path)
    engine._handle_quote_cancel({"gateway_id": GW, "symbol": "AAPL"})
    ack = _only(pub, f"quote.cancel_ack.{GW}")
    assert (ack["accepted"], ack["reject_code"], ack["quote_id"]) == (
        False, "ORDER_NOT_FOUND", "",
    )  # fmt: skip


# --- vocabulary -----------------------------------------------------------------


@pytest.mark.parametrize("kind", ["oco", "combo", "quote"])
def test_refusals_by_an_unconnected_gateway_use_order_ack_codes(
    kind: str, monkeypatch: Any, tmp_path: Any
) -> None:
    engine, pub = _engine(monkeypatch, tmp_path)
    payload = {"gateway_id": "GHOST", "oco_id": "X", "combo_id": "X", "symbol": "AAPL"}
    getattr(engine, f"_handle_{kind}_cancel")(payload)
    ack = _only(pub, f"{kind}.cancel_ack.GHOST")
    assert ack["accepted"] is False
    assert ack["reject_code"] in _order_ack_reject_codes()


def test_every_code_the_engine_can_send_is_order_ack_vocabulary() -> None:
    """The cancel acks' reject_code is a string only for want of a shared enum
    type in the IDL; this pins it to order.ack's vocabulary."""
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "src/edumatcher/engine/main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    codes = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
            "_handle_oco_cancel",
            "_handle_combo_cancel",
            "_handle_quote_cancel",
            "_structure_cancel_ack",
        ):
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Constant)
                    and isinstance(inner.value, str)
                    and inner.value.isupper()
                    and "_" in inner.value
                ):
                    codes.add(inner.value)
    assert codes and codes <= _order_ack_reject_codes() | {"CANCELLED"}

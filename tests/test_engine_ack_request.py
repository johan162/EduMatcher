"""``order.ack`` says which request it answers (API gateway review C1, Q2).

A refused new order, a refused cancel and a refused amend all publish
``order.ack accepted=false``. Readers told them apart by ``request_tag``,
which a cancel or amend carries only when the client sent one, so an
untagged refused amend marked a still-resting order REJECTED in every
gateway's cache.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from edumatcher.models.order import OrderType, Side
from tests.engine_harness import connect, make_engine, msgs, order_payload

ACK = "order.ack.GW01"


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    eng, _pub = make_engine(monkeypatch, tmp_path)
    connect(eng, "GW01")
    return eng


def _resting(engine: Any) -> str:
    engine._handle_new_order(
        order_payload(Side.BUY, OrderType.LIMIT, 10, "GW01", price=100.0)
    )
    ack = msgs(engine.pub_sock, ACK)[-1]
    assert ack["accepted"]
    return str(ack["order_id"])


def test_an_accepted_new_order_is_labelled_new(engine: Any) -> None:
    _resting(engine)
    assert msgs(engine.pub_sock, ACK)[-1]["request"] == "NEW"


def test_a_refused_new_order_is_labelled_new(engine: Any) -> None:
    engine._handle_new_order(
        order_payload(Side.BUY, OrderType.LIMIT, 0, "GW01", price=100.0)
    )
    ack = msgs(engine.pub_sock, ACK)[-1]
    assert ack["accepted"] is False
    assert ack["request"] == "NEW"


def test_an_untagged_refused_amend_is_labelled_amend(engine: Any) -> None:
    order_id = _resting(engine)
    engine._handle_amend({"order_id": order_id, "gateway_id": "GW01", "qty": 0})
    ack = msgs(engine.pub_sock, ACK)[-1]
    assert ack["accepted"] is False
    assert "request_tag" not in ack
    assert ack["request"] == "AMEND"


def test_an_untagged_refused_cancel_is_labelled_cancel(engine: Any) -> None:
    engine._handle_cancel({"order_id": "NO-SUCH", "gateway_id": "GW01"})
    ack = msgs(engine.pub_sock, ACK)[-1]
    assert ack["accepted"] is False
    assert ack["request"] == "CANCEL"


def test_an_engine_error_answer_is_labelled_by_its_request(engine: Any) -> None:
    from edumatcher.models.generated.order import (
        TOPIC_ORDER_AMEND,
        TOPIC_ORDER_CANCEL,
        TOPIC_ORDER_NEW,
    )
    from edumatcher.models.message import decode

    for topic, request in (
        (TOPIC_ORDER_NEW, "NEW"),
        (TOPIC_ORDER_CANCEL, "CANCEL"),
        (TOPIC_ORDER_AMEND, "AMEND"),
    ):
        frames = engine._error_answer(topic, {"order_id": "X"}, "GW01", "boom", None)
        # Published, as _reject_after_error does: the harness checks that every
        # counted reject reached the bus.
        engine.pub_sock.send_multipart(frames)
        assert decode(frames)[1]["request"] == request

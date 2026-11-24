"""L044: an ADMIN disconnects another participant with ``risk.gateway_kick``.

``system.gateway_disconnect`` names only the gateway it ends, so a kick sent
with it reached the audit trail as the target's own logout: the operator's id
appeared nowhere, an unknown id was ignored silently and nothing answered.
The ADMIN message carries the requester, is acknowledged (with a refusal for
an unknown, disconnected or own id) and is recorded as an ``admin.action``.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.models.order import OrderType, Side
from tests.engine_harness import (
    all_msgs,
    connect,
    make_engine,
    msgs,
    order_payload,
    submit_quote,
)

ADMIN = "ADM01"
MM = "MM01"
TRADER = "TRADER01"


def _engine(monkeypatch: Any, tmp_path: Any) -> tuple[Any, Any]:
    engine, pub_sock = make_engine(
        monkeypatch,
        tmp_path,
        gateways=(ADMIN, MM, TRADER),
        mm_gateways=(MM,),
        admin_gateways=(ADMIN,),
    )
    connect(engine, ADMIN, MM, TRADER)
    submit_quote(engine, MM, bid_price=99.0, ask_price=101.0)
    engine._handle_new_order(
        order_payload(
            gateway_id=MM, side=Side.BUY, order_type=OrderType.LIMIT,
            price=95.0, qty=10,
        )
    )  # fmt: skip
    pub_sock.sent.clear()
    return engine, pub_sock


def _kick(engine: Any, target: str, caller: str = ADMIN, **extra: Any) -> None:
    engine._dispatch_pull_message(
        "risk.gateway_kick",
        {"gateway_id": caller, "target_gateway_id": target, **extra},
    )


def _actions(pub_sock: Any, caller: str = ADMIN) -> list[dict[str, Any]]:
    return [
        m
        for m in msgs(pub_sock, f"admin.action.{caller}")
        if m.get("action") == "gateway.kick"
    ]


def test_a_kick_disconnects_the_target_and_names_the_admin(monkeypatch, tmp_path):
    engine, pub_sock = _engine(monkeypatch, tmp_path)
    _kick(engine, "mm01", note="compliance hold", command_id="k1")

    assert MM not in engine._connected_participants
    (bye,) = msgs(pub_sock, f"system.gateway_bye.{MM}")
    assert bye["reason"] == f"kicked by {ADMIN}: compliance hold"
    (ack,) = msgs(pub_sock, f"risk.gateway_kick_ack.{ADMIN}")
    assert ack["accepted"] is True
    assert (ack["target_gateway_id"], ack["command_id"]) == (MM, "k1")
    (action,) = _actions(pub_sock)
    assert action["accepted"] is True and action["command_id"] == "k1"
    assert action["initiator_gateway_id"] == ADMIN
    assert action["scope"] == {"target_gateway_id": MM, "note": "compliance hold"}


def test_the_bye_reason_without_a_note_still_names_the_admin(monkeypatch, tmp_path):
    engine, pub_sock = _engine(monkeypatch, tmp_path)
    _kick(engine, TRADER, command_id="k2")
    (bye,) = msgs(pub_sock, f"system.gateway_bye.{TRADER}")
    assert bye["reason"] == f"kicked by {ADMIN}"


def test_the_targets_disconnect_behaviour_applies(monkeypatch, tmp_path):
    """The participant's configured behaviour (here the default,
    CANCEL_QUOTES_ONLY) runs exactly as for its own logout."""
    engine, pub_sock = _engine(monkeypatch, tmp_path)
    _kick(engine, MM, command_id="k3")
    reasons = {m["cancel_reason"] for m in msgs(pub_sock, f"order.cancelled.{MM}")}
    assert reasons == {"GATEWAY_DISCONNECT"}
    assert len(msgs(pub_sock, f"order.cancelled.{MM}")) == 2  # both quote legs
    remaining = list(engine.books["AAPL"].orders_for_gateway(MM))
    assert [o.price_ticks for o in remaining] == [9500]  # the plain order stays
    # The ack follows the disconnect's effects, so a caller that sees it can
    # read the roster and find the target gone.
    topics = [t for t, _ in all_msgs(pub_sock)]
    assert topics.index(f"risk.gateway_kick_ack.{ADMIN}") > topics.index(
        f"system.gateway_bye.{MM}"
    )


@pytest.mark.parametrize(
    ("caller", "target", "reason"),
    [
        (ADMIN, "NOSUCH01", "Gateway not configured: NOSUCH01"),
        (ADMIN, ADMIN, "Cannot kick own gateway; disconnect instead"),
        (ADMIN, "", "target_gateway_id required"),
        (TRADER, MM, "Gateway kick is only allowed for ADMIN participants"),
    ],
)
def test_a_refused_kick_disconnects_nothing(
    monkeypatch, tmp_path, caller: str, target: str, reason: str
):
    engine, pub_sock = _engine(monkeypatch, tmp_path)
    _kick(engine, target, caller=caller, command_id="k4")

    (ack,) = msgs(pub_sock, f"risk.gateway_kick_ack.{caller}")
    assert ack["accepted"] is False and ack["reason"] == reason
    assert ack["command_id"] == "k4"
    assert not [t for t, _ in all_msgs(pub_sock) if t.startswith("system.gateway_bye.")]
    assert {ADMIN, MM, TRADER} <= engine._connected_participants
    (action,) = _actions(pub_sock, caller)
    assert action["accepted"] is False and action["reason"] == reason


def test_a_disconnected_target_is_refused(monkeypatch, tmp_path):
    """Kicking a gateway that is not connected would publish a second bye
    for a session clearing already closed."""
    engine, pub_sock = _engine(monkeypatch, tmp_path)
    engine._handle_gateway_disconnect({"gateway_id": TRADER})
    pub_sock.sent.clear()

    _kick(engine, TRADER, command_id="k5")

    (ack,) = msgs(pub_sock, f"risk.gateway_kick_ack.{ADMIN}")
    assert ack["accepted"] is False
    assert ack["reason"] == f"Gateway not connected: {TRADER}"
    assert not msgs(pub_sock, f"system.gateway_bye.{TRADER}")


def test_a_caller_that_is_not_connected_is_refused(monkeypatch, tmp_path):
    engine, pub_sock = _engine(monkeypatch, tmp_path)
    engine._handle_gateway_disconnect({"gateway_id": ADMIN})
    pub_sock.sent.clear()

    _kick(engine, MM, command_id="k6")

    (ack,) = msgs(pub_sock, f"risk.gateway_kick_ack.{ADMIN}")
    assert ack["accepted"] is False
    assert MM in engine._connected_participants

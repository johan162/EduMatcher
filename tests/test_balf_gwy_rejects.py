"""Refusals made at the BALF gateway reach the audit trail (A3)."""

# flake8: noqa: F811  (imported fixtures are redefined by the tests that use them)
from __future__ import annotations

from typing import Any

from edumatcher.balf_gwy.gateway import BalfGateway

from tests.test_balf_gwy_k11_k12 import (  # noqa: F401  (fixtures)
    GW,
    _connect,
    _logon,
    _publish,
    _push,
    _ready_session,
    _sent,
    gateway,
    peers,
)

TOPIC = "system.gateway_reject"


def test_a_frame_before_logon_is_reported(gateway: BalfGateway, peers: Any) -> None:
    session = _connect(gateway, peers)
    session.addr = ("10.0.0.7", 5000)
    gateway._process_frame(session, 0x10, 1, b"")
    (sent,) = _sent(gateway, TOPIC)
    assert sent["source"] == "BALF"
    assert sent["reject_code"] == "AUTH_REQUIRED"
    assert sent["peer"] == "10.0.0.7:5000"


def test_a_rate_limited_message_is_reported(gateway: BalfGateway, peers: Any) -> None:
    session = _ready_session(gateway, peers)
    session.rate_tokens = 0.0
    session.rate_updated = float("inf")
    gateway._process_frame(session, 0x10, 1, b"")
    (sent,) = _sent(gateway, TOPIC)
    assert sent["reject_code"] == "RATE_LIMITED"
    assert sent["gateway_id"] == GW


def test_a_refused_logon_is_reported_as_auth_failed(
    gateway: BalfGateway, peers: Any
) -> None:
    session = _connect(gateway, peers)
    _logon(gateway, session)
    _push(gateway).sent.clear()
    _publish(
        gateway,
        f"system.gateway_auth.{GW}",
        {"gateway_id": GW, "accepted": False, "reason": "not configured"},
    )
    (sent,) = _sent(gateway, TOPIC)
    assert sent["reject_code"] == "AUTH_FAILED"
    assert sent["reason"] == "not configured"

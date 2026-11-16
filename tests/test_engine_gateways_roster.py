"""The engine's system.gateways roster: when each participant connected."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import edumatcher.engine.main as em
from edumatcher.models.generated.system import TOPIC_GATEWAYS_REQUEST
from tests.engine_harness import connect, make_engine, msgs


def _roster(engine: Any) -> dict[str, dict[str, Any]]:
    engine._dispatch_pull_message(TOPIC_GATEWAYS_REQUEST, {"gateway_id": "GW03"})
    reply = msgs(engine.pub_sock, "system.gateways.GW03")[-1]
    return {g["id"]: g for g in reply["gateways"]}


def test_connected_since_is_the_accepted_connect_and_absent_while_offline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine, _pub = make_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(em, "now_ns", lambda: 1_000)
    connect(engine, "GW01")
    monkeypatch.setattr(em, "now_ns", lambda: 2_000)
    engine._handle_gateway_connect({"gateway_id": "GW01"})  # refused: already on
    roster = _roster(engine)
    assert roster["GW01"]["connected_since_ns"] == 1_000
    assert "connected_since_ns" not in roster["GW02"]

    engine._handle_gateway_disconnect({"gateway_id": "GW01", "reason": "bye"})
    assert "connected_since_ns" not in _roster(engine)["GW01"]

    connect(engine, "GW01")  # a reconnect starts a new connection
    assert _roster(engine)["GW01"]["connected_since_ns"] == 2_000

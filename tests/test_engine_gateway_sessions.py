"""Every gateway session can end, and a refused id costs nothing
(For-Later L029, L031; WP-FL02).

L029: the silence clock started only with a session's first heartbeat, so a
client accepted and then dead before its first beat held its gateway id for
good ("Gateway already connected" to every later logon). It now starts at
connect, with the default interval until the first beat names its own.

L031: a refused ``gateway_connect`` (or a ``gateway_disconnect``) for an id
that is not a configured participant created a session the engine kept for
ever, reachable by any client through ALF ``HELLO``.
"""

from __future__ import annotations

import types
from typing import Any

from edumatcher.models.message import GATEWAY_HEARTBEAT_INTERVAL_SEC
from edumatcher.models.order import OrderType, Side
from edumatcher.models.participant import DisconnectBehaviour
from tests.engine_harness import SYMBOL, make_engine, msgs, order_payload

DEADLINE = 3 * GATEWAY_HEARTBEAT_INTERVAL_SEC  # three missed default beats


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


def setup(monkeypatch: Any, tmp_path: Any) -> tuple[Any, Any, _Clock]:
    engine, pub = make_engine(monkeypatch, tmp_path)
    clock = _Clock()
    monkeypatch.setattr(
        "edumatcher.engine.main.time",
        types.SimpleNamespace(
            monotonic=clock.monotonic,
            sleep=lambda *_: None,
            time=lambda: clock.now,
            time_ns=lambda: int(clock.now * 1e9),
            perf_counter=clock.monotonic,
            perf_counter_ns=lambda: int(clock.now * 1e9),
        ),
    )
    return engine, pub, clock


def expire_at(engine: Any, clock: _Clock, t: float) -> None:
    clock.now = t
    engine._next_silence_check = 0.0
    engine._expire_silent_gateways()


def connected(engine: Any, gw: str) -> bool:
    session = engine._sessions.get(gw)
    return session is not None and session.connected


# -- L029: a session that never beats ----------------------------------------


def test_a_session_that_never_beats_expires_after_three_default_intervals(
    monkeypatch, tmp_path
) -> None:
    engine, pub, clock = setup(monkeypatch, tmp_path)
    engine._handle_gateway_connect({"gateway_id": "GW01"})

    expire_at(engine, clock, 1000.0 + DEADLINE - 1)
    assert connected(engine, "GW01")

    expire_at(engine, clock, 1000.0 + DEADLINE + 1)
    assert not connected(engine, "GW01")
    assert [p["reason"] for p in msgs(pub, "system.gateway_bye.GW01")] == [
        "heartbeat_timeout"
    ]


def test_the_expired_id_can_log_on_again(monkeypatch, tmp_path) -> None:
    engine, pub, clock = setup(monkeypatch, tmp_path)
    engine._handle_gateway_connect({"gateway_id": "GW01"})
    expire_at(engine, clock, 1000.0 + DEADLINE + 1)

    engine._handle_gateway_connect({"gateway_id": "GW01"})
    assert [a["accepted"] for a in msgs(pub, "system.gateway_auth.GW01")] == [
        True,
        True,
    ]


def test_an_expired_session_that_never_beat_gets_its_disconnect_behaviour(
    monkeypatch, tmp_path
) -> None:
    engine, pub, clock = setup(monkeypatch, tmp_path)
    assert engine._engine_config is not None
    engine._engine_config.participants["GW01"].disconnect_behaviour = (
        DisconnectBehaviour.CANCEL_ALL
    )
    engine._handle_gateway_connect({"gateway_id": "GW01"})
    engine._handle_new_order(order_payload(Side.BUY, OrderType.LIMIT, 10, "GW01", price=99.0))  # fmt: skip
    assert len(list(engine.books[SYMBOL].resting_orders())) == 1

    expire_at(engine, clock, 1000.0 + DEADLINE + 1)
    assert list(engine.books[SYMBOL].resting_orders()) == []
    (cancelled,) = msgs(pub, "order.cancelled.GW01")
    assert cancelled["cancel_reason"] == "GATEWAY_DISCONNECT"


def test_a_first_beat_with_a_longer_interval_replaces_the_default(
    monkeypatch, tmp_path
) -> None:
    engine, _pub, clock = setup(monkeypatch, tmp_path)
    engine._handle_gateway_connect({"gateway_id": "GW01"})
    clock.now = 1010.0
    engine._handle_gateway_heartbeat({"gateway_id": "GW01", "interval_sec": 300})

    expire_at(engine, clock, 1000.0 + DEADLINE + 1)
    assert connected(engine, "GW01")
    expire_at(engine, clock, 1010.0 + 3 * 300 + 1)
    assert not connected(engine, "GW01")


def test_a_session_that_beats_on_time_stays(monkeypatch, tmp_path) -> None:
    engine, _pub, clock = setup(monkeypatch, tmp_path)
    engine._handle_gateway_connect({"gateway_id": "GW01"})
    for k in range(1, 10):
        clock.now = 1000.0 + k * GATEWAY_HEARTBEAT_INTERVAL_SEC
        engine._handle_gateway_heartbeat(
            {"gateway_id": "GW01", "interval_sec": GATEWAY_HEARTBEAT_INTERVAL_SEC}
        )
        expire_at(engine, clock, clock.now)
    assert connected(engine, "GW01")


# -- L031: refused ids leave nothing behind ----------------------------------


def test_refused_unknown_ids_create_no_session(monkeypatch, tmp_path) -> None:
    engine, pub, _clock = setup(monkeypatch, tmp_path)
    before = set(engine._sessions)
    for i in range(1000):
        engine._handle_gateway_connect({"gateway_id": f"NOPE{i}"})

    assert set(engine._sessions) == before
    for i in (0, 999):
        (auth,) = msgs(pub, f"system.gateway_auth.NOPE{i}")
        assert auth["accepted"] is False
        assert auth["reason"] == f"Gateway not configured: NOPE{i}"
    labels = set(engine.metrics.auth_rejects)
    assert not any(label.startswith("NOPE") for label in labels)


def test_a_disconnect_for_an_unknown_id_creates_no_session(
    monkeypatch, tmp_path
) -> None:
    engine, pub, _clock = setup(monkeypatch, tmp_path)
    before = set(engine._sessions)
    for i in range(100):
        engine._handle_gateway_disconnect({"gateway_id": f"NOPE{i}"})
    assert set(engine._sessions) == before
    assert msgs(pub, "system.gateway_bye.NOPE0") == []


def test_a_configured_id_already_connected_is_still_refused(
    monkeypatch, tmp_path
) -> None:
    engine, pub, _clock = setup(monkeypatch, tmp_path)
    engine._handle_gateway_connect({"gateway_id": "GW01"})
    engine._handle_gateway_connect({"gateway_id": "GW01"})
    acks = msgs(pub, "system.gateway_auth.GW01")
    assert [a["accepted"] for a in acks] == [True, False]
    assert acks[1]["reason"] == (
        f"Gateway already connected: GW01 — if that session is gone, "
        f"the ID is freed within {DEADLINE} s"
    )


def test_the_refusal_says_when_a_silent_id_is_freed(monkeypatch, tmp_path) -> None:
    """A person whose console died sees how long to wait, counted from the
    session's last beat at its own interval."""
    engine, pub, clock = setup(monkeypatch, tmp_path)
    engine._handle_gateway_connect({"gateway_id": "GW01"})
    clock.now += 30
    engine._handle_gateway_connect({"gateway_id": "GW01"})
    engine._handle_gateway_heartbeat({"gateway_id": "GW01", "interval_sec": 5})
    clock.now += 2.5
    engine._handle_gateway_connect({"gateway_id": "GW01"})
    reasons = [a["reason"] for a in msgs(pub, "system.gateway_auth.GW01")[1:]]
    assert [r.rsplit("within ", 1)[1] for r in reasons] == [
        f"{DEADLINE - 30} s",
        "13 s",
    ]

"""Every gateway must react to an engine restart the same way (K11/B2).

A restarted engine holds no sessions. A gateway that keeps treating its
clients as authenticated leaves them trading against a session that no longer
exists, so each one must subscribe to ``system.startup_recovery``, tell every
client, close it, and forget the engine-side state it cached.

The API gateway honours the same contract (K15, finding P4) but has no TCP
sessions of its own to drop: it forgets the gateway ids it believes the engine
has authenticated, so the next request re-runs ``gateway_connect``. That half
is asserted in ``test_api_gateway_k13_k15.py`` rather than duplicated here,
because none of the session machinery below applies to it.
"""

from __future__ import annotations

import socket
from collections import deque
from typing import Any

import pytest

from edumatcher.alf_gwy.config import AlfGatewayConfig
from edumatcher.alf_gwy.gateway import AlfGateway
from edumatcher.alf_gwy.gateway import ClientSession as AlfSession
from edumatcher.balf_gwy.config import BalfGatewayConfig
from edumatcher.balf_gwy.gateway import BalfGateway
from edumatcher.balf_gwy.gateway import ClientSession as BalfSession
from edumatcher.models.generated.system import TOPIC_STARTUP_RECOVERY
from edumatcher.models.message import encode

GW = "TRADER01"


class _FakePush:
    closed = False

    def send_multipart(self, frames: list[bytes]) -> None:
        _ = frames

    def close(self) -> None:
        self.closed = True


class _FakeSub:
    def __init__(self) -> None:
        self.closed = False
        self.topics: list[bytes] = []
        self._queue: deque[list[bytes]] = deque()

    def setsockopt(self, op: int, value: bytes) -> None:
        _ = op
        self.topics.append(value)

    def poll(self, timeout: int = 0) -> int:
        _ = timeout
        return 1 if self._queue else 0

    def recv_multipart(self) -> list[bytes]:
        return self._queue.popleft()

    def close(self) -> None:
        self.closed = True


def _make_alf(monkeypatch: pytest.MonkeyPatch) -> AlfGateway:
    monkeypatch.setattr(
        "edumatcher.alf_gwy.gateway.make_pusher", lambda _addr: _FakePush()
    )
    return AlfGateway(
        AlfGatewayConfig(
            bind_address="127.0.0.1", port=5565, gateway_roles=((GW, "TRADER"),)
        )
    )


def _make_balf(monkeypatch: pytest.MonkeyPatch) -> BalfGateway:
    monkeypatch.setattr(
        "edumatcher.balf_gwy.gateway.make_pusher", lambda _addr: _FakePush()
    )
    return BalfGateway(
        BalfGatewayConfig(
            bind_address="127.0.0.1", port=5561, gateway_roles=((GW, "TRADER"),)
        )
    )


@pytest.fixture(params=["alf", "balf"])
def gateway(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Any:
    """A gateway with one authenticated session and a fake SUB socket."""
    sub = _FakeSub()
    subscribed: list[str] = []

    def _record(_addr: str, *topics: str, **_kw: object) -> _FakeSub:
        subscribed.extend(topics)
        return sub

    monkeypatch.setattr(
        f"edumatcher.{request.param}_gwy.gateway.make_subscriber", _record
    )
    gw: Any = (_make_alf if request.param == "alf" else _make_balf)(monkeypatch)
    gw._sub = sub

    left, right = socket.socketpair()
    request.addfinalizer(left.close)
    request.addfinalizer(right.close)
    cls = AlfSession if request.param == "alf" else BalfSession
    session = cls(sock=left, addr=("127.0.0.1", 40000))
    session.authenticated = True
    session.gateway_id = GW
    session.connect_emitted = True
    gw._clients[left.fileno()] = session
    gw._active_gateway_sessions[GW] = left.fileno()
    return gw, session, sub, subscribed


def test_every_gateway_subscribes_to_startup_recovery(gateway: Any) -> None:
    _, _, _, subscribed = gateway
    assert TOPIC_STARTUP_RECOVERY in subscribed


def test_every_gateway_drops_its_sessions_on_an_engine_restart(gateway: Any) -> None:
    gw, session, sub, _ = gateway
    sub._queue.append(encode(TOPIC_STARTUP_RECOVERY, {"restored_orders": 0}))

    gw._poll_engine_events()

    assert session.closing, "the client was left believing it was logged on"
    assert session.out_queue, "the client was never told"
    assert not session.connect_emitted, "a disconnect would name a lost session"

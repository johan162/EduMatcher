"""Engine lifecycle events from the engine bus (WP-B3.2, design §9.2)."""

from __future__ import annotations

import time
from zoneinfo import ZoneInfo

import pytest
import zmq

from edumatcher.models.generated.circuit_breaker import (
    make_circuit_breaker_halt,
    make_circuit_breaker_resume,
)
from edumatcher.models.generated.health import TOPIC_HEALTH_EVENT, parse_health_event
from edumatcher.models.generated.session import make_session_state
from edumatcher.models.generated.system import (
    make_diagnostic,
    make_gateway_auth,
    make_gateway_bye,
)
from edumatcher.monitor.activity import Activity
from edumatcher.monitor.collector import Monitor
from edumatcher.monitor.config import MonitorConfig
from edumatcher.monitor.events import SUBSCRIPTIONS, EngineEvent, translate
from tests.conftest import free_ports
from tests.test_monitor_main import QuietHost

STOCKHOLM = ZoneInfo("Europe/Stockholm")
WALL = 1_760_000_000.0


@pytest.fixture
def activity() -> Activity:
    return Activity(STOCKHOLM, {"GW1": "TRADER"})


CASES = [
    (
        "connect",
        make_gateway_auth(gateway_id="GW1", accepted=True, description="desk 3"),
        EngineEvent("CONNECT", "INFO", "GW1", "desk 3"),
    ),
    (
        "auth reject",
        make_gateway_auth(gateway_id="GW9", accepted=False, reason="unknown_gateway"),
        EngineEvent("AUTH_REJECT", "WARN", "GW9", "unknown_gateway"),
    ),
    (
        "disconnect",
        make_gateway_bye(gateway_id="GW1", reason="logout"),
        EngineEvent("DISCONNECT", "INFO", "GW1", "logout"),
    ),
    (
        "heartbeat timeout is flagged",
        make_gateway_bye(gateway_id="GW1", reason="heartbeat_timeout"),
        EngineEvent("DISCONNECT", "WARN", "GW1", "heartbeat_timeout"),
    ),
    (
        "diagnostic",
        make_diagnostic(
            component="DISPATCH_ERROR", detail="order.new", count=3, error="KeyError"
        ),
        EngineEvent("DIAGNOSTIC", "WARN", "DISPATCH_ERROR", "order.new (x3): KeyError"),
    ),
    (
        "session",
        make_session_state(state="CONTINUOUS", prev_state="OPENING_AUCTION"),
        EngineEvent("SESSION", "INFO", "session", "OPENING_AUCTION -> CONTINUOUS"),
    ),
    (
        "halt",
        make_circuit_breaker_halt(symbol="AAA", halt_source="CB", level="L1"),
        EngineEvent("HALT", "WARN", "AAA", "L1 CB"),
    ),
    (
        "resume",
        make_circuit_breaker_resume(symbol="AAA", reason="timer"),
        EngineEvent("RESUME", "INFO", "AAA", "timer"),
    ),
]


@pytest.mark.parametrize(
    ("frames", "expected"), [c[1:] for c in CASES], ids=[c[0] for c in CASES]
)
def test_translate(
    frames: list[bytes], expected: EngineEvent, activity: Activity
) -> None:
    assert translate(frames, activity, WALL) == expected


def test_a_foreign_topic_is_ignored(activity: Activity) -> None:
    assert translate([b"session.state_extra", b"{}"], activity, WALL) is None
    assert translate([b"book.AAA", b"{}"], activity, WALL) is None


def test_a_malformed_message_raises(activity: Activity) -> None:
    with pytest.raises(Exception):
        translate([b"system.gateway_bye.GW1", b"{not json"], activity, WALL)


def test_subscriptions_are_only_the_lifecycle_topics() -> None:
    assert not any(prefix.startswith("book") for prefix in SUBSCRIPTIONS)
    assert len(SUBSCRIPTIONS) == 6


class TestActivityEffects:
    def test_connect_sets_connected_since(self, activity: Activity) -> None:
        translate(make_gateway_auth(gateway_id="GW1", accepted=True), activity, WALL)
        p = activity.participants["GW1"]
        assert p.connected is True
        assert p.connected_since == "2025-10-09T08:53:20.000Z"
        translate(make_gateway_bye(gateway_id="GW1"), activity, WALL + 5)
        assert p.connected is False
        assert p.connected_since is None

    def test_session_state_is_tracked(self, activity: Activity) -> None:
        translate(
            make_session_state(state="PRE_OPEN", prev_state="CLOSED"), activity, WALL
        )
        assert activity.session_state == "PRE_OPEN"
        assert activity.session_opened_at == WALL


def test_the_collector_publishes_engine_events() -> None:
    """A real engine-bus PUB, through pm-monitor's SUB, out as health.event."""
    pull, pub, engine = free_ports(3)
    ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
    engine_pub: zmq.Socket[bytes] = ctx.socket(zmq.PUB)
    engine_pub.setsockopt(zmq.LINGER, 0)
    engine_pub.bind(f"tcp://127.0.0.1:{engine}")
    mon = Monitor(
        MonitorConfig(pull_port=pull, pub_port=pub),
        STOCKHOLM,
        engine_pub_addr=f"tcp://127.0.0.1:{engine}",
        host_sampler=QuietHost(),
    )
    sub: zmq.Socket[bytes] = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.LINGER, 0)
    sub.setsockopt(zmq.SUBSCRIBE, TOPIC_HEALTH_EVENT.encode())
    sub.connect(mon.config.pub_connect_addr)
    try:
        deadline = time.monotonic() + 5
        event = None
        while event is None and time.monotonic() < deadline:
            # resend until both slow joiners are connected
            engine_pub.send_multipart(
                make_gateway_bye(gateway_id="GW1", reason="heartbeat_timeout")
            )
            engine_pub.send_multipart([b"book.AAA", b"{}"])  # not subscribed
            time.sleep(0.05)
            mon.drain_engine()
            if sub.poll(50):
                event = parse_health_event(sub.recv_multipart())
        assert event is not None
        assert (event.kind, event.severity, event.subject, event.detail) == (
            "DISCONNECT",
            "WARN",
            "GW1",
            "heartbeat_timeout",
        )
        assert mon.engine_events_invalid == 0
    finally:
        sub.close()
        engine_pub.close()
        mon.close()


def test_a_malformed_engine_message_is_counted() -> None:
    pull, pub = free_ports(2)
    mon = Monitor(
        MonitorConfig(pull_port=pull, pub_port=pub), STOCKHOLM, host_sampler=QuietHost()
    )
    try:
        mon.receive_engine([b"system.gateway_bye.GW1", b"{not json"])
        assert (mon.engine_events_in, mon.engine_events_invalid) == (1, 1)
    finally:
        mon.close()

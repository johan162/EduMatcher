"""Engine lifecycle events from the engine bus (design §9.2).

pm-monitor subscribes to a handful of topic prefixes only -- the engine bus
carries every book snapshot and fill, and decoding those would be most of
pm-monitor's work for nothing. Each message becomes one ``health.event`` and
may update :class:`~edumatcher.monitor.activity.Activity` (connect times,
session state).

A subscription to ``session.state`` or ``system.diagnostic`` also delivers
any longer topic that starts with the same text, so those two are matched
exactly before parsing.
"""

from __future__ import annotations

from dataclasses import dataclass

from edumatcher.models.generated.circuit_breaker import (
    PREFIX_CIRCUIT_BREAKER_HALT,
    PREFIX_CIRCUIT_BREAKER_RESUME,
    parse_circuit_breaker_halt,
    parse_circuit_breaker_resume,
)
from edumatcher.models.generated.session import TOPIC_SESSION_STATE, parse_session_state
from edumatcher.models.generated.system import (
    PREFIX_GATEWAY_AUTH,
    PREFIX_GATEWAY_BYE,
    TOPIC_DIAGNOSTIC,
    parse_diagnostic,
    parse_gateway_auth,
    parse_gateway_bye,
)
from edumatcher.monitor.activity import Activity

#: The engine bus prefixes pm-monitor subscribes to, and nothing else.
SUBSCRIPTIONS: tuple[str, ...] = (
    PREFIX_GATEWAY_AUTH,
    PREFIX_GATEWAY_BYE,
    TOPIC_DIAGNOSTIC,
    TOPIC_SESSION_STATE,
    PREFIX_CIRCUIT_BREAKER_HALT,
    PREFIX_CIRCUIT_BREAKER_RESUME,
)

#: The disconnect reason the dashboard highlights (§9.2).
HEARTBEAT_TIMEOUT = "heartbeat_timeout"


@dataclass(frozen=True)
class EngineEvent:
    """What becomes one ``health.event``."""

    kind: str
    severity: str
    subject: str
    detail: str = ""


def _suffix(topic: str, prefix: str) -> str | None:
    """The parameter after a ``prefix.`` (a gateway id or a symbol, which may
    itself contain a dot); ``None`` when the topic does not have one."""
    if not topic.startswith(prefix):
        return None
    return topic[len(prefix) :] or None


def translate(
    frames: list[bytes], activity: Activity, now_wall: float
) -> EngineEvent | None:
    """One engine bus message as an event; ``None`` for a topic not ours.

    Raises on a malformed message of one of our topics (the caller counts it).
    """
    topic = frames[0].decode()
    if _suffix(topic, PREFIX_GATEWAY_AUTH) is not None:
        auth = parse_gateway_auth(frames)
        if auth.accepted:
            activity.connected_at(auth.gateway_id, now_wall)
            return EngineEvent("CONNECT", "INFO", auth.gateway_id, auth.description)
        return EngineEvent("AUTH_REJECT", "WARN", auth.gateway_id, auth.reason)
    if _suffix(topic, PREFIX_GATEWAY_BYE) is not None:
        bye = parse_gateway_bye(frames)
        activity.set_connected(bye.gateway_id, False, now_wall)
        severity = "WARN" if bye.reason == HEARTBEAT_TIMEOUT else "INFO"
        return EngineEvent("DISCONNECT", severity, bye.gateway_id, bye.reason)
    if topic == TOPIC_DIAGNOSTIC:
        diag = parse_diagnostic(frames)
        detail = f"{diag.detail} (x{diag.count})"
        if diag.error:
            detail += f": {diag.error}"
        return EngineEvent("DIAGNOSTIC", "WARN", diag.component, detail)
    if topic == TOPIC_SESSION_STATE:
        state = parse_session_state(frames)
        previous = state.prev_state or activity.session_state
        activity.set_session_state(state.state, now_wall, previous=previous)
        detail = f"{previous} -> {state.state}" if previous else state.state
        return EngineEvent("SESSION", "INFO", "session", detail)
    if _suffix(topic, PREFIX_CIRCUIT_BREAKER_HALT) is not None:
        halt = parse_circuit_breaker_halt(frames)
        parts = [p for p in (halt.level, halt.halt_source) if p]
        return EngineEvent("HALT", "WARN", halt.symbol, " ".join(parts))
    if _suffix(topic, PREFIX_CIRCUIT_BREAKER_RESUME) is not None:
        resume = parse_circuit_breaker_resume(frames)
        return EngineEvent("RESUME", "INFO", resume.symbol, resume.reason)
    return None

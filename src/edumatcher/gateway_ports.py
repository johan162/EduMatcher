"""Single source of truth for every TCP/ZeroMQ port the exchange binds.

Two consumers need the same table and must never disagree about it:

``cverifier.layer3_semantic``
    M018 reports two sections configured onto the same port.  It needs each
    section's *effective* port, i.e. the configured value or, when the key is
    omitted, the runtime default that section will actually bind.

``config_show``
    The port panel shows the same inventory to a human, including the engine
    and index sockets that appear nowhere in ``engine_config.yaml``.

Adding a gateway therefore means editing one table here, not two tables in
two packages that drift apart the first time someone forgets the second one.

The defaults below must match each gateway's own ``config.py``/loader; the
runtime loaders remain authoritative for a *running* process, and these
values only describe what those loaders fall back to.
"""

from __future__ import annotations

import os
from typing import Any, NamedTuple


class GatewaySpec(NamedTuple):
    """One optional, single-instance gateway section."""

    key: str  # top-level engine_config.yaml key
    process: str  # the pm-* executable that binds it
    default_port: int
    proto: str  # "TCP" | "ZMQ PUB" | "ZMQ PULL" | "HTTP"
    function: str  # short human description, for the viewer


class ExtraPortSpec(NamedTuple):
    """An additional listener bound by a section that binds more than one."""

    field: str  # the key inside that section
    default_port: int
    proto: str
    function: str


class FixedListener(NamedTuple):
    """A socket that is not configurable through engine_config.yaml."""

    port: int
    proto: str
    process: str
    function: str
    origin: str  # "fixed" (source constant) | "env" (environment variable)
    env_var: str | None = None


# ---------------------------------------------------------------------------
# Optional gateway sections, one listener each
# ---------------------------------------------------------------------------
SINGLETON_GATEWAYS: tuple[GatewaySpec, ...] = (
    GatewaySpec("alf_gateway", "pm-alf-gwy", 5565, "TCP", "ALF order gateway"),
    GatewaySpec("balf_gateway", "pm-balf-gwy", 5560, "TCP", "Binary ALF gateway"),
    GatewaySpec("market_data_gateway", "pm-md-gwy", 5570, "TCP", "Market data (MDLF)"),
    GatewaySpec("post_trade_gateway", "pm-ralf-gwy", 5580, "TCP", "Post-trade (RALF)"),
    GatewaySpec("dc_gateway", "pm-dc-gwy", 5590, "TCP", "Drop-copy (DCLF)"),
    GatewaySpec("log_server", "pm-log-srv", 5600, "TCP", "Log ingest (LALF)"),
)

# pm-log-srv is the one section that binds more than one listener: besides its
# LALF/TCP 'port' above, LALF-PS binds a ZeroMQ PUB and a ZeroMQ PULL socket.
# All three participate in the cross-section collision check — a pub_port that
# happens to equal pm-md-gwy's port is exactly as fatal as two TCP gateways
# sharing one, and far easier to overlook.
LOG_SERVER_EXTRA_PORTS: tuple[ExtraPortSpec, ...] = (
    ExtraPortSpec("pub_port", 5601, "ZMQ PUB", "Log broadcast (LALF-PS)"),
    ExtraPortSpec("pull_port", 5602, "ZMQ PULL", "Log control (LALF-PS)"),
)

# api_gateways is a named mapping of possibly-many instances, each with a port.
DEFAULT_API_GATEWAY_PORT = 8080

# ---------------------------------------------------------------------------
# Sockets bound outside the YAML entirely
# ---------------------------------------------------------------------------
# Mirrors the module-level constants in edumatcher/config.py. Ports are fixed
# source constants; the bind host for both the engine trio and the index pair
# is overridable via EDUMATCHER_ENGINE_BIND_HOST / EDUMATCHER_INDEX_BIND_HOST.
# Either way they are invisible in engine_config.yaml, which is exactly why a
# viewer must show them.
FIXED_LISTENERS: tuple[FixedListener, ...] = (
    FixedListener(5555, "ZMQ PULL", "pm-engine", "Order intake (CALF)", "fixed"),
    FixedListener(5556, "ZMQ PUB", "pm-engine", "Event + book feed", "fixed"),
    FixedListener(5557, "ZMQ PUB", "pm-engine", "Drop-copy feed", "fixed"),
    FixedListener(
        5558,
        "ZMQ PUB",
        "pm-index",
        "Index value publish",
        "env",
        "EDUMATCHER_INDEX_PUB_PORT",
    ),
    FixedListener(
        5559,
        "ZMQ PULL",
        "pm-index",
        "Index command intake",
        "env",
        "EDUMATCHER_INDEX_PULL_PORT",
    ),
)


def resolved_fixed_listeners() -> tuple[FixedListener, ...]:
    """``FIXED_LISTENERS`` with the environment overrides applied.

    The index ports honour ``EDUMATCHER_INDEX_PUB_PORT`` /
    ``EDUMATCHER_INDEX_PULL_PORT``; a non-integer value is ignored so the
    viewer shows the compiled-in default rather than crashing on a typo in
    someone's shell profile.
    """
    out: list[FixedListener] = []
    for listener in FIXED_LISTENERS:
        port = listener.port
        if listener.env_var:
            raw = os.environ.get(listener.env_var)
            if raw is not None:
                try:
                    port = int(raw)
                except ValueError:
                    port = listener.port
        out.append(listener._replace(port=port))
    return tuple(out)


def effective_port(
    section: dict[str, Any], default: int, key: str = "port"
) -> int | None:
    """Return the port ``section`` will bind, or ``None`` if it is malformed.

    A section present with no ``port:`` still binds, on ``default`` — which is
    why an omitted key must resolve to a number rather than being skipped.
    ``None`` means the value is not an integer; callers treat that as "already
    reported elsewhere" and ignore it.
    """
    port = section.get(key, default)
    if isinstance(port, bool) or not isinstance(port, int):
        return None
    return port

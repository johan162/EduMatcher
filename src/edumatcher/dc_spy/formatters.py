"""Rendering of drop-copy messages for pm-dc-spy.

Two output modes are supported, mirroring ``calf_spy.formatters``:

- ``human``: one colourised, aligned line per event, meant to be read live
  in a terminal (see :func:`format_human`).
- ``json``: one ``json.dumps`` object per line, meant to be piped into
  ``jq``, logged to a file, or otherwise consumed by another program (see
  :func:`format_json`).

Both formatters are pure functions over a decoded ``(topic, payload)`` pair
plus a receive timestamp -- no socket or session state -- so they are
trivially unit-testable in isolation from the network layer.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from edumatcher.dc_spy.client import REPLAY_TOPIC_PREFIX

# Fields already surfaced by dedicated columns; excluded from the trailing
# "KEY=VALUE ..." payload dump in human mode to avoid redundant repetition.
_ENVELOPE_FIELDS = frozenset(
    {
        "seq",
        "timestamp",
        "gateway_id",
        "event_type",
        "symbol",
        "fill_qty",
        "fill_price",
        "liquidity_flag",
    }
)

_LIQUIDITY_STYLE = {"MAKER": "bold blue", "TAKER": "bold magenta"}
_DEFAULT_LIQUIDITY_STYLE = "bold white"


def _local_clock() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def is_replay(topic: str) -> bool:
    return topic.startswith(REPLAY_TOPIC_PREFIX)


def format_human(topic: str, payload: dict[str, Any], *, raw: bool = False) -> str:
    """Render one drop-copy message as a single human-readable line.

    Uses ``rich`` markup tags (``[style]...[/style]``); the caller decides
    whether to render them (a ``rich.console.Console``) or strip them
    (plain ``print`` when colour is disabled / stdout is not a TTY).

    Layout::

        10:02:17.512  FILL     TRADER01   AAPL       #42     100@150.05 MAKER
        10:02:17.520  REPLAY   TRADER01   MSFT       #7      50@415.20 TAKER
    """
    clock = _local_clock()
    replay = is_replay(topic)
    label = "REPLAY" if replay else "FILL"
    style = "bold yellow" if replay else "bold green"

    event_type = payload.get("event_type", "")
    gateway_id = payload.get("gateway_id", "")
    symbol = payload.get("symbol", "")
    seq = payload.get("seq", "")
    fill_qty = payload.get("fill_qty")
    fill_price = payload.get("fill_price")
    liquidity = payload.get("liquidity_flag", "")
    liq_style = _LIQUIDITY_STYLE.get(liquidity, _DEFAULT_LIQUIDITY_STYLE)

    fill_str = ""
    if fill_qty is not None and fill_price is not None:
        fill_str = f"{fill_qty}@{fill_price}"

    rest = _format_payload(payload, exclude=_ENVELOPE_FIELDS)

    head = (
        f"[dim]{clock}[/dim]  "
        f"[{style}]{label:<8}[/{style}] "
        f"{gateway_id:<10} "
        f"{symbol:<10} "
        f"[dim]#{seq:<6}[/dim] "
        f"{fill_str:<16} "
        f"[{liq_style}]{liquidity}[/{liq_style}]"
    )
    if event_type and event_type != "order.fill":
        head += f" TYPE={event_type}"
    line = f"{head} {rest}".rstrip()

    if raw:
        line += f"\n  [dim]{topic}|{json.dumps(payload, sort_keys=True)}[/dim]"
    return line


def _format_payload(payload: dict[str, Any], *, exclude: frozenset[str]) -> str:
    """Render the remaining KEY=VALUE fields, sorted for stable output."""
    return " ".join(
        f"{key}={value}" for key, value in sorted(payload.items()) if key not in exclude
    )


def format_json(topic: str, payload: dict[str, Any], *, recv_ts: float) -> str:
    """Render one drop-copy message as a single JSON line.

    The envelope fields (``seq``/``gateway_id``/``symbol``) are already
    top-level keys in the drop-copy payload; ``topic`` and ``recv_ts`` and a
    derived ``replay`` flag are added so a consumer can distinguish live vs.
    replay traffic without re-parsing the topic string.
    """
    record = {
        "recv_ts": recv_ts,
        "topic": topic,
        "replay": is_replay(topic),
        **payload,
    }
    return json.dumps(record, sort_keys=False)


__all__ = ["format_human", "format_json", "is_replay"]

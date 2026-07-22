"""Rendering of parsed RALF frames for pm-ralf-spy.

Two output modes are supported:

- ``human``: one colourised, aligned line per event, meant to be read live
  in a terminal (see :func:`format_human`).
- ``json``: one ``json.dumps`` object per line, meant to be piped into
  ``jq``, logged to a file, or otherwise consumed by another program (see
  :func:`format_json`).

Both formatters are pure functions over a parsed :class:`RalfFrame` plus a
receive timestamp -- no socket or session state -- so they are trivially
unit-testable in isolation from the network layer.
"""

from __future__ import annotations

import json
from collections.abc import Set as AbstractSet
from datetime import datetime

from edumatcher.ralf_gateway.protocol import RalfFrame

# Channel -> rich style used for the channel badge in human mode.
_CHANNEL_STYLE: dict[str, str] = {
    "CLEARING": "bold cyan",
    "DROP_COPY": "bold green",
    "AUDIT": "bold magenta",
}
_DEFAULT_CHANNEL_STYLE = "bold white"

# Message types that carry no CH/SYM/SEQ envelope (session-level, not
# stream-level) and are rendered with a distinct, de-emphasised layout.
_SESSION_MSG_TYPES = frozenset({"WELCOME", "HB", "PONG", "ERR", "EXIT"})

# Fields already surfaced by dedicated columns; excluded from the trailing
# "KEY=VALUE ..." payload dump in human mode to avoid redundant repetition.
_ENVELOPE_FIELDS = frozenset({"CH", "SYM", "SEQ", "TS"})


def channel_style(channel: str) -> str:
    """Return the rich style string used for one channel's badge."""
    return _CHANNEL_STYLE.get(channel, _DEFAULT_CHANNEL_STYLE)


def _local_clock() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def format_human(frame: RalfFrame, *, raw_line: str | None = None) -> str:
    """Render one RALF frame as a single human-readable line.

    Uses ``rich`` markup tags (``[style]...[/style]``); the caller decides
    whether to render them (a ``rich.console.Console``) or strip them
    (plain ``print`` when colour is disabled / stdout is not a TTY).

    Layout for a stream event (has CH/SYM/SEQ)::

        10:02:17.123  EXEC    CLEARING AAPL    #4   PX=150.10 QTY=200 ...

    Layout for a session-level message (WELCOME/HB/PONG/ERR/EXIT), which has
    no channel/symbol of its own::

        10:02:17.123  WELCOME          GW=ralf-gwy01 ROLE=AUDIT ...
    """
    clock = _local_clock()
    msg_type = frame.msg_type
    fields = frame.fields

    if msg_type == "ERR":
        code = fields.get("CODE", "?")
        rest = _format_payload(fields, exclude={"CODE"})
        head = f"[dim]{clock}[/dim]  [bold red]{msg_type:<8}[/bold red] [bold red]{code}[/bold red]"
        line = f"{head}  {rest}".rstrip()
    elif msg_type in _SESSION_MSG_TYPES:
        style = "bold white" if msg_type == "WELCOME" else "dim"
        rest = _format_payload(fields, exclude=set())
        head = f"[dim]{clock}[/dim]  [{style}]{msg_type:<8}[/{style}]"
        line = f"{head}  {rest}".rstrip()
    else:
        ch = fields.get("CH", "")
        sym = fields.get("SYM", "")
        seq = fields.get("SEQ", "")
        style = channel_style(ch)
        rest = _format_payload(fields, exclude=_ENVELOPE_FIELDS)
        line = (
            f"[dim]{clock}[/dim]  "
            f"[{style}]{msg_type:<8}[/{style}] "
            f"[{style}]{ch:<10}[/{style}] "
            f"{sym:<10} "
            f"[dim]#{seq:<6}[/dim] "
            f"{rest}"
        ).rstrip()

    if raw_line is not None:
        line += f"\n  [dim]{raw_line}[/dim]"
    return line


def _format_payload(fields: dict[str, str], *, exclude: AbstractSet[str]) -> str:
    """Render the remaining KEY=VALUE fields, sorted for stable output."""
    return " ".join(
        f"{key}={value}" for key, value in sorted(fields.items()) if key not in exclude
    )


def format_json(frame: RalfFrame, *, recv_ts: float) -> str:
    """Render one RALF frame as a single JSON line.

    The envelope fields (``CH``/``SYM``/``SEQ``) are lifted to top-level
    keys for easy ``jq`` filtering (e.g. ``jq 'select(.ch=="CLEARING")'``);
    every field -- including the envelope ones -- is also kept verbatim
    under ``fields`` so no information is lost relative to the raw wire
    line.
    """
    fields = frame.fields
    record = {
        "recv_ts": recv_ts,
        "msg_type": frame.msg_type,
        "ch": fields.get("CH"),
        "sym": fields.get("SYM"),
        "seq": _maybe_int(fields.get("SEQ")),
        "ts": fields.get("TS"),
        "fields": fields,
    }
    return json.dumps(record, sort_keys=False)


def _maybe_int(value: str | None) -> int | str | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return value

"""CALF protocol parsing and line-building helpers.

The CALF gateway uses a newline-delimited UTF-8 text protocol where each line
looks like:

    MSGTYPE|KEY=VALUE|KEY=VALUE\n
This module contains only protocol-level helpers and deliberately avoids any
socket or gateway state logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


class CalfProtocolError(ValueError):
    """Raised when a CALF line fails protocol validation."""


@dataclass(frozen=True)
class CalfFrame:
    """Parsed CALF frame.

    Attributes
    ----------
    msg_type:
        First token of the line, for example ``HELLO`` or ``TRADE``.
    fields:
        Parsed key/value pairs where duplicate keys resolve by last-value-wins.
    """

    msg_type: str
    fields: dict[str, str]


_ALLOWED_MSGTYPE_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def iso_utc(ts_seconds: float) -> str:
    """Format Unix-seconds timestamp as UTC ISO-8601 with milliseconds."""
    dt = datetime.fromtimestamp(ts_seconds, tz=UTC)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_line(line: str) -> CalfFrame:
    """Parse a CALF line into ``CalfFrame``.

    Notes
    -----
    - Empty lines are invalid
    - ``MSGTYPE`` must be uppercase token chars
    - Duplicate keys are accepted and resolved with last-value-wins semantics
    - Field-level whitespace is preserved in values (gateway decides semantics)
    """
    raw = line.strip("\r\n")
    if not raw:
        raise CalfProtocolError("empty line")

    parts = raw.split("|")
    msg_type = parts[0]
    if not msg_type or any(ch not in _ALLOWED_MSGTYPE_CHARS for ch in msg_type):
        raise CalfProtocolError(f"invalid MSGTYPE: {msg_type!r}")

    fields: dict[str, str] = {}
    for token in parts[1:]:
        if "=" not in token:
            raise CalfProtocolError(f"invalid field token: {token!r}")
        key, value = token.split("=", 1)
        if not key:
            raise CalfProtocolError("empty field key")
        fields[key] = value

    return CalfFrame(msg_type=msg_type, fields=fields)


def build_line(msg_type: str, fields: dict[str, str] | None = None) -> bytes:
    """Build one UTF-8 encoded CALF line with trailing newline."""
    if not msg_type or any(ch not in _ALLOWED_MSGTYPE_CHARS for ch in msg_type):
        raise CalfProtocolError(f"invalid MSGTYPE: {msg_type!r}")

    tokens = [msg_type]
    if fields:
        for key, value in fields.items():
            if not key:
                raise CalfProtocolError("empty field key")
            if "|" in key or "|" in value:
                raise CalfProtocolError("'|' not allowed in key/value")
            tokens.append(f"{key}={value}")
    return ("|".join(tokens) + "\n").encode("utf-8")

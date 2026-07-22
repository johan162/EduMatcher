"""DC1 line protocol parsing and formatting helpers.

DC1 is deliberately the simplest of EduMatcher's TCP protocols: unlike RALF
(role-gated channels, replay-by-sequence) or CALF (channel/symbol
subscription grammar), the drop-copy feed has exactly one thing a client can
ask for -- "give me fills for gateway ID X" -- so the wire grammar is just
HELLO/WELCOME plus unsolicited DC_FILL/HB lines. See
docs/user-guide/201-dc-gateway.md for the full protocol reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


class DcProtocolError(ValueError):
    """Raised when a DC1 line cannot be parsed or validated."""


@dataclass(frozen=True)
class DcFrame:
    """One parsed DC1 frame."""

    msg_type: str
    fields: dict[str, str]


_ALLOWED_MSGTYPE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def iso_utc(ts_seconds: float) -> str:
    """Format a Unix-seconds timestamp to UTC ISO-8601 with milliseconds."""
    dt = datetime.fromtimestamp(ts_seconds, tz=UTC)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_line(line: str) -> DcFrame:
    """Parse a DC1 line of form MSGTYPE|KEY=VALUE|..."""
    raw = line.strip("\r\n")
    if not raw:
        raise DcProtocolError("empty line")

    parts = raw.split("|")
    msg_type = parts[0]
    if not msg_type or any(ch not in _ALLOWED_MSGTYPE for ch in msg_type):
        raise DcProtocolError(f"invalid MSGTYPE: {msg_type!r}")

    fields: dict[str, str] = {}
    for token in parts[1:]:
        if "=" not in token:
            raise DcProtocolError(f"invalid field token: {token!r}")
        key, value = token.split("=", 1)
        if not key:
            raise DcProtocolError("empty field key")
        fields[key] = value

    return DcFrame(msg_type=msg_type, fields=fields)


def build_line(msg_type: str, fields: dict[str, str] | None = None) -> bytes:
    """Build one encoded DC1 line terminated by newline."""
    if not msg_type or any(ch not in _ALLOWED_MSGTYPE for ch in msg_type):
        raise DcProtocolError(f"invalid MSGTYPE: {msg_type!r}")

    tokens = [msg_type]
    if fields:
        for key, value in fields.items():
            if not key:
                raise DcProtocolError("empty field key")
            if "|" in key or "|" in value:
                raise DcProtocolError("'|' not allowed in key/value")
            tokens.append(f"{key}={value}")
    return ("|".join(tokens) + "\n").encode("utf-8")

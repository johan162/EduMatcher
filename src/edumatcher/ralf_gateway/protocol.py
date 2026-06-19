"""RALF line protocol parsing and formatting helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


class RalfProtocolError(ValueError):
    """Raised when a RALF line cannot be parsed or validated."""


@dataclass(frozen=True)
class RalfFrame:
    """One parsed RALF frame."""

    msg_type: str
    fields: dict[str, str]


_ALLOWED_MSGTYPE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def iso_utc(ts_seconds: float) -> str:
    """Format a Unix-seconds timestamp to UTC ISO-8601 with milliseconds."""
    dt = datetime.fromtimestamp(ts_seconds, tz=UTC)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_line(line: str) -> RalfFrame:
    """Parse a RALF line of form MSGTYPE|KEY=VALUE|..."""
    raw = line.strip("\r\n")
    if not raw:
        raise RalfProtocolError("empty line")

    parts = raw.split("|")
    msg_type = parts[0]
    if not msg_type or any(ch not in _ALLOWED_MSGTYPE for ch in msg_type):
        raise RalfProtocolError(f"invalid MSGTYPE: {msg_type!r}")

    fields: dict[str, str] = {}
    for token in parts[1:]:
        if "=" not in token:
            raise RalfProtocolError(f"invalid field token: {token!r}")
        key, value = token.split("=", 1)
        if not key:
            raise RalfProtocolError("empty field key")
        fields[key] = value

    return RalfFrame(msg_type=msg_type, fields=fields)


def build_line(msg_type: str, fields: dict[str, str] | None = None) -> bytes:
    """Build one encoded RALF line terminated by newline."""
    if not msg_type or any(ch not in _ALLOWED_MSGTYPE for ch in msg_type):
        raise RalfProtocolError(f"invalid MSGTYPE: {msg_type!r}")

    tokens = [msg_type]
    if fields:
        for key, value in fields.items():
            if not key:
                raise RalfProtocolError("empty field key")
            if "|" in key or "|" in value:
                raise RalfProtocolError("'|' not allowed in key/value")
            tokens.append(f"{key}={value}")
    return ("|".join(tokens) + "\n").encode("utf-8")

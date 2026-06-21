"""CALF line parser/serializer library.

Message format:
    MSGTYPE|KEY=VALUE|KEY=VALUE\n
This parser is intentionally strict for protocol examples while still small.
"""

from __future__ import annotations

from dataclasses import dataclass


class CalfParseError(ValueError):
    """Raised when a CALF message cannot be parsed."""


@dataclass(frozen=True)
class CalfMessage:
    msg_type: str
    fields: dict[str, str]


ALLOWED_MSGTYPE_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def _is_valid_msg_type(msg_type: str) -> bool:
    return bool(msg_type) and all(ch in ALLOWED_MSGTYPE_CHARS for ch in msg_type)


def parse_calf_line(line: str) -> CalfMessage:
    """Parse one CALF line into a message object.

    The input may include trailing newlines; they are stripped.
    """
    raw = line.rstrip("\r\n")
    if not raw:
        raise CalfParseError("empty line")

    parts = raw.split("|")
    msg_type = parts[0]
    if not _is_valid_msg_type(msg_type):
        raise CalfParseError(f"invalid MSGTYPE: {msg_type!r}")

    fields: dict[str, str] = {}
    for token in parts[1:]:
        if "=" not in token:
            raise CalfParseError(f"field is missing '=': {token!r}")
        key, value = token.split("=", 1)
        if not key:
            raise CalfParseError("empty field name")
        if "|" in key or "|" in value:
            raise CalfParseError("'|' is not allowed inside field key/value")
        fields[key] = value

    return CalfMessage(msg_type=msg_type, fields=fields)


def build_calf_line(msg_type: str, fields: dict[str, str] | None = None) -> str:
    """Build one CALF protocol line terminated by '\n'."""
    if not _is_valid_msg_type(msg_type):
        raise CalfParseError(f"invalid MSGTYPE: {msg_type!r}")

    tokens = [msg_type]
    for key, value in (fields or {}).items():
        if not key:
            raise CalfParseError("empty field name")
        if "|" in key or "|" in value:
            raise CalfParseError("'|' is not allowed inside field key/value")
        tokens.append(f"{key}={value}")
    return "|".join(tokens) + "\n"

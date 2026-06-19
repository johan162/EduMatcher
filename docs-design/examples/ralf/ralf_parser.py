"""RALF line parser/serializer library.

Message format:
    MSGTYPE|KEY=VALUE|KEY=VALUE\n
The parser is strict enough for protocol work but lightweight for examples.
"""

from __future__ import annotations

from dataclasses import dataclass


class RalfParseError(ValueError):
    """Raised when a RALF message cannot be parsed."""


@dataclass(frozen=True)
class RalfMessage:
    msg_type: str
    fields: dict[str, str]


ALLOWED_MSGTYPE_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def _is_valid_msg_type(msg_type: str) -> bool:
    return bool(msg_type) and all(ch in ALLOWED_MSGTYPE_CHARS for ch in msg_type)


def parse_ralf_line(line: str) -> RalfMessage:
    """Parse one RALF line into a message object.

    The input may include trailing newlines; they are stripped.
    """
    raw = line.rstrip("\r\n")
    if not raw:
        raise RalfParseError("empty line")

    parts = raw.split("|")
    msg_type = parts[0]
    if not _is_valid_msg_type(msg_type):
        raise RalfParseError(f"invalid MSGTYPE: {msg_type!r}")

    fields: dict[str, str] = {}
    for token in parts[1:]:
        if "=" not in token:
            raise RalfParseError(f"field is missing '=': {token!r}")
        key, value = token.split("=", 1)
        if not key:
            raise RalfParseError("empty field name")
        if "|" in key or "|" in value:
            raise RalfParseError("'|' is not allowed inside field key/value")
        fields[key] = value

    return RalfMessage(msg_type=msg_type, fields=fields)


def build_ralf_line(msg_type: str, fields: dict[str, str] | None = None) -> str:
    """Build one RALF protocol line terminated by '\n'."""
    if not _is_valid_msg_type(msg_type):
        raise RalfParseError(f"invalid MSGTYPE: {msg_type!r}")

    tokens = [msg_type]
    for key, value in (fields or {}).items():
        if not key:
            raise RalfParseError("empty field name")
        if "|" in key or "|" in value:
            raise RalfParseError("'|' is not allowed inside field key/value")
        tokens.append(f"{key}={value}")
    return "|".join(tokens) + "\n"

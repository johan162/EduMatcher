"""DC1 line parser/serializer library.

Message format:
    MSGTYPE|KEY=VALUE|KEY=VALUE\n
The parser is strict enough for protocol work but lightweight for examples.
"""

from __future__ import annotations

from dataclasses import dataclass


class DcParseError(ValueError):
    """Raised when a DC1 message cannot be parsed."""


@dataclass(frozen=True)
class DcMessage:
    msg_type: str
    fields: dict[str, str]


ALLOWED_MSGTYPE_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def _is_valid_msg_type(msg_type: str) -> bool:
    return bool(msg_type) and all(ch in ALLOWED_MSGTYPE_CHARS for ch in msg_type)


def parse_dc_line(line: str) -> DcMessage:
    """Parse one DC1 line into a message object.

    The input may include trailing newlines; they are stripped.
    """
    raw = line.rstrip("\r\n")
    if not raw:
        raise DcParseError("empty line")

    parts = raw.split("|")
    msg_type = parts[0]
    if not _is_valid_msg_type(msg_type):
        raise DcParseError(f"invalid MSGTYPE: {msg_type!r}")

    fields: dict[str, str] = {}
    for token in parts[1:]:
        if "=" not in token:
            raise DcParseError(f"field is missing '=': {token!r}")
        key, value = token.split("=", 1)
        if not key:
            raise DcParseError("empty field name")
        if "|" in key or "|" in value:
            raise DcParseError("'|' is not allowed inside field key/value")
        fields[key] = value

    return DcMessage(msg_type=msg_type, fields=fields)


def build_dc_line(msg_type: str, fields: dict[str, str] | None = None) -> str:
    """Build one DC1 protocol line terminated by '\n'."""
    if not _is_valid_msg_type(msg_type):
        raise DcParseError(f"invalid MSGTYPE: {msg_type!r}")

    tokens = [msg_type]
    for key, value in (fields or {}).items():
        if not key:
            raise DcParseError("empty field name")
        if "|" in key or "|" in value:
            raise DcParseError("'|' is not allowed inside field key/value")
        tokens.append(f"{key}={value}")
    return "|".join(tokens) + "\n"

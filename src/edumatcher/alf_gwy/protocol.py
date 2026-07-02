"""ALF TCP gateway protocol parsing and line construction helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime


class AlfProtocolError(ValueError):
    """Raised when an ALF line cannot be parsed."""


class ValidationError(ValueError):
    """Raised for command validation problems with a stable error code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class AlfFrame:
    """One parsed ALF frame."""

    command: str
    fields: dict[str, str]


_ALLOWED_COMMAND_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
_MAX_CLIENT_NAME_LEN = 32


def iso_utc(ts_seconds: float) -> str:
    """Format Unix timestamp as UTC ISO-8601 with milliseconds."""
    dt = datetime.fromtimestamp(ts_seconds, tz=UTC)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_alf_line(raw_line: str) -> AlfFrame:
    """Parse one ALF line into ``(command, fields)``.

    Parsing rules intentionally match ``pm-alf-console`` behavior:
    - Strip full-line whitespace
    - Split on '|'
    - Command token and field names are uppercased
    - Duplicate keys resolve last-value-wins
    - Tokens without '=' are ignored
    """
    line = raw_line.strip()
    if not line:
        raise AlfProtocolError("empty line")

    segments = line.split("|")
    command = segments[0].strip().upper()
    if not command or any(ch not in _ALLOWED_COMMAND_CHARS for ch in command):
        raise AlfProtocolError(f"invalid command {command!r}")

    fields: dict[str, str] = {}
    for seg in segments[1:]:
        if "=" not in seg:
            continue
        key, _, value = seg.partition("=")
        key_u = key.strip().upper()
        if not key_u:
            continue
        fields[key_u] = value.strip().upper()

    return AlfFrame(command=command, fields=fields)


def build_line(msg_type: str, fields: dict[str, str] | None = None) -> bytes:
    """Build one ALF line terminated by newline."""
    msg = msg_type.strip().upper()
    if not msg or any(ch not in _ALLOWED_COMMAND_CHARS for ch in msg):
        raise AlfProtocolError(f"invalid message type {msg_type!r}")

    tokens = [msg]
    if fields:
        for key, value in fields.items():
            clean_key = key.strip().upper()
            if not clean_key:
                raise AlfProtocolError("empty field key")
            clean_value = str(value).replace("\r", " ").replace("\n", " ")
            if "|" in clean_key or "|" in clean_value:
                raise AlfProtocolError("'|' not allowed in field key/value")
            tokens.append(f"{clean_key}={clean_value}")
    return ("|".join(tokens) + "\n").encode("utf-8")


def safe_int(value: str, field_name: str, *, min_value: int | None = None) -> int:
    """Parse a bounded integer with clear validation errors."""
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValidationError(
            "INVALID_VALUE", f"{field_name}: invalid integer '{value}'"
        ) from exc

    if abs(result) > 2_147_483_647:
        raise ValidationError(
            "INVALID_VALUE", f"{field_name}: integer out of range '{value}'"
        )

    if min_value is not None and result < min_value:
        raise ValidationError("INVALID_VALUE", f"{field_name}: must be >= {min_value}")
    return result


def safe_float(value: str, field_name: str) -> float:
    """Parse a finite float and reject NaN/Inf."""
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValidationError(
            "INVALID_VALUE", f"{field_name}: invalid number '{value}'"
        ) from exc

    if math.isnan(result) or math.isinf(result):
        raise ValidationError("INVALID_VALUE", f"{field_name}: NaN/Inf not allowed")
    return result


def validate_hello_fields(fields: dict[str, str]) -> tuple[str, str, str]:
    """Validate mandatory HELLO fields and return (client, proto, gateway_id)."""
    client = fields.get("CLIENT", "").strip()
    proto = fields.get("PROTO", "").strip().upper()
    gateway_id = fields.get("ID", "").strip().upper()

    if not client:
        raise ValidationError("MISSING_FIELD", "CLIENT is required")
    if len(client) > _MAX_CLIENT_NAME_LEN:
        raise ValidationError("INVALID_VALUE", "CLIENT exceeds 32 chars")
    if proto != "ALF1":
        raise ValidationError("PROTO_MISMATCH", "PROTO must be ALF1")
    if not gateway_id:
        raise ValidationError("MISSING_FIELD", "ID is required")

    return client, proto, gateway_id

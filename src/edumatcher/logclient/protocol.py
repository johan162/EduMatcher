"""LALF (Logging ALF) wire protocol parsing and line-building helpers.

LALF is the newline-delimited, ``KEY=VALUE``-framed TCP protocol used
between any ``pm-*`` process and ``pm-log-srv`` (docs-design/EduMatcher-log-srv.md
§5, normative reference §15). Every LALF message starts with a header line

    <MSGTYPE>|KEY=VALUE|KEY=VALUE|...\\n

parsed exactly like CALF's own grammar (see
``edumatcher.md_gateway.protocol``, which this module deliberately mirrors
in shape). Unlike CALF, one message type — ``LOG`` — carries an
arbitrary-text payload that cannot safely be squeezed into the pipe-delimited
grammar (a log message may itself contain ``|``, embedded newlines, or any
Unicode). LALF solves this the same way CALF never had to: the header line's
final field is ``LEN=<n>``, and exactly ``n`` further raw UTF-8 bytes
immediately follow the header line's own terminating ``\\n`` — never scanned
for a delimiter, so they may contain anything (§15.4's normative wire
format).

This module contains only protocol-level helpers (parsing/building frames)
and deliberately avoids any socket or server state logic, exactly like
``md_gateway/protocol.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROTO_VERSION = "LALF1"
MAX_HEADER_LINE_BYTES = 4096  # including the terminating \n — same ceiling as CALF
DEFAULT_MAX_MESSAGE_BYTES = 65536  # LOG payload ceiling before truncation (§15.7)
HELLO_TIMEOUT_SEC = 5

# Message types that carry a LEN-prefixed payload after their header line.
# Only LOG does in this revision (§5.2, §15.4) — every other message type is
# header-only and has no payload to read.
_PAYLOAD_MSG_TYPES = frozenset({"LOG"})

_ALLOWED_MSGTYPE_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")

_VALID_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

# §15.9 ERR codes
ERR_INVALID_LEVEL = "INVALID_LEVEL"
ERR_MISSING_FIELD = "MISSING_FIELD"
ERR_PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
ERR_PROTO_MISMATCH = "PROTO_MISMATCH"
ERR_HELLO_TIMEOUT = "HELLO_TIMEOUT"
ERR_BAD_MESSAGE = "BAD_MESSAGE"


class LalfProtocolError(ValueError):
    """Raised when a LALF line or frame fails protocol validation."""


@dataclass(frozen=True)
class LalfFrame:
    """One parsed LALF header line, plus its payload bytes if any.

    Attributes
    ----------
    msg_type:
        First token of the header line, e.g. ``HELLO`` or ``LOG``.
    fields:
        Parsed ``KEY=VALUE`` pairs; duplicate keys resolve last-value-wins,
        matching CALF's own parser semantics.
    payload:
        Raw payload bytes for message types that carry one (``LOG``,
        identified by a ``LEN`` field); ``None`` for header-only messages.
    """

    msg_type: str
    fields: dict[str, str]
    payload: bytes | None = None


def iso_utc(ts_seconds: float) -> str:
    """Format Unix-seconds timestamp as UTC ISO-8601 with milliseconds."""
    dt = datetime.fromtimestamp(ts_seconds, tz=UTC)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_header_line(line: str) -> tuple[str, dict[str, str]]:
    """Parse one LALF header line into ``(msg_type, fields)``.

    Mirrors ``md_gateway.protocol.parse_line`` exactly: the same MSGTYPE
    token rules, the same last-value-wins duplicate-key handling, and the
    same rejection of malformed ``KEY=VALUE`` tokens. This function only
    parses the header line itself — it never looks at or reads a payload;
    callers use the returned ``fields["LEN"]`` (when present) to know how
    many further bytes to read (§15.4).
    """
    raw = line.strip("\r\n")
    if not raw:
        raise LalfProtocolError("empty line")

    parts = raw.split("|")
    msg_type = parts[0]
    if not msg_type or any(ch not in _ALLOWED_MSGTYPE_CHARS for ch in msg_type):
        raise LalfProtocolError(f"invalid MSGTYPE: {msg_type!r}")

    fields: dict[str, str] = {}
    for token in parts[1:]:
        if "=" not in token:
            raise LalfProtocolError(f"invalid field token: {token!r}")
        key, value = token.split("=", 1)
        if not key:
            raise LalfProtocolError("empty field key")
        fields[key] = value

    return msg_type, fields


def build_header_line(msg_type: str, fields: dict[str, str] | None = None) -> bytes:
    """Build one UTF-8 encoded LALF header line with a trailing newline.

    Note this does *not* append any payload bytes — callers that are
    building a ``LOG`` frame must append the raw payload themselves,
    immediately after this line's bytes, with no extra separator (§15.4).
    """
    if not msg_type or any(ch not in _ALLOWED_MSGTYPE_CHARS for ch in msg_type):
        raise LalfProtocolError(f"invalid MSGTYPE: {msg_type!r}")

    tokens = [msg_type]
    if fields:
        for key, value in fields.items():
            if not key:
                raise LalfProtocolError("empty field key")
            if "|" in key or "|" in value or "\n" in key or "\n" in value:
                raise LalfProtocolError(
                    "'|' and newline not allowed in header key/value"
                )
            tokens.append(f"{key}={value}")
    return ("|".join(tokens) + "\n").encode("utf-8")


def build_log_frame(
    *,
    seq: int,
    ts: str,
    level: str,
    logger: str,
    message: str,
    module: str | None = None,
    line: int | None = None,
    has_exception: bool = False,
    max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
) -> bytes:
    """Build a complete ``LOG`` frame: header line + LEN-prefixed payload.

    Truncates ``message`` to ``max_message_bytes`` (by UTF-8 byte length,
    never splitting a multi-byte codepoint) rather than raising — mirrors
    the server-side truncate-not-reject behavior in §15.7/§15.9's
    ``PAYLOAD_TOO_LARGE`` handling, so a client that wants to pre-truncate
    before sending (rather than relying on the server to do it) gets the
    identical outcome. Returns the truncation flag alongside the encoded
    bytes so a caller (e.g. ``TcpLogHandler`` in phase 2) can act on it;
    this function itself has no side effects.
    """
    if level not in _VALID_LEVELS:
        raise LalfProtocolError(f"invalid LEVEL: {level!r}")

    payload = _truncate_utf8(message, max_message_bytes)

    fields: dict[str, str] = {
        "SEQ": str(seq),
        "TS": ts,
        "LEVEL": level,
        "LOGGER": logger,
    }
    if module is not None:
        fields["MODULE"] = module
    if line is not None:
        fields["LINE"] = str(line)
    if has_exception:
        fields["EXC"] = "1"
    fields["LEN"] = str(len(payload))

    header = build_header_line("LOG", fields)
    return header + payload


def _truncate_utf8(text: str, max_bytes: int) -> bytes:
    """Encode ``text`` as UTF-8, truncating to at most ``max_bytes`` bytes.

    Truncation never splits a multi-byte UTF-8 codepoint — it walks back
    from the naive byte cut until the tail decodes cleanly, so the result
    is always valid UTF-8, just possibly shorter than the naive slice.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return encoded
    cut = encoded[:max_bytes]
    # Walk back until this is valid UTF-8 on its own (handles the case
    # where the cut lands in the middle of a multi-byte sequence).
    while cut:
        try:
            cut.decode("utf-8")
            return cut
        except UnicodeDecodeError:
            cut = cut[:-1]
    return b""


def validate_log_fields(fields: dict[str, str]) -> str | None:
    """Validate a parsed ``LOG`` frame's header fields.

    Returns an LALF ``ERR`` code (``INVALID_LEVEL``/``MISSING_FIELD``) on
    failure, or ``None`` if the fields are valid (§15.7, §15.9). Does not
    validate ``LEN`` itself — that is checked by the frame reader, since it
    determines how many payload bytes to consume before this function is
    even reachable.
    """
    for required in ("SEQ", "TS", "LEVEL", "LOGGER", "LEN"):
        if required not in fields:
            return ERR_MISSING_FIELD
    if fields["LEVEL"] not in _VALID_LEVELS:
        return ERR_INVALID_LEVEL
    return None


def payload_len(fields: dict[str, str]) -> int | None:
    """Return the declared payload length for a header line, or ``None``.

    Only message types with a ``LEN`` field carry a payload (currently only
    ``LOG``, §15.4) — every other message type is header-only.
    """
    raw = fields.get("LEN")
    if raw is None:
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError) as exc:
        raise LalfProtocolError(f"invalid LEN: {raw!r}") from exc
    if n < 0:
        raise LalfProtocolError(f"invalid LEN: {raw!r}")
    return n


def has_payload(msg_type: str) -> bool:
    """Whether ``msg_type`` is expected to carry a LEN-prefixed payload."""
    return msg_type in _PAYLOAD_MSG_TYPES


# ---------------------------------------------------------------------------
# Incremental frame reader
# ---------------------------------------------------------------------------


class FrameReader:
    """Incrementally reassembles LALF frames from a byte stream.

    TCP has no message boundaries below LALF's own framing (§15.4's "TCP
    stream requirement") — a single ``recv()`` may deliver a partial header
    line, a whole frame, several frames, or a header line with only part of
    its payload. This class is the buffering/re-framing logic every reader
    (the server's per-connection loop, a test harness, a future non-Python
    client's Python test double) needs, factored out so it is written and
    tested exactly once rather than once per caller.

    Usage: call :meth:`feed` with newly received bytes, then repeatedly
    call :meth:`next_frame` until it returns ``None`` (meaning: not enough
    bytes buffered yet for a complete frame).
    """

    def __init__(self, *, max_header_line_bytes: int = MAX_HEADER_LINE_BYTES) -> None:
        self._buf = bytearray()
        self._max_header_line_bytes = max_header_line_bytes
        # State for a header line that has been parsed but whose payload
        # bytes have not all arrived yet.
        self._pending_msg_type: str | None = None
        self._pending_fields: dict[str, str] | None = None
        self._pending_len: int | None = None

    def feed(self, data: bytes) -> None:
        self._buf.extend(data)

    def __len__(self) -> int:
        return len(self._buf)

    def next_frame(self) -> LalfFrame | None:
        """Return the next complete frame, or ``None`` if not enough data yet.

        Raises ``LalfProtocolError`` for a malformed header line or an
        oversized header line (mirrors ``md_gateway/gateway.py``'s own
        4096-byte defensive framing guard, §15.3).
        """
        # Resume a header line whose payload we were already waiting on.
        if self._pending_msg_type is not None:
            assert self._pending_fields is not None
            assert self._pending_len is not None
            if len(self._buf) < self._pending_len:
                return None
            payload = bytes(self._buf[: self._pending_len])
            del self._buf[: self._pending_len]
            frame = LalfFrame(
                msg_type=self._pending_msg_type,
                fields=self._pending_fields,
                payload=payload,
            )
            self._pending_msg_type = None
            self._pending_fields = None
            self._pending_len = None
            return frame

        idx = self._buf.find(b"\n")
        if idx < 0:
            if len(self._buf) > self._max_header_line_bytes:
                raise LalfProtocolError(
                    f"header line exceeds {self._max_header_line_bytes} bytes"
                )
            return None

        raw = bytes(self._buf[:idx])
        if len(raw) + 1 > self._max_header_line_bytes:
            del self._buf[: idx + 1]
            raise LalfProtocolError(
                f"header line exceeds {self._max_header_line_bytes} bytes"
            )

        line = raw.decode("utf-8", errors="replace")
        msg_type, fields = parse_header_line(line)
        del self._buf[: idx + 1]

        n = payload_len(fields)
        if n is None:
            return LalfFrame(msg_type=msg_type, fields=fields, payload=None)

        if len(self._buf) < n:
            # Not enough payload bytes yet — remember this header line and
            # wait for the next feed().
            self._pending_msg_type = msg_type
            self._pending_fields = fields
            self._pending_len = n
            return None

        payload = bytes(self._buf[:n])
        del self._buf[:n]
        return LalfFrame(msg_type=msg_type, fields=fields, payload=payload)

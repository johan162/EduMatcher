"""ALF protocol parser/serializer and session connection helper.

Wire format:
    VERB|KEY=VALUE|KEY=VALUE\\n

This module parses messages *received from* pm-alf-gwy, so it must reflect
what the gateway actually puts on the wire in its responses -- not the
normalization the gateway applies while validating commands it receives.
See docs/user-guide/900-app-alf-protocol.md ("Case handling"): that
uppercasing rule describes how pm-alf-gwy parses inbound commands, not how
it formats outbound messages. docs/user-guide/220-alf-gateway.md's own
wire examples show the gateway sending mixed-case data back (e.g.
``GW=alf-gwy01``, ``ORDER|ID=abc123``), so order IDs, free-text
``REASON``/``DETAIL`` fields, and similar values must round-trip with
their original case intact -- forcing them to uppercase would corrupt an
order ID a client later needs to echo back in AMEND/CANCEL. The C parser
library (alf_parser.c) already preserves value case; this module matches
that behavior.

Parsing rules:
- Split on '|'; first token is the command/verb, uppercased
- Remaining tokens are KEY=VALUE; split on first '=' only
- Keys are uppercased; values preserve their original case
- Tokens without '=' are silently skipped
- Duplicate keys: last value wins
"""

from __future__ import annotations

import socket
from dataclasses import dataclass


class AlfParseError(ValueError):
    """Raised when an ALF message cannot be parsed."""


@dataclass(frozen=True)
class AlfMessage:
    """One parsed ALF message received from the gateway."""

    msg_type: str  # e.g. "ACK", "FILL", "WELCOME"
    fields: dict[
        str, str
    ]  # keys uppercase; values preserve original case; last-value-wins


@dataclass
class WelcomeInfo:
    """Information extracted from the WELCOME handshake response."""

    gateway_id: str
    gw_name: str
    proto: str
    heartbeat_interval: int  # seconds
    idle_timeout: int  # seconds
    raw_fields: dict[str, str]


_ALLOWED_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def parse_alf_line(line: str) -> AlfMessage:
    """Parse one ALF line into an AlfMessage.

    Strips full-line whitespace and uppercases the command verb and all
    field names (both are case-insensitive on the wire), skips segments
    without '=', and resolves duplicates with last-value-wins semantics.
    Field *values* preserve their original case — the gateway's own
    responses are not uppercase-normalized (see module docstring), and
    forcing them upper would corrupt data like order IDs that a client
    must echo back verbatim in a later AMEND/CANCEL.
    """
    raw = line.strip()
    if not raw:
        raise AlfParseError("empty line")

    segments = raw.split("|")
    msg_type = segments[0].strip().upper()
    if not msg_type or any(ch not in _ALLOWED_CHARS for ch in msg_type):
        raise AlfParseError(f"invalid message type: {msg_type!r}")

    fields: dict[str, str] = {}
    for seg in segments[1:]:
        if "=" not in seg:
            continue  # silently skip bare-word segments (e.g. "HISTORY" in INDEX|HISTORY|...)
        key, _, value = seg.partition("=")
        key = key.strip().upper()
        if key:
            fields[key] = value.strip()

    return AlfMessage(msg_type=msg_type, fields=fields)


def build_alf_line(msg_type: str, fields: dict[str, str] | None = None) -> str:
    """Build one ALF protocol line terminated by '\\n'.

    The message type is uppercased; field keys and values are passed
    through as-is.  Raises AlfParseError if the message type is invalid
    or if any key/value contains a '|' character.
    """
    msg = msg_type.strip().upper()
    if not msg or any(ch not in _ALLOWED_CHARS for ch in msg):
        raise AlfParseError(f"invalid message type: {msg_type!r}")

    tokens = [msg]
    if fields:
        for k, v in fields.items():
            clean_k = k.strip().upper()
            clean_v = str(v).replace("\n", " ").replace("\r", " ")
            if not clean_k:
                raise AlfParseError("empty field key")
            if "|" in clean_k or "|" in clean_v:
                raise AlfParseError(f"'|' not allowed in ALF field: {k}={v!r}")
            tokens.append(f"{clean_k}={clean_v}")

    return "|".join(tokens) + "\n"


class LineReader:
    """Buffered TCP line reader.

    Accumulates recv() chunks and yields complete '\\n'-delimited lines.
    Never assumes one recv() equals one message — TCP is a byte stream.
    """

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buf = bytearray()

    def recv_line(self) -> str:
        """Block until one complete '\\n'-terminated line is available.

        Returns the line without the trailing '\\n', decoded as UTF-8.
        Raises RuntimeError when the server closes the connection.
        """
        while True:
            nl = self._buf.find(b"\n")
            if nl >= 0:
                raw = bytes(self._buf[:nl])
                del self._buf[: nl + 1]
                return raw.decode("utf-8", errors="replace")
            chunk = self._sock.recv(4096)
            if not chunk:
                raise RuntimeError("connection closed by gateway")
            self._buf.extend(chunk)


class AlfSession:
    """TCP connection to pm-alf-gwy with a completed HELLO/WELCOME handshake.

    Typical usage::

        session = AlfSession.connect("127.0.0.1", 5565, "TRADER01")
        session.send("NEW", {"SYM": "AAPL", "SIDE": "BUY", "TYPE": "LIMIT",
                              "QTY": "100", "PRICE": "150.00"})
        msg = session.recv_msg()
        print(msg.msg_type, msg.fields)
        session.close()
    """

    def __init__(
        self,
        sock: socket.socket,
        reader: LineReader,
        gateway_id: str,
        welcome: WelcomeInfo,
    ) -> None:
        self._sock = sock
        self._reader = reader
        self._gateway_id = gateway_id
        self._welcome = welcome
        self._known_symbols: list[str] = []

    @classmethod
    def connect(
        cls,
        host: str,
        port: int,
        gateway_id: str,
        client_name: str = "alf-client",
        timeout: float = 5.0,
    ) -> "AlfSession":
        """Open a TCP connection and complete the HELLO/WELCOME handshake.

        Returns an authenticated AlfSession.  Raises RuntimeError when the
        gateway refuses the gateway ID or when the connection times out.
        """
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.settimeout(None)  # switch to blocking mode after connect
        reader = LineReader(sock)

        hello = build_alf_line(
            "HELLO",
            {
                "CLIENT": client_name[:32],
                "PROTO": "ALF1",
                "ID": gateway_id.upper(),
            },
        )
        sock.sendall(hello.encode("utf-8"))

        # Wait for WELCOME; skip any HB lines that may race ahead
        for _ in range(20):
            raw = reader.recv_line()
            try:
                msg = parse_alf_line(raw)
            except AlfParseError:
                continue

            if msg.msg_type == "WELCOME":
                gw_id = msg.fields.get("ID", gateway_id.upper())
                try:
                    hbint = int(msg.fields.get("HBINT", "5"))
                    idle = int(msg.fields.get("IDLE", "30"))
                except ValueError:
                    hbint, idle = 5, 30

                welcome = WelcomeInfo(
                    gateway_id=gw_id,
                    gw_name=msg.fields.get("GW", "alf-gwy"),
                    proto=msg.fields.get("PROTO", "ALF1"),
                    heartbeat_interval=hbint,
                    idle_timeout=idle,
                    raw_fields=dict(msg.fields),
                )
                return cls(sock, reader, gw_id, welcome)

            if msg.msg_type == "ERR":
                code = msg.fields.get("CODE", "?")
                detail = msg.fields.get("DETAIL", raw)
                sock.close()
                raise RuntimeError(f"Gateway refused connection [{code}]: {detail}")

            if msg.msg_type == "HB":
                continue

            sock.close()
            raise RuntimeError(f"Unexpected message before WELCOME: {raw!r}")

        sock.close()
        raise RuntimeError("WELCOME not received within expected handshake window")

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def send(self, msg_type: str, fields: dict[str, str] | None = None) -> None:
        """Send one ALF line to the gateway."""
        self._sock.sendall(build_alf_line(msg_type, fields).encode("utf-8"))

    def send_raw(self, line: str) -> None:
        """Send a pre-built ALF line (without trailing '\\n') to the gateway.

        For callers that already have a full "VERB|K=V|..." string on hand
        (e.g. a REPL forwarding a user-typed command) and don't need
        ``send()``'s dict-to-line building. Appends the trailing '\\n'.
        """
        self._sock.sendall((line + "\n").encode("utf-8"))

    def recv_msg(self) -> AlfMessage:
        """Receive and parse one ALF message from the gateway.

        Blocks until a complete '\\n'-terminated line is available.
        """
        return parse_alf_line(self._reader.recv_line())

    def close(self) -> None:
        """Send EXIT and close the TCP connection."""
        try:
            self._sock.sendall(b"EXIT\n")
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def gateway_id(self) -> str:
        return self._gateway_id

    @property
    def welcome(self) -> WelcomeInfo:
        return self._welcome

    @property
    def sock(self) -> socket.socket:
        return self._sock

    @property
    def reader(self) -> LineReader:
        return self._reader

    @property
    def known_symbols(self) -> list[str]:
        return list(self._known_symbols)

    def set_known_symbols(self, symbols: list[str]) -> None:
        """Update the cached symbol list (called after a SYMBOLS response)."""
        self._known_symbols = [s.upper() for s in symbols]

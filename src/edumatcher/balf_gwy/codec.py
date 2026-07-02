"""BALF wire protocol codec — frame parsing and building.

This module owns the binary layout.  Nothing in here depends on other
edumatcher modules so it can be unit-tested in isolation.

All integer fields are little-endian (``<`` prefix).
Prices are ``i64`` scaled by ``PRICE_SCALE`` (10^8).

Frame layout
------------
Every BALF message is an 8-byte header followed by a fixed-size body
whose total length is determined by ``msg_type``:

    Byte 0   magic       0xBA
    Byte 1   version     1
    Byte 2   msg_type
    Byte 3   flags       must be 0x00 in v1.0.0
    Bytes 4-7 seq_no     u32 LE, 0 for LOGON / LOGON_ACK

The body starts immediately at byte 8.
"""

from __future__ import annotations

import struct
import time
from typing import Any, Final

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

BALF_MAGIC: Final[int] = 0xBA
BALF_VERSION: Final[int] = 0x01
PRICE_SCALE: Final[int] = 100_000_000  # 10^8

HEADER_SIZE: Final[int] = 8
HEADER_FMT: Final[str] = "<BBBBI"  # magic, version, msg_type, flags, seq_no

# ---------------------------------------------------------------------------
# Message type codes
# ---------------------------------------------------------------------------

MSG_LOGON: Final[int] = 0x01
MSG_LOGON_ACK: Final[int] = 0x02
MSG_NEW_ORDER: Final[int] = 0x10
MSG_ORDER_ACK: Final[int] = 0x11
MSG_CANCEL_ORDER: Final[int] = 0x12
MSG_CANCEL_ACK: Final[int] = 0x13
MSG_AMEND_ORDER: Final[int] = 0x14
MSG_AMEND_ACK: Final[int] = 0x15
MSG_EXECUTION_REPORT: Final[int] = 0x20
MSG_HEARTBEAT: Final[int] = 0x30
MSG_HEARTBEAT_ACK: Final[int] = 0x31
MSG_LOGOUT: Final[int] = 0x40

# Total frame sizes (header + body) — normative per spec §5.1
FRAME_SIZE: Final[dict[int, int]] = {
    MSG_LOGON: 32,  # body 24
    MSG_LOGON_ACK: 92,  # body 84
    MSG_NEW_ORDER: 60,  # body 52
    MSG_ORDER_ACK: 60,  # body 52
    MSG_CANCEL_ORDER: 24,  # body 16
    MSG_CANCEL_ACK: 32,  # body 24
    MSG_AMEND_ORDER: 44,  # body 36
    MSG_AMEND_ACK: 48,  # body 40
    MSG_EXECUTION_REPORT: 64,  # body 56
    MSG_HEARTBEAT: 16,  # body 8
    MSG_HEARTBEAT_ACK: 16,  # body 8
    MSG_LOGOUT: 8,  # body 0
}

# Set of message types that clients are allowed to send
CLIENT_MSG_TYPES: Final[frozenset[int]] = frozenset(
    {
        MSG_LOGON,
        MSG_NEW_ORDER,
        MSG_CANCEL_ORDER,
        MSG_AMEND_ORDER,
        MSG_HEARTBEAT,
        MSG_HEARTBEAT_ACK,
        MSG_LOGOUT,
    }
)

# ---------------------------------------------------------------------------
# Side / order-type / TIF / SMP codes
# ---------------------------------------------------------------------------

SIDE_BUY: Final[int] = 0x01
SIDE_SELL: Final[int] = 0x02

SIDE_TO_STR: Final[dict[int, str]] = {
    SIDE_BUY: "BUY",
    SIDE_SELL: "SELL",
}

ORDER_TYPE_TO_STR: Final[dict[int, str]] = {
    0x01: "MARKET",
    0x02: "LIMIT",
    0x03: "IOC",
    0x04: "FOK",
    0x05: "STOP",
    0x06: "STOP_LIMIT",
    0x07: "ICEBERG",
    0x08: "TRAILING_STOP",
}

TIF_TO_STR: Final[dict[int, str]] = {
    0x01: "DAY",
    0x02: "GTC",
    0x03: "ATO",
    0x04: "ATC",
}

SMP_TO_STR: Final[dict[int, str]] = {
    0x00: "NONE",
    0x01: "CANCEL_AGGRESSOR",
    0x02: "CANCEL_RESTING",
    0x03: "CANCEL_BOTH",
}

# Cancel reason codes (outbound CANCEL_ACK.cancel_reason)
CANCEL_REASON_CLIENT: Final[int] = 0
CANCEL_REASON_SYSTEM: Final[int] = 255  # SMP, session-end, IOC expire, etc.

# Status codes (EXECUTION_REPORT.status)
STATUS_PARTIAL: Final[int] = 0x01
STATUS_FILLED: Final[int] = 0x02

# LOGON_ACK reject codes (gateway-level)
LOGON_REJECT_NONE: Final[int] = 0x00
LOGON_REJECT_NOT_CONFIGURED: Final[int] = 0x01
LOGON_REJECT_ALREADY_CONNECTED: Final[int] = 0x02
LOGON_REJECT_PROTO_MISMATCH: Final[int] = 0x03
LOGON_REJECT_OTHER: Final[int] = 0xFF

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _encode_fixed(s: str | bytes, width: int) -> bytes:
    """Return ``s`` left-aligned and zero-padded to exactly ``width`` bytes.

    Silently truncates if ``s`` is longer than ``width``.
    """
    if isinstance(s, str):
        raw = s.encode("ascii", errors="replace")
    else:
        raw = s
    return raw[:width].ljust(width, b"\x00")


def _decode_fixed(raw: bytes) -> str:
    """Decode zero-padded ASCII; strips everything from the first null byte."""
    null_pos = raw.find(b"\x00")
    if null_pos >= 0:
        raw = raw[:null_pos]
    return raw.decode("ascii", errors="replace")


def encode_price(display: float) -> int:
    """Convert a display-format price to BALF i64 wire format."""
    return round(display * PRICE_SCALE)


def decode_price(wire: int) -> float:
    """Convert a BALF i64 wire price to a display-format float."""
    return wire / PRICE_SCALE


def now_ns() -> int:
    """Current wall-clock time as nanoseconds since Unix epoch."""
    return int(time.time_ns())


# ---------------------------------------------------------------------------
# Header builders / parsers
# ---------------------------------------------------------------------------


def build_header(msg_type: int, seq_no: int, flags: int = 0) -> bytes:
    """Pack an 8-byte BALF header."""
    return struct.pack(HEADER_FMT, BALF_MAGIC, BALF_VERSION, msg_type, flags, seq_no)


def parse_header(raw: bytes) -> tuple[int, int, int, int]:
    """Unpack a BALF header.

    Returns ``(magic, msg_type, flags, seq_no)``.
    Raises ``ValueError`` if the buffer is too short.
    """
    if len(raw) < HEADER_SIZE:
        raise ValueError(f"header buffer too short: {len(raw)} < {HEADER_SIZE}")
    _magic, _version, msg_type, flags, seq_no = struct.unpack_from(HEADER_FMT, raw)
    return _magic, msg_type, flags, seq_no


# ---------------------------------------------------------------------------
# LOGON  (0x01, 32 bytes total)
# ---------------------------------------------------------------------------
# Body: gateway_id[16] | proto_version u8 | reserved[7]

_LOGON_FMT = "<16sB7s"


def parse_logon(body: bytes) -> tuple[str, int]:
    """Parse a LOGON body.

    Returns ``(gateway_id, proto_version)``.
    """
    if len(body) < 24:
        raise ValueError(f"LOGON body too short: {len(body)}")
    gw_raw, proto_ver, _reserved = struct.unpack_from(_LOGON_FMT, body)
    return _decode_fixed(gw_raw).upper(), proto_ver


# ---------------------------------------------------------------------------
# LOGON_ACK  (0x02, 92 bytes total)
# ---------------------------------------------------------------------------
# Body: gateway_id[16] | accepted u8 | reject_code u8 | msg_len u8 | _pad u8 | msg[64]

_LOGON_ACK_FMT = "<16sBBBB64s"


def build_logon_ack(
    gateway_id: str,
    accepted: bool,
    reject_code: int = LOGON_REJECT_NONE,
    msg: str = "",
    seq_no: int = 0,
) -> bytes:
    """Build a LOGON_ACK frame (92 bytes)."""
    msg_raw = msg.encode("ascii", errors="replace")[:64]
    msg_padded = msg_raw.ljust(64, b"\x00")
    body = struct.pack(
        _LOGON_ACK_FMT,
        _encode_fixed(gateway_id, 16),
        1 if accepted else 0,
        reject_code & 0xFF,
        len(msg_raw),
        0,
        msg_padded,
    )
    return build_header(MSG_LOGON_ACK, seq_no) + body


# ---------------------------------------------------------------------------
# NEW_ORDER  (0x10, 60 bytes total)
# ---------------------------------------------------------------------------
# Body: client_order_id Q | symbol[8] | price q | stop_price q | trail_offset q |
#       quantity I | visible_qty I | side B | order_type B | tif B | smp B

_NEW_ORDER_FMT = "<Q8sqqqIIBBBB"


def parse_new_order(body: bytes) -> dict[str, Any]:
    """Parse a NEW_ORDER body into a plain dict.

    All price fields remain as raw i64 (BALF wire units).
    """
    if len(body) < 52:
        raise ValueError(f"NEW_ORDER body too short: {len(body)}")
    (
        client_order_id,
        sym_raw,
        price,
        stop_price,
        trail_offset,
        quantity,
        visible_qty,
        side,
        order_type,
        tif,
        smp,
    ) = struct.unpack_from(_NEW_ORDER_FMT, body)
    return {
        "client_order_id": client_order_id,
        "symbol": _decode_fixed(sym_raw).upper(),
        "price": price,
        "stop_price": stop_price,
        "trail_offset": trail_offset,
        "quantity": quantity,
        "visible_qty": visible_qty,
        "side": side,
        "order_type": order_type,
        "tif": tif,
        "smp": smp,
    }


# ---------------------------------------------------------------------------
# ORDER_ACK  (0x11, 60 bytes total)
# ---------------------------------------------------------------------------
# Body: client_order_id Q | order_id Q | timestamp_ns Q |
#       accepted B | reject_code B | reason_len B | reason[25]

_ORDER_ACK_FMT = "<QQQBBB25s"


def build_order_ack(
    *,
    client_order_id: int,
    balf_order_id: int,
    seq_no: int,
    accepted: bool,
    reject_code: int = 0,
    reason: str = "",
    timestamp_ns: int = 0,
) -> bytes:
    """Build an ORDER_ACK frame (60 bytes)."""
    reason_raw = reason.encode("ascii", errors="replace")[:25]
    reason_padded = reason_raw.ljust(25, b"\x00")
    body = struct.pack(
        _ORDER_ACK_FMT,
        client_order_id,
        balf_order_id,
        timestamp_ns or now_ns(),
        1 if accepted else 0,
        reject_code & 0xFF,
        len(reason_raw),
        reason_padded,
    )
    return build_header(MSG_ORDER_ACK, seq_no) + body


# ---------------------------------------------------------------------------
# CANCEL_ORDER  (0x12, 24 bytes total)
# ---------------------------------------------------------------------------
# Body: client_order_id Q | order_id Q

_CANCEL_ORDER_FMT = "<QQ"


def parse_cancel_order(body: bytes) -> tuple[int, int]:
    """Parse CANCEL_ORDER body.

    Returns ``(client_order_id, balf_order_id)``.
    """
    if len(body) < 16:
        raise ValueError(f"CANCEL_ORDER body too short: {len(body)}")
    return struct.unpack_from(_CANCEL_ORDER_FMT, body)


# ---------------------------------------------------------------------------
# CANCEL_ACK  (0x13, 32 bytes total)
# ---------------------------------------------------------------------------
# Body: client_order_id Q | order_id Q | accepted B | cancel_reason B | reserved[6]

_CANCEL_ACK_FMT = "<QQBBxxxxxx"


def build_cancel_ack(
    *,
    client_order_id: int,
    balf_order_id: int,
    seq_no: int,
    accepted: bool,
    cancel_reason: int = CANCEL_REASON_CLIENT,
) -> bytes:
    """Build a CANCEL_ACK frame (32 bytes)."""
    body = struct.pack(
        _CANCEL_ACK_FMT,
        client_order_id,
        balf_order_id,
        1 if accepted else 0,
        cancel_reason & 0xFF,
    )
    return build_header(MSG_CANCEL_ACK, seq_no) + body


# ---------------------------------------------------------------------------
# AMEND_ORDER  (0x14, 44 bytes total)
# ---------------------------------------------------------------------------
# Body: client_order_id Q | order_id Q | new_price q | new_quantity I |
#       amend_flags B | reserved[7]

_AMEND_ORDER_FMT = "<QQqIBxxxxxxx"


def parse_amend_order(body: bytes) -> dict[str, Any]:
    """Parse an AMEND_ORDER body.

    Returns a dict with ``client_order_id``, ``balf_order_id``,
    ``new_price`` (raw i64), ``new_quantity``, and ``amend_flags``.
    """
    if len(body) < 36:
        raise ValueError(f"AMEND_ORDER body too short: {len(body)}")
    client_order_id, order_id, new_price, new_quantity, amend_flags = (
        struct.unpack_from(_AMEND_ORDER_FMT, body)
    )
    return {
        "client_order_id": client_order_id,
        "balf_order_id": order_id,
        "new_price": new_price,
        "new_quantity": new_quantity,
        "amend_flags": amend_flags,
    }


# ---------------------------------------------------------------------------
# AMEND_ACK  (0x15, 48 bytes total)
# ---------------------------------------------------------------------------
# Body: client_order_id Q | order_id Q | new_price q | new_quantity I |
#       remaining_qty I | accepted B | priority_reset B | reserved[6]

_AMEND_ACK_FMT = "<QQqIIBBxxxxxx"


def build_amend_ack(
    *,
    client_order_id: int,
    balf_order_id: int,
    seq_no: int,
    accepted: bool,
    new_price: int = 0,
    new_quantity: int = 0,
    remaining_qty: int = 0,
    priority_reset: bool = False,
    reject_reason: str = "",
) -> bytes:
    """Build an AMEND_ACK frame (48 bytes).

    When ``accepted=False``, ``reject_reason`` is carried as an ORDER_ACK
    reject path (see spec §5.9 notes). This frame itself does not carry a
    reason field — the caller should send ORDER_ACK for rejects.

    For accepted amends the price/quantity fields carry post-amend values.
    """
    body = struct.pack(
        _AMEND_ACK_FMT,
        client_order_id,
        balf_order_id,
        new_price,
        new_quantity,
        remaining_qty,
        1 if accepted else 0,
        1 if priority_reset else 0,
    )
    return build_header(MSG_AMEND_ACK, seq_no) + body


# ---------------------------------------------------------------------------
# EXECUTION_REPORT  (0x20, 64 bytes total)
# ---------------------------------------------------------------------------
# Body: client_order_id Q | order_id Q | fill_price q | fill_qty I |
#       remaining_qty I | timestamp_ns Q | symbol[8] | side B | status B | reserved[6]

_EXEC_REPORT_FMT = "<QQqIIQ8sBBxxxxxx"


def build_execution_report(
    *,
    client_order_id: int,
    balf_order_id: int,
    seq_no: int,
    fill_price: int,
    fill_qty: int,
    remaining_qty: int,
    timestamp_ns: int,
    symbol: str,
    side: int,
    status: int,
) -> bytes:
    """Build an EXECUTION_REPORT frame (64 bytes)."""
    body = struct.pack(
        _EXEC_REPORT_FMT,
        client_order_id,
        balf_order_id,
        fill_price,
        fill_qty,
        remaining_qty,
        timestamp_ns,
        _encode_fixed(symbol, 8),
        side & 0xFF,
        status & 0xFF,
    )
    return build_header(MSG_EXECUTION_REPORT, seq_no) + body


# ---------------------------------------------------------------------------
# HEARTBEAT  (0x30, 16 bytes total)
# ---------------------------------------------------------------------------
# Body: send_time_ns Q

_HEARTBEAT_FMT = "<Q"


def build_heartbeat(seq_no: int, send_time_ns: int = 0) -> bytes:
    """Build a HEARTBEAT frame (16 bytes)."""
    ts = send_time_ns if send_time_ns else now_ns()
    return build_header(MSG_HEARTBEAT, seq_no) + struct.pack(_HEARTBEAT_FMT, ts)


def parse_heartbeat(body: bytes) -> int:
    """Parse a HEARTBEAT body; returns ``send_time_ns``."""
    if len(body) < 8:
        raise ValueError(f"HEARTBEAT body too short: {len(body)}")
    (val,) = struct.unpack_from(_HEARTBEAT_FMT, body)
    return int(val)


# ---------------------------------------------------------------------------
# HEARTBEAT_ACK  (0x31, 16 bytes total)
# ---------------------------------------------------------------------------
# Body: orig_send_time_ns Q


def build_heartbeat_ack(orig_send_time_ns: int, seq_no: int) -> bytes:
    """Build a HEARTBEAT_ACK frame (16 bytes)."""
    return build_header(MSG_HEARTBEAT_ACK, seq_no) + struct.pack(
        "<Q", orig_send_time_ns
    )


# ---------------------------------------------------------------------------
# LOGOUT  (0x40, 8 bytes total — header only)
# ---------------------------------------------------------------------------


def build_logout(seq_no: int) -> bytes:
    """Build a LOGOUT frame (8 bytes — header only)."""
    return build_header(MSG_LOGOUT, seq_no)

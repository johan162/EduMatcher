"""Reference BALF parser (Python)

This parser is intentionally small and focused on wire decoding.
It is suitable as a customer reference implementation for BALF v1.

What a BALF client must handle besides the happy path
-----------------------------------------------------
* ``LOGON_ACK`` is *held* until the gateway has the symbol metadata (a price
  is meaningless without its symbol's tick scale), so it may take a moment.
  ``accepted=0`` is final: the gateway closes the TCP connection after it.
  ``describe_logon_ack`` names each reject code and says what to do; the one
  to expect in practice is ``0xFF`` with ``msg == "SYMBOLS_UNAVAILABLE"`` (the
  engine accepted the connection but never sent its symbol list within the
  gateway's ``auth_timeout_sec``): reconnect and log on again.
* A ``LOGOUT`` (0x40, header only) from the gateway means the engine
  restarted and no longer holds the session. The connection closes; log on
  again from scratch (sequence numbers and order ids start over).
* An order for a symbol the engine does not list is refused with an
  ``ORDER_ACK`` ``reject_code`` 0x03, never silently priced.
* ``CANCEL_ACK``, ``AMEND_ACK`` and ``STOP_TRIGGERED`` (sent before the stop
  order's own execution reports) are decoded below; ``cancel_reason`` 255
  means the exchange cancelled the order (SMP, IOC remainder, session end...).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple

BALF_MAGIC = 0xBA
BALF_VERSION = 0x01
PRICE_SCALE = 100_000_000

MSG_LOGON = 0x01
MSG_LOGON_ACK = 0x02
MSG_NEW_ORDER = 0x10
MSG_ORDER_ACK = 0x11
MSG_CANCEL_ORDER = 0x12
MSG_CANCEL_ACK = 0x13
MSG_AMEND_ORDER = 0x14
MSG_AMEND_ACK = 0x15
MSG_EXECUTION_REPORT = 0x20
MSG_STOP_TRIGGERED = 0x21
MSG_HEARTBEAT = 0x30
MSG_HEARTBEAT_ACK = 0x31
MSG_LOGOUT = 0x40

# LOGON_ACK reject codes (gateway-level)
LOGON_REJECT_NONE = 0x00
LOGON_REJECT_NOT_CONFIGURED = 0x01
LOGON_REJECT_ALREADY_CONNECTED = 0x02
LOGON_REJECT_PROTO_MISMATCH = 0x03
LOGON_REJECT_OTHER = 0xFF

#: LOGON_ACK message text that tells a reject of code 0xFF what went wrong.
LOGON_MSG_SYMBOLS_UNAVAILABLE = "SYMBOLS_UNAVAILABLE"

# ORDER_ACK reject codes
ORDER_REJECT_NAMES: Dict[int, str] = {
    0x00: "ACCEPTED",
    0x01: "GW_NOT_CONFIGURED",
    0x02: "GW_NOT_CONNECTED",
    0x03: "SYMBOL_NOT_CONFIGURED",
    0x04: "MARKET_CLOSED",
    0x05: "ATO_OUTSIDE_OPENING",
    0x06: "ATC_OUTSIDE_CLOSING",
    0x07: "HALT_REJECTION",
    0x08: "PHASE_REJECTION",
    0x09: "TRAILING_STOP_NO_PRICE",
    0x0A: "INSUFFICIENT_LIQUIDITY",
    0x0B: "PRICE_COLLAR",
    0x0C: "INVALID_FIELD",
    0xFF: "OTHER",
}

# CANCEL_ACK.cancel_reason
CANCEL_REASON_CLIENT = 0  # the client asked
CANCEL_REASON_SYSTEM = 255  # the exchange decided: SMP, IOC remainder, session end...

STATUS_NAMES: Dict[int, str] = {1: "PARTIAL", 2: "FILLED"}
SIDE_NAMES: Dict[int, str] = {1: "BUY", 2: "SELL"}
#: STOP_TRIGGERED.order_type (the order's armed type) and .becomes
STOP_TYPE_NAMES: Dict[int, str] = {5: "STOP", 6: "STOP_LIMIT", 8: "TRAILING_STOP"}
BECOMES_NAMES: Dict[int, str] = {1: "MARKET", 2: "LIMIT"}

FRAME_SIZES: Dict[int, int] = {
    MSG_LOGON: 32,
    MSG_LOGON_ACK: 92,
    MSG_NEW_ORDER: 60,
    MSG_ORDER_ACK: 60,
    MSG_CANCEL_ORDER: 24,
    MSG_CANCEL_ACK: 32,
    MSG_AMEND_ORDER: 44,
    MSG_AMEND_ACK: 48,
    MSG_EXECUTION_REPORT: 64,
    MSG_STOP_TRIGGERED: 56,
    MSG_HEARTBEAT: 16,
    MSG_HEARTBEAT_ACK: 16,
    MSG_LOGOUT: 8,
}


@dataclass(frozen=True)
class Header:
    magic: int
    version: int
    msg_type: int
    flags: int
    seq_no: int


def decode_price(raw: int) -> float:
    return raw / PRICE_SCALE


def _read_u32_le(buf: bytes, off: int) -> int:
    return int.from_bytes(buf[off : off + 4], "little", signed=False)


def _read_u64_le(buf: bytes, off: int) -> int:
    return int.from_bytes(buf[off : off + 8], "little", signed=False)


def _read_i64_le(buf: bytes, off: int) -> int:
    return int.from_bytes(buf[off : off + 8], "little", signed=True)


def _read_ascii_zp(buf: bytes) -> str:
    return buf.split(b"\x00", 1)[0].decode("ascii", errors="replace")


def parse_header(frame: bytes) -> Header:
    if len(frame) < 8:
        raise ValueError("frame too short for BALF header")
    hdr = Header(
        magic=frame[0],
        version=frame[1],
        msg_type=frame[2],
        flags=frame[3],
        seq_no=_read_u32_le(frame, 4),
    )
    if hdr.magic != BALF_MAGIC:
        raise ValueError(f"bad BALF magic: 0x{hdr.magic:02X}")
    if hdr.version != BALF_VERSION:
        raise ValueError(
            f"unsupported BALF version: {hdr.version} (expected {BALF_VERSION})"
        )
    return hdr


def split_frame(frame: bytes) -> Tuple[Header, bytes]:
    hdr = parse_header(frame)
    expected = FRAME_SIZES.get(hdr.msg_type)
    if expected is None:
        raise ValueError(f"unknown msg_type: 0x{hdr.msg_type:02X}")
    if len(frame) != expected:
        raise ValueError(f"bad frame size: got {len(frame)}, expected {expected}")
    return hdr, frame[8:]


def parse_logon_ack(body: bytes) -> dict[str, Any]:
    if len(body) != 84:
        raise ValueError("LOGON_ACK body must be 84 bytes")
    gateway_id = _read_ascii_zp(body[0:16])
    accepted = body[16] == 1
    reject_code = body[17]
    msg_len = body[18]
    msg = body[20 : 20 + min(msg_len, 64)].decode("ascii", errors="replace")
    return {
        "gateway_id": gateway_id,
        "accepted": accepted,
        "reject_code": reject_code,
        "message": msg,
    }


def describe_logon_ack(ack: dict[str, Any]) -> str:
    """One line saying whether the logon succeeded and, if not, what to do.

    A rejected logon is always followed by the gateway closing the connection,
    so every "retry" below means: open a new TCP connection and send LOGON.
    """
    if ack["accepted"]:
        return f"logged on as {ack['gateway_id']}"
    code, text = ack["reject_code"], ack["message"]
    if code == LOGON_REJECT_OTHER and text == LOGON_MSG_SYMBOLS_UNAVAILABLE:
        return (
            "SYMBOLS_UNAVAILABLE: the engine accepted the connection but did "
            "not send its symbol list in time; reconnect and log on again, "
            "and check the engine's health if it repeats"
        )
    advice = {
        LOGON_REJECT_NOT_CONFIGURED: "the gateway ID is not a configured participant",
        LOGON_REJECT_ALREADY_CONNECTED: "this gateway ID already has a live session",
        LOGON_REJECT_PROTO_MISMATCH: "unsupported protocol version in LOGON",
    }.get(code, "rejected by the gateway or the engine")
    return f"logon rejected (0x{code:02X}): {advice}: {text}"


def parse_order_ack(body: bytes) -> dict[str, Any]:
    if len(body) != 52:
        raise ValueError("ORDER_ACK body must be 52 bytes")
    client_order_id = _read_u64_le(body, 0)
    order_id = _read_u64_le(body, 8)
    timestamp_ns = _read_u64_le(body, 16)
    accepted = body[24] == 1
    reject_code = body[25]
    reason_len = body[26]
    reason = body[27 : 27 + min(reason_len, 25)].decode("ascii", errors="replace")
    return {
        "client_order_id": client_order_id,
        "order_id": order_id,
        "timestamp_ns": timestamp_ns,
        "accepted": accepted,
        "reject_code": reject_code,
        "reject_name": ORDER_REJECT_NAMES.get(reject_code, f"0x{reject_code:02X}"),
        "reason": reason,
    }


def parse_cancel_ack(body: bytes) -> dict[str, Any]:
    if len(body) != 24:
        raise ValueError("CANCEL_ACK body must be 24 bytes")
    cancel_reason = body[17]
    return {
        "client_order_id": _read_u64_le(body, 0),
        "order_id": _read_u64_le(body, 8),
        "accepted": body[16] == 1,
        "cancel_reason": cancel_reason,
        "by_exchange": cancel_reason == CANCEL_REASON_SYSTEM,
    }


def parse_amend_ack(body: bytes) -> dict[str, Any]:
    if len(body) != 40:
        raise ValueError("AMEND_ACK body must be 40 bytes")
    return {
        "client_order_id": _read_u64_le(body, 0),
        "order_id": _read_u64_le(body, 8),
        "new_price": decode_price(_read_i64_le(body, 16)),
        "new_quantity": _read_u32_le(body, 24),
        "remaining_qty": _read_u32_le(body, 28),
        "accepted": body[32] == 1,
        "priority_reset": body[33] == 1,
    }


def parse_stop_triggered(body: bytes) -> dict[str, Any]:
    """A stop, stop-limit or trailing stop fired. Its execution reports follow."""
    if len(body) != 48:
        raise ValueError("STOP_TRIGGERED body must be 48 bytes")
    order_type, becomes = body[40], body[41]
    return {
        "client_order_id": _read_u64_le(body, 0),
        "order_id": _read_u64_le(body, 8),
        "stop_price": decode_price(_read_i64_le(body, 16)),
        "trigger_price": decode_price(_read_i64_le(body, 24)),
        "symbol": _read_ascii_zp(body[32:40]),
        "order_type": STOP_TYPE_NAMES.get(order_type, order_type),
        "becomes": BECOMES_NAMES.get(becomes, becomes),
    }


def parse_execution_report(body: bytes) -> dict[str, Any]:
    if len(body) != 56:
        raise ValueError("EXECUTION_REPORT body must be 56 bytes")
    client_order_id = _read_u64_le(body, 0)
    order_id = _read_u64_le(body, 8)
    fill_price_raw = _read_i64_le(body, 16)
    fill_qty = _read_u32_le(body, 24)
    remaining_qty = _read_u32_le(body, 28)
    timestamp_ns = _read_u64_le(body, 32)
    symbol = _read_ascii_zp(body[40:48])
    side = body[48]
    status = body[49]
    return {
        "client_order_id": client_order_id,
        "order_id": order_id,
        "fill_price": decode_price(fill_price_raw),
        "fill_qty": fill_qty,
        "remaining_qty": remaining_qty,
        "timestamp_ns": timestamp_ns,
        "symbol": symbol,
        "side": SIDE_NAMES.get(side, side),
        "status": STATUS_NAMES.get(status, status),
    }


def _self_test() -> None:
    # Minimal LOGON_ACK example frame
    body = bytearray(84)
    body[0:16] = b"TRADER01\x00\x00\x00\x00\x00\x00\x00\x00"
    body[16] = 1
    body[17] = 0
    msg = b"ok"
    body[18] = len(msg)
    body[20 : 20 + len(msg)] = msg
    frame = bytes([BALF_MAGIC, BALF_VERSION, MSG_LOGON_ACK, 0]) + (0).to_bytes(4, "little") + bytes(body)

    hdr, payload = split_frame(frame)
    assert hdr.msg_type == MSG_LOGON_ACK
    ack = parse_logon_ack(payload)
    assert ack["gateway_id"] == "TRADER01"
    assert ack["accepted"] is True
    assert ack["message"] == "ok"
    assert describe_logon_ack(ack) == "logged on as TRADER01"

    # The refusal a client sees when the engine never sent its symbols.
    body = bytearray(84)
    body[0:8] = b"TRADER01"
    body[17] = LOGON_REJECT_OTHER
    msg = LOGON_MSG_SYMBOLS_UNAVAILABLE.encode()
    body[18] = len(msg)
    body[20 : 20 + len(msg)] = msg
    frame = _frame(MSG_LOGON_ACK, bytes(body))
    _, payload = split_frame(frame)
    ack = parse_logon_ack(payload)
    assert not ack["accepted"] and ack["message"] == "SYMBOLS_UNAVAILABLE"
    assert describe_logon_ack(ack).startswith("SYMBOLS_UNAVAILABLE")

    # CANCEL_ACK for an exchange-initiated cancel (e.g. self-match prevention).
    body = bytearray(24)
    body[0:8] = (7).to_bytes(8, "little")
    body[8:16] = (42).to_bytes(8, "little")
    body[16], body[17] = 1, CANCEL_REASON_SYSTEM
    _, payload = split_frame(_frame(MSG_CANCEL_ACK, bytes(body)))
    cancel = parse_cancel_ack(payload)
    assert cancel["accepted"] and cancel["by_exchange"] and cancel["order_id"] == 42

    # AMEND_ACK: price 150.25, quantity 80, 60 left, priority lost.
    body = bytearray(40)
    body[8:16] = (42).to_bytes(8, "little")
    body[16:24] = int(150.25 * PRICE_SCALE).to_bytes(8, "little", signed=True)
    body[24:28] = (80).to_bytes(4, "little")
    body[28:32] = (60).to_bytes(4, "little")
    body[32], body[33] = 1, 1
    _, payload = split_frame(_frame(MSG_AMEND_ACK, bytes(body)))
    amend = parse_amend_ack(payload)
    assert amend["new_price"] == 150.25 and amend["remaining_qty"] == 60
    assert amend["accepted"] and amend["priority_reset"]

    # STOP_TRIGGERED: a trailing stop on AAPL fired at 148.00 and becomes a MARKET.
    body = bytearray(48)
    body[8:16] = (42).to_bytes(8, "little")
    body[16:24] = (148 * PRICE_SCALE).to_bytes(8, "little", signed=True)
    body[32:36] = b"AAPL"
    body[40], body[41] = 8, 1
    _, payload = split_frame(_frame(MSG_STOP_TRIGGERED, bytes(body)))
    stop = parse_stop_triggered(payload)
    assert stop["order_type"] == "TRAILING_STOP" and stop["becomes"] == "MARKET"
    assert stop["stop_price"] == 148.0 and stop["symbol"] == "AAPL"

    # LOGOUT is a bare header: the engine restarted, log on again.
    hdr, payload = split_frame(_frame(MSG_LOGOUT, b""))
    assert hdr.msg_type == MSG_LOGOUT and payload == b""


def _frame(msg_type: int, body: bytes, seq_no: int = 0) -> bytes:
    return (
        bytes([BALF_MAGIC, BALF_VERSION, msg_type, 0])
        + seq_no.to_bytes(4, "little")
        + body
    )


if __name__ == "__main__":
    _self_test()
    print("balf_parser.py self-test: OK")

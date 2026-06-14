"""Reference BALF parser (Python)

This parser is intentionally small and focused on wire decoding.
It is suitable as a customer reference implementation for BALF v1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

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
MSG_HEARTBEAT = 0x30
MSG_HEARTBEAT_ACK = 0x31
MSG_LOGOUT = 0x40

FRAME_SIZES: Dict[int, int] = {
    MSG_LOGON: 32,
    MSG_LOGON_ACK: 92,
    MSG_NEW_ORDER: 60,
    MSG_ORDER_ACK: 68,
    MSG_CANCEL_ORDER: 32,
    MSG_CANCEL_ACK: 40,
    MSG_AMEND_ORDER: 52,
    MSG_AMEND_ACK: 56,
    MSG_EXECUTION_REPORT: 72,
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


def parse_logon_ack(body: bytes) -> dict:
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


def parse_order_ack(body: bytes) -> dict:
    if len(body) != 60:
        raise ValueError("ORDER_ACK body must be 60 bytes")
    client_order_id = _read_u64_le(body, 0)
    order_id = body[8:24]
    timestamp_ns = _read_u64_le(body, 24)
    accepted = body[32] == 1
    reject_code = body[33]
    reason_len = body[34]
    reason = body[35 : 35 + min(reason_len, 25)].decode("ascii", errors="replace")
    return {
        "client_order_id": client_order_id,
        "order_id": order_id,
        "timestamp_ns": timestamp_ns,
        "accepted": accepted,
        "reject_code": reject_code,
        "reason": reason,
    }


def parse_execution_report(body: bytes) -> dict:
    if len(body) != 64:
        raise ValueError("EXECUTION_REPORT body must be 64 bytes")
    client_order_id = _read_u64_le(body, 0)
    order_id = body[8:24]
    fill_price_raw = _read_i64_le(body, 24)
    fill_qty = _read_u32_le(body, 32)
    remaining_qty = _read_u32_le(body, 36)
    timestamp_ns = _read_u64_le(body, 40)
    symbol = _read_ascii_zp(body[48:56])
    side = body[56]
    status = body[57]
    return {
        "client_order_id": client_order_id,
        "order_id": order_id,
        "fill_price": decode_price(fill_price_raw),
        "fill_qty": fill_qty,
        "remaining_qty": remaining_qty,
        "timestamp_ns": timestamp_ns,
        "symbol": symbol,
        "side": side,
        "status": status,
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


if __name__ == "__main__":
    _self_test()
    print("balf_parser.py self-test: OK")

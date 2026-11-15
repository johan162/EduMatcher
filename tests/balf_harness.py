"""A real ``Engine`` wired straight to a real ``BalfGateway``, for session tests.

Not a test module (no ``test_`` prefix) — pytest will not collect it.

Why a bridge instead of hand-made engine payloads: the BALF review found
``EXECUTION_REPORT.timestamp_ns`` was always 0 because the gateway read a key
the engine had stopped sending, and every unit test fed it a hand-written
payload with that old key. Here every engine event the gateway handles is
one the engine really published, and every frame the client "sends" goes
through ``BalfGateway._drain_frames`` exactly as if it had been read off TCP.

The two processes are joined synchronously: :meth:`BalfBridge.pump` hands each
pushed frame to ``Engine._dispatch_pull_message`` and each published frame to
``BalfGateway._dispatch_engine_event`` until both directions are idle. There
is no ZMQ, no thread and no timing in between, so a test reads like the
sequence of events it describes.
"""

from __future__ import annotations

import socket
import struct
from collections import deque
from typing import Any

import pytest

from edumatcher.balf_gwy import codec as C
from edumatcher.balf_gwy.config import BalfGatewayConfig
from edumatcher.balf_gwy.gateway import BalfGateway, ClientSession
from edumatcher.models.message import decode
from edumatcher.engine.main import Engine
from tests.engine_harness import FakeSock, make_engine


class FakePush:
    """In-memory PUSH: the bridge drains ``queue`` into the engine."""

    def __init__(self) -> None:
        self.closed = False
        self.queue: deque[list[bytes]] = deque()
        self.sent: list[list[bytes]] = []

    def send_multipart(self, frames: list[bytes]) -> None:
        self.queue.append(frames)
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


class FakeSub:
    """In-memory SUB. The bridge delivers events itself, so it stays empty."""

    def __init__(self) -> None:
        self.closed = False
        self.queue: deque[list[bytes]] = deque()

    def setsockopt(self, op: int, value: Any) -> None:
        _ = op, value

    def getsockopt(self, op: int) -> int:
        _ = op
        return 0

    def poll(self, timeout: int = 0) -> int:
        _ = timeout
        return 1 if self.queue else 0

    def recv_multipart(self) -> list[bytes]:
        return self.queue.popleft()

    def close(self) -> None:
        self.closed = True


class BalfBridge:
    """One engine, one gateway, any number of client sessions."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Any,
        config: BalfGatewayConfig | None = None,
        **engine_kw: Any,
    ) -> None:
        self.engine: Engine
        self.pub: FakeSock
        self.engine, self.pub = make_engine(monkeypatch, tmp_path, **engine_kw)
        # The real engine pre-creates one book per configured symbol in
        # _load_config(); without it system.symbols lists nothing and the
        # gateway refuses every symbol as unknown.
        self.engine._load_config()
        self.push = FakePush()
        self.sub = FakeSub()
        monkeypatch.setattr(
            "edumatcher.balf_gwy.gateway.make_pusher", lambda _addr: self.push
        )
        monkeypatch.setattr(
            "edumatcher.balf_gwy.gateway.make_subscriber",
            lambda *_a, **_k: self.sub,
        )
        self.gw = BalfGateway(config or BalfGatewayConfig())
        self._pub_idx = len(self.pub.sent)
        self._peers: list[socket.socket] = []
        #: The client end of each session's socketpair, by session id().
        self.peer_of: dict[int, socket.socket] = {}
        #: Last sequence number each session's "client" sent, by session id().
        self._client_seq: dict[int, int] = {}

    # -- plumbing -----------------------------------------------------------

    def pump(self) -> None:
        """Run both directions until neither has anything left to deliver."""
        while self.push.queue or self._pub_idx < len(self.pub.sent):
            while self.push.queue:
                topic, payload = decode(self.push.queue.popleft())
                # Gateway-local refusals are audit records, not commands.
                if topic.startswith("system.gateway_reject"):
                    continue
                self.engine._dispatch_pull_message(topic, payload)
            while self._pub_idx < len(self.pub.sent):
                frames = self.pub.sent[self._pub_idx]
                self._pub_idx += 1
                self.gw._dispatch_engine_event(*decode(frames))

    def published(self, prefix: str) -> list[dict[str, Any]]:
        """Every engine publication whose topic starts with ``prefix``."""
        out = []
        for frames in self.pub.sent:
            topic, payload = decode(frames)
            if topic.startswith(prefix):
                out.append(payload)
        return out

    def close(self) -> None:
        for sock in self._peers:
            sock.close()

    # -- client side --------------------------------------------------------

    def connect(self, name: str = "client") -> ClientSession:
        """A new TCP connection; the peer end is kept open and never read."""
        left, right = socket.socketpair()
        left.setblocking(False)
        self._peers.extend((left, right))
        session = ClientSession(sock=left, addr=(name, 40000 + left.fileno()))
        self.peer_of[id(session)] = right
        session.rate_tokens = float(self.gw.config.max_messages_per_second)
        self.gw._clients[left.fileno()] = session
        return session

    def send(self, session: ClientSession, frame: bytes, raw: bool = False) -> None:
        """Hand ``frame`` to the gateway as if read off the client's socket.

        Like a real client library, numbers every non-LOGON frame with the
        session's next sequence number (the gateway enforces them since the
        BALF review's C10), so a test need not count. ``raw`` sends the
        frame exactly as built, for tests about the numbering itself.
        """
        if not raw and frame[2] != C.MSG_LOGON:
            seq = self._client_seq.get(id(session), 0) + 1
            self._client_seq[id(session)] = seq
            frame = frame[:4] + seq.to_bytes(4, "little") + frame[8:]
        session.in_buffer.extend(frame)
        self.gw._drain_frames(session)
        self.pump()

    def logon(self, gw_id: str, name: str | None = None) -> ClientSession:
        """Connect and log on; asserts the LOGON_ACK accepted and clears it."""
        session = self.connect(name or gw_id)
        self.send(session, logon_frame(gw_id))
        frames = take(session)
        assert [mt for mt, _ in frames] == [C.MSG_LOGON_ACK], frames
        assert frames[0][1][24] == 1, "LOGON_ACK refused"
        return session

    def logout(self, session: ClientSession) -> None:
        """Send LOGOUT and run the flush that ends the session."""
        self.send(session, C.build_header(C.MSG_LOGOUT, 0))
        self.gw._flush_client_writes()
        self.pump()


# ---------------------------------------------------------------------------
# Frames
# ---------------------------------------------------------------------------


def logon_frame(gw_id: str) -> bytes:
    body = struct.pack("<16sB7s", gw_id.encode("ascii"), C.BALF_VERSION, b"\0" * 7)
    return C.build_header(C.MSG_LOGON, 0) + body


def new_order_frame(
    client_order_id: int,
    *,
    side: int,
    price: float,
    qty: int = 100,
    symbol: str = "AAPL",
    order_type: int = 0x02,
    tif: int = 0x01,
    smp: int = 0x00,
    stop_price: float = 0.0,
    trail_offset: float = 0.0,
    seq_no: int = 1,
) -> bytes:
    body = struct.pack(
        "<Q8sqqqIIBBBB",
        client_order_id,
        symbol.encode("ascii"),
        C.encode_price(price),
        C.encode_price(stop_price),
        C.encode_price(trail_offset),
        qty,
        0,
        side,
        order_type,
        tif,
        smp,
    )
    return C.build_header(C.MSG_NEW_ORDER, seq_no) + body


def cancel_frame(client_order_id: int, order_id: int, seq_no: int = 1) -> bytes:
    return C.build_header(C.MSG_CANCEL_ORDER, seq_no) + struct.pack(
        "<QQ", client_order_id, order_id
    )


def amend_frame(
    client_order_id: int,
    order_id: int,
    *,
    new_price: float = 0.0,
    new_quantity: int = 0,
    flags: int,
    seq_no: int = 1,
) -> bytes:
    body = struct.pack(
        "<QQqIBxxxxxxx",
        client_order_id,
        order_id,
        C.encode_price(new_price),
        new_quantity,
        flags,
    )
    return C.build_header(C.MSG_AMEND_ORDER, seq_no) + body


def heartbeat_frame(seq_no: int) -> bytes:
    return C.build_header(C.MSG_HEARTBEAT, seq_no) + struct.pack("<Q", 1)


# ---------------------------------------------------------------------------
# Reading what the client was sent
# ---------------------------------------------------------------------------


def read_wire(peer: socket.socket) -> list[tuple[int, bytes]]:
    """Every whole frame waiting on the client's end of the socket.

    The bytes that really crossed the connection, unlike :func:`take`, which
    reads the gateway's queue. Stops at end of stream.
    """
    peer.setblocking(False)
    buf = bytearray()
    while True:
        try:
            chunk = peer.recv(65536)
        except BlockingIOError:
            break
        if not chunk:
            break
        buf.extend(chunk)
    frames = []
    while len(buf) >= C.HEADER_SIZE:
        size = C.FRAME_SIZE[buf[2]]
        if len(buf) < size:
            break
        frames.append((buf[2], bytes(buf[:size])))
        del buf[:size]
    assert not buf, f"{len(buf)} trailing bytes: not a whole frame"
    return frames


def take(session: ClientSession) -> list[tuple[int, bytes]]:
    """Remove and return every queued outbound frame as (msg_type, frame)."""
    frames = [(f[2], bytes(f)) for f in session.out_queue]
    session.out_queue.clear()
    session.out_offset = 0
    return frames


def of_type(frames: list[tuple[int, bytes]], msg_type: int) -> list[bytes]:
    return [f for mt, f in frames if mt == msg_type]


def order_ack(frame: bytes) -> dict[str, Any]:
    clid, oid, ts, acc, rc, rlen, reason = struct.unpack_from(
        "<QQQBBB25s", frame, C.HEADER_SIZE
    )
    return {
        "client_order_id": clid,
        "order_id": oid,
        "timestamp_ns": ts,
        "accepted": acc,
        "reject_code": rc,
        "reason": reason[:rlen].decode("ascii"),
    }


def cancel_ack(frame: bytes) -> dict[str, int]:
    clid, oid, acc, reason = struct.unpack_from("<QQBB", frame, C.HEADER_SIZE)
    return {
        "client_order_id": clid,
        "order_id": oid,
        "accepted": acc,
        "cancel_reason": reason,
    }


def amend_ack(frame: bytes) -> dict[str, int]:
    clid, oid, price, qty, rem, acc, reset = struct.unpack_from(
        "<QQqIIBB", frame, C.HEADER_SIZE
    )
    return {
        "client_order_id": clid,
        "order_id": oid,
        "new_price": price,
        "new_quantity": qty,
        "remaining_qty": rem,
        "accepted": acc,
        "priority_reset": reset,
    }

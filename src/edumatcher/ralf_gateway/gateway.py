"""RALF dissemination gateway.

Subscribes to internal engine events and republishes them over a TCP line
protocol for external clearing/drop-copy/audit parties.
"""

from __future__ import annotations

import errno
import select
import signal
import socket
import time
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import zmq

from edumatcher.messaging.bus import make_subscriber
from edumatcher.models.message import decode
from edumatcher.ralf_gateway.config import RalfGatewayConfig
from edumatcher.ralf_gateway.protocol import RalfFrame, build_line, iso_utc, parse_line

_ALLOWED_CHANNELS = frozenset({"CLEARING", "DROP_COPY", "AUDIT"})


@dataclass
class JournalEvent:
    seq: int
    created_mono: float
    line: bytes
    channel: str
    symbol: str


@dataclass
class ClientSession:
    sock: socket.socket
    addr: tuple[str, int]
    client_id: str = ""
    role: str = ""
    authenticated: bool = False
    last_seq_seen: int = 0
    subscriptions: set[tuple[str, str]] = field(default_factory=set)
    in_buffer: bytearray = field(default_factory=bytearray)
    out_queue: deque[bytes] = field(default_factory=deque)
    out_offset: int = 0
    closing: bool = False
    last_activity: float = field(default_factory=time.monotonic)


class RalfGateway:
    """RALF TCP gateway process."""

    def __init__(self, config: RalfGatewayConfig) -> None:
        self.config = config
        self._running = False
        self._next_seq = 1
        self._journal: deque[JournalEvent] = deque()
        self._clients: dict[int, ClientSession] = {}
        self._server: socket.socket | None = None
        self._sub: zmq.Socket[bytes] = make_subscriber(
            config.engine_pub_addr,
            "trade.executed",
            "system.eod",
        )
        self._last_heartbeat = time.monotonic()
        self._trade_counts: dict[str, int] = {}  # symbol → intraday execution count

    def run(self) -> None:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self.config.bind_address, self.config.port))
        self._server.listen(128)
        self._server.setblocking(False)

        self._running = True
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, lambda *_: self.stop())
            signal.signal(signal.SIGTERM, lambda *_: self.stop())

        print(
            f"[RALF] Listening on {self.config.bind_address}:{self.config.port} "
            f"(engine pub: {self.config.engine_pub_addr})"
        )

        while self._running:
            self._accept_new_clients()
            self._read_client_data()
            self._poll_engine_events()
            self._send_heartbeat_if_due()
            self._flush_client_writes()
            self._drop_idle_clients()
            self._prune_journal()
            time.sleep(0.01)

        self.close()

    def stop(self) -> None:
        self._running = False

    def close(self) -> None:
        for sess in list(self._clients.values()):
            try:
                sess.sock.close()
            except OSError:
                pass
        self._clients.clear()
        if self._server is not None:
            self._server.close()
            self._server = None
        if not self._sub.closed:
            self._sub.close()

    # ------------------------------------------------------------------
    # Networking
    # ------------------------------------------------------------------

    def _accept_new_clients(self) -> None:
        if self._server is None:
            return
        while True:
            try:
                conn, addr = self._server.accept()
            except BlockingIOError:
                break
            conn.setblocking(False)
            self._clients[conn.fileno()] = ClientSession(sock=conn, addr=addr)

    def _read_client_data(self) -> None:
        if not self._clients:
            return

        readable: list[socket.socket] = [s.sock for s in self._clients.values()]
        try:
            ready, _, _ = select.select(readable, [], [], 0)
        except OSError:
            return

        for sock_obj in ready:
            sess = self._clients.get(sock_obj.fileno())
            if sess is None:
                continue
            try:
                chunk = sess.sock.recv(4096)
            except (BlockingIOError, OSError):
                continue
            if not chunk:
                self._disconnect(sess)
                continue
            sess.in_buffer.extend(chunk)
            sess.last_activity = time.monotonic()
            self._drain_lines(sess)

    def _drain_lines(self, sess: ClientSession) -> None:
        while True:
            idx = sess.in_buffer.find(b"\n")
            if idx < 0:
                return
            raw = bytes(sess.in_buffer[:idx])
            del sess.in_buffer[: idx + 1]
            line = raw.decode("utf-8", errors="replace")
            self._handle_client_line(sess, line)

    def _flush_client_writes(self) -> None:
        for sess in list(self._clients.values()):
            while sess.out_queue:
                payload = sess.out_queue[0]
                unsent = payload[sess.out_offset :]
                try:
                    sent = sess.sock.send(unsent)
                except (BlockingIOError, OSError):
                    break
                if sent <= 0:
                    break
                sess.out_offset += sent
                sess.last_activity = time.monotonic()
                if sess.out_offset >= len(payload):
                    sess.out_queue.popleft()
                    sess.out_offset = 0
            if len(sess.out_queue) > self.config.max_client_queue:
                self._queue_line(
                    sess,
                    "ERR",
                    {"CODE": "SLOW_CLIENT", "DETAIL": "queue overflow"},
                )
                self._close_after_flush(sess)
            if sess.closing and not sess.out_queue:
                self._disconnect(sess)

    # ------------------------------------------------------------------
    # Protocol handling
    # ------------------------------------------------------------------

    def _handle_client_line(self, sess: ClientSession, line: str) -> None:
        try:
            frame = parse_line(line)
        except Exception:
            self._queue_line(
                sess,
                "ERR",
                {"CODE": "BAD_MESSAGE", "DETAIL": "parse error"},
            )
            return

        if not sess.authenticated:
            if frame.msg_type != "HELLO":
                self._queue_line(
                    sess,
                    "ERR",
                    {"CODE": "AUTH_REQUIRED", "DETAIL": "send HELLO first"},
                )
                self._close_after_flush(sess)
                return
            self._handle_hello(sess, frame)
            return

        if frame.msg_type == "SUB":
            self._handle_sub(sess, frame)
        elif frame.msg_type == "UNSUB":
            self._handle_unsub(sess, frame)
        elif frame.msg_type == "PING":
            self._queue_line(sess, "PONG", {"TS": iso_utc(time.time())})
        elif frame.msg_type == "EXIT":
            self._close_after_flush(sess)
        else:
            self._queue_line(
                sess,
                "ERR",
                {"CODE": "BAD_MESSAGE", "DETAIL": f"unsupported {frame.msg_type}"},
            )

    def _handle_hello(self, sess: ClientSession, frame: RalfFrame) -> None:
        client = frame.fields.get("CLIENT", "")
        proto = frame.fields.get("PROTO", "")
        role = frame.fields.get("ROLE", "").upper()

        if not client or proto != "RALF1" or not role:
            self._queue_line(
                sess,
                "ERR",
                {"CODE": "AUTH_REQUIRED", "DETAIL": "CLIENT/PROTO/ROLE required"},
            )
            self._close_after_flush(sess)
            return

        if role not in self.config.allowed_roles:
            self._queue_line(
                sess,
                "ERR",
                {"CODE": "ENTITLEMENT_DENIED", "DETAIL": "role not allowed"},
            )
            self._close_after_flush(sess)
            return

        last_seq = 0
        last_seq_raw = frame.fields.get("LASTSEQ")
        if last_seq_raw:
            try:
                last_seq = int(last_seq_raw)
            except ValueError:
                self._queue_line(
                    sess,
                    "ERR",
                    {"CODE": "BAD_MESSAGE", "DETAIL": "LASTSEQ must be integer"},
                )
                self._close_after_flush(sess)
                return

        sess.client_id = client
        sess.role = role
        sess.last_seq_seen = last_seq
        sess.authenticated = True

        self._queue_line(
            sess,
            "WELCOME",
            {
                "PROTO": "RALF1",
                "GW": self.config.name,
                "ROLE": role,
                "REPLAY": str(self.config.replay_retention_sec),
                "HBINT": str(self.config.heartbeat_interval_sec),
            },
        )

        if last_seq > 0:
            self._replay_from(sess, last_seq)

    def _handle_sub(self, sess: ClientSession, frame: RalfFrame) -> None:
        ch_raw = frame.fields.get("CH", "")
        sym_raw = frame.fields.get("SYM", "*")

        if not ch_raw:
            self._queue_line(
                sess,
                "ERR",
                {"CODE": "INVALID_CHANNEL", "DETAIL": "CH required"},
            )
            return

        channels = [c.strip().upper() for c in ch_raw.split(",") if c.strip()]
        symbols = [s.strip().upper() for s in sym_raw.split(",") if s.strip()]
        if not symbols:
            symbols = ["*"]

        for ch in channels:
            if ch not in _ALLOWED_CHANNELS:
                self._queue_line(
                    sess,
                    "ERR",
                    {"CODE": "INVALID_CHANNEL", "DETAIL": f"unsupported CH={ch}"},
                )
                return
            if ch != sess.role and sess.role != "AUDIT":
                self._queue_line(
                    sess,
                    "ERR",
                    {
                        "CODE": "ENTITLEMENT_DENIED",
                        "DETAIL": f"role {sess.role!r} cannot access CH={ch}",
                    },
                )
                return

        for ch in channels:
            for sym in symbols:
                sess.subscriptions.add((ch, sym))

        self._queue_line(
            sess,
            "SNAP",
            {
                "CH": ",".join(channels),
                "SYM": ",".join(symbols),
                "SEQ": str(self._next_seq - 1),
                "TS": iso_utc(time.time()),
            },
        )

    def _handle_unsub(self, sess: ClientSession, frame: RalfFrame) -> None:
        ch_raw = frame.fields.get("CH", "")
        sym_raw = frame.fields.get("SYM", "*")

        channels = [c.strip().upper() for c in ch_raw.split(",") if c.strip()]
        symbols = [s.strip().upper() for s in sym_raw.split(",") if s.strip()]
        if not symbols:
            symbols = ["*"]

        for ch in channels:
            for sym in symbols:
                sess.subscriptions.discard((ch, sym))

    def _replay_from(self, sess: ClientSession, last_seq: int) -> None:
        if not self._journal:
            return
        oldest = self._journal[0].seq
        if last_seq < oldest - 1:
            self._queue_line(
                sess,
                "ERR",
                {"CODE": "REPLAY_MISS", "DETAIL": "requested seq outside retention"},
            )
            self._queue_line(
                sess,
                "SNAP",
                {
                    "CH": "CLEARING",
                    "SYM": "*",
                    "SEQ": str(self._next_seq - 1),
                    "TS": iso_utc(time.time()),
                },
            )
            return

        for evt in self._journal:
            if evt.seq > last_seq:
                self._queue_raw(sess, evt.line)

    # ------------------------------------------------------------------
    # Engine event mapping
    # ------------------------------------------------------------------

    def _poll_engine_events(self) -> None:
        while self._sub.poll(timeout=0):
            try:
                topic, payload = decode(self._sub.recv_multipart())
            except zmq.ZMQError as exc:
                if exc.errno != errno.EINTR:
                    raise
                break
            except Exception:
                continue
            if topic == "trade.executed":
                self._handle_trade(payload)
            elif topic == "system.eod":
                self._handle_eod(payload)

    def _handle_trade(self, payload: dict[str, Any]) -> None:
        symbol = str(payload.get("symbol", "")).upper()
        qty = str(payload.get("quantity", 0))
        px = str(payload.get("price", 0.0))
        ts_value = float(payload.get("timestamp", time.time()))
        self._trade_counts[symbol] = self._trade_counts.get(symbol, 0) + 1

        for channel in ("CLEARING", "DROP_COPY", "AUDIT"):
            self._emit_event(
                "EXEC",
                {
                    "CH": channel,
                    "SYM": symbol,
                    "TS": iso_utc(ts_value),
                    "EXEC_ID": str(payload.get("id", "")),
                    "MATCH_ID": str(payload.get("id", "")),
                    "BUY_ORDER_ID": str(payload.get("buy_order_id", "")),
                    "SELL_ORDER_ID": str(payload.get("sell_order_id", "")),
                    "BUY_GW": str(payload.get("buy_gateway_id", "")),
                    "SELL_GW": str(payload.get("sell_gateway_id", "")),
                    "SIDE": str(payload.get("aggressor_side", "")),
                    "QTY": qty,
                    "PX": px,
                },
                channel=channel,
                symbol=symbol,
            )

    def _handle_eod(self, payload: dict[str, Any]) -> None:
        books = payload.get("books", [])
        if not isinstance(books, list):
            return

        for raw_book in books:
            if not isinstance(raw_book, dict):
                continue
            symbol = str(raw_book.get("symbol", "")).upper()
            exec_count = str(self._trade_counts.get(symbol, 0))
            for channel in ("CLEARING", "AUDIT"):
                self._emit_event(
                    "EOD",
                    {
                        "CH": channel,
                        "SYM": symbol,
                        "TS": iso_utc(time.time()),
                        "TRADE_COUNT": exec_count,
                        "EXEC_COUNT": exec_count,
                    },
                    channel=channel,
                    symbol=symbol,
                )
        self._trade_counts.clear()

    def _emit_event(
        self,
        msg_type: str,
        fields: dict[str, str],
        *,
        channel: str,
        symbol: str,
    ) -> None:
        seq = self._next_seq
        self._next_seq += 1

        merged = dict(fields)
        merged["SEQ"] = str(seq)
        line = build_line(msg_type, merged)
        evt = JournalEvent(
            seq=seq,
            created_mono=time.monotonic(),
            line=line,
            channel=channel,
            symbol=symbol,
        )
        self._journal.append(evt)

        for sess in self._clients.values():
            if not sess.authenticated:
                continue
            if self._session_wants(sess, channel, symbol):
                self._queue_raw(sess, line)

    def _session_wants(self, sess: ClientSession, channel: str, symbol: str) -> bool:
        for ch, sym in sess.subscriptions:
            if ch != channel:
                continue
            if sym == "*" or sym == symbol:
                return True
        return False

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def _send_heartbeat_if_due(self) -> None:
        now = time.monotonic()
        if now - self._last_heartbeat < self.config.heartbeat_interval_sec:
            return
        self._last_heartbeat = now

        for sess in self._clients.values():
            if sess.authenticated:
                self._queue_line(sess, "HB", {"TS": iso_utc(time.time())})

    def _drop_idle_clients(self) -> None:
        now = time.monotonic()
        for sess in list(self._clients.values()):
            if now - sess.last_activity > self.config.idle_timeout_sec:
                self._queue_line(
                    sess,
                    "EXIT",
                    {"REASON": "idle_timeout", "TS": iso_utc(time.time())},
                )
                self._close_after_flush(sess)

    def _prune_journal(self) -> None:
        cutoff = time.monotonic() - self.config.replay_retention_sec
        while self._journal and self._journal[0].created_mono < cutoff:
            self._journal.popleft()

    # ------------------------------------------------------------------
    # Send/disconnect helpers
    # ------------------------------------------------------------------

    def _queue_line(
        self, sess: ClientSession, msg_type: str, fields: dict[str, str]
    ) -> None:
        self._queue_raw(sess, build_line(msg_type, fields))

    def _queue_raw(self, sess: ClientSession, payload: bytes) -> None:
        sess.out_queue.append(payload)

    def _disconnect(self, sess: ClientSession) -> None:
        fileno = sess.sock.fileno()
        try:
            sess.sock.close()
        except OSError:
            pass
        self._clients.pop(fileno, None)

    def _close_after_flush(self, sess: ClientSession) -> None:
        sess.closing = True

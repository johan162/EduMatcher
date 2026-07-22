"""DC gateway runtime.

Exposes the engine's drop-copy feed (``edumatcher.engine.drop_copy``, ZMQ
PUB on :5557 by default) to plain TCP clients that cannot or should not
speak ZeroMQ -- risk systems, clearing brokers, compliance monitors, or any
process that wants a per-participant fill feed without importing pyzmq.

Architecturally this is the TCP counterpart to ``pm-dc-spy``: both connect a
``zmq.SUB`` socket to the drop-copy PUB address and read
``drop_copy.event.<gateway_id>`` messages, but where ``pm-dc-spy`` prints
them to a terminal, ``pm-dc-gwy`` relays them as DC1 text lines to any
number of concurrently connected TCP clients, each scoped to the gateway ID
it asked for in ``HELLO``.

Unlike ``pm-ralf-gwy``, there is no role/entitlement model here (drop copy
has none -- see docs/user-guide/200-drop-copy.md) and no replay-by-sequence
protocol (``DropCopyPublisher.replay()`` is in-process only, not reachable
over this wire -- see the same page). A client simply says which gateway ID
it wants and receives that gateway's live fills for as long as it stays
connected.
"""

from __future__ import annotations

import errno
import logging
import select
import signal
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import zmq

from edumatcher.dc_gateway.config import DcGatewayConfig
from edumatcher.dc_gateway.protocol import DcFrame, build_line, iso_utc, parse_line
from edumatcher.messaging.bus import make_subscriber
from edumatcher.models.message import decode

log = logging.getLogger(__name__)

_MAX_LINE_BYTES = 4096
_MAX_DC_EVENTS_PER_LOOP = 1000
# Topic prefix used by DropCopyPublisher (engine/drop_copy.py) for live
# (non-replay) fill events.
_DC_EVENT_TOPIC_PREFIX = "drop_copy.event."


@dataclass
class ClientSession:
    sock: socket.socket
    addr: tuple[str, int]
    gateway_id: str = ""
    client_name: str = ""
    authenticated: bool = False
    in_buffer: bytearray = field(default_factory=bytearray)
    out_queue: deque[bytes] = field(default_factory=deque)
    out_offset: int = 0
    closing: bool = False
    last_activity: float = field(default_factory=time.monotonic)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


class DcGateway:
    """DC TCP gateway process."""

    def __init__(self, config: DcGatewayConfig) -> None:
        self.config = config
        self._running = False
        self._server: socket.socket | None = None
        self._clients: dict[int, ClientSession] = {}
        # gateway_id -> set of client fds subscribed to that ID. More than
        # one client may request the same gateway_id (unlike ALF/RALF
        # sessions, DC has no "single active session per ID" constraint --
        # any number of external recipients may watch the same participant).
        self._sessions_by_gateway: dict[str, set[int]] = {}
        # Refcounted ZMQ topic subscriptions on the internal drop-copy SUB.
        self._topic_refcounts: dict[str, int] = {}

        self._sub: zmq.Socket[bytes] = make_subscriber(config.drop_copy_pub_addr)
        self._last_heartbeat = time.monotonic()

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

        log.info(
            "listening on %s:%s (drop_copy_pub=%s)",
            self.config.bind_address,
            self.config.port,
            self.config.drop_copy_pub_addr,
        )

        try:
            while self._running:
                self._accept_new_clients()
                self._read_client_data()
                self._poll_dc_events()
                self._send_heartbeat_if_due()
                self._flush_client_writes()
                self._drop_idle_clients()
                time.sleep(0.01)
        finally:
            self.close()

    def stop(self) -> None:
        log.info("stop requested")
        self._running = False

    def close(self) -> None:
        log.info("closing DC gateway")
        for sess in list(self._clients.values()):
            try:
                sess.sock.close()
            except OSError:
                pass
        self._clients.clear()
        self._sessions_by_gateway.clear()
        self._topic_refcounts.clear()
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
            except OSError as exc:
                log.warning("accept failed: %s", exc)
                break
            conn.setblocking(False)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._clients[conn.fileno()] = ClientSession(sock=conn, addr=addr)
            log.info(
                "client connected addr=%s:%s fd=%d", addr[0], addr[1], conn.fileno()
            )

    def _read_client_data(self) -> None:
        if not self._clients:
            return

        readable: list[socket.socket] = [s.sock for s in self._clients.values()]
        try:
            ready, _, _ = select.select(readable, [], [], 0)
        except OSError as exc:
            log.warning("read select failed: %s", exc)
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
                self._disconnect(sess, reason="peer_closed")
                continue
            sess.in_buffer.extend(chunk)
            sess.last_activity = time.monotonic()

            if b"\n" not in sess.in_buffer and len(sess.in_buffer) > _MAX_LINE_BYTES:
                sess.in_buffer.clear()
                self._queue_line(
                    sess, "ERR", {"CODE": "BAD_MESSAGE", "DETAIL": "line too long"}
                )
                self._close_after_flush(sess)
                continue

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
                log.warning(
                    "disconnecting slow client fd=%d queue=%d max=%d",
                    sess.sock.fileno(),
                    len(sess.out_queue),
                    self.config.max_client_queue,
                )
                sess.out_queue.clear()
                sess.out_offset = 0
                self._queue_line(
                    sess, "ERR", {"CODE": "SLOW_CLIENT", "DETAIL": "queue overflow"}
                )
                self._close_after_flush(sess)
            if sess.closing and not sess.out_queue:
                self._disconnect(sess, reason="close_after_flush")

    # ------------------------------------------------------------------
    # Protocol handling
    # ------------------------------------------------------------------

    def _handle_client_line(self, sess: ClientSession, line: str) -> None:
        try:
            frame = parse_line(line)
        except Exception:
            self._queue_line(
                sess, "ERR", {"CODE": "BAD_MESSAGE", "DETAIL": "parse error"}
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

        if frame.msg_type == "PING":
            self._queue_line(sess, "PONG", {"TS": iso_utc(time.time())})
        elif frame.msg_type == "EXIT":
            self._close_after_flush(sess)
        else:
            self._queue_line(
                sess,
                "ERR",
                {"CODE": "BAD_MESSAGE", "DETAIL": f"unsupported {frame.msg_type}"},
            )

    def _handle_hello(self, sess: ClientSession, frame: DcFrame) -> None:
        client = frame.fields.get("CLIENT", "")
        proto = frame.fields.get("PROTO", "")
        gateway_id = frame.fields.get("ID", "").strip().upper()

        if not client or proto != "DC1" or not gateway_id:
            self._queue_line(
                sess,
                "ERR",
                {"CODE": "AUTH_REQUIRED", "DETAIL": "CLIENT/PROTO/ID required"},
            )
            self._close_after_flush(sess)
            return

        sess.client_name = client
        sess.gateway_id = gateway_id
        sess.authenticated = True

        self._dc_subscribe(gateway_id, sess.sock.fileno())

        self._queue_line(
            sess,
            "WELCOME",
            {
                "PROTO": "DC1",
                "GW": self.config.name,
                "ID": gateway_id,
                "HBINT": str(self.config.heartbeat_interval_sec),
                "IDLE": str(self.config.idle_timeout_sec),
            },
        )
        log.info(
            "session authenticated fd=%d client=%s gateway_id=%s",
            sess.sock.fileno(),
            client,
            gateway_id,
        )

    # ------------------------------------------------------------------
    # Drop-copy event relay
    # ------------------------------------------------------------------

    def _dc_subscribe(self, gateway_id: str, fd: int) -> None:
        self._sessions_by_gateway.setdefault(gateway_id, set()).add(fd)
        topic = f"{_DC_EVENT_TOPIC_PREFIX}{gateway_id}"
        ref = self._topic_refcounts.get(topic, 0)
        if ref == 0:
            self._sub.setsockopt(zmq.SUBSCRIBE, topic.encode("utf-8"))
        self._topic_refcounts[topic] = ref + 1

    def _dc_unsubscribe(self, gateway_id: str, fd: int) -> None:
        fds = self._sessions_by_gateway.get(gateway_id)
        if fds is None or fd not in fds:
            return
        fds.discard(fd)
        if not fds:
            del self._sessions_by_gateway[gateway_id]

        topic = f"{_DC_EVENT_TOPIC_PREFIX}{gateway_id}"
        ref = self._topic_refcounts.get(topic, 0)
        if ref <= 1:
            self._topic_refcounts.pop(topic, None)
            self._sub.setsockopt(zmq.UNSUBSCRIBE, topic.encode("utf-8"))
            return
        self._topic_refcounts[topic] = ref - 1

    def _poll_dc_events(self) -> None:
        budget = _MAX_DC_EVENTS_PER_LOOP
        while budget > 0 and self._sub.poll(timeout=0):
            try:
                topic, payload = decode(self._sub.recv_multipart())
            except zmq.ZMQError as exc:
                if exc.errno != errno.EINTR:
                    log.warning(
                        "drop-copy SUB recv error errno=%s; dropping remaining "
                        "events for this tick",
                        exc.errno,
                    )
                break
            except Exception:
                log.warning("decode error on drop-copy SUB event", exc_info=True)
                budget -= 1
                continue

            budget -= 1

            if not topic.startswith(_DC_EVENT_TOPIC_PREFIX):
                continue
            gateway_id = topic[len(_DC_EVENT_TOPIC_PREFIX) :].upper()
            fds = self._sessions_by_gateway.get(gateway_id)
            if not fds:
                continue

            line = build_line(
                "DC_FILL",
                {
                    "SEQ": str(payload.get("seq", "")),
                    "ORDER_ID": str(payload.get("order_id", "")),
                    "SYMBOL": str(payload.get("symbol", "")),
                    "FILL_QTY": str(payload.get("fill_qty", "")),
                    "FILL_PRICE": str(payload.get("fill_price", "")),
                    "LIQUIDITY": str(payload.get("liquidity_flag", "")),
                },
            )
            for fd in fds:
                sess = self._clients.get(fd)
                if sess is not None:
                    self._queue_raw(sess, line)

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

    # ------------------------------------------------------------------
    # Send/disconnect helpers
    # ------------------------------------------------------------------

    def _queue_line(
        self, sess: ClientSession, msg_type: str, fields: dict[str, str]
    ) -> None:
        self._queue_raw(sess, build_line(msg_type, fields))

    def _queue_raw(self, sess: ClientSession, payload: bytes) -> None:
        sess.out_queue.append(payload)

    def _disconnect(self, sess: ClientSession, reason: str = "unspecified") -> None:
        fileno = sess.sock.fileno()
        if sess.gateway_id:
            self._dc_unsubscribe(sess.gateway_id, fileno)
        try:
            sess.sock.close()
        except OSError:
            pass
        self._clients.pop(fileno, None)
        log.info(
            "client disconnected fd=%d client=%s gateway_id=%s reason=%s",
            fileno,
            sess.client_name or "-",
            sess.gateway_id or "-",
            reason,
        )

    def _close_after_flush(self, sess: ClientSession) -> None:
        sess.closing = True
        log.debug("session fd=%d marked closing-after-flush", sess.sock.fileno())

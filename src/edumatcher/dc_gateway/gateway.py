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
has none -- see ../../../docs/books/protocols-and-clients/part-3-session-behaviour/060-drop-copy.md) and no replay-by-sequence
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

from edumatcher.health import HealthReporter
from edumatcher.health.samples import client_gateway_samples
from edumatcher.models.generated.health import MetricSample
from edumatcher.dc_gateway.config import DcGatewayConfig
from edumatcher.dc_gateway.protocol import DcFrame, build_line, iso_utc, parse_line
from edumatcher.health.samples import counter
from edumatcher.messaging.bus import make_subscriber
from edumatcher.models.generated.drop_copy import PREFIX_DROP_COPY_EVENT
from edumatcher.models.message import decode

log = logging.getLogger(__name__)

#: Longest a closing session may take to drain its final line (SLOW_CLIENT
#: error, idle EXIT, a refused HELLO) before it is disconnected regardless --
#: as pm-md-gwy drops a slow client. A client that has stopped reading never
#: drains, so without this it was never dropped at all.
CLOSE_GRACE_SEC = 5.0
#: A connection must send HELLO within this long or is closed with
#: EXIT|REASON=auth_timeout -- the same deadline in all three line gateways.
HELLO_TIMEOUT_SEC = 5.0
#: On a stop, how long sessions get to take their queued lines and the final
#: EXIT|REASON=shutdown before close() drops what is left.
SHUTDOWN_FLUSH_SEC = 1.0

_MAX_LINE_BYTES = 4096
_MAX_DC_EVENTS_PER_LOOP = 1000
# Topic prefix used by DropCopyPublisher (engine/drop_copy.py) for live
# (non-replay) fill events.
_DC_EVENT_TOPIC_PREFIX = PREFIX_DROP_COPY_EVENT
# Receive high-water mark of the drop-copy SUB. ZeroMQ's default of 1000
# drops silently during a burst; the other whole-stream consumers (pm-md-gwy,
# pm-alf-gwy, pm-stats, pm-audit) use 1e5.
_SUB_RCVHWM = 100_000
# After a WARNING about lost drop-copy events, further losses are only
# counted (gwy.feed_gaps) until this long has passed.
_FEED_GAP_LOG_INTERVAL_SEC = 60.0


@dataclass
class ClientSession:
    sock: socket.socket
    addr: tuple[str, int]
    gateway_id: str = ""
    client_name: str = ""
    authenticated: bool = False
    #: Set at the first bytes received. A connection closed before that (a
    #: TCP liveness probe) is logged at DEBUG and not counted as a disconnect.
    heard_from: bool = False
    in_buffer: bytearray = field(default_factory=bytearray)
    out_queue: deque[bytes] = field(default_factory=deque)
    out_offset: int = 0
    closing: bool = False
    #: When ``closing`` was set, and why: the session is disconnected with
    #: this reason once its queue drains or CLOSE_GRACE_SEC passes.
    closing_since: float = 0.0
    close_reason: str = "close_after_flush"
    last_activity: float = field(default_factory=time.monotonic)
    connected_at: float = field(default_factory=time.monotonic)

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
        # Health beacon (operator dashboard §8.5); attached by main().
        # slow_clients counts sessions flagged slow, once each; closing_clients
        # is how many are draining their final line (at most CLOSE_GRACE_SEC).
        self._reporter: HealthReporter | None = None
        self._msgs_out = 0
        self._slow_clients = 0
        self._disconnects: dict[str, int] = {}
        # gateway_id -> set of client fds subscribed to that ID. More than
        # one client may request the same gateway_id (unlike ALF/RALF
        # sessions, DC has no "single active session per ID" constraint --
        # any number of external recipients may watch the same participant).
        self._sessions_by_gateway: dict[str, set[int]] = {}
        # Refcounted ZMQ topic subscriptions on the internal drop-copy SUB.
        self._topic_refcounts: dict[str, int] = {}
        # Last payload seq per watched gateway_id, to count events the SUB
        # never received (gwy.feed_gaps). Forgotten when the ID's last
        # watcher leaves: fills nobody watched are not a loss.
        self._feed_seq: dict[str, int] = {}
        self._feed_gaps = 0
        self._feed_gaps_unlogged = 0
        self._feed_gap_logged_at: float | None = None

        # Only watched IDs are subscribed, in _dc_subscribe(). The catch-all
        # subscription make_subscriber() adds without topics is dropped: with
        # it, a burst for IDs nobody watches filled the receive buffer and
        # cost a watched ID its fills (review H1).
        self._sub: zmq.Socket[bytes] = make_subscriber(
            config.drop_copy_pub_addr, rcvhwm=_SUB_RCVHWM
        )
        self._sub.setsockopt(zmq.UNSUBSCRIBE, b"")
        self._last_heartbeat = time.monotonic()

    def run(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.config.bind_address, self.config.port))
        server.listen(128)
        server.setblocking(False)
        # Published only once listening: callers poll it as the readiness signal.
        self._server = server

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

        reporter = self._reporter
        try:
            while self._running:
                if reporter is not None:
                    reporter.tick_and_publish(self.metric_samples)
                self._accept_new_clients()
                self._read_client_data()
                backlog = self._poll_dc_events()
                self._send_heartbeat_if_due()
                self._flush_client_writes()
                self._drop_idle_clients()
                if not backlog:
                    time.sleep(0.01)
            self._flush_for_shutdown()
        finally:
            self.close()

    def _flush_for_shutdown(self) -> None:
        """Say goodbye to every session before a requested stop.

        close() used to close every socket at once: queued lines died with
        it and a client read only EOF, which looks like a crash (review C4).
        Now: one more relay pass, ``EXIT|REASON=shutdown`` to every session
        not already closing, then a flush bounded by SHUTDOWN_FLUSH_SEC;
        close() drops whatever a peer has not taken by then. Not run after a
        crash (run() calls it only when the loop ends normally).
        """
        self._poll_dc_events()
        for sess in list(self._clients.values()):
            if not sess.closing:
                self._queue_line(
                    sess, "EXIT", {"REASON": "shutdown", "TS": iso_utc(time.time())}
                )
            self._close_after_flush(sess, reason="shutdown")
        deadline = time.monotonic() + SHUTDOWN_FLUSH_SEC
        while self._clients and time.monotonic() < deadline:
            # _flush_client_writes disconnects each session whose queue has
            # drained; one whose peer takes nothing stays until the deadline.
            self._flush_client_writes()
            if self._clients:
                time.sleep(0.01)

    def stop(self) -> None:
        log.info("stop requested")
        self._running = False

    def attach_reporter(self, reporter: HealthReporter) -> None:
        """Ship this gateway's metrics through ``reporter`` (from main())."""
        self._reporter = reporter

    def metric_samples(self) -> list[MetricSample]:
        """Design §8.5: clients, lines out, disconnects by reason, plus the
        two signals for clients stuck in close-after-flush, and the watched
        drop-copy events that never reached this gateway."""
        return [
            *client_gateway_samples(
                "gwy",
                clients=len(self._clients),
                clients_max=self.config.max_connections,
                msgs_out=self._msgs_out,
                disconnects=self._disconnects,
                slow_clients=self._slow_clients,
                closing_clients=sum(1 for s in self._clients.values() if s.closing),
            ),
            counter("gwy.feed_gaps", self._feed_gaps),
        ]

    def close(self) -> None:
        if self._reporter is not None:
            self._reporter.stop()
        log.info("closing DC gateway")
        for sess in list(self._clients.values()):
            self._disconnect(
                sess, reason=sess.close_reason if sess.closing else "shutdown"
            )
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
            if len(self._clients) >= self.config.max_connections:
                log.warning(
                    "connection rejected: max_connections=%d reached",
                    self.config.max_connections,
                )
                try:
                    conn.close()
                except OSError:
                    pass
                continue
            conn.setblocking(False)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._clients[conn.fileno()] = ClientSession(sock=conn, addr=addr)
            log.debug(
                "connection accepted addr=%s:%s fd=%d", addr[0], addr[1], conn.fileno()
            )

    def _read_client_data(self) -> None:
        if not self._clients:
            return

        # poll(), not select(): select() refuses a descriptor of 1024 or
        # more, which stopped every client being read (review C3).
        poller = select.poll()
        for fd in self._clients:
            poller.register(fd, select.POLLIN)
        try:
            ready = poller.poll(0)
        except OSError as exc:
            log.warning("read poll failed: %s", exc)
            return

        # Any event (data, EOF, error) is settled by recv() below.
        for fd, _event in ready:
            sess = self._clients.get(fd)
            if sess is None:
                continue
            try:
                chunk = sess.sock.recv(4096)
            except BlockingIOError:
                continue
            except OSError as exc:
                # ECONNRESET and the like: the peer is gone. Treating it as
                # "no data yet" left the session to linger until idle timeout.
                log.info("recv failed fd=%d: %s", sess.sock.fileno(), exc)
                self._disconnect(sess, reason="peer_reset")
                continue
            if not chunk:
                self._disconnect(sess, reason="peer_closed")
                continue
            if not sess.heard_from:
                sess.heard_from = True
                log.info(
                    "client connected addr=%s:%s fd=%d",
                    sess.addr[0],
                    sess.addr[1],
                    sess.sock.fileno(),
                )
            sess.in_buffer.extend(chunk)
            sess.last_activity = time.monotonic()
            self._drain_lines(sess)

    def _drain_lines(self, sess: ClientSession) -> None:
        while True:
            if sess.closing:
                # The line that closed it was its last: nothing after it is
                # answered or acted on (a pipelined HELLO, SUB, ...).
                sess.in_buffer.clear()
                return
            idx = sess.in_buffer.find(b"\n")
            if idx < 0:
                # No newline yet: a buffer already at the limit can only
                # become an oversized line, so refuse it now rather than
                # buffer without bound.
                if len(sess.in_buffer) >= _MAX_LINE_BYTES:
                    self._reject_oversized_line(sess)
                    continue
                return
            raw = bytes(sess.in_buffer[:idx])
            del sess.in_buffer[: idx + 1]
            if len(raw) + 1 > _MAX_LINE_BYTES:
                self._reject_oversized_line(sess)
                continue
            line = raw.decode("utf-8", errors="replace")
            self._handle_client_line(sess, line)

    def _reject_oversized_line(self, sess: ClientSession) -> None:
        log.warning(
            "dropping client fd=%d: inbound line exceeds %d bytes",
            sess.sock.fileno(),
            _MAX_LINE_BYTES,
        )
        self._queue_line(
            sess,
            "ERR",
            {"CODE": "BAD_MESSAGE", "DETAIL": f"line exceeds {_MAX_LINE_BYTES} bytes"},
        )
        self._close_after_flush(sess)

    def _flush_client_writes(self) -> None:
        now = time.monotonic()
        for sess in list(self._clients.values()):
            while sess.out_queue:
                payload = sess.out_queue[0]
                unsent = payload[sess.out_offset :]
                try:
                    sent = sess.sock.send(unsent)
                except BlockingIOError, OSError:
                    break
                if sent <= 0:
                    break
                sess.out_offset += sent
                sess.last_activity = time.monotonic()
                if sess.out_offset >= len(payload):
                    sess.out_queue.popleft()
                    sess.out_offset = 0
            if not sess.closing and len(sess.out_queue) > self.config.max_client_queue:
                self._slow_clients += 1
                log.warning(
                    "disconnecting slow client fd=%d queue=%d max=%d",
                    sess.sock.fileno(),
                    len(sess.out_queue),
                    self.config.max_client_queue,
                )
                self._drop_backlog(sess)
                self._queue_line(
                    sess, "ERR", {"CODE": "SLOW_CLIENT", "DETAIL": "queue overflow"}
                )
                self._close_after_flush(sess, reason="slow_client")
            if sess.closing and (
                not sess.out_queue or now - sess.closing_since >= CLOSE_GRACE_SEC
            ):
                self._disconnect(sess, reason=sess.close_reason)

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
            self._feed_seq.pop(gateway_id, None)
            self._sub.setsockopt(zmq.UNSUBSCRIBE, topic.encode("utf-8"))
            return
        self._topic_refcounts[topic] = ref - 1

    def _poll_dc_events(self) -> bool:
        """Relay up to _MAX_DC_EVENTS_PER_LOOP events; True if the budget ran
        out, so the loop goes round again without sleeping."""
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
                return False
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
            self._check_feed_seq(gateway_id, payload.get("seq"))

            line = build_line(
                "DC_FILL",
                {
                    "SEQ": str(payload.get("seq", "")),
                    "ORDER_ID": str(payload.get("order_id", "")),
                    "SYMBOL": str(payload.get("symbol", "")),
                    "FILL_QTY": str(payload.get("fill_qty", "")),
                    "FILL_PRICE": str(payload.get("fill_price", "")),
                    "LIQUIDITY": str(payload.get("liquidity_flag", "")),
                    # When the engine published the fill, and the public
                    # trade(s) it belongs to (trade.executed id, RALF
                    # EXEC_ID); the trade id's prefix is the engine run.
                    "TS": iso_utc(int(payload.get("timestamp", 0)) / 1e9),
                    "TRADE_ID": ",".join(payload.get("trade_ids", [])),
                },
            )
            for fd in fds:
                sess = self._clients.get(fd)
                if sess is not None:
                    self._queue_raw(sess, line)
        return budget == 0

    def _check_feed_seq(self, gateway_id: str, seq: object) -> None:
        """Count the events of a watched ID that never arrived.

        ``seq`` is the engine's per-participant counter. A jump is loss
        between the engine and this gateway; the client sees it as a ``SEQ``
        gap but cannot recover it over DC1, so the operator is told. ``seq``
        not above the last one is a new engine run (it restarts at 1).
        """
        if not isinstance(seq, int):
            return
        last = self._feed_seq.get(gateway_id)
        self._feed_seq[gateway_id] = seq
        if last is None:
            return
        if seq <= last:
            log.info(
                "drop-copy seq for %s went from %d to %d: engine restart",
                gateway_id,
                last,
                seq,
            )
            return
        missed = seq - last - 1
        if missed == 0:
            return
        self._feed_gaps += missed
        self._feed_gaps_unlogged += missed
        now = time.monotonic()
        logged = self._feed_gap_logged_at
        if logged is not None and now - logged < _FEED_GAP_LOG_INTERVAL_SEC:
            return
        self._feed_gap_logged_at = now
        log.warning(
            "drop-copy feed lost %d event(s) for %s: seq %d..%d never arrived "
            "(%d lost since the last warning); DC1 clients cannot recover them",
            missed,
            gateway_id,
            last + 1,
            seq - 1,
            self._feed_gaps_unlogged,
        )
        self._feed_gaps_unlogged = 0

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
            if sess.closing:
                continue  # already on its way out; do not queue another EXIT
            if not sess.authenticated:
                if now - sess.connected_at > HELLO_TIMEOUT_SEC:
                    self._queue_line(
                        sess,
                        "EXIT",
                        {"REASON": "auth_timeout", "TS": iso_utc(time.time())},
                    )
                    self._close_after_flush(sess, reason="auth_timeout")
                continue
            if now - sess.last_activity > self.config.idle_timeout_sec:
                self._queue_line(
                    sess,
                    "EXIT",
                    {"REASON": "idle_timeout", "TS": iso_utc(time.time())},
                )
                self._close_after_flush(sess, reason="idle_timeout")

    # ------------------------------------------------------------------
    # Send/disconnect helpers
    # ------------------------------------------------------------------

    def _queue_line(
        self, sess: ClientSession, msg_type: str, fields: dict[str, str]
    ) -> None:
        self._queue_raw(sess, build_line(msg_type, fields))

    def _queue_raw(self, sess: ClientSession, payload: bytes) -> None:
        if sess.closing:
            # Its final line (ERR / EXIT) is already queued; anything more
            # only grows the backlog of a client that is being dropped.
            return
        sess.out_queue.append(payload)
        self._msgs_out += 1

    def _disconnect(self, sess: ClientSession, reason: str = "unspecified") -> None:
        silent = reason == "peer_closed" and not sess.heard_from
        if not silent:
            self._disconnects[reason] = self._disconnects.get(reason, 0) + 1
        fileno = sess.sock.fileno()
        if sess.gateway_id:
            self._dc_unsubscribe(sess.gateway_id, fileno)
        try:
            sess.sock.close()
        except OSError:
            pass
        self._clients.pop(fileno, None)
        (log.debug if silent else log.info)(
            "client disconnected fd=%d client=%s gateway_id=%s reason=%s",
            fileno,
            sess.client_name or "-",
            sess.gateway_id or "-",
            reason,
        )

    def _close_after_flush(
        self, sess: ClientSession, reason: str = "close_after_flush"
    ) -> None:
        """Send what is queued, then disconnect -- within CLOSE_GRACE_SEC.

        The grace is what makes this a disconnect for a client that has
        stopped reading: its queue never drains, so without a deadline the
        session (and its queue) lived for ever.
        """
        if sess.closing:
            return
        sess.closing = True
        sess.closing_since = time.monotonic()
        sess.close_reason = reason
        log.debug("session fd=%d closing after flush (%s)", sess.sock.fileno(), reason)

    @staticmethod
    def _drop_backlog(sess: ClientSession) -> None:
        """Discard queued lines, keeping one already partly sent: cutting it
        would leave a torn line on the wire ahead of the final ERR."""
        head = sess.out_queue[0] if sess.out_queue and sess.out_offset else None
        sess.out_queue.clear()
        if head is None:
            sess.out_offset = 0
        else:
            sess.out_queue.append(head)

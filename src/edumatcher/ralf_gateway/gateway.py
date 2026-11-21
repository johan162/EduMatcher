"""RALF dissemination gateway.

Subscribes to internal engine events and republishes them over a TCP line
protocol for external clearing/drop-copy/audit parties.
"""

from __future__ import annotations

import errno
import logging
import secrets
import select
import signal
import socket
import time
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import zmq

from edumatcher.health import HealthReporter
from edumatcher.health.samples import client_gateway_samples, counter
from edumatcher.models.generated.health import MetricSample
from edumatcher.messaging.bus import make_subscriber
from edumatcher.models.message import decode, decode_sequence
from edumatcher.ralf_gateway.config import RalfGatewayConfig
from edumatcher.ralf_gateway.protocol import RalfFrame, build_line, iso_utc, parse_line
from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED
from edumatcher.models.generated.system import (
    TOPIC_EOD,
)

_ALLOWED_CHANNELS = frozenset({"CLEARING", "DROP_COPY", "AUDIT"})
_MAX_LINE_BYTES = 4096
_MAX_ENGINE_EVENTS_PER_LOOP = 1000
# Receive high-water mark of the engine SUB. ZeroMQ's default of 1000 drops
# silently during a burst (review H2); the other whole-stream consumers
# (pm-md-gwy, pm-alf-gwy, pm-stats, pm-audit) use 1e5.
_SUB_RCVHWM = 100_000
# After a WARNING about lost engine messages on a topic, further losses on it
# are only counted (gwy.bus_gaps) until this long has passed.
_BUS_GAP_LOG_INTERVAL_SEC = 60.0

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
    #: Set at the first bytes received. A connection closed before that (a
    #: TCP liveness probe) is logged at DEBUG and not counted as a disconnect.
    heard_from: bool = False
    #: The HELLO's checkpoint (0 = none), and whether its EPOCH is this
    #: run's. Each SUB replays what follows it for the pairs it adds.
    last_seq_seen: int = 0
    same_run: bool = True
    #: Replayed lines still queued: the slow-client limit applies to what is
    #: queued beyond them (review C2), and shrinks back as the queue drains.
    replay_allowance: int = 0
    subscriptions: set[tuple[str, str]] = field(default_factory=set)
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


class RalfGateway:
    """RALF TCP gateway process."""

    def __init__(self, config: RalfGatewayConfig) -> None:
        self.config = config
        self._running = False
        # This run's identity on the wire (WELCOME|EPOCH=). Sequences and the
        # journal live in memory and begin again at 1 when the gateway
        # restarts, so a LASTSEQ must name the run it came from: once the new
        # run's stream passes it, a replay would otherwise serve the new
        # run's events as the continuation of the old (review H1). The same
        # rule as pm-md-gwy's RESUME.
        self._epoch = secrets.token_hex(4)
        # Internal watermark used by tests/polling loops to detect that at
        # least one event has been emitted.
        self._next_seq = 1
        # Wire-level SEQ is maintained independently per channel.
        self._next_seq_by_channel: dict[str, int] = {ch: 1 for ch in _ALLOWED_CHANNELS}
        self._journal: deque[JournalEvent] = deque()
        self._clients: dict[int, ClientSession] = {}
        # Health beacon (operator dashboard §8.5); attached by main().
        # slow_clients counts sessions flagged slow, once each; closing_clients
        # is how many are draining their final line (at most CLOSE_GRACE_SEC).
        self._reporter: HealthReporter | None = None
        self._msgs_out = 0
        self._slow_clients = 0
        self._disconnects: dict[str, int] = {}
        self._server: socket.socket | None = None
        self._sub: zmq.Socket[bytes] = make_subscriber(
            config.engine_pub_addr,
            TOPIC_TRADE_EXECUTED,
            TOPIC_EOD,
            rcvhwm=_SUB_RCVHWM,
        )
        # Bus sequence per topic (SequencedPublisher), and what was lost:
        # messages missed per topic, those not yet in a WARNING, and when each
        # topic last logged. RALF numbers the lines it emits, so a loss here
        # leaves every channel's SEQ dense: only this counter shows it.
        self._bus_seq: dict[str, int] = {}
        self._bus_gaps: dict[str, int] = {}
        self._bus_gaps_unlogged: dict[str, int] = {}
        self._bus_gap_logged_at: dict[str, float] = {}
        self._bus_restart_logged_at: dict[str, float] = {}
        self._last_heartbeat = time.monotonic()
        self._trade_counts: dict[str, int] = {}  # symbol → intraday execution count

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
            "listening on %s:%s (engine_pub=%s)",
            self.config.bind_address,
            self.config.port,
            self.config.engine_pub_addr,
        )

        reporter = self._reporter
        try:
            while self._running:
                if reporter is not None:
                    reporter.tick_and_publish(self.metric_samples)
                self._accept_new_clients()
                self._read_client_data()
                backlog = self._poll_engine_events()
                self._send_heartbeat_if_due()
                self._flush_client_writes()
                self._drop_idle_clients()
                self._prune_journal()
                # A pass that used its whole engine budget left events
                # queued: go round again at once (review P1).
                if not backlog:
                    time.sleep(0.01)
            self._flush_for_shutdown()
        finally:
            self.close()

    def _flush_for_shutdown(self) -> None:
        """Say goodbye to every session before a requested stop.

        close() used to close every socket at once: queued lines died with
        it and a client read only EOF, which looks like a crash (review C7).
        Now: one more engine pass, ``EXIT|REASON=shutdown`` to every session
        not already closing, then a flush bounded by SHUTDOWN_FLUSH_SEC;
        close() drops whatever a peer has not taken by then. Not run after a
        crash (run() calls it only when the loop ends normally). The same as
        pm-dc-gwy.
        """
        self._poll_engine_events()
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
        two signals for clients stuck in close-after-flush, and the engine
        messages that never reached this gateway, by topic."""
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
            *(
                counter("gwy.bus_gaps", n, topic)
                for topic, n in sorted(self._bus_gaps.items())
            ),
        ]

    def close(self) -> None:
        if self._reporter is not None:
            self._reporter.stop()
        log.info("closing RALF gateway")
        for sess in list(self._clients.values()):
            self._disconnect(
                sess, reason=sess.close_reason if sess.closing else "shutdown"
            )
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
        # more, which stopped every client being read (review C5).
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
            sess.replay_allowance = min(sess.replay_allowance, len(sess.out_queue))
            limit = self.config.max_client_queue + sess.replay_allowance
            if not sess.closing and len(sess.out_queue) > limit:
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
        epoch = frame.fields.get("EPOCH", "")
        if last_seq > 0 and not epoch:
            self._queue_line(
                sess,
                "ERR",
                {"CODE": "BAD_MESSAGE", "DETAIL": "LASTSEQ requires EPOCH"},
            )
            self._close_after_flush(sess)
            return

        sess.client_id = client
        sess.role = role
        sess.last_seq_seen = last_seq
        sess.same_run = epoch == self._epoch
        sess.authenticated = True

        self._queue_line(
            sess,
            "WELCOME",
            {
                "PROTO": "RALF1",
                "GW": self.config.name,
                "EPOCH": self._epoch,
                "ROLE": role,
                "REPLAY": str(self.config.replay_retention_sec),
                "HBINT": str(self.config.heartbeat_interval_sec),
            },
        )

        log.info(
            "session authenticated fd=%d client=%s role=%s",
            sess.sock.fileno(),
            client,
            role,
        )

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

        before = set(sess.subscriptions)
        for ch in channels:
            for sym in symbols:
                sess.subscriptions.add((ch, sym))

        # Replay here, not at HELLO: what happened between WELCOME and this
        # SUB reached no subscription, and the SNAP below would have covered
        # it (review C1). Same pass, so nothing slips in between.
        if sess.last_seq_seen > 0:
            self._replay_for_sub(sess, before, channels)

        self._queue_line(
            sess,
            "SNAP",
            {
                "CH": ",".join(channels),
                "SYM": ",".join(symbols),
                "SEQ": str(self._latest_seq_for_channels(channels)),
                "TS": iso_utc(time.time()),
            },
        )

    def _handle_unsub(self, sess: ClientSession, frame: RalfFrame) -> None:
        ch_raw = frame.fields.get("CH", "")
        sym_raw = frame.fields.get("SYM", "*")

        channels = [c.strip().upper() for c in ch_raw.split(",") if c.strip()]
        symbols = [s.strip().upper() for s in sym_raw.split(",") if s.strip()]
        if not channels:
            self._queue_line(
                sess, "ERR", {"CODE": "BAD_MESSAGE", "DETAIL": "CH required"}
            )
            return
        if not symbols:
            symbols = ["*"]

        for ch in channels:
            for sym in symbols:
                sess.subscriptions.discard((ch, sym))

    def _replay_for_sub(
        self,
        sess: ClientSession,
        before: set[tuple[str, str]],
        channels: list[str],
    ) -> None:
        """Queue the journal lines after the HELLO's LASTSEQ that the pairs
        this SUB added want and the earlier pairs did not; or REPLAY_MISS
        (the SNAP that follows is the baseline)."""
        last_seq = sess.last_seq_seen
        oldest_by_channel: dict[str, int] = {}
        for evt in self._journal:
            if evt.channel in channels and evt.channel not in oldest_by_channel:
                oldest_by_channel[evt.channel] = evt.seq

        # A miss when LASTSEQ is from another gateway run, is ahead of a
        # channel, or when what follows it has aged out of the journal --
        # including all of it, which used to look like a clean empty replay.
        def missed(ch: str) -> bool:
            latest = self._next_seq_by_channel.get(ch, 1) - 1
            oldest = oldest_by_channel.get(ch, latest + 1)
            return last_seq > latest or last_seq < oldest - 1

        if not sess.same_run or any(missed(ch) for ch in channels):
            self._queue_line(
                sess,
                "ERR",
                {"CODE": "REPLAY_MISS", "DETAIL": "requested seq outside retention"},
            )
            return

        replayed = 0
        for evt in self._journal:
            if (
                evt.seq > last_seq
                and _wants(sess.subscriptions, evt.channel, evt.symbol)
                and not _wants(before, evt.channel, evt.symbol)
            ):
                self._queue_raw(sess, evt.line)
                replayed += 1
        sess.replay_allowance += replayed

    # ------------------------------------------------------------------
    # Engine event mapping
    # ------------------------------------------------------------------

    def _poll_engine_events(self) -> bool:
        """Handle queued engine events; True when the budget ran out.

        Bounded per pass, as in pm-md-gwy and pm-dc-gwy: a burst of trades
        must not starve client reads, heartbeats and flushes.
        """
        budget = _MAX_ENGINE_EVENTS_PER_LOOP
        while budget > 0 and self._sub.poll(timeout=0):
            budget -= 1
            try:
                frames = self._sub.recv_multipart()
            except zmq.ZMQError as exc:
                if exc.errno != errno.EINTR:
                    log.warning("engine SUB recv error errno=%s", exc.errno)
                return False
            try:
                self._check_bus_sequence(frames)
                topic, payload = decode(frames)
            except Exception:
                log.warning("decode error on engine SUB event", exc_info=True)
                continue
            if topic == TOPIC_TRADE_EXECUTED:
                self._handle_trade(payload)
            elif topic == TOPIC_EOD:
                self._handle_eod(payload)
        return budget == 0

    def _check_bus_sequence(self, frames: list[bytes]) -> None:
        """Count engine messages that never arrived (as pm-md-gwy does).

        The engine numbers each topic (``SequencedPublisher``), so a jump
        means ZeroMQ dropped messages at a high-water mark. The gateway
        numbers the lines it emits, so without this neither it nor any RALF
        client could see the loss. A number that goes back is an engine
        restart (sequences begin again at 1), not a gap. Frames without a
        sequence say nothing either way.
        """
        seq = decode_sequence(frames)
        if seq is None:
            return
        topic = frames[0].decode("utf-8", errors="replace")
        last = self._bus_seq.get(topic)
        self._bus_seq[topic] = seq
        if last is None:
            return
        now = time.monotonic()
        if seq <= last:
            logged = self._bus_restart_logged_at.get(topic)
            if logged is None or now - logged >= _BUS_GAP_LOG_INTERVAL_SEC:
                self._bus_restart_logged_at[topic] = now
                log.info(
                    "%s sequence went from %d to %d: publisher restart",
                    topic,
                    last,
                    seq,
                )
            return
        missed = seq - last - 1
        if missed == 0:
            return
        self._bus_gaps[topic] = self._bus_gaps.get(topic, 0) + missed
        unlogged = self._bus_gaps_unlogged.get(topic, 0) + missed
        logged = self._bus_gap_logged_at.get(topic)
        if logged is not None and now - logged < _BUS_GAP_LOG_INTERVAL_SEC:
            self._bus_gaps_unlogged[topic] = unlogged
            return
        self._bus_gap_logged_at[topic] = now
        self._bus_gaps_unlogged[topic] = 0
        log.warning(
            "engine bus dropped %d message(s) on %s: sequence %d..%d never "
            "arrived (%d lost on %s since the last warning); RALF clients "
            "cannot see this loss",
            missed,
            topic,
            last + 1,
            seq - 1,
            unlogged,
            topic,
        )

    def _handle_trade(self, payload: dict[str, Any]) -> None:
        symbol = str(payload.get("symbol", "")).upper()
        qty = str(payload.get("quantity", 0))
        px = str(payload.get("price", 0.0))
        raw_ts_ns = payload.get("ts_ns")
        ts_value = (
            int(raw_ts_ns) / 1_000_000_000 if raw_ts_ns is not None else time.time()
        )
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
            for channel in ("CLEARING", "DROP_COPY", "AUDIT"):
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
        seq = self._next_seq_by_channel.get(channel, 1)
        self._next_seq_by_channel[channel] = seq + 1
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

    def _latest_seq_for_channels(self, channels: list[str]) -> int:
        latest = 0
        for ch in channels:
            latest = max(latest, self._next_seq_by_channel.get(ch, 1) - 1)
        return latest

    def _session_wants(self, sess: ClientSession, channel: str, symbol: str) -> bool:
        return _wants(sess.subscriptions, channel, symbol)

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
        client_id = sess.client_id or "-"
        try:
            sess.sock.close()
        except OSError:
            pass
        self._clients.pop(fileno, None)
        (log.debug if silent else log.info)(
            "client disconnected fd=%d client=%s reason=%s", fileno, client_id, reason
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
        sess.replay_allowance = 0
        if head is None:
            sess.out_offset = 0
        else:
            sess.out_queue.append(head)


def _wants(subscriptions: set[tuple[str, str]], channel: str, symbol: str) -> bool:
    """True when a (channel, symbol) line matches one of ``subscriptions``."""
    for ch, sym in subscriptions:
        if ch == channel and (sym == "*" or sym == symbol):
            return True
    return False

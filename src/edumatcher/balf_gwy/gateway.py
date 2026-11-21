"""BALF TCP gateway runtime.

Accepts binary BALF connections, performs engine authentication, and bridges
BALF frames to/from the engine ZMQ bus.

Design mirrors ``alf_gwy.gateway`` closely:
- Single-threaded loop waiting on a selector (epoll/kqueue) over the
  listener, the client sockets and the SUB socket's notification fd
- One live TCP connection per gateway ID; the ID's order map outlives the
  connection, so a client that logs on again keeps its order ids
- Engine auth via system.gateway_connect / system.gateway_auth.{GW}, every
  gateway-scoped topic subscribed once, by prefix, at start-up
- Closing a session sends system.gateway_disconnect at once, which applies
  the engine-configured disconnect_behaviour (LEAVE_ALL /
  CANCEL_QUOTES_ONLY / CANCEL_ALL)

Defensive posture
-----------------
All inbound data from external clients is treated as untrusted.
- Bad magic byte, wrong version, unknown msg_type → hard close
- Any frame but LOGON before logon → hard close
- Sequence gap or repeat after logon → hard close
- Non-zero flags → log-and-continue (forward-compatible)
- Invalid field values → per-request reject, session stays open
- Rate-limit exceeded → per-request reject (RC_RATE_LIMITED), not an error
- Too many errors in window → hard close
- Outbound queue full → close after the frame being sent (SLOW_CLIENT)
- No inbound traffic for heartbeat_timeout_sec → disconnect
- A closing session that does not drain within the close grace → disconnect
- Engine events lost (sequence gap on the SUB socket) → LOGOUT and close
"""

from __future__ import annotations

import errno
import itertools
import logging
import re
import selectors
import signal
import socket
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, cast

import zmq

from edumatcher.health import HealthReporter
from edumatcher.health.samples import gateway_stats_samples
from edumatcher.models.generated.health import MetricSample
from edumatcher.balf_gwy.codec import (
    BALF_MAGIC,
    BALF_VERSION,
    CANCEL_REASON_EXPIRED,
    CANCEL_REASON_SYSTEM,
    CLIENT_MSG_TYPES,
    FRAME_SIZE,
    HEADER_SIZE,
    LOGON_REJECT_ALREADY_CONNECTED,
    LOGON_REJECT_NOT_CONFIGURED,
    LOGON_REJECT_OTHER,
    LOGON_REJECT_PROTO_MISMATCH,
    MSG_AMEND_ORDER,
    MSG_CANCEL_ORDER,
    MSG_HEARTBEAT,
    MSG_HEARTBEAT_ACK,
    MSG_LOGON,
    MSG_LOGOUT,
    MSG_NEW_ORDER,
    ORDER_TYPE_CODE,
    SIDE_CODE,
    TIF_CODE,
    build_amend_ack,
    build_cancel_ack,
    build_heartbeat,
    build_heartbeat_ack,
    build_logon_ack,
    build_logout,
    build_order_ack,
    build_order_status,
    encode_price,
    parse_amend_order,
    parse_cancel_order,
    parse_heartbeat,
    parse_logon,
    parse_new_order,
)
from edumatcher.balf_gwy.config import BalfGatewayConfig
from edumatcher.balf_gwy.protocol import (
    BalfValidationError,
    RC_INVALID_FIELD,
    RC_OTHER,
    RC_RATE_LIMITED,
    RC_SYMBOL_NOT_CONFIGURED,
    classify_engine_reject,
    validate_amend_flags,
)
from edumatcher.balf_gwy.translate import (
    build_engine_new_order,
    cancel_reason_from_engine,
    engine_amended_to_balf_params,
    engine_fill_to_execution_report_dict,
    engine_triggered_to_stop_triggered_dict,
    new_engine_order_id,
)
from edumatcher.messaging.bus import PushSocket, make_pusher, make_subscriber
from edumatcher.messaging.reject_report import RejectReporter
from edumatcher.models.message import (
    decode,
    decode_sequence,
    make_gateway_connect_msg,
    GATEWAY_HEARTBEAT_INTERVAL_SEC,
    make_gateway_disconnect_msg,
    make_gateway_heartbeat_msg,
    make_order_amend_msg,
    make_order_cancel_msg,
    make_order_new_msg,
    make_orders_request_msg,
    make_symbols_request_msg,
)
from edumatcher.models.price import register_tick_decimals
from edumatcher.models.generated.order import (
    PREFIX_ORDER_ACK,
    PREFIX_ORDER_AMENDED,
    PREFIX_ORDER_CANCELLED,
    PREFIX_ORDER_EXPIRED,
    PREFIX_ORDER_FILL,
    PREFIX_ORDER_TRIGGERED,
    PREFIX_ORDERS,
    serialise_execution_report_balf,
    serialise_stop_triggered_balf,
)
from edumatcher.models.generated.system import (
    PREFIX_GATEWAY_AUTH,
    PREFIX_SYMBOLS,
    TOPIC_STARTUP_RECOVERY,
)

log = logging.getLogger(__name__)

#: A gateway ID as config-gen accepts it (config_gen/gateway_spec.py), at
#: most the 16 bytes of the LOGON field. Same pattern as pm-alf-gwy's.
_GATEWAY_ID_RE = re.compile(r"[A-Z][A-Z0-9_]{0,15}")

#: Event families that change a session's order state, each topic scoped to
#: one gateway (``<prefix><GW>``).
_PRIVATE_EVENT_PREFIXES = (
    PREFIX_ORDER_ACK,
    PREFIX_ORDER_FILL,
    PREFIX_ORDER_CANCELLED,
    PREFIX_ORDER_AMENDED,
    PREFIX_ORDER_EXPIRED,
    PREFIX_ORDER_TRIGGERED,
)

#: Receive high-water mark of the SUB socket. Past it the engine's PUB
#: drops for this subscriber without a trace, and this socket carries every
#: gateway's order events: ZMQ's default of 1 000 held about 9 500
#: fill-sized events in the review's repro before 10 500 of 20 000 vanished
#: (C5). Same depth as pm-alf-gwy and pm-audit.
_SUB_RCVHWM = 200_000

#: Longest wait for socket activity, and the cadence of the housekeeping
#: (client heartbeats, engine heartbeats, timeouts). Same as pm-alf-gwy.
_LOOP_WAIT_SEC = 0.1

#: How long a closing session may take to drain its queue before it is
#: disconnected anyway. Same grace as pm-alf-gwy.
_CLOSE_GRACE_SEC = 5.0

#: How long a requested stop waits for clients to take what they are owed.
_SHUTDOWN_FLUSH_SEC = 2.0

#: Engine events handled per loop iteration. Large enough that a normal
#: burst clears in one pass, small enough that a flood still leaves time
#: for heartbeats and idle-timeout checks.
_ENGINE_DRAIN_BUDGET = 256

# Gateway-process-wide, so a tag can never be mistaken for one of a previous
# session on the same socket.
_request_tags = itertools.count(1)


def _next_request_tag() -> str:
    return f"BALF-{next(_request_tags)}"


def _drop_pending(
    pending: dict[str, "_PendingRequest"],
    by_uuid: dict[str, list[str]],
    request_tag: str,
) -> "_PendingRequest | None":
    """Remove *request_tag* from both the tag map and its per-order index."""
    req = pending.pop(request_tag, None)
    if req is not None:
        tags = by_uuid.get(req.engine_uuid)
        if tags is not None:
            if request_tag in tags:
                tags.remove(request_tag)
            if not tags:
                by_uuid.pop(req.engine_uuid, None)
    return req


def _take_pending(
    pending: dict[str, "_PendingRequest"],
    by_uuid: dict[str, list[str]],
    engine_uuid: str,
    request_tag: str,
) -> "_PendingRequest | None":
    """Resolve an engine result to the request that caused it.

    The tag is authoritative. Without one — an engine build that does not echo
    it, or a system-originated event — the oldest in-flight request for the
    order is the only defensible answer.
    """
    if request_tag and request_tag in pending:
        return _drop_pending(pending, by_uuid, request_tag)
    if request_tag:
        return None
    tags = by_uuid.get(engine_uuid)
    if not tags:
        return None
    return _drop_pending(pending, by_uuid, tags[0])


# ---------------------------------------------------------------------------
# Per-client state
# ---------------------------------------------------------------------------


@dataclass
class _PendingRequest:
    """Tracks an in-flight cancel or amend for later ack correlation."""

    balf_client_order_id: int
    balf_order_id: int
    engine_uuid: str


@dataclass
class _GatewayOrders:
    """Order state of one gateway ID, shared by every session it opens here.

    Why this is not per TCP session: whether an order outlives its session
    is the participant's ``disconnect_behaviour``, and the default
    (``CANCEL_QUOTES_ONLY``) leaves ordinary orders on the book. When this
    map lived in ``ClientSession``, a client that reconnected (LOGOUT,
    heartbeat timeout, ``EVICT_OLD``, a network blip) lost every BALF id of
    its resting orders: their fills were dropped as "unknown order" and a
    cancel was refused, while the engine kept trading them (review H1).

    Keyed by gateway ID and kept for the life of the process, the next
    session of the same ID receives those orders' events under their
    original BALF ids and can cancel or amend them. Ids keep counting up
    across sessions, so an old id never names a new order. It is also kept
    across an engine restart: the engine restores GTC orders under their
    original engine ids, and an entry for an order the engine forgot is
    harmless (a cancel of it is refused by the engine, as it should be).
    A pm-balf-gwy restart starts with no map: the first logon of each ID
    adopts its resting orders (``adopt_pending``, ``_adopt_orders``).

    In-flight cancels and amends live here too, so their result reaches the
    client even when it arrives on the next session of the same ID.
    """

    balf_id_seq: int = 0
    # engine UUID -> (balf_order_id, client_order_id) for accepted new orders
    engine_to_balf: dict[str, tuple[int, int]] = field(default_factory=dict)
    # balf_order_id -> engine UUID for cancel/amend lookup
    balf_to_engine: dict[int, str] = field(default_factory=dict)
    # request_tag -> _PendingRequest for in-flight cancels
    pending_cancel: dict[str, _PendingRequest] = field(default_factory=dict)
    # request_tag -> _PendingRequest for in-flight amends
    pending_amend: dict[str, _PendingRequest] = field(default_factory=dict)
    # engine UUID -> request tags still in flight, oldest first. An engine that
    # does not echo the tag is correlated against the oldest request.
    cancel_tags: dict[str, list[str]] = field(default_factory=dict)
    amend_tags: dict[str, list[str]] = field(default_factory=dict)
    # engine UUID -> symbol (for amend ack price conversion)
    order_symbol: dict[str, str] = field(default_factory=dict)
    # A map this process has just created holds none of the orders the ID
    # left on the book under an earlier pm-balf-gwy: they are asked for at
    # the first logon and adopted from the reply (ORDER_STATUS, L027).
    adopt_pending: bool = False

    def next_balf_id(self) -> int:
        """Allocate the next BALF order ID for this gateway ID (never 0)."""
        self.balf_id_seq += 1
        return self.balf_id_seq

    def forget(self, engine_uuid: str) -> None:
        """Drop a terminal order from both directions of the map."""
        mapping = self.engine_to_balf.pop(engine_uuid, None)
        if mapping is not None:
            self.balf_to_engine.pop(mapping[0], None)
        self.order_symbol.pop(engine_uuid, None)


@dataclass
class ClientSession:
    sock: socket.socket
    addr: tuple[str, int]

    # Authentication state
    gateway_id: str | None = None
    authenticated: bool = False
    auth_pending: bool = False
    # Engine accepted the connect; waiting for the symbol metadata that the
    # LOGON_ACK is withheld for.
    symbols_pending: bool = False
    symbols_requested_at: float = 0.0
    # LOGON_ACK text, held from acceptance until metadata makes it sendable.
    logon_ack_msg: str = ""
    role: str = "TRADER"

    # Buffers
    in_buffer: bytearray = field(default_factory=bytearray)
    out_queue: deque[bytes] = field(default_factory=deque)
    out_offset: int = 0

    # Sequence counters (gateway → client direction)
    outbound_seq: int = 0
    # Last sequence number received from the client (0 until its first
    # numbered frame; LOGON carries 0 and is not part of the sequence).
    inbound_seq: int = 0

    # Timestamps
    connected_at: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)
    last_outbound: float = field(default_factory=time.monotonic)

    # The gateway ID's order state (see _GatewayOrders). Bound at logon to
    # the object shared by every session of that ID; the default is a
    # placeholder no handler reaches before authentication.
    orders: _GatewayOrders = field(default_factory=_GatewayOrders)

    # The peer's receive window is full: output waits for the selector to
    # report the socket writable instead of being retried every pass.
    write_blocked: bool = False

    # Soft-close flag: flush and then disconnect
    closing: bool = False
    # When a closing session is disconnected whether or not its queue has
    # drained (see BalfGateway._close_after_flush).
    close_deadline: float = float("inf")

    # True once gateway_connect was emitted for this session.
    connect_emitted: bool = False

    # Last system.gateway_heartbeat sent to the engine for this session; -inf
    # so the first beat goes out on the first tick after authentication.
    last_engine_heartbeat: float = float("-inf")

    # Rate limiting
    rate_tokens: float = 0.0
    rate_updated: float = field(default_factory=time.monotonic)

    # Error counting for hard-close on abuse
    errors: int = 0
    error_times: deque[float] = field(default_factory=deque)

    def __post_init__(self) -> None:
        self.connected_at = time.monotonic()
        self.last_activity = time.monotonic()
        self.last_outbound = time.monotonic()
        self.rate_updated = time.monotonic()

    def next_seq(self) -> int:
        """Increment and return the next outbound sequence number."""
        self.outbound_seq += 1
        return self.outbound_seq

    @property
    def logon_in_progress(self) -> bool:
        """The gateway ID is claimed but the LOGON_ACK has not gone out yet."""
        return self.auth_pending or self.symbols_pending

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------


class BalfGateway:
    """BALF TCP gateway process."""

    def __init__(self, config: BalfGatewayConfig) -> None:
        self.config = config
        self._running = False

        self._server: socket.socket | None = None
        self._clients: dict[int, ClientSession] = {}
        # epoll/kqueue over the listener, every client socket and the SUB
        # socket's notification fd: one wait costs O(ready), and descriptors
        # above 1023 work (select.select raised ValueError there, review C12).
        self._selector = selectors.DefaultSelector()
        self._next_housekeeping = 0.0

        # gateway_id -> fd for active authenticated sessions
        self._active_gateway_sessions: dict[str, int] = {}

        # Known gateway roles from config (gateway_id -> role string)
        self._gateway_roles: dict[str, str] = {
            gw_id: role for gw_id, role in config.gateway_roles
        }

        # gateway_id -> order state kept across that ID's sessions (H1)
        self._gateway_orders: dict[str, _GatewayOrders] = {}

        # Known symbols (populated from system.symbols response)
        self._known_symbols: set[str] = set()
        # True once the engine has answered system.symbols_request at least
        # once. Until then no order can be priced, so no logon completes.
        self._symbols_ready = False

        # ZMQ sockets
        self._push: PushSocket = make_pusher(config.engine_pull_addr)
        #: Refusals made here, told to the engine so the audit trail holds them.
        self._rejects = RejectReporter(
            "BALF", lambda frames: self._push.send_multipart(frames)
        )
        # Every gateway-scoped family is subscribed once, by prefix, for all
        # gateways, and never changed afterwards. The gateway used to
        # SUBSCRIBE a session's own topics at LOGON, right before sending
        # gateway_connect. A SUBSCRIBE travels on the SUB socket's TCP
        # connection and the engine's PUB applies it asynchronously, while
        # the connect goes over the PUSH connection: an engine that answered
        # first had its reply filtered out, and the client got ten seconds of
        # silence and a close with no LOGON_ACK (review C3: 137 of 300
        # logons in the repro). pm-alf-gwy hit the same race and fixed it the
        # same way. Events of gateways with no session here are skipped in
        # _poll_engine_events before their payload is decoded.
        self._sub: zmq.Socket[bytes] = make_subscriber(
            config.engine_pub_addr,
            PREFIX_GATEWAY_AUTH,
            PREFIX_SYMBOLS,
            PREFIX_ORDERS,
            *_PRIVATE_EVENT_PREFIXES,
            TOPIC_STARTUP_RECOVERY,
            rcvhwm=_SUB_RCVHWM,
        )
        #: Last per-topic sequence seen on each private event topic (see
        #: _check_sequence). Tracked for every gateway, with a session here
        #: or not, so a session that logs on later is not told of a false gap.
        self._topic_seq: dict[str, int] = {}

        self._global_stats: dict[str, int] = {
            "connected_clients": 0,
            "frames_received_total": 0,
            "frames_forwarded_total": 0,
            "frames_rejected_total": 0,
            "protocol_errors_total": 0,
            "auth_failures": 0,
            "disconnects_total": 0,
            "slow_client_disconnects": 0,
            "events_lost": 0,
        }
        # Health beacon (operator dashboard §8.5); attached by main().
        self._reporter: HealthReporter | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

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
            "BALF gateway listening on %s:%d (engine: pull=%s pub=%s)",
            self.config.bind_address,
            self.config.port,
            self.config.engine_pull_addr,
            self.config.engine_pub_addr,
        )

        # The loop waits for work instead of sleeping a fixed 5 ms per pass.
        # With the sleep, a request was read in one pass and the engine's
        # reply, arriving a few hundred microseconds later, was delivered in
        # the next: every NEW_ORDER -> ORDER_ACK took two full sleeps, 10.6 ms
        # median against an engine that answered at once (review P1), for
        # the protocol sold for latency-sensitive clients.
        #
        # The ZMQ socket joins the selector through its notification fd,
        # which is edge-triggered: it signals "something changed", not "a
        # message is waiting". So before every wait the loop asks ZMQ itself
        # (zmq.EVENTS) and does not block while messages are left over from a
        # pass that hit _ENGINE_DRAIN_BUDGET; the same holds for output that
        # is waiting on this gateway rather than on a peer's window.
        self._selector.register(self._server, selectors.EVENT_READ, None)
        zmq_fd = cast(int, self._sub.getsockopt(zmq.FD))
        self._selector.register(zmq_fd, selectors.EVENT_READ, None)
        reporter = self._reporter
        try:
            while self._running:
                if reporter is not None:
                    reporter.tick_and_publish(self.metric_samples)
                now = time.monotonic()
                busy = self._has_pending_writes() or bool(
                    cast(int, self._sub.getsockopt(zmq.EVENTS)) & zmq.POLLIN
                )
                timeout = 0.0 if busy else max(0.0, self._next_housekeeping - now)
                ready: list[ClientSession] = []
                writable: set[int] = set()
                accept = False
                for key, mask in self._selector.select(timeout):
                    if isinstance(key.data, ClientSession):
                        if mask & selectors.EVENT_READ:
                            ready.append(key.data)
                        if mask & selectors.EVENT_WRITE:
                            writable.add(key.fd)
                    elif key.fileobj is self._server:
                        accept = True
                if accept:
                    self._accept_new_clients()
                self._read_client_data(ready)
                self._poll_engine_events()
                now = time.monotonic()
                if now >= self._next_housekeeping:
                    self._next_housekeeping = now + _LOOP_WAIT_SEC
                    self._send_heartbeats_if_due()
                    self._send_engine_heartbeats_if_due()
                    self._drop_stale_clients()
                self._flush_client_writes(writable)
            self._flush_for_shutdown()
        finally:
            self.close()

    def _has_pending_writes(self) -> bool:
        """Output is waiting on this gateway, not on a peer's receive window.

        A write-blocked session is excluded: retrying it before the selector
        reports it writable is a busy-spin, not progress.
        """
        return any(s.out_queue and not s.write_blocked for s in self._clients.values())

    def _set_write_interest(self, session: ClientSession, want: bool) -> None:
        """Wait for writability on ``session`` (want) or stop waiting for it.

        A session that was never registered (tests build sessions without
        accepting them) has nothing to modify; the flag still records it.
        """
        if session.write_blocked == want:
            return
        session.write_blocked = want
        events = selectors.EVENT_READ | (selectors.EVENT_WRITE if want else 0)
        try:
            self._selector.modify(session.sock, events, session)
        except KeyError, ValueError:
            pass

    def _flush_for_shutdown(self) -> None:
        """Give every session what it is owed before a requested stop.

        close() used to disconnect every session at once: frames already
        queued (fills among them) and events the engine had already
        published to this socket died with the sockets, and the client saw
        a reset with no reason (review C6). Now: one drain of the SUB socket,
        a LOGOUT to every authenticated session, then a flush bounded by
        ``_SHUTDOWN_FLUSH_SEC``; whatever a peer has not taken by then is
        dropped by close(). Not run after a crash: the loop's state is not
        to be trusted then (run() calls it only when the loop ends normally).
        """
        self._poll_engine_events()
        for session in list(self._clients.values()):
            if session.authenticated and not session.closing:
                self._queue_frame(session, build_logout(session.next_seq()))
            self._close_after_flush(session, "gateway_shutdown")
        deadline = time.monotonic() + _SHUTDOWN_FLUSH_SEC
        while self._clients and time.monotonic() < deadline:
            # _flush_client_writes disconnects each session whose queue has
            # drained; a peer that takes nothing just keeps its session here
            # until the deadline.
            self._flush_client_writes()
            if self._clients:
                time.sleep(0.01)

    def stop(self) -> None:
        self._running = False

    def attach_reporter(self, reporter: HealthReporter) -> None:
        """Ship this gateway's metrics through ``reporter`` (from main())."""
        self._reporter = reporter

    def metric_samples(self) -> list[MetricSample]:
        """Design §8.5: the existing ``_global_stats``, exported as they are."""
        return gateway_stats_samples(self._global_stats, self.config.max_connections)

    def close(self) -> None:
        if self._reporter is not None:
            self._reporter.stop()
        for session in list(self._clients.values()):
            self._disconnect(session, reason="gateway_shutdown")
        self._clients.clear()
        self._active_gateway_sessions.clear()

        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None
        self._selector.close()

        if not self._push.closed:
            self._push.close()
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
            except OSError:
                break

            if len(self._clients) >= self.config.max_connections:
                try:
                    conn.close()
                except OSError:
                    pass
                log.warning("BALF max_connections reached, rejecting %s", addr)
                continue

            conn.setblocking(False)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            session = ClientSession(sock=conn, addr=addr)
            session.rate_tokens = float(self.config.max_messages_per_second)
            self._clients[conn.fileno()] = session
            self._selector.register(conn, selectors.EVENT_READ, session)
            self._global_stats["connected_clients"] = len(self._clients)
            log.debug("BALF new connection from %s", addr)

    def _read_client_data(self, ready: list[ClientSession]) -> None:
        """Read once from each session the selector reported readable."""
        for session in ready:
            # An earlier session's frames may have closed this one this pass.
            if self._clients.get(session.sock.fileno()) is not session:
                continue
            try:
                chunk = session.sock.recv(8192)
            except BlockingIOError, InterruptedError:
                continue
            except OSError:
                self._disconnect(session, reason="recv_error")
                continue

            if not chunk:
                self._disconnect(session, reason="peer_closed")
                continue

            session.in_buffer.extend(chunk)
            session.last_activity = time.monotonic()
            self._drain_frames(session)

    def _drain_frames(self, session: ClientSession) -> None:
        """Parse and process all complete BALF frames from in_buffer."""
        while len(session.in_buffer) >= HEADER_SIZE:
            if session.closing:
                # Don't process more frames once we're shutting down
                session.in_buffer.clear()
                return

            magic = session.in_buffer[0]
            if magic != BALF_MAGIC:
                log.warning(
                    "BALF bad magic 0x%02X from %s — hard-closing", magic, session.addr
                )
                self._global_stats["protocol_errors_total"] += 1
                self._hard_close(session)
                return

            version = session.in_buffer[1]
            if version != BALF_VERSION:
                log.warning("BALF bad version 0x%02X from %s", version, session.addr)
                self._global_stats["protocol_errors_total"] += 1
                self._hard_close(session)
                return

            msg_type = session.in_buffer[2]
            flags = session.in_buffer[3]
            total = FRAME_SIZE.get(msg_type)

            if total is None:
                log.warning(
                    "BALF unknown msg_type 0x%02X from %s — hard-closing",
                    msg_type,
                    session.addr,
                )
                self._global_stats["protocol_errors_total"] += 1
                self._hard_close(session)
                return

            if len(session.in_buffer) < total:
                break  # Partial frame — wait for more data

            # Extract complete frame
            seq_no = struct.unpack_from("<I", session.in_buffer, 4)[0]
            body = bytes(session.in_buffer[HEADER_SIZE:total])
            del session.in_buffer[:total]

            session.last_activity = time.monotonic()
            self._global_stats["frames_received_total"] += 1

            if flags != 0:
                # Spec says must be 0x00; log and continue (forward-compat)
                log.debug(
                    "BALF non-zero flags 0x%02X from %s (ignoring)", flags, session.addr
                )

            self._process_frame(session, msg_type, seq_no, body)

    def _flush_client_writes(self, writable: set[int] | None = None) -> None:
        """Send what each session has queued.

        ``writable`` is the set of descriptors the selector reported
        writable this pass; a write-blocked session is retried only then.
        ``None`` (shutdown, tests) means "try every session".
        """
        for session in list(self._clients.values()):
            if session.write_blocked:
                if writable is not None and session.sock.fileno() not in writable:
                    continue  # still waiting for the peer to drain its window
                self._set_write_interest(session, False)
            while session.out_queue:
                payload = session.out_queue[0]
                unsent = payload[session.out_offset :]
                try:
                    sent = session.sock.send(unsent)
                except BlockingIOError, InterruptedError:
                    self._set_write_interest(session, True)
                    break
                except OSError:
                    # EPIPE, ECONNRESET, …: the peer is gone for good. Left in
                    # place, a closing session waited for a flush that could
                    # never happen.
                    self._disconnect(session, reason="send_error")
                    break
                if sent <= 0:
                    break
                session.out_offset += sent
                if session.out_offset >= len(payload):
                    session.out_queue.popleft()
                    session.out_offset = 0
                    session.last_outbound = time.monotonic()

            if (
                session.closing
                and not session.out_queue
                and session.sock.fileno() in self._clients
            ):
                self._disconnect(session, reason="session_closed")

    # ------------------------------------------------------------------
    # Frame dispatch
    # ------------------------------------------------------------------

    def _process_frame(
        self,
        session: ClientSession,
        msg_type: int,
        seq_no: int,
        body: bytes,
    ) -> None:
        if not session.authenticated:
            if msg_type == MSG_LOGON:
                # The whole logon is one window, not just the auth wait: since
                # K11 the LOGON_ACK is also held for the symbol metadata, and
                # a client that retried its LOGON then was answered "already
                # connected" by its own session and closed, which also tore
                # down the engine session it was about to get (review C9).
                if session.logon_in_progress:
                    self._queue_frame(
                        session,
                        build_logon_ack(
                            session.gateway_id or "",
                            accepted=False,
                            reject_code=LOGON_REJECT_OTHER,
                            msg="LOGON_ALREADY_PENDING",
                        ),
                    )
                    return

                if not self._allow_message_now(session):
                    self._global_stats["frames_rejected_total"] += 1
                    self._report_reject(session, "RATE_LIMITED", "LOGON rate limited")
                    self._queue_frame(
                        session,
                        build_logon_ack(
                            session.gateway_id or "",
                            accepted=False,
                            reject_code=LOGON_REJECT_OTHER,
                            msg="RATE_LIMITED",
                        ),
                    )
                    return
                self._handle_logon(session, body)
            else:
                log.warning(
                    "BALF pre-auth msg_type 0x%02X from %s — closing",
                    msg_type,
                    session.addr,
                )
                self._global_stats["protocol_errors_total"] += 1
                self._report_reject(
                    session, "AUTH_REQUIRED", f"msg_type 0x{msg_type:02X} before LOGON"
                )
                self._hard_close(session)
            return

        # Authenticated path
        if msg_type == MSG_LOGON:
            # Duplicate LOGON after auth — ignore
            return

        # Every other frame of a logged-on client is numbered 1, 2, 3, …
        # (wrapping to 1 after UINT32_MAX), and the spec makes a gap or a
        # repeat a protocol error. The gateway used to read the number and
        # never look at it, so a client that mis-numbered was never told
        # (review C10, decision Q4). A client that cannot count its own
        # frames will also misread the gateway's, so the session ends here.
        expected = 1 if session.inbound_seq == 0xFFFFFFFF else session.inbound_seq + 1
        if seq_no != expected:
            log.warning(
                "BALF sequence error from %s (%s): expected %d, got %d — hard-closing",
                session.addr,
                session.gateway_id,
                expected,
                seq_no,
            )
            self._global_stats["protocol_errors_total"] += 1
            self._hard_close(session)
            return
        session.inbound_seq = seq_no

        if msg_type not in CLIENT_MSG_TYPES:
            # Client sending a server-only frame type — tolerate but count
            log.debug(
                "BALF client sent server-direction msg 0x%02X (ignoring)", msg_type
            )
            return

        # A LOGOUT is honoured whatever the bucket says: ignoring a client's
        # goodbye leaves a session it believes closed holding its gateway ID.
        if msg_type != MSG_LOGOUT and not self._allow_message_now(session):
            self._global_stats["frames_rejected_total"] += 1
            self._report_reject(session, "RATE_LIMITED", "message rate limited")
            log.debug("BALF rate-limited %s", session.addr)
            self._refuse_rate_limited(session, msg_type, body)
            return

        try:
            if msg_type == MSG_LOGOUT:
                self._handle_logout(session)
            elif msg_type == MSG_NEW_ORDER:
                self._handle_new_order(session, body)
            elif msg_type == MSG_CANCEL_ORDER:
                self._handle_cancel_order(session, body)
            elif msg_type == MSG_AMEND_ORDER:
                self._handle_amend_order(session, body)
            elif msg_type == MSG_HEARTBEAT:
                self._handle_heartbeat(session, body)
            elif msg_type == MSG_HEARTBEAT_ACK:
                pass  # just updates last_activity (already done above)
        except BalfValidationError as exc:
            # Per-request validation failure; session stays open
            self._global_stats["frames_rejected_total"] += 1
            self._register_error(session, exc)
        except Exception as exc:
            log.exception("BALF unexpected error from %s: %s", session.addr, exc)
            self._global_stats["frames_rejected_total"] += 1
            self._register_error(
                session, BalfValidationError(RC_OTHER, "internal error")
            )

    def _refuse_rate_limited(
        self, session: ClientSession, msg_type: int, body: bytes
    ) -> None:
        """Answer a request the token bucket refused (review C2, decision Q2).

        It used to be dropped with no frame at all: a client waiting for the
        ORDER_ACK the spec promises for every NEW_ORDER waited forever, and a
        dropped CANCEL_ORDER left an order live that the client believed was
        being cancelled. Each request now gets its own ack type with
        accepted = 0. It is not counted towards max_errors_before_disconnect:
        the bucket has already absorbed the burst, and ten throttled orders
        in a minute should not end the session. Heartbeats need no answer.
        The bodies are fixed-size, so the parsers cannot fail here.
        """
        if msg_type == MSG_NEW_ORDER:
            parsed = parse_new_order(body)
            self._queue_frame(
                session,
                build_order_ack(
                    client_order_id=int(parsed["client_order_id"]),
                    balf_order_id=0,
                    seq_no=session.next_seq(),
                    accepted=False,
                    reject_code=RC_RATE_LIMITED,
                    reason="RATE_LIMITED",
                ),
            )
        elif msg_type == MSG_CANCEL_ORDER:
            client_order_id, balf_order_id = parse_cancel_order(body)
            self._queue_frame(
                session,
                build_cancel_ack(
                    client_order_id=client_order_id,
                    balf_order_id=balf_order_id,
                    seq_no=session.next_seq(),
                    accepted=False,
                ),
            )
        elif msg_type == MSG_AMEND_ORDER:
            amend = parse_amend_order(body)
            self._queue_frame(
                session,
                build_amend_ack(
                    client_order_id=int(amend["client_order_id"]),
                    balf_order_id=int(amend["balf_order_id"]),
                    seq_no=session.next_seq(),
                    accepted=False,
                ),
            )

    # ------------------------------------------------------------------
    # Message handlers (client → gateway)
    # ------------------------------------------------------------------

    def _handle_logon(self, session: ClientSession, body: bytes) -> None:
        try:
            gw_id, proto_ver = parse_logon(body)
        except ValueError as exc:
            log.warning("BALF malformed LOGON from %s: %s", session.addr, exc)
            self._hard_close(session)
            return

        # Protocol version check
        if proto_ver != BALF_VERSION:
            self._queue_frame(
                session,
                build_logon_ack(
                    gw_id,
                    accepted=False,
                    reject_code=LOGON_REJECT_PROTO_MISMATCH,
                    msg=f"expected version {BALF_VERSION} got {proto_ver}",
                ),
            )
            self._close_after_flush(session)
            return

        # The gateway ID must be one config-gen accepts. The ID is the last
        # dot-separated part of every topic routed back to a session, so an
        # ID with a '.' had its auth reply looked up under another name and
        # sat unanswered until the auth timeout (review C14); anything the
        # pattern refuses can never be a configured participant anyway.
        if not _GATEWAY_ID_RE.fullmatch(gw_id):
            self._queue_frame(
                session,
                build_logon_ack(
                    gw_id,
                    accepted=False,
                    reject_code=LOGON_REJECT_OTHER,
                    msg="gateway_id invalid",
                ),
            )
            self._close_after_flush(session)
            return

        # Duplicate session policy
        if self._gateway_in_use(gw_id):
            if self.config.duplicate_session_policy == "EVICT_OLD":
                # Pending sessions hold the ID too (B4): leaving one in place
                # would make the auth reply ambiguous between two sessions.
                for old_session in self._sessions_holding(gw_id, exclude=session):
                    log.info("BALF evicting old session for %s", gw_id)
                    self._disconnect(old_session, reason="duplicate_login_eviction")
            else:  # REJECT_NEW
                self._queue_frame(
                    session,
                    build_logon_ack(
                        gw_id,
                        accepted=False,
                        reject_code=LOGON_REJECT_ALREADY_CONNECTED,
                        msg=f"{gw_id} already connected",
                    ),
                )
                self._close_after_flush(session)
                return

        session.gateway_id = gw_id
        session.auth_pending = True
        session.connect_emitted = False

        # The auth and symbols replies are already subscribed (by prefix, at
        # start-up), so the connect can go out at once.
        try:
            self._send_to_engine(
                make_gateway_connect_msg(gw_id),
                count_as_command=False,
            )
            session.connect_emitted = True
        except BalfValidationError:
            # Engine unavailable: reject logon immediately so the client can retry
            # instead of waiting on a handshake that will never complete.
            session.auth_pending = False
            session.gateway_id = None
            self._queue_frame(
                session,
                build_logon_ack(
                    gw_id,
                    accepted=False,
                    reject_code=LOGON_REJECT_OTHER,
                    msg="ENGINE_UNAVAILABLE",
                ),
            )

    def _handle_logout(self, session: ClientSession) -> None:
        log.info("BALF LOGOUT from %s (%s)", session.addr, session.gateway_id)
        self._close_after_flush(session, "client_logout")

    def _handle_new_order(self, session: ClientSession, body: bytes) -> None:
        try:
            parsed = parse_new_order(body)
        except ValueError as exc:
            log.warning("BALF malformed NEW_ORDER from %s: %s", session.addr, exc)
            self._global_stats["protocol_errors_total"] += 1
            self._hard_close(session)
            return

        gw_id = self._require_gw(session)
        engine_uuid = new_engine_order_id()
        balf_id = session.orders.next_balf_id()
        client_order_id = int(parsed["client_order_id"])

        symbol = str(parsed["symbol"])
        if symbol not in self._known_symbols:
            # The engine never listed it, so its tick scale is unknown and the
            # price cannot be converted — never fall back to the default (B1).
            unknown = BalfValidationError(
                RC_SYMBOL_NOT_CONFIGURED, f"unknown symbol {symbol}"
            )
            self._queue_frame(
                session,
                build_order_ack(
                    client_order_id=client_order_id,
                    balf_order_id=0,
                    seq_no=session.next_seq(),
                    accepted=False,
                    reject_code=unknown.reject_code,
                    reason=unknown.reason,
                ),
            )
            self._global_stats["frames_rejected_total"] += 1
            self._register_error(session, unknown)
            return

        try:
            order_dict = build_engine_new_order(parsed, gw_id, engine_uuid)
        except BalfValidationError as exc:
            # Counted like every other refusal here; field errors were the
            # one kind missing from frames_rejected_total (review C13).
            self._global_stats["frames_rejected_total"] += 1
            self._queue_frame(
                session,
                build_order_ack(
                    client_order_id=client_order_id,
                    balf_order_id=0,
                    seq_no=session.next_seq(),
                    accepted=False,
                    reject_code=exc.reject_code,
                    reason=exc.reason,
                ),
            )
            self._register_error(session, exc)
            return

        session.orders.engine_to_balf[engine_uuid] = (balf_id, client_order_id)
        session.orders.balf_to_engine[balf_id] = engine_uuid
        session.orders.order_symbol[engine_uuid] = str(parsed["symbol"])

        try:
            self._send_to_engine(make_order_new_msg(order_dict))
        except BalfValidationError as exc:
            session.orders.engine_to_balf.pop(engine_uuid, None)
            session.orders.balf_to_engine.pop(balf_id, None)
            session.orders.order_symbol.pop(engine_uuid, None)
            self._queue_frame(
                session,
                build_order_ack(
                    client_order_id=client_order_id,
                    balf_order_id=0,
                    seq_no=session.next_seq(),
                    accepted=False,
                    reject_code=exc.reject_code,
                    reason=exc.reason,
                ),
            )
            self._global_stats["frames_rejected_total"] += 1
            self._register_error(session, exc)
            return

    def _handle_cancel_order(self, session: ClientSession, body: bytes) -> None:
        try:
            balf_cancel_clordid, balf_order_id = parse_cancel_order(body)
        except ValueError as exc:
            log.warning("BALF malformed CANCEL_ORDER from %s: %s", session.addr, exc)
            self._global_stats["protocol_errors_total"] += 1
            self._hard_close(session)
            return

        if balf_order_id == 0:
            self._queue_frame(
                session,
                build_cancel_ack(
                    client_order_id=balf_cancel_clordid,
                    balf_order_id=0,
                    seq_no=session.next_seq(),
                    accepted=False,
                    cancel_reason=0,
                ),
            )
            return

        gw_id = self._require_gw(session)
        engine_uuid = session.orders.balf_to_engine.get(balf_order_id)
        if engine_uuid is None:
            # Unknown order — send immediate reject
            self._queue_frame(
                session,
                build_cancel_ack(
                    client_order_id=balf_cancel_clordid,
                    balf_order_id=balf_order_id,
                    seq_no=session.next_seq(),
                    accepted=False,
                    cancel_reason=0,
                ),
            )
            return

        # Track the pending cancel for correlation when the result arrives. A
        # pipelined second cancel of the same order gets its own tag (B3).
        request_tag = _next_request_tag()
        session.orders.pending_cancel[request_tag] = _PendingRequest(
            balf_client_order_id=balf_cancel_clordid,
            balf_order_id=balf_order_id,
            engine_uuid=engine_uuid,
        )
        session.orders.cancel_tags.setdefault(engine_uuid, []).append(request_tag)

        try:
            self._send_to_engine(
                make_order_cancel_msg(engine_uuid, gw_id, request_tag=request_tag)
            )
        except BalfValidationError as exc:
            _drop_pending(
                session.orders.pending_cancel, session.orders.cancel_tags, request_tag
            )
            self._queue_frame(
                session,
                build_cancel_ack(
                    client_order_id=balf_cancel_clordid,
                    balf_order_id=balf_order_id,
                    seq_no=session.next_seq(),
                    accepted=False,
                    cancel_reason=CANCEL_REASON_SYSTEM,
                ),
            )
            self._global_stats["frames_rejected_total"] += 1
            self._register_error(session, exc)
            return

    def _handle_amend_order(self, session: ClientSession, body: bytes) -> None:
        try:
            parsed = parse_amend_order(body)
        except ValueError as exc:
            log.warning("BALF malformed AMEND_ORDER from %s: %s", session.addr, exc)
            self._global_stats["protocol_errors_total"] += 1
            self._hard_close(session)
            return

        balf_order_id = int(parsed["balf_order_id"])
        balf_amend_clordid = int(parsed["client_order_id"])

        try:
            validate_amend_flags(int(parsed["amend_flags"]))
        except BalfValidationError as exc:
            self._global_stats["frames_rejected_total"] += 1
            self._queue_frame(
                session,
                build_amend_ack(
                    client_order_id=balf_amend_clordid,
                    balf_order_id=balf_order_id,
                    seq_no=session.next_seq(),
                    accepted=False,
                ),
            )
            self._register_error(session, exc)
            return

        if balf_order_id == 0:
            self._queue_frame(
                session,
                build_amend_ack(
                    client_order_id=balf_amend_clordid,
                    balf_order_id=0,
                    seq_no=session.next_seq(),
                    accepted=False,
                ),
            )
            return

        gw_id = self._require_gw(session)
        engine_uuid = session.orders.balf_to_engine.get(balf_order_id)
        if engine_uuid is None:
            # Unknown order — reject immediately as AMEND_ACK
            self._queue_frame(
                session,
                build_amend_ack(
                    client_order_id=balf_amend_clordid,
                    balf_order_id=balf_order_id,
                    seq_no=session.next_seq(),
                    accepted=False,
                ),
            )
            return

        # Decode price/qty to send to engine
        flags = int(parsed["amend_flags"])
        price_display: float | None = None
        qty: int | None = None

        if flags & 0x01:
            raw_price = parsed["new_price"]
            price_display = int(raw_price) / 1e8 if raw_price else None
        if flags & 0x02:
            raw_qty = int(parsed["new_quantity"])
            qty = raw_qty if raw_qty > 0 else None

        # A flagged field must carry a value. A zero one used to be read as
        # "not flagged", so an amend of price and quantity with a zero price
        # changed only the quantity and was acknowledged as accepted
        # (review C11). Refuse the whole amend instead: the client asked for
        # something the gateway cannot do.
        price_missing = bool(flags & 0x01) and price_display is None
        qty_missing = bool(flags & 0x02) and qty is None
        if price_missing or qty_missing:
            no_field_exc = BalfValidationError(
                RC_INVALID_FIELD, "flagged amend field is zero"
            )
            self._global_stats["frames_rejected_total"] += 1
            self._queue_frame(
                session,
                build_amend_ack(
                    client_order_id=balf_amend_clordid,
                    balf_order_id=balf_order_id,
                    seq_no=session.next_seq(),
                    accepted=False,
                ),
            )
            self._register_error(session, no_field_exc)
            return

        request_tag = _next_request_tag()
        session.orders.pending_amend[request_tag] = _PendingRequest(
            balf_client_order_id=balf_amend_clordid,
            balf_order_id=balf_order_id,
            engine_uuid=engine_uuid,
        )
        session.orders.amend_tags.setdefault(engine_uuid, []).append(request_tag)

        try:
            self._send_to_engine(
                make_order_amend_msg(
                    engine_uuid,
                    gw_id,
                    price=price_display,
                    qty=qty,
                    request_tag=request_tag,
                )
            )
        except BalfValidationError as exc:
            _drop_pending(
                session.orders.pending_amend, session.orders.amend_tags, request_tag
            )
            self._queue_frame(
                session,
                build_amend_ack(
                    client_order_id=balf_amend_clordid,
                    balf_order_id=balf_order_id,
                    seq_no=session.next_seq(),
                    accepted=False,
                ),
            )
            self._global_stats["frames_rejected_total"] += 1
            self._register_error(session, exc)
            return

    def _handle_heartbeat(self, session: ClientSession, body: bytes) -> None:
        try:
            send_time_ns = parse_heartbeat(body)
        except ValueError:
            send_time_ns = 0
        self._queue_frame(
            session, build_heartbeat_ack(send_time_ns, session.next_seq())
        )

    # ------------------------------------------------------------------
    # Engine event polling
    # ------------------------------------------------------------------

    def _poll_engine_events(self) -> None:
        """Drain at most ``_ENGINE_DRAIN_BUDGET`` events, then return.

        A publisher faster than this loop would otherwise keep ``poll()``
        readable forever, so heartbeats, idle timeouts and client writes were
        never reached and every connected client eventually timed out.
        """
        for _ in range(_ENGINE_DRAIN_BUDGET):
            if not self._sub.poll(timeout=0):
                break
            try:
                frames = self._sub.recv_multipart()
            except zmq.ZMQError as exc:
                if exc.errno != errno.EINTR:
                    raise
                break
            try:
                topic = frames[0].decode()
                gap = self._check_sequence(topic, frames)
                # Most of this socket is other gateways' order events (it
                # subscribes every gateway-scoped family by prefix). Their
                # payload is never read, so it is not decoded either; only
                # the sequence above is kept.
                if self._for_absent_gateway(topic):
                    continue
                topic, payload = decode(frames)
            except Exception:
                continue

            try:
                self._dispatch_engine_event(topic, payload)
            except Exception as exc:
                log.exception("BALF error dispatching engine event %s: %s", topic, exc)
            if gap:
                self._end_out_of_sync_session(topic)

    def _check_sequence(self, topic: str, frames: list[bytes]) -> bool:
        """Return True when the engine's events on ``topic`` were dropped.

        The engine numbers each topic (``SequencedPublisher``), and this
        socket subscribes to every private family whole, so a jump means the
        PUB dropped events at the high-water mark: fills, acks or cancels a
        client will never see (review C5). Counted in ``events_lost`` and
        logged for every gateway; the session, if there is one, is ended by
        the caller once the event that revealed the gap has been delivered.
        """
        if not topic.startswith(_PRIVATE_EVENT_PREFIXES):
            return False
        seq = decode_sequence(frames)
        if seq is None:
            return False
        last = self._topic_seq.get(topic)
        self._topic_seq[topic] = seq
        # First sight of the topic, or a lower number: the engine restarted.
        if last is None or seq <= last + 1:
            return False
        missed = seq - last - 1
        self._global_stats["events_lost"] += missed
        log.warning("engine dropped %d event(s) on %s", missed, topic)
        return True

    def _end_out_of_sync_session(self, topic: str) -> None:
        """LOGOUT the session whose events were lost (decision Q5).

        BALF 1.0.0 has no frame that says "reconcile", and its spec tells a
        receiver that is out of sync to reconnect. A session that has
        silently lost a fill is wrong in a way the client cannot see, so it
        is ended; its orders stay reachable from the next session of the
        same ID (WP-BALF01).
        """
        session = self._session_for_gateway(topic.rpartition(".")[2].upper())
        if session is None or session.closing:
            return
        log.warning(
            "BALF closing %s (%s): engine events for it were lost",
            session.addr,
            session.gateway_id,
        )
        self._queue_frame(session, build_logout(session.next_seq()))
        self._close_after_flush(session, "events_lost")

    def _for_absent_gateway(self, topic: str) -> bool:
        """A private order event for a gateway with no session here.

        Exactly what _dispatch_engine_event would drop after decoding it.
        Auth and symbols replies are never in this set.
        """
        return (
            topic.startswith(_PRIVATE_EVENT_PREFIXES)
            and topic.rpartition(".")[2].upper() not in self._active_gateway_sessions
        )

    def _dispatch_engine_event(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == TOPIC_STARTUP_RECOVERY:
            self._handle_engine_restart()
            return

        if topic.startswith(PREFIX_GATEWAY_AUTH):
            gw_id = topic.rsplit(".", 1)[-1].upper()
            self._handle_gateway_auth(gw_id, payload)
            return

        if topic.startswith(PREFIX_SYMBOLS):
            gw_id = topic.rsplit(".", 1)[-1].upper()
            self._handle_symbols_response(gw_id, payload)
            return

        if "." not in topic:
            return

        gw_id = topic.rsplit(".", 1)[-1].upper()
        session = self._session_for_gateway(gw_id)
        if session is None:
            return

        if topic.startswith(PREFIX_ORDERS):
            if session.orders.adopt_pending:
                self._adopt_orders(session, payload)
        elif topic.startswith(PREFIX_ORDER_ACK):
            self._handle_order_ack_event(session, payload)
        elif topic.startswith(PREFIX_ORDER_FILL):
            self._handle_fill_event(session, payload)
        elif topic.startswith(PREFIX_ORDER_CANCELLED):
            self._handle_cancelled_event(session, payload)
        elif topic.startswith(PREFIX_ORDER_AMENDED):
            self._handle_amended_event(session, payload)
        elif topic.startswith(PREFIX_ORDER_EXPIRED):
            self._handle_expired_event(session, payload)
        elif topic.startswith(PREFIX_ORDER_TRIGGERED):
            self._handle_triggered_event(session, payload)

    def _adopt_orders(self, session: ClientSession, payload: dict[str, Any]) -> None:
        """Give each resting order of the ID a BALF id and tell the client
        (ORDER_STATUS): left on the book under an earlier pm-balf-gwy, they
        were out of reach over BALF (L027). The client's own reference comes
        back from the engine's ``client_tag``; an order not entered over BALF
        has none, and is reported with ``client_order_id`` 0."""
        orders = session.orders
        orders.adopt_pending = False
        adopted = 0
        for order in payload.get("orders", []):
            if not isinstance(order, dict):
                continue
            engine_uuid = str(order.get("id", ""))
            if not engine_uuid or engine_uuid in orders.engine_to_balf:
                continue
            tag = order.get("client_tag")
            client_order_id = (
                int(tag)
                if isinstance(tag, str) and tag.isdigit() and int(tag) < 2**64
                else 0
            )
            balf_id = orders.next_balf_id()
            symbol = str(order.get("symbol", ""))
            orders.engine_to_balf[engine_uuid] = (balf_id, client_order_id)
            orders.balf_to_engine[balf_id] = engine_uuid
            orders.order_symbol[engine_uuid] = symbol
            price = order.get("price")
            stop_price = order.get("stop_price")
            self._queue_frame(
                session,
                build_order_status(
                    client_order_id=client_order_id,
                    balf_order_id=balf_id,
                    price=encode_price(price) if price else 0,
                    stop_price=encode_price(stop_price) if stop_price else 0,
                    quantity=int(order.get("quantity", 0)),
                    remaining_qty=int(order.get("remaining_qty", 0)),
                    symbol=symbol,
                    side=SIDE_CODE.get(str(order.get("side")), 0),
                    order_type=ORDER_TYPE_CODE.get(str(order.get("order_type")), 0),
                    tif=TIF_CODE.get(str(order.get("tif")), 0),
                    seq_no=session.next_seq(),
                ),
            )
            adopted += 1
        if adopted:
            log.info(
                "BALF adopted %d resting order(s) of %s", adopted, session.gateway_id
            )

    def _handle_gateway_auth(self, gw_id: str, payload: dict[str, Any]) -> None:
        session = self._find_pending_auth_session(gw_id)
        if session is None:
            return

        accepted = bool(payload.get("accepted", False))
        reason = str(payload.get("reason", ""))
        description = str(payload.get("description", ""))

        if not accepted:
            self._global_stats["auth_failures"] += 1
            session.auth_pending = False
            # The engine refused this connect, so it holds no session for it;
            # a disconnect sent on close would tear down the one that does.
            session.connect_emitted = False
            self._report_reject(
                session, "AUTH_FAILED", reason or f"Gateway not configured: {gw_id}"
            )
            self._queue_frame(
                session,
                build_logon_ack(
                    gw_id,
                    accepted=False,
                    reject_code=LOGON_REJECT_NOT_CONFIGURED,
                    msg=reason or f"Gateway not configured: {gw_id}",
                ),
            )
            self._close_after_flush(session)
            return

        session.auth_pending = False
        session.role = self._gateway_roles.get(gw_id, "TRADER")

        session.logon_ack_msg = (
            description
            or f"gateway={self.config.name} hbint={self.config.heartbeat_interval_sec:.0f}s"
        )

        # Refresh the tick registry on every logon; hold the LOGON_ACK back
        # until the first answer, because an order accepted before it would be
        # priced against the shared two-decimal default (B1).
        # Marked before the send, not after it: _send_to_engine raises when
        # the engine PUSH queue is full, and a session that is neither
        # authenticated nor pending is invisible to both the symbols sweep
        # and the auth timeout (R3).
        session.symbols_pending = True
        session.symbols_requested_at = time.monotonic()
        try:
            self._send_to_engine(
                make_symbols_request_msg(gw_id), count_as_command=False
            )
        except BalfValidationError:
            # The request never left, so no metadata can answer it. Fail the
            # logon now rather than holding the client for the full timeout.
            log.warning("BALF symbol request for %s refused by the engine", gw_id)
            session.symbols_pending = False
            self._queue_frame(
                session,
                build_logon_ack(
                    gw_id,
                    accepted=False,
                    reject_code=LOGON_REJECT_OTHER,
                    msg="ENGINE_UNAVAILABLE",
                ),
            )
            self._close_after_flush(session)
            return

        if self._symbols_ready:
            self._complete_logon(session, gw_id)
            return

        log.info(
            "BALF gateway %s authenticated; LOGON_ACK held for symbol metadata", gw_id
        )

    def _complete_logon(self, session: ClientSession, gw_id: str) -> None:
        """Symbol metadata is in: the session may now trade."""
        session.symbols_pending = False
        session.authenticated = True
        fresh = gw_id not in self._gateway_orders
        session.orders = self._gateway_orders.setdefault(gw_id, _GatewayOrders())
        self._active_gateway_sessions[gw_id] = session.sock.fileno()
        self._queue_frame(
            session,
            build_logon_ack(gw_id, accepted=True, msg=session.logon_ack_msg),
        )
        log.info("BALF gateway authenticated: %s from %s", gw_id, session.addr)
        if fresh:
            session.orders.adopt_pending = True
            try:
                self._send_to_engine(
                    make_orders_request_msg(gw_id), count_as_command=False
                )
            except BalfValidationError:
                session.orders.adopt_pending = False
                log.warning(
                    "BALF could not ask the engine for %s's resting orders; "
                    "orders it left on the book are out of reach this run",
                    gw_id,
                )

    def _handle_symbols_response(self, gw_id: str, payload: dict[str, Any]) -> None:
        entries = payload.get("symbols", [])
        if not isinstance(entries, list):
            return
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            sym = str(entry.get("symbol", "")).upper()
            if not sym:
                continue
            self._known_symbols.add(sym)
            tick_decimals = entry.get("tick_decimals")
            if isinstance(tick_decimals, int):
                register_tick_decimals(sym, tick_decimals)

        self._symbols_ready = True
        for session in list(self._clients.values()):
            if session.symbols_pending and session.gateway_id:
                self._complete_logon(session, session.gateway_id)

    def _handle_engine_restart(self) -> None:
        """A restarted engine holds no sessions: every one here is dead."""
        lost = [
            s for s in self._clients.values() if s.authenticated or s.logon_in_progress
        ]
        # A first start also announces itself; with no session to lose it is
        # not news.
        log.log(
            logging.WARNING if lost else logging.INFO,
            "engine (re)started; closing %d BALF session(s) so their clients log on again",
            len(lost),
        )
        # Its symbol configuration may have changed with it.
        self._known_symbols.clear()
        self._symbols_ready = False

        for session in lost:
            gw_id = session.gateway_id or ""
            if session.authenticated:
                self._queue_frame(session, build_logout(session.next_seq()))
            else:
                self._queue_frame(
                    session,
                    build_logon_ack(
                        gw_id,
                        accepted=False,
                        reject_code=LOGON_REJECT_OTHER,
                        msg="ENGINE_RESTARTED",
                    ),
                )
            session.authenticated = False
            session.auth_pending = False
            session.symbols_pending = False
            # The restarted engine never had this session: a disconnect sent
            # on close would name a gateway it has already forgotten.
            session.connect_emitted = False
            if self._active_gateway_sessions.get(gw_id) == session.sock.fileno():
                self._active_gateway_sessions.pop(gw_id, None)
            self._close_after_flush(session)

    def _handle_order_ack_event(
        self, session: ClientSession, payload: dict[str, Any]
    ) -> None:
        engine_uuid = str(payload.get("order_id", ""))
        accepted = bool(payload.get("accepted", False))
        reason = str(payload.get("reason", ""))
        request_tag = str(payload.get("request_tag") or "")

        # A refusal may belong to an in-flight cancel or amend; correlate it by
        # the tag that request carried (B3).
        if not accepted:
            pending = _take_pending(
                session.orders.pending_cancel,
                session.orders.cancel_tags,
                engine_uuid,
                request_tag,
            )
            if pending is not None:
                self._queue_frame(
                    session,
                    build_cancel_ack(
                        client_order_id=pending.balf_client_order_id,
                        balf_order_id=pending.balf_order_id,
                        seq_no=session.next_seq(),
                        accepted=False,
                    ),
                )
                return

            pending = _take_pending(
                session.orders.pending_amend,
                session.orders.amend_tags,
                engine_uuid,
                request_tag,
            )
            if pending is not None:
                self._queue_frame(
                    session,
                    build_amend_ack(
                        client_order_id=pending.balf_client_order_id,
                        balf_order_id=pending.balf_order_id,
                        seq_no=session.next_seq(),
                        accepted=False,
                    ),
                )
                return

        # New order ack
        mapping = session.orders.engine_to_balf.get(engine_uuid)
        if mapping is None:
            # No mapping — late/stray ack from engine, ignore
            return

        balf_order_id, client_order_id = mapping
        # The order's ts_ns as the engine carries it back on its ack: the
        # entry time pm-balf-gwy stamped on the order (translate.py), the one
        # clock the whole order flow agrees on. This used to be the
        # gateway's clock when the ack happened to be processed (review C1).
        # 0 lets build_order_ack fall back to now for an ack without it.
        ts_ns = int(payload.get("ts_ns") or 0)

        if not accepted:
            # Terminal rejection — clean up mapping
            session.orders.forget(engine_uuid)
            reject_code = classify_engine_reject(payload.get("reject_code"), reason)
            self._queue_frame(
                session,
                build_order_ack(
                    client_order_id=client_order_id,
                    balf_order_id=0,
                    seq_no=session.next_seq(),
                    accepted=False,
                    reject_code=reject_code,
                    reason=reason[:25],
                    timestamp_ns=ts_ns,
                ),
            )
        else:
            self._queue_frame(
                session,
                build_order_ack(
                    client_order_id=client_order_id,
                    balf_order_id=balf_order_id,
                    seq_no=session.next_seq(),
                    accepted=True,
                    timestamp_ns=ts_ns,
                ),
            )

    def _handle_fill_event(
        self, session: ClientSession, payload: dict[str, Any]
    ) -> None:
        engine_uuid = str(payload.get("order_id", ""))
        mapping = session.orders.engine_to_balf.get(engine_uuid)
        if mapping is None:
            return

        balf_order_id, client_order_id = mapping
        params = engine_fill_to_execution_report_dict(
            payload, balf_order_id, client_order_id
        )

        self._queue_frame(
            session,
            serialise_execution_report_balf(params, seq_no=session.next_seq()),
        )

        # Clean up mapping on full fill
        status_str = str(payload.get("status", "")).upper()
        if status_str == "FILLED":
            session.orders.forget(engine_uuid)

    def _handle_cancelled_event(
        self, session: ClientSession, payload: dict[str, Any]
    ) -> None:
        engine_uuid = str(payload.get("order_id", ""))

        pending = _take_pending(
            session.orders.pending_cancel,
            session.orders.cancel_tags,
            engine_uuid,
            str(payload.get("request_tag") or ""),
        )
        if pending is not None:
            self._queue_frame(
                session,
                build_cancel_ack(
                    client_order_id=pending.balf_client_order_id,
                    balf_order_id=pending.balf_order_id,
                    seq_no=session.next_seq(),
                    accepted=True,
                    cancel_reason=0,
                ),
            )
        else:
            # System-originated cancel (SMP, session-end, etc.)
            mapping = session.orders.engine_to_balf.get(engine_uuid)
            if mapping is not None:
                balf_order_id, client_order_id = mapping
                self._queue_frame(
                    session,
                    build_cancel_ack(
                        client_order_id=client_order_id,
                        balf_order_id=balf_order_id,
                        seq_no=session.next_seq(),
                        accepted=True,
                        cancel_reason=cancel_reason_from_engine(payload),
                    ),
                )

        # Clean up mapping
        session.orders.forget(engine_uuid)

    def _handle_amended_event(
        self, session: ClientSession, payload: dict[str, Any]
    ) -> None:
        engine_uuid = str(payload.get("order_id", ""))

        pending = _take_pending(
            session.orders.pending_amend,
            session.orders.amend_tags,
            engine_uuid,
            str(payload.get("request_tag") or ""),
        )
        if pending is None:
            return

        symbol = session.orders.order_symbol.get(engine_uuid, "")
        params = engine_amended_to_balf_params(
            payload,
            pending.balf_order_id,
            pending.balf_client_order_id,
            symbol,
        )
        self._queue_frame(
            session,
            build_amend_ack(seq_no=session.next_seq(), **params),
        )

    def _handle_triggered_event(
        self, session: ClientSession, payload: dict[str, Any]
    ) -> None:
        """A stop fired: STOP_TRIGGERED, ahead of its execution reports."""
        mapping = session.orders.engine_to_balf.get(str(payload.get("order_id", "")))
        if mapping is None:
            return
        balf_order_id, client_order_id = mapping
        params = engine_triggered_to_stop_triggered_dict(
            payload, balf_order_id, client_order_id
        )
        self._queue_frame(
            session, serialise_stop_triggered_balf(params, seq_no=session.next_seq())
        )

    def _handle_expired_event(
        self, session: ClientSession, payload: dict[str, Any]
    ) -> None:
        engine_uuid = str(payload.get("order_id", ""))
        mapping = session.orders.engine_to_balf.pop(engine_uuid, None)
        if mapping is None:
            return
        balf_order_id, client_order_id = mapping
        session.orders.balf_to_engine.pop(balf_order_id, None)
        session.orders.order_symbol.pop(engine_uuid, None)
        # Notify client: an expiry is an exchange-side cancel with its own
        # reason code, so it is not confused with an unexplained one.
        self._queue_frame(
            session,
            build_cancel_ack(
                client_order_id=client_order_id,
                balf_order_id=balf_order_id,
                seq_no=session.next_seq(),
                accepted=True,
                cancel_reason=CANCEL_REASON_EXPIRED,
            ),
        )

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def _send_heartbeats_if_due(self) -> None:
        now = time.monotonic()
        for session in self._clients.values():
            if not session.authenticated:
                continue
            if now - session.last_outbound >= self.config.heartbeat_interval_sec:
                self._queue_frame(session, build_heartbeat(session.next_seq()))

    def _send_engine_heartbeats_if_due(self) -> None:
        """Tell the engine each authenticated session is still alive.

        One beat per session, so a session that closes stops being reported
        and the engine frees its ID if the disconnect never reaches it.
        """
        now = time.monotonic()
        for session in self._clients.values():
            if not session.authenticated or session.closing or not session.gateway_id:
                continue
            if now - session.last_engine_heartbeat < GATEWAY_HEARTBEAT_INTERVAL_SEC:
                continue
            session.last_engine_heartbeat = now
            log.debug("engine heartbeat sent gateway_id=%s", session.gateway_id)
            self._send_to_engine(
                make_gateway_heartbeat_msg(session.gateway_id),
                count_as_command=False,
                require_engine=False,
            )

    def _drop_stale_clients(self) -> None:
        now = time.monotonic()
        for session in list(self._clients.values()):
            if session.closing:
                if now >= session.close_deadline:
                    log.info(
                        "BALF %s (%s) did not drain in %.0f s — closing",
                        session.addr,
                        session.gateway_id,
                        _CLOSE_GRACE_SEC,
                    )
                    self._disconnect(session, reason="close_timeout")
                continue
            if not session.authenticated:
                if session.symbols_pending:
                    # Engine accepted the connect but never sent its symbols;
                    # fail the logon with a reason instead of hanging it.
                    if (
                        now - session.symbols_requested_at
                        > self.config.auth_timeout_sec
                    ):
                        log.warning(
                            "BALF no symbol metadata for %s — rejecting logon",
                            session.gateway_id,
                        )
                        session.symbols_pending = False
                        self._queue_frame(
                            session,
                            build_logon_ack(
                                session.gateway_id or "",
                                accepted=False,
                                reject_code=LOGON_REJECT_OTHER,
                                msg="SYMBOLS_UNAVAILABLE",
                            ),
                        )
                        self._close_after_flush(session)
                    continue
                # Unauthenticated sessions must send LOGON within auth_timeout
                if now - session.connected_at > self.config.auth_timeout_sec:
                    log.warning(
                        "BALF auth timeout from %s — hard-closing", session.addr
                    )
                    self._hard_close(session)
                continue
            # Heartbeat / idle timeout for authenticated sessions
            if now - session.last_activity > self.config.heartbeat_timeout_sec:
                log.info(
                    "BALF heartbeat timeout for %s (%s)",
                    session.addr,
                    session.gateway_id,
                )
                self._disconnect(session, reason="heartbeat_timeout")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_gw(self, session: ClientSession) -> str:
        if not session.gateway_id or not session.authenticated:
            raise BalfValidationError(RC_OTHER, "not authenticated")
        return session.gateway_id

    def _allow_message_now(self, session: ClientSession) -> bool:
        now = time.monotonic()
        elapsed = now - session.rate_updated
        session.rate_updated = now
        max_rate = float(self.config.max_messages_per_second)
        session.rate_tokens = min(max_rate, session.rate_tokens + elapsed * max_rate)
        if session.rate_tokens < 1.0:
            return False
        session.rate_tokens -= 1.0
        return True

    def _report_reject(self, session: ClientSession, code: str, reason: str) -> None:
        """Tell the engine this gateway refused ``session``, for the audit trail."""
        self._rejects.report(
            code,
            session.gateway_id or "",
            f"{session.addr[0]}:{session.addr[1]}",
            reason,
        )

    def _register_error(self, session: ClientSession, exc: BalfValidationError) -> None:
        session.errors += 1
        now = time.monotonic()
        session.error_times.append(now)
        # Purge old errors outside the window
        cutoff = now - self.config.error_window_sec
        while session.error_times and session.error_times[0] < cutoff:
            session.error_times.popleft()

        if len(session.error_times) >= self.config.max_errors_before_disconnect:
            log.warning(
                "BALF too many errors from %s (%s) — hard-closing",
                session.addr,
                session.gateway_id,
            )
            self._global_stats["protocol_errors_total"] += 1
            self._hard_close(session)

    def _queue_frame(self, session: ClientSession, frame: bytes) -> None:
        # Whatever a session was owed was queued before it started closing
        # (the closing LOGON_ACK or LOGOUT is queued first, then the close).
        # A frame queued after that would follow a LOGOUT, or, after a
        # SLOW_CLIENT cut, land behind a queue that was thrown away.
        if session.closing:
            return
        if len(session.out_queue) >= self.config.max_client_queue:
            self._global_stats["slow_client_disconnects"] += 1
            log.warning(
                "BALF outbound queue full for %s — SLOW_CLIENT close", session.addr
            )
            # Keep a frame the client has already started to receive, or its
            # stream would end inside it, with the next frame's header read
            # as the rest of its body (review C15).
            head = session.out_queue[0] if session.out_offset else None
            session.out_queue.clear()
            if head is not None:
                session.out_queue.append(head)
            self._close_after_flush(session, "slow_client")
            return
        session.out_queue.append(frame)

    def _close_after_flush(
        self, session: ClientSession, reason: str = "session_closed"
    ) -> None:
        """End the session once its queue has drained, or at the grace.

        A closing session used to be skipped by every timeout and keep its
        gateway ID until the queue drained, which for a peer that stopped
        reading (a hung process, a link that drops without FIN) was never:
        under REJECT_NEW the participant was locked out of pm-balf-gwy for
        good, while the engine, no longer getting heartbeats, had long freed
        the ID (review C4). Three changes:

        - the engine is told now, and the ID is released now, so the client
          can log on again at once and the engine applies the participant's
          disconnect behaviour when the client asked for it, not when the
          flush happens to finish. Doing one without the other would race:
          a new session's gateway_connect would reach an engine still
          holding the old one;
        - the session gets a deadline, enforced in _drop_stale_clients;
        - nothing more is queued to it (see _queue_frame).
        """
        if session.closing:
            return
        session.closing = True
        session.close_deadline = time.monotonic() + _CLOSE_GRACE_SEC
        self._release_gateway_id(session, reason)

    def _release_gateway_id(self, session: ClientSession, reason: str) -> None:
        """Tell the engine the session is gone and free its gateway ID."""
        gw_id = session.gateway_id
        if not gw_id:
            return
        if self._active_gateway_sessions.get(gw_id) == session.sock.fileno():
            self._active_gateway_sessions.pop(gw_id, None)
        if session.connect_emitted:
            self._send_to_engine(
                make_gateway_disconnect_msg(gw_id, reason=reason),
                count_as_command=False,
                require_engine=False,
            )
            session.connect_emitted = False

    def _hard_close(self, session: ClientSession) -> None:
        """Immediately close without flushing — for protocol violations."""
        session.closing = True
        session.out_queue.clear()
        session.out_offset = 0
        self._disconnect(session, reason="protocol_error")

    def _disconnect(self, session: ClientSession, *, reason: str) -> None:
        gw_id = session.gateway_id
        self._release_gateway_id(session, reason)

        fd = session.sock.fileno()
        try:
            self._selector.unregister(session.sock)
        except KeyError, ValueError:
            pass  # never registered (built outside _accept_new_clients)
        session.close()
        self._clients.pop(fd, None)
        self._global_stats["connected_clients"] = len(self._clients)
        self._global_stats["disconnects_total"] += 1
        log.info("BALF disconnected %s (%s) reason=%s", session.addr, gw_id, reason)

    def _send_to_engine(
        self,
        frames: list[bytes],
        *,
        count_as_command: bool = True,
        require_engine: bool = True,
    ) -> None:
        try:
            self._push.send_multipart(frames)
        except zmq.Again:
            if self._push.closed:
                return
            if not require_engine:
                return
            raise BalfValidationError(RC_OTHER, "ENGINE_UNAVAILABLE")
        except zmq.ZMQError as exc:
            if self._push.closed:
                return
            if exc.errno == zmq.EAGAIN:
                if not require_engine:
                    return
                raise BalfValidationError(RC_OTHER, "ENGINE_UNAVAILABLE")
            raise
        if count_as_command:
            self._global_stats["frames_forwarded_total"] += 1

    def _gateway_in_use(self, gw_id: str) -> bool:
        if gw_id in self._active_gateway_sessions:
            return True
        return bool(self._sessions_holding(gw_id))

    def _sessions_holding(
        self, gw_id: str, *, exclude: ClientSession | None = None
    ) -> list[ClientSession]:
        """Every session that claims *gw_id*, authenticated or still logging on."""
        return [
            s
            for s in self._clients.values()
            if s is not exclude
            and s.gateway_id == gw_id
            and not s.closing
            and (s.authenticated or s.logon_in_progress)
        ]

    def _session_for_gateway(self, gw_id: str) -> ClientSession | None:
        fd = self._active_gateway_sessions.get(gw_id)
        if fd is None:
            return None
        return self._clients.get(fd)

    def _find_pending_auth_session(self, gw_id: str) -> ClientSession | None:
        for session in self._clients.values():
            if session.gateway_id == gw_id and session.auth_pending:
                return session
        return None

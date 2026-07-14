"""BALF TCP gateway runtime.

Accepts binary BALF connections, performs engine authentication, and bridges
BALF frames to/from the engine ZMQ bus.

Design mirrors ``alf_gwy.gateway`` closely:
- Single-threaded select() loop (no threads, no async)
- One TCP connection per gateway ID
- Engine auth via system.gateway_connect / system.gateway_auth.{GW}
- Disconnect triggers system.gateway_disconnect which applies engine-configured
  disconnect_behaviour (LEAVE_ALL / CANCEL_QUOTES_ONLY / CANCEL_ALL)

Defensive posture
-----------------
All inbound data from external clients is treated as untrusted.
- Bad magic byte → hard close
- Unknown msg_type → hard close
- Frame body too short → hard close
- Non-zero flags → log-and-continue (forward-compatible)
- Invalid field values → per-request reject, session stays open
- Rate-limit exceeded → reject + error counter
- Too many errors in window → hard close
- Outbound queue full → SLOW_CLIENT close
- Inbound idle / heartbeat timeout → graceful disconnect
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
from typing import Any

import zmq

from edumatcher.balf_gwy.codec import (
    BALF_MAGIC,
    BALF_VERSION,
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
    build_amend_ack,
    build_cancel_ack,
    build_execution_report,
    build_heartbeat,
    build_heartbeat_ack,
    build_logon_ack,
    build_order_ack,
    now_ns,
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
    classify_engine_reason,
    validate_amend_flags,
)
from edumatcher.balf_gwy.translate import (
    build_engine_new_order,
    engine_amended_to_balf_params,
    engine_fill_to_balf_params,
    new_engine_order_id,
)
from edumatcher.messaging.bus import make_pusher, make_subscriber
from edumatcher.models.message import (
    decode,
    make_gateway_connect_msg,
    make_gateway_disconnect_msg,
    make_order_amend_msg,
    make_order_cancel_msg,
    make_order_new_msg,
    make_symbols_request_msg,
)
from edumatcher.models.price import register_tick_decimals

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-client state
# ---------------------------------------------------------------------------


@dataclass
class _PendingRequest:
    """Tracks an in-flight cancel or amend for later ack correlation."""

    balf_client_order_id: int
    balf_order_id: int


@dataclass
class ClientSession:
    sock: socket.socket
    addr: tuple[str, int]

    # Authentication state
    gateway_id: str | None = None
    authenticated: bool = False
    auth_pending: bool = False
    role: str = "TRADER"

    # Buffers
    in_buffer: bytearray = field(default_factory=bytearray)
    out_queue: deque[bytes] = field(default_factory=deque)
    out_offset: int = 0

    # Sequence counters (gateway → client direction)
    outbound_seq: int = 0

    # Timestamps
    last_activity: float = field(default_factory=time.monotonic)
    last_outbound: float = field(default_factory=time.monotonic)

    # Order ID mapping
    # balf_id_seq: monotonically increasing, starts at 1 per session
    _balf_id_seq: int = 0
    # engine UUID -> (balf_order_id, client_order_id) for accepted new orders
    engine_to_balf: dict[str, tuple[int, int]] = field(default_factory=dict)
    # balf_order_id -> engine UUID for cancel/amend lookup
    balf_to_engine: dict[int, str] = field(default_factory=dict)
    # engine UUID -> _PendingRequest for in-flight cancels
    pending_cancel: dict[str, _PendingRequest] = field(default_factory=dict)
    # engine UUID -> _PendingRequest for in-flight amends
    pending_amend: dict[str, _PendingRequest] = field(default_factory=dict)
    # engine UUID -> symbol (for amend ack price conversion)
    order_symbol: dict[str, str] = field(default_factory=dict)

    # ZMQ topic subscriptions owned by this session
    subscriptions: set[str] = field(default_factory=set)

    # Soft-close flag: flush and then disconnect
    closing: bool = False

    # Rate limiting
    rate_tokens: float = 0.0
    rate_updated: float = field(default_factory=time.monotonic)

    # Error counting for hard-close on abuse
    errors: int = 0
    error_times: deque[float] = field(default_factory=deque)

    def __post_init__(self) -> None:
        self.last_activity = time.monotonic()
        self.last_outbound = time.monotonic()
        self.rate_updated = time.monotonic()

    def next_balf_id(self) -> int:
        """Allocate the next session-scoped BALF order ID (never 0)."""
        self._balf_id_seq += 1
        return self._balf_id_seq

    def next_seq(self) -> int:
        """Increment and return the next outbound sequence number."""
        self.outbound_seq += 1
        return self.outbound_seq

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

        # gateway_id -> fd for active authenticated sessions
        self._active_gateway_sessions: dict[str, int] = {}

        # ZMQ topic ref-counts (shared across clients)
        self._topic_refcounts: dict[str, int] = {}

        # Known gateway roles from config (gateway_id -> role string)
        self._gateway_roles: dict[str, str] = {
            gw_id: role for gw_id, role in config.gateway_roles
        }

        # Known symbols (populated from system.symbols response)
        self._known_symbols: set[str] = set()

        # ZMQ sockets
        self._push: zmq.Socket[bytes] = make_pusher(config.engine_pull_addr)
        self._sub: zmq.Socket[bytes] = make_subscriber(
            config.engine_pub_addr,
            "session.state",
            "trade.executed",
        )

        self._global_stats: dict[str, int] = {
            "connected_clients": 0,
            "frames_received_total": 0,
            "frames_forwarded_total": 0,
            "frames_rejected_total": 0,
            "protocol_errors_total": 0,
            "auth_failures": 0,
            "disconnects_total": 0,
            "slow_client_disconnects": 0,
        }

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

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
            "BALF gateway listening on %s:%d (engine: pull=%s pub=%s)",
            self.config.bind_address,
            self.config.port,
            self.config.engine_pull_addr,
            self.config.engine_pub_addr,
        )

        try:
            while self._running:
                self._accept_new_clients()
                self._read_client_data()
                self._poll_engine_events()
                self._send_heartbeats_if_due()
                self._flush_client_writes()
                self._drop_stale_clients()
                time.sleep(0.005)
        finally:
            self.close()

    def stop(self) -> None:
        self._running = False

    def close(self) -> None:
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
            self._global_stats["connected_clients"] = len(self._clients)
            log.debug("BALF new connection from %s", addr)

    def _read_client_data(self) -> None:
        if not self._clients:
            return
        try:
            ready, _, _ = select.select(
                [s.sock for s in self._clients.values()], [], [], 0
            )
        except OSError:
            return

        for sock_obj in ready:
            session = self._clients.get(sock_obj.fileno())
            if session is None:
                continue
            try:
                chunk = session.sock.recv(8192)
            except (BlockingIOError, OSError):
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
            import struct as _struct

            seq_no = _struct.unpack_from("<I", session.in_buffer, 4)[0]
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

    def _flush_client_writes(self) -> None:
        for session in list(self._clients.values()):
            while session.out_queue:
                payload = session.out_queue[0]
                unsent = payload[session.out_offset :]
                try:
                    sent = session.sock.send(unsent)
                except (BlockingIOError, OSError):
                    break
                if sent <= 0:
                    break
                session.out_offset += sent
                if session.out_offset >= len(payload):
                    session.out_queue.popleft()
                    session.out_offset = 0
                    session.last_outbound = time.monotonic()

            if session.closing and not session.out_queue:
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
                self._handle_logon(session, body)
            else:
                log.warning(
                    "BALF pre-auth msg_type 0x%02X from %s — closing",
                    msg_type,
                    session.addr,
                )
                self._global_stats["protocol_errors_total"] += 1
                self._hard_close(session)
            return

        # Authenticated path
        if msg_type == MSG_LOGON:
            # Duplicate LOGON after auth — ignore
            return

        if msg_type not in CLIENT_MSG_TYPES:
            # Client sending a server-only frame type — tolerate but count
            log.debug(
                "BALF client sent server-direction msg 0x%02X (ignoring)", msg_type
            )
            return

        if not self._allow_message_now(session):
            self._global_stats["frames_rejected_total"] += 1
            log.debug("BALF rate-limited %s", session.addr)
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

    # ------------------------------------------------------------------
    # Message handlers (client → gateway)
    # ------------------------------------------------------------------

    def _handle_logon(self, session: ClientSession, body: bytes) -> None:
        try:
            gw_id, proto_ver = parse_logon(body)
        except (ValueError, struct_error) as exc:
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

        # Gateway ID must be a non-empty ASCII string
        if not gw_id or len(gw_id) > 16:
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
                old_fd = self._active_gateway_sessions.get(gw_id)
                if old_fd is not None:
                    old_session = self._clients.get(old_fd)
                    if old_session is not None:
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

        # Subscribe to the auth reply topic and send gateway_connect to engine
        auth_topic = f"system.gateway_auth.{gw_id}"
        self._subscribe_topic(auth_topic)
        session.subscriptions.add(auth_topic)
        try:
            self._send_to_engine(
                make_gateway_connect_msg(gw_id),
                count_as_command=False,
            )
        except BalfValidationError:
            # Engine unavailable: reject logon immediately so the client can retry
            # instead of waiting on a handshake that will never complete.
            session.auth_pending = False
            session.gateway_id = None
            if auth_topic in session.subscriptions:
                session.subscriptions.remove(auth_topic)
            self._unsubscribe_topic(auth_topic)
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
        self._close_after_flush(session)

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
        balf_id = session.next_balf_id()
        client_order_id = int(parsed["client_order_id"])

        try:
            order_dict = build_engine_new_order(parsed, gw_id, engine_uuid)
        except BalfValidationError as exc:
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

        session.engine_to_balf[engine_uuid] = (balf_id, client_order_id)
        session.balf_to_engine[balf_id] = engine_uuid
        session.order_symbol[engine_uuid] = str(parsed["symbol"])

        try:
            self._send_to_engine(make_order_new_msg(order_dict))
        except BalfValidationError as exc:
            session.engine_to_balf.pop(engine_uuid, None)
            session.balf_to_engine.pop(balf_id, None)
            session.order_symbol.pop(engine_uuid, None)
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
        self._global_stats["frames_forwarded_total"] += 1

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
        engine_uuid = session.balf_to_engine.get(balf_order_id)
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

        # Track the pending cancel for correlation when ack arrives
        session.pending_cancel[engine_uuid] = _PendingRequest(
            balf_client_order_id=balf_cancel_clordid,
            balf_order_id=balf_order_id,
        )

        try:
            self._send_to_engine(make_order_cancel_msg(engine_uuid, gw_id))
        except BalfValidationError as exc:
            session.pending_cancel.pop(engine_uuid, None)
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
        self._global_stats["frames_forwarded_total"] += 1

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
        engine_uuid = session.balf_to_engine.get(balf_order_id)
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

        if price_display is None and qty is None:
            no_field_exc = BalfValidationError(
                RC_INVALID_FIELD, "no valid amend field set"
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
            self._register_error(session, no_field_exc)
            return

        session.pending_amend[engine_uuid] = _PendingRequest(
            balf_client_order_id=balf_amend_clordid,
            balf_order_id=balf_order_id,
        )

        try:
            self._send_to_engine(
                make_order_amend_msg(engine_uuid, gw_id, price=price_display, qty=qty)
            )
        except BalfValidationError as exc:
            session.pending_amend.pop(engine_uuid, None)
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
        self._global_stats["frames_forwarded_total"] += 1

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
        while self._sub.poll(timeout=0):
            try:
                topic, payload = decode(self._sub.recv_multipart())
            except zmq.ZMQError as exc:
                if exc.errno != errno.EINTR:
                    raise
                break
            except Exception:
                continue

            try:
                self._dispatch_engine_event(topic, payload)
            except Exception as exc:
                log.exception("BALF error dispatching engine event %s: %s", topic, exc)

    def _dispatch_engine_event(self, topic: str, payload: dict[str, Any]) -> None:
        if topic.startswith("system.gateway_auth."):
            gw_id = topic.rsplit(".", 1)[-1].upper()
            self._handle_gateway_auth(gw_id, payload)
            return

        if topic.startswith("system.symbols."):
            gw_id = topic.rsplit(".", 1)[-1].upper()
            self._handle_symbols_response(gw_id, payload)
            return

        if "." not in topic:
            return

        gw_id = topic.rsplit(".", 1)[-1].upper()
        session = self._session_for_gateway(gw_id)
        if session is None:
            return

        if topic.startswith("order.ack."):
            self._handle_order_ack_event(session, payload)
        elif topic.startswith("order.fill."):
            self._handle_fill_event(session, payload)
        elif topic.startswith("order.cancelled."):
            self._handle_cancelled_event(session, payload)
        elif topic.startswith("order.amended."):
            self._handle_amended_event(session, payload)
        elif topic.startswith("order.expired."):
            self._handle_expired_event(session, payload)

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
        session.authenticated = True
        session.role = self._gateway_roles.get(gw_id, "TRADER")
        self._active_gateway_sessions[gw_id] = session.sock.fileno()

        for t in self._gateway_topics(gw_id):
            if t not in session.subscriptions:
                self._subscribe_topic(t)
                session.subscriptions.add(t)

        msg = (
            description
            or f"gateway={self.config.name} hbint={self.config.heartbeat_interval_sec:.0f}s"
        )
        self._queue_frame(
            session,
            build_logon_ack(
                gw_id,
                accepted=True,
                msg=msg,
            ),
        )

        # Request symbol metadata to populate tick registry
        self._send_to_engine(make_symbols_request_msg(gw_id), count_as_command=False)
        log.info("BALF gateway authenticated: %s from %s", gw_id, session.addr)

    def _handle_symbols_response(self, gw_id: str, payload: dict[str, Any]) -> None:
        symbols_raw = payload.get("symbols", [])
        symbol_meta = payload.get("symbol_meta", {})
        if not isinstance(symbols_raw, list):
            return
        for s in symbols_raw:
            sym = str(s).upper()
            self._known_symbols.add(sym)
            if isinstance(symbol_meta, dict):
                meta = symbol_meta.get(sym)
                if isinstance(meta, dict):
                    tick_size = meta.get("tick_size")
                    if isinstance(tick_size, (int, float)) and tick_size > 0:
                        decimals = self._infer_decimals(float(tick_size))
                        if decimals is not None:
                            register_tick_decimals(sym, decimals)

    def _handle_order_ack_event(
        self, session: ClientSession, payload: dict[str, Any]
    ) -> None:
        engine_uuid = str(payload.get("order_id", ""))
        accepted = bool(payload.get("accepted", False))
        reason = str(payload.get("reason", ""))

        # Determine whether this ack is for a cancel, amend, or new order
        pending_cancel = session.pending_cancel.get(engine_uuid)
        pending_amend = session.pending_amend.get(engine_uuid)

        if pending_cancel and not accepted:
            del session.pending_cancel[engine_uuid]
            self._queue_frame(
                session,
                build_cancel_ack(
                    client_order_id=pending_cancel.balf_client_order_id,
                    balf_order_id=pending_cancel.balf_order_id,
                    seq_no=session.next_seq(),
                    accepted=False,
                ),
            )
            return

        if pending_amend and not accepted:
            del session.pending_amend[engine_uuid]
            self._queue_frame(
                session,
                build_amend_ack(
                    client_order_id=pending_amend.balf_client_order_id,
                    balf_order_id=pending_amend.balf_order_id,
                    seq_no=session.next_seq(),
                    accepted=False,
                ),
            )
            return

        # New order ack
        mapping = session.engine_to_balf.get(engine_uuid)
        if mapping is None:
            # No mapping — late/stray ack from engine, ignore
            return

        balf_order_id, client_order_id = mapping

        if not accepted:
            # Terminal rejection — clean up mapping
            session.engine_to_balf.pop(engine_uuid, None)
            session.balf_to_engine.pop(balf_order_id, None)
            session.order_symbol.pop(engine_uuid, None)
            reject_code = classify_engine_reason(reason)
            self._queue_frame(
                session,
                build_order_ack(
                    client_order_id=client_order_id,
                    balf_order_id=0,
                    seq_no=session.next_seq(),
                    accepted=False,
                    reject_code=reject_code,
                    reason=reason[:25],
                ),
            )
        else:
            ts_ns = now_ns()
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
        mapping = session.engine_to_balf.get(engine_uuid)
        if mapping is None:
            return

        balf_order_id, client_order_id = mapping
        params = engine_fill_to_balf_params(payload, balf_order_id, client_order_id)

        self._queue_frame(
            session,
            build_execution_report(seq_no=session.next_seq(), **params),
        )

        # Clean up mapping on full fill
        status_str = str(payload.get("status", "")).upper()
        if status_str == "FILLED":
            session.engine_to_balf.pop(engine_uuid, None)
            session.balf_to_engine.pop(balf_order_id, None)
            session.order_symbol.pop(engine_uuid, None)

    def _handle_cancelled_event(
        self, session: ClientSession, payload: dict[str, Any]
    ) -> None:
        engine_uuid = str(payload.get("order_id", ""))

        pending = session.pending_cancel.pop(engine_uuid, None)
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
            mapping = session.engine_to_balf.get(engine_uuid)
            if mapping is not None:
                balf_order_id, client_order_id = mapping
                self._queue_frame(
                    session,
                    build_cancel_ack(
                        client_order_id=client_order_id,
                        balf_order_id=balf_order_id,
                        seq_no=session.next_seq(),
                        accepted=True,
                        cancel_reason=255,  # system-originated
                    ),
                )

        # Clean up mapping
        mapping = session.engine_to_balf.pop(engine_uuid, None)
        if mapping:
            session.balf_to_engine.pop(mapping[0], None)
        session.order_symbol.pop(engine_uuid, None)

    def _handle_amended_event(
        self, session: ClientSession, payload: dict[str, Any]
    ) -> None:
        engine_uuid = str(payload.get("order_id", ""))

        pending = session.pending_amend.pop(engine_uuid, None)
        if pending is None:
            return

        symbol = session.order_symbol.get(engine_uuid, "")
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

    def _handle_expired_event(
        self, session: ClientSession, payload: dict[str, Any]
    ) -> None:
        engine_uuid = str(payload.get("order_id", ""))
        mapping = session.engine_to_balf.pop(engine_uuid, None)
        if mapping is None:
            return
        balf_order_id, client_order_id = mapping
        session.balf_to_engine.pop(balf_order_id, None)
        session.order_symbol.pop(engine_uuid, None)
        # Notify client: expired orders are reported as system-originated cancels
        self._queue_frame(
            session,
            build_cancel_ack(
                client_order_id=client_order_id,
                balf_order_id=balf_order_id,
                seq_no=session.next_seq(),
                accepted=True,
                cancel_reason=CANCEL_REASON_SYSTEM,
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

    def _drop_stale_clients(self) -> None:
        now = time.monotonic()
        for session in list(self._clients.values()):
            if session.closing:
                continue
            if not session.authenticated:
                # Unauthenticated sessions must send LOGON within auth_timeout
                if now - session.last_activity > self.config.auth_timeout_sec:
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
        if len(session.out_queue) >= self.config.max_client_queue:
            self._global_stats["slow_client_disconnects"] += 1
            log.warning(
                "BALF outbound queue full for %s — SLOW_CLIENT close", session.addr
            )
            session.out_queue.clear()
            session.out_offset = 0
            session.closing = True
            return
        session.out_queue.append(frame)

    def _close_after_flush(self, session: ClientSession) -> None:
        session.closing = True

    def _hard_close(self, session: ClientSession) -> None:
        """Immediately close without flushing — for protocol violations."""
        session.closing = True
        session.out_queue.clear()
        session.out_offset = 0
        self._disconnect(session, reason="protocol_error")

    def _disconnect(self, session: ClientSession, *, reason: str) -> None:
        gw_id = session.gateway_id

        if (
            gw_id
            and session.authenticated
            and self._active_gateway_sessions.get(gw_id) == session.sock.fileno()
        ):
            self._active_gateway_sessions.pop(gw_id, None)
            self._send_to_engine(
                make_gateway_disconnect_msg(gw_id, reason=reason),
                count_as_command=False,
                require_engine=False,
            )

        # Unsubscribe all ZMQ topics owned by this session
        for t in list(session.subscriptions):
            self._unsubscribe_topic(t)
        session.subscriptions.clear()

        fd = session.sock.fileno()
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

    def _subscribe_topic(self, topic: str) -> None:
        ref = self._topic_refcounts.get(topic, 0)
        if ref == 0:
            self._sub.setsockopt(zmq.SUBSCRIBE, topic.encode("utf-8"))
        self._topic_refcounts[topic] = ref + 1

    def _unsubscribe_topic(self, topic: str) -> None:
        ref = self._topic_refcounts.get(topic, 0)
        if ref <= 1:
            self._topic_refcounts.pop(topic, None)
            self._sub.setsockopt(zmq.UNSUBSCRIBE, topic.encode("utf-8"))
            return
        self._topic_refcounts[topic] = ref - 1

    def _gateway_topics(self, gw_id: str) -> tuple[str, ...]:
        return (
            f"system.gateway_auth.{gw_id}",
            f"system.symbols.{gw_id}",
            f"order.ack.{gw_id}",
            f"order.fill.{gw_id}",
            f"order.cancelled.{gw_id}",
            f"order.amended.{gw_id}",
            f"order.expired.{gw_id}",
        )

    def _gateway_in_use(self, gw_id: str) -> bool:
        if gw_id in self._active_gateway_sessions:
            return True
        for session in self._clients.values():
            if session.gateway_id == gw_id and (
                session.auth_pending or session.authenticated
            ):
                return True
        return False

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

    @staticmethod
    def _infer_decimals(tick_size: float) -> int | None:
        if tick_size <= 0:
            return None
        s = f"{tick_size:.10f}".rstrip("0")
        if "." not in s:
            return 0
        return len(s.split(".")[1])


# Keep a local reference to struct.error for bare-except avoidance
try:
    import struct as _struct_mod

    struct_error = _struct_mod.error
except ImportError:
    struct_error = Exception  # type: ignore[misc,assignment]

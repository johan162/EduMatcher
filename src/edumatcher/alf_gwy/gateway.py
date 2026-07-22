"""ALF TCP gateway runtime.

This process accepts ALF text commands over TCP, validates them defensively,
and bridges traffic to/from the engine ZMQ bus.
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

from edumatcher.alf_gwy.config import AlfGatewayConfig
from edumatcher.alf_gwy.protocol import (
    AlfProtocolError,
    ValidationError,
    build_line,
    iso_utc,
    parse_alf_line,
    safe_float,
    safe_int,
    validate_hello_fields,
)
from edumatcher.messaging.bus import make_pusher, make_subscriber
from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType
from edumatcher.models.message import (
    decode,
    make_combo_cancel_msg,
    make_combo_order_msg,
    make_gateway_connect_msg,
    make_gateway_disconnect_msg,
    make_kill_switch_msg,
    make_oco_cancel_msg,
    make_oco_order_msg,
    make_order_amend_msg,
    make_order_cancel_msg,
    make_order_new_msg,
    make_orders_request_msg,
    make_quote_bootstrap_request_msg,
    make_quote_cancel_msg,
    make_quote_legs_request_msg,
    make_quote_new_msg,
    make_symbols_request_msg,
)
from edumatcher.models.order import Order, OrderType, Side, SmpAction, TIF
from edumatcher.models.price import register_tick_decimals, to_ticks

_MAX_LINE_BYTES = 4096
_MAX_ENGINE_EVENTS_PER_LOOP = 1000
_MAX_DC_EVENTS_PER_LOOP = 1000
# Topic prefix used by edumatcher.engine.drop_copy.DropCopyPublisher for live
# (non-replay) fill events -- see docs/user-guide/200-drop-copy.md.
_DC_EVENT_TOPIC_PREFIX = "drop_copy.event."

log = logging.getLogger(__name__)


@dataclass
class ClientSession:
    sock: socket.socket
    addr: tuple[str, int]
    gateway_id: str | None = None
    client_name: str = ""
    role: str = "TRADER"
    authenticated: bool = False
    auth_pending: bool = False
    dc_enabled: bool = False
    subscriptions: set[str] = field(default_factory=set)
    out_queue: deque[bytes] = field(default_factory=deque)
    out_offset: int = 0
    in_buffer: bytearray = field(default_factory=bytearray)
    closing: bool = False
    connected_at: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)
    last_outbound: float = field(default_factory=time.monotonic)
    connect_emitted: bool = False
    lines_received: int = 0
    lines_sent: int = 0
    errors: int = 0
    error_times: deque[float] = field(default_factory=deque)
    rate_tokens: float = 0.0
    rate_updated: float = 0.0

    def __post_init__(self) -> None:
        self.connected_at = time.monotonic()
        self.last_activity = time.monotonic()
        self.last_outbound = time.monotonic()
        self.rate_updated = time.monotonic()

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class AlfGateway:
    """ALF TCP gateway process."""

    def __init__(self, config: AlfGatewayConfig) -> None:
        self.config = config
        self._running = False

        self._server: socket.socket | None = None
        self._clients: dict[int, ClientSession] = {}
        self._active_gateway_sessions: dict[str, int] = {}
        self._topic_refcounts: dict[str, int] = {}
        self._dc_topic_refcounts: dict[str, int] = {}
        self._gateway_roles = {gw_id: role for gw_id, role in config.gateway_roles}
        # Shared ref-data snapshot state loaded from engine symbols responses.
        self._known_symbols: set[str] = set()
        self._symbols_snapshot_loaded = False

        self._push: zmq.Socket[bytes] = make_pusher(config.engine_pull_addr)
        self._sub: zmq.Socket[bytes] = make_subscriber(
            config.engine_pub_addr,
            "session.state",
            "trade.executed",
            "circuit_breaker.halt.",
            "circuit_breaker.resume.",
        )
        # Separate SUB socket for the engine's drop-copy feed (:5557). Kept
        # distinct from self._sub (:5556) because it is a different ZMQ PUB
        # address entirely -- see edumatcher.engine.drop_copy. No topics are
        # subscribed here at startup; DC|ON subscribes this session's own
        # drop_copy.event.<GW_ID> topic on demand (see _dc_subscribe_topic).
        self._dc_sub: zmq.Socket[bytes] = make_subscriber(config.drop_copy_pub_addr)

        self._global_stats: dict[str, int] = {
            "connected_clients": 0,
            "commands_received_total": 0,
            "commands_forwarded_total": 0,
            "commands_rejected_total": 0,
            "errors_total": 0,
            "disconnects_total": 0,
            "slow_client_disconnects": 0,
            "auth_failures": 0,
        }

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
            "listening on %s:%s (engine_pull=%s engine_pub=%s)",
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
                self._poll_dc_events()
                self._send_heartbeats_if_due()
                self._flush_client_writes()
                self._drop_idle_clients()
                time.sleep(0.01)
        finally:
            self.close()

    def stop(self) -> None:
        log.info("stop requested")
        self._running = False

    def close(self) -> None:
        log.info("closing ALF gateway")
        for session in list(self._clients.values()):
            self._disconnect(session, reason="gateway_shutdown")
        self._clients.clear()
        self._active_gateway_sessions.clear()

        if self._server is not None:
            self._server.close()
            self._server = None

        if not self._push.closed:
            self._push.close()
        if not self._sub.closed:
            self._sub.close()
        if not self._dc_sub.closed:
            self._dc_sub.close()

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
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            if len(self._clients) >= self.config.max_connections:
                try:
                    conn.close()
                except OSError:
                    pass
                continue

            session = ClientSession(sock=conn, addr=addr)
            session.rate_tokens = float(self.config.max_commands_per_second)
            self._clients[conn.fileno()] = session
            self._global_stats["connected_clients"] = len(self._clients)

    def _read_client_data(self) -> None:
        if not self._clients:
            return

        readable = [session.sock for session in self._clients.values()]
        try:
            ready, _, _ = select.select(readable, [], [], 0)
        except OSError:
            return

        for sock_obj in ready:
            session = self._clients.get(sock_obj.fileno())
            if session is None:
                continue

            try:
                chunk = session.sock.recv(4096)
            except (BlockingIOError, OSError):
                continue

            if not chunk:
                self._disconnect(session, reason="peer_closed")
                continue

            session.in_buffer.extend(chunk)
            session.last_activity = time.monotonic()

            if (
                b"\n" not in session.in_buffer
                and len(session.in_buffer) > _MAX_LINE_BYTES
            ):
                session.in_buffer.clear()
                self._register_error(
                    session,
                    "BAD_MESSAGE",
                    "Line exceeds 4096 bytes",
                    close_connection=False,
                )
                continue

            self._drain_lines(session)

    def _drain_lines(self, session: ClientSession) -> None:
        while True:
            idx = session.in_buffer.find(b"\n")
            if idx < 0:
                return

            raw = bytes(session.in_buffer[:idx])
            del session.in_buffer[: idx + 1]

            if len(raw) + 1 > _MAX_LINE_BYTES:
                self._register_error(
                    session,
                    "BAD_MESSAGE",
                    "Line exceeds 4096 bytes",
                    close_connection=False,
                )
                continue

            try:
                line = raw.decode("utf-8").replace("\x00", "?")
            except UnicodeDecodeError:
                self._register_error(
                    session,
                    "BAD_MESSAGE",
                    "Line is not valid UTF-8",
                    close_connection=False,
                )
                continue
            try:
                self._handle_client_line(session, line)
            except Exception:
                self._register_error(
                    session,
                    "INTERNAL_ERROR",
                    "unexpected error",
                    close_connection=False,
                )

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
                    session.lines_sent += 1
                    session.last_outbound = time.monotonic()

            if session.closing and not session.out_queue:
                self._disconnect(session, reason="session_closed")

    # ------------------------------------------------------------------
    # Protocol dispatch
    # ------------------------------------------------------------------

    def _handle_client_line(self, session: ClientSession, line: str) -> None:
        session.lines_received += 1
        self._global_stats["commands_received_total"] += 1

        try:
            frame = parse_alf_line(line)
        except AlfProtocolError as exc:
            self._register_error(
                session, "BAD_MESSAGE", str(exc), close_connection=False
            )
            return

        cmd = frame.command
        fields = frame.fields

        if not session.authenticated:
            if cmd == "HELLO" and session.auth_pending:
                self._register_error(
                    session,
                    "HELLO_ALREADY_PENDING",
                    "HELLO already received; awaiting auth result",
                    close_connection=False,
                )
                return

            if not self._allow_command_now(session):
                self._register_error(
                    session,
                    "RATE_LIMITED",
                    "Too many commands per second",
                    close_connection=False,
                )
                return
            if cmd != "HELLO":
                self._register_error(
                    session,
                    "AUTH_REQUIRED",
                    "HELLO must be the first message",
                    close_connection=True,
                )
                return
            try:
                self._handle_hello(session, fields)
            except ValidationError as exc:
                close_conn = exc.code not in {
                    "ENGINE_UNAVAILABLE",
                    "HELLO_ALREADY_PENDING",
                }
                self._register_error(
                    session, exc.code, exc.detail, close_connection=close_conn
                )
            return

        if cmd == "HELLO":
            # Ignore duplicate HELLO after successful auth.
            return

        if cmd == "PING":
            self._queue_line(session, "PONG", {"TS": iso_utc(time.time())})
            return

        if cmd in {"EXIT", "QUIT"}:
            self._close_after_flush(session)
            return

        if not self._allow_command_now(session):
            self._register_error(
                session,
                "RATE_LIMITED",
                "Too many commands per second",
                close_connection=False,
            )
            return

        try:
            self._dispatch_authenticated(session, cmd, fields)
        except ValidationError as exc:
            self._global_stats["commands_rejected_total"] += 1
            self._register_error(session, exc.code, exc.detail, close_connection=False)
        except Exception:
            self._global_stats["commands_rejected_total"] += 1
            self._register_error(
                session,
                "INTERNAL_ERROR",
                "unexpected error",
                close_connection=False,
            )

    def _dispatch_authenticated(
        self, session: ClientSession, cmd: str, fields: dict[str, str]
    ) -> None:
        if cmd == "NEW":
            self._handle_new(session, fields)
            return
        if cmd == "AMEND":
            self._handle_amend(session, fields)
            return
        if cmd == "CANCEL":
            self._handle_cancel(session, fields)
            return
        if cmd == "QUOTE":
            self._handle_quote(session, fields)
            return
        if cmd == "QUOTE_CANCEL":
            self._handle_quote_cancel(session, fields)
            return
        if cmd == "KILL":
            symbol = fields.get("SYM", "")
            self._send_to_engine(
                make_kill_switch_msg(self._require_gw(session), symbol)
            )
            return
        if cmd == "DC":
            self._handle_dc(session, fields)
            return
        if cmd == "SYMBOLS":
            self._send_to_engine(make_symbols_request_msg(self._require_gw(session)))
            return
        if cmd == "ORDERS":
            self._send_to_engine(make_orders_request_msg(self._require_gw(session)))
            return
        if cmd == "QBOOT":
            self._send_to_engine(
                make_quote_bootstrap_request_msg(
                    self._require_gw(session), fields.get("SYM", "")
                )
            )
            return
        if cmd == "QLEGS":
            self._send_to_engine(
                make_quote_legs_request_msg(
                    self._require_gw(session),
                    fields.get("SYM", ""),
                    fields.get("SHOW", "ACTIVE"),
                )
            )
            return

        if cmd in {"STATUS", "POS", "HELP"}:
            raise ValidationError(
                "UNKNOWN_COMMAND",
                f"{cmd} is interactive-only and not supported by pm-alf-gwy",
            )

        raise ValidationError("UNKNOWN_COMMAND", f"Unknown command: {cmd}")

    def _handle_hello(self, session: ClientSession, fields: dict[str, str]) -> None:
        if session.auth_pending:
            raise ValidationError(
                "HELLO_ALREADY_PENDING",
                "HELLO already received; awaiting auth result",
            )

        client, _proto, gateway_id = validate_hello_fields(fields)

        if self._gateway_in_use(gateway_id):
            self._register_error(
                session,
                "GATEWAY_ALREADY_CONNECTED",
                f"Gateway already connected: {gateway_id}",
                close_connection=True,
            )
            return

        session.client_name = client
        session.gateway_id = gateway_id
        session.auth_pending = True
        session.connect_emitted = False

        auth_topic = f"system.gateway_auth.{gateway_id}"
        self._subscribe_topic(auth_topic)
        session.subscriptions.add(auth_topic)
        try:
            self._send_to_engine(
                make_gateway_connect_msg(gateway_id), count_as_command=False
            )
        except ValidationError:
            session.auth_pending = False
            session.gateway_id = None
            session.client_name = ""
            if auth_topic in session.subscriptions:
                session.subscriptions.remove(auth_topic)
                self._unsubscribe_topic(auth_topic)
            raise
        session.connect_emitted = True

    def _handle_new(self, session: ClientSession, fields: dict[str, str]) -> None:
        req_type = fields.get("TYPE", "LIMIT")
        if req_type == "OCO":
            self._handle_new_oco(session, fields)
            return
        if req_type == "COMBO":
            self._handle_new_combo(session, fields)
            return
        self._handle_new_single(session, fields)

    def _handle_new_single(
        self, session: ClientSession, fields: dict[str, str]
    ) -> None:
        symbol = self._required_str(fields, "SYM")
        self._validate_symbol(symbol)

        side = self._parse_side(self._required_str(fields, "SIDE"))
        order_type = self._parse_order_type(self._required_str(fields, "TYPE"))
        quantity = safe_int(self._required_str(fields, "QTY"), "QTY", min_value=1)
        tif = self._parse_tif(fields.get("TIF", "DAY"))
        # SMP omitted entirely means "let the engine apply this gateway's
        # configured smp_action default" -- distinct from an explicit
        # SMP=NONE, which means the client deliberately allows self-trades.
        # See SmpAction's docstring in models/order.py.
        smp = self._parse_smp(fields["SMP"]) if "SMP" in fields else None

        price = safe_float(fields["PRICE"], "PRICE") if "PRICE" in fields else None
        stop_price = safe_float(fields["STOP"], "STOP") if "STOP" in fields else None
        visible = (
            safe_int(fields["VISIBLE"], "VISIBLE", min_value=1)
            if "VISIBLE" in fields
            else None
        )
        trail_offset = (
            safe_float(fields["TRAIL"], "TRAIL") if "TRAIL" in fields else None
        )

        if (
            order_type
            in {
                OrderType.LIMIT,
                OrderType.FOK,
                OrderType.ICEBERG,
                OrderType.IOC,
            }
            and price is None
        ):
            raise ValidationError("MISSING_FIELD", "PRICE is required for this TYPE")

        if order_type in {OrderType.STOP, OrderType.STOP_LIMIT} and stop_price is None:
            raise ValidationError("MISSING_FIELD", "STOP is required for this TYPE")

        if order_type == OrderType.STOP_LIMIT and price is None:
            raise ValidationError(
                "MISSING_FIELD", "PRICE is required for TYPE=STOP_LIMIT"
            )

        if order_type == OrderType.ICEBERG:
            if visible is None:
                raise ValidationError(
                    "MISSING_FIELD", "VISIBLE is required for TYPE=ICEBERG"
                )
            if visible >= quantity:
                raise ValidationError(
                    "INVALID_VALUE", "VISIBLE must be less than QTY for TYPE=ICEBERG"
                )

        if order_type == OrderType.TRAILING_STOP and trail_offset is None:
            raise ValidationError(
                "MISSING_FIELD", "TRAIL is required for TYPE=TRAILING_STOP"
            )

        order = Order.create(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            gateway_id=self._require_gw(session),
            tif=tif,
            price=to_ticks(price, symbol) if price is not None else None,
            stop_price=to_ticks(stop_price, symbol) if stop_price is not None else None,
            visible_qty=visible,
            smp_action=smp,
            trail_offset=(
                to_ticks(trail_offset, symbol) if trail_offset is not None else None
            ),
            oco_group_id=None,
        )

        self._send_to_engine(make_order_new_msg(order.to_dict()))

    def _handle_new_oco(self, session: ClientSession, fields: dict[str, str]) -> None:
        gateway_id = self._require_gw(session)
        oco_id = self._required_str(fields, "OCO_ID")
        symbol = self._required_str(fields, "SYM")
        self._validate_symbol(symbol)

        quantity = safe_int(self._required_str(fields, "QTY"), "QTY", min_value=1)
        tif = self._parse_tif(fields.get("TIF", "DAY"))

        def _parse_leg(prefix: str) -> dict[str, Any]:
            leg_side = self._parse_side(self._required_str(fields, f"{prefix}SIDE"))
            leg_type = self._parse_order_type(
                self._required_str(fields, f"{prefix}TYPE")
            )

            leg: dict[str, Any] = {
                "side": leg_side.value,
                "order_type": leg_type.value,
            }

            if f"{prefix}PRICE" in fields:
                leg["price"] = safe_float(fields[f"{prefix}PRICE"], f"{prefix}PRICE")
            if f"{prefix}STOP" in fields:
                leg["stop_price"] = safe_float(fields[f"{prefix}STOP"], f"{prefix}STOP")
            if f"{prefix}TRAIL" in fields:
                leg["trail_offset"] = safe_float(
                    fields[f"{prefix}TRAIL"], f"{prefix}TRAIL"
                )
            return leg

        leg1 = _parse_leg("LEG1_")
        leg2 = _parse_leg("LEG2_")

        payload = {
            "oco_id": oco_id,
            "gateway_id": gateway_id,
            "symbol": symbol,
            "quantity": quantity,
            "tif": tif.value,
            "leg1": leg1,
            "leg2": leg2,
        }
        self._send_to_engine(make_oco_order_msg(payload))

    def _handle_new_combo(self, session: ClientSession, fields: dict[str, str]) -> None:
        gateway_id = self._require_gw(session)
        combo_id = self._required_str(fields, "COMBO_ID")
        combo_type = self._parse_combo_type(
            self._required_str(fields, "COMBO_TYPE", default="AON")
        )
        tif = self._parse_tif(fields.get("TIF", "DAY"))
        # SMP omitted entirely means "let the engine apply this gateway's
        # configured smp_action default" to every leg -- distinct from an
        # explicit SMP=NONE. See SmpAction's docstring in models/order.py.
        smp_action = self._parse_smp(fields["SMP"]) if "SMP" in fields else None

        leg_count = safe_int(
            self._required_str(fields, "LEG_COUNT"), "LEG_COUNT", min_value=2
        )
        if leg_count > 10:
            raise ValidationError("INVALID_VALUE", "LEG_COUNT must be <= 10")

        legs: list[ComboLeg] = []
        for index in range(leg_count):
            prefix = f"LEG{index}"
            sym = self._required_str(fields, f"{prefix}.SYM")
            self._validate_symbol(sym)
            side = self._parse_side(self._required_str(fields, f"{prefix}.SIDE"))
            qty = safe_int(
                self._required_str(fields, f"{prefix}.QTY"),
                f"{prefix}.QTY",
                min_value=1,
            )
            leg_type = self._parse_order_type(fields.get(f"{prefix}.TYPE", "LIMIT"))

            price_raw = fields.get(f"{prefix}.PRICE")
            stop_raw = fields.get(f"{prefix}.STOP")

            price = (
                safe_float(price_raw, f"{prefix}.PRICE")
                if price_raw is not None
                else None
            )
            stop = (
                safe_float(stop_raw, f"{prefix}.STOP") if stop_raw is not None else None
            )

            if (
                leg_type in {OrderType.LIMIT, OrderType.IOC, OrderType.FOK}
                and price is None
            ):
                raise ValidationError(
                    "MISSING_FIELD", f"{prefix}.PRICE required for {leg_type.value}"
                )
            if leg_type in {OrderType.STOP, OrderType.STOP_LIMIT} and stop is None:
                raise ValidationError(
                    "MISSING_FIELD", f"{prefix}.STOP required for {leg_type.value}"
                )

            legs.append(
                ComboLeg(
                    symbol=sym,
                    side=side,
                    order_type=leg_type,
                    quantity=qty,
                    price=to_ticks(price, sym) if price is not None else None,
                    stop_price=to_ticks(stop, sym) if stop is not None else None,
                    smp_action=smp_action,
                )
            )

        combo = ComboOrder.create(
            combo_id=combo_id,
            gateway_id=gateway_id,
            combo_type=combo_type,
            tif=tif,
            legs=legs,
        )
        self._send_to_engine(make_combo_order_msg(combo.to_dict()))

    def _handle_amend(self, session: ClientSession, fields: dict[str, str]) -> None:
        order_id = self._required_str(fields, "ID")
        price = safe_float(fields["PRICE"], "PRICE") if "PRICE" in fields else None
        qty = safe_int(fields["QTY"], "QTY", min_value=1) if "QTY" in fields else None
        if price is None and qty is None:
            raise ValidationError("MISSING_FIELD", "AMEND requires PRICE and/or QTY")

        self._send_to_engine(
            make_order_amend_msg(
                order_id, self._require_gw(session), price=price, qty=qty
            )
        )

    def _handle_cancel(self, session: ClientSession, fields: dict[str, str]) -> None:
        gateway_id = self._require_gw(session)
        combo_id = fields.get("COMBO_ID")
        if combo_id:
            self._send_to_engine(make_combo_cancel_msg(combo_id, gateway_id))
            return

        oco_id = fields.get("OCO_ID")
        if oco_id:
            self._send_to_engine(make_oco_cancel_msg(oco_id, gateway_id))
            return

        order_id = fields.get("ID")
        if not order_id:
            raise ValidationError(
                "MISSING_FIELD", "CANCEL requires ID, COMBO_ID, or OCO_ID"
            )

        self._send_to_engine(make_order_cancel_msg(order_id, gateway_id))

    def _handle_quote(self, session: ClientSession, fields: dict[str, str]) -> None:
        self._require_role(session, "MARKET_MAKER")

        symbol = self._required_str(fields, "SYM")
        self._validate_symbol(symbol)

        bid = safe_float(self._required_str(fields, "BID"), "BID")
        ask = safe_float(self._required_str(fields, "ASK"), "ASK")
        bid_qty = safe_int(
            self._required_str(fields, "BID_QTY"), "BID_QTY", min_value=1
        )
        ask_qty = safe_int(
            self._required_str(fields, "ASK_QTY"), "ASK_QTY", min_value=1
        )
        tif = self._parse_tif(fields.get("TIF", "DAY"))

        if bid >= ask:
            raise ValidationError("INVALID_VALUE", "QUOTE requires BID < ASK")

        payload: dict[str, Any] = {
            "gateway_id": self._require_gw(session),
            "symbol": symbol,
            "bid_price": bid,
            "bid_qty": bid_qty,
            "ask_price": ask,
            "ask_qty": ask_qty,
            "tif": tif.value,
        }
        quote_id = fields.get("QUOTE_ID")
        if quote_id:
            payload["quote_id"] = quote_id

        self._send_to_engine(make_quote_new_msg(payload))

    def _handle_quote_cancel(
        self, session: ClientSession, fields: dict[str, str]
    ) -> None:
        self._require_role(session, "MARKET_MAKER")
        symbol = self._required_str(fields, "SYM")
        self._validate_symbol(symbol)
        self._send_to_engine(make_quote_cancel_msg(self._require_gw(session), symbol))

    def _handle_dc(self, session: ClientSession, fields: dict[str, str]) -> None:
        """Toggle asynchronous drop-copy relay for this session.

        ``DC|ON`` subscribes this session to the engine's drop-copy feed
        (``DROP_COPY_PUB_ADDR``, :5557) scoped to this session's own
        ``gateway_id`` -- every subsequent fill for this gateway arrives
        asynchronously as a ``DC_FILL`` line, mirroring how a real exchange
        relays drop copy down a participant's own session rather than
        requiring a separate connection. ``DC|OFF`` unsubscribes. Mirrors
        the on/off semantics of a real FIX drop-copy session being
        provisioned per participant -- see docs/user-guide/200-drop-copy.md.
        """
        state = self._required_str(fields, "STATE")
        gateway_id = self._require_gw(session)

        if state == "ON":
            if not session.dc_enabled:
                self._dc_subscribe_topic(f"{_DC_EVENT_TOPIC_PREFIX}{gateway_id}")
                session.dc_enabled = True
            self._queue_line(session, "DC_ACK", {"STATE": "ON"})
            return
        if state == "OFF":
            if session.dc_enabled:
                self._dc_unsubscribe_topic(f"{_DC_EVENT_TOPIC_PREFIX}{gateway_id}")
                session.dc_enabled = False
            self._queue_line(session, "DC_ACK", {"STATE": "OFF"})
            return
        raise ValidationError("INVALID_VALUE", "DC STATE must be ON or OFF")

    # ------------------------------------------------------------------
    # Engine event polling
    # ------------------------------------------------------------------

    def _poll_engine_events(self) -> None:
        budget = _MAX_ENGINE_EVENTS_PER_LOOP
        while budget > 0 and self._sub.poll(timeout=0):
            try:
                topic, payload = decode(self._sub.recv_multipart())
            except zmq.ZMQError as exc:
                if exc.errno != errno.EINTR:
                    log.warning(
                        "ALF gateway SUB recv error (errno=%s); dropping remaining events for this tick",
                        exc.errno,
                    )
                break
            except Exception:
                budget -= 1
                continue

            budget -= 1

            if topic.startswith("system.gateway_auth."):
                gateway_id = topic.rsplit(".", 1)[-1].upper()
                self._handle_gateway_auth(gateway_id, payload)
                continue

            if topic.startswith("system.symbols."):
                gateway_id = topic.rsplit(".", 1)[-1].upper()
                self._handle_symbols_response(gateway_id, payload)
                continue

            if topic.startswith("order.orders."):
                gateway_id = topic.rsplit(".", 1)[-1].upper()
                self._handle_orders_response(gateway_id, payload)
                continue

            if topic.startswith("system.quote_bootstrap."):
                gateway_id = topic.rsplit(".", 1)[-1].upper()
                self._handle_qboot_response(gateway_id, payload)
                continue

            if topic.startswith("system.quote_legs."):
                gateway_id = topic.rsplit(".", 1)[-1].upper()
                self._handle_qlegs_response(gateway_id, payload)
                continue

            if topic == "session.state":
                self._broadcast(
                    "SESSION",
                    {
                        "STATE": str(payload.get("state", "")),
                        "PREV_STATE": str(payload.get("prev_state", "")),
                    },
                )
                continue

            if topic.startswith("circuit_breaker.halt."):
                self._broadcast(
                    "HALT",
                    {
                        "SYMBOL": str(payload.get("symbol", "")),
                        "LEVEL": str(payload.get("level", "")),
                    },
                )
                continue

            if topic.startswith("circuit_breaker.resume."):
                self._broadcast(
                    "RESUME",
                    {
                        "SYMBOL": str(payload.get("symbol", "")),
                        "MODE": str(payload.get("resumption_mode", "")),
                    },
                )
                continue

            if topic == "trade.executed":
                self._broadcast(
                    "TRADE",
                    {
                        "SYMBOL": str(payload.get("symbol", "")),
                        "PRICE": str(payload.get("price", "")),
                        "QTY": str(payload.get("quantity", "")),
                        "SIDE": str(payload.get("aggressor_side", "")),
                    },
                )
                continue

            self._route_gateway_scoped_event(topic, payload)

    def _poll_dc_events(self) -> None:
        """Poll the drop-copy SUB socket (:5557) and relay to subscribed sessions.

        Separate from :meth:`_poll_engine_events` because drop copy lives on
        its own ZMQ PUB socket, distinct from the main event bus (:5556).
        Only sessions that sent ``DC|ON`` are subscribed to any topic on
        this socket at all (see ``_handle_dc``/``_dc_subscribe_topic``), so
        this poll is a no-op whenever no connected session has opted in.
        """
        budget = _MAX_DC_EVENTS_PER_LOOP
        while budget > 0 and self._dc_sub.poll(timeout=0):
            try:
                topic, payload = decode(self._dc_sub.recv_multipart())
            except zmq.ZMQError as exc:
                if exc.errno != errno.EINTR:
                    log.warning(
                        "ALF gateway drop-copy SUB recv error (errno=%s); "
                        "dropping remaining DC events for this tick",
                        exc.errno,
                    )
                break
            except Exception:
                budget -= 1
                continue

            budget -= 1

            if not topic.startswith(_DC_EVENT_TOPIC_PREFIX):
                continue
            gateway_id = topic[len(_DC_EVENT_TOPIC_PREFIX) :].upper()
            session = self._session_for_gateway(gateway_id)
            if session is None or not session.dc_enabled:
                continue

            self._queue_line(
                session,
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

    def _handle_gateway_auth(self, gateway_id: str, payload: dict[str, Any]) -> None:
        target = self._find_pending_auth_session(gateway_id)
        if target is None:
            return

        accepted = bool(payload.get("accepted", False))
        reason = str(payload.get("reason", ""))

        if not accepted:
            self._global_stats["auth_failures"] += 1
            target.auth_pending = False
            self._register_error(
                target,
                "AUTH_FAILED",
                reason or f"Gateway not configured: {gateway_id}",
                close_connection=True,
            )
            return

        target.auth_pending = False
        target.authenticated = True
        target.gateway_id = gateway_id
        target.role = self._gateway_roles.get(gateway_id, "TRADER")
        self._active_gateway_sessions[gateway_id] = target.sock.fileno()

        for topic in self._gateway_topics(gateway_id):
            if topic not in target.subscriptions:
                self._subscribe_topic(topic)
                target.subscriptions.add(topic)

        self._queue_line(
            target,
            "WELCOME",
            {
                "PROTO": "ALF1",
                "GW": self.config.name,
                "ID": gateway_id,
                "HBINT": str(self.config.heartbeat_interval_sec),
                "IDLE": str(self.config.idle_timeout_sec),
            },
        )

        self._send_to_engine(
            make_symbols_request_msg(gateway_id), count_as_command=False
        )

    def _handle_symbols_response(
        self, gateway_id: str, payload: dict[str, Any]
    ) -> None:
        session = self._session_for_gateway(gateway_id)
        if session is None:
            return

        symbols_raw = payload.get("symbols", [])
        symbol_meta = payload.get("symbol_meta", {})
        symbols = [str(s).upper() for s in symbols_raw if isinstance(s, str)]
        self._symbols_snapshot_loaded = True
        self._known_symbols.update(symbols)

        if isinstance(symbol_meta, dict):
            for sym in symbols:
                meta = symbol_meta.get(sym)
                if not isinstance(meta, dict):
                    continue
                tick_size = meta.get("tick_size")
                if isinstance(tick_size, (int, float)) and tick_size > 0:
                    decimals = self._infer_decimals(float(tick_size))
                    if decimals is not None:
                        register_tick_decimals(sym, decimals)

        self._queue_line(session, "SYMBOLS", {"COUNT": str(len(symbols))})
        for sym in symbols:
            tick = ""
            if isinstance(symbol_meta, dict):
                meta = symbol_meta.get(sym)
                if isinstance(meta, dict) and "tick_size" in meta:
                    tick = str(meta["tick_size"])
            self._queue_line(session, "SYMBOL", {"SYM": sym, "TICK": tick})
        self._queue_line(session, "END", {"TYPE": "SYMBOLS"})

    def _handle_orders_response(self, gateway_id: str, payload: dict[str, Any]) -> None:
        session = self._session_for_gateway(gateway_id)
        if session is None:
            return

        orders = payload.get("orders", [])
        if not isinstance(orders, list):
            orders = []

        self._queue_line(
            session,
            "ORDERS",
            {"COUNT": str(len(orders)), "GW": gateway_id},
        )

        for od in orders:
            if not isinstance(od, dict):
                continue
            fields = {
                "ID": str(od.get("id", "")),
                "SYM": str(od.get("symbol", "")),
                "SIDE": str(od.get("side", "")),
                "TYPE": str(od.get("order_type", "")),
                "QTY": str(od.get("quantity", "")),
                "REMAINING": str(od.get("remaining_qty", "")),
                "PRICE": (
                    str(od.get("price", "")) if od.get("price") is not None else ""
                ),
                "STATUS": str(od.get("status", "")),
            }
            self._queue_line(session, "ORDER", fields)

        self._queue_line(session, "END", {"TYPE": "ORDERS"})

    def _handle_qboot_response(self, gateway_id: str, payload: dict[str, Any]) -> None:
        session = self._session_for_gateway(gateway_id)
        if session is None:
            return

        quotes = payload.get("quotes", [])
        if not isinstance(quotes, list):
            quotes = []

        self._queue_line(session, "QBOOT", {"COUNT": str(len(quotes))})
        for quote in quotes:
            if not isinstance(quote, dict):
                continue
            self._queue_line(
                session,
                "QUOTE",
                {
                    "QUOTE_ID": str(quote.get("quote_id", "")),
                    "SYM": str(quote.get("symbol", "")),
                    "BID": str(quote.get("bid_price", "")),
                    "ASK": str(quote.get("ask_price", "")),
                    "BID_QTY": str(quote.get("bid_qty", "")),
                    "ASK_QTY": str(quote.get("ask_qty", "")),
                    "STATUS": str(quote.get("status", "")),
                },
            )
        self._queue_line(session, "END", {"TYPE": "QBOOT"})

    def _handle_qlegs_response(self, gateway_id: str, payload: dict[str, Any]) -> None:
        session = self._session_for_gateway(gateway_id)
        if session is None:
            return

        legs = payload.get("legs", [])
        if not isinstance(legs, list):
            legs = []
        recent = payload.get("recent", [])
        if not isinstance(recent, list):
            recent = []
        show_requested = str(payload.get("show_requested", "ACTIVE"))

        self._queue_line(
            session,
            "QLEGS",
            {
                "COUNT": str(len(legs)),
                "RECENT_COUNT": str(len(recent)),
                "SHOW": show_requested,
            },
        )
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            self._queue_line(
                session,
                "LEG",
                {
                    "QUOTE_ID": str(leg.get("quote_id", "")),
                    "SYM": str(leg.get("symbol", "")),
                    "SIDE": str(leg.get("leg_side", "")),
                    "ORDER_ID": str(leg.get("order_id", "")),
                    "QTY": str(leg.get("qty", "")),
                    "REMAINING": str(leg.get("remaining", "")),
                    "FILLED": str(leg.get("filled", "")),
                    "STATUS": str(leg.get("status", "")),
                    "QUOTE_STATUS": str(leg.get("quote_status", "")),
                },
            )
        for entry in recent:
            if not isinstance(entry, dict):
                continue
            quote_id = str(entry.get("quote_id", ""))
            self._queue_line(
                session,
                "RECENT_LEG",
                {
                    "QUOTE_ID": quote_id,
                    "SYM": str(entry.get("symbol", "")),
                    "QUOTE_STATUS": str(entry.get("quote_status", "")),
                    "REASON": str(entry.get("reason", "")),
                    "REMOVED_AT_NS": str(entry.get("removed_at_ns", "")),
                },
            )
            # Per-leg detail (qty/remaining/filled/status), when the engine
            # had it available at removal time — see
            # docs-design/EduMatcher-QLEGS-RECENT.md §9.3. Emitted as
            # separate, optional lines rather than folded into RECENT_LEG's
            # field set so existing parsers of RECENT_LEG are unaffected,
            # and so a missing snapshot (bid_leg/ask_leg is None) is simply
            # the absence of a line rather than a row of blank fields.
            for leg_line_type, leg_field, leg_side in (
                ("RECENT_BID_LEG", "bid_leg", "BUY"),
                ("RECENT_ASK_LEG", "ask_leg", "SELL"),
            ):
                leg = entry.get(leg_field)
                if not isinstance(leg, dict):
                    continue
                self._queue_line(
                    session,
                    leg_line_type,
                    {
                        "QUOTE_ID": quote_id,
                        "SIDE": leg_side,
                        "ORDER_ID": str(leg.get("order_id", "")),
                        "QTY": str(leg.get("qty", "")),
                        "REMAINING": str(leg.get("remaining", "")),
                        "FILLED": str(leg.get("filled", "")),
                        "STATUS": str(leg.get("status", "")),
                    },
                )
        self._queue_line(session, "END", {"TYPE": "QLEGS"})

    def _route_gateway_scoped_event(self, topic: str, payload: dict[str, Any]) -> None:
        if "." not in topic:
            return
        gateway_id = topic.rsplit(".", 1)[-1].upper()
        session = self._session_for_gateway(gateway_id)
        if session is None:
            return

        fields: dict[str, str] | None = None
        msg_type: str | None = None

        if topic.startswith("order.ack."):
            msg_type = "ACK"
            fields = {
                "ORDER_ID": str(payload.get("order_id", "")),
                "ACCEPTED": "TRUE" if bool(payload.get("accepted", False)) else "FALSE",
                "REASON": str(payload.get("reason", "")),
                "SYMBOL": str(payload.get("symbol", "")),
                "SIDE": str(payload.get("side", "")),
                "TYPE": str(payload.get("order_type", "")),
            }
        elif topic.startswith("order.fill."):
            msg_type = "FILL"
            fields = {
                "ORDER_ID": str(payload.get("order_id", "")),
                "FILL_QTY": str(payload.get("fill_qty", "")),
                "FILL_PRICE": str(payload.get("fill_price", "")),
                "REMAINING": str(payload.get("remaining_qty", "")),
                "STATUS": str(payload.get("status", "")),
            }
        elif topic.startswith("order.amended."):
            msg_type = "AMENDED"
            fields = {
                "ORDER_ID": str(payload.get("order_id", "")),
                "PRICE": (
                    str(payload.get("price", ""))
                    if payload.get("price") is not None
                    else ""
                ),
                "QTY": str(payload.get("qty", "")),
                "REMAINING": str(payload.get("remaining_qty", "")),
                "PRIORITY_RESET": (
                    "TRUE" if bool(payload.get("priority_reset", False)) else "FALSE"
                ),
            }
        elif topic.startswith("order.cancelled."):
            msg_type = "CANCELLED"
            fields = {"ORDER_ID": str(payload.get("order_id", ""))}
        elif topic.startswith("order.expired."):
            msg_type = "EXPIRED"
            fields = {"ORDER_ID": str(payload.get("order_id", ""))}
        elif topic.startswith("quote.ack."):
            msg_type = "QUOTE_ACK"
            fields = {
                "QUOTE_ID": str(payload.get("quote_id", "")),
                "ACCEPTED": "TRUE" if bool(payload.get("accepted", False)) else "FALSE",
                "REASON": str(payload.get("reason", "")),
                "BID_ID": str(payload.get("bid_order_id", "")),
                "ASK_ID": str(payload.get("ask_order_id", "")),
            }
        elif topic.startswith("quote.status."):
            msg_type = "QUOTE_STATUS"
            fields = {
                "QUOTE_ID": str(payload.get("quote_id", "")),
                "STATUS": str(payload.get("status", "")),
                "REASON": str(payload.get("reason", "")),
            }
        elif topic.startswith("combo.ack."):
            msg_type = "COMBO_ACK"
            fields = {
                "COMBO_ID": str(payload.get("combo_id", "")),
                "ACCEPTED": "TRUE" if bool(payload.get("accepted", False)) else "FALSE",
                "REASON": str(payload.get("reason", "")),
            }
        elif topic.startswith("combo.status."):
            msg_type = "COMBO_STATUS"
            details = payload.get("details")
            reason = ""
            if isinstance(details, dict):
                reason = str(details.get("reason", ""))
            fields = {
                "COMBO_ID": str(payload.get("combo_id", "")),
                "STATUS": str(payload.get("status", "")),
                "REASON": reason,
            }
        elif topic.startswith("oco.ack."):
            msg_type = "OCO_ACK"
            fields = {
                "OCO_ID": str(payload.get("oco_id", "")),
                "ACCEPTED": "TRUE" if bool(payload.get("accepted", False)) else "FALSE",
                "LEG1_ID": str(payload.get("order_id_1", "")),
                "LEG2_ID": str(payload.get("order_id_2", "")),
                "REASON": str(payload.get("reason", "")),
            }
        elif topic.startswith("oco.cancelled."):
            msg_type = "OCO_CANCELLED"
            fields = {
                "OCO_ID": str(payload.get("oco_id", "")),
                "CANCELLED_ID": str(payload.get("cancelled_order_id", "")),
                "REASON": str(payload.get("reason", "")),
            }
        elif topic.startswith("risk.kill_switch_ack."):
            msg_type = "KILL_ACK"
            fields = {
                "ACCEPTED": "TRUE" if bool(payload.get("accepted", False)) else "FALSE",
                "REASON": str(payload.get("reason", "")),
                "ORDERS": str(payload.get("cancelled_orders", 0)),
                "QUOTES": str(payload.get("cancelled_quotes", 0)),
            }

        if msg_type is not None and fields is not None:
            self._queue_line(session, msg_type, fields)

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def _send_heartbeats_if_due(self) -> None:
        now = time.monotonic()
        for session in self._clients.values():
            if not session.authenticated:
                continue
            if now - session.last_outbound < self.config.heartbeat_interval_sec:
                continue
            self._queue_line(session, "HB", {"TS": iso_utc(time.time())})

    def _drop_idle_clients(self) -> None:
        now = time.monotonic()
        for session in list(self._clients.values()):
            if (
                not session.authenticated
                and now - session.connected_at > self.config.handshake_timeout_sec
            ):
                self._queue_line(
                    session,
                    "ERR",
                    {
                        "CODE": "AUTH_TIMEOUT",
                        "DETAIL": "Handshake timeout",
                    },
                )
                self._close_after_flush(session)
                continue

            if now - session.last_activity <= self.config.idle_timeout_sec:
                continue
            self._queue_line(
                session,
                "ERR",
                {"CODE": "IDLE_TIMEOUT", "DETAIL": "Session idle timeout"},
            )
            self._close_after_flush(session)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _required_str(
        self, fields: dict[str, str], key: str, *, default: str | None = None
    ) -> str:
        if key in fields:
            value = fields[key].strip()
            if value:
                return value
        if default is not None:
            return default
        raise ValidationError("MISSING_FIELD", f"{key} is required")

    def _parse_side(self, raw: str) -> Side:
        try:
            return Side(raw)
        except ValueError as exc:
            raise ValidationError(
                "INVALID_VALUE", f"SIDE: invalid value '{raw}'"
            ) from exc

    def _parse_order_type(self, raw: str) -> OrderType:
        try:
            return OrderType(raw)
        except ValueError as exc:
            raise ValidationError(
                "INVALID_VALUE", f"TYPE: invalid value '{raw}'"
            ) from exc

    def _parse_tif(self, raw: str) -> TIF:
        try:
            return TIF(raw)
        except ValueError as exc:
            raise ValidationError(
                "INVALID_VALUE", f"TIF: invalid value '{raw}'"
            ) from exc

    def _parse_smp(self, raw: str) -> SmpAction:
        try:
            return SmpAction(raw)
        except ValueError as exc:
            raise ValidationError(
                "INVALID_VALUE", f"SMP: invalid value '{raw}'"
            ) from exc

    def _parse_combo_type(self, raw: str) -> ComboType:
        try:
            return ComboType(raw)
        except ValueError as exc:
            raise ValidationError(
                "INVALID_VALUE", f"COMBO_TYPE: invalid value '{raw}'"
            ) from exc

    def _validate_symbol(self, symbol: str) -> None:
        if not self._symbols_snapshot_loaded:
            raise ValidationError(
                "SYMBOLS_NOT_READY",
                "Symbol metadata not loaded yet; retry shortly",
            )
        if symbol not in self._known_symbols:
            raise ValidationError("SYMBOL_NOT_CONFIGURED", f"Unknown symbol: {symbol}")

    def _require_gw(self, session: ClientSession) -> str:
        if session.gateway_id is None:
            raise ValidationError("AUTH_REQUIRED", "Session not authenticated")
        return session.gateway_id

    def _require_role(self, session: ClientSession, required: str) -> None:
        if session.role != required:
            raise ValidationError(
                "ROLE_DENIED",
                f"Command requires role {required}; current role is {session.role}",
            )

    def _allow_command_now(self, session: ClientSession) -> bool:
        now = time.monotonic()
        elapsed = now - session.rate_updated
        session.rate_updated = now

        max_rate = float(self.config.max_commands_per_second)
        session.rate_tokens = min(max_rate, session.rate_tokens + elapsed * max_rate)
        if session.rate_tokens < 1.0:
            return False

        session.rate_tokens -= 1.0
        return True

    def _queue_line(
        self, session: ClientSession, msg_type: str, fields: dict[str, str]
    ) -> None:
        self._queue_raw(session, build_line(msg_type, fields))

    def _queue_raw(self, session: ClientSession, payload: bytes) -> None:
        if len(session.out_queue) >= self.config.max_client_queue:
            self._global_stats["slow_client_disconnects"] += 1
            session.out_queue.clear()
            session.out_offset = 0
            session.out_queue.append(
                b"ERR|CODE=SLOW_CLIENT|DETAIL=Outbound queue full - disconnecting\n"
            )
            session.closing = True
            return
        session.out_queue.append(payload)

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
            raise ValidationError(
                "ENGINE_UNAVAILABLE",
                "Engine unavailable: command not forwarded; retry shortly",
            )
        except zmq.ZMQError as exc:
            if self._push.closed:
                return
            if exc.errno == zmq.EAGAIN:
                if not require_engine:
                    return
                raise ValidationError(
                    "ENGINE_UNAVAILABLE",
                    "Engine unavailable: command not forwarded; retry shortly",
                )
            raise
        if count_as_command:
            self._global_stats["commands_forwarded_total"] += 1

    def _register_error(
        self,
        session: ClientSession,
        code: str,
        detail: str,
        *,
        close_connection: bool,
    ) -> None:
        self._global_stats["errors_total"] += 1
        session.errors += 1
        self._queue_line(session, "ERR", {"CODE": code, "DETAIL": detail})

        now = time.monotonic()
        session.error_times.append(now)
        while (
            session.error_times
            and now - session.error_times[0] > self.config.error_window_sec
        ):
            session.error_times.popleft()

        if len(session.error_times) >= self.config.max_errors_before_disconnect:
            self._queue_line(
                session,
                "ERR",
                {
                    "CODE": "MAX_ERRORS",
                    "DETAIL": "Too many protocol errors - disconnecting",
                },
            )
            close_connection = True

        if close_connection:
            self._close_after_flush(session)

    def _close_after_flush(self, session: ClientSession) -> None:
        session.closing = True

    def _disconnect(self, session: ClientSession, *, reason: str) -> None:
        gateway_id = session.gateway_id

        if (
            gateway_id
            and self._active_gateway_sessions.get(gateway_id) == session.sock.fileno()
        ):
            self._active_gateway_sessions.pop(gateway_id, None)

        for topic in list(session.subscriptions):
            self._unsubscribe_topic(topic)
        session.subscriptions.clear()

        if gateway_id and session.dc_enabled:
            self._dc_unsubscribe_topic(f"{_DC_EVENT_TOPIC_PREFIX}{gateway_id}")
            session.dc_enabled = False

        if gateway_id and session.connect_emitted:
            self._send_to_engine(
                make_gateway_disconnect_msg(gateway_id, reason=reason),
                count_as_command=False,
                require_engine=False,
            )
            session.connect_emitted = False

        fileno = session.sock.fileno()
        session.close()
        self._clients.pop(fileno, None)
        self._global_stats["connected_clients"] = len(self._clients)
        self._global_stats["disconnects_total"] += 1

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

    def _dc_subscribe_topic(self, topic: str) -> None:
        """Refcounted SUBSCRIBE on the drop-copy socket (:5557).

        Kept separate from :meth:`_subscribe_topic` because it targets
        ``self._dc_sub`` rather than ``self._sub`` -- a different ZMQ PUB
        address entirely, not just a different topic namespace.
        """
        ref = self._dc_topic_refcounts.get(topic, 0)
        if ref == 0:
            self._dc_sub.setsockopt(zmq.SUBSCRIBE, topic.encode("utf-8"))
        self._dc_topic_refcounts[topic] = ref + 1

    def _dc_unsubscribe_topic(self, topic: str) -> None:
        ref = self._dc_topic_refcounts.get(topic, 0)
        if ref <= 1:
            self._dc_topic_refcounts.pop(topic, None)
            self._dc_sub.setsockopt(zmq.UNSUBSCRIBE, topic.encode("utf-8"))
            return
        self._dc_topic_refcounts[topic] = ref - 1

    def _gateway_topics(self, gateway_id: str) -> tuple[str, ...]:
        return (
            f"system.gateway_auth.{gateway_id}",
            f"order.ack.{gateway_id}",
            f"order.fill.{gateway_id}",
            f"order.amended.{gateway_id}",
            f"order.cancelled.{gateway_id}",
            f"order.expired.{gateway_id}",
            f"order.orders.{gateway_id}",
            f"quote.ack.{gateway_id}",
            f"quote.status.{gateway_id}",
            f"combo.ack.{gateway_id}",
            f"combo.status.{gateway_id}",
            f"oco.ack.{gateway_id}",
            f"oco.cancelled.{gateway_id}",
            f"risk.kill_switch_ack.{gateway_id}",
            f"system.symbols.{gateway_id}",
            f"system.quote_bootstrap.{gateway_id}",
        )

    def _gateway_in_use(self, gateway_id: str) -> bool:
        if gateway_id in self._active_gateway_sessions:
            return True
        for session in self._clients.values():
            if session.gateway_id == gateway_id and (
                session.auth_pending or session.authenticated
            ):
                return True
        return False

    def _session_for_gateway(self, gateway_id: str) -> ClientSession | None:
        fileno = self._active_gateway_sessions.get(gateway_id)
        if fileno is None:
            return None
        return self._clients.get(fileno)

    def _find_pending_auth_session(self, gateway_id: str) -> ClientSession | None:
        for session in self._clients.values():
            if session.gateway_id == gateway_id and session.auth_pending:
                return session
        return None

    def _broadcast(self, msg_type: str, fields: dict[str, str]) -> None:
        for session in self._clients.values():
            if session.authenticated:
                self._queue_line(session, msg_type, fields)

    @staticmethod
    def _infer_decimals(tick_size: float) -> int | None:
        if tick_size <= 0:
            return None
        text = f"{tick_size:.12f}".rstrip("0").rstrip(".")
        if "." not in text:
            return 0
        return len(text.split(".", 1)[1])

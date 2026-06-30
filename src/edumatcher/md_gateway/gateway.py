"""CALF market data gateway runtime.

Design priorities for this implementation:
- Correctness first: strict protocol validation and deterministic behavior
- Maintainability: clear decomposition and heavily documented control flow
- Defensive behavior: bounded queues, explicit disconnect paths, replay checks

The gateway bridges engine PUB topics onto CALF/TCP streams.
"""

from __future__ import annotations

import select
import signal
import socket
import threading
import time
from typing import Any

from edumatcher.md_gateway.client_session import ClientSession
from edumatcher.md_gateway.config import MarketDataGatewayConfig
from edumatcher.md_gateway.fanout import SubscriptionRegistry
from edumatcher.md_gateway.normaliser import EngineNormaliser
from edumatcher.md_gateway.protocol import build_line, iso_utc, parse_line
from edumatcher.md_gateway.replay_buffer import ReplayBuffer, ReplayMissError
from edumatcher.md_gateway.sequencer import SequenceAllocator
from edumatcher.messaging.bus import make_subscriber
from edumatcher.models.message import decode

_ALLOWED_CHANNELS = frozenset({"TOP", "TRADE", "STATE", "INDEX"})
_MAX_LINE_BYTES = 4096
_HELLO_TIMEOUT_SEC = 5


class MarketDataGateway:
    """CALF TCP gateway process."""

    def __init__(
        self,
        config: MarketDataGatewayConfig,
        known_symbols: set[str] | None = None,
    ) -> None:
        self.config = config
        self._known_symbols = set(s.upper() for s in (known_symbols or set()))

        self._running = False
        self._server: socket.socket | None = None
        self._clients: dict[int, ClientSession] = {}

        self._subs = SubscriptionRegistry()
        self._normaliser = EngineNormaliser()
        self._sequencer = SequenceAllocator()
        self._replay = ReplayBuffer(config.replay_window_sec)

        self._sub_sock = make_subscriber(
            config.engine_pub_addr,
            "book.",
            "trade.executed",
            "session.state",
            "circuit_breaker.halt.",
            "circuit_breaker.resume.",
        )
        self._index_sub = make_subscriber(config.index_pub_addr, "index.")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start TCP listener and process loop until stopped."""
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
            f"[CALF] Listening on {self.config.bind_address}:{self.config.port} "
            f"(engine pub: {self.config.engine_pub_addr})"
        )

        try:
            while self._running:
                self._accept_new_clients()
                self._read_client_data()
                self._poll_engine_events()
                self._send_heartbeats_if_due()
                self._flush_client_writes()
                self._drop_idle_clients()
                time.sleep(0.01)
        finally:
            self.close()

    def stop(self) -> None:
        self._running = False

    def close(self) -> None:
        for session in list(self._clients.values()):
            try:
                session.sock.close()
            except OSError:
                pass
        self._clients.clear()

        if self._server is not None:
            self._server.close()
            self._server = None

        if not self._sub_sock.closed:
            self._sub_sock.close()
        if not self._index_sub.closed:
            self._index_sub.close()

    # ------------------------------------------------------------------
    # Network IO
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
                self._disconnect(session)
                continue

            session.in_buffer.extend(chunk)
            session.last_activity = time.monotonic()

            # Defensive framing guard: when no newline arrives and the line grows
            # beyond the protocol max, fail fast to avoid unbounded buffering.
            if (
                b"\n" not in session.in_buffer
                and len(session.in_buffer) > _MAX_LINE_BYTES
            ):
                self._queue_line(
                    session,
                    "ERR",
                    {"CODE": "BAD_MESSAGE", "MSG": "line exceeds 4096 bytes"},
                )
                self._close_after_flush(session)
                continue

            self._drain_lines(session)

    def _drain_lines(self, session: ClientSession) -> None:
        """Extract complete newline-delimited lines and dispatch parser.

        TCP is a byte stream. This loop deliberately handles all three cases:
        1) partial line (leave in buffer)
        2) exactly one full line
        3) multiple lines in one recv chunk
        """
        while True:
            idx = session.in_buffer.find(b"\n")
            if idx < 0:
                return

            raw = bytes(session.in_buffer[:idx])
            del session.in_buffer[: idx + 1]

            if len(raw) + 1 > _MAX_LINE_BYTES:
                self._queue_line(
                    session,
                    "ERR",
                    {"CODE": "BAD_MESSAGE", "MSG": "line exceeds 4096 bytes"},
                )
                self._close_after_flush(session)
                return

            line = raw.decode("utf-8", errors="replace")
            self._handle_client_line(session, line)

    def _flush_client_writes(self) -> None:
        """Flush queued outbound bytes to all clients.

        Writes are non-blocking and may complete partially; ``out_offset`` tracks
        progress for the first queued message until fully sent.
        """
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
                session.last_activity = time.monotonic()

                if session.out_offset >= len(payload):
                    session.out_queue.popleft()
                    session.out_offset = 0

            if len(session.out_queue) > self.config.max_client_queue:
                self._queue_line(
                    session,
                    "ERR",
                    {"CODE": "SLOW_CLIENT", "MSG": "outbound queue overflow"},
                )
                self._close_after_flush(session)

            if session.closing and not session.out_queue:
                self._disconnect(session)

    # ------------------------------------------------------------------
    # Protocol handling
    # ------------------------------------------------------------------

    def _handle_client_line(self, session: ClientSession, line: str) -> None:
        try:
            frame = parse_line(line)
        except Exception:
            self._queue_line(
                session,
                "ERR",
                {"CODE": "BAD_MESSAGE", "MSG": "parse error"},
            )
            return

        if not session.authenticated:
            if frame.msg_type != "HELLO":
                self._queue_line(
                    session,
                    "ERR",
                    {"CODE": "AUTH_REQUIRED", "MSG": "send HELLO first"},
                )
                self._close_after_flush(session)
                return
            self._handle_hello(session, frame.fields)
            return

        if frame.msg_type == "SUB":
            self._handle_sub(session, frame.fields)
        elif frame.msg_type == "UNSUB":
            self._handle_unsub(session, frame.fields)
        elif frame.msg_type == "PING":
            self._queue_raw(session, build_line("PONG"), is_market_data=False)
        elif frame.msg_type == "EXIT":
            self._close_after_flush(session)
        else:
            self._queue_line(
                session,
                "ERR",
                {"CODE": "BAD_MESSAGE", "MSG": f"unsupported {frame.msg_type}"},
            )

    def _handle_hello(self, session: ClientSession, fields: dict[str, str]) -> None:
        client = fields.get("CLIENT", "")
        proto = fields.get("PROTO", "")
        if not client or len(client) > 32 or proto != "CALF1":
            self._queue_line(
                session,
                "ERR",
                {"CODE": "PROTO_MISMATCH", "MSG": "CLIENT and PROTO=CALF1 required"},
            )
            self._close_after_flush(session)
            return

        session.client_id = client
        session.authenticated = True
        session.last_activity = time.monotonic()

        welcome_fields = {
            "PROTO": "CALF1",
            "GW": self.config.name,
            "HBINT": str(self.config.heartbeat_interval_sec),
            "REPLAY": str(self.config.replay_window_sec),
        }
        if self._known_symbols:
            welcome_fields["SYMBOLS"] = ",".join(sorted(self._known_symbols))

        self._queue_line(session, "WELCOME", welcome_fields)

        resume_raw = fields.get("RESUME", "0")
        if resume_raw == "1":
            self._handle_resume(session, fields)

    def _handle_resume(self, session: ClientSession, fields: dict[str, str]) -> None:
        ch_values = self._parse_csv_upper(fields.get("CH", ""))
        sym_values = self._parse_csv_upper(fields.get("SYM", ""))

        if len(ch_values) != 1 or len(sym_values) != 1:
            self._queue_line(
                session,
                "ERR",
                {
                    "CODE": "BAD_MESSAGE",
                    "MSG": "RESUME requires exactly one CH and one SYM",
                },
            )
            self._close_after_flush(session)
            return

        last_seq_raw = fields.get("LASTSEQ", "")
        try:
            last_seq = int(last_seq_raw)
        except (TypeError, ValueError):
            self._queue_line(
                session,
                "ERR",
                {"CODE": "BAD_MESSAGE", "MSG": "LASTSEQ must be an integer"},
            )
            self._close_after_flush(session)
            return

        if last_seq <= 0:
            self._queue_line(
                session,
                "ERR",
                {"CODE": "BAD_MESSAGE", "MSG": "LASTSEQ must be > 0"},
            )
            self._close_after_flush(session)
            return

        ch = ch_values[0]
        sym = sym_values[0]

        if ch not in _ALLOWED_CHANNELS:
            self._queue_line(
                session,
                "ERR",
                {"CODE": "INVALID_CHANNEL", "CH": ch, "SYM": sym},
            )
            self._close_after_flush(session)
            return

        # Resume implies immediate live continuation for the requested stream.
        session.subscriptions.add((ch, sym))
        self._subs.set_for_client(session.sock.fileno(), session.subscriptions)

        try:
            lines = self._replay.replay_since(ch, sym, last_seq)
        except ReplayMissError:
            self._queue_line(
                session,
                "ERR",
                {"CODE": "REPLAY_MISS", "CH": ch, "SYM": sym},
            )
            self._send_snapshot_for_stream(session, ch, sym)
            return

        for line in lines:
            self._queue_raw(session, line, is_market_data=True)

    def _handle_sub(self, session: ClientSession, fields: dict[str, str]) -> None:
        channels = self._parse_csv_upper(fields.get("CH", ""))
        symbols = self._parse_csv_upper(fields.get("SYM", ""))

        if not channels:
            self._queue_line(session, "ERR", {"CODE": "INVALID_CHANNEL"})
            return
        if not symbols:
            self._queue_line(session, "ERR", {"CODE": "INVALID_SYMBOL"})
            return

        # Validate channels first so request is all-or-nothing.
        for ch in channels:
            if ch not in _ALLOWED_CHANNELS:
                self._queue_line(session, "ERR", {"CODE": "INVALID_CHANNEL", "CH": ch})
                return

        # Validate symbol wildcard and known symbol list before mutating state.
        for sym in symbols:
            if sym == "*" and set(channels) != {"STATE"}:
                self._queue_line(session, "ERR", {"CODE": "INVALID_SYMBOL", "SYM": sym})
                return
            if sym != "*" and self._known_symbols and sym not in self._known_symbols:
                if not any(ch == "INDEX" for ch in channels):
                    self._queue_line(
                        session, "ERR", {"CODE": "INVALID_SYMBOL", "SYM": sym}
                    )
                    return
            if any(ch == "INDEX" for ch in channels) and not sym:
                self._queue_line(session, "ERR", {"CODE": "INVALID_SYMBOL", "SYM": sym})
                return

        requested_pairs = {(ch, sym) for ch in channels for sym in symbols}
        merged_subs = set(session.subscriptions)
        merged_subs.update(requested_pairs)

        unique_symbols = {sym for _, sym in merged_subs}
        if len(unique_symbols) > self.config.max_symbols_per_client:
            self._queue_line(session, "ERR", {"CODE": "SUB_LIMIT"})
            return

        # Only newly added pairs trigger auto SNAP behavior.
        new_pairs = requested_pairs - session.subscriptions
        session.subscriptions = merged_subs
        self._subs.set_for_client(session.sock.fileno(), session.subscriptions)

        for ch, sym in sorted(new_pairs):
            if ch in {"TOP", "STATE"}:
                self._send_snapshot_for_stream(session, ch, sym)

    def _handle_unsub(self, session: ClientSession, fields: dict[str, str]) -> None:
        channels = self._parse_csv_upper(fields.get("CH", ""))
        symbols = self._parse_csv_upper(fields.get("SYM", ""))
        if not channels or not symbols:
            self._queue_line(session, "ERR", {"CODE": "BAD_MESSAGE"})
            return

        for ch in channels:
            for sym in symbols:
                session.subscriptions.discard((ch, sym))
        self._subs.set_for_client(session.sock.fileno(), session.subscriptions)

    # ------------------------------------------------------------------
    # Snapshot and stream emission
    # ------------------------------------------------------------------

    def _send_snapshot_for_stream(
        self, session: ClientSession, ch: str, sym: str
    ) -> None:
        seq = self._sequencer.ensure_started(ch, sym)
        fields: dict[str, str] = {
            "CH": ch,
            "SYM": sym,
            "SEQ": str(seq),
            "TS": iso_utc(time.time()),
        }
        if ch == "TOP":
            fields.update(self._normaliser.top_snapshot_fields(sym))
        elif ch == "STATE":
            fields.update(self._normaliser.state_snapshot_fields(sym))
        elif ch == "INDEX":
            fields.update(self._normaliser.index_snapshot_fields(sym))

        self._queue_raw(session, build_line("SNAP", fields), is_market_data=True)

    def _emit_stream_event(
        self,
        msg_type: str,
        ch: str,
        sym: str,
        payload_fields: dict[str, str],
        ts_seconds: float,
    ) -> None:
        """Emit one market-data event to subscribed clients.

        This method centralizes sequence allocation + replay persistence so all
        CALF stream event types behave consistently.
        """
        seq = self._sequencer.next_seq(ch, sym)
        fields = {
            "CH": ch,
            "SYM": sym,
            "SEQ": str(seq),
            "TS": iso_utc(ts_seconds),
        }
        fields.update(payload_fields)

        line = build_line(msg_type, fields)
        self._replay.append(ch, sym, seq, line)

        for target in self._clients.values():
            if not target.authenticated:
                continue
            if self._subs.session_wants(target.sock.fileno(), ch, sym):
                self._queue_raw(target, line, is_market_data=True)

    # ------------------------------------------------------------------
    # Engine event mapping
    # ------------------------------------------------------------------

    def _poll_engine_events(self) -> None:
        while self._sub_sock.poll(timeout=0):
            try:
                topic, payload = decode(self._sub_sock.recv_multipart())
            except Exception:
                continue
            now_seconds = _extract_ts(payload)

            if topic.startswith("book."):
                sym = topic[5:].upper()
                self._known_symbols.add(sym)
                md_fields = self._normaliser.normalise_book(sym, payload)
                if md_fields:
                    self._emit_stream_event("MD", "TOP", sym, md_fields, now_seconds)
                continue

            if topic == "trade.executed":
                sym, trade_fields = self._normaliser.normalise_trade(payload)
                if sym:
                    self._known_symbols.add(sym)
                    self._emit_stream_event(
                        "TRADE",
                        "TRADE",
                        sym,
                        trade_fields,
                        now_seconds,
                    )
                continue

            if topic == "session.state":
                sym, state_fields = self._normaliser.normalise_session_state(payload)
                self._emit_stream_event(
                    "STATE", "STATE", sym, state_fields, now_seconds
                )
                continue

            if topic.startswith("circuit_breaker.halt."):
                sym = topic.split(".", 2)[2].upper()
                state_sym, state_fields = self._normaliser.normalise_halt(sym)
                self._emit_stream_event(
                    "STATE",
                    "STATE",
                    state_sym,
                    state_fields,
                    now_seconds,
                )
                continue

            if topic.startswith("circuit_breaker.resume."):
                sym = topic.split(".", 2)[2].upper()
                state_sym, state_fields = self._normaliser.normalise_resume(sym)
                self._emit_stream_event(
                    "STATE",
                    "STATE",
                    state_sym,
                    state_fields,
                    now_seconds,
                )

        while self._index_sub.poll(timeout=0):
            try:
                topic, payload = decode(self._index_sub.recv_multipart())
            except Exception:
                continue
            now_seconds = _extract_ts(payload)
            if topic == "index.update":
                index_id, fields = self._normaliser.normalise_index_update(payload)
                if index_id:
                    self._emit_stream_event(
                        "IDX", "INDEX", index_id, fields, now_seconds
                    )

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def _send_heartbeats_if_due(self) -> None:
        now = time.monotonic()
        for session in self._clients.values():
            if not session.authenticated:
                continue
            baseline = max(session.last_market_data_sent, session.last_heartbeat_sent)
            if now - baseline < self.config.heartbeat_interval_sec:
                continue
            self._queue_line(session, "HB", {"TS": iso_utc(time.time())})
            session.last_heartbeat_sent = now

    def _drop_idle_clients(self) -> None:
        now = time.monotonic()
        for session in list(self._clients.values()):
            idle = now - session.last_activity
            if not session.authenticated and idle > _HELLO_TIMEOUT_SEC:
                self._disconnect(session)
                continue
            if session.authenticated and idle > self.config.idle_timeout_sec:
                self._disconnect(session)

    # ------------------------------------------------------------------
    # Queue/disconnect helpers
    # ------------------------------------------------------------------

    def _queue_line(
        self,
        session: ClientSession,
        msg_type: str,
        fields: dict[str, str],
    ) -> None:
        self._queue_raw(session, build_line(msg_type, fields), is_market_data=False)

    def _queue_raw(
        self,
        session: ClientSession,
        payload: bytes,
        *,
        is_market_data: bool,
    ) -> None:
        session.out_queue.append(payload)
        if is_market_data:
            session.last_market_data_sent = time.monotonic()

    def _disconnect(self, session: ClientSession) -> None:
        fd = session.sock.fileno()
        try:
            session.sock.close()
        except OSError:
            pass
        self._clients.pop(fd, None)
        self._subs.remove_client(fd)

    def _close_after_flush(self, session: ClientSession) -> None:
        session.closing = True

    @staticmethod
    def _parse_csv_upper(raw: str) -> list[str]:
        return [token.strip().upper() for token in raw.split(",") if token.strip()]


def _extract_ts(payload: dict[str, Any]) -> float:
    """Extract event timestamp with robust fallback."""
    raw = payload.get("timestamp")
    if raw is None:
        return time.time()
    try:
        return float(raw)
    except (TypeError, ValueError):
        return time.time()

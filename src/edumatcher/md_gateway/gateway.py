"""CALF market data gateway runtime.

Design priorities for this implementation:
- Correctness first: strict protocol validation and deterministic behavior
- Maintainability: clear decomposition and heavily documented control flow
- Defensive behavior: bounded queues, explicit disconnect paths, replay checks

The gateway bridges engine PUB topics onto CALF/TCP streams.
"""

from __future__ import annotations

import logging
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

_ALLOWED_CHANNELS = frozenset({"TOP", "TRADE", "STATE", "INDEX", "DEPTH"})
# Channels that may be combined with SYM=* on a single SUB line (CALF 1.0.0,
# see EduMatcher-CALF-Extensions.md §5). INDEX and DEPTH are deliberately
# excluded: INDEX always requires an explicit index id, and DEPTH is heavy
# enough per-message that a wildcard subscription could multiply one
# client's outbound bandwidth by the whole symbol count (§6.9).
_WILDCARD_ELIGIBLE_CHANNELS = frozenset({"STATE", "TOP", "TRADE"})
_MAX_LINE_BYTES = 4096
_HELLO_TIMEOUT_SEC = 5
_MAX_ENGINE_EVENTS_PER_LOOP = 2000

log = logging.getLogger(__name__)


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
        self._normaliser = EngineNormaliser(depth_levels=config.depth_levels)
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

        log.info(
            "listening on %s:%s (engine_pub=%s index_pub=%s)",
            self.config.bind_address,
            self.config.port,
            self.config.engine_pub_addr,
            self.config.index_pub_addr,
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
        log.info("stop requested")
        self._running = False

    def close(self) -> None:
        log.info("closing market data gateway")
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
            session = ClientSession(sock=conn, addr=addr)
            session.rate_tokens = float(self.config.max_messages_per_second)
            self._clients[conn.fileno()] = session
            log.info(
                "client connected addr=%s:%s fd=%d", addr[0], addr[1], conn.fileno()
            )

    def _read_client_data(self) -> None:
        if not self._clients:
            return

        readable = [session.sock for session in self._clients.values()]
        try:
            ready, _, _ = select.select(readable, [], [], 0)
        except (OSError, ValueError) as exc:
            log.warning("read select failed: %s", exc)
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
                log.warning(
                    "dropping client fd=%d due to oversized inbound line",
                    session.sock.fileno(),
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
                log.warning(
                    "dropping client fd=%d due to oversized framed line",
                    session.sock.fileno(),
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

                if session.out_offset >= len(payload):
                    session.out_queue.popleft()
                    session.out_offset = 0

            if len(session.out_queue) > self.config.max_client_queue:
                log.warning(
                    "disconnecting slow client fd=%d queue=%d max=%d",
                    session.sock.fileno(),
                    len(session.out_queue),
                    self.config.max_client_queue,
                )
                self._disconnect(session, reason="slow_client")
                continue

            if session.closing and not session.out_queue:
                self._disconnect(session, reason="close_after_flush")

    # ------------------------------------------------------------------
    # Protocol handling
    # ------------------------------------------------------------------

    def _handle_client_line(self, session: ClientSession, line: str) -> None:
        try:
            frame = parse_line(line)
        except Exception as exc:
            log.debug(
                "parse error for fd=%d line=%r err=%s", session.sock.fileno(), line, exc
            )
            self._queue_line(
                session,
                "ERR",
                {"CODE": "BAD_MESSAGE", "MSG": "parse error"},
            )
            return

        if not self._allow_message_now(session):
            log.debug("rate-limited client fd=%d", session.sock.fileno())
            self._queue_line(
                session,
                "ERR",
                {"CODE": "RATE_LIMITED", "MSG": "too many messages"},
            )
            return

        if not session.authenticated:
            if frame.msg_type != "HELLO":
                self._queue_line(
                    session,
                    "ERR",
                    {"CODE": "AUTH_REQUIRED", "MSG": "send HELLO first"},
                )
                log.info(
                    "pre-auth command rejected fd=%d cmd=%s",
                    session.sock.fileno(),
                    frame.msg_type,
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
            log.debug(
                "unsupported command fd=%d cmd=%s",
                session.sock.fileno(),
                frame.msg_type,
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
            # CH_SUPPORTED lets a client detect gateway capability without a
            # PROTO version bump (EduMatcher-CALF-Extensions.md §3.2). Always
            # the full _ALLOWED_CHANNELS list since every channel in it ships
            # on by default as of 1.0.0 — its value to a client is mainly in
            # its *presence*, which distinguishes a 1.0.0+ gateway from a
            # pre-1.0.0 one that predates this field entirely.
            "CH_SUPPORTED": ",".join(sorted(_ALLOWED_CHANNELS)),
        }
        if self._known_symbols:
            welcome_fields["SYMBOLS"] = ",".join(sorted(self._known_symbols))

        self._queue_line(session, "WELCOME", welcome_fields)
        log.info("client authenticated fd=%d client=%s", session.sock.fileno(), client)

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
        # SYM=* is allowed for STATE, TOP, and TRADE (CALF 1.0.0, see
        # EduMatcher-CALF-Extensions.md §5); INDEX and DEPTH still require an
        # explicit symbol/index id (§4.2, §6.9).
        for sym in symbols:
            if sym == "*" and not set(channels).issubset(_WILDCARD_ELIGIBLE_CHANNELS):
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
        log.debug(
            "subscriptions updated fd=%d total=%d new=%d",
            session.sock.fileno(),
            len(session.subscriptions),
            len(new_pairs),
        )

        for ch, sym in sorted(new_pairs):
            # Wildcard TOP has no single meaningful "top of book" of its own
            # (unlike STATE's session-wide summary) — top_snapshot_fields("*")
            # would look up a symbol literally named "*" and return an empty
            # snapshot. Send one real per-symbol SNAP for every currently
            # known symbol instead (EduMatcher-CALF-Extensions.md §5.4). The
            # ("TOP", "*") pair itself is still stored in session.subscriptions
            # above so future live MD events fan out via the wildcard match in
            # SubscriptionRegistry.session_wants, including for symbols that
            # become known only after this SUB.
            if ch == "TOP" and sym == "*":
                for real_sym in sorted(self._known_symbols):
                    self._send_snapshot_for_stream(session, "TOP", real_sym)
                continue
            # INDEX has always had a working SNAP path (index_snapshot_fields,
            # the "elif ch == 'INDEX'" branch below) but it was never wired
            # into SUB's auto-snapshot trigger, so SUB|CH=INDEX silently sent
            # no baseline — contradicting EduMatcher-Index.md's original
            # design ("gateway sends an initial SNAP"). Fixed here to match
            # TOP/STATE/DEPTH's already-established pattern.
            if ch in {"TOP", "STATE", "INDEX", "DEPTH"}:
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
        log.debug(
            "subscriptions removed fd=%d now=%d",
            session.sock.fileno(),
            len(session.subscriptions),
        )

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
        elif ch == "DEPTH":
            fields.update(self._normaliser.depth_snapshot_fields(sym))

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
        log.debug("stream event msg=%s ch=%s sym=%s seq=%d", msg_type, ch, sym, seq)

        for target in self._clients.values():
            if not target.authenticated or target.closing:
                continue
            if self._subs.session_wants(target.sock.fileno(), ch, sym):
                self._queue_raw(target, line, is_market_data=True)

    # ------------------------------------------------------------------
    # Engine event mapping
    # ------------------------------------------------------------------

    def _poll_engine_events(self) -> None:
        budget = _MAX_ENGINE_EVENTS_PER_LOOP
        while budget > 0 and self._sub_sock.poll(timeout=0):
            try:
                topic, payload = decode(self._sub_sock.recv_multipart())
            except Exception as exc:
                log.warning("md_gateway decode error on engine SUB event: %s", exc)
                budget -= 1
                continue
            budget -= 1
            try:
                now_seconds = _extract_ts(payload)

                if topic.startswith("book."):
                    sym = topic[5:].upper()
                    self._known_symbols.add(sym)
                    md_fields = self._normaliser.normalise_book(sym, payload)
                    if md_fields:
                        self._emit_stream_event(
                            "MD", "TOP", sym, md_fields, now_seconds
                        )
                    depth_fields = self._normaliser.normalise_depth(sym, payload)
                    if depth_fields:
                        self._emit_stream_event(
                            "DEPTH", "DEPTH", sym, depth_fields, now_seconds
                        )
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
                    sym, state_fields = self._normaliser.normalise_session_state(
                        payload
                    )
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
            except Exception:
                log.warning(
                    "md_gateway handler error on engine topic=%s", topic, exc_info=True
                )
                continue

        while budget > 0 and self._index_sub.poll(timeout=0):
            try:
                topic, payload = decode(self._index_sub.recv_multipart())
            except Exception as exc:
                log.warning("md_gateway decode error on index SUB event: %s", exc)
                budget -= 1
                continue
            budget -= 1
            try:
                now_seconds = _extract_ts(payload)
                if topic == "index.update":
                    index_id, fields = self._normaliser.normalise_index_update(payload)
                    if index_id:
                        self._emit_stream_event(
                            "IDX", "INDEX", index_id, fields, now_seconds
                        )
            except Exception:
                log.warning(
                    "md_gateway handler error on index topic=%s", topic, exc_info=True
                )
                continue

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
            if (
                not session.authenticated
                and now - session.connected_at > _HELLO_TIMEOUT_SEC
            ):
                self._disconnect(session, reason="auth_timeout")
                continue
            if session.authenticated and idle > self.config.idle_timeout_sec:
                self._disconnect(session, reason="idle_timeout")

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
        if session.closing and is_market_data:
            return
        if len(session.out_queue) >= self.config.max_client_queue:
            if not session.closing:
                session.out_queue.clear()
                session.out_offset = 0
                session.closing = True
            return
        session.out_queue.append(payload)
        if is_market_data:
            session.last_market_data_sent = time.monotonic()

    def _allow_message_now(self, session: ClientSession) -> bool:
        now = time.monotonic()
        elapsed = now - session.rate_updated
        session.rate_updated = now
        max_rate = float(self.config.max_messages_per_second)
        session.rate_tokens = min(max_rate, session.rate_tokens + elapsed * max_rate)
        if session.rate_tokens < 1.0:
            log.debug("message bucket empty fd=%d", session.sock.fileno())
            return False
        session.rate_tokens -= 1.0
        return True

    def _disconnect(self, session: ClientSession, reason: str = "unspecified") -> None:
        fd = session.sock.fileno()
        client_id = session.client_id or "-"
        try:
            session.sock.close()
        except OSError:
            pass
        self._clients.pop(fd, None)
        self._subs.remove_client(fd)
        log.info("client disconnected fd=%d client=%s reason=%s", fd, client_id, reason)

    def _close_after_flush(self, session: ClientSession) -> None:
        session.closing = True
        log.debug("session fd=%d marked closing-after-flush", session.sock.fileno())

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

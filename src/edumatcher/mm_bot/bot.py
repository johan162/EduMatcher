"""MMBot — state machine and event loop for the market-maker bot."""

from __future__ import annotations

import random
import signal
import time
from enum import Enum
from typing import Any

import zmq

from edumatcher.messaging.bus import make_pusher, make_subscriber
from edumatcher.models.message import (
    decode,
    make_gateway_connect_msg,
    make_quote_bootstrap_request_msg,
    make_quote_cancel_msg,
    make_quote_legs_request_msg,
    make_quote_new_msg,
    make_symbols_request_msg,
)
from edumatcher.mm_bot.pricer import QuotePricer


class BotState(str, Enum):
    CONNECTING = "CONNECTING"
    AUTHENTICATING = "AUTHENTICATING"
    WAITING_FOR_SESSION = "WAITING_FOR_SESSION"
    QUOTING = "QUOTING"
    REPRICING = "REPRICING"
    REISSUING = "REISSUING"
    PAUSED = "PAUSED"


# Session states where quoting is allowed
_QUOTING_SESSIONS = {"CONTINUOUS"}


class MMBot:
    """Autonomous market-maker bot for a single symbol."""

    def __init__(
        self,
        *,
        gateway_id: str,
        symbol: str,
        gap: float,
        qty: int,
        drift_ticks: int,
        reissue_delay_ms: int,
        tif: str,
        heartbeat_interval_sec: float,
        startup_session_timeout_sec: float,
        bootstrap_timeout_sec: float,
        cancel_timeout_sec: float,
        shutdown_timeout_sec: float,
        qlegs_reconcile_interval_sec: float,
        initial_min: float | None,
        initial_max: float | None,
        engine_pull: str,
        engine_pub: str,
        verbose: bool,
    ) -> None:
        self.gateway_id = gateway_id
        self.symbol = symbol
        self.gap = gap
        self.qty = qty
        self.drift_ticks = drift_ticks
        self.tif = tif
        self.verbose = verbose

        self._reissue_delay_sec = reissue_delay_ms / 1000.0
        self._heartbeat_interval_sec = heartbeat_interval_sec
        self._startup_session_timeout_sec = startup_session_timeout_sec
        self._bootstrap_timeout_sec = bootstrap_timeout_sec
        self._cancel_timeout_sec = cancel_timeout_sec
        self._shutdown_timeout_sec = shutdown_timeout_sec
        self._qlegs_reconcile_interval_sec = qlegs_reconcile_interval_sec
        self._initial_min = initial_min
        self._initial_max = initial_max
        self._engine_pull = engine_pull
        self._engine_pub = engine_pub

        # Runtime state
        self._running = False
        self._state = BotState.CONNECTING
        self._session_state: str | None = None
        self._tick_size = 0.01  # default; updated from symbol metadata
        self._pricer: QuotePricer | None = None

        # Quote tracking
        self._quote_id: str | None = None
        self._bid_order_id: str | None = None
        self._ask_order_id: str | None = None
        self._quoted_at_mid: float | None = None
        self._reissue_at: float | None = None
        self._last_heartbeat: float = 0.0
        self._last_qlegs_reconcile: float = 0.0

        # Pre-ack fill buffer
        self._pending_fills: list[dict[str, Any]] = []

        # Sockets (created in run())
        self._push_sock: zmq.Socket[bytes] | None = None
        self._sub_sock: zmq.Socket[bytes] | None = None

    def _log(self, text: str) -> None:
        now = time.strftime("%H:%M:%S")
        print(f"[MM:{self.gateway_id} {now}] {text}")

    def _debug(self, text: str) -> None:
        if self.verbose:
            self._log(text)

    def _setup_sockets(self) -> None:
        self._push_sock = make_pusher(self._engine_pull)
        self._sub_sock = make_subscriber(
            self._engine_pub,
            f"system.gateway_auth.{self.gateway_id}",
            f"system.symbols.{self.gateway_id}",
            f"system.quote_bootstrap.{self.gateway_id}",
            f"system.quote_legs.{self.gateway_id}",
            f"book.{self.symbol}",
            "trade.executed",
            f"order.fill.{self.gateway_id}",
            f"order.cancelled.{self.gateway_id}",
            f"quote.ack.{self.gateway_id}",
            f"quote.status.{self.gateway_id}",
            "session.state",
            f"circuit_breaker.halt.{self.symbol}",
            f"circuit_breaker.resume.{self.symbol}",
        )

    def _close_sockets(self) -> None:
        if self._push_sock:
            self._push_sock.close()
            self._push_sock = None
        if self._sub_sock:
            self._sub_sock.close()
            self._sub_sock = None

    def _send(self, frames: list[bytes]) -> None:
        if self._push_sock:
            self._push_sock.send_multipart(frames)

    def _authenticate(self, timeout_sec: float = 3.0) -> bool:
        """Send gateway_connect and wait for auth ACK."""
        assert self._sub_sock is not None
        time.sleep(0.05)
        self._send(make_gateway_connect_msg(self.gateway_id))
        self._state = BotState.AUTHENTICATING

        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        deadline = time.monotonic() + timeout_sec

        while time.monotonic() < deadline:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            socks = dict(poller.poll(timeout=min(remaining_ms, 200)))
            if self._sub_sock not in socks:
                continue
            topic, payload = decode(self._sub_sock.recv_multipart())
            if topic == f"system.gateway_auth.{self.gateway_id}":
                accepted = bool(payload.get("accepted", False))
                if accepted:
                    self._log("authenticated")
                else:
                    reason = str(payload.get("reason", "unknown"))
                    self._log(f"auth rejected: {reason}")
                return accepted
            # Also capture session.state that arrives during auth
            if topic == "session.state":
                self._session_state = str(payload.get("state", "")).upper()
                self._debug(f"session state (during auth): {self._session_state}")

        self._log("authentication timed out")
        return False

    def _request_symbols(self, timeout_sec: float = 3.0) -> list[str]:
        """Request and wait for symbol list."""
        assert self._sub_sock is not None
        self._send(make_symbols_request_msg(self.gateway_id))

        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        deadline = time.monotonic() + timeout_sec

        while time.monotonic() < deadline:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            socks = dict(poller.poll(timeout=min(remaining_ms, 200)))
            if self._sub_sock not in socks:
                continue
            topic, payload = decode(self._sub_sock.recv_multipart())
            if topic == f"system.symbols.{self.gateway_id}":
                symbols = [str(s).upper() for s in payload.get("symbols", [])]
                self._debug(f"symbols received: {symbols}")
                # Extract tick_size if available
                sym_meta = payload.get("symbol_meta", {})
                if self.symbol in sym_meta:
                    meta = sym_meta[self.symbol]
                    if "tick_size" in meta:
                        self._tick_size = float(meta["tick_size"])
                return symbols
            if topic == "session.state":
                self._session_state = str(payload.get("state", "")).upper()

        self._log("symbols request timed out")
        return []

    def _request_bootstrap(self) -> dict[str, Any] | None:
        """Request QBOOT and wait for reply within timeout."""
        assert self._sub_sock is not None
        self._send(make_quote_bootstrap_request_msg(self.gateway_id, self.symbol))

        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        deadline = time.monotonic() + self._bootstrap_timeout_sec

        while time.monotonic() < deadline:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            socks = dict(poller.poll(timeout=min(remaining_ms, 100)))
            if self._sub_sock not in socks:
                continue
            topic, payload = decode(self._sub_sock.recv_multipart())
            if topic == f"system.quote_bootstrap.{self.gateway_id}":
                return payload
            # Capture other events during wait
            self._buffer_event(topic, payload)

        self._debug("QBOOT request timed out — continuing with fallback")
        return None

    def _request_qlegs(self) -> dict[str, Any] | None:
        """Request QLEGS snapshot and wait for reply."""
        assert self._sub_sock is not None
        self._send(make_quote_legs_request_msg(self.gateway_id, self.symbol, "ALL"))

        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        deadline = time.monotonic() + self._bootstrap_timeout_sec

        while time.monotonic() < deadline:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            socks = dict(poller.poll(timeout=min(remaining_ms, 100)))
            if self._sub_sock not in socks:
                continue
            topic, payload = decode(self._sub_sock.recv_multipart())
            if topic == f"system.quote_legs.{self.gateway_id}":
                return payload
            self._buffer_event(topic, payload)

        self._debug("QLEGS request timed out")
        return None

    def _buffer_event(self, topic: str, payload: dict[str, Any]) -> None:
        """Buffer events received during startup waits."""
        if topic == "session.state":
            self._session_state = str(payload.get("state", "")).upper()
        elif topic == f"book.{self.symbol}":
            self._handle_book(payload)
        elif topic == "trade.executed":
            self._handle_trade(payload)

    def _try_adopt_from_bootstrap(self, boot_payload: dict[str, Any] | None) -> bool:
        """Try to adopt an active quote from QBOOT. Returns True if adopted."""
        if not boot_payload:
            return False
        assert self._pricer is not None

        quotes = boot_payload.get("quotes", [])
        for q in quotes:
            if (
                str(q.get("symbol", "")).upper() == self.symbol
                and str(q.get("state", "")).upper() == "ACTIVE"
            ):
                self._quote_id = str(q.get("quote_id", ""))
                self._bid_order_id = str(q.get("bid_order_id", ""))
                self._ask_order_id = str(q.get("ask_order_id", ""))
                bid_price = q.get("bid_price")
                ask_price = q.get("ask_price")
                if bid_price is not None and ask_price is not None:
                    mid = (float(bid_price) + float(ask_price)) / 2.0
                    self._pricer.set_mid(mid)
                    self._quoted_at_mid = mid
                    self._log(
                        f"adopted existing quote {self._quote_id} "
                        f"bid={bid_price} ask={ask_price}"
                    )
                    return True
        return False

    def _resolve_bootstrap_reference(self, boot_payload: dict[str, Any] | None) -> bool:
        """Resolve initial reference price (non-adopt). Returns True if resolved."""
        assert self._pricer is not None

        # 1. Book-derived mid
        if self._pricer.mid_price is not None:
            self._debug(f"reference from book: {self._pricer.mid_price}")
            return True

        # 2. Check QBOOT for inactive quote prices as reference
        if boot_payload:
            quotes = boot_payload.get("quotes", [])
            for q in quotes:
                if str(q.get("symbol", "")).upper() == self.symbol:
                    bid_price = q.get("bid_price")
                    ask_price = q.get("ask_price")
                    if bid_price is not None and ask_price is not None:
                        mid = (float(bid_price) + float(ask_price)) / 2.0
                        self._pricer.set_mid(mid)
                        self._debug(f"reference from bootstrap quote: {mid}")
                        return True

        # 4. Random bootstrap
        if self._initial_min is not None and self._initial_max is not None:
            price = random.uniform(self._initial_min, self._initial_max)
            # Round to nearest tick
            price = round(
                round(price / self._tick_size) * self._tick_size,
                self._pricer.price_decimals,
            )
            self._pricer.set_mid(price)
            self._log(f"bootstrap from random range: {price}")
            return True

        return False

    def _wait_for_session(self, timeout_sec: float) -> bool:
        """Wait for first session.state event. Returns True if received."""
        if self._session_state is not None:
            return True

        assert self._sub_sock is not None
        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        deadline = time.monotonic() + timeout_sec

        while time.monotonic() < deadline:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            socks = dict(poller.poll(timeout=min(remaining_ms, 200)))
            if self._sub_sock not in socks:
                continue
            topic, payload = decode(self._sub_sock.recv_multipart())
            if topic == "session.state":
                self._session_state = str(payload.get("state", "")).upper()
                return True
            self._buffer_event(topic, payload)

        return False

    def _send_quote(self) -> None:
        """Compute prices and send a fresh quote."""
        assert self._pricer is not None
        if self._pricer.mid_price is None:
            self._debug("cannot send quote — no mid price")
            return

        bid, ask = self._pricer.compute_prices()
        quote_payload: dict[str, Any] = {
            "gateway_id": self.gateway_id,
            "symbol": self.symbol,
            "bid_price": bid,
            "ask_price": ask,
            "bid_qty": self.qty,
            "ask_qty": self.qty,
            "tif": self.tif,
        }
        self._send(make_quote_new_msg(quote_payload))
        self._quoted_at_mid = self._pricer.mid_price
        self._state = BotState.REISSUING
        self._debug(f"QUOTE sent bid={bid} ask={ask}")

    def _cancel_quote(self) -> None:
        """Send quote.cancel for current symbol."""
        self._send(make_quote_cancel_msg(self.gateway_id, self.symbol))
        self._debug("CANCEL sent")

    def _cancel_and_reissue(self) -> None:
        """Replace active quote with a fresh one at current mid."""
        self._send_quote()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _handle_book(self, payload: dict[str, Any]) -> None:
        """Handle book.SYMBOL event."""
        if self._pricer is None:
            return
        bids = payload.get("bids", [])
        asks = payload.get("asks", [])
        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None
        self._pricer.update_mid(best_bid, best_ask)
        self._debug(f"book mid={self._pricer.mid_price}")

    def _handle_trade(self, payload: dict[str, Any]) -> None:
        """Handle trade.executed — update mid if no book data."""
        if self._pricer is None:
            return
        symbol = str(payload.get("symbol", "")).upper()
        if symbol != self.symbol:
            return
        price = payload.get("price")
        if price is not None and self._pricer.mid_price is None:
            self._pricer.set_mid(float(price))
            self._debug(f"mid from trade: {price}")

    def _handle_quote_ack(self, payload: dict[str, Any]) -> None:
        """Handle quote.ack — record IDs or handle rejection."""
        accepted = bool(payload.get("accepted", False))
        if accepted:
            self._quote_id = str(payload.get("quote_id", ""))
            self._bid_order_id = str(payload.get("bid_order_id", ""))
            self._ask_order_id = str(payload.get("ask_order_id", ""))
            self._state = BotState.QUOTING
            self._debug(f"quote ACK id={self._quote_id}")
            # Process buffered fills
            self._process_pending_fills()
        else:
            reason = str(payload.get("reason", "unknown"))
            self._log(f"quote REJECTED: {reason}")
            # Retry after delay
            self._reissue_at = time.monotonic() + self._reissue_delay_sec

    def _handle_quote_status(self, payload: dict[str, Any]) -> None:
        """Handle quote.status — detect INACTIVE/CANCELLED."""
        status = str(payload.get("status", "")).upper()
        self._debug(f"quote.status: {status}")

        if status in ("INACTIVE_BID_FILLED", "INACTIVE_ASK_FILLED", "CANCELLED"):
            # Schedule reissue
            if self._state not in (BotState.PAUSED, BotState.WAITING_FOR_SESSION):
                self._reissue_at = time.monotonic() + self._reissue_delay_sec
                self._quote_id = None
                self._bid_order_id = None
                self._ask_order_id = None

    def _handle_order_fill(self, payload: dict[str, Any]) -> None:
        """Handle order.fill — check if it belongs to our quote."""
        order_id = str(payload.get("order_id", ""))

        # If we don't have ack mapping yet, buffer the fill
        if self._bid_order_id is None and self._ask_order_id is None:
            self._pending_fills.append(payload)
            return

        if order_id not in (self._bid_order_id, self._ask_order_id):
            return  # not our quote

        side = "BID" if order_id == self._bid_order_id else "ASK"
        fill_qty = payload.get("fill_qty", 0)
        self._debug(f"fill: {side} {fill_qty}@{payload.get('fill_price', '?')}")

        # Reset or start the reissue timer
        self._reissue_at = time.monotonic() + self._reissue_delay_sec

    def _handle_order_cancelled(self, payload: dict[str, Any]) -> None:
        """Handle order.cancelled — track leg cleanup."""
        order_id = str(payload.get("order_id", ""))
        if order_id in (self._bid_order_id, self._ask_order_id):
            self._debug(f"leg cancelled: {order_id}")

    def _handle_session_state(self, payload: dict[str, Any]) -> None:
        """Handle session.state transitions."""
        new_state = str(payload.get("state", "")).upper()
        old_state = self._session_state
        self._session_state = new_state
        self._debug(f"session: {old_state} -> {new_state}")

        if new_state in _QUOTING_SESSIONS:
            if self._state == BotState.PAUSED:
                self._state = BotState.WAITING_FOR_SESSION
                # Trigger reissue if we have reference
                if self._pricer and self._pricer.mid_price is not None:
                    self._reissue_at = time.monotonic()
        else:
            # Non-trading phase — cancel and pause
            if self._state in (BotState.QUOTING, BotState.REPRICING):
                self._cancel_quote()
                self._quote_id = None
                self._bid_order_id = None
                self._ask_order_id = None
            self._state = BotState.PAUSED
            self._reissue_at = None

    def _handle_circuit_breaker_halt(self) -> None:
        """Handle circuit_breaker.halt.SYMBOL."""
        self._log("circuit breaker HALT")
        if self._state in (BotState.QUOTING, BotState.REPRICING, BotState.REISSUING):
            self._cancel_quote()
            self._quote_id = None
            self._bid_order_id = None
            self._ask_order_id = None
        self._state = BotState.PAUSED
        self._reissue_at = None

    def _handle_circuit_breaker_resume(self) -> None:
        """Handle circuit_breaker.resume.SYMBOL."""
        self._log("circuit breaker RESUME")
        self._state = BotState.WAITING_FOR_SESSION

    def _process_pending_fills(self) -> None:
        """Process fills that arrived before quote.ack."""
        for fill in self._pending_fills:
            self._handle_order_fill(fill)
        self._pending_fills.clear()

    # ------------------------------------------------------------------
    # Main event loop
    # ------------------------------------------------------------------

    def _dispatch(self, topic: str, payload: dict[str, Any]) -> None:
        """Route an incoming message to the appropriate handler."""
        if topic == f"book.{self.symbol}":
            self._handle_book(payload)
            # Check drift while quoting
            if (
                self._state == BotState.QUOTING
                and self._pricer
                and self._quoted_at_mid is not None
                and self._pricer.has_drifted(self._quoted_at_mid)
            ):
                self._state = BotState.REPRICING
                self._debug("drift detected — repricing")
                self._cancel_and_reissue()
        elif topic == "trade.executed":
            self._handle_trade(payload)
        elif topic == f"quote.ack.{self.gateway_id}":
            self._handle_quote_ack(payload)
        elif topic == f"quote.status.{self.gateway_id}":
            self._handle_quote_status(payload)
        elif topic == f"order.fill.{self.gateway_id}":
            self._handle_order_fill(payload)
        elif topic == f"order.cancelled.{self.gateway_id}":
            self._handle_order_cancelled(payload)
        elif topic == "session.state":
            self._handle_session_state(payload)
        elif topic == f"circuit_breaker.halt.{self.symbol}":
            self._handle_circuit_breaker_halt()
        elif topic == f"circuit_breaker.resume.{self.symbol}":
            self._handle_circuit_breaker_resume()

    def _tick(self) -> None:
        """Periodic housekeeping — reissue timer, heartbeat, QLEGS."""
        now = time.monotonic()

        # Reissue timer
        if self._reissue_at is not None and now >= self._reissue_at:
            self._reissue_at = None
            if self._state in (
                BotState.QUOTING,
                BotState.REPRICING,
                BotState.REISSUING,
                BotState.WAITING_FOR_SESSION,
            ):
                if (
                    self._session_state in _QUOTING_SESSIONS
                    and self._pricer
                    and self._pricer.mid_price is not None
                ):
                    self._cancel_and_reissue()
                elif self._state == BotState.WAITING_FOR_SESSION:
                    pass  # wait for session
                else:
                    self._state = BotState.WAITING_FOR_SESSION

        # Heartbeat guard
        if now - self._last_heartbeat >= self._heartbeat_interval_sec:
            self._last_heartbeat = now
            if (
                self._state == BotState.QUOTING
                and self._quote_id is None
                and self._session_state in _QUOTING_SESSIONS
                and self._pricer
                and self._pricer.mid_price is not None
            ):
                self._log("heartbeat: no active quote — reissuing")
                self._cancel_and_reissue()

        # Periodic QLEGS reconciliation
        if now - self._last_qlegs_reconcile >= self._qlegs_reconcile_interval_sec:
            self._last_qlegs_reconcile = now
            if self._state == BotState.QUOTING:
                self._reconcile_qlegs()

    def _reconcile_qlegs(self) -> None:
        """Send QLEGS and reconcile against local state."""
        payload = self._request_qlegs()
        if payload is None:
            return

        legs = payload.get("legs", [])
        if not legs and self._quote_id is not None:
            # Engine says no legs but we think we have a quote
            self._log("QLEGS mismatch: no legs but local quote exists — reissuing")
            self._quote_id = None
            self._bid_order_id = None
            self._ask_order_id = None
            self._reissue_at = time.monotonic()
            return

        # Check if our IDs match
        for leg in legs:
            leg_qid = str(leg.get("quote_id", ""))
            if leg_qid and self._quote_id and leg_qid != self._quote_id:
                self._log("QLEGS mismatch: quote_id divergence — reissuing")
                self._quote_id = None
                self._bid_order_id = None
                self._ask_order_id = None
                self._reissue_at = time.monotonic()
                return

    def run(self) -> int:
        """Run the bot event loop. Returns exit code."""
        self._setup_sockets()
        self._running = True

        # Install signal handlers
        def _sig_handler(signum: int, frame: Any) -> None:
            self._running = False

        signal.signal(signal.SIGINT, _sig_handler)
        signal.signal(signal.SIGTERM, _sig_handler)

        try:
            return self._run_loop()
        finally:
            self._close_sockets()

    def _run_loop(self) -> int:
        """Internal event loop."""
        # Step 1: Authenticate
        if not self._authenticate():
            self._log("startup failed: authentication")
            return 1

        # Step 2: Request symbols
        symbols = self._request_symbols()
        if symbols and self.symbol not in symbols:
            self._log(f"startup failed: {self.symbol} not in symbol list")
            return 1

        # Step 3: Initialize pricer
        self._pricer = QuotePricer(
            tick_size=self._tick_size,
            gap=self.gap,
            drift_ticks=self.drift_ticks,
        )

        # Step 4: QBOOT — try adoption
        boot_payload = self._request_bootstrap()
        self._try_adopt_from_bootstrap(boot_payload)

        # Step 5: QLEGS reconciliation
        qlegs_payload = self._request_qlegs()
        if qlegs_payload and self._quote_id:
            # Reconcile adopted quote against legs
            legs = qlegs_payload.get("legs", [])
            if legs:
                for leg in legs:
                    if str(leg.get("quote_id", "")) != self._quote_id:
                        self._log("startup QLEGS mismatch — clearing adopted state")
                        self._quote_id = None
                        self._bid_order_id = None
                        self._ask_order_id = None
                        break

        # Step 6: Wait for session state
        if not self._wait_for_session(self._startup_session_timeout_sec):
            self._log("startup failed: no session.state received within timeout")
            return 1

        # Step 7: Determine initial state
        has_adopted = self._quote_id is not None
        if has_adopted:
            # We adopted an existing quote from QBOOT
            if self._session_state in _QUOTING_SESSIONS:
                self._state = BotState.QUOTING
            else:
                self._state = BotState.PAUSED
        else:
            # Need to resolve reference (book/trade/bootstrap-quote/random)
            resolved = self._resolve_bootstrap_reference(boot_payload)
            if not resolved:
                self._log(
                    "startup failed: no reference price available "
                    "(no book, no trade, no bootstrap, no random range)"
                )
                return 1
            if self._session_state in _QUOTING_SESSIONS:
                self._state = BotState.WAITING_FOR_SESSION
                self._send_quote()
            else:
                self._state = BotState.PAUSED

        self._log(f"running state={self._state.value} session={self._session_state}")
        self._last_heartbeat = time.monotonic()
        self._last_qlegs_reconcile = time.monotonic()

        # Main event loop
        assert self._sub_sock is not None
        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        poll_timeout_ms = max(
            50, int(min(self._heartbeat_interval_sec, self._reissue_delay_sec) * 500)
        )

        while self._running:
            socks = dict(poller.poll(timeout=poll_timeout_ms))
            if self._sub_sock in socks:
                topic, payload = decode(self._sub_sock.recv_multipart())
                self._dispatch(topic, payload)
            self._tick()

        # Shutdown
        self._do_shutdown()
        return 0

    def _do_shutdown(self) -> None:
        """Send cancel and wait for confirmation."""
        if self._state in (BotState.QUOTING, BotState.REPRICING, BotState.REISSUING):
            self._cancel_quote()
            # Wait briefly for confirmation
            if self._sub_sock:
                poller = zmq.Poller()
                poller.register(self._sub_sock, zmq.POLLIN)
                deadline = time.monotonic() + self._shutdown_timeout_sec
                while time.monotonic() < deadline:
                    remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
                    socks = dict(poller.poll(timeout=min(remaining_ms, 100)))
                    if self._sub_sock in socks:
                        topic, _payload = decode(self._sub_sock.recv_multipart())
                        if topic == f"quote.status.{self.gateway_id}":
                            self._debug("shutdown: cancel confirmed")
                            break
        self._log("shutdown complete")

    def shutdown(self) -> None:
        """External shutdown trigger."""
        self._running = False

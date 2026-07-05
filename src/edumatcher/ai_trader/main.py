"""Autonomous AI trader process.

Usage examples:
  poetry run pm-ai-trader --id AI01 --profile aggressive
  poetry run pm-ai-trader --id AI07 --profile cautious --symbols AAPL,MSFT
"""

from __future__ import annotations

import argparse
from collections import deque
import random
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any

import zmq

from edumatcher.ai_trader.personality import available_profiles, get_profile
from edumatcher.config import ENGINE_PULL_ADDR, ENGINE_PUB_ADDR
from edumatcher.messaging.bus import make_pusher, make_subscriber
from edumatcher.models.message import (
    decode,
    make_gateway_connect_msg,
    make_order_new_msg,
    make_symbols_request_msg,
)


@dataclass
class MarketSnapshot:
    best_bid: float | None = None
    best_ask: float | None = None
    last_price: float | None = None


@dataclass
class BotMetrics:
    submitted: int = 0
    acknowledged: int = 0
    rejected: int = 0
    filled: int = 0
    cancelled: int = 0


class AITraderBot:
    def __init__(
        self,
        gateway_id: str,
        profile_name: str,
        symbols: list[str],
        seed: int,
        run_id: str,
        max_position: int,
        max_rejects: int,
        reject_window_sec: float,
        reject_cooldown_sec: float,
        stale_data_sec: float,
    ) -> None:
        self.gateway_id = gateway_id.upper()
        self.profile = get_profile(profile_name)
        self._symbols_filter = [sym.upper() for sym in symbols]
        self._rng = random.Random(seed)
        self._run_id = run_id

        self._running = True
        self._last_submit_ts = 0.0
        self._market: dict[str, MarketSnapshot] = {}
        self._known_symbols: list[str] = []
        self._positions: dict[str, int] = {}
        self._last_market_update: dict[str, float] = {}
        self._reject_times: deque[float] = deque()
        self._risk_pause_until = 0.0
        self.metrics = BotMetrics()

        self._max_position = max_position
        self._max_rejects = max_rejects
        self._reject_window_sec = reject_window_sec
        self._reject_cooldown_sec = reject_cooldown_sec
        self._stale_data_sec = stale_data_sec

        self.push_sock = make_pusher(ENGINE_PULL_ADDR)
        self.sub_sock = make_subscriber(
            ENGINE_PUB_ADDR,
            f"system.gateway_auth.{self.gateway_id}",
            f"system.symbols.{self.gateway_id}",
            f"order.ack.{self.gateway_id}",
            f"order.fill.{self.gateway_id}",
            f"order.cancelled.{self.gateway_id}",
            f"order.expired.{self.gateway_id}",
            "book.",
            "trade.executed",
        )

    def _log(self, text: str) -> None:
        now = time.strftime("%H:%M:%S")
        print(f"[AI:{self.gateway_id} {now}] {text}")

    def _authenticate(self, timeout_sec: float = 3.0) -> bool:
        time.sleep(0.1)
        self.push_sock.send_multipart(make_gateway_connect_msg(self.gateway_id))

        poller = zmq.Poller()
        poller.register(self.sub_sock, zmq.POLLIN)
        deadline = time.monotonic() + timeout_sec

        while time.monotonic() < deadline:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            socks = dict(poller.poll(timeout=min(remaining_ms, 200)))
            if self.sub_sock not in socks:
                continue
            topic, payload = decode(self.sub_sock.recv_multipart())
            if topic == f"system.gateway_auth.{self.gateway_id}":
                accepted = bool(payload.get("accepted", False))
                if accepted:
                    self._log("authenticated")
                else:
                    reason = str(payload.get("reason", "unknown reason"))
                    self._log(f"authentication rejected: {reason}")
                return accepted

        self._log("authentication timed out")
        return False

    def _request_symbols(self) -> None:
        self.push_sock.send_multipart(make_symbols_request_msg(self.gateway_id))

    def _on_book(self, symbol: str, payload: dict[str, Any]) -> None:
        bids = payload.get("bids", [])
        asks = payload.get("asks", [])
        if symbol not in self._market:
            self._market[symbol] = MarketSnapshot()

        snap = self._market[symbol]
        snap.last_price = _as_float(payload.get("last_price"))
        snap.best_bid = _as_float(bids[0].get("price")) if bids else None
        snap.best_ask = _as_float(asks[0].get("price")) if asks else None
        self._last_market_update[symbol] = time.monotonic()

    def _on_trade(self, payload: dict[str, Any]) -> None:
        symbol = str(payload.get("symbol", "")).upper()
        if not symbol:
            return
        if symbol not in self._market:
            self._market[symbol] = MarketSnapshot()
        self._market[symbol].last_price = _as_float(payload.get("price"))
        self._last_market_update[symbol] = time.monotonic()

    def _trim_reject_times(self, now: float) -> None:
        threshold = now - self._reject_window_sec
        while self._reject_times and self._reject_times[0] < threshold:
            self._reject_times.popleft()

    def _on_reject(self) -> None:
        now = time.monotonic()
        self._reject_times.append(now)
        self._trim_reject_times(now)
        if len(self._reject_times) >= self._max_rejects:
            self._risk_pause_until = now + self._reject_cooldown_sec
            self._reject_times.clear()
            self._log(
                "reject breaker tripped; pausing submissions "
                f"for {self._reject_cooldown_sec:.1f}s"
            )

    def _update_position_from_fill(self, payload: dict[str, Any]) -> None:
        symbol = str(payload.get("symbol", "")).upper()
        side = str(payload.get("side", "")).upper()
        fill_qty_raw = payload.get("fill_qty")
        if not symbol or side not in {"BUY", "SELL"}:
            return
        if fill_qty_raw is None:
            return
        try:
            fill_qty = int(fill_qty_raw)
        except (TypeError, ValueError):
            return
        if fill_qty <= 0:
            return
        pos = self._positions.get(symbol, 0)
        if side == "BUY":
            pos += fill_qty
        else:
            pos -= fill_qty
        self._positions[symbol] = pos

    def _handle_event(self, topic: str, payload: dict[str, Any]) -> None:
        if topic.startswith("book."):
            self._on_book(topic.split(".", 1)[1].upper(), payload)
            return

        if topic == "trade.executed":
            self._on_trade(payload)
            return

        if topic == f"system.symbols.{self.gateway_id}":
            raw = payload.get("symbols", [])
            all_syms = [str(sym).upper() for sym in raw if str(sym).strip()]
            if self._symbols_filter:
                allowed = set(self._symbols_filter)
                self._known_symbols = [sym for sym in all_syms if sym in allowed]
            else:
                self._known_symbols = all_syms
            return

        if topic == f"order.ack.{self.gateway_id}":
            if payload.get("accepted", False):
                self.metrics.acknowledged += 1
            else:
                self.metrics.rejected += 1
                self._on_reject()
            return

        if topic == f"order.fill.{self.gateway_id}":
            self.metrics.filled += 1
            self._update_position_from_fill(payload)
            return

        if topic in {
            f"order.cancelled.{self.gateway_id}",
            f"order.expired.{self.gateway_id}",
        }:
            self.metrics.cancelled += 1

    def _active_symbols(self) -> list[str]:
        if self._known_symbols:
            return self._known_symbols
        if self._symbols_filter:
            return self._symbols_filter
        return sorted(self._market)

    def _pick_symbol(self) -> str | None:
        universe = self._active_symbols()
        if not universe:
            return None
        return self._rng.choice(universe)

    def _make_order_payload(self, symbol: str) -> dict[str, Any] | None:
        now = time.monotonic()
        last_update = self._last_market_update.get(symbol)
        if (
            self._stale_data_sec > 0
            and last_update is not None
            and (now - last_update) > self._stale_data_sec
        ):
            return None

        snap = self._market.get(symbol, MarketSnapshot())
        pos = self._positions.get(symbol, 0)
        if pos >= self._max_position:
            side = "SELL"
        elif pos <= -self._max_position:
            side = "BUY"
        else:
            side = "BUY" if self._rng.random() < 0.5 else "SELL"

        qty = self.profile.sample_qty(self._rng)

        if side == "BUY":
            allowed = self._max_position - pos
        else:
            allowed = self._max_position + pos
        if allowed <= 0:
            return None
        qty = min(qty, allowed)
        if qty <= 0:
            return None

        # Build a limit price around top-of-book and personality aggression.
        # If no market data exists yet, avoid blind orders.
        if side == "BUY":
            ref = snap.best_bid if snap.best_bid is not None else snap.last_price
            if ref is None:
                return None
            if (
                snap.best_ask is not None
                and self._rng.random() < self.profile.cross_probability
            ):
                price = snap.best_ask
            else:
                price = max(
                    0.01,
                    ref - self.profile.passive_offset_ticks * self.profile.tick_size,
                )
        else:
            ref = snap.best_ask if snap.best_ask is not None else snap.last_price
            if ref is None:
                return None
            if (
                snap.best_bid is not None
                and self._rng.random() < self.profile.cross_probability
            ):
                price = snap.best_bid
            else:
                price = ref + self.profile.passive_offset_ticks * self.profile.tick_size

        return {
            "symbol": symbol,
            "side": side,
            "order_type": "LIMIT",
            "quantity": qty,
            "price": round(price, 4),
            "tif": "DAY",
            "gateway_id": self.gateway_id,
            "run_id": self._run_id,
            "strategy": self.profile.name,
        }

    def _maybe_submit_order(self) -> None:
        now = time.monotonic()
        self._trim_reject_times(now)

        if now < self._risk_pause_until:
            return

        interval = self.profile.decision_interval_ms / 1000.0
        if now - self._last_submit_ts < interval:
            return

        symbol = self._pick_symbol()
        if symbol is None:
            return

        payload = self._make_order_payload(symbol)
        if payload is None:
            return

        self.push_sock.send_multipart(make_order_new_msg(payload))
        self.metrics.submitted += 1
        self._last_submit_ts = now

    def run(self, duration_sec: float) -> int:
        if not self._authenticate():
            return 1

        self._request_symbols()

        poller = zmq.Poller()
        poller.register(self.sub_sock, zmq.POLLIN)

        started = time.monotonic()
        next_symbols_refresh = started + 2.0
        while self._running:
            if duration_sec > 0 and (time.monotonic() - started) >= duration_sec:
                self._running = False
                break

            socks = dict(poller.poll(timeout=100))
            if self.sub_sock in socks:
                topic, payload = decode(self.sub_sock.recv_multipart())
                self._handle_event(topic, payload)

            if time.monotonic() >= next_symbols_refresh and not self._known_symbols:
                self._request_symbols()
                next_symbols_refresh = time.monotonic() + 2.0

            self._maybe_submit_order()

        self._log(
            "stopped "
            f"submitted={self.metrics.submitted} "
            f"acked={self.metrics.acknowledged} "
            f"rejected={self.metrics.rejected} "
            f"fills={self.metrics.filled}"
        )
        self.push_sock.close()
        self.sub_sock.close()
        return 0


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EduMatcher autonomous AI trader")
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-ai-trader")
    parser.add_argument("--id", required=True, help="Gateway ID, e.g. AI01")
    parser.add_argument(
        "--profile",
        default="cautious",
        choices=available_profiles(),
        help="Personality profile",
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="Optional comma-separated symbol allowlist, e.g. AAPL,MSFT",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=1,
        help="Random seed for deterministic behavior",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Run duration in seconds; 0 means run until stopped",
    )
    parser.add_argument(
        "--run-id",
        default="",
        help="Optional run identifier, autogenerated if omitted",
    )
    parser.add_argument(
        "--max-position",
        type=int,
        default=1000,
        help="Absolute position limit per symbol",
    )
    parser.add_argument(
        "--max-rejects",
        type=int,
        default=25,
        help="Reject count threshold for breaker",
    )
    parser.add_argument(
        "--reject-window",
        type=float,
        default=10.0,
        help="Rolling window in seconds for reject threshold",
    )
    parser.add_argument(
        "--reject-cooldown",
        type=float,
        default=5.0,
        help="Pause duration in seconds after reject breaker trips",
    )
    parser.add_argument(
        "--stale-data",
        type=float,
        default=4.0,
        help="Max age in seconds for market data before pausing submissions",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    run_id = args.run_id or f"botrun-{uuid.uuid4().hex[:12]}"

    try:
        bot = AITraderBot(
            gateway_id=str(args.id),
            profile_name=str(args.profile),
            symbols=symbols,
            seed=int(args.seed),
            run_id=run_id,
            max_position=int(args.max_position),
            max_rejects=int(args.max_rejects),
            reject_window_sec=float(args.reject_window),
            reject_cooldown_sec=float(args.reject_cooldown),
            stale_data_sec=float(args.stale_data),
        )
        rc = bot.run(duration_sec=float(args.duration))
        raise SystemExit(rc)
    except KeyboardInterrupt:
        print("\n[AI] interrupted")
        raise SystemExit(0)
    except Exception as exc:
        print(f"[AI] FATAL: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

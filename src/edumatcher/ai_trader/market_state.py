"""What a worker knows about the market, shared read-only by its agents.

Fed from the engine PUB feed (book, depth, trades, session, auction
indicative, circuit breakers) and the reference-data replies. Prices on the
wire are display money; everything an agent acts on is integer ticks.

Signals are time-decayed EMAs over irregular observations, so one quiet
symbol and one busy symbol are measured on the same clock:

* ``ema_fast`` / ``ema_slow`` of log price (time constants ``TAU_FAST`` /
  ``TAU_SLOW`` seconds),
* ``var_rate`` -- EMA of squared log return per second, so
  ``sqrt(var_rate)`` is a per-sqrt-second volatility,
* ``flow`` -- EMA of signed aggressor volume share (+1 all buys, -1 all sells).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

TAU_FAST = 30.0
TAU_SLOW = 300.0
TAU_FLOW = 60.0
#: Observations and seconds of history before signals leave zero.
WARMUP_OBSERVATIONS = 20
WARMUP_SECONDS = TAU_FAST
#: Return-per-second variance is measured over at least this interval, so
#: two snapshots a millisecond apart cannot produce an absurd rate.
MIN_RETURN_DT = 0.25


def _alpha(dt: float, tau: float) -> float:
    return 1.0 - math.exp(-max(dt, 0.0) / tau)


def _clip(x: float) -> float:
    return -1.0 if x < -1.0 else 1.0 if x > 1.0 else x


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) and out > 0 else None


def _signed(value: Any, default: float) -> float:
    """A finite float of any sign (``_as_float`` is for prices: positive only)."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


@dataclass
class SymbolState:
    symbol: str
    tick_decimals: int = 2
    best_bid: int | None = None  # ticks
    best_ask: int | None = None
    bid_qty: int = 0
    ask_qty: int = 0
    last_trade: int | None = None
    prev_close: int | None = None
    #: Static collar reference: prev_close, else the first price seen. The
    #: engine's own reference is not on the wire; this is the best estimate.
    static_ref: int | None = None
    microprice: int | None = None
    imbalance: float = 0.0
    indicative_price: int | None = None
    indicative_side: str | None = None
    indicative_qty: int = 0
    halted: bool = False
    collar_static_pct: float | None = None
    collar_dynamic_pct: float | None = None
    max_order_qty: int | None = None
    max_order_value: float | None = None
    updated_at: float | None = None  # monotonic, last book/trade/depth
    #: pm-market-sim's true value, in (fractional) ticks; None without the sim.
    true_value: float | None = None
    # signals
    ema_fast: float | None = None
    ema_slow: float | None = None
    var_rate: float = 0.0
    flow: float = 0.0
    observations: int = 0
    first_obs_at: float | None = None
    _last_lp: float | None = field(default=None, repr=False)
    _last_obs_at: float | None = field(default=None, repr=False)
    _last_flow_at: float | None = field(default=None, repr=False)

    # --- units -----------------------------------------------------------
    @property
    def scale(self) -> int:
        return int(10**self.tick_decimals)

    def ticks(self, display_price: float) -> int:
        return int(round(display_price * self.scale))

    def display(self, ticks: int) -> float:
        return ticks / self.scale

    # --- derived prices ----------------------------------------------------
    @property
    def mid(self) -> int | None:
        if self.best_bid is not None and self.best_ask is not None:
            return (self.best_bid + self.best_ask) // 2
        return None

    def reference(self, *, auction: bool = False) -> int | None:
        """Best available estimate of where the symbol trades, in ticks."""
        if auction and self.indicative_price is not None:
            return self.indicative_price
        for candidate in (self.mid, self.last_trade, self.best_bid, self.best_ask):
            if candidate is not None:
                return candidate
        if self.indicative_price is not None:
            return self.indicative_price
        return self.prev_close

    def collar_band(self, margin: float = 0.9) -> tuple[int, int] | None:
        """Prices the engine's collar will accept, shrunk by ``margin``.

        None when no collar is configured for the symbol.
        """
        lo, hi = 1, None
        if self.collar_static_pct is None and self.collar_dynamic_pct is None:
            return None
        if self.collar_static_pct is not None and self.static_ref is not None:
            band = self.collar_static_pct * margin
            lo = max(lo, math.ceil(self.static_ref * (1 - band)))
            hi = math.floor(self.static_ref * (1 + band))
        if self.collar_dynamic_pct is not None and self.last_trade is not None:
            band = self.collar_dynamic_pct * margin
            lo = max(lo, math.ceil(self.last_trade * (1 - band)))
            dyn_hi = math.floor(self.last_trade * (1 + band))
            hi = dyn_hi if hi is None else min(hi, dyn_hi)
        if hi is None:
            return None
        return (lo, hi) if lo <= hi else None

    # --- signals -----------------------------------------------------------
    @property
    def warmed_up(self) -> bool:
        return (
            self.observations >= WARMUP_OBSERVATIONS
            and self.first_obs_at is not None
            and self._last_obs_at is not None
            and self._last_obs_at - self.first_obs_at >= WARMUP_SECONDS
        )

    def _sigma_scale(self) -> float:
        """Typical log-price excursion over ``TAU_SLOW`` (floored at a tick)."""
        sigma = math.sqrt(self.var_rate)
        price = math.exp(self._last_lp) if self._last_lp is not None else 1.0
        tick_floor = (1.0 / price) / math.sqrt(60.0)  # one tick a minute
        return 2.0 * max(sigma, tick_floor) * math.sqrt(TAU_SLOW)

    def momentum_score(self) -> float:
        """+1 strongly rising, -1 strongly falling, 0 neutral or warming up."""
        if not self.warmed_up or self.ema_fast is None or self.ema_slow is None:
            return 0.0
        return _clip((self.ema_fast - self.ema_slow) / self._sigma_scale())

    def reversion_score(self) -> float:
        """+1 far below its slow average (expect a rise), -1 far above."""
        if not self.warmed_up or self.ema_slow is None or self._last_lp is None:
            return 0.0
        return _clip(-(self._last_lp - self.ema_slow) / self._sigma_scale())

    def observe(self, price_ticks: int, now: float) -> None:
        if price_ticks <= 0:
            return
        lp = math.log(price_ticks)
        if self._last_lp is None or self._last_obs_at is None:
            self.ema_fast = self.ema_slow = lp
            self.first_obs_at = now
        else:
            dt = now - self._last_obs_at
            r = lp - self._last_lp
            assert self.ema_fast is not None and self.ema_slow is not None
            self.ema_fast += _alpha(dt, TAU_FAST) * (lp - self.ema_fast)
            self.ema_slow += _alpha(dt, TAU_SLOW) * (lp - self.ema_slow)
            rate = r * r / max(dt, MIN_RETURN_DT)
            self.var_rate += _alpha(max(dt, MIN_RETURN_DT), TAU_SLOW) * (
                rate - self.var_rate
            )
        self._last_lp = lp
        self._last_obs_at = now
        self.observations += 1
        if self.static_ref is None:
            self.static_ref = price_ticks

    def observe_flow(self, aggressor: str, now: float) -> None:
        sign = 1.0 if aggressor == "BUY" else -1.0 if aggressor == "SELL" else 0.0
        if self._last_flow_at is None:
            self.flow = sign
        else:
            self.flow += _alpha(now - self._last_flow_at, TAU_FLOW) * (sign - self.flow)
        self._last_flow_at = now


#: How long a piece of news stays in mind (seconds).
NEWS_MEMORY_SEC = 1800.0


@dataclass
class NewsItem:
    """One piece of news as the market heard it."""

    news_id: str
    #: None: every symbol (market news)
    symbols: frozenset[str] | None
    sentiment: float
    #: credibility for a rumour, 1 for news that is known to be true
    weight: float
    rumour: bool
    seen_at: float  # monotonic

    def touches(self, symbol: str) -> bool:
        return self.symbols is None or symbol in self.symbols


class MarketState:
    def __init__(self) -> None:
        self.symbols: dict[str, SymbolState] = {}
        #: sector name -> its symbols (from the deployed market_sim.yaml)
        self.sectors: dict[str, frozenset[str]] = {}
        self.news: dict[str, NewsItem] = {}
        self.session: str | None = None
        self.sessions_enabled = True
        self.next_state: str | None = None
        self.next_at: float | None = None  # wall seconds
        self.phase_since: float | None = None  # wall seconds

    def get(self, symbol: str) -> SymbolState:
        state = self.symbols.get(symbol)
        if state is None:
            state = self.symbols[symbol] = SymbolState(symbol)
        return state

    # --- session -------------------------------------------------------------
    def can_trade(self) -> bool:
        if not self.sessions_enabled:
            return True
        return self.session is not None and self.session != "CLOSED"

    @property
    def phase(self) -> str:
        """The effective phase: CONTINUOUS whenever sessions are disabled."""
        if not self.sessions_enabled:
            return "CONTINUOUS"
        return self.session or "CLOSED"

    def on_session_state(self, payload: dict[str, Any], wall: float) -> bool:
        """Apply ``session.state``; True when the phase changed."""
        state = str(payload.get("state") or "").upper()
        if not state:
            return False
        changed = state != self.session
        self.session = state
        if changed:
            self.phase_since = wall
        nxt = payload.get("next")
        self.next_state, self.next_at = None, None
        if isinstance(nxt, dict):
            self.next_state = str(nxt.get("state") or "").upper() or None
            self.next_at = _parse_iso(nxt.get("at"))
        return changed

    def on_session_status(self, payload: dict[str, Any], wall: float) -> bool:
        self.sessions_enabled = bool(payload.get("sessions_enabled", True))
        return self.on_session_state({"state": payload.get("state")}, wall)

    # --- reference data -------------------------------------------------------
    def on_symbols(self, payload: dict[str, Any]) -> list[str]:
        out: list[str] = []
        for entry in payload.get("symbols", []):
            if not isinstance(entry, dict):
                continue
            sym = str(entry.get("symbol", "")).strip().upper()
            if not sym:
                continue
            st = self.get(sym)
            decimals = entry.get("tick_decimals")
            if isinstance(decimals, int):
                st.tick_decimals = decimals
            prev = _as_float(entry.get("prev_close"))
            if prev is not None:
                st.prev_close = st.ticks(prev)
                st.static_ref = st.prev_close
            out.append(sym)
        return out

    def on_reference(self, payload: dict[str, Any]) -> None:
        for entry in payload.get("symbols", []):
            if not isinstance(entry, dict):
                continue
            sym = str(entry.get("symbol", "")).strip().upper()
            if not sym:
                continue
            st = self.get(sym)
            collar = entry.get("collar")
            if isinstance(collar, dict):
                st.collar_static_pct = _as_float(collar.get("static_band_pct"))
                st.collar_dynamic_pct = _as_float(collar.get("dynamic_band_pct"))
            limits = entry.get("order_limits")
            if isinstance(limits, dict):
                q = limits.get("max_order_qty")
                st.max_order_qty = int(q) if isinstance(q, int) and q > 0 else None
                st.max_order_value = _as_float(limits.get("max_order_value"))

    def on_sim_value(self, payload: dict[str, Any]) -> None:
        """pm-market-sim's true values, for the symbols this market knows."""
        for entry in payload.get("values", []):
            if not isinstance(entry, dict):
                continue
            st = self.symbols.get(str(entry.get("symbol", "")).upper())
            value = _as_float(entry.get("value"))
            if st is not None and value is not None and value > 0:
                st.true_value = value * st.scale

    def on_news(self, payload: dict[str, Any], now: float) -> NewsItem | None:
        """Take in one ``news.event``; returns the item it created, if any.

        A confirmation replaces its rumour with news known to be true; a
        retraction removes the rumour and leaves an impulse the other way,
        as large as the rumour was believable.
        """
        self.news = {
            k: n for k, n in self.news.items() if now - n.seen_at < NEWS_MEMORY_SEC
        }
        news_id = str(payload.get("id", ""))
        status = str(payload.get("status", ""))
        related = self.news.pop(str(payload.get("related_id") or ""), None)
        sentiment = _signed(payload.get("sentiment"), 0.0)
        scope = str(payload.get("scope", ""))
        targets = [str(t).upper() for t in payload.get("targets") or []]
        if scope == "MARKET":
            symbols: frozenset[str] | None = None
        elif scope == "SECTOR":
            symbols = frozenset(s for t in targets for s in self.sectors.get(t, ()))
        else:
            symbols = frozenset(targets)
        if status == "RETRACTED":
            if related is None:
                return None
            item = NewsItem(
                news_id, symbols, -related.sentiment, related.weight, False, now
            )
        elif status == "RUMOUR":
            cred = min(1.0, max(0.0, _signed(payload.get("credibility"), 0.5)))
            item = NewsItem(news_id, symbols, sentiment, cred, True, now)
        else:
            item = NewsItem(news_id, symbols, sentiment, 1.0, False, now)
        self.news[news_id] = item
        return item

    def rumour_tilt(self, symbol: str) -> float:
        """Credibility-weighted sentiment of the open rumours about ``symbol``."""
        return sum(
            n.sentiment * n.weight
            for n in self.news.values()
            if n.rumour and n.touches(symbol)
        )

    def on_halt_status(self, payload: dict[str, Any]) -> None:
        for entry in payload.get("halted", []):
            if isinstance(entry, dict) and entry.get("symbol"):
                self.get(str(entry["symbol"]).upper()).halted = True

    # --- market data ------------------------------------------------------------
    def on_book(self, symbol: str, payload: dict[str, Any], now: float) -> None:
        st = self.get(symbol)
        decimals = payload.get("tick_decimals")
        if isinstance(decimals, int):
            st.tick_decimals = decimals
        bids = payload.get("bids") or []
        asks = payload.get("asks") or []
        bid = _as_float(bids[0].get("price")) if bids else None
        ask = _as_float(asks[0].get("price")) if asks else None
        st.best_bid = st.ticks(bid) if bid is not None else None
        st.best_ask = st.ticks(ask) if ask is not None else None
        st.bid_qty = int(bids[0].get("qty") or 0) if bids else 0
        st.ask_qty = int(asks[0].get("qty") or 0) if asks else 0
        last = _as_float(payload.get("last_price"))
        if last is not None:
            st.last_trade = st.ticks(last)
        st.updated_at = now
        ref = st.mid if st.mid is not None else st.last_trade
        if ref is not None:
            st.observe(ref, now)

    def on_depth(self, symbol: str, payload: dict[str, Any], now: float) -> None:
        st = self.get(symbol)
        micro = _as_float(payload.get("microprice"))
        if micro is not None:
            st.microprice = st.ticks(micro)
        try:
            st.imbalance = _clip(float(payload.get("imbalance") or 0.0))
        except (TypeError, ValueError):
            st.imbalance = 0.0
        st.updated_at = now

    def on_trade(self, payload: dict[str, Any], now: float) -> None:
        sym = str(payload.get("symbol", "")).upper()
        price = _as_float(payload.get("price"))
        if not sym or price is None:
            return
        st = self.get(sym)
        st.last_trade = st.ticks(price)
        st.updated_at = now
        st.observe(st.last_trade, now)
        st.observe_flow(str(payload.get("aggressor_side") or "").upper(), now)

    def on_indicative(self, symbol: str, payload: dict[str, Any]) -> None:
        st = self.get(symbol)
        eq = _as_float(payload.get("eq_price"))
        st.indicative_price = st.ticks(eq) if eq is not None else None
        side = payload.get("imbalance_side")
        st.indicative_side = str(side).upper() if side else None
        st.indicative_qty = int(payload.get("imbalance_qty") or 0)

    def on_halt(self, symbol: str, halted: bool) -> None:
        self.get(symbol).halted = halted

    def clear_indicatives(self) -> None:
        for st in self.symbols.values():
            st.indicative_price = None
            st.indicative_side = None
            st.indicative_qty = 0


def _parse_iso(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None

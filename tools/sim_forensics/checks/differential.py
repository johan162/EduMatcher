"""E5-E7 — the run's commands re-run under changes that must make no difference.

E2 re-runs the audit's commands through one fresh engine and compares it
with the live engine. These checks run that re-run (the *reference*) again
and, beside it in lockstep, engines that see the same run with one thing
changed the matching rules say does not matter. Each command's outputs are
compared with the reference's, symbol by symbol; a symbol's first
difference is reported and the symbol is then left alone (one difference
makes every later one likely).

- **E5, symbol isolation.** One engine per symbol, configured with that
  symbol alone and fed only its commands -- plus every command that names
  no symbol (sessions, gateway connects, kill switches), which goes to all.
  A difference is state shared between symbols. The engine-wide rule that
  an order id is unique (``DUPLICATE_ORDER``) is the one legitimate
  exception; combos span symbols and leave theirs out.
- **E6, crash recovery.** Every ``_E6_EVERY`` commands the reference
  checkpoints through its own persistence (``Engine._flush_persistence``)
  and a fresh engine restores from those files, as a restarted one does.
  The restarted engine is given what a restart gets from outside, not from
  the files: the session phase (the scheduler) and the connected gateways
  (which reconnect). Its books are compared with the reference's at once
  -- priority order, quantities, armed stops and their triggers, OCO,
  quote and combo links -- and its outputs for the next ``_E6_SPAN``
  commands.
- **E7, metamorphic.** (a) Gateways swapped within groups of identical
  configuration, and every order id renamed; (b) every price of every
  symbol shifted up by ``_E7_SHIFT`` ticks. Collars and circuit breakers
  are percentages of a price, rounded down, so no shift leaves them as
  they were: the shifted engine applies them in the original prices (its
  collars and breakers see every price un-shifted), and the check shows
  that everything else -- matching, auctions, stops, notionals -- does not
  depend on the price level. Not run where order limits (a notional cap)
  are configured. Outputs are mapped back before the comparison.

Together these cost several E2 re-runs, so they are *slow* checks.
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import hashlib
import json
import random
import tempfile
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any
from unittest import mock

from sim_forensics.audit import audit_files, run_config_text
from sim_forensics.checks.rerun import (
    _ID_PREFIX,
    _ORDER_ID,
    _compare,
    _Ids,
    _Sink,
    apply,
    fresh_engine,
    inputs,
    live_clock,
)
from sim_forensics.dataset import Dataset
from sim_forensics.registry import Outcome, Sample, Skipped, check

import edumatcher.engine.main as engine_main
from edumatcher.config_artifact import decode as decode_artifact
from edumatcher.engine.circuit_breaker import CircuitBreakerState
from edumatcher.engine.collar import CollarConfig, CollarResult, validate_collar
from edumatcher.engine.config_loader import EngineConfig
from edumatcher.engine.order_book import _DEAD_STATUSES, OrderBook
from edumatcher.models.trade import reset_trade_ids_for_tests, set_run_seq

#: Commands between two E6 restarts, and how many each restarted engine runs.
_E6_EVERY = 100_000
_E6_SPAN = 20_000
_E7_SHIFT = 7
_KEEP = 50
#: Numbers a restarted engine assigns afresh (E6).
_RENUMBERED = frozenset({"priority_seq"})
#: Answers that depend on other symbols' orders: order ids are engine-wide.
_CROSS_SYMBOL_CODES = frozenset({"DUPLICATE_ORDER"})
#: Payload keys naming the order, quote or OCO a message is about.
_ID_KEYS = ("order_id", "id", "quote_id", "oco_id", "cancelled_order_id", "bid_order_id", "ask_order_id", "order_id_1")  # fmt: skip
#: Prices in ticks a client sends, and display prices the engine publishes.
_TICK_KEYS = frozenset({"price_ticks", "stop_price_ticks", "bid_price_ticks", "ask_price_ticks", "eq_price_ticks", "trigger_price_ticks", "last_price_ticks"})  # fmt: skip
#: Σ price_ticks × qty, and the quantity each shifts with.
_NOTIONAL_KEYS = {"fill_notional_ticks": "fill_qty", "cum_notional_ticks": "cum_qty"}
_PRICE_KEYS = frozenset({"price", "stop_price", "eq_price", "indicative_price", "last_price", "old_price", "trigger_price", "reference_price", "corridor_low", "corridor_high", "print_price"})  # fmt: skip
#: A display price that is a VWAP, off the tick grid.
_VWAP_KEYS = frozenset({"fill_price"})

Msgs = list[tuple[str, dict[str, Any]]]


class _Where:
    """Which symbol a command or message is about: its own ``symbol``, or
    the symbol learned for the order, quote or OCO it names."""

    def __init__(self) -> None:
        self.of: dict[str, str] = {}

    def learn(self, p: dict[str, Any]) -> None:
        sym = p.get("symbol")
        if sym:
            for key in _ID_KEYS:
                if p.get(key):
                    self.of[str(p[key])] = str(sym)

    def symbol(self, p: dict[str, Any]) -> str | None:
        if p.get("symbol"):
            return str(p["symbol"])
        for key in _ID_KEYS:
            sym = self.of.get(str(p.get(key)))
            if sym is not None:
                return sym
        return None

    def group(self, msgs: Msgs) -> dict[str | None, Msgs]:
        out: dict[str | None, Msgs] = defaultdict(list)
        for topic, p in msgs:
            self.learn(p)
            out[self.symbol(p)].append((topic, p))
        return out


@dataclass
class _Lane:
    """One engine compared with the reference."""

    engine: engine_main.Engine
    sink: _Sink
    ids: _Ids = field(default_factory=_Ids)
    #: Symbols (None: messages about none) that already differed.
    diverged: set[str | None] = field(default_factory=set)


class _Run:
    def __init__(self, ds: Dataset) -> None:
        self.ds = ds
        self.counts: Counter[str] = Counter()
        self.samples: dict[str, list[Sample]] = defaultdict(list)
        self.notes: dict[str, Counter[str]] = defaultdict(Counter)
        self.where = _Where()
        self.n = 0  # commands so far

    def flag(self, cid: str, **sample: object) -> None:
        self.counts[cid] += 1
        if len(self.samples[cid]) < _KEEP:
            self.samples[cid].append(sample)

    def compare(
        self,
        cid: str,
        lane: _Lane,
        mine: Msgs,
        ref: Msgs,
        only: set[str | None] | None,
        exact: bool = True,
        ignore: frozenset[str] = frozenset(),
        **context: object,
    ) -> None:
        """Compare *mine* with the reference's *ref* symbol by symbol (only
        the symbols in *only*, if given); floats to 9 decimals unless
        *exact*."""
        if not exact:
            mine = [(t, _rounded(p)) for t, p in mine]
            ref = [(t, _rounded(p)) for t, p in ref]
        if ignore:
            mine = [(t, {k: v for k, v in p.items() if k not in ignore}) for t, p in mine]  # fmt: skip
            ref = [(t, {k: v for k, v in p.items() if k not in ignore}) for t, p in ref]  # fmt: skip
        mg, rg = self.where.group(mine), self.where.group(ref)
        keys = only if only is not None else set(mg) | set(rg)
        for g in sorted(keys, key=str):
            if g in lane.diverged:
                continue
            diffs, _ = _compare(lane.ids, list(mg.get(g, [])), list(rg.get(g, [])))
            if not diffs:
                continue
            lane.diverged.add(g)
            if any(p.get("reject_code") in _CROSS_SYMBOL_CODES for _, p in rg.get(g, [])):  # fmt: skip
                self.notes[cid]["explained by an engine-wide rule"] += 1
                continue
            self.flag(cid, symbol=g, command_no=self.n, diffs=diffs[:4], **context)

    # --- the pass ------------------------------------------------------------

    def run(self) -> None:
        data = self.ds.data_dir
        files = audit_files(data)
        if not files:
            raise Skipped("no audit.log in the data dir")
        compiled = decode_artifact(run_config_text(files))
        self.config = config = compiled.engine
        reset_trade_ids_for_tests()
        set_run_seq(1)
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(
                engine_main, "validate_collar", _collar_in_original_prices
            ),
            live_clock(files) as clock,
        ):
            self.tmp = Path(tmp)
            empty = self.tmp / "empty"
            empty.mkdir()
            sink = _Sink()
            self.ref = _Lane(fresh_engine(config, sink, empty), sink)
            sink.take()
            self.e5 = _Isolation(self, empty)
            self.e6 = _Recovery(self)
            self.e7 = _Metamorphic(self, empty)
            for topic, chain, payload, live, ts in inputs(files):
                if topic is None or topic == "startup" or topic.startswith("book."):
                    continue
                clock.follow(live)
                self.n += 1
                self.where.learn(payload)
                apply(self.ref.engine, topic, payload)
                ref = self.ref.sink.take()
                self.e5.step(topic, payload, ref, chain)
                self.e6.step(ts, topic, payload, ref, chain)
                self.e7.step(topic, payload, ref, chain)


def _rounded(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _rounded(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_rounded(x) for x in v]
    return round(v, 9) if isinstance(v, float) else v


# --- E5 ----------------------------------------------------------------------


class _Isolation:
    def __init__(self, run: _Run, empty: Path) -> None:
        self.run, self.empty = run, empty
        self.lanes: dict[str, _Lane] = {}
        #: Commands that named no symbol, for engines started later.
        self.broadcast: list[tuple[str, dict[str, Any]]] = []
        #: Symbols a combo touched: not isolated.
        self.combined: set[str] = {
            leg.symbol for c in run.config.market_maker_combos for leg in c.legs
        }

    def lane(self, symbol: str) -> _Lane | None:
        if symbol in self.lanes:
            return self.lanes[symbol]
        cfg = self.run.config.symbols.get(symbol)
        if cfg is None:
            return None
        config = replace(self.run.config, symbols={symbol: cfg})
        sink = _Sink()
        lane = self.lanes[symbol] = _Lane(fresh_engine(config, sink, self.empty), sink)
        for topic, p in self.broadcast:
            apply(lane.engine, topic, p)
        sink.take()
        return lane

    def step(self, topic: str, p: dict[str, Any], ref: Msgs, chain: str) -> None:
        if topic.startswith("order.combo"):
            for leg in p.get("legs") or []:
                self.combined.add(str(leg.get("symbol")))
            return
        symbol = self.run.where.symbol(p)
        if symbol is None:
            self.broadcast.append((topic, p))
            for s, each in self.lanes.items():
                apply(each.engine, topic, p)
                if s not in self.combined:
                    self.run.compare("E5", each, each.sink.take(), ref, {s}, command=topic, chain=chain)  # fmt: skip
                else:
                    each.sink.take()
            return
        lane = self.lane(symbol)
        if lane is None or symbol in self.combined:
            return
        apply(lane.engine, topic, p)
        mine = lane.sink.take()
        others = set(self.run.where.group(ref)) - {symbol, None}
        if others and "E5-other" not in lane.diverged:
            lane.diverged.add("E5-other")
            self.run.flag("E5", symbol=symbol, command=topic, chain=chain, error="the command changed other symbols", others=sorted(str(o) for o in others)[:5])  # fmt: skip
        self.run.compare("E5", lane, mine, ref, {symbol, None}, command=topic, chain=chain)  # fmt: skip


# --- E6 ----------------------------------------------------------------------


def _book_state(b: OrderBook) -> dict[str, Any]:
    """A book as matching sees it: each side in priority order, armed stops
    in trigger order, trailing stops in the order they are checked."""

    def live(heap: list[Any]) -> list[tuple[Any, ...]]:
        entries = sorted(
            (e for e in heap if e.valid and e.order.status not in _DEAD_STATUSES),
            key=lambda e: e.key,
        )
        o = [e.order for e in entries]
        return [(x.id, x.price_ticks, x.stop_price_ticks, x.remaining_qty, x.displayed_qty) for x in o]  # fmt: skip

    return {
        "bids": live(b._bids),
        "asks": live(b._asks),
        "buy stops": live(b._buy_stops),
        "sell stops": live(b._sell_stops),
        "trailing stops": [
            (o.id, o.stop_price_ticks, o.trail_offset_ticks, o.remaining_qty)
            for o in b._trailing_stops
            if o.status not in _DEAD_STATUSES
        ],
        "last prices": (b.last_trade_price, b.last_buy_price, b.last_sell_price),
    }


def _engine_state(e: engine_main.Engine, skip: set[str]) -> dict[str, Any]:
    """Links between orders the engine keeps outside its books (quotes of
    the symbols in *skip* left out)."""
    return {
        "OCO groups": sorted((k, tuple(v)) for k, v in e._oco_groups.items()),
        "quotes": sorted(
            (k, v.bid_order_id, v.ask_order_id)
            for k, v in e._quote_index._index.items()
            if v.symbol not in skip
        ),
        "combo links": sorted(e._order_to_combo.items()),
    }


class _Recovery:
    def __init__(self, run: _Run) -> None:
        self.run = run
        self.lane: _Lane | None = None
        self.left = 0
        self.restarts = 0
        self.reseeded = 0
        #: Each gateway's last connect command, for the restarted engine.
        self.connects: dict[str, dict[str, Any]] = {}

    def step(self, ts: str, topic: str, p: dict[str, Any], ref: Msgs, chain: str) -> None:  # fmt: skip
        if topic == "system.gateway_connect":
            self.connects[str(p.get("gateway_id"))] = p
        if self.lane is not None:
            apply(self.lane.engine, topic, p)
            # A restart numbers each book's queue afresh: the order of the
            # queue is compared at the restart, not the numbers after it.
            self.run.compare("E6", self.lane, self.lane.sink.take(), ref, None, ignore=_RENUMBERED, restart=self.restarts, command=topic, chain=chain)  # fmt: skip
            self.left -= 1
            if self.left <= 0:
                self.lane = None
        if self.lane is None and self.run.n % _E6_EVERY == 0:
            self.restart(datetime.fromisoformat(ts).date())

    def restart(self, today: date) -> None:
        self.restarts += 1
        ref = self.run.ref.engine
        state = self.run.tmp / f"restart-{self.restarts}"
        state.mkdir()
        with _state_files(state):
            ref._flush_persistence(force=True)
        sink = _Sink()
        engine = fresh_engine(self.run.config, sink, state, today)
        # What a restart gets from outside: the phase, the gateways.
        engine._session_state = ref._session_state
        engine._next_session_state = ref._next_session_state
        # A restart seeds a market maker's quote again where it has none
        # live (seed_once, docs-design/EduMatcher-Revised-Quote-Persistence.md
        # §5.4): those books differ by design from here on.
        reseeded = {
            str(p["symbol"])
            for topic, p in sink.take()
            if topic.startswith("order.ack.") and p.get("is_seed")
        }
        self.reseeded += len(reseeded)
        for gw in sorted(ref._connected_fix_gateways):
            if gw in self.connects:
                engine._dispatch_pull_message("system.gateway_connect", self.connects[gw])  # fmt: skip
        sink.take()
        lane = _Lane(engine, sink, diverged=set[str | None](reseeded))
        # Engine-wide links first: one finding each, never cut by the sample cap.
        mine_e = _engine_state(engine, reseeded)
        theirs_e = _engine_state(ref, reseeded)
        for key in theirs_e:
            if mine_e[key] != theirs_e[key]:
                lost = sorted(set(theirs_e[key]) - set(mine_e[key]))
                self.run.flag("E6", restart=self.restarts, error=f"restored {key} differ", missing=len(lost), example=str(lost[:2])[:300])  # fmt: skip
        for symbol in sorted(set(ref.books) - reseeded):
            mine = _book_state(engine.books[symbol]) if symbol in engine.books else {}
            theirs = _book_state(ref.books[symbol])
            for key in theirs:
                if mine.get(key) != theirs[key]:
                    lane.diverged.add(symbol)
                    self.run.flag("E6", restart=self.restarts, symbol=symbol, error=f"restored {key} differ", reference=str(theirs[key])[:300], restored=str(mine.get(key))[:300])  # fmt: skip
                    break
        self.lane, self.left = lane, _E6_SPAN


def _state_files(state: Path) -> Any:
    """The engine's persistence files, pointed into *state*."""
    return mock.patch.multiple(
        engine_main,
        GTC_ORDERS_FILE=state / "gtc_orders.json",
        GTC_COMBOS_FILE=state / "gtc_combos.json",
        BOOK_STATS_FILE=state / "book_stats.json",
    )


# --- E7 ----------------------------------------------------------------------


class _Transform:
    """A change to the commands and its inverse on the outputs."""

    name = ""
    #: Outputs equal the reference's bit for bit (else floats to 9 decimals).
    exact = True

    def config(self, config: EngineConfig) -> EngineConfig:
        return config

    def command(self, topic: str, p: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        return topic, p

    def output(self, topic: str, p: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        return topic, p


class _Rename(_Transform):
    """Gateways swapped within groups of identical configuration; every
    order id renamed."""

    name = "rename"

    def __init__(self, config: EngineConfig) -> None:
        groups: dict[str, list[str]] = defaultdict(list)
        for gw, cfg in config.fix_gateways.items():
            fields = {k: v for k, v in asdict(cfg).items() if k not in ("id", "description")}  # fmt: skip
            groups[json.dumps(fields, sort_keys=True, default=str)].append(gw)
        rng = random.Random(7)
        self.gw: dict[str, str] = {}
        for members in groups.values():
            shuffled = sorted(members)
            rng.shuffle(shuffled)
            self.gw.update(zip(sorted(members), shuffled))
        self.gw_back = {v: k for k, v in self.gw.items()}
        self.ids_back: dict[str, str] = {}
        self.prefix_back: dict[str, str] = {}

    def _id(self, oid: str) -> str:
        new = hashlib.md5(b"E7" + oid.encode()).hexdigest()
        self.ids_back[new] = oid
        self.prefix_back[new[:8]] = oid[:8]
        return new

    def _map(self, v: Any, forward: bool) -> Any:
        if isinstance(v, dict):
            return {k: self._map(x, forward) for k, x in v.items()}
        if isinstance(v, list):
            return [self._map(x, forward) for x in v]
        if isinstance(v, str):
            gws = self.gw if forward else self.gw_back
            if v in gws:
                return gws[v]
            if _ORDER_ID.match(v):
                return self._id(v) if forward else self.ids_back.get(v, v)
            if not forward:
                return _ID_PREFIX.sub(lambda m: self.prefix_back.get(m.group(), m.group()), v)  # fmt: skip
        return v

    def _topic(self, topic: str, forward: bool) -> str:
        head, _, last = topic.rpartition(".")
        gws = self.gw if forward else self.gw_back
        return f"{head}.{gws[last]}" if head and last in gws else topic

    def command(self, topic: str, p: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        return self._topic(topic, True), self._map(p, True)

    def output(self, topic: str, p: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        return self._topic(topic, False), self._map(p, False)


_validate_collar = validate_collar
#: The breaker's prices, in ticks.
_BREAKER_PRICES = ("reference_price", "trigger_price", "corridor_reference")


@dataclass
class _ShiftedCollar(CollarConfig):
    """A collar the E7-shifted engine applies in the original prices."""

    e7_shift: int = 0


def _collar_in_original_prices(
    price: int, collar: CollarConfig, last: int | None
) -> CollarResult:
    k = collar.e7_shift if isinstance(collar, _ShiftedCollar) else 0
    return _validate_collar(price - k, collar, None if last is None else last - k)


class _ShiftedBreaker:
    """A circuit breaker running in the original prices behind a shifted
    engine: prices in are un-shifted, prices out shifted back."""

    def __init__(self, inner: CircuitBreakerState, k: int) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_k", k)

    def __getattr__(self, name: str) -> Any:
        v = getattr(self._inner, name)
        return v + self._k if name in _BREAKER_PRICES and v is not None else v

    def __setattr__(self, name: str, v: Any) -> None:
        if name in _BREAKER_PRICES and v is not None:
            v -= self._k
        setattr(self._inner, name, v)

    def seed_reference(self, price: int, now: int) -> None:
        self._inner.seed_reference(price - self._k, now)

    def record_trade(self, price: int, now: int) -> Any:
        return self._inner.record_trade(price - self._k, now)

    def within_corridor(self, price: int) -> bool:
        return bool(self._inner.within_corridor(price - self._k))

    def corridor(self) -> tuple[int, int] | None:
        bounds = self._inner.corridor()
        return None if bounds is None else (bounds[0] + self._k, bounds[1] + self._k)


class _Shift(_Transform):
    """Every price of every symbol up by ``_E7_SHIFT`` ticks."""

    name = "price shift"
    #: A fill's price is its trades' VWAP, off the tick grid: shifting it
    #: back is exact only up to float noise.
    exact = False

    def __init__(self, config: EngineConfig, where: _Where) -> None:
        self.where = where
        self.decimals = {s: c.tick_decimals for s, c in config.symbols.items()}

    @staticmethod
    def unsupported(config: EngineConfig) -> str:
        """Why a shift could change outcomes here ("" if it cannot)."""
        for s, c in config.symbols.items():
            if c.order_limits:
                return f"{s} has order limits"
        return ""

    def adopt(self, engine: engine_main.Engine) -> None:
        """Make the shifted engine apply its collars and circuit breakers in
        the original prices."""
        k = _E7_SHIFT
        for sym, collar in engine._collars.items():
            engine._collars[sym] = _ShiftedCollar(**{**vars(collar), "reference_price": collar.reference_price - k}, e7_shift=k)  # fmt: skip
        for sym, cb in engine._circuit_breakers.items():
            # Startup seeded each breaker from the shifted last prices.
            cb.trade_history = deque((t, p - k) for t, p in cb.trade_history)
            cb._trade_price_sum -= k * len(cb.trade_history)
            for name in _BREAKER_PRICES:
                if getattr(cb, name) is not None:
                    setattr(cb, name, getattr(cb, name) - k)
            engine._circuit_breakers[sym] = _ShiftedBreaker(cb, k)  # type: ignore[assignment]

    def config(self, config: EngineConfig) -> EngineConfig:
        k = _E7_SHIFT
        symbols = {}
        for s, c in config.symbols.items():
            scale = 10**c.tick_decimals
            symbols[s] = replace(
                c,
                # Its own: the engine writes the collar's reference into it.
                collar=replace(c.collar) if c.collar else None,
                market_maker_quotes=[
                    replace(q, bid_price_ticks=q.bid_price_ticks + k, ask_price_ticks=q.ask_price_ticks + k)  # fmt: skip
                    for q in c.market_maker_quotes
                ],
                last_buy_price=None if c.last_buy_price is None else (round(c.last_buy_price * scale) + k) / scale,  # fmt: skip
                last_sell_price=None if c.last_sell_price is None else (round(c.last_sell_price * scale) + k) / scale,  # fmt: skip
            )

        def leg(x: Any) -> Any:
            return replace(
                x,
                price_ticks=None if x.price_ticks is None else x.price_ticks + k,
                stop_price_ticks=None if x.stop_price_ticks is None else x.stop_price_ticks + k,  # fmt: skip
            )

        combos = [replace(c, legs=[leg(x) for x in c.legs]) for c in config.market_maker_combos]  # fmt: skip
        return replace(config, symbols=symbols, market_maker_combos=combos)

    def _shift(self, v: Any, by: int, scale: float) -> Any:
        if isinstance(v, dict):
            v = {
                k: x + by * int(v.get(_NOTIONAL_KEYS[k]) or 0) if k in _NOTIONAL_KEYS and isinstance(x, int) else x  # fmt: skip
                for k, x in v.items()
            }
            return {
                k: (
                    x + by
                    if k in _TICK_KEYS and isinstance(x, int)
                    else (
                        (round(x * scale) + by) / scale
                        if k in _PRICE_KEYS and isinstance(x, (int, float))
                        else (
                            x + by / scale
                            if k in _VWAP_KEYS and isinstance(x, (int, float))
                            else self._shift(x, by, scale)
                        )
                    )
                )
                for k, x in v.items()
            }
        if isinstance(v, list):
            return [self._shift(x, by, scale) for x in v]
        return v

    def _scale(self, p: dict[str, Any]) -> float:
        sym = self.where.symbol(p)
        return float(10 ** self.decimals.get(sym or "", 2))

    def command(self, topic: str, p: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        return topic, self._shift(p, _E7_SHIFT, self._scale(p))

    def output(self, topic: str, p: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        return topic, self._shift(p, -_E7_SHIFT, self._scale(p))


class _Metamorphic:
    def __init__(self, run: _Run, empty: Path) -> None:
        self.run = run
        transforms: list[_Transform] = [_Rename(run.config)]
        why = _Shift.unsupported(run.config)
        if why:
            run.notes["E7"][f"price shift not run: {why}"] += 1
        else:
            transforms.append(_Shift(run.config, run.where))
        self.lanes: list[tuple[_Transform, _Lane]] = []
        for t in transforms:
            sink = _Sink()
            self.lanes.append((t, _Lane(fresh_engine(t.config(run.config), sink, empty), sink)))  # fmt: skip
            if isinstance(t, _Shift):
                t.adopt(self.lanes[-1][1].engine)
            sink.take()

    def step(self, topic: str, p: dict[str, Any], ref: Msgs, chain: str) -> None:
        for t, lane in self.lanes:
            apply(lane.engine, *t.command(topic, p))
            mine = [t.output(tp, x) for tp, x in lane.sink.take()]
            self.run.compare("E7", lane, mine, ref, None, t.exact, transform=t.name, command=topic, chain=chain)  # fmt: skip


# --- checks ------------------------------------------------------------------


def _differentials(ds: Dataset) -> _Run:
    cached = ds.cache.get("differentials")
    if isinstance(cached, Skipped):
        raise cached
    if isinstance(cached, _Run):
        return cached
    r = _Run(ds)
    try:
        r.run()
    except Skipped as exc:
        ds.cache["differentials"] = exc
        raise
    ds.cache["differentials"] = r
    return r


def _outcome(r: _Run, cid: str, note: str) -> Outcome:
    note += "".join(f"; {k}: {n}" for k, n in r.notes[cid].items())
    return Outcome(r.counts[cid], r.samples[cid], note)


@check(
    "E5",
    "replay",
    "Each symbol re-run alone does what it did in the whole re-run",
    needs=(),
    slow=True,
)
def symbol_isolation(ds: Dataset) -> Outcome:
    r = _differentials(ds)
    note = f"{r.n} commands, {len(r.e5.lanes)} symbols"
    if r.e5.combined:
        note += f", {len(r.e5.combined)} left out (combos)"
    return _outcome(r, "E5", note)


@check(
    "E6",
    "replay",
    "An engine restored from a checkpoint continues as the uninterrupted re-run",
    needs=(),
    slow=True,
)
def crash_recovery(ds: Dataset) -> Outcome:
    r = _differentials(ds)
    note = (
        f"{r.e6.restarts} restarts, every {_E6_EVERY} commands, each compared for "
        f"{_E6_SPAN}; {r.e6.reseeded} books re-seeded at a restart (by design) not compared"  # fmt: skip
    )
    return _outcome(r, "E6", note)


@check(
    "E7",
    "replay",
    "Renamed gateways and ids, and shifted prices, change nothing but themselves",
    needs=(),
    slow=True,
)
def metamorphic(ds: Dataset) -> Outcome:
    r = _differentials(ds)
    names = ", ".join(t.name for t, _ in r.e7.lanes)
    return _outcome(r, "E7", f"{r.n} commands; transforms: {names}")

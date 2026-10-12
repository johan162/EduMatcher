"""A worker: one event loop hosting many agents.

The worker owns the market-data feed (engine PUB) and one MarketState that
all its agents read, and a transport that carries their orders. Each loop
it drains market data, drains order events into the agents, steps the
agents and sends what they ask for.

Startup: log every participant on, learn symbols / session / reference
data / halts, build the agents, seed their positions from the engine, ask
for a book snapshot of every symbol (the engine only publishes a book when
it changes, so a quiet symbol would otherwise never be priced).

Day cycle: a few seconds after the close (so the closing auction's fills,
which come over the order sessions, are in) every agent closes its day and
one JSON line per agent is appended to ``<DATA_DIR>/ai_swarm/<date>-<worker>.jsonl``.
An engine restart (its startup broadcast) re-reads all reference data; the
gateway drops the order sessions, which reconnect and re-read positions.
"""

from __future__ import annotations

import json
import logging
import selectors
import time
from dataclasses import dataclass
from typing import Any, cast

import zmq

from edumatcher.ai_trader.actions import Action, NewOco, NewOrder
from edumatcher.ai_trader.agent import Agent
from edumatcher.ai_trader.clock import Clock, WallClock
from edumatcher.ai_trader.market_state import MarketState
from edumatcher.ai_trader.preset import Preset
from edumatcher.ai_trader.transport import (
    AckEvent,
    AgentEvent,
    DoneEvent,
    FillEvent,
    OcoAckEvent,
    SessionEvent,
    Transport,
)
from datetime import UTC, datetime
from pathlib import Path

from edumatcher.config import (
    DATA_DIR,
    ENGINE_PUB_ADDR,
    ENGINE_PULL_ADDR,
    REF_DATA_DIR,
    SIM_PUB_ADDR,
)
from edumatcher.models.generated.news import TOPIC_NEWS_EVENT
from edumatcher.models.generated.sim import TOPIC_SIM_VALUE
from edumatcher.market_sim.config import FILE_NAME as SIM_FILE_NAME, load_sectors
from edumatcher.messaging.bus import get_context, make_pusher
from edumatcher.models.generated.auction import PREFIX_AUCTION_INDICATIVE
from edumatcher.models.generated.book import PREFIX_BOOK_SNAPSHOT, PREFIX_DEPTH
from edumatcher.models.generated.circuit_breaker import (
    PREFIX_CIRCUIT_BREAKER_HALT,
    PREFIX_CIRCUIT_BREAKER_RESUME,
)
from edumatcher.models.generated.session import TOPIC_SESSION_STATE
from edumatcher.models.generated.system import (
    TOPIC_STARTUP_RECOVERY,
    topic_halt_status,
    topic_reference,
    topic_session_status,
    topic_symbols,
)
from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED
from edumatcher.models.message import (
    decode,
    make_book_snapshot_request_msg,
    make_halt_status_request_msg,
    make_reference_request_msg,
    make_session_state_request_msg,
    make_symbols_request_msg,
)

log = logging.getLogger(__name__)

#: How often sessions are pinged (pm-alf-gwy drops a session idle for 30 s).
HEARTBEAT_INTERVAL = 5.0
#: A symbol with no market data for this long gets a snapshot request.
STALE_SECONDS = 10.0
STATUS_INTERVAL = 60.0
#: Shortest loop period. Agents are simulated people: a few milliseconds of
#: batching costs them nothing and caps the loop rate under heavy traffic.
MIN_LOOP_SEC = 0.005
#: How often sessions are kept alive / reconnected.
MAINTAIN_INTERVAL = 0.2
#: Rate-budget controller: window and per-adjustment bounds.
BUDGET_WINDOW = 20.0
BUDGET_MAX_STEP = 1.5
#: Seconds after CLOSED before the day is closed, so late closing-auction
#: fills (order sessions) catch up with the state change (market data).
SUMMARY_GRACE = 5.0
#: Seconds between reference-data requests while resyncing after an engine restart.
RESYNC_RETRY = 1.0


@dataclass(frozen=True)
class AgentSpec:
    gateway_id: str
    preset: Preset
    symbols: list[str]  # empty = every symbol
    seed: int


class Worker:
    def __init__(
        self,
        specs: list[AgentSpec],
        transport: Transport,
        *,
        clock: Clock | None = None,
        budget_orders_per_sec: float | None = None,
        pull_addr: str = ENGINE_PULL_ADDR,
        pub_addr: str = ENGINE_PUB_ADDR,
        sim_addr: str = SIM_PUB_ADDR,
        name: str = "worker",
        summary_dir: Path = DATA_DIR / "ai_swarm",
    ) -> None:
        self.specs = specs
        self.transport = transport
        self.clock = clock or WallClock()
        self.budget = budget_orders_per_sec
        self.name = name
        self.market = MarketState()
        self.agents: dict[str, Agent] = {}
        self._running = True
        self._push = make_pusher(pull_addr)
        self._md = get_context().socket(zmq.SUB)
        self._md.setsockopt(zmq.RCVHWM, 200_000)
        self._md.connect(pub_addr)
        # pm-market-sim's own PUB, for the value strategy; nothing arrives
        # when it is not running.
        self._md.connect(sim_addr)
        self._md.setsockopt(zmq.SUBSCRIBE, TOPIC_SIM_VALUE.encode())
        self._md.setsockopt(zmq.SUBSCRIBE, TOPIC_NEWS_EVENT.encode())
        self.market.sectors = load_sectors(REF_DATA_DIR / SIM_FILE_NAME)
        for topic in (
            PREFIX_BOOK_SNAPSHOT,
            PREFIX_DEPTH,
            TOPIC_TRADE_EXECUTED,
            TOPIC_SESSION_STATE,
            PREFIX_AUCTION_INDICATIVE,
            PREFIX_CIRCUIT_BREAKER_HALT,
            PREFIX_CIRCUIT_BREAKER_RESUME,
            TOPIC_STARTUP_RECOVERY,
        ):
            self._md.setsockopt(zmq.SUBSCRIBE, topic.encode())
        self._ref_gw = ""
        self._snapshot_requested: dict[str, float] = {}
        self._symbols_known = False
        self._session_known = False
        self._sent_window: list[tuple[float, int]] = []
        self.actions_sent = 0
        self.summary_dir = summary_dir
        self.days_closed = 0
        self._day_close_at: float | None = None
        #: After an engine restart: when to (re)ask for reference data, until
        #: the session status answers. The first asks can be lost while the
        #: bus reconnects.
        self._resync_at: float | None = None

    # --- control -------------------------------------------------------------
    def stop(self, *_args: object) -> None:
        self._running = False

    def _push_engine(self, frames: list[bytes]) -> bool:
        """Send a read request; the engine being away is not an error.

        The engine bus PUSH socket never blocks (SNDTIMEO 0, IMMEDIATE), so
        while the engine is down every send raises ``zmq.Again``.
        """
        try:
            self._push.send_multipart(frames)
        except zmq.Again:
            return False
        return True

    # --- startup -----------------------------------------------------------------
    def _request_reference(self) -> None:
        gw = self._ref_gw
        for frames in (
            make_symbols_request_msg(gw),
            make_session_state_request_msg(gw),
            make_reference_request_msg(gw),
            make_halt_status_request_msg(gw),
        ):
            self._push_engine(frames)

    def start(self, timeout: float = 15.0) -> bool:
        ids = [s.gateway_id for s in self.specs]
        accepted = self.transport.connect(ids, timeout=timeout)
        specs = [s for s in self.specs if s.gateway_id in accepted]
        if not specs:
            log.error("[%s] no participant could log on", self.name)
            return False
        self._ref_gw = specs[0].gateway_id
        for topic in (
            topic_symbols(self._ref_gw),
            topic_session_status(self._ref_gw),
            topic_reference(self._ref_gw),
            topic_halt_status(self._ref_gw),
        ):
            self._md.setsockopt(zmq.SUBSCRIBE, topic.encode())
        time.sleep(0.2)
        deadline = time.monotonic() + timeout
        next_ask = 0.0
        while not (self._symbols_known and self._session_known):
            if time.monotonic() >= deadline:
                log.error("[%s] no symbols/session reply from the engine", self.name)
                return False
            if time.monotonic() >= next_ask:
                self._request_reference()
                next_ask = time.monotonic() + 2.0
            self._drain_market(wait_ms=100)
        known = sorted(self.market.symbols)
        now = self.clock.monotonic()
        for spec in specs:
            universe = (
                [s for s in spec.symbols if s in self.market.symbols]
                if spec.symbols
                else known
            )
            if not universe:
                log.error(
                    "[%s] %s: none of its symbols exist", self.name, spec.gateway_id
                )
                continue
            self.agents[spec.gateway_id] = Agent(
                spec.gateway_id, spec.preset, universe, spec.seed, now
            )
            self.transport.request_positions(spec.gateway_id)
        for sym in sorted({s for a in self.agents.values() for s in a.universe}):
            self._request_snapshot(sym, now, force=True)
        self._apply_budget(now, initial=True)
        log.info(
            "[%s] %d agent(s) on %d symbol(s); session=%s",
            self.name,
            len(self.agents),
            len(known),
            self.market.phase,
        )
        return bool(self.agents)

    # --- market data -----------------------------------------------------------------
    def _request_snapshot(self, symbol: str, now: float, force: bool = False) -> None:
        last = self._snapshot_requested.get(symbol)
        if not force and last is not None and now - last < STALE_SECONDS:
            return
        self._snapshot_requested[symbol] = now
        self._push_engine(make_book_snapshot_request_msg(symbol))

    def _drain_market(self, wait_ms: int = 0, max_messages: int = 5000) -> int:
        if wait_ms and not self._md.poll(wait_ms):
            return 0
        n = 0
        while n < max_messages:
            try:
                frames = self._md.recv_multipart(zmq.NOBLOCK)
            except zmq.Again:
                break
            n += 1
            self.handle_market(*decode(frames))
        return n

    def handle_market(self, topic: str, payload: dict[str, Any]) -> None:
        now = self.clock.monotonic()
        m = self.market
        if topic.startswith(PREFIX_BOOK_SNAPSHOT):
            m.on_book(topic[len(PREFIX_BOOK_SNAPSHOT) :].upper(), payload, now)
        elif topic.startswith(PREFIX_DEPTH):
            m.on_depth(topic[len(PREFIX_DEPTH) :].upper(), payload, now)
        elif topic == TOPIC_TRADE_EXECUTED:
            m.on_trade(payload, now)
        elif topic == TOPIC_SIM_VALUE:
            m.on_sim_value(payload)
        elif topic == TOPIC_NEWS_EVENT:
            m.on_news(payload, now)
        elif topic.startswith(PREFIX_AUCTION_INDICATIVE):
            m.on_indicative(topic[len(PREFIX_AUCTION_INDICATIVE) :].upper(), payload)
        elif topic.startswith(PREFIX_CIRCUIT_BREAKER_HALT):
            m.on_halt(topic[len(PREFIX_CIRCUIT_BREAKER_HALT) :].upper(), True)
        elif topic.startswith(PREFIX_CIRCUIT_BREAKER_RESUME):
            m.on_halt(topic[len(PREFIX_CIRCUIT_BREAKER_RESUME) :].upper(), False)
        elif topic == TOPIC_SESSION_STATE:
            previous = m.session
            if m.on_session_state(payload, self.clock.wall()):
                self._on_phase_change(previous, m.session, now)
            self._session_known = True
        elif topic == topic_session_status(self._ref_gw):
            self._resync_at = None
            previous = m.session
            if m.on_session_status(payload, self.clock.wall()) and self._session_known:
                self._on_phase_change(previous, m.session, now)
            self._session_known = True
        elif topic == topic_symbols(self._ref_gw):
            m.on_symbols(payload)
            self._symbols_known = True
        elif topic == topic_reference(self._ref_gw):
            m.on_reference(payload)
        elif topic == topic_halt_status(self._ref_gw):
            m.on_halt_status(payload)
        elif topic == TOPIC_STARTUP_RECOVERY:
            log.warning("[%s] engine restarted; re-reading reference data", self.name)
            self._resync(now)

    def _on_phase_change(
        self, previous: str | None, current: str | None, now: float
    ) -> None:
        log.info("[%s] session %s -> %s", self.name, previous or "unknown", current)
        if previous in ("OPENING_AUCTION", "CLOSING_AUCTION"):
            self.market.clear_indicatives()
        if current == "CLOSED":
            for agent in self.agents.values():
                agent.on_session_closed()
            self._day_close_at = now + SUMMARY_GRACE
        if previous == "CLOSED" and current != "CLOSED":
            if self._day_close_at is not None:
                self.close_day()  # the next day starts before the grace ran out
            # A new day: books changed while closed (DAY orders expired).
            for sym in list(self.market.symbols):
                self._request_snapshot(sym, now, force=True)

    def _resync(self, now: float) -> None:
        self._request_reference()
        for sym in list(self.market.symbols):
            self._request_snapshot(sym, now, force=True)
        self._resync_at = now + RESYNC_RETRY

    def close_day(self) -> None:
        """Close every agent's day; one JSON line each, one INFO line in all."""
        self._day_close_at = None
        self.days_closed += 1
        closed_at = datetime.fromtimestamp(self.clock.wall(), UTC)
        rows = [agent.end_of_day(self.market) for agent in self.agents.values()]
        path = self.summary_dir / f"{closed_at:%Y-%m-%d}-{self.name}.jsonl"
        try:
            self.summary_dir.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                for row in rows:
                    line = {"closed_at": closed_at.isoformat(), "day": self.days_closed}
                    fh.write(json.dumps({**line, **row}) + "\n")
        except OSError as exc:
            log.error(
                "[%s] cannot write the daily summary %s: %s", self.name, path, exc
            )
        log.info(
            "[%s] day %d closed: %d agents, %d orders, %d fills, %d rejects, "
            "P&L %.2f",
            self.name,
            self.days_closed,
            len(rows),
            sum(r["submitted"] for r in rows),
            sum(r["fills"] for r in rows),
            sum(r["rejected"] for r in rows),
            sum(r["pnl_mtm"] for r in rows),
        )

    # --- order events -----------------------------------------------------------------
    def dispatch(self, gateway_id: str, event: AgentEvent) -> None:
        agent = self.agents.get(gateway_id)
        if agent is None:
            return
        now = self.clock.monotonic()
        if isinstance(event, AckEvent):
            agent.on_ack(
                now,
                order_id=event.order_id,
                tag=event.tag,
                accepted=event.accepted,
                code=event.code,
                reason=event.reason,
                request_tag=event.request_tag,
            )
        elif isinstance(event, FillEvent):
            st = self.market.get(event.symbol)
            agent.on_fill(
                order_id=event.order_id,
                tag=event.tag,
                symbol=event.symbol,
                side=event.side,
                fill_qty=event.fill_qty,
                fill_price_ticks=st.ticks(event.fill_price),
                remaining=event.remaining,
            )
        elif isinstance(event, DoneEvent):
            agent.on_done(order_id=event.order_id, tag=event.tag)
        elif isinstance(event, OcoAckEvent):
            agent.on_oco_ack(event.oco_tag, event.accepted, event.leg_ids, event.reason)
        elif isinstance(event, SessionEvent):
            if event.up:
                agent.on_reconnected()
                self.transport.request_positions(gateway_id)
                # The session may have been lost to an engine restart whose
                # startup broadcast this worker missed: re-read the market.
                if self._resync_at is None:
                    self._resync_at = now
        else:
            agent.on_positions(
                {
                    sym: (qty, float(self.market.get(sym).ticks(cost)) if cost else 0.0)
                    for sym, (qty, cost) in event.positions.items()
                }
            )

    # --- rate budget -------------------------------------------------------------------
    def _apply_budget(self, now: float, initial: bool = False) -> None:
        """Steer the agents' decision rates so actions/s meets the budget.

        Starts from the nominal tempo rates, then corrects multiplicatively
        from the measured action rate over the last ``BUDGET_WINDOW`` seconds
        (one decision makes between zero and a few actions, so the ratio has
        to be learned).
        """
        if self.budget is None or not self.agents:
            return
        if initial:
            nominal = sum(
                a.preset.tempo.decisions_per_min / 60.0 for a in self.agents.values()
            )
            scale = self.budget / nominal if nominal > 0 else 1.0
            for a in self.agents.values():
                a.rate_scale = scale
            return
        self._sent_window = [
            (t, n) for t, n in self._sent_window if t >= now - BUDGET_WINDOW
        ]
        if not self._sent_window or now - self._sent_window[0][0] < BUDGET_WINDOW / 2:
            return
        span = max(now - self._sent_window[0][0], 1.0)
        measured = sum(n for _, n in self._sent_window) / span
        if measured <= 0:
            return
        factor = min(
            BUDGET_MAX_STEP, max(1.0 / BUDGET_MAX_STEP, self.budget / measured)
        )
        factor = factor**0.5  # damped
        for a in self.agents.values():
            a.rate_scale *= factor

    # --- main loop -----------------------------------------------------------------------
    def _send(self, agent: Agent, actions: list[Action]) -> int:
        n = 0
        for action in actions:
            sym = action.symbol
            decimals = self.market.get(sym).tick_decimals
            if self.transport.send(agent.gateway_id, action, decimals):
                n += 1
            elif isinstance(action, (NewOrder, NewOco)):
                agent.on_done(order_id=None, tag=action.tag)  # never left
        return n

    def _sync_selector(
        self, sel: selectors.BaseSelector, known: dict[int, tuple[str, object]]
    ) -> None:
        """Register the transport's current session fds (they change on reconnect).

        Compared by connection, not fd number: a reconnect often gets the
        closed socket's number back, and epoll has already forgotten it.
        """
        current = self.transport.fileno_map()
        for fd in set(known) - set(current):
            try:
                sel.unregister(fd)
            except (KeyError, ValueError):
                pass
            del known[fd]
        for fd, (gw, conn) in current.items():
            old = known.get(fd)
            if old is not None and old[1] is conn:
                continue
            if old is not None:
                sel.unregister(fd)
            sel.register(fd, selectors.EVENT_READ, gw)
            known[fd] = (gw, conn)

    def run(self, duration: float = 0.0) -> None:
        start = self.clock.monotonic()
        next_heartbeat = start
        next_status = start + STATUS_INTERVAL
        next_budget = start + BUDGET_WINDOW / 2
        next_stale_sweep = start
        next_maintain = start
        # epoll/kqueue over the session sockets plus the market-data SUB's
        # notification fd (edge-triggered: drained fully, and zmq.EVENTS is
        # checked before waiting so nothing is left behind).
        sel = selectors.DefaultSelector()
        md_fd = cast(int, self._md.getsockopt(zmq.FD))
        sel.register(md_fd, selectors.EVENT_READ, None)
        session_fds: dict[int, tuple[str, object]] = {}
        self._sync_selector(sel, session_fds)
        try:
            while self._running:
                loop_start = self.clock.monotonic()
                if duration > 0 and loop_start - start >= duration:
                    break
                md_pending = bool(
                    cast(int, self._md.getsockopt(zmq.EVENTS)) & zmq.POLLIN
                )
                ready: list[str] = []
                for key, _mask in sel.select(0 if md_pending else 0.02):
                    if key.data is not None:
                        ready.append(key.data)
                self._drain_market()
                for gw, event in self.transport.poll_events(ready):
                    self.dispatch(gw, event)
                now = self.clock.monotonic()
                wall = self.clock.wall()
                sent = 0
                for agent in self.agents.values():
                    # Nothing to do while its session is down: decisions would
                    # only be orders that cannot leave.
                    if now < agent.next_due or not self.transport.is_up(
                        agent.gateway_id
                    ):
                        continue
                    actions = agent.step(now, wall, self.market)
                    if actions:
                        sent += self._send(agent, actions)
                if sent:
                    self.actions_sent += sent
                    self._sent_window.append((now, sent))
                if now >= next_maintain:
                    next_maintain = now + MAINTAIN_INTERVAL
                    for gw, event in self.transport.maintain(now):
                        self.dispatch(gw, event)
                    self._sync_selector(sel, session_fds)
                if now >= next_heartbeat:
                    self.transport.heartbeat(list(self.agents))
                    next_heartbeat = now + HEARTBEAT_INTERVAL
                if now >= next_stale_sweep:
                    next_stale_sweep = now + 1.0
                    for sym, st in self.market.symbols.items():
                        if st.updated_at is None or now - st.updated_at > STALE_SECONDS:
                            self._request_snapshot(sym, now)
                if now >= next_budget:
                    self._apply_budget(now)
                    next_budget = now + BUDGET_WINDOW / 2
                if self._resync_at is not None and now >= self._resync_at:
                    self._resync(now)
                if self._day_close_at is not None and now >= self._day_close_at:
                    self.close_day()
                if now >= next_status:
                    next_status = now + STATUS_INTERVAL
                    self._log_status(now - start)
                spent = self.clock.monotonic() - loop_start
                if spent < MIN_LOOP_SEC:
                    time.sleep(MIN_LOOP_SEC - spent)
        finally:
            sel.close()
            self.transport.disconnect(list(self.agents))
            for agent in self.agents.values():
                log.info("[%s] stopped %s", agent.gateway_id, agent.summary())

    def _log_status(self, elapsed: float) -> None:
        live = sum(len(a.orders.orders) for a in self.agents.values())
        rejects = sum(sum(a.stats.rejected.values()) for a in self.agents.values())
        fills = sum(a.orders.fills for a in self.agents.values())
        log.info(
            "[%s] t=%.0fs session=%s actions=%d (%.1f/s) live_orders=%d fills=%d rejects=%d",
            self.name,
            elapsed,
            self.market.phase,
            self.actions_sent,
            self.actions_sent / max(elapsed, 1.0),
            live,
            fills,
            rejects,
        )

    def close(self) -> None:
        self._push.close()
        self._md.close()
        self.transport.close()

"""Exchange activity from beacon metrics: the snapshot's trading, participant,
book and gateway blocks (design §8, §9.4, §11.1).

Fed one accepted beacon at a time (:meth:`Activity.observe`); counters become
increments through :class:`~edumatcher.monitor.rates.CounterTracker` and are
summed into the figures the dashboard shows, gauges are kept as last seen.

Gateways are mapped by **process name**, never by metric prefix (I37): the
ALF and BALF gateways export their ``_global_stats`` keys, RALF and drop-copy
use ``gwy.clients``/``gwy.slow_clients``, the MD gateway ``md.*``, the API
gateway ``api.*`` and pm-log-srv ``log.*``. :data:`GATEWAYS` says, per
process, which metric means what.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, tzinfo
from typing import Any

from edumatcher.engine.metrics import SESSION_STATE_ORDER
from edumatcher.models.generated.health import HealthBeacon
from edumatcher.monitor.rates import DAILY_COUNTERS, CounterTracker, Rate
from edumatcher.monitor.timefmt import iso_utc
from edumatcher.stats.trading_day import trading_date

ENGINE = "pm-engine"


@dataclass(frozen=True)
class GatewayMetrics:
    """Which metrics of one gateway process fill its ``GatewayStats``."""

    kind: str
    clients: str  # gauge, summed over labels
    traffic: str  # counter, summed over labels -> msgs_per_sec
    clients_max: str | None = None
    disconnects: str | None = None  # counter, summed over labels
    slow: str | None = None  # counter
    slow_label: str | None = None  # only this label of ``slow``; None = all


GATEWAYS: dict[str, GatewayMetrics] = {
    "pm-alf-gwy": GatewayMetrics(
        "ALF",
        clients="gwy.connected_clients",
        traffic="gwy.commands_received_total",
        clients_max="gwy.clients_max",
        disconnects="gwy.disconnects_total",
        slow="gwy.slow_client_disconnects",
    ),
    "pm-balf-gwy": GatewayMetrics(
        "BALF",
        clients="gwy.connected_clients",
        traffic="gwy.frames_received_total",
        clients_max="gwy.clients_max",
        disconnects="gwy.disconnects_total",
        slow="gwy.slow_client_disconnects",
    ),
    "pm-md-gwy": GatewayMetrics(
        "MD",
        clients="md.clients",
        traffic="md.msgs_out",
        clients_max="md.clients_max",
        disconnects="md.disconnects",
        slow="md.disconnects",
        slow_label="slow_client",
    ),
    "pm-ralf-gwy": GatewayMetrics(
        "RALF",
        clients="gwy.clients",
        traffic="gwy.msgs_out",
        disconnects="gwy.disconnects",
        slow="gwy.slow_clients",
    ),
    "pm-dc-gwy": GatewayMetrics(
        "DC",
        clients="gwy.clients",
        traffic="gwy.msgs_out",
        disconnects="gwy.disconnects",
        slow="gwy.slow_clients",
    ),
    "pm-api-gwy": GatewayMetrics(
        "API", clients="api.ws_sessions", traffic="api.http_requests"
    ),
    "pm-log-srv": GatewayMetrics(
        "LOG", clients="log.sessions", traffic="log.events_in"
    ),
}

#: Counters where any increase within 5 minutes is a WARN threshold (§9.6),
#: by metric name -> rule name. The gateways' slow-client counters join them
#: through :data:`GATEWAYS` as ``slow_client_disconnects``.
WATCHED_INCREASES = {
    "api.dropped_events": "api_dropped_events",
    "stats.feed_gaps": "stats_feed_gaps",
}
SLOW_RULE = "slow_client_disconnects"

#: Every inbound request that can be rejected. ``engine.rejects`` counts the
#: rejected acks of new orders, combos and OCOs (``orders_in``), cancels,
#: amends and quotes alike, so a ratio over ``orders_in`` alone reads over
#: 100 % for a market maker whose quote refreshes are refused (I67).
REQUEST_COUNTERS = frozenset(
    {"engine.orders_in", "engine.cancels_in", "engine.amends_in", "engine.quotes_in"}
)


@dataclass
class Participant:
    """One gateway id as the engine counts it."""

    orders: Rate = field(default_factory=Rate)
    requests: float = 0.0
    rejects: float = 0.0
    fills: float = 0.0
    connects: float = 0.0
    disconnects: float = 0.0
    heartbeat_timeouts: float = 0.0
    connected: bool | None = None  # None until the engine has reported it
    connected_since: str | None = None
    resting_orders: int = 0

    def new_day(self) -> None:
        self.orders.new_day()
        self.requests = self.rejects = self.fills = 0.0
        self.connects = self.disconnects = self.heartbeat_timeouts = 0.0


@dataclass
class Book:
    gauges: dict[str, float] = field(default_factory=dict)
    trades: float = 0.0


@dataclass
class Gateway:
    process: str
    gauges: dict[str, dict[str, float]] = field(
        default_factory=dict
    )  # name -> label -> v
    traffic: Rate = field(default_factory=Rate)
    disconnects: float = 0.0
    slow: Rate = field(default_factory=Rate)

    def gauge_sum(self, name: str | None) -> float | None:
        if name is None or name not in self.gauges:
            return None
        return sum(self.gauges[name].values())


class Activity:
    """Everything the engine and the gateways say about trading and clients."""

    def __init__(self, session_tz: tzinfo, roles: dict[str, str] | None = None) -> None:
        self.session_tz = session_tz
        #: Configured gateway id -> participant role (from the engine config).
        self.roles = dict(roles or {})
        self.tracker = CounterTracker()
        self.date = ""
        self.orders = Rate()
        self.trades = Rate()
        self.rejects = Rate()
        self.requests = Rate()
        self.traded_value = 0.0
        self.engine_gauges: dict[str, float] = {}
        self.session_state = ""
        #: Wall time the session opened today (first move out of CLOSED).
        self.session_opened_at: float | None = None
        self.participants: dict[str, Participant] = {
            gw: Participant() for gw in self.roles
        }
        self.books: dict[str, Book] = {}
        self.gateways: dict[str, Gateway] = {}  # by process key
        #: (rule, source key) -> increases of a watched counter (§9.6)
        self.increases: dict[tuple[str, str], Rate] = {}

    # ------------------------------------------------------------------
    # day
    # ------------------------------------------------------------------

    def roll_day(self, now_wall: float) -> bool:
        """Start a new "today" when the trading date changed; True if it did."""
        date = trading_date(now_wall, self.session_tz)
        if date == self.date:
            return False
        first = self.date == ""
        self.date = date
        if not first:
            self.orders.new_day()
            self.trades.new_day()
            self.rejects.new_day()
            self.requests.new_day()
            self.traded_value = 0.0
            self.session_opened_at = None
            for p in self.participants.values():
                p.new_day()
            for b in self.books.values():
                b.trades = 0.0
            for g in self.gateways.values():
                g.traffic.new_day()
                g.slow.new_day()
                g.disconnects = 0.0
        return True

    def hours_open(self, now_wall: float) -> float:
        """Hours since the session opened today, else since local midnight."""
        start = self.session_opened_at
        if start is None:
            day = datetime.fromisoformat(self.date).date()
            start = datetime.combine(day, dtime(0), self.session_tz).timestamp()
        return max(0.0, now_wall - start) / 3600.0

    # ------------------------------------------------------------------
    # beacons in
    # ------------------------------------------------------------------

    def observe(
        self, key: str, beacon: HealthBeacon, now: float, now_wall: float
    ) -> None:
        """Fold one accepted beacon of source ``key`` in."""
        self.roll_day(now_wall)
        started_today = (
            trading_date(beacon.started_at_ns / 1e9, self.session_tz) == self.date
        )
        process = beacon.process
        gateway_metrics = GATEWAYS.get(process)
        gateway: Gateway | None = None
        if gateway_metrics is not None:
            gateway = self.gateways.setdefault(key, Gateway(process))
            gateway.gauges = {}
        for sample in beacon.metrics:
            name, label, value = sample.name, sample.label, sample.value
            if sample.kind == "GAUGE":
                if process == ENGINE:
                    self._engine_gauge(name, label, value, now_wall)
                elif gateway is not None:
                    gateway.gauges.setdefault(name, {})[label] = value
                continue
            delta, first = self.tracker.step((key, name, label), beacon.boot_id, value)
            windowed = not first
            if first and not (started_today or name in DAILY_COUNTERS):
                continue  # a baseline from before today
            if delta <= 0:
                continue
            if process == ENGINE:
                self._engine_counter(name, label, delta, now, windowed)
            elif gateway is not None and gateway_metrics is not None:
                self._gateway_counter(
                    gateway, gateway_metrics, key, name, label, delta, now, windowed
                )
            rule = WATCHED_INCREASES.get(name)
            if rule is not None:
                self._increase(rule, key, delta, now, windowed)

    def _increase(
        self, rule: str, key: str, delta: float, now: float, windowed: bool
    ) -> None:
        self.increases.setdefault((rule, key), Rate()).add(
            now, delta, windowed=windowed
        )

    def _participant(self, gateway_id: str) -> Participant:
        return self.participants.setdefault(gateway_id, Participant())

    def _engine_counter(
        self, name: str, label: str, delta: float, now: float, windowed: bool
    ) -> None:
        if name in REQUEST_COUNTERS:
            self.requests.add(now, delta, windowed=windowed)
            self._participant(label).requests += delta
        if name == "engine.orders_in":
            self.orders.add(now, delta, windowed=windowed)
            self._participant(label).orders.add(now, delta, windowed=windowed)
        elif name == "engine.rejects":
            self.rejects.add(now, delta, windowed=windowed)
            self._participant(label).rejects += delta
        elif name == "engine.fills":
            self._participant(label).fills += delta
        elif name == "engine.connects":
            self._participant(label).connects += delta
        elif name == "engine.disconnects":
            self._participant(label).disconnects += delta
        elif name == "engine.heartbeat_timeouts":
            self._participant(label).heartbeat_timeouts += delta
        elif name == "engine.trades":
            self.trades.add(now, delta, windowed=windowed)
            self.books.setdefault(label, Book()).trades += delta
        elif name == "engine.traded_value":
            self.traded_value += delta

    def _engine_gauge(
        self, name: str, label: str, value: float, now_wall: float
    ) -> None:
        if name == "engine.participant_connected":
            self.set_connected(label, value >= 1, now_wall)
        elif name == "engine.resting_orders":
            self._participant(label).resting_orders = int(value)
        elif name.startswith("engine.book_"):
            self.books.setdefault(label, Book()).gauges[name] = value
        elif name == "engine.session_state":
            index = int(value)
            if 0 <= index < len(SESSION_STATE_ORDER):
                self.set_session_state(SESSION_STATE_ORDER[index].value, now_wall)
        elif not label:
            self.engine_gauges[name] = value

    def _gateway_counter(
        self,
        gateway: Gateway,
        spec: GatewayMetrics,
        key: str,
        name: str,
        label: str,
        delta: float,
        now: float,
        windowed: bool,
    ) -> None:
        if name == spec.traffic:
            gateway.traffic.add(now, delta, windowed=windowed)
        if name == spec.disconnects:
            gateway.disconnects += delta
        if name == spec.slow and (spec.slow_label is None or label == spec.slow_label):
            gateway.slow.add(now, delta, windowed=windowed)
            self._increase(SLOW_RULE, key, delta, now, windowed)

    # ------------------------------------------------------------------
    # engine bus (events.py) and gauges
    # ------------------------------------------------------------------

    def set_connected(self, gateway_id: str, connected: bool, now_wall: float) -> None:
        """A participant's connection as last reported; ``connected_since``
        only when the connect itself was seen."""
        p = self._participant(gateway_id)
        if connected and p.connected is False:
            p.connected_since = iso_utc(now_wall)
        elif not connected:
            p.connected_since = None
        p.connected = connected

    def connected_at(self, gateway_id: str, now_wall: float) -> None:
        """A ``CONNECT`` event: the connect time is known exactly."""
        p = self._participant(gateway_id)
        p.connected = True
        p.connected_since = iso_utc(now_wall)

    def set_session_state(
        self, state: str, now_wall: float, previous: str | None = None
    ) -> None:
        self.roll_day(now_wall)
        before = self.session_state if previous is None else previous
        if before == "CLOSED" and state != "CLOSED" and self.session_opened_at is None:
            self.session_opened_at = now_wall
        self.session_state = state

    # ------------------------------------------------------------------
    # snapshot blocks
    # ------------------------------------------------------------------

    def requests_5m(self, now: float) -> float:
        return self.requests.last_5m(now)

    def reject_pct_5m(self, now: float) -> float:
        """Rejected over all inbound requests in the last 5 minutes."""
        requests = self.requests.last_5m(now)
        return 0.0 if requests <= 0 else 100.0 * self.rejects.last_5m(now) / requests

    def trading(self, now: float, now_wall: float) -> dict[str, Any]:
        self.roll_day(now_wall)
        hours = self.hours_open(now_wall)
        g = self.engine_gauges
        return {
            "orders": self.orders.stats(now, hours),
            "trades": self.trades.stats(now, hours),
            "traded_value_today": max(0.0, self.traded_value),
            "reject_pct_5m": self.reject_pct_5m(now),
            "handle_p50_us": max(0.0, g.get("engine.handle_us_p50", 0.0)),
            "handle_p99_us": max(0.0, g.get("engine.handle_us_p99", 0.0)),
            "busy_pct": max(0.0, g.get("engine.busy_pct", 0.0)),
        }

    def participant_records(self, now: float, now_wall: float) -> list[dict[str, Any]]:
        hours = self.hours_open(now_wall)
        out = []
        for gateway_id, p in sorted(self.participants.items()):
            out.append(
                {
                    "id": gateway_id[:32],
                    "role": self.roles.get(gateway_id, "")[:32],
                    "connected": bool(p.connected),
                    "connected_since": p.connected_since if p.connected else None,
                    "orders": p.orders.stats(now, hours),
                    "reject_pct": (
                        0.0 if p.requests <= 0 else 100.0 * p.rejects / p.requests
                    ),
                    "fills_today": int(p.fills),
                    "resting_orders": max(0, p.resting_orders),
                    "connects_today": int(p.connects),
                    "disconnects_today": int(p.disconnects),
                    "heartbeat_timeouts_today": int(p.heartbeat_timeouts),
                }
            )
        return out

    def book_records(self) -> list[dict[str, Any]]:
        out = []
        for symbol, b in sorted(self.books.items()):
            g = b.gauges
            out.append(
                {
                    "symbol": symbol[:16],
                    "resting_orders": int(g.get("engine.book_resting_orders", 0)),
                    "stop_orders": int(g.get("engine.book_stop_orders", 0)),
                    "bid_levels": int(g.get("engine.book_bid_levels", 0)),
                    "ask_levels": int(g.get("engine.book_ask_levels", 0)),
                    "est_bytes": int(g.get("engine.book_est_bytes", 0)),
                    "heap_garbage_pct": min(
                        100.0, max(0.0, g.get("engine.book_heap_garbage_pct", 0.0))
                    ),
                    "trades_today": int(b.trades),
                    "halted": g.get("engine.book_halted", 0.0) >= 1,
                }
            )
        return out

    def gateway_records(self, now: float, keys: Iterable[str]) -> list[dict[str, Any]]:
        """``GatewayStats`` for the gateway processes among ``keys``."""
        out = []
        for key in keys:
            g = self.gateways.get(key)
            if g is None:
                continue
            spec = GATEWAYS[g.process]
            clients_max = g.gauge_sum(spec.clients_max)
            out.append(
                {
                    "key": key,
                    "kind": spec.kind,
                    "clients": int(g.gauge_sum(spec.clients) or 0),
                    "clients_max": None if clients_max is None else int(clients_max),
                    "msgs_per_sec": g.traffic.minute.total(now) / 60.0,
                    "disconnects_today": int(g.disconnects),
                    "slow_disconnects_today": int(g.slow.today),
                }
            )
        return out

    def forget_source(self, key: str) -> None:
        self.tracker.forget_source(key)
        self.gateways.pop(key, None)
        for watched in [w for w in self.increases if w[1] == key]:
            del self.increases[watched]

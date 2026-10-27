"""Engine counters and timings for the health beacon.

See docs-design/EduMatcher-Operator-Dashboard.md §8.2-§8.4. ``EngineMetrics``
holds only what the engine does not already keep: per-gateway counters
incremented on the handler funnels, and the dispatch-latency ring and busy
time, both fed from 1 message in ``SAMPLE_EVERY`` (design A4.10).
Everything else in the beacon -- trades, books, sessions, diagnostics -- is
read from the engine's existing state when the beacon is built, so there is
no second copy that could disagree.

Hot-path cost is one dict lookup plus one dict update per counted event; no
allocation once a label has been seen.

Label cardinality (risk K4)
---------------------------
A gateway id on an inbound message is whatever the sender wrote: the engine
rejects an unconfigured id, but only *after* the counters here have counted
the attempt. Every id is therefore mapped to a bounded label set before it
becomes a dict key: configured participants by name, anything else as
``UNKNOWN_LABEL``. Without a loaded configuration (backward-compatible mode)
the first ``MAX_DYNAMIC_LABELS`` distinct ids are kept and the rest fold into
``UNKNOWN_LABEL``. Neither the engine's memory nor the beacon can be grown by
a client inventing ids.
"""

from __future__ import annotations

import gc
import sys
import time
from collections.abc import Iterable
from typing import get_args

from edumatcher.engine.order_book import BookStats, OrderBook
from edumatcher.health.samples import counter, gauge
from edumatcher.models.generated.health import MetricSample
from edumatcher.models.reject import RejectCode
from edumatcher.models.session import SessionState

# --- Memory estimate constants (design §8.3) ---------------------------------
# Measured, not guessed: bytes per object beyond the containers' own storage,
# from a tracemalloc measurement of books of 2k-40k resting LIMIT orders
# (stable to within 2 % across that range). tests/test_engine_metrics.py
# re-measures and fails when the estimate drifts more than 15 % -- re-measure
# these when Order, _HeapEntry or Trade gain fields.
ORDER_BYTES = 425  # one Order (slots dataclass) with its id strings
ENTRY_BYTES = 160  # one _HeapEntry (slots) with its key tuple
TRADE_BYTES = 330  # one Trade in recent_trades

#: Label for a gateway id outside the configured participants.
UNKNOWN_LABEL = "(unknown)"
#: Distinct gateway labels kept when no configuration is loaded.
MAX_DYNAMIC_LABELS = 64
#: Longest label the beacon accepts (spec/messages/health.yaml MetricSample).
MAX_LABEL_LEN = 32
#: Raw-id -> label cache bound; ids beyond it are resolved on each call.
_LABEL_CACHE_MAX = 4096

#: Sampled dispatch durations kept per message class. A power of two so the
#: index wraps with a mask; the ring is preallocated and never resized.
LATENCY_RING = 1024
_RING_MASK = LATENCY_RING - 1

#: The percentiles cover the sampled messages of the last minute, at most
#: LATENCY_RING of them. They used to cover one beacon window (2 s): at
#: classroom rates that is a few dozen samples, and nearest-rank p99 of fewer
#: than 100 samples is simply their maximum -- the dashboard's "p99" was the
#: worst message of each 2 s.
LATENCY_HORIZON_NS = 60_000_000_000

#: Garbage collections remembered for engine.gc_pause_us_max.
GC_RING = 1024
_GC_MASK = GC_RING - 1

#: The run loop times one message (and one maintenance pass) in this many --
#: a power of two, tested with a mask. Timing every message cost about 1 % of
#: throughput; percentiles over 1-in-16 are statistically the same at any
#: rate where they mean anything (design A4.10, workplan I28/I31).
SAMPLE_EVERY = 16
SAMPLE_MASK = SAMPLE_EVERY - 1

#: ``engine.session_state`` is the index of the state in this tuple; pm-monitor
#: maps it back to the name with the same tuple.
SESSION_STATE_ORDER: tuple[SessionState, ...] = tuple(SessionState)

#: Per-gateway counters, in beacon order (design §8.2).
GATEWAY_COUNTERS: tuple[str, ...] = (
    "orders_in",
    "rejects",
    "cancels_in",
    "amends_in",
    "quotes_in",
    "fills",
    "connects",
    "auth_rejects",
    "disconnects",
    "heartbeat_timeouts",
)


class _LatencyRing:
    """The last LATENCY_RING sampled durations of one message class, each
    with when it started and how much of it was garbage collection."""

    __slots__ = ("duration", "started", "gc", "pos")

    def __init__(self) -> None:
        self.duration = [0] * LATENCY_RING
        self.started = [0] * LATENCY_RING
        self.gc = [0] * LATENCY_RING
        self.pos = 0

    def add(self, started_ns: int, duration_ns: int, gc_ns: int) -> None:
        i = self.pos & _RING_MASK
        self.duration[i] = duration_ns
        self.started[i] = started_ns
        self.gc[i] = gc_ns
        self.pos += 1

    def since(self, since_ns: int) -> list[tuple[int, int]]:
        """(duration, gc) of every sample started at or after ``since_ns``."""
        return [
            (self.duration[i], self.gc[i])
            for i in range(min(self.pos, LATENCY_RING))
            if self.started[i] >= since_ns
        ]


class EngineMetrics:
    """The engine's own counters; owned by ``Engine`` as ``self.metrics``."""

    def __init__(self) -> None:
        self.orders_in: dict[str, int] = {}
        self.rejects: dict[str, int] = {}
        self.cancels_in: dict[str, int] = {}
        self.amends_in: dict[str, int] = {}
        self.quotes_in: dict[str, int] = {}
        #: Keyed by raw gateway id, not label: filled on the trade hot path by
        #: Engine._publish_trade, from ids of orders the engine accepted.
        self.fills: dict[str, int] = {}
        self.connects: dict[str, int] = {}
        self.auth_rejects: dict[str, int] = {}
        self.disconnects: dict[str, int] = {}
        self.heartbeat_timeouts: dict[str, int] = {}
        #: Every reject by reason (``RejectCode``, or a label from
        #: :func:`reject_label`); a bounded set, so the label is the reason.
        self.rejects_by_code: dict[str, int] = {}

        self.msgs_in = 0
        self.gtc_flush_ms = 0.0
        #: Per symbol, the books' daily (trades, qty, value ticks) carried over
        #: their PRE_OPEN resets. engine.trades/traded_qty/traded_value are
        #: exported as carried + daily, so they are COUNTERs as the health spec
        #: defines them -- monotonic since process start -- although each book
        #: zeroes its daily figures every trading day. Exported raw, a reset
        #: read as a process restart in pm-monitor and lost the trades between
        #: the previous beacon and the reset (A+B review, I89). Updated only at
        #: the reset, never on the trade path.
        self._carried: dict[str, tuple[int, int, int]] = {}

        self._known: frozenset[str] | None = None
        self._dynamic: set[str] = set()
        self._labels: dict[str, str] = {}

        # Sampled timing (I31): durations of 1 message in SAMPLE_EVERY, order
        # entry apart from everything else -- heartbeats, connects, queries,
        # admin -- so a book snapshot request does not count as matching.
        self._orders = _LatencyRing()
        self._other = _LatencyRing()
        self._dispatch_ns = 0
        self._dispatch_samples = 0
        self._maint_ns = 0
        self._maint_samples = 0
        self._iterations = 0
        self._window_msgs = 0
        self._window_iterations = 0
        self._window_start_ns = time.perf_counter_ns()
        #: True until an order-entry message has been timed in the current
        #: window, so even a quiet engine reports an order latency rather than
        #: zeros: at a few orders a minute, 1 in 16 of all messages could
        #: miss every one of them. Other messages are timed meanwhile, which
        #: costs nothing at the rates where it happens. Read by the loop.
        self.sample_next = True

        # Garbage collection, timed by on_gc. gc_ns only grows: the loop
        # reads it either side of a sampled dispatch to learn how much of
        # that dispatch was collection.
        self.gc_ns = 0
        self.gc_collections = 0
        self._gc_started_ns = 0
        self._gc_window_ns = 0
        self._gc_pause = [0] * GC_RING
        self._gc_at = [0] * GC_RING
        self._gc_pos = 0

    # ------------------------------------------------------------------
    # labels
    # ------------------------------------------------------------------

    def carry_daily(self, book: OrderBook) -> None:
        """Fold a book's daily figures in; call just before they are zeroed."""
        trades, qty, value = self._carried.get(book.symbol, (0, 0, 0))
        self._carried[book.symbol] = (
            trades + book.daily_trades,
            qty + book.daily_qty,
            value + book.daily_value_ticks,
        )

    def trade_totals(self, book: OrderBook) -> tuple[int, int, int]:
        """(trades, qty, value ticks) of a book since process start."""
        trades, qty, value = self._carried.get(book.symbol, (0, 0, 0))
        return (
            trades + book.daily_trades,
            qty + book.daily_qty,
            value + book.daily_value_ticks,
        )

    def set_known_gateways(self, known: frozenset[str] | None) -> None:
        """Configured participants; ``None`` when running without config."""
        self._known = None if known is None else frozenset(g.upper() for g in known)
        self._labels.clear()
        self._dynamic.clear()

    @property
    def known_gateways(self) -> frozenset[str]:
        return self._known or frozenset()

    def label(self, gateway: object) -> str:
        """The bounded label a raw gateway id is counted under."""
        if type(gateway) is not str:
            return UNKNOWN_LABEL
        cached = self._labels.get(gateway)
        if cached is not None:
            return cached
        canonical = gateway.upper()
        if not canonical or len(canonical) > MAX_LABEL_LEN:
            result = UNKNOWN_LABEL
        elif self._known is not None:
            result = canonical if canonical in self._known else UNKNOWN_LABEL
        elif canonical in self._dynamic or len(self._dynamic) < MAX_DYNAMIC_LABELS:
            self._dynamic.add(canonical)
            result = canonical
        else:
            result = UNKNOWN_LABEL
        if len(self._labels) < _LABEL_CACHE_MAX:
            self._labels[gateway] = result
        return result

    def count_reject(self, gateway: object, code: str) -> None:
        """One rejected acknowledgement: per gateway and by reason."""
        self.count(self.rejects, gateway)
        self.rejects_by_code[code] = self.rejects_by_code.get(code, 0) + 1

    def count(self, counter_: dict[str, int], gateway: object) -> None:
        """Increment one per-gateway counter -- the hot-path entry point.

        Shaped for the perf gate (design A4.10): a cache hit is one dict
        subscript, and the try costs nothing when it does not raise.
        TypeError covers an unhashable id from a malformed payload.
        """
        try:
            label = self._labels[gateway]  # type: ignore[index]
        except KeyError, TypeError:
            label = self.label(gateway)
        counter_[label] = counter_.get(label, 0) + 1

    def order_in(self, gateway: object) -> None:
        """``count(self.orders_in, gateway)``, specialised: it runs once per
        inbound order, so it skips the counter argument (perf gate, A4.10)."""
        try:
            label = self._labels[gateway]  # type: ignore[index]
        except KeyError, TypeError:
            label = self.label(gateway)
        orders_in = self.orders_in
        orders_in[label] = orders_in.get(label, 0) + 1

    # ------------------------------------------------------------------
    # timing
    # ------------------------------------------------------------------

    def record_dispatch(
        self,
        duration_ns: int,
        msgs_total: int,
        *,
        started_ns: int | None = None,
        gc_ns: int = 0,
        order: bool = True,
    ) -> None:
        """One *sampled* PULL message (design A4.10, I31).

        The run loop times one message in ``SAMPLE_EVERY`` -- plus every one
        until an order message is timed in a beacon window, see
        ``sample_next`` -- and passes its own
        running message count, so ``msgs_in`` stays exact without an
        attribute update on every message. ``gc_ns`` is the collection time
        inside the dispatch; ``order`` is False for anything but order entry.
        """
        self.msgs_in = msgs_total
        if order:
            self.sample_next = False
        if started_ns is None:
            started_ns = time.perf_counter_ns()
        (self._orders if order else self._other).add(started_ns, duration_ns, gc_ns)
        self._dispatch_ns += duration_ns
        self._dispatch_samples += 1

    def on_gc(self, phase: str, info: dict[str, int]) -> None:
        """A ``gc.callbacks`` hook: times every collection."""
        now = time.perf_counter_ns()
        if phase == "start":
            self._gc_started_ns = now
            return
        pause = now - self._gc_started_ns
        self.gc_ns += pause
        self.gc_collections += 1
        i = self._gc_pos & _GC_MASK
        self._gc_pause[i] = pause
        self._gc_at[i] = now
        self._gc_pos += 1

    def watch_gc(self) -> None:
        """Start timing collections; the engine's run loop calls this."""
        if self.on_gc not in gc.callbacks:
            gc.callbacks.append(self.on_gc)

    def unwatch_gc(self) -> None:
        if self.on_gc in gc.callbacks:
            gc.callbacks.remove(self.on_gc)

    def record_maintenance(
        self, duration_ns: int, iterations_total: int, msgs_total: int
    ) -> None:
        """One *sampled* maintenance pass; ``iterations_total`` is the loop's
        running count of passes, sampled or not.

        Also syncs ``msgs_in``: maintenance runs when idle too (every poll
        timeout), so the count catches up within SAMPLE_EVERY passes after a
        burst instead of waiting for the next sampled message.
        """
        self._iterations = iterations_total
        self.msgs_in = msgs_total
        self._maint_ns += duration_ns
        self._maint_samples += 1

    def timing_samples(self, now_ns: int | None = None) -> list[MetricSample]:
        """Latency over the last LATENCY_HORIZON_NS, and busy and GC share
        for the interval since the last call, which starts a new interval.

        Percentiles and max are over the *sampled* messages; busy time is
        estimated as mean sampled duration x count, separately for message
        handling and for maintenance passes.
        """
        now_ns = time.perf_counter_ns() if now_ns is None else now_ns
        since = now_ns - LATENCY_HORIZON_NS
        orders = self._orders.since(since)
        recent = sorted(d for d, _ in orders)
        ex_gc = sorted(d - g for d, g in orders)
        other = sorted(d for d, _ in self._other.since(since))
        pauses = [
            self._gc_pause[i]
            for i in range(min(self._gc_pos, GC_RING))
            if self._gc_at[i] >= since
        ]
        busy_ns = 0.0
        if self._dispatch_samples:
            msgs = self.msgs_in - self._window_msgs
            busy_ns += self._dispatch_ns / self._dispatch_samples * msgs
        if self._maint_samples:
            passes = self._iterations - self._window_iterations
            busy_ns += self._maint_ns / self._maint_samples * passes
        elapsed = now_ns - self._window_start_ns
        busy_pct = min(100.0, 100.0 * busy_ns / elapsed) if elapsed > 0 else 0.0
        gc_window = self.gc_ns - self._gc_window_ns
        gc_pct = min(100.0, 100.0 * gc_window / elapsed) if elapsed > 0 else 0.0

        self._dispatch_ns = self._dispatch_samples = 0
        self._maint_ns = self._maint_samples = 0
        self._window_msgs = self.msgs_in
        self._window_iterations = self._iterations
        self._window_start_ns = now_ns
        self._gc_window_ns = self.gc_ns
        self.sample_next = True
        return [
            gauge("engine.handle_us_p50", percentile(recent, 50) / 1000.0),
            gauge("engine.handle_us_p99", percentile(recent, 99) / 1000.0),
            gauge("engine.handle_us_max", (recent[-1] if recent else 0) / 1000.0),
            gauge("engine.handle_us_p99_ex_gc", percentile(ex_gc, 99) / 1000.0),
            gauge("engine.handle_samples", len(recent)),
            gauge("engine.other_us_p99", percentile(other, 99) / 1000.0),
            gauge("engine.other_us_max", (other[-1] if other else 0) / 1000.0),
            gauge("engine.busy_pct", busy_pct),
            gauge("engine.gc_pause_us_max", max(pauses, default=0) / 1000.0),
            gauge("engine.gc_time_pct", gc_pct),
            counter("engine.gc_collections", self.gc_collections),
        ]

    # ------------------------------------------------------------------
    # samples
    # ------------------------------------------------------------------

    def counter_samples(self) -> list[MetricSample]:
        """Every per-gateway counter for every configured gateway, zeros
        included (design G17: a zero that is never published looks like
        "no data"), plus any other label that has counted something."""
        out: list[MetricSample] = [counter("engine.msgs_in", self.msgs_in)]
        known = self.known_gateways
        for name in GATEWAY_COUNTERS:
            # Keys are labels already, except for counters filled with raw
            # ids on a hot path (fills); label() folds those here.
            values: dict[str, int] = {}
            for key, n in getattr(self, name).items():
                label = self.label(key)
                values[label] = values.get(label, 0) + n
            for label in sorted(known | values.keys()):
                out.append(counter(f"engine.{name}", values.get(label, 0), label))
        # Every reason, zeros included (G17): a counter first seen with a
        # value counts as a baseline in pm-monitor when the engine started on
        # an earlier day, so the first rejects of a new reason would be lost.
        for code in sorted(REJECT_LABELS | self.rejects_by_code.keys()):
            out.append(
                counter(
                    "engine.rejects_by_code", self.rejects_by_code.get(code, 0), code
                )
            )
        return out


#: How a reject without a ``RejectCode`` -- quotes, combos and OCOs carry
#: only a reason text -- is labelled in ``engine.rejects_by_code``: the first
#: entry whose text the reason contains (lower case). Two are not RejectCodes:
#: the market-maker obligations a quote can fail (``mm_max_spread_ticks``,
#: ``mm_min_qty``), the commonest reject of a quoting bot.
REASON_LABELS: tuple[tuple[str, str], ...] = (
    ("gateway not configured", "GATEWAY_NOT_CONFIGURED"),
    ("gateway not connected", "AUTH_REQUIRED"),
    ("only allowed for market_maker", "ROLE_DENIED"),
    ("circuit breaker", "CIRCUIT_BREAKER_ACTIVE"),
    ("halted", "INSTRUMENT_HALTED"),
    ("market is closed", "MARKET_CLOSED"),
    ("symbol not configured", "UNKNOWN_SYMBOL"),
    ("missing", "MISSING_FIELD"),
    ("invalid", "MALFORMED_MESSAGE"),
    ("exceeds max", "MM_MAX_SPREAD"),
    ("quote size must be", "MM_MIN_QTY"),
    ("not found", "ORDER_NOT_FOUND"),
    ("no active quote", "ORDER_NOT_FOUND"),
    ("quantit", "QTY_OUT_OF_RANGE"),
    ("price", "PRICE_OUT_OF_RANGE"),
)


#: Every label ``engine.rejects_by_code`` can carry.
REJECT_LABELS: frozenset[str] = (
    frozenset(get_args(RejectCode))
    | {label for _needle, label in REASON_LABELS}
    | {"UNKNOWN"}
)


def reject_label(reason: str) -> str:
    """The ``engine.rejects_by_code`` label of a reject known only by its text."""
    text = reason.lower()
    for needle, label in REASON_LABELS:
        if needle in text:
            return label
    return "UNKNOWN"


def percentile(sorted_values: list[int], pct: float) -> float:
    """Nearest-rank percentile of an ascending list; 0 for an empty one."""
    if not sorted_values:
        return 0.0
    rank = max(1, -(-len(sorted_values) * pct // 100))  # ceil without floats
    return float(sorted_values[int(rank) - 1])


def book_samples(books: Iterable[OrderBook]) -> list[MetricSample]:
    """Per-book gauges of design §8.3, one ``book_stats()`` call per book.

    Named ``engine.book_*`` rather than the design's ``book.*``: that is the
    prefix of the parameterised topic ``book.{symbol}``, so a metric called
    book-dot-halted would also be the book topic of a symbol named HALTED.
    """
    out: list[MetricSample] = []
    for book in books:
        stats: BookStats = book.book_stats()
        sym = book.symbol
        out.extend(
            (
                gauge("engine.book_resting_orders", stats.resting_orders, sym),
                gauge("engine.book_gtc_orders", stats.gtc_orders, sym),
                gauge("engine.book_stop_orders", stats.stop_orders, sym),
                gauge("engine.book_bid_levels", stats.bid_levels, sym),
                gauge("engine.book_ask_levels", stats.ask_levels, sym),
                gauge("engine.book_heap_entries", stats.heap_entries, sym),
                gauge("engine.book_heap_garbage_pct", stats.heap_garbage_pct, sym),
                gauge("engine.book_est_bytes", memory_estimate(book, stats), sym),
            )
        )
    return out


def memory_estimate(book: OrderBook, stats: BookStats | None = None) -> int:
    """Estimated bytes held by one book (design §8.3). Never exact: Python
    has no cheap per-object-graph size, so this is container storage plus
    measured per-object constants. O(levels + gateways), not O(orders)."""
    stats = book.book_stats() if stats is None else stats
    # A garbage heap entry (cancelled or filled, not yet compacted) still
    # holds its Order alive, so it costs an Order as well as an entry.
    garbage = stats.heap_entries - stats.live_entries
    return (
        sum(sys.getsizeof(c) for c in book.containers())
        + (stats.resting_orders + garbage) * ORDER_BYTES
        + stats.heap_entries * ENTRY_BYTES
        + stats.recent_trades * TRADE_BYTES
    )

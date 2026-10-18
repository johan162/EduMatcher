"""Engine counters and timings for the health beacon.

See docs-design/EduMatcher-Operator-Dashboard.md §8.2-§8.4. ``EngineMetrics``
holds only what the engine does not already keep: per-gateway counters
incremented on the handler funnels, the dispatch-latency ring and busy time.
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

import sys
import time
from collections.abc import Iterable

from edumatcher.engine.order_book import BookStats, OrderBook
from edumatcher.health.samples import counter, gauge
from edumatcher.models.generated.health import MetricSample
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

#: Dispatch durations kept for the per-interval percentiles. A power of two so
#: the index wraps with a mask; the ring is preallocated and never resized.
LATENCY_RING = 1024
_RING_MASK = LATENCY_RING - 1

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

        self.msgs_in = 0
        self.gtc_flush_ms = 0.0

        self._known: frozenset[str] | None = None
        self._dynamic: set[str] = set()
        self._labels: dict[str, str] = {}

        self._ring = [0] * LATENCY_RING
        self._ring_pos = 0
        self._ring_count = 0  # durations recorded since the last sample
        self._busy_ns = 0
        self._window_start_ns = time.perf_counter_ns()

    # ------------------------------------------------------------------
    # labels
    # ------------------------------------------------------------------

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

    def count(self, counter_: dict[str, int], gateway: object) -> None:
        """Increment one per-gateway counter -- the hot-path entry point.

        Shaped for the perf gate (design A4.10): a cache hit is one dict
        subscript, and the try costs nothing when it does not raise.
        TypeError covers an unhashable id from a malformed payload.
        """
        try:
            label = self._labels[gateway]  # type: ignore[index]
        except (KeyError, TypeError):
            label = self.label(gateway)
        counter_[label] = counter_.get(label, 0) + 1

    def order_in(self, gateway: object) -> None:
        """``count(self.orders_in, gateway)``, specialised: it runs once per
        inbound order, so it skips the counter argument (perf gate, A4.10)."""
        try:
            label = self._labels[gateway]  # type: ignore[index]
        except (KeyError, TypeError):
            label = self.label(gateway)
        orders_in = self.orders_in
        orders_in[label] = orders_in.get(label, 0) + 1

    # ------------------------------------------------------------------
    # timing
    # ------------------------------------------------------------------

    def record_dispatch(self, duration_ns: int) -> None:
        """One handled PULL message: latency ring + busy time."""
        self.msgs_in += 1
        self._ring[self._ring_pos & _RING_MASK] = duration_ns
        self._ring_pos += 1
        self._ring_count += 1
        self._busy_ns += duration_ns

    def record_busy(self, duration_ns: int) -> None:
        """Busy time that is not message handling (maintenance flushes)."""
        self._busy_ns += duration_ns

    def timing_samples(self, now_ns: int | None = None) -> list[MetricSample]:
        """Percentiles and busy share for the interval since the last call,
        which starts a new interval."""
        now_ns = time.perf_counter_ns() if now_ns is None else now_ns
        n = min(self._ring_count, LATENCY_RING)
        recent = sorted(
            self._ring[(self._ring_pos - i - 1) & _RING_MASK] for i in range(n)
        )
        elapsed = now_ns - self._window_start_ns
        busy_pct = min(100.0, 100.0 * self._busy_ns / elapsed) if elapsed > 0 else 0.0
        self._ring_count = 0
        self._busy_ns = 0
        self._window_start_ns = now_ns
        return [
            gauge("engine.handle_us_p50", percentile(recent, 50) / 1000.0),
            gauge("engine.handle_us_p99", percentile(recent, 99) / 1000.0),
            gauge("engine.handle_us_max", (recent[-1] if recent else 0) / 1000.0),
            gauge("engine.busy_pct", busy_pct),
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
        return out


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

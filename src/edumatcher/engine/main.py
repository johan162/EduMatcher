"""
Matching Engine — main process.

Startup:
  poetry run pm-engine [-v|-vv] [--log-level LEVEL] [-q]

ZMQ sockets:
  PULL :5555  — receives order.new / order.amend / order.cancel from gateways
  PUB  :5556  — broadcasts order.ack, order.fill, order.amended, order.cancelled,
                order.expired, trade.executed, book.{SYMBOL}

Shutdown (SIGINT / Ctrl-C):
  1. Save resting GTC and DAY orders to data/gtc_orders.json — a process
     exit is not a day boundary; a DAY order is only discarded on the next
     startup if its business day has passed (see _restore_gtc and
     docs-design/EduMatcher-Revised-Quote-Persistence.md §12-§13)
  2. Clean ZMQ teardown

How to read this file: follow ONE new order
-------------------------------------------
The file is large (it also handles quotes, combos, OCO, sessions, risk
controls, persistence, ...).  Ignore all of that on a first read and follow
the path of a plain ``order.new`` message.  Everything is single-threaded:
one message is completely handled before the next is looked at, which is what
makes the exchange deterministic and the code free of locks.

  1. ``Engine.run``                  poll the PULL socket; ``decode`` the
                                     frames into (topic, payload dict).
  2. ``Engine._echo_command``        re-publish the raw request so the audit
                                     trail contains it (before handling it).
  3. ``Engine._dispatch_pull_message`` route by topic; ``order.new`` goes to
  4. ``Engine._handle_new_order``    -- the gatekeeper: build the ``Order``,
                                     resolve SMP, then a series of checks
                                     (gateway, symbol, validation, session,
                                     halt, collar); each failure sends ONE
                                     reject and returns.  Survivors get the
                                     positive ACK.
  5. ``OrderBook.process``           (engine/order_book.py) the matching
                                     itself; returns ``(trades, events)``.
  6. ``Engine._publish_dispatch``    turn the result into bus messages:
                                     ``order.fill`` / ``order.cancelled`` /
                                     rejects per order, then
  7. ``Engine._publish_trade``       one ``trade.executed`` per trade, plus
                                     position ledger, drop copy and circuit
                                     breaker updates.
  8. back in ``run``                 maintenance tick (book snapshots, timers,
                                     persistence) and the next message.

Output goes out on the PUB socket as multipart frames ``[topic, payload]``
(plus an envelope frame carrying causation ids); gateways subscribe to
``order.ack.<GATEWAY>``-style topics so each participant only receives its
own private messages, while ``trade.executed`` and ``book.<SYMBOL>`` are
public.  The engine only *publishes*; it never talks to a client directly.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
import platform
import logging
import random
import signal
import sys
import time
from pathlib import Path
from typing import Any, Optional, cast

import holidays
import zmq

from edumatcher.config import (
    ENGINE_PULL_BIND_ADDR,
    ENGINE_PUB_BIND_ADDR,
    GTC_ORDERS_FILE,
    GTC_COMBOS_FILE,
    BOOK_STATS_FILE,
    RUN_SEQ_FILE,
    ENGINE_CONFIG_FILE,
    DATA_DIR,
)
from edumatcher.engine.auction import (
    AuctionResult,
    compute_equilibrium,
    execute_uncross,
    executable_at,
)
from edumatcher.cli_version import add_version_argument, package_version, source_commit
from edumatcher.engine.circuit_breaker import CircuitBreakerLevel, CircuitBreakerState
from edumatcher.engine.collar import CollarConfig, validate_collar
from edumatcher.engine.order_limits import (
    OrderLimitsConfig,
    validate_order_limits,
)
from edumatcher.engine.config_loader import (
    DAY_KEYS,
    DaySchedule,
    EngineConfig,
    ScheduleConfig,
    load_engine_config,
)
from edumatcher.engine.schedule_resolve import (
    is_bank_holiday,
    resolve_day,
    upcoming_holidays,
)
from edumatcher.engine.drop_copy import DropCopyPublisher
from edumatcher.engine.order_book import OrderBook
from edumatcher.engine.metrics import (
    SAMPLE_MASK,
    SESSION_STATE_ORDER,
    EngineMetrics,
    book_samples,
    reject_label,
)
from edumatcher.health import HealthReporter, counter, gauge
from edumatcher.models.generated.health import MetricSample
from edumatcher.engine.persistence import (
    load_gtc_orders,
    save_gtc_orders,
    load_book_stats,
    save_book_stats,
    load_gtc_combos,
    save_gtc_combos,
    load_and_bump_run_seq,
)
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler
from edumatcher.messaging.bus import make_puller, make_publisher
from edumatcher.models.combo import ComboOrder, ComboStatus, ComboType
from edumatcher.models.clock import now_ns
from edumatcher.models.generated.session import (
    TOPIC_SESSION_NEXT,
    TOPIC_SESSION_TRANSITION,
)
from edumatcher.models.generated.order import (
    TOPIC_ORDER_AMEND,
    TOPIC_ORDER_CANCEL,
    TOPIC_ORDER_COMBO,
    TOPIC_ORDER_COMBO_CANCEL,
    TOPIC_ORDER_NEW,
    TOPIC_ORDER_OCO,
    TOPIC_ORDER_OCO_CANCEL,
    TOPIC_ORDERS_REQUEST,
    TOPIC_PRICE_LEVEL_ORDERS_REQUEST,
    OrderFillLiquidityFlag,
    make_order_cancelled_unchecked,
    make_order_fill_unchecked,
    topic_order_ack,
)
from edumatcher.models.generated.trade import make_trade_executed_unchecked
from edumatcher.models.generated.order import (
    make_engine_trace_unchecked,
    make_order_triggered_unchecked,
)
from edumatcher.models.generated.risk import make_band_unchecked
from edumatcher.models.generated.system import make_book_checkpoint
from edumatcher.models.message import (
    dumps,
    decode,
    decode_push_envelope,
    make_ack_msg,
    make_amended_msg,
    make_book_msg,
    make_depth_msg,
    make_cancelled_msg,
    make_combo_ack_msg,
    make_combo_status_msg,
    make_eod_msg,
    make_expired_msg,
    fill_status,
    make_gateway_auth_msg,
    make_gateway_bye_msg,
    make_circuit_breaker_halt_all_ack_msg,
    make_circuit_breaker_resume_all_ack_msg,
    make_symbol_halt_ack_msg,
    make_symbol_resume_ack_msg,
    make_cancel_symbol_ack_msg,
    make_force_uncross_ack_msg,
    make_kill_switch_ack_msg,
    make_kill_switch_gateway_ack_msg,
    make_kill_switch_global_ack_msg,
    make_orders_msg,
    make_price_level_orders_msg,
    make_quote_ack_msg,
    make_quote_bootstrap_msg,
    make_quote_legs_msg,
    make_quote_status_msg,
    make_symbols_msg,
    make_auction_indicative_msg,
    make_session_state_msg,
    make_session_transition_ack_msg,
    make_auction_result_msg,
    make_oco_ack_msg,
    make_oco_cancelled_msg,
    make_session_status_msg,
    make_session_schedule_msg,
    make_gateways_msg,
    make_volume_msg,
    make_halt_status_msg,
    make_position_snapshot_msg,
    make_reference_msg,
    make_reference_reload_ack_msg,
    make_admin_action_msg,
    make_risk_state_msg,
    make_startup_msg,
    make_startup_recovery_msg,
    make_recovery_item_msg,
    make_diagnostic_msg,
)
from edumatcher.models.participant import (
    DisconnectBehaviour,
    ParticipantRole,
    ParticipantSession,
)
from edumatcher.models.order import (
    Order,
    OrderOrigin,
    OrderStatus,
    OrderType,
    Side,
    SmpAction,
    TIF,
)
from edumatcher.models.price import (
    TickViolation,
    from_ticks,
    to_ticks,
    to_ticks_exact,
)
from edumatcher.models.price import get_tick_decimals, register_tick_decimals
from edumatcher.models.trade import current_run_seq, set_run_seq
from edumatcher.models.quote import (
    QuoteEntry,
    QuoteIndex,
    QuoteLegSnapshot,
    QuoteRefreshPolicy,
    QuoteState,
)
from edumatcher.models.session import (
    SessionState,
    VALID_TRANSITIONS,
    accepts_orders,
    is_auction_phase,
    is_matching_enabled,
)
from edumatcher.models.trade import Trade
from edumatcher.models.generated.book import TOPIC_BOOK_SNAPSHOT_REQUEST
from edumatcher.models.generated.circuit_breaker import (
    make_circuit_breaker_extend,
    make_circuit_breaker_halt,
    make_circuit_breaker_resume,
)
from edumatcher.models.generated.risk import (
    TOPIC_CANCEL_SYMBOL,
    TOPIC_CIRCUIT_BREAKER_HALT_ALL,
    TOPIC_CIRCUIT_BREAKER_RESUME_ALL,
    TOPIC_FORCE_UNCROSS,
    TOPIC_KILL_SWITCH,
    TOPIC_KILL_SWITCH_GATEWAY,
    TOPIC_KILL_SWITCH_GLOBAL,
    TOPIC_SYMBOL_HALT,
    TOPIC_SYMBOL_RESUME,
)
from edumatcher.models.reject import CancelReason, RejectCode
from edumatcher.models.generated.quote import (
    TOPIC_QUOTE_CANCEL,
    TOPIC_QUOTE_NEW,
)
from edumatcher.models.generated.system import (
    TOPIC_GATEWAYS_REQUEST,
    TOPIC_GATEWAY_CONNECT,
    TOPIC_GATEWAY_DISCONNECT,
    TOPIC_GATEWAY_HEARTBEAT,
    TOPIC_HALT_STATUS_REQUEST,
    TOPIC_POSITION_REQUEST,
    TOPIC_QUOTE_BOOTSTRAP_REQUEST,
    TOPIC_QUOTE_LEGS_REQUEST,
    TOPIC_REFERENCE_RELOAD,
    TOPIC_REFERENCE_REQUEST,
    TOPIC_RISK_STATE_REQUEST,
    TOPIC_SESSION_SCHEDULE_REQUEST,
    TOPIC_SESSION_STATE_REQUEST,
    TOPIC_SYMBOLS_REQUEST,
    TOPIC_VOLUME_REQUEST,
)

# Kept for backward compatibility (e.g. tests that reference it).  The hot path
# uses the monotonic now_ns() for event timestamps (M9), not this raw source.
_time_ns = time.time_ns

# L2: operational logging goes through the logging module (not print()).  The
# process entry point (main()) configures the handler/level; the library itself
# installs no handlers.
log = logging.getLogger(__name__)


def _country_wire_code(country: str | None) -> str | None:
    """Return the ISO alpha-2 country code used by reference messages."""
    if country is None:
        return None
    try:
        return str(holidays.country_holidays(country).country)
    except Exception:
        return country[:2].upper()


def _weekly_schedule_wire(
    schedule: "ScheduleConfig | None", country: str
) -> dict[str, Any] | None:
    """Serialize a resolved ScheduleConfig into the WeeklySchedule wire shape.

    Includes the engine-resolved ``today``/``today_is_holiday`` convenience
    fields (see the ``WeeklySchedule`` doc in spec/messages/system.yaml) so a
    client -- in particular a browser, e.g. trader-gui's countdown widget --
    never needs its own holiday calendar; the engine already runs the same
    ``python-holidays`` lookup for pm-scheduler and resolves "which entry
    applies right now" once, here.
    """
    if schedule is None:
        return None

    def _day(ds: "DaySchedule | None") -> dict[str, str] | None:
        if ds is None:
            return None
        return {
            "pre_open": ds.pre_open,
            "opening_auction_start": ds.opening_auction_start,
            "continuous_start": ds.continuous_start,
            "closing_auction_start": ds.closing_auction_start,
            "closing_auction_end": ds.closing_auction_end,
        }

    today = datetime.now().date()
    result: dict[str, Any] = {key: _day(schedule.days[key]) for key in DAY_KEYS}
    result["holidays"] = _day(schedule.holidays)
    result["today"] = _day(resolve_day(schedule, today, country))
    result["today_is_holiday"] = is_bank_holiday(today, country)
    result["upcoming_holidays"] = [
        {"date": day.isoformat(), "name": name[:64]}
        for day, name in upcoming_holidays(country, today)[:64]
    ]
    return result


_CLIENT_NAME = "pm-engine"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"

# Pre-built status set — a small hot-path allocation avoided (see
# docs-design/perf-notes.md). The pre-encoded trade topic that used to sit here
# now lives in the generated binding, which pre-encodes it the same way.
_ENDED_STATUSES = frozenset(
    {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}
)

#: What an order the book rejected is told when matching was on: only a FOK
#: short of liquidity gets there (see ``Engine._book_reject``).
_NO_LIQUIDITY: tuple[RejectCode, str] = (
    "INSUFFICIENT_LIQUIDITY",
    "Insufficient liquidity",
)


class _Execution:
    """What one order executed in one dispatch: the sum of its trades.

    One ``order.fill`` reports all of them (H5), at the order's own VWAP (H6),
    with the ids of the trades behind it and the order's MAKER/TAKER side
    (G9). An order is the aggressor of all its trades in a dispatch or of
    none, so the first trade settles the flag.
    """

    __slots__ = ("qty", "notional", "trade_ids", "flag")

    def __init__(self, flag: OrderFillLiquidityFlag) -> None:
        self.qty = 0
        self.notional = 0  # ticks x shares, divided once (H6)
        self.trade_ids: list[str] = []
        self.flag: OrderFillLiquidityFlag = flag


#: The topics timed as order entry (engine.handle_us_*); every other PULL
#: message -- heartbeats, connects, queries, admin -- is engine.other_us_*.
_ORDER_ENTRY_TOPICS = frozenset(
    {
        TOPIC_ORDER_NEW,
        TOPIC_ORDER_CANCEL,
        TOPIC_ORDER_AMEND,
        TOPIC_ORDER_COMBO,
        TOPIC_ORDER_COMBO_CANCEL,
        TOPIC_ORDER_OCO,
        TOPIC_ORDER_OCO_CANCEL,
        TOPIC_QUOTE_NEW,
        TOPIC_QUOTE_CANCEL,
    }
)
_DEBUG_SUMMARY_INTERVAL_SEC = 5.0


def _book_may_reject(order: Order, do_match: bool) -> bool:
    """True when ``book.process(order, match=do_match)`` may finalise the
    order as REJECTED: a FOK short of liquidity, or an order that cannot
    rest posted while matching is off. Such an order is acked only after
    the book has decided, so a rejected one gets a single ``accepted=false``
    ack, never ``accepted=true`` first (X5; participant guide, order types).
    """
    return order.order_type is OrderType.FOK or (
        not do_match
        and order.order_type in (OrderType.MARKET, OrderType.IOC, OrderType.FOK)
    )


#: How often the resting book is checkpointed to disk while the session runs.
#: This is the upper bound on what an abrupt termination can lose. Five
#: seconds keeps the write volume negligible next to the 200 ms poll tick
#: while bounding the exposure to something an operator can reason about.
_PERSIST_INTERVAL_SEC = 5.0

#: A session that has sent a system.gateway_heartbeat is disconnected once
#: this many of its own beat intervals pass without another one.
_HEARTBEAT_MISSED_LIMIT = 3
#: How often sessions are checked for missed heartbeats. Checking on every
#: loop pass cost ~9% of the engine at 500 sessions and 1 000 orders/s.
_SILENCE_CHECK_SEC = 1.0

#: Topics whose payload names an order the submitting gateway is waiting on an
#: ack for. If a handler for one of these raises, the client is left with no
#: ACK and no REJECT, so the except path owes it a reject. Query topics
#: (``*_request``) and session/risk control topics are absent deliberately:
#: nothing is resting on them, and a spurious order-reject addressed to an id
#: that is not an order is worse than silence.
_ORDER_TOPICS = frozenset(
    {
        TOPIC_ORDER_NEW,
        TOPIC_ORDER_CANCEL,
        TOPIC_ORDER_AMEND,
        TOPIC_ORDER_COMBO,
        TOPIC_ORDER_COMBO_CANCEL,
        TOPIC_ORDER_OCO,
        TOPIC_ORDER_OCO_CANCEL,
    }
)


def order_to_display_dict(order: Order) -> dict[str, Any]:
    """Serialize an order for an outbound snapshot in *display* units (L3).

    Single source of truth built on ``Order.to_dict()`` (so fields never drift
    from the model), with tick prices converted to display floats. The
    timestamp is the one field this projection does NOT convert (AR-0.3b):
    it rides through as ``ts_ns``, the same raw nanosecond integer
    ``Order.timestamp`` already is, matching the convention the rest of the
    wire uses (trade.executed, book/depth snapshots, the index family) —
    see spec/messages/order.yaml's OrderDisplay doc for why converting a
    correlation-critical timestamp to display seconds, the way price is
    converted to display money, would be the wrong call here.
    """
    d = order.to_dict()
    sym = order.symbol
    # The projection renames as well as converts: what leaves here is display
    # money, so it must not keep a name that says ticks.
    d["price"] = (
        from_ticks(order.price_ticks, sym) if order.price_ticks is not None else None
    )
    d["stop_price"] = (
        from_ticks(order.stop_price_ticks, sym)
        if order.stop_price_ticks is not None
        else None
    )
    d["trail_offset"] = (
        from_ticks(order.trail_offset_ticks, sym)
        if order.trail_offset_ticks is not None
        else None
    )
    for tick_key in ("price_ticks", "stop_price_ticks", "trail_offset_ticks"):
        del d[tick_key]
    # `tick_decimals` rides through: it is what the display floats above were
    # produced at, so a reader can still tell 75.7 from 75.70.
    return d


def ack_detail(order: Order) -> dict[str, Any]:
    """The order record an ``order.ack`` carries: the display projection
    plus the tick prices, which are canonical on the ack (S22)."""
    d = order_to_display_dict(order)
    d["price_ticks"] = order.price_ticks
    d["stop_price_ticks"] = order.stop_price_ticks
    d["trail_offset_ticks"] = order.trail_offset_ticks
    return d


def _deployed_config() -> "tuple[EngineConfig, str] | None":
    """The engine section of the deployed artifact and the artifact's text,
    from one read, if one is deployed.

    Deferred import: ``config_artifact`` imports the subsystem config modules
    to describe the artifact's shape.
    """
    from edumatcher.config_artifact import load_compiled_text

    loaded = load_compiled_text()
    return None if loaded is None else (loaded[0].engine, loaded[1])


#: Longest identifier the engine will echo from an inbound payload back into a
#: reply. Matches the `max_len` the risk spec declares for gateway_id and
#: target_gateway_id.
_MAX_WIRE_ID_LEN = 32
#: Longest command_id echoed back, matching the spec's bound.
_MAX_WIRE_COMMAND_ID_LEN = 64
#: Longest operator note echoed into an admin.action monitor record, matching
#: the `max_len` the admin spec declares for `scope.note`. Load-bearing for a
#: reason worth stating: the ack is sent *before* the monitor record, so an
#: unbounded note lets a kill switch run, answer "accepted", and then lose its
#: own audit entry to a validation error nobody sees. Design section 27.5.
_MAX_WIRE_NOTE_LEN = 256
#: Longest circuit-breaker level name quoted back in a rejection, matching the
#: `max_len` circuit_breaker.halt declares for `level`. Same load-bearing
#: reasoning as ``_clamp_wire_id``: an unknown level is quoted verbatim into a
#: `symbol_halt_ack` whose `reason` the risk spec bounds at 512, so an
#: unbounded one raises inside the ack builder and the caller gets no answer.
_MAX_WIRE_CB_LEVEL_LEN = 32


def _clamp_wire_id(value: object, limit: int = _MAX_WIRE_ID_LEN) -> str:
    """Normalise an identifier arriving from the wire, bounded and upper-cased.

    The bound is load-bearing rather than tidy. Every rejection path quotes the
    gateway it could not resolve — ``_gateway_status`` builds
    ``f"Gateway not configured: {gw_id}"`` — and since 5.3a those replies are
    generated constructors that validate, with ``reason`` bounded at 512
    characters. An inbound gateway_id of five thousand characters would
    therefore raise MessageValidationError inside the ack builder.

    The engine survives that where pm-index did not: ``_dispatch_pull_message``
    wraps every branch in a try/except. But ``_reject_after_error`` returns
    early for anything outside ``_ORDER_TOPICS``, so a risk command would send
    **no ack at all** and leave its caller waiting for a timeout — where before
    adoption it got a real, if oversized, answer. Clamping keeps the answer.

    Truncating loses nothing: an id longer than the spec allows cannot name a
    gateway that exists, so a clamped one fails the same lookup with the same
    reason.
    """
    return str(value).upper()[:limit]


def _clamp_wire_text(value: object, limit: int = _MAX_WIRE_ID_LEN) -> str:
    """Bound an inbound correlation key without changing its case.

    ``_clamp_wire_id`` upper-cases because it normalises gateway ids, which the
    engine matches against configuration. The keys this bounds are echoed back
    into a reply *topic* the caller is already waiting on, so changing their
    case would send the answer somewhere nobody is listening. The API gateway
    passes a mixed-case API key here for read-only reference callers.
    """
    return str(value)[:limit]


class Engine:
    """The matching-engine process: message loop, rule gates, and publishing.

    The actual price-time matching lives in ``OrderBook`` (one per symbol,
    held in ``self.books``).  The Engine is everything around it: it decides
    whether an order may reach a book at all (``_handle_new_order``), calls
    the book, and converts the book's answer into messages
    (``_publish_dispatch``).  See the module docstring for the walk-through.
    """

    # Minimum interval between book snapshot publishes per symbol (seconds)
    SNAPSHOT_INTERVAL = 0.5
    QUOTE_HISTORY_MAXLEN = 30
    DROP_COPY_BUFFER_SIZE = 10_000
    RECENT_TRADES_MAXLEN = 20
    DEPTH_SNAPSHOT_TOLERANCE_TICKS = 100

    def __init__(self, verbose: bool = False, config_path: str | None = None) -> None:
        # Kept for backward compatibility with existing callers/tests. Detail
        # logging is no longer gated by this flag -- it is gated by the
        # standard logging level (see main()'s -v/-vv/--log-level/-q), same
        # as every other process. This attribute currently has no effect.
        self.verbose = verbose
        self.books: dict[str, OrderBook] = {}  # symbol → OrderBook
        # Health-beacon counters (operator dashboard §8.2-§8.4). Created here,
        # with no socket, so the unit-test harness can assert on them; the
        # reporter that ships them is attached by main(), never here.
        self.metrics = EngineMetrics()
        self._reporter: HealthReporter | None = None
        self._book_metrics_interval_sec = 10.0
        self._next_book_metrics = 0.0
        self._book_metric_samples: list[MetricSample] = []
        self._running = False
        self._error_count = 0
        self._unknown_topic_count = 0
        # A fourth failure mode, distinct from the two above: the message
        # could not be decoded at all, so it has no topic to route and no
        # gateway to reject to.
        self._undecodable_count = 0
        # Every fill published, counted so a handler that raises part-way can
        # tell whether anything already printed (see _reject_after_error).
        self._fills_published = 0
        # Maintenance flushes that failed. Degraded market data is preferable
        # to an ended session, but the degradation must be visible.
        self._flush_error_count = 0
        # Monotonic timestamp of the last persistence checkpoint. Starts at 0
        # so the first tick writes one immediately rather than waiting out an
        # interval on a freshly started engine.
        self._last_persist = 0.0
        self._next_silence_check = 0.0
        # If None → no symbol restrictions (backward-compat mode)
        self._allowed_symbols: frozenset[str] | None = None
        self._allowed_fix_gateways: frozenset[str] | None = None
        self._engine_config: EngineConfig | None = None
        # Path _load_config() re-reads on POST /admin/reference/reload.
        # None when the engine was constructed from an in-memory EngineConfig
        # (tests, or the compiled-artifact fast path) rather than a file.
        self._config_path: Path | None = None
        # Compiled reference-data bundle + its content-hash version, cached
        # so GET /reference/* doesn't recompute it on every request. Rebuilt
        # on load and on a successful reload.
        self._reference_cache: dict[str, Any] | None = None
        self._reference_config_version: str | None = None
        self._gateway_descriptions: dict[str, str] = {}
        self._connected_fix_gateways: set[str] = set()
        self._sessions: dict[str, ParticipantSession] = {}
        self.quote_history_maxlen: int = self.QUOTE_HISTORY_MAXLEN
        self.drop_copy_buffer_size: int = self.DROP_COPY_BUFFER_SIZE
        self.recent_trades_maxlen: int = self.RECENT_TRADES_MAXLEN
        self.depth_snapshot_tolerance_ticks: int = self.DEPTH_SNAPSHOT_TOLERANCE_TICKS
        self._quote_index = QuoteIndex(self.quote_history_maxlen)

        # Halt state — keyed by symbol; True means halted (circuit breaker fired)
        self._halted_symbols: dict[str, bool] = {}
        # Persisted book stats — loaded once during _load_config and kept for
        # _handle_symbols_request so prev_close is available without re-reading
        self._book_stats: dict[str, dict[str, Any]] = {}
        # Price collar configs — keyed by symbol; populated in _load_config()
        self._collars: dict[str, CollarConfig] = {}
        #: What the books report beyond trades and order events, shared by
        #: every book and published by _flush_trace (S24).
        self._trace: list[tuple[Any, ...]] = []
        # Order-size / notional caps — keyed by symbol; populated in
        # _load_config(). Absent symbol means no cap is configured.
        self._order_limits: dict[str, OrderLimitsConfig] = {}
        # Circuit breaker states — keyed by symbol; populated in _load_config()
        self._circuit_breakers: dict[str, CircuitBreakerState] = {}
        # Picks the random end of every reopening call phase. Seeded from
        # config when reproducibility matters (demos, tests), from OS entropy
        # otherwise — an unpredictable reopen instant is the entire point.
        self._reopening_rng = random.Random()
        # Drop copy publisher — None until run() is called (avoids binding port 5557 in tests)
        self._drop_copy: Optional[DropCopyPublisher] = None

        # Global order_id → symbol map for O(1) cancel routing
        self._order_symbol: dict[str, str] = {}

        # Per-gateway pre-encoded ZMQ topic bytes, cached on first contact so
        # per-message frames are a dict lookup (see docs-design/perf-notes.md).
        self._topic_cache: dict[str, bytes] = {}

        # Per-symbol timestamp of last snapshot publish (for throttling)
        self._last_snapshot: dict[str, float] = {}
        # Set of symbols whose book changed since last snapshot publish
        self._dirty_symbols: set[str] = set()
        self.snapshot_interval_sec: float = self.SNAPSHOT_INTERVAL
        self.auction_indicative_interval_sec: float = 1.0
        self._last_auction_indicative: float = 0.0
        #: Uncrosses run so far this engine run (auction_id).
        self._auctions_run = 0

        # Combo-order tracking
        self._combos: dict[str, ComboOrder] = {}  # combo internal id → ComboOrder
        self._order_to_combo: dict[str, str] = {}  # child order_id → combo internal id

        # OCO-order tracking
        self._oco_groups: dict[str, list[str]] = (
            {}
        )  # oco_group_id → [order_id_1, order_id_2]
        self._order_to_oco: dict[str, str] = {}  # order_id → oco_group_id

        # Per-gateway position ledger — updated on every fill; keyed by
        # uppercase gateway_id → symbol → value.  Allows bots to resync
        # inventory state after a restart via system.position_request.
        self._gateway_positions: dict[str, dict[str, int]] = {}
        self._gateway_avg_cost: dict[str, dict[str, float]] = {}

        # Session state (auction / continuous matching)
        self._sessions_enabled: bool = False
        self._session_state: SessionState = SessionState.CONTINUOUS
        # The next scheduled transition, as told by whoever drove the last
        # one, or as the scheduler announced it (`session.next`). Empty
        # unless the scheduler supplied it -- see
        # `_handle_session_transition` for why a manual transition clears it.
        self._next_session_state: str = ""
        self._next_session_at: str = ""
        self._enforce_collars: bool = True
        self._enforce_circuit_breakers: bool = True
        self._debug_counts: defaultdict[str, int] = defaultdict(int)
        self._debug_last_summary = time.monotonic()

        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Load engine config (symbol allowlist + MM orders).
        #
        # With no explicit path the engine reads the compiled artifact, so it
        # and every gateway resolve the same defaults from the same validated
        # file. An explicit path still parses YAML directly: tests construct an
        # Engine from a fixture without compiling one first.
        deployed = _deployed_config() if config_path is None else None
        engine_config = deployed[0] if deployed is not None else None
        #: The artifact the engine runs on, verbatim (``system.startup``).
        self._config_text = deployed[1] if deployed is not None else None
        path = Path(config_path) if config_path else ENGINE_CONFIG_FILE
        if engine_config is not None or path.exists():
            try:
                self._engine_config = engine_config or load_engine_config(path)
                # Reload (POST /admin/reference/reload) re-parses this same
                # YAML file with load_engine_config(). Not offered when the
                # engine started from a compiled artifact (engine_config is
                # not None here) — that path has no single YAML file to
                # re-read; the artifact is a separate build step.
                self._config_path = path if engine_config is None else None
                self._allowed_symbols = self._engine_config.allowed_symbols
                self._allowed_fix_gateways = self._engine_config.allowed_fix_gateways
                self.metrics.set_known_gateways(self._allowed_fix_gateways)
                self._sessions_enabled = self._engine_config.sessions_enabled
                self._enforce_collars = self._engine_config.enforce_collars
                self._enforce_circuit_breakers = (
                    self._engine_config.enforce_circuit_breakers
                )
                if self._engine_config.reopening_random_seed is not None:
                    self._reopening_rng.seed(self._engine_config.reopening_random_seed)
                self.snapshot_interval_sec = self._engine_config.snapshot_interval_sec
                self.auction_indicative_interval_sec = (
                    self._engine_config.auction_indicative_interval_sec
                )
                self.quote_history_maxlen = self._engine_config.quote_history_maxlen
                self.drop_copy_buffer_size = self._engine_config.drop_copy_buffer_size
                self.recent_trades_maxlen = self._engine_config.recent_trades_maxlen
                self.depth_snapshot_tolerance_ticks = (
                    self._engine_config.depth_snapshot_tolerance_ticks
                )
                self._quote_index = QuoteIndex(self.quote_history_maxlen)
                self._gateway_descriptions = {
                    gw_id: cfg.description
                    for gw_id, cfg in self._engine_config.fix_gateways.items()
                }
                if self._sessions_enabled:
                    # Start CLOSED and wait for scheduler transitions.
                    self._session_state = SessionState.CLOSED
                log.info(
                    f"Loaded config from {path}  "
                    f"({len(self._allowed_symbols)} symbol(s): "
                    f"{', '.join(sorted(self._allowed_symbols))}; "
                    f"{len(self._allowed_fix_gateways)} gateway id(s))"
                )
                log.info(
                    "Session handling: "
                    + (
                        "enabled (startup state: CLOSED)"
                        if self._sessions_enabled
                        else "disabled"
                    )
                )
                log.info(
                    "Risk enforcement: "
                    f"collars={'on' if self._enforce_collars else 'off'}, "
                    f"circuit_breakers={'on' if self._enforce_circuit_breakers else 'off'}"
                )
                self._rebuild_reference_cache()
            except (FileNotFoundError, PermissionError) as exc:
                log.warning(
                    "Config file %s could not be read — "
                    "running without symbol restrictions. (%s)",
                    path,
                    exc,
                )
            except Exception as exc:
                log.error("FATAL: Invalid config %s: %s", path, exc)
                sys.exit(1)
        else:
            log.info(f"No config file at {path} — running without symbol restrictions.")

        try:
            self.pull_sock = make_puller(ENGINE_PULL_BIND_ADDR)
            self.pub_sock = make_publisher(ENGINE_PUB_BIND_ADDR)
        except zmq.ZMQError as exc:
            log.error(
                "FATAL: Cannot bind sockets — %s\n"
                "         Is another engine instance already running?",
                exc,
            )
            sys.exit(1)

        # Give PUB socket a moment to bind before any client can connect
        time.sleep(0.05)

    def _dbg_count(self, key: str, amount: int = 1) -> None:
        if not log.isEnabledFor(logging.DEBUG):
            return
        self._debug_counts[key] += amount
        self._flush_debug_summary()

    def _flush_debug_summary(self, force: bool = False) -> None:
        if not log.isEnabledFor(logging.DEBUG):
            return
        now = time.monotonic()
        if not force and now - self._debug_last_summary < _DEBUG_SUMMARY_INTERVAL_SEC:
            return
        if not self._debug_counts:
            self._debug_last_summary = now
            return
        summary = ", ".join(
            f"{key}={value}" for key, value in sorted(self._debug_counts.items())
        )
        log.debug("decision summary: %s", summary)
        self._debug_counts.clear()
        self._debug_last_summary = now

    def _gateway_status(self, gateway_id: str) -> tuple[bool, str]:
        """Return (is_allowed_and_connected, reason_if_not).

        The reason interpolates the gateway id, and callers put that reason on
        an ack whose ``reason`` the risk spec bounds at 512 characters — so
        the id has to be bounded before it gets here. Handlers clamp on the
        way in (``_clamp_wire_id``); this note exists because the coupling is
        not local: an unbounded id reaching this line becomes a validation
        error two calls away, in a generated ack constructor.
        """
        gw_id = gateway_id.upper()
        if self._allowed_fix_gateways is None:
            return True, ""
        if gw_id not in self._allowed_fix_gateways:
            return False, f"Gateway not configured: {gw_id}"
        session = self._sessions.get(gw_id)
        connected = (session is not None and session.connected) or (
            gw_id in self._connected_fix_gateways
        )
        if not connected:
            return False, f"Gateway not connected: {gw_id}"
        return True, ""

    @staticmethod
    def _gateway_reject_code(reason: str) -> RejectCode:
        if reason.startswith("Gateway not configured"):
            return "GATEWAY_NOT_CONFIGURED"
        return "AUTH_REQUIRED"

    def _halt_reject_code(self, symbol: str) -> RejectCode:
        """Distinguish an automatic volatility halt from a discretionary one.

        ``_halted_symbols`` is one boolean whatever caused the halt, but the
        circuit breaker already records the cause in ``halt_source`` ("CB" for
        a level trip, "ADMIN" for an operator action).  A symbol can be halted
        with no circuit breaker configured at all — the global halt-all sets
        the flag for every symbol — and that case is an operator action by
        construction, so it reads as INSTRUMENT_HALTED.
        """
        cb = self._circuit_breakers.get(symbol)
        if cb is not None and cb.halt_source == "CB":
            return "CIRCUIT_BREAKER_ACTIVE"
        return "INSTRUMENT_HALTED"

    @staticmethod
    def _cancel_reason_of(order: Order) -> CancelReason | None:
        """Narrow ``Order.cancel_reason`` to the generated ``Literal``.

        ``Order`` types the field as a plain ``str`` so that ``models.order``
        need not import the generated module, which would close an import
        cycle through ``models.message``.  The book only ever writes values
        from the spec's enum, so the cast is safe; ``make_order_cancelled``'s
        own validation is the backstop if that ever stops being true.
        """
        return cast(Optional[CancelReason], order.cancel_reason)

    @staticmethod
    def _amend_reject_code(reason: str) -> RejectCode:
        if reason == "Order not found":
            return "ORDER_NOT_FOUND"
        if reason.startswith("Cannot amend "):
            terminal = (
                "FILLED",
                "CANCELLED",
                "REJECTED",
                "EXPIRED",
            )
            if any(reason == f"Cannot amend {status} order" for status in terminal):
                return "ORDER_ALREADY_TERMINAL"
            return "AMEND_NOT_PERMITTED"
        if "quantity" in reason.lower():
            return "QTY_OUT_OF_RANGE"
        if "price" in reason.lower():
            return "PRICE_OUT_OF_RANGE"
        return "AMEND_NOT_PERMITTED"

    def _reject(
        self,
        *,
        gateway_id: str,
        order_id: str,
        code: RejectCode,
        reason: str,
        client_tag: str | None,
        request_tag: str | None,
    ) -> None:
        self.pub_sock.send_multipart(
            self._order_ack(
                gateway_id,
                order_id,
                accepted=False,
                reason=reason,
                reject_code=code,
                client_tag=client_tag,
                request_tag=request_tag,
            )
        )

    # -- the reject funnel --------------------------------------------------
    # Every order-flow ack goes through one of these four, so an
    # `accepted=False` is counted in engine.rejects exactly once, whichever of
    # the dozens of reject sites produced it (design finding F4). Admin and
    # gateway-auth acks are not order rejects and do not pass through here.
    # tests/test_engine_metrics.py forbids calling the four builders directly.

    def _order_ack(
        self,
        gateway_id: str,
        order_id: str,
        accepted: bool,
        reason: str = "",
        *,
        reject_code: RejectCode | None = None,
        client_tag: str | None = None,
        request_tag: str | None = None,
        order: dict[str, Any] | None = None,
    ) -> list[bytes]:
        # Explicit keywords, not **kwargs: this runs on every order ack, and
        # repacking a kwargs dict cost ~200 ns there (perf gate, design A4.10).
        if not accepted:
            self.metrics.count_reject(gateway_id, reject_code or reject_label(reason))
        return make_ack_msg(
            gateway_id,
            order_id,
            accepted,
            reason,
            reject_code=reject_code,
            client_tag=client_tag,
            request_tag=request_tag,
            order=order,
        )

    def _combo_ack(
        self, gateway_id: str, combo_id: str, accepted: bool, reason: str = ""
    ) -> list[bytes]:
        if not accepted:
            self.metrics.count_reject(gateway_id, reject_label(reason))
        return make_combo_ack_msg(gateway_id, combo_id, accepted, reason)

    def _oco_ack(
        self,
        gateway_id: str,
        oco_id: str,
        accepted: bool,
        reason: str = "",
        order_id_1: str = "",
        order_id_2: str = "",
    ) -> list[bytes]:
        if not accepted:
            self.metrics.count_reject(gateway_id, reject_label(reason))
        return make_oco_ack_msg(
            gateway_id, oco_id, accepted, reason, order_id_1, order_id_2
        )

    def _quote_ack(
        self,
        gateway_id: str,
        quote_id: str,
        accepted: bool,
        reason: str = "",
        bid_order_id: str = "",
        ask_order_id: str = "",
        *,
        symbol: str = "",
    ) -> list[bytes]:
        if not accepted:
            self.metrics.count_reject(gateway_id, reject_label(reason))
        return make_quote_ack_msg(
            gateway_id,
            quote_id,
            accepted,
            reason,
            bid_order_id,
            ask_order_id,
            symbol=symbol,
        )

    def _resolve_smp_action(
        self, gateway_id: str, smp_action: SmpAction | None
    ) -> SmpAction:
        """Resolve a possibly-unspecified SMP action to a concrete value.

        ``smp_action=None`` means the client omitted ``SMP=`` (or the JSON
        equivalent) entirely -- distinct from an *explicit* ``SMP=NONE``,
        which is a deliberate request to allow self-trades and must be
        respected as-is. When omitted, fall back to the order's gateway's
        configured ``participants[].smp_action`` default, or ``SmpAction.NONE``
        if the gateway has none configured (unconfigured/unknown gateway,
        or the engine is running without a loaded config). See SmpAction's
        docstring in models/order.py for the full rationale.
        """
        if smp_action is not None:
            return smp_action
        cfg = (
            self._engine_config.fix_gateways.get(gateway_id.upper())
            if self._engine_config
            else None
        )
        return cfg.smp_action if cfg is not None else SmpAction.NONE

    def _session_for_gateway(self, gateway_id: str) -> ParticipantSession:
        gw_id = gateway_id.upper()
        session = self._sessions.get(gw_id)
        if session is not None:
            return session
        session = ParticipantSession(gateway_id=gw_id)
        self._sessions[gw_id] = session
        return session

    # ------------------------------------------------------------------
    # Book access
    # ------------------------------------------------------------------

    def _book(self, symbol: str) -> OrderBook:
        if symbol not in self.books:
            book = OrderBook(symbol, recent_trades_maxlen=self.recent_trades_maxlen)
            # X3: inactivate a quote at the fill itself, inside the dispatch;
            # _publish_dispatch's later call finds it already done.
            book.on_quote_leg_fill = self._on_quote_leg_filled
            # X15: the same for an OCO leg's sibling.
            book.on_oco_leg_done = self._check_oco_after_event
            book.trace = self._trace
            self.books[symbol] = book
        return self.books[symbol]

    def _flush_auction_indicative(self) -> None:
        """Publish the indicative uncross for every symbol in a call phase.

        This is the imbalance indicator a real venue disseminates while an
        auction collects orders. The engine already computes exactly this at
        the moment a phase *ends* (`_run_uncross`) and on the circuit-breaker
        reopening path; what was missing is publishing it while there is
        still time for anyone to act on it. A participant can only supply the
        offsetting interest that resolves an imbalance if the imbalance is
        visible beforehand, and the open and the close are where the largest
        volume of the day prints (T-M1).

        Every symbol every interval, including ones that would not cross at
        all: "nothing would trade yet" is a real reading during a call phase,
        and suppressing unchanged values would leave a client unable to tell a
        stable indicative from a stalled feed.

        Halted symbols are skipped. A halt is its own reopening auction with
        its own corridor, and the circuit-breaker path already publishes an
        indicative for it — two sources describing one symbol would sooner or
        later disagree.
        """
        if not is_auction_phase(self._session_state):
            return

        now = time.monotonic()
        if now - self._last_auction_indicative < self.auction_indicative_interval_sec:
            return
        self._last_auction_indicative = now

        phase = self._session_state.value
        for symbol, book in self.books.items():
            if self._halted_symbols.get(symbol):
                continue
            indicative = compute_equilibrium(book)
            self.pub_sock.send_multipart(
                make_auction_indicative_msg(
                    symbol,
                    phase,
                    (
                        from_ticks(indicative.eq_price, symbol)
                        if indicative.eq_price is not None
                        else None
                    ),
                    indicative.eq_qty,
                    indicative.imbalance_side,
                    indicative.surplus,
                    eq_price_ticks=indicative.eq_price,
                )
            )

    def _mark_dirty(self, symbol: str) -> None:
        """Flag a symbol as needing a snapshot publish."""
        self._dirty_symbols.add(symbol)

    def _flush_snapshots(self) -> None:
        """
        Publish book snapshots for all dirty symbols whose throttle window
        has elapsed (snapshot_interval_sec seconds since last publish).
        Called once per poll loop tick.
        """
        now = time.monotonic()
        sent: set[str] = set()
        for symbol in self._dirty_symbols:
            last = self._last_snapshot.get(symbol, 0.0)
            if now - last >= self.snapshot_interval_sec:
                book = self.books.get(symbol)
                if book:
                    self.pub_sock.send_multipart(make_book_msg(symbol, book.snapshot()))
                    # Depth metrics — published alongside each book snapshot
                    depth = book.depth_snapshot(
                        tolerance_ticks=self.depth_snapshot_tolerance_ticks
                    )
                    if depth:
                        # Via the factory, not an inline encode: the two drifted
                        # apart once already, leaving make_depth_msg publishing a
                        # topic nobody subscribed to.
                        self.pub_sock.send_multipart(make_depth_msg(symbol, depth))
                self._last_snapshot[symbol] = now
                sent.add(symbol)
        self._dirty_symbols -= sent

    # ------------------------------------------------------------------
    # Config: seed stats + inject market-maker quotes
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        """Pre-create books, seed stats, inject MM quotes from engine config."""
        if not self._engine_config:
            return

        for sym, sym_cfg in self._engine_config.symbols.items():
            register_tick_decimals(sym, sym_cfg.tick_decimals)

        # Restore persisted stats first so config seeds only fill gaps
        stats = load_book_stats(BOOK_STATS_FILE)
        self._book_stats = stats
        for sym, sym_cfg in self._engine_config.symbols.items():
            book = self._book(sym)
            persisted = stats.get(sym, {})
            lbp_raw = persisted.get("last_buy_price")
            lsp_raw = persisted.get("last_sell_price")

            lbp = (
                to_ticks(float(lbp_raw), sym)
                if lbp_raw is not None
                else (
                    to_ticks(float(sym_cfg.last_buy_price), sym)
                    if sym_cfg.last_buy_price is not None
                    else None
                )
            )
            lsp = (
                to_ticks(float(lsp_raw), sym)
                if lsp_raw is not None
                else (
                    to_ticks(float(sym_cfg.last_sell_price), sym)
                    if sym_cfg.last_sell_price is not None
                    else None
                )
            )
            # X24: the last trade price comes back too (persisted as
            # prev_close); a recovery uncross that printed has the newer one.
            prev_close = persisted.get("prev_close")
            last = to_ticks(float(prev_close), sym) if prev_close is not None else None
            book.restore_stats(lbp, lsp, last)
        if stats:
            log.info(f"Restored book statistics for {len(stats)} symbol(s).")

        n_mm_quotes = 0
        for sym, sym_cfg in self._engine_config.symbols.items():
            for idx, quote_seed in enumerate(sym_cfg.market_maker_quotes, start=1):
                gateway_id = quote_seed.gateway_id

                # seed_once: skip injection if this (gateway_id, symbol) pair
                # already has an active, quote-managed entry in QuoteIndex —
                # i.e. a live quote was restored by _restore_gtc() (GTC
                # unconditionally, same-day DAY if it survived the business-
                # day check). This runs after _restore_gtc() (see run()'s
                # ordering) and after QuoteIndex has been rebuilt from
                # restored quote-origin orders, so it reflects genuinely live
                # quote state rather than "this symbol has ever traded"
                # (the previous book_stats-based check). A quote that was
                # fully hit through and removed, or that expired as a stale
                # TIF=DAY order, is correctly treated as absent here, so a
                # fresh seed fires for it — closing the gap in
                # docs-design/EduMatcher-Revised-Quote-Persistence.md §3.3.
                # See §5.4 and the ordering-dependency note in §6.1.
                already_has_quote = self._quote_index.get(gateway_id, sym) is not None
                if quote_seed.seed_once and already_has_quote:
                    log.info(
                        f"Skipping seed quote for {sym}/{gateway_id} "
                        f"(seed_once=true, an active quote was restored)"
                    )
                    continue

                quote_id = quote_seed.quote_id or f"SEED-{gateway_id}-{sym}-{idx}"

                previous = self._quote_index.remove(
                    gateway_id, sym, reason="Replaced by startup quote"
                )
                if previous:
                    self._cancel_quote_entry(
                        previous,
                        reason="Replaced by startup quote",
                        cancel_reason="QUOTE_REPLACED",
                    )

                bid = Order.create(
                    symbol=sym,
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=quote_seed.bid_qty,
                    gateway_id=gateway_id,
                    tif=quote_seed.tif,
                    price_ticks=quote_seed.bid_price_ticks,
                    is_seed=True,
                )
                ask = Order.create(
                    symbol=sym,
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=quote_seed.ask_qty,
                    gateway_id=gateway_id,
                    tif=quote_seed.tif,
                    price_ticks=quote_seed.ask_price_ticks,
                    is_seed=True,
                )
                bid.origin = OrderOrigin.QUOTE
                ask.origin = OrderOrigin.QUOTE
                bid.quote_id = quote_id
                ask.quote_id = quote_id

                self._order_symbol[bid.id] = sym
                self._order_symbol[ask.id] = sym
                self._quote_index.put(
                    QuoteEntry(
                        quote_id=quote_id,
                        gateway_id=gateway_id,
                        symbol=sym,
                        bid_order_id=bid.id,
                        ask_order_id=ask.id,
                    )
                )

                # Seeded quote legs are the one order-creation path in the
                # engine that previously published no "this order now
                # exists" event at all — _handle_new_order, _handle_quote_new,
                # OCO, and combo all ack immediately on acceptance (see the
                # ACK-before-match note below and its counterpart in
                # _handle_new_order); this loop instead went straight to
                # book.process() and only ever spoke up later, if the leg
                # filled or was rejected on entry. A subscriber that starts
                # after seeding (or, as here, simply never sees a fill for a
                # long-resting leg) has no way to learn the leg's symbol,
                # side, price, or qty until it is cancelled — by which point
                # order.cancelled's deliberately minimal shape (id, gateway,
                # client_tag, group ids only; see spec/messages/order.yaml)
                # can no longer supply them either, producing a display row
                # with every economic field blank. Publish the same ACK
                # shape every other acceptance path uses, before matching,
                # so both legs are on record from the moment they're seeded.
                # order_to_display_dict() supplies the display-money price
                # (not order.price's raw ticks) so this ack, unlike the raw
                # payload echo _handle_new_order's ack uses, is correct for
                # any symbol regardless of tick_decimals.
                for leg in (bid, ask):
                    self.pub_sock.send_multipart(
                        self._order_ack(
                            gateway_id,
                            leg.id,
                            accepted=True,
                            order=ack_detail(leg),
                        )
                    )
                # _handle_quote_new (the runtime PUSH-driven equivalent of
                # this seed loop) always follows its own pair of order acks
                # with quote.status: ACTIVE — this loop was the one quote-
                # creation path that skipped it, so a symbol seeded only at
                # startup (no live quote submissions during the session)
                # never had a quote.status event at all, leaving pm-orders'
                # quote lane empty even after the two-order-ack fix above.
                self.pub_sock.send_multipart(
                    make_quote_status_msg(gateway_id, quote_id, "ACTIVE")
                )

                now = now_ns()
                book = self._book(sym)
                # #16: seeded quotes must not cross-match if the engine starts in
                # a non-continuous phase (e.g. CLOSED) — they rest for the open.
                seed_do_match = is_matching_enabled(self._session_state)
                for quote_order in (bid, ask):
                    trades, events = book.process(
                        quote_order, match=seed_do_match, now=now
                    )
                    self._publish_dispatch(trades, events)

                self._mark_dirty(sym)
                n_mm_quotes += 1
                log.info(
                    f"MM quote {quote_id} {sym} "
                    f"bid={from_ticks(quote_seed.bid_price_ticks, sym)}"
                    f"x{quote_seed.bid_qty} "
                    f"ask={from_ticks(quote_seed.ask_price_ticks, sym)}"
                    f"x{quote_seed.ask_qty} "
                    f"gw={gateway_id}"
                )

        n_mm_combos = 0
        for combo_cfg in self._engine_config.market_maker_combos:
            combo = ComboOrder.create(
                combo_id=combo_cfg.combo_id,
                gateway_id="MM",
                combo_type=combo_cfg.combo_type,
                tif=combo_cfg.tif,
                legs=combo_cfg.legs,
            )
            if self._accept_combo(combo, publish_ack=False, is_seed=True):
                n_mm_combos += 1

        if n_mm_quotes or n_mm_combos:
            log.info(
                f"Injected {n_mm_quotes} market-maker quote(s) "
                f"and {n_mm_combos} combo(s)."
            )
            # Publish immediately on startup (bypass throttle)
            for sym in self._engine_config.symbols:
                if sym in self.books:
                    self.pub_sock.send_multipart(
                        make_book_msg(sym, self.books[sym].snapshot())
                    )

        # Wire collar and circuit breaker configs now that tick-decimals are set
        for sym, sym_cfg in self._engine_config.symbols.items():
            if sym_cfg.collar is not None:
                # Populate reference_price from the book's resolved last-buy /
                # last-sell ticks (buy side preferred). These were set above by
                # restore_stats() and already prefer persisted book_stats.json
                # over the static config seed, so the collar reference tracks
                # the most recently known price instead of a stale config value.
                book = self._book(sym)
                ref_ticks = (
                    book.last_buy_price
                    if book.last_buy_price is not None
                    else book.last_sell_price
                )
                if ref_ticks is not None:
                    sym_cfg.collar.symbol = sym
                    sym_cfg.collar.reference_price = ref_ticks
                    self._collars[sym] = sym_cfg.collar
            if sym_cfg.order_limits is not None:
                self._order_limits[sym] = sym_cfg.order_limits
            if sym_cfg.circuit_breaker is not None:
                sym_cfg.circuit_breaker.symbol = sym
                cb_state = CircuitBreakerState(
                    symbol=sym, config=sym_cfg.circuit_breaker
                )
                # Seed the breaker's reference from the same resolved last-buy /
                # last-sell price used for the collar, so the breaker is active
                # from the first order on day one (before any fills), consistent
                # with collars being active from their reference immediately.
                book = self._book(sym)
                cb_ref_ticks = (
                    book.last_buy_price
                    if book.last_buy_price is not None
                    else book.last_sell_price
                )
                if cb_ref_ticks is not None:
                    cb_state.seed_reference(cb_ref_ticks, now_ns())
                self._circuit_breakers[sym] = cb_state

    # ------------------------------------------------------------------
    # Startup — restore GTC orders
    # ------------------------------------------------------------------

    def _startup(self, run_seq: int) -> None:
        """Everything ``run`` does before serving: announce, restore, seed,
        then publish what that left in the books' trace and the collars."""
        self._announce_startup(run_seq)
        self._restore_gtc()
        self._load_config()  # seed stats + MM orders (after GTC restore)
        self._flush_trace()
        self._publish_bands()
        self._publish_checkpoints("STARTUP")

    def _publish_checkpoints(self, reason: str) -> None:
        """``system.book_checkpoint.<SYM>`` for every book: what a replay
        needs to start from here (S25)."""
        phase = self._session_state.value
        for symbol in sorted(self.books):
            self.pub_sock.send_multipart(
                make_book_checkpoint(
                    **self.books[symbol].checkpoint(), reason=reason, phase=phase
                )
            )

    def _flush_trace(self) -> None:
        """Publish the books' trace: ``order.triggered.<GW>`` for a stop that
        fired, ``engine.trace.<SYM>`` (audit only) for the rest."""
        send = self.pub_sock.send_multipart
        for rec in self._trace:
            kind = rec[0]
            if kind == "TRIGGERED":
                _, symbol, order, armed, stop, trade_id, trade_price, becomes = rec
                send(
                    make_order_triggered_unchecked(
                        gateway_id=order.gateway_id,
                        order_id=order.id,
                        symbol=symbol,
                        order_type=armed,
                        stop_price_ticks=stop,
                        trigger_trade_id=trade_id,
                        trigger_price_ticks=trade_price,
                        becomes=becomes,
                        client_tag=order.client_tag,
                    )
                )
            elif kind == "RESTED":
                send(make_engine_trace_unchecked(symbol=rec[1], kind=kind, order_id=rec[2], priority_seq=rec[3]))  # fmt: skip
            elif kind == "ICEBERG_REFILL":
                send(make_engine_trace_unchecked(symbol=rec[1], kind=kind, order_id=rec[2], priority_seq=rec[3], displayed_qty=rec[4]))  # fmt: skip
            else:  # TRAILING_RATCHET
                send(make_engine_trace_unchecked(symbol=rec[1], kind=kind, order_id=rec[2], stop_price_ticks=rec[3], last_price_ticks=rec[4]))  # fmt: skip
        self._trace.clear()

    def _publish_bands(self) -> None:
        """``risk.band.<SYM>`` for each collared symbol: the static band and
        the dynamic band's width, as ``validate_collar`` applies them."""
        for symbol, c in sorted(self._collars.items()):
            ref = c.reference_price
            self.pub_sock.send_multipart(
                make_band_unchecked(
                    symbol=symbol,
                    kind="COLLAR",
                    reference_price_ticks=ref,
                    static_low_ticks=int(ref * (1 - c.static_band_pct)),
                    static_high_ticks=int(ref * (1 + c.static_band_pct)),
                    dynamic_band_pct=c.dynamic_band_pct,
                )
            )

    def _announce_startup(self, run_seq: int) -> None:
        """Publish ``system.startup``: which engine, configuration and
        persisted state this start began from. First, before the restore
        publishes anything: an audit reader takes it as the start of a run."""
        loaded = []
        for path in (GTC_ORDERS_FILE, GTC_COMBOS_FILE, BOOK_STATS_FILE):
            try:
                data = path.read_bytes()
            except FileNotFoundError:
                loaded.append({"name": path.name, "sha256": None, "entries": 0})
                continue
            try:
                entries = len(json.loads(data))
            except ValueError, TypeError:
                entries = 0  # the restore reports what it could not read
            sha = hashlib.sha256(data).hexdigest()
            loaded.append({"name": path.name, "sha256": sha, "entries": entries})
        text = self._config_text
        self.pub_sock.send_multipart(
            make_startup_msg(
                engine_version=package_version(),
                git_commit=source_commit(),
                python_version=platform.python_version(),
                run_seq=run_seq,
                config_sha256=(
                    hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None
                ),
                config=text,
                loaded=loaded,
            )
        )

    def _restore_gtc(self) -> None:
        # M4: register tick decimals BEFORE restoring and publishing snapshots.
        # run() calls _restore_gtc() before _load_config(), so without this the
        # startup snapshots format prices with the default 2 decimals — 100x
        # off for a 4-decimal symbol.  Re-registration in _load_config is a
        # harmless no-op.
        if self._engine_config:
            for sym, sym_cfg in self._engine_config.symbols.items():
                register_tick_decimals(sym, sym_cfg.tick_decimals)

        orders = load_gtc_orders(GTC_ORDERS_FILE)
        # X26: re-queue in each book's current priority. The file lists orders
        # in first-arrival order, but an iceberg refill (or an amend that loses
        # priority) moved an order to the back of its level with a new
        # arrival_seq; restoring in file order would give it its old place.
        orders.sort(key=lambda o: (o.symbol, o.arrival_seq))
        # Business day for the TIF=DAY staleness check below: machine-local
        # calendar date, matching pm-scheduler's own notion of "today" (see
        # docs-design/EduMatcher-Revised-Quote-Persistence.md §13.3 — the
        # engine has no separate session-timezone config, so local date is
        # the deliberate simplification for this check).
        today = datetime.now().date()
        restored_count = 0
        # Real, always-on counters for system.startup_recovery below --
        # unlike _dbg_count(), which only increments under DEBUG logging and
        # so cannot be trusted as the wire-visible summary of what happened.
        discarded_stale_day_count = 0
        failed_restore_count = 0
        quote_remnant_count = 0
        rebuilt_quote_count = 0
        # Restored quote-origin orders (origin=QUOTE), collected as we go so
        # they can be regrouped into QuoteEntry objects after the loop — see
        # the QuoteIndex rebuild below. See
        # docs-design/EduMatcher-Revised-Quote-Persistence.md §5.3.
        restored_quote_legs: list[Order] = []
        restored_oco_legs: dict[str, list[Order]] = {}
        for order in orders:
            # Skip GTC orders for symbols no longer in config
            if self._allowed_symbols and order.symbol not in self._allowed_symbols:
                log.info(
                    f"Skipping GTC order {order.id[:8]} for removed symbol {order.symbol}"
                )
                continue
            # A TIF=DAY order only survives a restart within the same
            # business day — a process exit is not a day boundary (§12), but
            # a genuine calendar rollover while the process was up (or down)
            # still ends its validity, same as it always has for TIF=DAY.
            # TIF=GTC orders are never date-gated. See §13.4.
            if order.tif == TIF.DAY:
                order_day = datetime.fromtimestamp(order.ts_ns / 1e9).date()
                if order_day < today:
                    log.info(
                        f"Discarding stale TIF=DAY order {order.id[:8]} "
                        f"({order.symbol}) — order date {order_day} is before "
                        f"today ({today}); business day has rolled over since "
                        f"this order was resting"
                    )
                    self._dbg_count("stale_day_orders_discarded")
                    discarded_stale_day_count += 1
                    self.pub_sock.send_multipart(
                        make_recovery_item_msg(
                            order.id,
                            "ORDER",
                            "DISCARDED_STALE_DAY",
                            symbol=order.symbol,
                        )
                    )
                    continue
            order.status = OrderStatus.NEW
            book = self._book(order.symbol)
            # match=False: restore resting state only; do not replay execution.
            # Two crossed GTC orders saved from an auction phase would otherwise
            # silently match with no fill events or position updates.
            #
            # Guard each order so one bad record cannot abort engine startup
            # (finding C6): a persisted order that raises during restore is
            # logged and skipped rather than crashing the whole engine.
            try:
                book.process(order, match=False)
            except Exception as exc:
                log.info(
                    f"Skipping GTC order {order.id[:8]} ({order.symbol}) "
                    f"— restore failed: {exc}"
                )
                failed_restore_count += 1
                self.pub_sock.send_multipart(
                    make_recovery_item_msg(
                        order.id,
                        "ORDER",
                        "FAILED",
                        symbol=order.symbol,
                        detail=str(exc),
                    )
                )
                continue
            self._order_symbol[order.id] = order.symbol
            restored_count += 1
            log.info(f"Restored GTC order {order.id} ({order.symbol})")
            self.pub_sock.send_multipart(
                make_recovery_item_msg(
                    order.id, "ORDER", "RESTORED", symbol=order.symbol
                )
            )
            if order.origin == OrderOrigin.QUOTE and order.quote_id:
                restored_quote_legs.append(order)
            if order.oco_group_id:
                restored_oco_legs.setdefault(order.oco_group_id, []).append(order)
        # X23: re-link OCO pairs, as quotes are rebuilt below. Legs come in
        # priority order, so leg 1 (posted first) comes first. A pair with one
        # surviving leg is not re-linked: its leg rests as a plain order.
        for oco_id, legs in restored_oco_legs.items():
            if len(legs) == 2:
                self._oco_groups[oco_id] = [leg.id for leg in legs]
                for leg in legs:
                    self._order_to_oco[leg.id] = oco_id
        if restored_count:
            log.info(
                f"Restored {restored_count} resting order(s) from previous session."
            )
            # M3: restore rests orders without matching, so two crossed GTC
            # orders would leave the book crossed at startup.  Uncross each
            # book at the equilibrium price before continuous trading begins
            # -- but only if it begins now (sessions disabled). With sessions
            # the engine starts CLOSED and reaches CONTINUOUS through a
            # transition that uncrosses; a book crossed in a call phase is
            # the auction's to print, not the restart's (X25).
            if is_matching_enabled(self._session_state):
                for symbol in list(self.books.keys()):
                    self._run_uncross(symbol_filter=symbol, reason="RECOVERY")
            # Publish initial book snapshots immediately on startup
            for symbol, book in self.books.items():
                self.pub_sock.send_multipart(make_book_msg(symbol, book.snapshot()))

        # Rebuild QuoteIndex from restored quote-origin orders (GTC
        # unconditionally, same-day DAY per the staleness check above — a
        # stale DAY leg never reaches restored_quote_legs, since it `continue`s
        # out of the loop before this point). See
        # docs-design/EduMatcher-Revised-Quote-Persistence.md §5.3, §13.7.
        #
        # Group by (gateway_id, quote_id): a quote's bid and ask legs are
        # independent Order records in gtc_orders.json, so both, one, or
        # (if a corrupt record was skipped above) neither may have survived
        # to this point for a given quote_id.
        if restored_quote_legs:
            groups: dict[tuple[str, str], dict[str, Order]] = {}
            for leg in restored_quote_legs:
                key = (leg.gateway_id, leg.quote_id or "")
                groups.setdefault(key, {})[leg.side.value] = leg
            rebuilt_quotes = 0
            for (gateway_id, quote_id), legs_by_side in groups.items():
                bid = legs_by_side.get(Side.BUY.value)
                ask = legs_by_side.get(Side.SELL.value)
                if bid is not None and ask is not None:
                    entry = QuoteEntry(
                        quote_id=quote_id,
                        gateway_id=gateway_id,
                        symbol=bid.symbol,
                        bid_order_id=bid.id,
                        ask_order_id=ask.id,
                    )
                    self._quote_index.put(entry)
                    rebuilt_quotes += 1
                else:
                    # Single surviving leg: the sibling was filled, cancelled,
                    # skipped for a removed symbol, or lost to a corrupt
                    # record before this point. Per §5.3, this leg is not
                    # quote-managed going forward — it keeps resting as an
                    # ordinary order (already restored above via book.process)
                    # but is deliberately not inserted into QuoteIndex, since
                    # there is no sibling left to manage it against.
                    surviving = bid or ask
                    if surviving is not None:
                        log.info(
                            f"Restored single-leg quote remnant "
                            f"{surviving.id[:8]} ({surviving.symbol}) for "
                            f"quote_id={quote_id!r}, gateway_id={gateway_id!r} "
                            f"— resting as a plain order, not quote-managed "
                            f"(sibling leg did not restore)"
                        )
                        self._dbg_count("quote_remnants_restored")
                        quote_remnant_count += 1
                        self.pub_sock.send_multipart(
                            make_recovery_item_msg(
                                surviving.id,
                                "ORDER",
                                "QUOTE_REMNANT",
                                symbol=surviving.symbol,
                            )
                        )
            if rebuilt_quotes:
                log.info(
                    f"Rebuilt {rebuilt_quotes} active quote(s) in QuoteIndex "
                    f"from restored quote-origin orders."
                )
            rebuilt_quote_count = rebuilt_quotes

        # Restore GTC combos and rebuild parent-child links
        combos = load_gtc_combos(GTC_COMBOS_FILE)
        for combo in combos:
            self._combos[combo.id] = combo
            for child_id in combo.child_order_ids:
                self._order_to_combo[child_id] = combo.id
            # AR-0.5: load_gtc_combos() has no per-combo guard today, so every
            # combo that reaches this point restored successfully — there is
            # no failure path yet to report a different outcome for.
            self.pub_sock.send_multipart(
                make_recovery_item_msg(combo.id, "COMBO", "RESTORED")
            )
        if combos:
            log.info(f"Restored {len(combos)} GTC combo(s) from previous session.")

        # Broadcast once, unconditionally (even an all-zero restart is worth
        # a record) -- see spec/messages/system.yaml::startup_recovery. Every
        # count above previously reached only log.info/log.error, invisible
        # to pm-audit's bare PUB subscription on the engine's :5556 socket.
        self.pub_sock.send_multipart(
            make_startup_recovery_msg(
                restored_orders=restored_count,
                discarded_stale_day_orders=discarded_stale_day_count,
                failed_orders=failed_restore_count,
                quote_remnants_restored=quote_remnant_count,
                rebuilt_quotes=rebuilt_quote_count,
                restored_combos=len(combos),
            )
        )

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    def _validate_new_order(self, order: Order) -> tuple[RejectCode, str] | None:
        """Boundary validation for an inbound order (M7 / A4).

        Returns a human-readable rejection reason, or None if the order is
        acceptable.  Runs before the positive ACK so malformed orders never
        reach the book.
        """
        # A4: a duplicate order id (gateway retry / replay) would overwrite the
        # routing map and rest a second heap entry, doubling liquidity.
        if order.id in self._order_symbol:
            return "DUPLICATE_ORDER", f"Duplicate order id {order.id}"
        # M7: quantity must be positive.
        if order.quantity <= 0 or order.remaining_qty <= 0:
            return "QTY_OUT_OF_RANGE", "Quantity must be positive"
        # M7: order types that rest / price-limit must carry a positive price.
        price_required = order.order_type in (
            OrderType.LIMIT,
            OrderType.FOK,
            OrderType.STOP_LIMIT,
            OrderType.ICEBERG,
        )
        if price_required and (order.price_ticks is None or order.price_ticks <= 0):
            return (
                "PRICE_OUT_OF_RANGE",
                f"{order.order_type.value} order requires a positive price",
            )
        # M7: iceberg visible slice must be present and not exceed quantity.
        if order.order_type == OrderType.ICEBERG:
            if order.visible_qty is None or order.visible_qty <= 0:
                return "MISSING_FIELD", "ICEBERG order requires a positive visible_qty"
            if order.visible_qty > order.quantity:
                return (
                    "QTY_OUT_OF_RANGE",
                    "ICEBERG visible_qty must not exceed quantity",
                )
        # G12: pre-trade order-size and notional caps. Configured per risk
        # level with a per-symbol override; an unconfigured symbol has no cap.
        # A priceless order (MARKET, IOC) has no known notional, so only the
        # quantity cap can apply to it.
        limits = self._order_limits.get(order.symbol)
        if limits is not None:
            breach = validate_order_limits(
                order.quantity,
                (
                    from_ticks(order.price_ticks, order.symbol)
                    if order.price_ticks is not None
                    else None
                ),
                limits,
            )
            if breach is not None:
                return breach
        return None

    def _handle_new_order(self, payload: dict[str, Any]) -> None:
        """Handle one ``order.new``: gate it, ACK it, match it, publish it.

        Every order ends in exactly one of two ways, and a client must always
        learn which:

        * REJECTED -- a gate below fails.  ONE ``order.ack`` with
          ``accepted=False`` and a machine-readable reject code is sent, and
          the function returns.  The book never sees the order.
        * ACCEPTED -- an ``order.ack`` with ``accepted=True`` is sent, then
          the book matches, then fills/cancels/trades are published.

        The gates run cheapest-and-most-fundamental first, so the reject code
        a client gets names the first thing wrong with its order:

          1 gateway known + connected     5 session accepts orders?
          2 symbol is configured          6 ATO / ATC time-in-force window
          3 (book for the symbol exists)  7 symbol halted?
          4 field validation (qty, price) 8 price collar   9 can it rest?

        Stage numbers appear again as ``# [n]`` markers in the body.
        """
        # Counted before anything can reject it: this is what was submitted.
        self.metrics.order_in(payload.get("gateway_id"))
        # Wire dict -> Order object.  Prices arrive already as integer ticks.
        order = Order.from_dict(payload)
        self._dbg_count("new_order_requests")

        # SMP=None means the client omitted it -- fall back to the gateway's
        # configured default (participants[].smp_action). An explicit value
        # (including SmpAction.NONE) from the client is always respected.
        order.smp_action = self._resolve_smp_action(order.gateway_id, order.smp_action)

        # FIX gateway allowlist + connect/auth check
        # Fast-path: if gateway_id is already in _connected_fix_gateways it is
        # known-good (allowed + connected).  Only invoke _gateway_status() on
        # first contact, disconnected gateways, or backward-compat mode.
        # [1] gateway
        _gw_id_upper = order.gateway_id.upper()
        if _gw_id_upper not in self._connected_fix_gateways:
            ok, reason = self._gateway_status(order.gateway_id)
            if not ok:
                self._dbg_count("new_order_reject_gateway")
                self._reject(
                    gateway_id=order.gateway_id,
                    order_id=order.id,
                    code=self._gateway_reject_code(reason),
                    reason=reason,
                    client_tag=order.client_tag,
                    request_tag=None,
                )
                log.info(f"REJECTED {order.id[:8]} — {reason}")
                return

        # [2] Symbol allowlist check
        if self._allowed_symbols and order.symbol not in self._allowed_symbols:
            self._dbg_count("new_order_reject_symbol")
            reason = f"Symbol not configured: {order.symbol}"
            self._reject(
                gateway_id=order.gateway_id,
                order_id=order.id,
                code="UNKNOWN_SYMBOL",
                reason=reason,
                client_tag=order.client_tag,
                request_tag=None,
            )
            log.info(f"REJECTED {order.id[:8]} — symbol not configured: {order.symbol}")
            return

        # [3] Ensure the (configured) symbol's book exists even if the order is
        # about to be rejected — keeps book state observable and consistent.
        # (Books are created lazily, on first use of a symbol.)
        self._book(order.symbol)

        # M7 / A4: validate the payload at the engine boundary BEFORE the
        # positive ACK, so bad values are rejected with a reasoned NACK instead
        # of ACKing accepted=True and then crashing inside the book (swallowed
        # by the blanket handler → order silently lost) or corrupting the index.
        # [4] field validation (see _validate_new_order)
        validation_result = self._validate_new_order(order)
        if validation_result is not None:
            code, validation_error = validation_result
            self._dbg_count("new_order_reject_validation")
            self._reject(
                gateway_id=order.gateway_id,
                order_id=order.id,
                code=code,
                reason=validation_error,
                client_tag=order.client_tag,
                request_tag=None,
            )
            log.info(f"REJECTED {order.id[:8]} — {validation_error}")
            return

        # [5] Session state gating (only when trading sessions are configured;
        # without them the exchange is always open for continuous trading)
        if self._sessions_enabled and not accepts_orders(self._session_state):
            self._dbg_count("new_order_reject_session")
            self._reject(
                gateway_id=order.gateway_id,
                order_id=order.id,
                code="MARKET_CLOSED",
                reason="Market is closed",
                client_tag=order.client_tag,
                request_tag=None,
            )
            return

        # [6] ATO orders only during opening auction
        if (
            self._sessions_enabled
            and order.tif == TIF.ATO
            and self._session_state != SessionState.OPENING_AUCTION
        ):
            self._dbg_count("new_order_reject_ato_window")
            self._reject(
                gateway_id=order.gateway_id,
                order_id=order.id,
                code="SESSION_NOT_PERMITTED",
                reason="ATO orders only accepted during opening auction",
                client_tag=order.client_tag,
                request_tag=None,
            )
            return

        # ATC orders only during closing auction
        if (
            self._sessions_enabled
            and order.tif == TIF.ATC
            and self._session_state != SessionState.CLOSING_AUCTION
        ):
            self._dbg_count("new_order_reject_atc_window")
            self._reject(
                gateway_id=order.gateway_id,
                order_id=order.id,
                code="SESSION_NOT_PERMITTED",
                reason="ATC orders only accepted during closing auction",
                client_tag=order.client_tag,
                request_tag=None,
            )
            return

        book = self._book(order.symbol)
        # do_match is the pivotal flag from here on: True = continuous trading,
        # orders may trade on arrival; False = a call phase (auction), orders
        # are only queued.  It is passed straight to book.process(match=...).
        do_match = is_matching_enabled(self._session_state)

        # [7] Halt check — this symbol is halted, by the circuit breaker or by an
        # administrator.  Both set the same flag; only the reject code tells a
        # client which, so it can distinguish an automatic volatility halt it
        # should wait out from a discretionary one it should not.
        if self._halted_symbols.get(order.symbol):
            if order.order_type in (OrderType.MARKET, OrderType.FOK, OrderType.IOC):
                self._dbg_count("new_order_reject_halt")
                code = self._halt_reject_code(order.symbol)
                trigger = (
                    "circuit breaker halt"
                    if code == "CIRCUIT_BREAKER_ACTIVE"
                    else "trading halt"
                )
                reason = (
                    f"{order.symbol} is halted — "
                    f"{order.order_type.value} orders rejected during {trigger}"
                )
                self._reject(
                    gateway_id=order.gateway_id,
                    order_id=order.id,
                    code=code,
                    reason=reason,
                    client_tag=order.client_tag,
                    request_tag=None,
                )
                return
            # LIMIT / ICEBERG: accept and rest without matching (auction interest)
            do_match = False

        # [8] Price collar check — static and dynamic band protection
        # (rejects a "fat finger" price too far from a reference / last trade)
        if self._enforce_collars and order.price_ticks is not None:
            collar = self._collars.get(order.symbol)
            if collar is not None:
                result = validate_collar(
                    order.price_ticks, collar, book.last_trade_price
                )
                if result.rejected:
                    self._dbg_count("new_order_reject_collar")
                    log.debug(
                        "collar reject order_id=%s symbol=%s price=%s last_trade=%s reason=%s",
                        order.id,
                        order.symbol,
                        order.price_ticks,
                        book.last_trade_price,
                        result.reason,
                    )
                    self._reject(
                        gateway_id=order.gateway_id,
                        order_id=order.id,
                        code="COLLAR_BREACH",
                        reason=result.reason,
                        client_tag=order.client_tag,
                        request_tag=None,
                    )
                    return

        # [9] MARKET / FOK / IOC cannot rest — reject during no-matching phases
        if not do_match and order.order_type in (
            OrderType.MARKET,
            OrderType.FOK,
            OrderType.IOC,
        ):
            self._dbg_count("new_order_reject_no_match_phase")
            self._reject(
                gateway_id=order.gateway_id,
                order_id=order.id,
                code="SESSION_NOT_PERMITTED",
                reason=f"{order.order_type.value} orders not accepted during {self._session_state.value}",
                client_tag=order.client_tag,
                request_tag=None,
            )
            return

        log.info(
            f"NEW {order.id[:8]} {order.symbol} {order.side.value} "
            f"{order.order_type.value} qty={order.quantity} price={order.price_ticks}"
        )

        # ---- All gates passed: from here the order WILL be accepted. ----

        # TRAILING_STOP: compute initial stop_price from last trade if not supplied
        if order.order_type == OrderType.TRAILING_STOP:
            book = self._book(order.symbol)
            if order.stop_price_ticks is None:
                if book.last_trade_price is None:
                    self._reject(
                        gateway_id=order.gateway_id,
                        order_id=order.id,
                        code="MISSING_FIELD",
                        reason="Trailing stop requires STOP= or a prior trade price",
                        client_tag=order.client_tag,
                        request_tag=None,
                    )
                    return
                if order.side == Side.SELL:
                    order.stop_price_ticks = book.last_trade_price - order.trail_offset_ticks  # type: ignore[operator]
                else:
                    order.stop_price_ticks = book.last_trade_price + order.trail_offset_ticks  # type: ignore[operator]

        # M8: order→symbol registration happens AFTER book.process() succeeds
        # (below), not here — so a failure mid-processing leaves no half-applied
        # routing entry for an order that never reached the book.

        # M9: use the monotonic clock (now_ns) for the matching timestamp, not
        # raw time.time_ns — a wall-clock regression (e.g. an NTP step) must
        # never make event timestamps go backwards.  Since time priority is
        # driven by the engine arrival sequence (H1), this is the correct
        # source of truth for ordering; the small monotonic-guard cost is
        # acceptable on the single-threaded hot path.
        now = now_ns()

        # ---- Publish the ACK, then match. ----
        #
        # NOTE: accepted=True is published here, BEFORE book.process() runs.
        # This is the "gateway ACK" — it confirms the engine accepted the order
        # for processing (symbol valid, session open, gateway authenticated).
        # The exception is an order the book may still reject (a FOK short of
        # liquidity, _book_may_reject): its ACK is sent after process(), and
        # only if the book did not reject it -- a rejected FOK gets the one
        # accepted=False ACK of _publish_dispatch below (X5).
        #
        # Hot path: the ACK is built inline (bypassing make_ack_msg) with
        # pre-cached per-gateway topic bytes and hot attributes bound to locals
        # (see docs-design/perf-notes.md).
        _gw = order.gateway_id
        _tc = self._topic_cache
        ack_topic = _tc.get(_gw)
        if ack_topic is None:
            # First order from this gateway
            ack_topic = _tc[_gw] = topic_order_ack(_gw).encode()
        _pub = self.pub_sock
        _side_v: str = payload["side"]
        _ot_v: str = payload["order_type"]
        _tif_v: str = payload["tif"]
        # order.new carries the limit price in ticks; order.ack.price and
        # order.fill.price are both declared display_price. Every other ack and
        # the fill (order_to_display_dict, _fill_frames) convert -- this hot
        # path echoed the tick value straight through, so a 46.78 limit acked
        # and filled as 4700 on the aggressor side while the passive leg of
        # the same match reported 46.78.
        _tick_px = payload.get("price_ticks")  # None for MARKET orders
        _ack_price = (
            from_ticks(_tick_px, order.symbol) if _tick_px is not None else None
        )
        # C3 (docs-design/reviews/EduMatcher-Trader-GUI-Review.md): the ack
        # must carry the complete order record, not just price -- Replace and
        # power-user Undo need stop_price/visible_qty/trail_offset/smp_action
        # for the order types that carry them, or those actions 422 against a
        # body missing a required field (visible_qty is already plain shares,
        # not ticks, so no from_ticks conversion).
        _ack_stop_price = (
            from_ticks(order.stop_price_ticks, order.symbol)
            if order.stop_price_ticks is not None
            else None
        )
        _ack_trail_offset = (
            from_ticks(order.trail_offset_ticks, order.symbol)
            if order.trail_offset_ticks is not None
            else None
        )
        # order.smp_action was resolved to a concrete SmpAction (never None)
        # a few lines above, by the _resolve_smp_action() call this hot path
        # shares with every other order-entry point.
        _ack_smp_action = order.smp_action.value
        _ack_frames = [
            ack_topic,
            dumps(
                {
                    "order_id": order.id,
                    "accepted": True,
                    "reason": "",
                    "symbol": order.symbol,
                    "side": _side_v,
                    "order_type": _ot_v,
                    "tif": _tif_v,
                    "qty": order.quantity,
                    "price": _ack_price,
                    "stop_price": _ack_stop_price,
                    "visible_qty": order.visible_qty,
                    "trail_offset": _ack_trail_offset,
                    "price_ticks": _tick_px,
                    "stop_price_ticks": order.stop_price_ticks,
                    "trail_offset_ticks": order.trail_offset_ticks,
                    "smp_action": _ack_smp_action,
                    "client_tag": order.client_tag,
                }
            ),
        ]
        _defer_ack = _book_may_reject(order, do_match)
        if not _defer_ack:
            _pub.send_multipart(_ack_frames)
            self._dbg_count("new_order_accepted")

        # ---- THE MATCH.  Everything above is plumbing; this one call is the
        # exchange.  It trades the order against the book and returns what
        # happened.  `trades` = executions, in match order.  `events` = the
        # orders whose state changed (aggressor AND the resting orders it
        # hit), possibly with repeats -- see OrderBook.process.
        trades, events = book.process(order, match=do_match, now=now)
        if _defer_ack and order.status is not OrderStatus.REJECTED:
            _pub.send_multipart(_ack_frames)
            self._dbg_count("new_order_accepted")
        self._dbg_count("new_order_events", len(events))
        self._dbg_count("new_order_trades", len(trades))

        # M8: register the routing entry only now that the book has accepted the
        # order.  _publish_dispatch below drops it again if the order ended
        # (H7), so this must precede it.
        self._order_symbol[order.id] = order.symbol

        # ---- Publish the outcome: order.fill / order.cancelled / rejects
        # for each order in `events`, then one trade.executed per trade. ----
        self._publish_dispatch(trades, events)

        # Mark book dirty; snapshot will be published on next throttle tick
        self._dirty_symbols.add(order.symbol)

    def _rebuild_reference_cache(self) -> None:
        """(Re)build the compiled reference-data bundle and its version hash.

        Static data only — tick sizes, resolved risk levels, circuit-breaker
        ladders, schedule, index definitions. Deliberately excludes anything
        that changes during a session (prices, halts, positions): those are
        served live by the existing /symbols, /session, /halts endpoints.
        """
        engine_cfg = self._engine_config
        if engine_cfg is None:
            self._reference_cache = None
            self._reference_config_version = None
            return

        symbols: list[dict[str, Any]] = []
        for sym, sym_cfg in sorted(engine_cfg.symbols.items()):
            entry: dict[str, Any] = {
                "symbol": sym,
                "tick_decimals": int(sym_cfg.tick_decimals),
                "level": sym_cfg.level,
            }
            if sym_cfg.collar is not None:
                entry["collar"] = {
                    "static_band_pct": sym_cfg.collar.static_band_pct,
                    "dynamic_band_pct": sym_cfg.collar.dynamic_band_pct,
                }
            if sym_cfg.order_limits is not None:
                # Caps are configured per symbol and nowhere else, so these are
                # simply what the symbol declared.
                entry["order_limits"] = {
                    "max_order_qty": sym_cfg.order_limits.max_order_qty,
                    "max_order_value": sym_cfg.order_limits.max_order_value,
                }
            if sym_cfg.circuit_breaker is not None:
                entry["circuit_breaker"] = {
                    "reference_window_ns": sym_cfg.circuit_breaker.reference_window_ns,
                    "levels": [
                        {
                            "name": lvl.name,
                            "price_shift_pct": lvl.price_shift_pct,
                            "halt_duration_ns": lvl.halt_duration_ns,
                        }
                        for lvl in sym_cfg.circuit_breaker.levels
                    ],
                }
            symbols.append(entry)

        risk_levels: list[dict[str, Any]] = []
        for name, level_cfg in sorted(engine_cfg.risk_control_levels.items()):
            collar_raw = level_cfg.get("collar") or {}
            level_entry: dict[str, Any] = {"name": name}
            if collar_raw:
                level_entry["collar"] = {
                    "static_band_pct": collar_raw.get("static_band_pct"),
                    "dynamic_band_pct": collar_raw.get("dynamic_band_pct"),
                }
            risk_levels.append(level_entry)

        schedule = engine_cfg.schedule
        # Config accepts country names such as ``Sweden``, while the bounded
        # reference wire field carries an ISO alpha-2 code.
        country = _country_wire_code(engine_cfg.locale.country)
        reference: dict[str, Any] = {
            "symbols": symbols,
            "risk": {
                "default_level": engine_cfg.default_risk_level,
                "levels": risk_levels,
            },
            "indexes": [
                {
                    "id": idx.id,
                    "description": idx.description,
                    "base_value": idx.base_value,
                    "constituents": list(idx.constituents),
                }
                for idx in engine_cfg.indices
            ],
            "schedule": {
                "sessions_enabled": engine_cfg.sessions_enabled,
                "country": country,
                "schedule": _weekly_schedule_wire(schedule, engine_cfg.locale.country),
            },
        }
        digest = hashlib.sha256(
            json.dumps(reference, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
        self._reference_cache = reference
        self._reference_config_version = digest

    def _handle_reference_request(self, payload: dict[str, Any]) -> None:
        # The PULL socket is a boundary of its own (design section 22.3), and
        # this id goes straight into a spec-bounded field ahead of the reply.
        gateway_id = _clamp_wire_text(payload.get("gateway_id", ""), 64)
        # One shape, always. An engine with no config loaded used to answer
        # with `{"config_version": None}` and nothing else, which every
        # slicing endpoint compensated for with a `.get(key, {})` default.
        reference = self._reference_cache or {
            "symbols": [],
            "risk": {"default_level": None, "levels": []},
            "indexes": [],
            "schedule": {
                "sessions_enabled": False,
                "country": None,
                "schedule": None,
            },
        }
        self.pub_sock.send_multipart(
            make_reference_msg(
                gateway_id,
                symbols=reference["symbols"],
                risk=reference["risk"],
                indexes=reference["indexes"],
                schedule=reference["schedule"],
                config_version=self._reference_config_version,
            )
        )

    def _handle_reference_reload(self, payload: dict[str, Any]) -> None:
        """Re-read static reference data from disk without touching live state.

        Deliberately narrower than the startup config load: it never
        re-seeds market-maker quotes, never creates or removes order books,
        and never touches session/halt state. A reload that changed the
        symbol or index set would require doing exactly those unsafe things
        mid-session, so it is rejected rather than partially applied.
        """
        gateway_id = _clamp_wire_text(payload.get("gateway_id", ""))
        command_id = _clamp_wire_text(payload.get("command_id", ""), 64)

        if self._config_path is None:
            self.pub_sock.send_multipart(
                make_reference_reload_ack_msg(
                    gateway_id,
                    command_id,
                    accepted=False,
                    reason=(
                        "No reloadable config file "
                        "(engine started from a compiled artifact)"
                    ),
                )
            )
            return

        try:
            new_config = load_engine_config(self._config_path)
        except Exception as exc:
            self.pub_sock.send_multipart(
                make_reference_reload_ack_msg(
                    gateway_id, command_id, accepted=False, reason=str(exc)
                )
            )
            return

        old_symbols = (
            frozenset(self._engine_config.symbols)
            if self._engine_config
            else frozenset()
        )
        new_symbols = frozenset(new_config.symbols)
        old_index_ids = (
            frozenset(idx.id for idx in self._engine_config.indices)
            if self._engine_config
            else frozenset()
        )
        new_index_ids = frozenset(idx.id for idx in new_config.indices)
        if new_symbols != old_symbols or new_index_ids != old_index_ids:
            self.pub_sock.send_multipart(
                make_reference_reload_ack_msg(
                    gateway_id,
                    command_id,
                    accepted=False,
                    reason=(
                        "Reload cannot add or remove symbols/indexes mid-session "
                        "(requires a restart); the symbol/index set changed"
                    ),
                )
            )
            return

        self._engine_config = new_config
        self._rebuild_reference_cache()
        self.pub_sock.send_multipart(
            make_reference_reload_ack_msg(
                gateway_id,
                command_id,
                accepted=True,
                config_version=self._reference_config_version,
            )
        )

    def _handle_symbols_request(self, payload: dict[str, Any]) -> None:
        gateway_id = _clamp_wire_text(payload.get("gateway_id", ""))
        symbols = sorted(self.books.keys())
        engine_cfg = self._engine_config
        entries: list[dict[str, Any]] = []
        for symbol in symbols:
            # One record per instrument, carrying its own symbol. This used to
            # be a list of strings beside a `symbol_meta` map keyed by those
            # same strings, which nine readers joined back together.
            meta: dict[str, Any] = {
                "symbol": symbol,
                "tick_decimals": get_tick_decimals(symbol),
            }
            sym_cfg = engine_cfg.symbols.get(symbol) if engine_cfg else None
            if sym_cfg is not None:
                meta["tick_decimals"] = int(sym_cfg.tick_decimals)

                mm_max_spread_ticks: int | None = None
                mm_min_qty: int | None = None
                enforce_mm_obligation: bool | None = None

                gw_cfg = engine_cfg.fix_gateways.get(gateway_id) if engine_cfg else None
                if gw_cfg is not None:
                    enforce_mm_obligation = gw_cfg.enforce_mm_obligation
                    mm_max_spread_ticks = gw_cfg.mm_max_spread_ticks
                    mm_min_qty = gw_cfg.mm_min_qty

                    global_sym_policy = (
                        engine_cfg.global_symbol_mm_obligation_policies.get(symbol)
                        if engine_cfg
                        else None
                    )
                    if global_sym_policy is not None:
                        enforce_mm_obligation = global_sym_policy.enforce_mm_obligation
                        mm_max_spread_ticks = global_sym_policy.mm_max_spread_ticks
                        mm_min_qty = global_sym_policy.mm_min_qty

                    gw_sym_policy = gw_cfg.mm_obligation_policies.get(symbol)
                    if gw_sym_policy is not None:
                        enforce_mm_obligation = gw_sym_policy.enforce_mm_obligation
                        mm_max_spread_ticks = gw_sym_policy.mm_max_spread_ticks
                        mm_min_qty = gw_sym_policy.mm_min_qty

                if enforce_mm_obligation is not None:
                    meta["enforce_mm_obligation"] = enforce_mm_obligation
                if mm_max_spread_ticks is not None:
                    meta["mm_max_spread_ticks"] = mm_max_spread_ticks
                if mm_min_qty is not None:
                    meta["mm_min_qty"] = mm_min_qty

            # Previous-close reference price (float display price)
            prev_close = self._book_stats.get(symbol, {}).get("prev_close")
            if prev_close is not None:
                meta["prev_close"] = prev_close

            entries.append(meta)

        self.pub_sock.send_multipart(make_symbols_msg(gateway_id, entries))

    def _handle_session_state_request(self, payload: dict[str, Any]) -> None:
        """Return the current session state without advancing it."""
        gateway_id = _clamp_wire_id(payload.get("gateway_id", ""))
        self.pub_sock.send_multipart(
            make_session_status_msg(
                gateway_id,
                self._session_state.value,
                self._sessions_enabled,
                next_state=self._next_session_state,
                next_at=self._next_session_at,
            )
        )

    def _update_position(
        self,
        gateway_id: str,
        symbol: str,
        side_str: str,
        fill_qty: int,
        fill_price: float,
    ) -> None:
        """Update per-gateway position ledger after a fill.

        Maintains a signed net quantity per symbol and a VWAP average cost
        that resets to the fill price whenever the position crosses zero.
        """
        gw = gateway_id.upper()
        gw_pos = self._gateway_positions.setdefault(gw, {})
        gw_cost = self._gateway_avg_cost.setdefault(gw, {})

        pos = gw_pos.get(symbol, 0)
        cost = gw_cost.get(symbol, 0.0)

        if side_str == "BUY":
            new_pos = pos + fill_qty
            if pos >= 0:
                # Opening or adding to a long position
                new_cost = (cost * pos + fill_price * fill_qty) / new_pos
            elif new_pos < 0:
                # Reducing a short, still net short: avg_cost unchanged
                new_cost = cost
            elif new_pos == 0:
                # Closed the short exactly flat
                new_cost = 0.0
            else:
                # Crossed from short to long: reset cost to fill price
                new_cost = fill_price
        else:  # SELL
            new_pos = pos - fill_qty
            if pos <= 0:
                # Opening or adding to a short position
                abs_new = abs(new_pos)
                new_cost = (cost * abs(pos) + fill_price * fill_qty) / abs_new
            elif new_pos > 0:
                # Reducing a long, still net long: avg_cost unchanged
                new_cost = cost
            elif new_pos == 0:
                # Closed the long exactly flat
                new_cost = 0.0
            else:
                # Crossed from long to short: reset cost to fill price
                new_cost = fill_price

        gw_pos[symbol] = new_pos
        gw_cost[symbol] = new_cost if new_pos != 0 else 0.0

    def _handle_position_request(self, payload: dict[str, Any]) -> None:
        """Reply with a per-symbol position snapshot for the requesting gateway."""
        gateway_id = _clamp_wire_id(payload.get("gateway_id", ""))
        ok, _ = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(make_position_snapshot_msg(gateway_id, []))
            return
        gw_pos = self._gateway_positions.get(gateway_id, {})
        gw_cost = self._gateway_avg_cost.get(gateway_id, {})
        positions = [
            {
                "symbol": sym,
                "net_qty": qty,
                "avg_cost": gw_cost.get(sym, 0.0),
            }
            for sym, qty in gw_pos.items()
            if qty != 0
        ]
        self.pub_sock.send_multipart(make_position_snapshot_msg(gateway_id, positions))

    def _handle_halt_status_request(self, payload: dict[str, Any]) -> None:
        """Reply with a snapshot of all currently halted symbols."""
        gateway_id = _clamp_wire_id(payload.get("gateway_id", ""))
        halted: list[dict[str, Any]] = []
        for symbol, is_halted in self._halted_symbols.items():
            if not is_halted:
                continue
            entry: dict[str, Any] = {"symbol": symbol}
            cb = self._circuit_breakers.get(symbol)
            if cb and cb.halted:
                entry["resume_at_ns"] = cb.resume_at_ns
                entry["level"] = cb.triggered_level
                entry["halt_source"] = cb.halt_source
            halted.append(entry)
        self.pub_sock.send_multipart(make_halt_status_msg(gateway_id, halted))

    def _handle_risk_state_request(self, payload: dict[str, Any]) -> None:
        """Reply with live per-symbol risk state (ADMIN only).

        Distinct from GET /reference/risk (static, named risk-level
        definitions) and GET /admin/halts (currently-halted symbols only):
        this reports the *live* collar reference price and circuit-breaker
        state for every symbol that has one configured, halted or not.
        Prices are converted to display units; nothing here is a new piece
        of engine state, only a read of self._collars / self._circuit_breakers.
        """
        gateway_id = _clamp_wire_id(payload.get("gateway_id", ""))
        symbols: list[dict[str, Any]] = []
        symbol_names: set[str] = set(self._collars.keys()) | set(
            self._circuit_breakers.keys()
        )
        for symbol in sorted(symbol_names):
            entry: dict[str, Any] = {"symbol": symbol}
            collar = self._collars.get(symbol)
            if collar is not None:
                entry["collar_reference_price"] = (
                    from_ticks(collar.reference_price, symbol)
                    if collar.reference_price
                    else None
                )
            cb = self._circuit_breakers.get(symbol)
            if cb is not None:
                corridor = self._corridor_payload(cb, symbol)
                entry["circuit_breaker"] = {
                    "halted": cb.halted,
                    "reference_price": (
                        from_ticks(cb.reference_price, symbol)
                        if cb.reference_price is not None
                        else None
                    ),
                    "trigger_price": (
                        from_ticks(cb.trigger_price, symbol)
                        if cb.trigger_price is not None
                        else None
                    ),
                    "triggered_level": cb.triggered_level,
                    "expansion_index": cb.expansion_index,
                    # Flat, matching `circuit_breaker.halt`. This used to nest
                    # the same helper's output under a key called `corridor`,
                    # so the wire read `corridor.corridor_low` -- one producer
                    # emitting two shapes of one value.
                    **{
                        "corridor_low": corridor["corridor_low"],
                        "corridor_high": corridor["corridor_high"],
                        "corridor_expansion": corridor["expansion"],
                    },
                    "resume_at_ns": cb.resume_at_ns,
                }
            symbols.append(entry)
        self.pub_sock.send_multipart(make_risk_state_msg(gateway_id, symbols))

    def _handle_session_schedule_request(self, payload: dict[str, Any]) -> None:
        """Return the session schedule configuration from the loaded engine config."""
        gateway_id = _clamp_wire_id(payload.get("gateway_id", ""))
        schedule: dict[str, Any] | None = None
        if self._engine_config and self._engine_config.schedule:
            schedule = _weekly_schedule_wire(
                self._engine_config.schedule, self._engine_config.locale.country
            )
        self.pub_sock.send_multipart(
            make_session_schedule_msg(gateway_id, self._sessions_enabled, schedule)
        )

    def _handle_gateways_request(self, payload: dict[str, Any]) -> None:
        """Return all configured gateways with their role and connection status."""
        gateway_id = _clamp_wire_id(payload.get("gateway_id", ""))
        gateways: list[dict[str, Any]] = []
        if self._engine_config:
            for gw_id, cfg in sorted(self._engine_config.fix_gateways.items()):
                session = self._sessions.get(gw_id)
                connected = (session is not None and session.connected) or (
                    gw_id in self._connected_fix_gateways
                )
                gateways.append(
                    {
                        "id": gw_id,
                        "role": cfg.role.value,
                        "description": cfg.description,
                        "connected": connected,
                    }
                )
        self.pub_sock.send_multipart(make_gateways_msg(gateway_id, gateways))

    def _handle_volume_request(self, payload: dict[str, Any]) -> None:
        """Return daily traded volume totals per symbol and exchange-wide."""
        gateway_id = _clamp_wire_id(payload.get("gateway_id", ""))
        symbols_vol: list[dict[str, Any]] = []
        total_qty = 0
        total_value = 0.0
        total_trades = 0
        for sym, book in sorted(self.books.items()):
            symbols_vol.append(
                {
                    "symbol": sym,
                    "qty": book.daily_qty,
                    "value": round(book.daily_value, 2),
                    "trades": book.daily_trades,
                }
            )
            total_qty += book.daily_qty
            total_value += book.daily_value
            total_trades += book.daily_trades
        self.pub_sock.send_multipart(
            make_volume_msg(
                gateway_id,
                symbols_vol,
                total_qty,
                round(total_value, 2),
                total_trades,
            )
        )

    def _handle_gateway_connect(self, payload: dict[str, Any]) -> None:
        gateway_id = str(payload.get("gateway_id", "")).upper()
        if not gateway_id:
            return

        session = self._session_for_gateway(gateway_id)

        if session.connected:
            # A second live connection under the same ID would share one
            # session, so either one dropping would run the disconnect
            # behaviour (CANCEL_ALL) against the other's orders.
            self.metrics.count(self.metrics.auth_rejects, gateway_id)
            self.pub_sock.send_multipart(
                make_gateway_auth_msg(
                    gateway_id,
                    accepted=False,
                    reason=f"Gateway already connected: {gateway_id}",
                )
            )
            log.info(f"REFUSED gateway connect (already connected): {gateway_id}")
            return

        if self._allowed_fix_gateways is None:
            # Backward-compat mode: no gateway restrictions
            self._connected_fix_gateways.add(gateway_id)
            session.connected = True
            self.metrics.count(self.metrics.connects, gateway_id)
            self.pub_sock.send_multipart(
                make_gateway_auth_msg(gateway_id, accepted=True)
            )
            return

        if gateway_id not in self._allowed_fix_gateways:
            self.metrics.count(self.metrics.auth_rejects, gateway_id)
            self.pub_sock.send_multipart(
                make_gateway_auth_msg(
                    gateway_id,
                    accepted=False,
                    reason=f"Gateway not configured: {gateway_id}",
                )
            )
            log.info(f"REFUSED gateway connect: {gateway_id}")
            return

        cfg = (
            self._engine_config.fix_gateways[gateway_id]
            if self._engine_config
            else None
        )
        if cfg:
            session.role = cfg.role
            session.disconnect_behaviour = cfg.disconnect_behaviour

        self._connected_fix_gateways.add(gateway_id)
        session.connected = True
        self.metrics.count(self.metrics.connects, gateway_id)
        self.pub_sock.send_multipart(
            make_gateway_auth_msg(
                gateway_id,
                accepted=True,
                description=self._gateway_descriptions.get(gateway_id, ""),
            )
        )
        desc = self._gateway_descriptions.get(gateway_id, "")
        if desc:
            log.info(f"Gateway connected: {gateway_id} — {desc}")
        else:
            log.info(f"Gateway connected: {gateway_id}")

    def _handle_book_snapshot_request(self, payload: dict[str, Any]) -> None:
        symbol = payload.get("symbol", "").upper()
        if symbol in self.books:
            self.pub_sock.send_multipart(
                make_book_msg(symbol, self.books[symbol].snapshot())
            )
        # If symbol unknown (no orders yet), there is nothing to send;
        # the viewer will get its first update when the first order arrives.

    def _handle_orders_request(self, payload: dict[str, Any]) -> None:
        gateway_id = str(payload.get("gateway_id", "")).upper()
        ok, _ = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(make_orders_msg(gateway_id, []))
            return
        orders: list[dict[str, Any]] = []
        for book in self.books.values():
            for order in book.resting_orders():
                if order.gateway_id == gateway_id:
                    orders.append(order_to_display_dict(order))
        self.pub_sock.send_multipart(make_orders_msg(gateway_id, orders))

    def _handle_price_level_orders_request(self, payload: dict[str, Any]) -> None:
        """ADMIN -> engine: every resting order for one symbol, across every
        gateway, optionally narrowed to a single price level.

        book.* and order.orders_request only ever expose the aggregate
        {price, qty, count} per level — never which orders, from which
        gateways, make it up. This is the admin-only, all-gateway analogue
        of order.orders_request (which is deliberately single-gateway, so
        an ordinary participant never sees another's resting orders); it
        exists for pm-admin's LEVEL command. See spec/messages/order.yaml's
        price_level_orders_request/price_level_orders for the wire
        contract this implements.

        Ordered by price (best-to-worst for the side isn't meaningful
        across a mixed bid/ask result, so this sorts plain ascending by
        price) then by arrival_seq within a price level, so time priority
        — which order would fill first if this level traded — is visible
        without the caller having to re-sort.
        """
        gateway_id = _clamp_wire_id(payload.get("gateway_id", ""))
        symbol = _clamp_wire_id(payload.get("symbol", ""), 16)

        def _reject(reason: str) -> None:
            self.pub_sock.send_multipart(
                make_price_level_orders_msg(
                    gateway_id,
                    symbol,
                    [],
                    price=payload.get("price"),
                    rejected=True,
                    reason=reason,
                )
            )

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            _reject(reason)
            return

        session = self._session_for_gateway(gateway_id)
        if session.role != ParticipantRole.ADMIN:
            _reject(
                "Price-level order composition is only allowed for ADMIN "
                "participants"
            )
            return

        book = self.books.get(symbol)
        if book is None:
            _reject(f"Unknown symbol: {symbol}")
            return

        price_filter = payload.get("price")
        price_ticks: int | None = None
        if price_filter is not None:
            price_ticks = to_ticks(float(price_filter), symbol)

        matching = [
            order
            for order in book.resting_orders()
            if price_ticks is None or order.price_ticks == price_ticks
        ]
        matching.sort(
            key=lambda o: (
                o.price_ticks if o.price_ticks is not None else 0,
                o.arrival_seq,
            )
        )

        orders = []
        for order in matching:
            display = order_to_display_dict(order)
            display["gateway_id"] = order.gateway_id
            orders.append(display)

        self.pub_sock.send_multipart(
            make_price_level_orders_msg(gateway_id, symbol, orders, price=price_filter)
        )

    def _handle_quote_bootstrap_request(self, payload: dict[str, Any]) -> None:
        gateway_id = _clamp_wire_id(payload.get("gateway_id", ""))
        symbol_filter = _clamp_wire_id(payload.get("symbol", ""), 16)

        ok, _ = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(make_quote_bootstrap_msg(gateway_id, []))
            return

        order_by_id: dict[str, Order] = {}
        for book in self.books.values():
            for order in book.resting_orders():
                order_by_id[order.id] = order

        entries = self._quote_index.entries_for_gateway(gateway_id)
        if symbol_filter:
            entries = [e for e in entries if e.symbol == symbol_filter]

        quotes: list[dict[str, Any]] = []
        for entry in entries:
            bid = order_by_id.get(entry.bid_order_id)
            ask = order_by_id.get(entry.ask_order_id)
            if bid is None and ask is None:
                continue

            quotes.append(
                {
                    "quote_id": entry.quote_id,
                    "gateway_id": entry.gateway_id,
                    "symbol": entry.symbol,
                    "state": entry.state.value,
                    "bid_order_id": entry.bid_order_id,
                    "ask_order_id": entry.ask_order_id,
                    "bid_price": (
                        from_ticks(bid.price_ticks, bid.symbol)
                        if bid is not None and bid.price_ticks is not None
                        else None
                    ),
                    "ask_price": (
                        from_ticks(ask.price_ticks, ask.symbol)
                        if ask is not None and ask.price_ticks is not None
                        else None
                    ),
                    "bid_qty": bid.quantity if bid is not None else 0,
                    "ask_qty": ask.quantity if ask is not None else 0,
                    "bid_remaining_qty": bid.remaining_qty if bid is not None else 0,
                    "ask_remaining_qty": ask.remaining_qty if ask is not None else 0,
                    "bid_status": bid.status.value if bid is not None else "MISSING",
                    "ask_status": ask.status.value if ask is not None else "MISSING",
                }
            )

        self.pub_sock.send_multipart(make_quote_bootstrap_msg(gateway_id, quotes))

    def _handle_quote_legs_request(self, payload: dict[str, Any]) -> None:
        """Reply to a QLEGS snapshot request with the gateway's quote legs.

        ``ACTIVE`` legs come straight from ``QuoteIndex`` plus each leg's
        live order state (qty, remaining, status) — unchanged from before.

        ``RECENT``/``ALL`` are now served from ``QuoteIndex``'s bounded
        per-gateway history of recently-removed quotes (see
        ``QuoteIndex.recent_for_gateway``), populated at every point a quote
        is inactivated (fill, cancel, disconnect, kill switch, circuit
        breaker halt, etc.). This history is a *quote-level* summary, not a
        per-leg one: once an order leaves the book its live qty/remaining/
        status are no longer available anywhere in the engine, so recent
        rows report the quote's identity, final state, removal reason, and
        removal time instead of reconstructing per-leg fill detail. The
        history is in-memory only, bounded, and does not survive an engine
        restart — see ../../../docs/books/operator-guide/part-6-observe-and-recover/010-persistence.md.

        ``complete`` is ``True`` whenever the reply honestly reflects what
        was asked for: ``ACTIVE`` is always complete, and ``RECENT``/``ALL``
        are now complete too (subject to the history buffer's bound — very
        old inactivations may have been evicted).
        """
        gateway_id = _clamp_wire_id(payload.get("gateway_id", ""))
        symbol_filter = str(payload.get("symbol", "")).upper()
        show = str(payload.get("show", "ACTIVE")).upper() or "ACTIVE"

        ok, _ = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                make_quote_legs_msg(gateway_id, [], show_requested=show, complete=True)
            )
            return

        legs: list[dict[str, Any]] = []
        if show in ("ACTIVE", "ALL"):
            legs = self._active_quote_legs(gateway_id, symbol_filter)

        recent: list[dict[str, Any]] = []
        if show in ("RECENT", "ALL"):
            recent = self._recent_quote_legs(gateway_id, symbol_filter)

        self.pub_sock.send_multipart(
            make_quote_legs_msg(
                gateway_id,
                legs,
                show_requested=show,
                complete=True,
                recent=recent,
            )
        )

    def _active_quote_legs(
        self, gateway_id: str, symbol_filter: str
    ) -> list[dict[str, Any]]:
        """Build the ACTIVE leg rows for one gateway (unchanged behavior)."""
        order_by_id: dict[str, Order] = {}
        for book in self.books.values():
            for order in book.resting_orders():
                order_by_id[order.id] = order

        entries = self._quote_index.entries_for_gateway(gateway_id)
        if symbol_filter:
            entries = [e for e in entries if e.symbol == symbol_filter]

        legs: list[dict[str, Any]] = []
        for entry in entries:
            for leg_side, order_id in (
                ("BUY", entry.bid_order_id),
                ("SELL", entry.ask_order_id),
            ):
                leg_order = order_by_id.get(order_id)
                if leg_order is None:
                    continue
                legs.append(
                    {
                        "quote_id": entry.quote_id,
                        "order_id": leg_order.id,
                        "symbol": entry.symbol,
                        "leg_side": leg_side,
                        "price": (
                            from_ticks(leg_order.price_ticks, entry.symbol)
                            if leg_order.price_ticks is not None
                            else None
                        ),
                        "qty": leg_order.quantity,
                        "remaining": leg_order.remaining_qty,
                        "filled": leg_order.quantity - leg_order.remaining_qty,
                        "status": leg_order.status.value,
                        "quote_status": entry.state.value,
                    }
                )
        return legs

    @staticmethod
    def _leg_snapshot_to_dict(
        leg: Optional[QuoteLegSnapshot],
    ) -> Optional[dict[str, Any]]:
        if leg is None:
            return None
        return {
            "order_id": leg.order_id,
            "price": leg.price,
            "qty": leg.qty,
            "remaining": leg.remaining,
            "filled": leg.filled,
            "status": leg.status,
        }

    def _recent_quote_legs(
        self, gateway_id: str, symbol_filter: str
    ) -> list[dict[str, Any]]:
        """Build RECENT rows from QuoteIndex's bounded inactivation history.

        Quote-level summary fields (see `_handle_quote_legs_request`
        docstring), most-recently-removed first, plus per-leg detail
        (`bid_leg`/`ask_leg`) when available.

        `QuoteEntry.state` is never mutated after creation (it is always
        the `ACTIVE` it started as), so it cannot be used to report a
        removed quote's final status. Instead, the final `quote_status` is
        derived from `reason`: fill-driven removals pass one of the
        `INACTIVE_*_FILLED` values as `reason` (see `_on_quote_leg_filled`),
        so that value doubles as the status; every other removal path is a
        cancellation of one kind or another (participant cancel, kill
        switch, disconnect, circuit breaker halt, replaced by a new quote,
        ...), so it is reported as `CANCELLED`.

        `bid_leg`/`ask_leg` carry each leg's final `order_id`/`qty`/
        `remaining`/`filled`/`status` at the moment its quote was removed,
        captured via `QuoteIndex.attach_leg_snapshots` (see
        `Engine._cancel_quote_entry` and `Engine._on_quote_leg_filled`).
        They are `None` on the rare entry recorded before its cancellation
        completed (e.g. process interrupted mid-cancel) — callers should
        treat a `None` leg as "detail unavailable," not "leg had no fill."
        """
        history = self._quote_index.recent_for_gateway(gateway_id, symbol_filter)
        fill_reasons = {
            QuoteState.INACTIVE_BID_FILLED.value,
            QuoteState.INACTIVE_ASK_FILLED.value,
        }
        return [
            {
                "quote_id": h.entry.quote_id,
                "symbol": h.entry.symbol,
                "bid_order_id": h.entry.bid_order_id,
                "ask_order_id": h.entry.ask_order_id,
                "quote_status": (
                    h.reason if h.reason in fill_reasons else QuoteState.CANCELLED.value
                ),
                "reason": h.reason,
                "removed_at_ns": h.removed_at_ns,
                "bid_leg": self._leg_snapshot_to_dict(h.bid_leg),
                "ask_leg": self._leg_snapshot_to_dict(h.ask_leg),
            }
            for h in history
        ]

    def _cancel_order_by_id(
        self,
        order_id: str,
        *,
        cancel_reason: CancelReason | None = None,
        command_id: str = "",
    ) -> Optional[Order]:
        """Cancel a resting order by id.

        Returns the cancelled `Order` (reflecting its final qty/remaining/
        status at the moment of cancellation) so callers that need that
        detail — e.g. quote-leg history snapshots, see
        `_snapshot_quote_leg` — don't have to re-derive it. Returns `None`
        if the order could not be found or was already terminal; callers
        that only care about success/failure can keep using this as a
        truthy check, same as the previous `bool` return.

        `cancel_reason`/`command_id` say *why* the exchange decided to cancel
        this order and, when the decision traces back to an admin/kill-switch
        command, which one — every caller here is an engine-initiated cancel
        (self-match-prevention and insufficient-liquidity cancels take a
        different, inline publish path — see `_cancel_reason_of`), and before
        this the two were silently dropped, leaving order.cancelled unable to
        answer "why was this cancelled" for a kill switch, an admin
        cancel-symbol, a gateway disconnect, a circuit-breaker halt, a quote
        replacement, or a quote leg cancelled because its sibling filled.
        """
        symbol = self._order_symbol.get(order_id)
        book = self.books.get(symbol) if symbol else None
        cancelled = book.cancel_order(order_id) if book else None
        if not cancelled:
            return None
        self._order_symbol.pop(order_id, None)
        self._mark_dirty(cancelled.symbol)
        # L8: echo the order's client_tag on the cancel so subscribers that
        # correlate on it don't miss quote/combo-driven cancels.
        self.pub_sock.send_multipart(
            make_cancelled_msg(
                cancelled.gateway_id,
                order_id,
                client_tag=cancelled.client_tag,
                order=cancelled.to_dict(),
                cancel_reason=cancel_reason,
                command_id=command_id or None,
            )
        )
        return cancelled

    @staticmethod
    def _snapshot_quote_leg(order: Optional[Order]) -> Optional[QuoteLegSnapshot]:
        """Build a `QuoteLegSnapshot` from a (possibly already-terminal)
        `Order`, or `None` if there is nothing to snapshot (e.g. the order
        was already gone before cancellation was attempted).

        `price` is converted to display money here, the same conversion
        `_active_quote_legs` applies, so a RECENT row and an ACTIVE row for
        the same leg report the same number. It is recorded at removal
        because the order is gone afterwards and its price is then
        unrecoverable from anywhere in the engine.
        """
        if order is None:
            return None
        return QuoteLegSnapshot(
            order_id=order.id,
            qty=order.quantity,
            remaining=order.remaining_qty,
            filled=order.quantity - order.remaining_qty,
            status=order.status.value,
            price=(
                from_ticks(order.price_ticks, order.symbol)
                if order.price_ticks is not None
                else None
            ),
        )

    def _cancel_quote_entry(
        self,
        entry: QuoteEntry,
        reason: str = "",
        *,
        cancel_reason: CancelReason | None = None,
        command_id: str = "",
    ) -> list[str]:
        """Cancel both legs of *entry*, returning the order ids actually
        cancelled (0, 1 or 2 of them — a leg already gone, e.g. filled or
        cancelled some other way, contributes nothing).

        AR-0.5: this used to return a bare ``int`` count. Every caller that
        built a risk-ack's ``cancelled_quotes`` from that count now also
        needs the ids behind it, so the return value carries both — the
        count is simply ``len()`` of what comes back, preserving the "a
        count that disagrees with its own list is itself a detectable
        defect" property the id lists exist for.
        """
        cancelled_ids: list[str] = []
        bid_order = self._cancel_order_by_id(
            entry.bid_order_id, cancel_reason=cancel_reason, command_id=command_id
        )
        if bid_order is not None:
            cancelled_ids.append(bid_order.id)
        ask_order = self._cancel_order_by_id(
            entry.ask_order_id, cancel_reason=cancel_reason, command_id=command_id
        )
        if ask_order is not None:
            cancelled_ids.append(ask_order.id)
        # entry has already been popped from the active QuoteIndex and its
        # quote-level history recorded by the caller (remove()/
        # cancel_all_for_*()) before _cancel_quote_entry runs — attach the
        # per-leg detail we just captured to that already-recorded entry.
        # See QuoteIndex.attach_leg_snapshots and
        # docs-design/EduMatcher-QLEGS-RECENT.md §9.3.
        self._quote_index.attach_leg_snapshots(
            entry.gateway_id,
            entry.quote_id,
            self._snapshot_quote_leg(bid_order),
            self._snapshot_quote_leg(ask_order),
        )
        self.pub_sock.send_multipart(
            make_quote_status_msg(
                entry.gateway_id,
                entry.quote_id,
                "CANCELLED",
                reason,
                command_id=command_id or None,
            )
        )
        return cancelled_ids

    def _cancel_orphaned_quote_legs(self, gateway_id: str, symbol: str) -> int:
        """Cancel any resting quote-origin order(s) for this gateway/symbol
        that are no longer tracked by an active ``QuoteIndex`` entry.

        This is the fallback half of ``_handle_quote_new``'s replace-in-slot
        cleanup (see its call site). It exists because
        ``_on_quote_leg_filled`` (``INACTIVATE_ON_ANY_FILL``) removes the
        ``QuoteIndex`` entry at fill time but deliberately leaves a
        *partially* filled hit leg resting — by design, that remainder stays
        live until a new quote actually replaces it, not until the fill
        happens. When no ``QuoteIndex`` entry is found on replace, this is
        the only remaining place that can find and clear such a leftover:
        it looks the gateway's resting quote-origin order(s) up directly via
        ``OrderBook.quote_orders_for_gateway`` — an O(k) index lookup (k =
        this gateway's resting quote legs in this book, at most 2) — rather
        than trusting ``QuoteIndex`` bookkeeping that has already been
        popped, and rather than scanning every resting order in the book.
        See ../../../docs/books/architecture-and-development/part-1-architecture/020-guided-tour.md §10 for the index's
        full rationale.

        Ordinary orders (``origin=ORDER``) are never touched here — this
        mirrors ``_handle_gateway_disconnect``'s ``CANCEL_ALL`` sweep, which
        excludes quote-origin orders for the same reason in reverse (it
        expects `QuoteIndex`-driven cancellation to handle those instead).
        """
        book = self.books.get(symbol)
        if book is None:
            return 0
        cancelled = 0
        for order in list(book.quote_orders_for_gateway(gateway_id)):
            if (
                self._cancel_order_by_id(order.id, cancel_reason="QUOTE_REPLACED")
                is not None
            ):
                cancelled += 1
        return cancelled

    def _publish_trade(self, trade: Any) -> None:
        """Publish ONE trade and run every side effect a trade has.

        Called once per ``Trade`` from ``_publish_dispatch`` -- the single
        funnel for all executions (new orders, quotes, combos, OCO, auctions,
        stop cascades).  Side effects, in order: ``trade.executed`` on the
        bus; fill counters; both counterparties' position ledgers; the drop
        copy (clearing/risk) feed; and the circuit-breaker check, which may
        halt the symbol as a consequence of this very trade.
        """
        # Generated from spec/messages/trade.yaml. The field list used to be a
        # dict literal here, which meant adding a field to trade.executed took
        # three coordinated edits (this function, feed_schema, the reference
        # docs) and reached the C clients not at all. It now takes one edit to
        # the spec. Costs ~0.6 µs/trade against the literal; see
        # docs-design/perf-notes.md and ../../../docs/books/architecture-and-development/part-4-developing/040-message-generation.md.
        #
        # The *unchecked* constructor: this is a measured hot path and the
        # engine is the authority on its own trades. Every other producer uses
        # the validating make_trade_executed.
        self.pub_sock.send_multipart(
            # Trade.to_wire() owns the two model->wire conversions (ticks to
            # display money, timestamp to ts_ns) so no caller has to remember
            # them. Same fields, same values, same bytes as the hand-written
            # kwargs it replaces.
            make_trade_executed_unchecked(**trade.to_wire())
        )
        # #10: update BOTH counterparties' position ledgers for every trade,
        # right here in the single trade-publication path — so fills produced
        # by any flow (new order, quote, combo, OCO leg, auction uncross,
        # stop cascade, amend rematch) are reflected in system.position_request.
        # Callers must NOT also call _update_position or positions double-count.
        # Raw ids, plain dict increments: this is the trade hot path, and
        # both ids belong to orders that already passed the gateway checks,
        # so they need no canonicalising here -- counter_samples() maps them
        # to labels when the beacon is built (perf gate, design A4.10).
        fills = self.metrics.fills
        buy, sell = trade.buy_gateway_id, trade.sell_gateway_id
        fills[buy] = fills.get(buy, 0) + 1
        fills[sell] = fills.get(sell, 0) + 1
        _trade_px = from_ticks(trade.price, trade.symbol)
        self._update_position(
            trade.buy_gateway_id, trade.symbol, "BUY", trade.quantity, _trade_px
        )
        self._update_position(
            trade.sell_gateway_id, trade.symbol, "SELL", trade.quantity, _trade_px
        )

        # H4: feed the drop-copy (clearing/risk) feed from this single trade
        # path so EVERY fill reaches it — quote, combo, OCO, and auction fills
        # were previously invisible because drop copy was only wired into the
        # new-order loop.  One record per counterparty per execution.
        # M13: derive the liquidity flag from the aggressor side instead of
        # hard-coding MAKER — the taker side is the aggressor.
        if self._drop_copy is not None:
            _agg = trade.aggressor_side
            for _gw, _oid, _sd in (
                (trade.buy_gateway_id, trade.buy_order_id, "BUY"),
                (trade.sell_gateway_id, trade.sell_order_id, "SELL"),
            ):
                self._drop_copy.publish_fill(
                    gateway_id=_gw,
                    order_id=_oid,
                    trade_ids=[trade.id],
                    symbol=trade.symbol,
                    fill_qty=trade.quantity,
                    fill_price=_trade_px,
                    liquidity_flag="TAKER" if _sd == _agg else "MAKER",
                )

        # Circuit breaker monitor — check if this fill triggered a halt.
        # Inline the null-guard to skip the function-call overhead entirely
        # when no circuit breaker is configured for the symbol.
        if self._enforce_circuit_breakers:
            _cb = self._circuit_breakers.get(trade.symbol)
            if _cb is not None:
                self._check_circuit_breaker(trade.symbol, trade.price, trade.ts_ns)

    @staticmethod
    def _executions(trades: list[Trade]) -> dict[str, _Execution]:
        """Each order's execution in THIS dispatch, from *trades*, in one pass.

        ``order.fill.fill_qty`` is specified as "quantity matched in this
        event, not cumulatively" (spec/messages/order.yaml): the trades of
        this dispatch that touched the order, which needs no before-state --
        ``quantity - remaining_qty`` is the running total, and a resting order
        hit a second time reported it again. The notional is summed in integer
        ticks and divided once, so the VWAP is correctly rounded: summed in
        display floats, 23 @ 108.67 came back as 108.66999999999999. The trade
        ids, in match order, let a consumer join a private fill to the public
        tape. The flag is the drop copy's derivation (M13): the aggressor side
        of a trade is TAKER.
        """
        out: dict[str, _Execution] = {}
        for t in trades:
            agg = t.aggressor_side
            for oid, side in ((t.buy_order_id, "BUY"), (t.sell_order_id, "SELL")):
                ex = out.get(oid)
                if ex is None:
                    ex = out[oid] = _Execution("TAKER" if side == agg else "MAKER")
                ex.qty += t.quantity
                ex.notional += t.price * t.quantity
                ex.trade_ids.append(t.id)
        return out

    def _book_reject(self, symbol: str, do_match: bool) -> tuple[RejectCode, str]:
        """Code and reason for an order ``book.process(match=do_match)`` rejects.

        With matching on, only a FOK short of liquidity is rejected. With it
        off, a MARKET/IOC/FOK cannot rest, and the reason is why matching is
        off -- as gate 8 and the phase gate of ``_handle_new_order`` say for
        an ordinary order (X12a). An AON combo blocked by a short leg is the
        remaining case: a liquidity shortfall again.
        """
        if not do_match:
            if self._halted_symbols.get(symbol):
                return self._halt_reject_code(symbol), f"{symbol} is halted"
            if not is_matching_enabled(self._session_state):
                return (
                    "SESSION_NOT_PERMITTED",
                    f"Orders that cannot rest are not accepted during "
                    f"{self._session_state.value}",
                )
        return _NO_LIQUIDITY

    def _publish_dispatch(
        self,
        trades: list[Trade],
        events: list[Order],
        reject: tuple[RejectCode, str] = _NO_LIQUIDITY,
    ) -> None:
        """Publish what one ``book.process()`` -- or an uncross -- did.

        Every path that matches calls this, so none can drift from the others
        again (X8d: seven copies had, each missing a different follow-up).
        ``events`` repeats an order once per level it swept, every copy in
        its final state, so each order is handled once:

        - an ``order.fill`` if it executed here, whatever its final status
          (X1: an IOC can fill and then be cancelled), then the quote refresh
          policy (X3; the uncross's only call, X8b);
        - ``order.cancelled``, or the reject *reject* (X12a), if it ended so;
        - the combo follow-up, and for an order that ended the OCO follow-up
          and the drop of its routing entry (H7). The book has already pulled
          an OCO sibling inside the dispatch (X15); here it is a no-op unless
          nothing in the book saw the end.

        Then the trades, which update both positions (H3).

        This is where the book's in-memory answer (``trades``, ``events``)
        becomes bus traffic.  Two things to hold on to:

        * PER ORDER messages (``order.fill``, ``order.cancelled``, reject)
          are private: the topic contains the owning gateway's id.  They go
          out first, one set per distinct order.
        * PER TRADE messages (``trade.executed``) are public and go out last.
          A participant therefore learns of its own fill slightly before the
          public tape shows it.
        """
        # Step 0: what the book did on the way -- a stop that fired, an order
        # that rested -- before the fills it explains.
        if self._trace:
            self._flush_trace()
        # Step 1: collapse the trade list into "what did each order execute
        # in total", so a sweep that hit 5 resting orders gives the aggressor
        # ONE order.fill (qty summed, VWAP price) and each resting order its own.
        executed = self._executions(trades)
        send = self.pub_sock.send_multipart
        seen: set[str] = set()
        # Step 2: one pass over the events, handling each order exactly once.
        for evt in events:
            oid = evt.id
            if oid in seen:
                continue  # the same Order, listed again after a later fill
            seen.add(oid)
            status = evt.status
            ex = executed.get(oid)
            if ex is not None:
                self._fills_published += 1
                send(self._fill_frames(evt, ex))
                if evt.quote_id is not None:
                    self._on_quote_leg_filled(evt)
            if status is OrderStatus.CANCELLED:
                send(
                    make_order_cancelled_unchecked(
                        gateway_id=evt.gateway_id,
                        order_id=oid,
                        symbol=evt.symbol,
                        client_tag=evt.client_tag,
                        cancel_reason=self._cancel_reason_of(evt),
                        remaining_qty=evt.remaining_qty,
                        cum_qty=evt.quantity - evt.remaining_qty,
                        oco_group_id=evt.oco_group_id,
                        combo_parent_id=evt.combo_parent_id,
                        quote_id=evt.quote_id,
                        leg_index=evt.leg_index,
                    )
                )
                log.info(f"CANCEL {oid[:8]} ({evt.gateway_id})")
            elif status is OrderStatus.REJECTED:
                self._reject(
                    gateway_id=evt.gateway_id,
                    order_id=oid,
                    code=reject[0],
                    reason=reject[1],
                    client_tag=evt.client_tag,
                    request_tag=None,
                )
            if evt.combo_parent_id is not None and status is not OrderStatus.NEW:
                self._check_combo_after_child_event(evt)
            if status in _ENDED_STATUSES:
                if evt.oco_group_id is not None:
                    self._check_oco_after_event(evt)
                self._order_symbol.pop(oid, None)

        # Step 3: the public tape, in the order the trades happened.
        for trade in trades:
            log.info(
                f"TRADE {trade.id[:8]} {trade.symbol} "
                f"qty={trade.quantity} @{trade.price}"
            )
            self._publish_trade(trade)

    @staticmethod
    def _fill_frames(order: Order, ex: _Execution) -> list[bytes]:
        """``order.fill`` for *order*'s execution *ex*: one shape for all paths.

        Built from the order itself rather than ``Order.to_dict()``, which
        has no display ``price`` (every path but the new-order one lost it)
        and costs a dict of 25 fields per fill. Adds the execution to the
        order's running notional, so call it once per execution.
        """
        symbol = order.symbol
        order.cum_notional_ticks += ex.notional
        return make_order_fill_unchecked(
            gateway_id=order.gateway_id,
            order_id=order.id,
            fill_qty=ex.qty,
            fill_price=ex.notional / (ex.qty * 10 ** get_tick_decimals(symbol)),
            remaining_qty=order.remaining_qty,
            status=fill_status(order.remaining_qty),
            symbol=symbol,
            side=order.side.value,
            order_type=order.order_type.value,
            tif=order.tif.value,
            qty=order.quantity,
            price=(
                from_ticks(order.price_ticks, symbol)
                if order.price_ticks is not None
                else None
            ),
            client_tag=order.client_tag,
            oco_group_id=order.oco_group_id,
            combo_parent_id=order.combo_parent_id,
            quote_id=order.quote_id,
            leg_index=order.leg_index,
            is_seed=order.is_seed,
            trade_ids=ex.trade_ids,
            liquidity_flag=ex.flag,
            fill_notional_ticks=ex.notional,
            cum_qty=order.quantity - order.remaining_qty,
            cum_notional_ticks=order.cum_notional_ticks,
        )

    def _check_circuit_breaker(self, symbol: str, trade_price: int, now: int) -> None:
        """
        Called after every fill to check whether a circuit breaker halt should fire.

        If the rolling-window average has moved more than ``dynamic_band_pct``
        from the trigger price, the symbol is halted:
          - All resting quotes for the symbol are cancelled.
          - A ``circuit_breaker.halt.{symbol}`` message is broadcast.
          - ``_halted_symbols[symbol]`` is set to True so new orders are blocked.
        """
        if not self._enforce_circuit_breakers:
            return

        cb = self._circuit_breakers.get(symbol)
        if cb is None:
            return
        triggered_level = cb.record_trade(trade_price, now)
        if triggered_level is None:
            return

        log.debug(
            "circuit breaker tripped symbol=%s level=%s trigger_price=%s reference_price=%s shift_pct=%s",
            symbol,
            triggered_level.name,
            cb.trigger_price,
            cb.reference_price,
            triggered_level.price_shift_pct,
        )
        cb.activate(now, triggered_level, self._reopening_rng)
        self._halted_symbols[symbol] = True

        # Cancel all resting quotes for the halted symbol.
        # Fast-path: avoid cancellation traversal when no quotes exist.
        if self._quote_index.has_symbol(symbol):
            for entry in self._quote_index.cancel_all_for_symbol(
                symbol, reason="Circuit breaker halt"
            ):
                self._cancel_quote_entry(
                    entry,
                    reason="Circuit breaker halt",
                    cancel_reason="CIRCUIT_BREAKER_HALT",
                )

        self.pub_sock.send_multipart(
            make_circuit_breaker_halt(
                symbol=symbol,
                trigger_price=(
                    from_ticks(cb.trigger_price, symbol)
                    if cb.trigger_price is not None
                    else None
                ),
                reference_price=(
                    from_ticks(cb.reference_price, symbol)
                    if cb.reference_price is not None
                    else None
                ),
                resume_at_ns=cb.resume_at_ns,
                halt_source=cb.halt_source,
                level=cb.triggered_level,
                **self._corridor_payload(cb, symbol),
            )
        )
        self._mark_dirty(symbol)
        bounds = cb.corridor()
        log.info(
            f"CIRCUIT BREAKER HALT {symbol}: "
            f"level={cb.triggered_level} "
            f"trigger={cb.trigger_price}, ref={cb.reference_price} ticks"
            + (
                f", corridor=[{bounds[0]}, {bounds[1]}] ticks "
                f"(+/-{cb.config.reopening.band_pct_at(0):.1%})"
                if bounds is not None
                else ", corridor=unbounded (ACE disabled)"
            )
        )

    def _corridor_payload(self, cb: CircuitBreakerState, symbol: str) -> dict[str, Any]:
        """Wire representation of the ACE corridor, in display prices."""
        bounds = cb.corridor()
        if bounds is None:
            return {"corridor_low": None, "corridor_high": None, "expansion": None}
        return {
            "corridor_low": from_ticks(bounds[0], symbol),
            "corridor_high": from_ticks(bounds[1], symbol),
            "expansion": cb.expansion_index,
        }

    def _run_closing_backstop(self) -> None:
        """Force every still-halted symbol to reopen at the session close.

        ACE will widen a corridor indefinitely, so on its own it has no
        terminating condition — the end of the trading day supplies one. This
        mirrors Nasdaq's Hybrid Closing Cross (Rule 4754(b)(7)(D)): a symbol
        that has not managed to reopen within its corridor prints *at* the
        corridor boundary rather than at the outlying equilibrium.

        This is the only place in the engine where a price is imposed rather
        than discovered. A clamped print can leave the book crossed — bids and
        asks beyond the boundary do not trade — which is intended: that
        interest survives to the next session rather than executing at a price
        the corridor was built to reject.
        """
        for symbol, cb in self._circuit_breakers.items():
            if not self._halted_symbols.get(symbol):
                continue

            book = self._book(symbol)
            indicative = compute_equilibrium(book)
            halt_source = cb.halt_source
            expansions = cb.expansion_index
            bounds = cb.corridor()

            print_price: int | None = None
            clamped = False
            if indicative.eq_price is not None and indicative.eq_qty > 0:
                print_price = indicative.eq_price
                if bounds is not None:
                    low, high = bounds
                    if print_price > high:
                        print_price, clamped = high, True
                    elif print_price < low:
                        print_price, clamped = low, True

            cb.deactivate()
            self._halted_symbols[symbol] = False

            if print_price is None:
                log.info(
                    f"CLOSING BACKSTOP {symbol}: no crossing interest, "
                    f"halt cleared after {expansions} ACE extension(s)"
                )
            else:
                log.info(
                    f"CLOSING BACKSTOP {symbol}: "
                    f"indicative={indicative.eq_price} ticks "
                    + (
                        f"outside [{bounds[0]}, {bounds[1]}] -> clamped to "
                        f"{print_price} ({indicative.imbalance_side or 'no'} imbalance)"
                        if clamped and bounds is not None
                        else f"within corridor -> printing at {print_price}"
                    )
                    + f", after {expansions} ACE extension(s)"
                )
                self._run_uncross(
                    symbol_filter=symbol,
                    reason="BACKSTOP",
                    price_override=print_price,
                )

            self.pub_sock.send_multipart(
                make_circuit_breaker_resume(
                    symbol=symbol,
                    halt_source=halt_source,
                    reason="CLOSING_BACKSTOP",
                    clamped=clamped,
                    print_price=(
                        from_ticks(print_price, symbol)
                        if print_price is not None
                        else None
                    ),
                )
            )
            self._mark_dirty(symbol)

    def _flush_circuit_breakers(self) -> None:
        """
        Called once per poll loop tick.  Checks all halted symbols and either
        reopens them or extends their call phase under ACE.

        The halt itself is the reopening auction's call phase: LIMIT orders are
        accepted and rest while MARKET/FOK/IOC are rejected, and matching is
        disabled. Resuming therefore always uncrosses at the equilibrium price
        first — crossed interest accumulates during the call, so restarting
        continuous matching without an uncross would begin on a crossed book.

        Automated Corridor Expansion (ACE) sits in front of that uncross. At
        the end of each call phase the equilibrium is computed as a dry run;
        if it falls outside the corridor the symbol does *not* reopen. The
        corridor widens one rung and another call phase begins. Because the
        ladder's last rung repeats, the corridor eventually contains any
        finite price, so no extension cap is needed — see §120.
        """
        now = now_ns()
        for symbol, cb in self._circuit_breakers.items():
            if not cb.should_resume(now):
                continue

            # Dry run: what price *would* this reopen at?
            book = self._book(symbol)
            indicative = compute_equilibrium(book)
            if (
                indicative.eq_price is not None
                and indicative.eq_qty > 0
                and not cb.within_corridor(indicative.eq_price)
            ):
                before = cb.corridor()
                cb.extend(now, self._reopening_rng)
                after = cb.corridor()
                assert before is not None and after is not None
                log.info(
                    f"ACE EXTEND {symbol}: indicative={indicative.eq_price} ticks "
                    f"outside [{before[0]}, {before[1]}] -> "
                    f"expansion={cb.expansion_index} "
                    f"corridor=[{after[0]}, {after[1]}] "
                    f"(+/-{cb.config.reopening.band_pct_at(cb.expansion_index):.1%}) "
                    f"qty={indicative.eq_qty} next_call_ends={cb.resume_at_ns}"
                )
                self.pub_sock.send_multipart(
                    make_circuit_breaker_extend(
                        symbol=symbol,
                        indicative_price=from_ticks(indicative.eq_price, symbol),
                        indicative_qty=indicative.eq_qty,
                        imbalance_side=indicative.imbalance_side or None,
                        resume_at_ns=cb.resume_at_ns,
                        **self._corridor_payload(cb, symbol),
                    )
                )
                self._mark_dirty(symbol)
                continue

            # Capture the halt source BEFORE deactivate() clears it.
            halt_source = cb.halt_source
            expansions = cb.expansion_index
            cb.deactivate()
            self._halted_symbols[symbol] = False
            self._run_uncross(symbol_filter=symbol, reason="REOPEN")
            self.pub_sock.send_multipart(
                make_circuit_breaker_resume(symbol=symbol, halt_source=halt_source)
            )
            self._mark_dirty(symbol)
            log.info(
                f"CIRCUIT BREAKER RESUME {symbol}: after {expansions} ACE extension(s)"
            )

    def _on_quote_leg_filled(self, order: Order) -> None:
        if not order.quote_id:
            return
        entry = self._quote_index.get(order.gateway_id, order.symbol)
        if not entry or entry.quote_id != order.quote_id:
            return

        cfg = (
            self._engine_config.fix_gateways.get(order.gateway_id)
            if self._engine_config
            else None
        )
        policy = (
            cfg.quote_refresh_policy
            if cfg is not None
            else QuoteRefreshPolicy.INACTIVATE_ON_ANY_FILL
        )

        should_inactivate = policy == QuoteRefreshPolicy.INACTIVATE_ON_ANY_FILL or (
            policy == QuoteRefreshPolicy.INACTIVATE_ON_FULL_FILL
            and order.status == OrderStatus.FILLED
        )
        if not should_inactivate:
            return

        status = (
            "INACTIVE_BID_FILLED" if order.side == Side.BUY else "INACTIVE_ASK_FILLED"
        )
        self._quote_index.remove(order.gateway_id, order.symbol, reason=status)
        sibling_id = entry.counterpart_order_id(order.side.value)
        sibling_order = self._cancel_order_by_id(
            sibling_id, cancel_reason="QUOTE_LEG_FILLED"
        )

        # `order` is the filled leg — already terminal, its final state is
        # available directly. `sibling_order` is whatever _cancel_order_by_id
        # just returned for the other leg. Attach both to the history entry
        # remove() just recorded, same pattern as _cancel_quote_entry.
        filled_snapshot = self._snapshot_quote_leg(order)
        sibling_snapshot = self._snapshot_quote_leg(sibling_order)
        bid_leg = filled_snapshot if order.side == Side.BUY else sibling_snapshot
        ask_leg = sibling_snapshot if order.side == Side.BUY else filled_snapshot
        self._quote_index.attach_leg_snapshots(
            order.gateway_id, entry.quote_id, bid_leg, ask_leg
        )

        self.pub_sock.send_multipart(
            make_quote_status_msg(order.gateway_id, entry.quote_id, status)
        )

    def _handle_quote_new(self, payload: dict[str, Any]) -> None:
        """Handle ``quote.new``: a market maker's two-sided quote.

        A quote is a BID and an ASK posted together (one price and size per
        side).  The engine does not give quotes a book of their own: it turns
        them into two ordinary LIMIT orders (the "legs", marked
        ``origin=QUOTE`` and sharing a ``quote_id``) and runs each through
        ``OrderBook.process`` like any other order.  What makes them special
        is bookkeeping:

        * a gateway has at most ONE live quote per symbol (``_quote_index``);
          a new quote REPLACES the old one (old legs cancelled first);
        * when a leg trades, the other leg may be pulled, depending on the
          gateway's refresh policy (``_on_quote_leg_filled``);
        * market-maker obligations (max spread, min size) can be enforced.

        Flow: gates -> parse + sanity -> obligation check -> replace old
        quote -> build two orders -> ACK + ACTIVE status -> match bid, then
        ask -> publish like any dispatch.  Unlike ``order.new`` every reject
        here is a ``quote.ack`` with ``accepted=False``.
        """
        self.metrics.count(self.metrics.quotes_in, payload.get("gateway_id"))
        gateway_id = str(payload.get("gateway_id", "")).upper()
        symbol = str(payload.get("symbol", "")).upper()
        quote_id = str(payload.get("quote_id", ""))
        self._dbg_count("quote_requests")

        # --- Gates (same ideas as _handle_new_order, quote-specific replies) --
        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self._dbg_count("quote_reject_gateway")
            self.pub_sock.send_multipart(
                self._quote_ack(gateway_id, quote_id, False, reason, symbol=symbol)
            )
            return

        session = self._session_for_gateway(gateway_id)
        if session.role != ParticipantRole.MARKET_MAKER:
            self._dbg_count("quote_reject_role")
            self.pub_sock.send_multipart(
                self._quote_ack(
                    gateway_id,
                    quote_id,
                    False,
                    "Quotes are only allowed for MARKET_MAKER participants",
                    symbol=symbol,
                )
            )
            return

        if not symbol:
            self._dbg_count("quote_reject_payload")
            self.pub_sock.send_multipart(
                self._quote_ack(
                    gateway_id,
                    quote_id,
                    False,
                    "Missing symbol",
                    symbol=symbol,
                )
            )
            return
        if self._allowed_symbols and symbol not in self._allowed_symbols:
            self._dbg_count("quote_reject_symbol")
            self.pub_sock.send_multipart(
                self._quote_ack(
                    gateway_id,
                    quote_id,
                    False,
                    f"Symbol not configured: {symbol}",
                    symbol=symbol,
                )
            )
            return

        # Halt check — circuit breaker has halted this symbol; reject incoming quotes
        if self._halted_symbols.get(symbol):
            self._dbg_count("quote_reject_halt")
            self.pub_sock.send_multipart(
                self._quote_ack(
                    gateway_id,
                    quote_id,
                    False,
                    f"{symbol} is halted — quotes rejected during circuit breaker halt",
                    symbol=symbol,
                )
            )
            return

        # #16: quotes are subject to the same session gating as ordinary orders.
        # Reject outright when the market is not accepting orders (e.g. CLOSED).
        if self._sessions_enabled and not accepts_orders(self._session_state):
            self._dbg_count("quote_reject_session")
            self.pub_sock.send_multipart(
                self._quote_ack(
                    gateway_id,
                    quote_id,
                    False,
                    "Market is closed",
                    symbol=symbol,
                )
            )
            return

        def _quote_ticks(key: str) -> int:
            """Read one quote price. Ticks only.

            A float here means a submitting gateway skipped its ``to_ticks``
            conversion. Accepting it would post the quote at 1/100th of the
            intended level on a two-decimal instrument — silent, and in the
            wrong direction for whichever side gets hit. Same rule and same
            reasoning as ``_handle_oco_order``'s ``_leg_ticks`` (design
            section 15.2); quotes joined it in 6.1b.
            """
            value = payload[key]
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{key} must be integer ticks, not display money")
            return value

        # --- Parse and sanity-check the payload ---
        try:
            bid_price = _quote_ticks("bid_price_ticks")
            ask_price = _quote_ticks("ask_price_ticks")
            bid_qty = int(payload["bid_qty"])
            ask_qty = int(payload["ask_qty"])
            tif = TIF(str(payload.get("tif", "DAY")).upper())
        except KeyError, TypeError, ValueError:
            self._dbg_count("quote_reject_payload")
            self.pub_sock.send_multipart(
                self._quote_ack(
                    gateway_id,
                    quote_id,
                    False,
                    "Invalid quote payload",
                    symbol=symbol,
                )
            )
            return

        if bid_qty <= 0 or ask_qty <= 0:
            self._dbg_count("quote_reject_payload")
            self.pub_sock.send_multipart(
                self._quote_ack(
                    gateway_id,
                    quote_id,
                    False,
                    "Quote quantities must be positive",
                    symbol=symbol,
                )
            )
            return
        if bid_price >= ask_price:
            self._dbg_count("quote_reject_payload")
            self.pub_sock.send_multipart(
                self._quote_ack(
                    gateway_id,
                    quote_id,
                    False,
                    "Quote requires bid_price < ask_price",
                    symbol=symbol,
                )
            )
            return

        # --- Market-maker obligations: which policy applies? ---
        # A designated market maker may be required to quote tightly and with
        # a minimum size.  The policy can be set at several levels; the most
        # specific one wins (see the precedence comment below).
        cfg = (
            self._engine_config.fix_gateways.get(gateway_id)
            if self._engine_config
            else None
        )
        enforce_mm = False
        mm_max_spread_ticks = 0
        mm_min_qty = 0
        # Quote legs have no per-request SMP concept of their own -- always
        # resolve from the gateway's configured default (or SmpAction.NONE).
        smp_action = self._resolve_smp_action(gateway_id, None)
        if cfg:
            enforce_mm = cfg.enforce_mm_obligation
            mm_max_spread_ticks = cfg.mm_max_spread_ticks
            mm_min_qty = cfg.mm_min_qty

            # Specificity precedence for MM obligation policy:
            # gateway+symbol > global symbol > gateway > global defaults.
            if self._engine_config is not None:
                global_symbol_policy = (
                    self._engine_config.global_symbol_mm_obligation_policies.get(symbol)
                )
                if global_symbol_policy is not None:
                    enforce_mm = global_symbol_policy.enforce_mm_obligation
                    mm_max_spread_ticks = global_symbol_policy.mm_max_spread_ticks
                    mm_min_qty = global_symbol_policy.mm_min_qty

            gateway_symbol_policy = cfg.mm_obligation_policies.get(symbol)
            if gateway_symbol_policy is not None:
                enforce_mm = gateway_symbol_policy.enforce_mm_obligation
                mm_max_spread_ticks = gateway_symbol_policy.mm_max_spread_ticks
                mm_min_qty = gateway_symbol_policy.mm_min_qty

        if cfg and enforce_mm:
            spread_ticks = ask_price - bid_price
            if spread_ticks > mm_max_spread_ticks:
                self._dbg_count("quote_reject_mm_obligation")
                self.pub_sock.send_multipart(
                    self._quote_ack(
                        gateway_id,
                        quote_id,
                        False,
                        (
                            f"Spread {spread_ticks} ticks exceeds max "
                            f"{mm_max_spread_ticks}"
                        ),
                        symbol=symbol,
                    )
                )
                return
            if bid_qty < mm_min_qty or ask_qty < mm_min_qty:
                self._dbg_count("quote_reject_mm_obligation")
                self.pub_sock.send_multipart(
                    self._quote_ack(
                        gateway_id,
                        quote_id,
                        False,
                        f"Quote size must be >= {mm_min_qty}",
                        symbol=symbol,
                    )
                )
                return

        # --- Replace semantics: one live quote per (gateway, symbol) ---
        # The old quote's legs must be gone BEFORE the new legs are matched,
        # otherwise the new bid could trade against the maker's own old ask.
        previous = self._quote_index.remove(
            gateway_id, symbol, reason="Replaced by new quote"
        )
        if previous:
            self._cancel_quote_entry(
                previous,
                reason="Replaced by new quote",
                cancel_reason="QUOTE_REPLACED",
            )
        else:
            # No active QuoteIndex entry — most commonly because a prior fill
            # already inactivated this gateway/symbol's quote (see
            # _on_quote_leg_filled). Under INACTIVATE_ON_ANY_FILL, that path
            # cancels only the untouched sibling leg — by design, the *hit*
            # leg's own remainder (if the fill was partial) is meant to stay
            # resting, live and tradeable, until this replacement quote
            # actually supersedes it (docs-design/EduMatcher-MM-Bot-review.md
            # §4 item 3; docs-design/mm-quote-identification.md's
            # replace-by-new-quote walkthrough: "cancel any surviving old
            # child orders"). Without this fallback, such a stray order is
            # never cancelled and rests alongside the fresh leg below,
            # silently doubling this gateway's exposure on that side.
            self._cancel_orphaned_quote_legs(gateway_id, symbol)

        if not quote_id:
            quote_id = f"{gateway_id}-{symbol}-{now_ns()}"

        # --- Build the two legs: ordinary LIMIT orders tagged as quote legs ---
        bid = Order.create(
            symbol=symbol,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=bid_qty,
            gateway_id=gateway_id,
            tif=tif,
            price_ticks=bid_price,
            smp_action=smp_action,
        )
        ask = Order.create(
            symbol=symbol,
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=ask_qty,
            gateway_id=gateway_id,
            tif=tif,
            price_ticks=ask_price,
            smp_action=smp_action,
        )
        bid.origin = OrderOrigin.QUOTE
        ask.origin = OrderOrigin.QUOTE
        bid.quote_id = quote_id
        ask.quote_id = quote_id

        # Register routing + the quote record BEFORE matching: a leg that fills
        # on entry fires _on_quote_leg_filled, which looks the quote up here.
        self._order_symbol[bid.id] = symbol
        self._order_symbol[ask.id] = symbol
        entry = QuoteEntry(
            quote_id=quote_id,
            gateway_id=gateway_id,
            symbol=symbol,
            bid_order_id=bid.id,
            ask_order_id=ask.id,
        )
        self._quote_index.put(entry)

        # X8a: the quote is accepted and live before its legs reach the book,
        # as an order is acked before it matches -- so a fill on entry, and
        # the refresh policy's INACTIVE_* it triggers, follow these two
        # messages instead of preceding an ACTIVE that is no longer true.
        self.pub_sock.send_multipart(
            self._quote_ack(
                gateway_id,
                quote_id,
                True,
                bid_order_id=bid.id,
                ask_order_id=ask.id,
                symbol=symbol,
            )
        )
        self._dbg_count("quote_accepted")
        self.pub_sock.send_multipart(
            make_quote_status_msg(gateway_id, quote_id, "ACTIVE")
        )

        now = now_ns()
        book = self._book(symbol)
        # #16: only match continuously in CONTINUOUS session state; in auction
        # phases (PRE_OPEN etc.) quote legs rest and cross at the uncross.
        do_match = is_matching_enabled(self._session_state)
        # --- Match the legs one at a time, bid first ---
        # Each leg is a normal aggressive LIMIT order: it may trade against
        # resting orders on entry, and any remainder rests.  Sequential on
        # purpose: if the bid fills and the policy pulls the quote, the ask
        # must not be posted at all (handled in the `if` below).
        for quote_order in (bid, ask):
            if (
                quote_order is ask
                and self._quote_index.get(gateway_id, symbol) is not entry
            ):
                # X8a: the bid's fill on entry inactivated the quote, and the
                # policy's sibling cancel ran before the ask existed in the
                # book. The ask never rests; its owner learns it the way a
                # resting sibling's owner does.
                ask.status = OrderStatus.CANCELLED
                ask.cancel_reason = "QUOTE_LEG_FILLED"
                self._order_symbol.pop(ask.id, None)
                self.pub_sock.send_multipart(
                    make_cancelled_msg(
                        gateway_id,
                        ask.id,
                        order=ask.to_dict(),
                        cancel_reason="QUOTE_LEG_FILLED",
                    )
                )
                # The hook's history entry was recorded without the ask.
                self._quote_index.attach_leg_snapshots(
                    gateway_id,
                    quote_id,
                    self._snapshot_quote_leg(bid),
                    self._snapshot_quote_leg(ask),
                )
                break
            trades, events = book.process(quote_order, match=do_match, now=now)
            self._publish_dispatch(trades, events)

        self._mark_dirty(symbol)

    def _handle_quote_cancel(self, payload: dict[str, Any]) -> None:
        """Handle ``quote.cancel``: withdraw this gateway's quote in a symbol.

        Removes the quote record, then cancels both legs through
        ``_cancel_quote_entry`` (which publishes the per-leg cancels).  The
        reply is a ``quote.ack``: accepted if a quote existed, otherwise a
        reject saying there was none.
        """
        gateway_id = str(payload.get("gateway_id", "")).upper()
        symbol = str(payload.get("symbol", "")).upper()

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                self._quote_ack(gateway_id, "", False, reason, symbol=symbol)
            )
            return

        entry = self._quote_index.remove(
            gateway_id, symbol, reason="Cancelled by participant"
        )
        if not entry:
            self.pub_sock.send_multipart(
                self._quote_ack(
                    gateway_id,
                    "",
                    False,
                    "No active quote for symbol",
                    symbol=symbol,
                )
            )
            return

        self._cancel_quote_entry(entry, reason="Cancelled by participant")
        self.pub_sock.send_multipart(
            self._quote_ack(gateway_id, entry.quote_id, True, symbol=symbol)
        )

    def _handle_gateway_disconnect(self, payload: dict[str, Any]) -> None:
        gateway_id = str(payload.get("gateway_id", "")).upper()
        if not gateway_id:
            return

        self.metrics.count(self.metrics.disconnects, gateway_id)
        session = self._session_for_gateway(gateway_id)
        session.connected = False
        session.heartbeat_interval_sec = 0
        self._connected_fix_gateways.discard(gateway_id)

        # Republish the disconnect on the PUB feed as the lifecycle counterpart
        # to system.gateway_auth.{id}, so PUB-only subscribers (e.g. clearing)
        # can close the matching session.  Emitted before any behaviour-specific
        # early return so it always fires.
        reason = str(payload.get("reason", ""))
        self.pub_sock.send_multipart(make_gateway_bye_msg(gateway_id, reason))

        if session.disconnect_behaviour == DisconnectBehaviour.LEAVE_ALL:
            return

        removed_quotes = self._quote_index.cancel_all_for_gateway(
            gateway_id, reason="Gateway disconnected"
        )
        for entry in removed_quotes:
            self._cancel_quote_entry(
                entry,
                reason="Gateway disconnected",
                cancel_reason="GATEWAY_DISCONNECT",
            )

        if session.disconnect_behaviour == DisconnectBehaviour.CANCEL_ALL:
            # O(k) per book via OrderBook._orders_by_gateway (k = this
            # gateway's resting orders there), not a scan of every resting
            # order in every book — see ../../../docs/books/architecture-and-development/part-1-architecture/020-guided-tour.md
            # §10. Quote-origin orders are excluded: the cancel_all_for_gateway
            # call above already handles those via QuoteIndex.
            for book in self.books.values():
                for order in list(book.orders_for_gateway(gateway_id)):
                    if order.origin != OrderOrigin.QUOTE:
                        self._cancel_order_by_id(
                            order.id, cancel_reason="GATEWAY_DISCONNECT"
                        )

    def _handle_gateway_heartbeat(self, payload: dict[str, Any]) -> None:
        gateway_id = _clamp_wire_id(payload.get("gateway_id", ""))
        session = self._sessions.get(gateway_id)
        if session is None or not session.connected:
            # A beat from a process whose session is gone (already timed out
            # or disconnected) must not resurrect it.
            return
        session.heartbeat_interval_sec = min(
            3600, max(1, int(payload.get("interval_sec", 0)))
        )
        session.last_heartbeat = time.monotonic()
        self._dbg_count("gateway_heartbeats")
        log.debug(
            "heartbeat gateway=%s interval=%ds",
            gateway_id,
            session.heartbeat_interval_sec,
        )

    def _expire_silent_gateways(self) -> None:
        """Disconnect each session that stopped sending its heartbeat.

        A process that died without a ``gateway_disconnect`` would otherwise
        keep its ID connected for ever and block every reconnect. The normal
        disconnect path runs, so ``disconnect_behaviour`` and the
        ``gateway_bye`` broadcast apply exactly as for a clean exit.
        """
        now = time.monotonic()
        if now < self._next_silence_check:
            return
        self._next_silence_check = now + _SILENCE_CHECK_SEC
        for session in list(self._sessions.values()):
            if not session.connected or session.heartbeat_interval_sec <= 0:
                continue
            limit = _HEARTBEAT_MISSED_LIMIT * session.heartbeat_interval_sec
            if now - session.last_heartbeat <= limit:
                continue
            log.warning(
                "Gateway %s missed %d heartbeats (interval %ds) — disconnecting",
                session.gateway_id,
                _HEARTBEAT_MISSED_LIMIT,
                session.heartbeat_interval_sec,
            )
            self.metrics.count(self.metrics.heartbeat_timeouts, session.gateway_id)
            self._handle_gateway_disconnect(
                {"gateway_id": session.gateway_id, "reason": "heartbeat_timeout"}
            )

    def _handle_kill_switch(self, payload: dict[str, Any]) -> None:
        gateway_id = _clamp_wire_id(payload.get("gateway_id", ""))
        symbol_filter = _clamp_wire_id(payload.get("symbol", ""), 16)
        # Echoed on the ack so concurrent mass cancels for one gateway can be
        # told apart. Absent for callers that do not supply it.
        command_id = str(payload.get("command_id", ""))[:_MAX_WIRE_COMMAND_ID_LEN]
        note = str(payload.get("note", ""))[:_MAX_WIRE_NOTE_LEN]

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                make_kill_switch_ack_msg(
                    gateway_id, False, reason, command_id=command_id
                )
            )
            self._publish_admin_action(
                gateway_id,
                command_id,
                "kill_switch.self",
                {"symbol": symbol_filter or None},
                accepted=False,
                reason=reason,
            )
            return

        cancelled_order_ids: list[str] = []
        cancelled_quote_order_ids: list[str] = []

        if symbol_filter:
            entry = self._quote_index.get(gateway_id, symbol_filter)
            if entry is not None:
                self._quote_index.remove(
                    gateway_id, symbol_filter, reason="Kill switch"
                )
                cancelled_quote_order_ids += self._cancel_quote_entry(
                    entry,
                    reason="Kill switch",
                    cancel_reason="KILL_SWITCH",
                    command_id=command_id,
                )
        else:
            entries = self._quote_index.cancel_all_for_gateway(
                gateway_id, reason="Kill switch"
            )
            for entry in entries:
                cancelled_quote_order_ids += self._cancel_quote_entry(
                    entry,
                    reason="Kill switch",
                    cancel_reason="KILL_SWITCH",
                    command_id=command_id,
                )

        # O(k) per book via OrderBook._orders_by_gateway (k = this gateway's
        # resting orders there) instead of a scan of every resting order in
        # every book — see ../../../docs/books/architecture-and-development/part-1-architecture/020-guided-tour.md §10.
        for book in self.books.values():
            if symbol_filter and book.symbol != symbol_filter:
                continue
            for order in list(book.orders_for_gateway(gateway_id)):
                if order.origin != OrderOrigin.QUOTE:
                    cancelled = self._cancel_order_by_id(
                        order.id,
                        cancel_reason="KILL_SWITCH",
                        command_id=command_id,
                    )
                    if cancelled is not None:
                        cancelled_order_ids.append(cancelled.id)

        cancelled_orders = len(cancelled_order_ids)
        cancelled_quotes = len(cancelled_quote_order_ids)

        self.pub_sock.send_multipart(
            make_kill_switch_ack_msg(
                gateway_id,
                True,
                cancelled_orders=cancelled_orders,
                cancelled_order_ids=cancelled_order_ids,
                cancelled_quotes=cancelled_quotes,
                cancelled_quote_order_ids=cancelled_quote_order_ids,
                command_id=command_id,
            )
        )
        self._publish_admin_action(
            gateway_id,
            command_id,
            "kill_switch.self",
            {
                "symbol": symbol_filter or None,
                "note": note,
                "cancelled_orders": cancelled_orders,
                "cancelled_order_ids": cancelled_order_ids,
                "cancelled_quotes": cancelled_quotes,
                "cancelled_quote_order_ids": cancelled_quote_order_ids,
            },
            accepted=True,
        )

    def _handle_kill_switch_gateway(self, payload: dict[str, Any]) -> None:
        """ADMIN → engine: cancel every order/quote for *target_gateway_id*.

        Unlike ``_handle_kill_switch``, the caller (``gateway_id``, checked
        for ADMIN role) and the affected gateway (``target_gateway_id``) are
        allowed to differ — this is one admin acting on another participant's
        exposure, not a gateway acting on its own.
        """
        gateway_id = _clamp_wire_id(payload.get("gateway_id", ""))
        target_gateway_id = _clamp_wire_id(payload.get("target_gateway_id", ""))
        command_id = str(payload.get("command_id", ""))[:_MAX_WIRE_COMMAND_ID_LEN]
        note = str(payload.get("note", ""))[:_MAX_WIRE_NOTE_LEN]

        def _reject(reason: str) -> None:
            self.pub_sock.send_multipart(
                make_kill_switch_gateway_ack_msg(
                    gateway_id, target_gateway_id, False, reason, command_id=command_id
                )
            )
            self._publish_admin_action(
                gateway_id,
                command_id,
                "kill_switch.gateway",
                {"target_gateway_id": target_gateway_id},
                accepted=False,
                reason=reason,
            )

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            _reject(reason)
            return

        session = self._session_for_gateway(gateway_id)
        if session.role != ParticipantRole.ADMIN:
            _reject(
                "Gateway-targeted kill switch is only allowed for ADMIN participants"
            )
            return

        if not target_gateway_id:
            _reject("target_gateway_id required")
            return

        cancelled_order_ids: list[str] = []
        cancelled_quote_order_ids: list[str] = []

        for entry in self._quote_index.cancel_all_for_gateway(
            target_gateway_id, reason="ADMIN kill switch"
        ):
            cancelled_quote_order_ids += self._cancel_quote_entry(
                entry,
                reason="ADMIN kill switch",
                cancel_reason="KILL_SWITCH",
                command_id=command_id,
            )

        # O(k) per book via OrderBook._orders_by_gateway (k = this gateway's
        # resting orders there) instead of a scan of every resting order in
        # every book — see ../../../docs/books/architecture-and-development/part-1-architecture/020-guided-tour.md §10.
        for book in self.books.values():
            for order in list(book.orders_for_gateway(target_gateway_id)):
                if order.origin != OrderOrigin.QUOTE:
                    cancelled = self._cancel_order_by_id(
                        order.id,
                        cancel_reason="KILL_SWITCH",
                        command_id=command_id,
                    )
                    if cancelled is not None:
                        cancelled_order_ids.append(cancelled.id)

        cancelled_orders = len(cancelled_order_ids)
        cancelled_quotes = len(cancelled_quote_order_ids)

        self.pub_sock.send_multipart(
            make_kill_switch_gateway_ack_msg(
                gateway_id,
                target_gateway_id,
                True,
                cancelled_orders=cancelled_orders,
                cancelled_order_ids=cancelled_order_ids,
                cancelled_quotes=cancelled_quotes,
                cancelled_quote_order_ids=cancelled_quote_order_ids,
                command_id=command_id,
            )
        )
        self._publish_admin_action(
            gateway_id,
            command_id,
            "kill_switch.gateway",
            {
                "target_gateway_id": target_gateway_id,
                "note": note,
                "cancelled_orders": cancelled_orders,
                "cancelled_order_ids": cancelled_order_ids,
                "cancelled_quotes": cancelled_quotes,
                "cancelled_quote_order_ids": cancelled_quote_order_ids,
            },
            accepted=True,
        )
        log.info(
            f"ADMIN KILL SWITCH (gateway) — target={target_gateway_id} by {gateway_id}:"
            f" orders={cancelled_orders} quotes={cancelled_quotes}"
        )

    def _handle_kill_switch_global(self, payload: dict[str, Any]) -> None:
        """ADMIN → engine: cancel every resting order/quote for every gateway.

        The full-market emergency stop. Distinct from
        ``risk.circuit_breaker_halt_all``, which halts trading but leaves
        resting orders in place — this cancels them outright.
        """
        gateway_id = _clamp_wire_id(payload.get("gateway_id", ""))
        command_id = str(payload.get("command_id", ""))[:_MAX_WIRE_COMMAND_ID_LEN]
        note = str(payload.get("note", ""))[:_MAX_WIRE_NOTE_LEN]

        def _reject(reason: str) -> None:
            self.pub_sock.send_multipart(
                make_kill_switch_global_ack_msg(
                    gateway_id, False, reason, command_id=command_id
                )
            )
            self._publish_admin_action(
                gateway_id,
                command_id,
                "kill_switch.global",
                {},
                accepted=False,
                reason=reason,
            )

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            _reject(reason)
            return

        session = self._session_for_gateway(gateway_id)
        if session.role != ParticipantRole.ADMIN:
            _reject("Global kill switch is only allowed for ADMIN participants")
            return

        cancelled_order_ids: list[str] = []
        cancelled_quote_order_ids: list[str] = []
        affected_gateways: set[str] = set()

        for target_gateway_id in self._quote_index.gateway_ids():
            entries = self._quote_index.cancel_all_for_gateway(
                target_gateway_id, reason="ADMIN global kill switch"
            )
            if entries:
                affected_gateways.add(target_gateway_id)
            for entry in entries:
                cancelled_quote_order_ids += self._cancel_quote_entry(
                    entry,
                    reason="ADMIN global kill switch",
                    cancel_reason="KILL_SWITCH",
                    command_id=command_id,
                )

        for book in self.books.values():
            for order in list(book.resting_orders()):
                if order.origin != OrderOrigin.QUOTE:
                    owner = order.gateway_id
                    cancelled = self._cancel_order_by_id(
                        order.id,
                        cancel_reason="KILL_SWITCH",
                        command_id=command_id,
                    )
                    if cancelled is not None:
                        cancelled_order_ids.append(cancelled.id)
                        affected_gateways.add(owner)

        cancelled_orders = len(cancelled_order_ids)
        cancelled_quotes = len(cancelled_quote_order_ids)
        affected_gateway_ids = sorted(affected_gateways)

        self.pub_sock.send_multipart(
            make_kill_switch_global_ack_msg(
                gateway_id,
                True,
                cancelled_orders=cancelled_orders,
                cancelled_order_ids=cancelled_order_ids,
                cancelled_quotes=cancelled_quotes,
                cancelled_quote_order_ids=cancelled_quote_order_ids,
                affected_gateways=len(affected_gateways),
                affected_gateway_ids=affected_gateway_ids,
                command_id=command_id,
            )
        )
        self._publish_admin_action(
            gateway_id,
            command_id,
            "kill_switch.global",
            {
                "note": note,
                "cancelled_orders": cancelled_orders,
                "cancelled_order_ids": cancelled_order_ids,
                "cancelled_quotes": cancelled_quotes,
                "cancelled_quote_order_ids": cancelled_quote_order_ids,
                "affected_gateways": len(affected_gateways),
                "affected_gateway_ids": affected_gateway_ids,
            },
            accepted=True,
        )
        log.warning(
            f"ADMIN KILL SWITCH (global) by {gateway_id}: "
            f"orders={cancelled_orders} quotes={cancelled_quotes} "
            f"gateways={len(affected_gateways)}"
        )

    def _handle_circuit_breaker_halt_all(self, payload: dict[str, Any]) -> None:
        gateway_id = str(payload.get("gateway_id", "")).upper()

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                make_circuit_breaker_halt_all_ack_msg(gateway_id, False, reason)
            )
            return

        session = self._session_for_gateway(gateway_id)
        if session.role != ParticipantRole.ADMIN:
            self.pub_sock.send_multipart(
                make_circuit_breaker_halt_all_ack_msg(
                    gateway_id,
                    False,
                    "Global circuit-breaker halt is only allowed for ADMIN participants",
                )
            )
            return

        symbols: set[str] = set(self.books.keys())
        symbols.update(self._circuit_breakers.keys())
        symbols.update(self._halted_symbols.keys())
        if self._allowed_symbols is not None:
            symbols.update(self._allowed_symbols)
        elif self._engine_config is not None:
            symbols.update(self._engine_config.symbols.keys())

        now = now_ns()
        halted_symbol_ids = sorted(symbols)
        cancelled_quote_order_ids: list[str] = []
        for symbol in halted_symbol_ids:
            self._halted_symbols[symbol] = True

            cb = self._circuit_breakers.get(symbol)
            if cb is not None:
                cb.halted = True
                cb.halted_at_ns = now
                cb.resume_at_ns = None
                cb.trigger_price = None
                cb.reference_price = None
                cb.triggered_level = "ADMIN_ALL"
                cb.halt_source = "ADMIN"

            for entry in self._quote_index.cancel_all_for_symbol(
                symbol, reason="Global circuit breaker halt"
            ):
                cancelled_quote_order_ids += self._cancel_quote_entry(
                    entry,
                    reason="Global circuit breaker halt",
                    cancel_reason="CIRCUIT_BREAKER_HALT",
                )

            self.pub_sock.send_multipart(
                make_circuit_breaker_halt(
                    symbol=symbol,
                    trigger_price=None,
                    reference_price=None,
                    resume_at_ns=None,
                    halt_source="ADMIN",
                    level="ADMIN_ALL",
                )
            )
            self._mark_dirty(symbol)

        self.pub_sock.send_multipart(
            make_circuit_breaker_halt_all_ack_msg(
                gateway_id,
                True,
                halted_symbols=len(halted_symbol_ids),
                halted_symbol_ids=halted_symbol_ids,
                cancelled_quotes=len(cancelled_quote_order_ids),
                cancelled_quote_order_ids=cancelled_quote_order_ids,
            )
        )

    def _handle_circuit_breaker_resume_all(self, payload: dict[str, Any]) -> None:
        gateway_id = str(payload.get("gateway_id", "")).upper()

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                make_circuit_breaker_resume_all_ack_msg(gateway_id, False, reason)
            )
            return

        session = self._session_for_gateway(gateway_id)
        if session.role != ParticipantRole.ADMIN:
            self.pub_sock.send_multipart(
                make_circuit_breaker_resume_all_ack_msg(
                    gateway_id,
                    False,
                    "Global circuit-breaker resume is only allowed for ADMIN participants",
                )
            )
            return

        # Collect every symbol that is currently halted
        halted_symbols = sorted(
            sym for sym, halted in self._halted_symbols.items() if halted
        )

        for symbol in halted_symbols:
            self._halted_symbols[symbol] = False

            cb = self._circuit_breakers.get(symbol)
            if cb is not None:
                cb.deactivate()

            self.pub_sock.send_multipart(
                make_circuit_breaker_resume(symbol=symbol, halt_source="ADMIN")
            )
            self._mark_dirty(symbol)

        self.pub_sock.send_multipart(
            make_circuit_breaker_resume_all_ack_msg(
                gateway_id,
                True,
                resumed_symbols=len(halted_symbols),
                resumed_symbol_ids=halted_symbols,
            )
        )
        if halted_symbols:
            log.info(
                f"ADMIN CIRCUIT BREAKER RESUME ALL — "
                f"{len(halted_symbols)} symbol(s): {', '.join(halted_symbols)}"
            )

    def _handle_symbol_halt(self, payload: dict[str, Any]) -> None:
        """Halt trading on a single symbol (ADMIN only).

        With a ``level`` naming one of the symbol's configured
        ``circuit_breaker.levels``, this runs through the same
        ``CircuitBreakerState.activate()`` state machine a price-triggered
        halt uses, so it gets a real ``resume_at_ns`` / ACE corridor and is
        picked up by the normal ``_flush_circuit_breakers()`` tick. Without a
        matching level (the previous behaviour), the halt is indefinite —
        cleared only by an explicit resume.
        """
        gateway_id = _clamp_wire_id(payload.get("gateway_id", ""))
        symbol = _clamp_wire_id(payload.get("symbol", ""), 16)
        level_name_raw = payload.get("level")
        level_name = (
            str(level_name_raw).upper()[:_MAX_WIRE_CB_LEVEL_LEN]
            if level_name_raw
            else None
        )
        note = str(payload.get("note", ""))[:_MAX_WIRE_NOTE_LEN]
        command_id = str(payload.get("command_id", ""))[:_MAX_WIRE_COMMAND_ID_LEN]

        def _reject(reason: str) -> None:
            self.pub_sock.send_multipart(
                make_symbol_halt_ack_msg(
                    gateway_id, symbol, False, reason, command_id=command_id
                )
            )
            self._publish_admin_action(
                gateway_id,
                command_id,
                "circuit_breaker.trigger",
                {"symbol": symbol, "level": level_name},
                accepted=False,
                reason=reason,
            )

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            _reject(reason)
            return

        session = self._session_for_gateway(gateway_id)
        if session.role != ParticipantRole.ADMIN:
            _reject("Per-symbol halt is only allowed for ADMIN participants")
            return

        if not symbol:
            _reject("symbol required")
            return

        if self._allowed_symbols is not None and symbol not in self._allowed_symbols:
            _reject(f"Unknown symbol: {symbol}")
            return

        now = now_ns()

        cb = self._circuit_breakers.get(symbol)
        if level_name is not None and cb is None:
            _reject(f"{symbol} has no circuit breaker configured")
            return

        triggered_level = "ADMIN_SYMBOL"
        resume_at_ns: int | None = None
        selected: CircuitBreakerLevel | None = None
        if cb is not None:
            if level_name is not None:
                selected = next(
                    (lvl for lvl in cb.config.levels if lvl.name == level_name),
                    None,
                )
                if selected is None:
                    _reject(f"Unknown circuit-breaker level for {symbol}: {level_name}")
                    return
        # Only once nothing can reject: a rejected trigger must not leave the
        # symbol halted with no circuit_breaker.halt ever published.
        self._halted_symbols[symbol] = True
        if cb is not None:
            if selected is not None:
                # Seed a reference price if none exists yet (mirrors the
                # startup seeding in _load_config()) — activate() itself does
                # not compute one, it only uses whatever is already set.
                if cb.reference_price is None:
                    book = self._book(symbol)
                    ref_ticks = (
                        book.last_buy_price
                        if book.last_buy_price is not None
                        else book.last_sell_price
                    )
                    if ref_ticks is not None:
                        cb.seed_reference(ref_ticks, now)
                cb.activate(now, selected, self._reopening_rng)
                cb.halt_source = "ADMIN"
                triggered_level = selected.name
                resume_at_ns = cb.resume_at_ns
            else:
                cb.halted = True
                cb.halted_at_ns = now
                cb.resume_at_ns = None
                cb.trigger_price = None
                cb.reference_price = None
                cb.triggered_level = "ADMIN_SYMBOL"
                cb.halt_source = "ADMIN"

        cancelled_quote_order_ids: list[str] = []
        for entry in self._quote_index.cancel_all_for_symbol(
            symbol, reason="Per-symbol halt"
        ):
            cancelled_quote_order_ids += self._cancel_quote_entry(
                entry,
                reason="Per-symbol halt",
                cancel_reason="CIRCUIT_BREAKER_HALT",
                command_id=command_id,
            )

        self.pub_sock.send_multipart(
            make_circuit_breaker_halt(
                symbol=symbol,
                trigger_price=None,
                reference_price=None,
                resume_at_ns=resume_at_ns,
                halt_source="ADMIN",
                level=triggered_level,
            )
        )
        self._mark_dirty(symbol)

        self.pub_sock.send_multipart(
            make_symbol_halt_ack_msg(
                gateway_id,
                symbol,
                True,
                cancelled_quotes=len(cancelled_quote_order_ids),
                cancelled_quote_order_ids=cancelled_quote_order_ids,
                command_id=command_id,
            )
        )
        self._publish_admin_action(
            gateway_id,
            command_id,
            "circuit_breaker.trigger",
            {"symbol": symbol, "level": triggered_level, "note": note},
            accepted=True,
        )
        log.info(
            f"ADMIN SYMBOL HALT — {symbol} by {gateway_id} (level={triggered_level})"
        )

    def _handle_symbol_resume(self, payload: dict[str, Any]) -> None:
        """Resume a single symbol that was halted by a per-symbol or global halt (ADMIN only)."""
        gateway_id = _clamp_wire_id(payload.get("gateway_id", ""))
        symbol = _clamp_wire_id(payload.get("symbol", ""), 16)
        note = str(payload.get("note", ""))[:_MAX_WIRE_NOTE_LEN]
        command_id = str(payload.get("command_id", ""))[:_MAX_WIRE_COMMAND_ID_LEN]

        def _reject(reason: str) -> None:
            self.pub_sock.send_multipart(
                make_symbol_resume_ack_msg(
                    gateway_id, symbol, False, reason, command_id=command_id
                )
            )
            self._publish_admin_action(
                gateway_id,
                command_id,
                "circuit_breaker.resume",
                {"symbol": symbol},
                accepted=False,
                reason=reason,
            )

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            _reject(reason)
            return

        session = self._session_for_gateway(gateway_id)
        if session.role != ParticipantRole.ADMIN:
            _reject("Per-symbol resume is only allowed for ADMIN participants")
            return

        if not symbol:
            _reject("symbol required")
            return

        if not self._halted_symbols.get(symbol):
            _reject(f"{symbol} is not halted")
            return

        self._halted_symbols[symbol] = False

        cb = self._circuit_breakers.get(symbol)
        if cb is not None:
            cb.deactivate()

        self.pub_sock.send_multipart(
            make_circuit_breaker_resume(symbol=symbol, halt_source="ADMIN")
        )
        self._mark_dirty(symbol)

        self.pub_sock.send_multipart(
            make_symbol_resume_ack_msg(gateway_id, symbol, True, command_id=command_id)
        )
        self._publish_admin_action(
            gateway_id,
            command_id,
            "circuit_breaker.resume",
            {"symbol": symbol, "note": note},
            accepted=True,
        )
        log.info(f"ADMIN SYMBOL RESUME — {symbol} by {gateway_id}")

    def _handle_cancel_symbol(self, payload: dict[str, Any]) -> None:
        """Cancel all resting orders for a symbol across every gateway (ADMIN only)."""
        gateway_id = _clamp_wire_id(payload.get("gateway_id", ""))
        symbol = _clamp_wire_id(payload.get("symbol", ""), 16)

        note = str(payload.get("note", ""))[:_MAX_WIRE_NOTE_LEN]
        command_id = str(payload.get("command_id", ""))[:_MAX_WIRE_COMMAND_ID_LEN]

        def _reject(reason: str) -> None:
            self.pub_sock.send_multipart(
                make_cancel_symbol_ack_msg(
                    gateway_id, symbol, False, reason, command_id=command_id
                )
            )
            self._publish_admin_action(
                gateway_id,
                command_id,
                "kill_switch.symbol",
                {"symbol": symbol},
                accepted=False,
                reason=reason,
            )

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            _reject(reason)
            return

        session = self._session_for_gateway(gateway_id)
        if session.role != ParticipantRole.ADMIN:
            _reject("Symbol-level mass cancel is only allowed for ADMIN participants")
            return

        if not symbol:
            _reject("symbol required")
            return

        book = self.books.get(symbol)
        cancelled_order_ids: list[str] = []
        if book is not None:
            for order in list(book.resting_orders()):
                if order.origin != OrderOrigin.QUOTE:
                    cancelled = self._cancel_order_by_id(
                        order.id,
                        cancel_reason="ADMIN_CANCEL_SYMBOL",
                        command_id=command_id,
                    )
                    if cancelled is not None:
                        cancelled_order_ids.append(cancelled.id)

        cancelled_quote_order_ids: list[str] = []
        for entry in self._quote_index.cancel_all_for_symbol(
            symbol, reason="Symbol mass cancel"
        ):
            cancelled_quote_order_ids += self._cancel_quote_entry(
                entry,
                reason="Symbol mass cancel",
                cancel_reason="ADMIN_CANCEL_SYMBOL",
                command_id=command_id,
            )

        cancelled_orders = len(cancelled_order_ids)
        cancelled_quotes = len(cancelled_quote_order_ids)

        self.pub_sock.send_multipart(
            make_cancel_symbol_ack_msg(
                gateway_id,
                symbol,
                True,
                cancelled_orders=cancelled_orders,
                cancelled_order_ids=cancelled_order_ids,
                cancelled_quotes=cancelled_quotes,
                cancelled_quote_order_ids=cancelled_quote_order_ids,
                command_id=command_id,
            )
        )
        self._publish_admin_action(
            gateway_id,
            command_id,
            "kill_switch.symbol",
            {
                "symbol": symbol,
                "note": note,
                "cancelled_orders": cancelled_orders,
                "cancelled_order_ids": cancelled_order_ids,
                "cancelled_quotes": cancelled_quotes,
                "cancelled_quote_order_ids": cancelled_quote_order_ids,
            },
            accepted=True,
        )
        log.info(
            f"ADMIN CANCEL SYMBOL — {symbol} by {gateway_id}:"
            f" orders={cancelled_orders} quotes={cancelled_quotes}"
        )

    def _handle_force_uncross(self, payload: dict[str, Any]) -> None:
        """Force one symbol to uncross now, optionally at an operator price,
        clearing any halt in the same step (ADMIN only).

        ``dry_run`` peeks the indicative print via a read-only equilibrium
        calculation and mutates nothing. A live run clears the halt so the
        ``_run_uncross`` guard does not skip the symbol, then uncrosses under
        ``reason="ADMIN_MANUAL"`` — which honours an asserted price even when
        the book has no natural equilibrium (a failed-auction recovery).
        """
        gateway_id = _clamp_wire_id(payload.get("gateway_id", ""))
        symbol = _clamp_wire_id(payload.get("symbol", ""), 16)
        price_raw = payload.get("price")
        dry_run = bool(payload.get("dry_run", False))
        note = str(payload.get("note", ""))[:_MAX_WIRE_NOTE_LEN]
        command_id = str(payload.get("command_id", ""))[:_MAX_WIRE_COMMAND_ID_LEN]

        def _reject(reason: str) -> None:
            self.pub_sock.send_multipart(
                make_force_uncross_ack_msg(
                    gateway_id,
                    False,
                    symbol=symbol,
                    reason=reason,
                    dry_run=dry_run,
                    command_id=command_id,
                )
            )
            self._publish_admin_action(
                gateway_id,
                command_id,
                "auction.reopen",
                {"symbol": symbol},
                accepted=False,
                reason=reason,
            )

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            _reject(reason)
            return

        session = self._session_for_gateway(gateway_id)
        if session.role != ParticipantRole.ADMIN:
            _reject("Force-uncross is only allowed for ADMIN participants")
            return

        if not symbol:
            _reject("symbol required")
            return

        if self._allowed_symbols is not None and symbol not in self._allowed_symbols:
            _reject(f"Unknown symbol: {symbol}")
            return

        price_ticks: int | None = None
        if price_raw is not None:
            try:
                price_val = float(price_raw)
            except TypeError, ValueError:
                _reject(f"Invalid price: {price_raw!r}")
                return
            if price_val <= 0:
                _reject("price must be positive")
                return
            try:
                price_ticks = to_ticks_exact(price_val, symbol)
            except TickViolation as exc:
                _reject(str(exc))
                return

        book = self._book(symbol)

        # Read-only peek. When a price is asserted, report what that price
        # would print; otherwise the naturally computed equilibrium.
        peek = (
            executable_at(book, price_ticks)
            if price_ticks is not None
            else compute_equilibrium(book)
        )
        indicative_price = (
            from_ticks(peek.eq_price, symbol) if peek.eq_price is not None else None
        )

        if dry_run:
            self.pub_sock.send_multipart(
                make_force_uncross_ack_msg(
                    gateway_id,
                    True,
                    symbol=symbol,
                    dry_run=True,
                    indicative_price=indicative_price,
                    indicative_qty=peek.eq_qty,
                    surplus=peek.surplus,
                    imbalance_side=peek.imbalance_side,
                    command_id=command_id,
                )
            )
            self._publish_admin_action(
                gateway_id,
                command_id,
                "auction.reopen",
                {"symbol": symbol, "note": note},
                accepted=True,
            )
            log.info(
                f"ADMIN REOPEN DRY-RUN — {symbol} by {gateway_id}: "
                f"indicative={indicative_price} qty={peek.eq_qty}"
            )
            return

        # Live run: clear the halt first so the _run_uncross guard admits the
        # symbol, then force the uncross.
        was_halted = self._halted_symbols.get(symbol, False)
        self._halted_symbols[symbol] = False
        cb = self._circuit_breakers.get(symbol)
        if cb is not None:
            cb.deactivate()
        if was_halted:
            self.pub_sock.send_multipart(
                make_circuit_breaker_resume(symbol=symbol, halt_source="ADMIN")
            )
            self._mark_dirty(symbol)

        outcomes = self._run_uncross(
            symbol_filter=symbol,
            reason="ADMIN_MANUAL",
            price_override=price_ticks,
        )
        printed_ticks, traded_qty = outcomes.get(symbol, (None, 0))
        printed_price = (
            from_ticks(printed_ticks, symbol) if printed_ticks is not None else None
        )

        self.pub_sock.send_multipart(
            make_force_uncross_ack_msg(
                gateway_id,
                True,
                symbol=symbol,
                dry_run=False,
                indicative_price=indicative_price,
                indicative_qty=peek.eq_qty,
                surplus=peek.surplus,
                imbalance_side=peek.imbalance_side,
                printed_price=printed_price,
                traded_qty=traded_qty,
                command_id=command_id,
            )
        )
        self._publish_admin_action(
            gateway_id,
            command_id,
            "auction.reopen",
            {"symbol": symbol, "note": note},
            accepted=True,
        )
        log.info(
            f"ADMIN REOPEN — {symbol} by {gateway_id}: "
            f"printed={printed_price} qty={traded_qty} "
            f"(price_override={price_ticks})"
        )

    # ------------------------------------------------------------------
    # Combo-order handlers
    #
    # A COMBO is a bundle of 2-10 orders on DIFFERENT symbols submitted as one
    # unit (think: buy A and sell B together).  The engine has no combo book:
    # each leg becomes an ordinary child Order that goes through the normal
    # OrderBook.process path.  The engine's job is the parent's bookkeeping:
    #
    #   self._combos          combo internal id -> ComboOrder (the parent)
    #   self._order_to_combo  child order id    -> combo internal id
    #
    # Whenever a child order's state changes, _publish_dispatch calls
    # _check_combo_after_child_event, which advances the parent:
    #   PENDING -> PARTIALLY_MATCHED -> MATCHED   (all legs filled), or
    #   any leg cancelled/expired/rejected -> FAILED, and every other leg is
    #   cancelled (_cascade_cancel_combo).  The user may also cancel the whole
    #   combo (CANCELLED).
    #
    # Note the limited meaning of "all-or-none" (AON): it is a guard at ENTRY
    # only.  If every leg could fill completely right now, the legs are
    # matched; if any leg could not, NO leg is matched on entry and all rest
    # as interest.  It is not a guarantee that the legs execute atomically
    # later on.
    # ------------------------------------------------------------------

    def _validate_combo(self, combo: ComboOrder) -> str:
        """Return an error string if the combo is invalid, else empty string.

        Structural checks only: 2-10 legs, one leg per symbol, configured
        symbols, positive quantities, a price where the order type needs one.
        (Per-leg collar/limit checks that a single order gets are not applied.)
        """
        if len(combo.legs) < 2:
            return "Combo requires at least 2 legs"
        if len(combo.legs) > 10:
            return "Combo supports at most 10 legs"

        symbols_in_combo = [leg.symbol for leg in combo.legs]
        if len(set(symbols_in_combo)) != len(symbols_in_combo):
            return "Duplicate symbols in combo legs"

        for leg in combo.legs:
            if self._allowed_symbols and leg.symbol not in self._allowed_symbols:
                return f"Symbol not configured: {leg.symbol}"

        for i, leg in enumerate(combo.legs):
            if leg.quantity <= 0:
                return f"Leg {i}: invalid quantity {leg.quantity}"
            needs_price = leg.order_type in (
                OrderType.LIMIT,
                OrderType.FOK,
                OrderType.STOP_LIMIT,
                OrderType.ICEBERG,
            )
            if needs_price and leg.price_ticks is None:
                return f"Leg {i}: {leg.order_type.value} requires a price"

        return ""

    def _accept_combo(
        self, combo: ComboOrder, *, publish_ack: bool = True, is_seed: bool = False
    ) -> bool:
        """Post combo child orders to books and start tracking the parent combo.

        Used for live submissions and for config-seeded combos
        (``is_seed=True``, ``publish_ack=False`` at startup).  Order of events:

        1. validate the combo; reject with ``combo.ack(accepted=False)``;
        2. ACK the combo and register the parent in ``_combos``;
        3. for AON, pre-check that every leg is fully fillable;
        4. for each leg: create the child Order, ACK it, run it through
           ``book.process``, publish the result.  A leg that dies on entry
           fails the combo and stops further legs from being posted.
        """
        reason = self._validate_combo(combo)
        if reason:
            if publish_ack:
                self.pub_sock.send_multipart(
                    self._combo_ack(combo.gateway_id, combo.combo_id, False, reason)
                )
            return False

        log.info(
            f"COMBO {combo.combo_id} accepted "
            f"({len(combo.legs)} legs) from {combo.gateway_id}"
        )
        if publish_ack:
            self.pub_sock.send_multipart(
                self._combo_ack(combo.gateway_id, combo.combo_id, True)
            )
        # Registered before any child is posted, so a child's own dispatch
        # runs the combo follow-up: a leg ending on entry fails the combo
        # (X21), and its fills move the combo's status.
        self._combos[combo.id] = combo

        # M5: all-or-none combos must not execute ANY leg unless EVERY leg can
        # fully fill simultaneously.  Pre-check each leg's fillability; if any
        # leg is short, post all legs without matching (they rest as pending
        # interest) so no partial, non-atomic execution occurs.
        aon_blocked = False
        if combo.combo_type == ComboType.AON:
            aon_blocked = not all(
                self._book(leg.symbol).fillable_quantity(leg.side, leg.price_ticks)
                >= leg.quantity
                for leg in combo.legs
            )

        # Create child orders and post to books, one leg at a time, in order.
        # Each leg is processed (and published) completely before the next
        # starts, so the legs of one combo are NOT atomic with respect to each
        # other -- which is exactly why the AON pre-check above exists.
        for i, leg in enumerate(combo.legs):
            # SMP=None on a leg means it was omitted (either by the client on
            # a live combo, or by an unset market_maker_combos[].legs[]
            # config seed) -- fall back to the gateway's configured default.
            leg_smp_action = self._resolve_smp_action(combo.gateway_id, leg.smp_action)
            child = Order.create(
                symbol=leg.symbol,
                side=leg.side,
                order_type=leg.order_type,
                quantity=leg.quantity,
                gateway_id=combo.gateway_id,
                tif=combo.tif,
                price_ticks=leg.price_ticks,
                stop_price_ticks=leg.stop_price_ticks,
                visible_qty=None,
                smp_action=leg_smp_action,
                client_tag=combo.client_tag,
                is_seed=is_seed,
            )
            # These two fields mark the order as a combo leg; they travel on
            # every fill/cancel message and let _publish_dispatch find the
            # parent again via _order_to_combo.
            child.combo_parent_id = combo.id
            child.leg_index = i

            combo.child_order_ids.append(child.id)
            combo.leg_statuses[i] = OrderStatus.NEW.value
            combo.leg_fill_qty[i] = 0
            self._order_to_combo[child.id] = combo.id
            self._order_symbol[child.id] = leg.symbol

            # No combo child leg previously published an order.ack at all --
            # combo.ack only confirms the parent, and _handle_new_order /
            # _handle_quote_new / OCO / the seeded-quote-leg loop above all
            # ack their orders individually. Without this, a subscriber that
            # starts after acceptance (or that only ever sees a long-resting,
            # never-filled leg) has no way to learn a child leg's symbol,
            # side, price or qty until it is cancelled -- and order.cancelled
            # deliberately does not carry them either. Publish the same ACK
            # shape every other order-creation path uses, before matching,
            # for every leg -- live or config-seeded. A leg the book may
            # still reject is acked after process(), and only if it was not
            # rejected (X5, _book_may_reject).
            book = self._book(leg.symbol)
            # H9: combo children respect the session's matching state and the
            # per-symbol halt, exactly like ordinary orders — no continuous
            # matching outside CONTINUOUS or while the leg's symbol is halted.
            # M5: an AON combo with any unfillable leg matches nothing.
            do_match = (
                is_matching_enabled(self._session_state)
                and not self._halted_symbols.get(leg.symbol)
                and not aon_blocked
            )
            ack = self._order_ack(
                combo.gateway_id,
                child.id,
                accepted=True,
                order=ack_detail(child),
            )
            defer_ack = _book_may_reject(child, do_match)
            if not defer_ack:
                self.pub_sock.send_multipart(ack)
            trades, events = book.process(child, match=do_match)
            if defer_ack and child.status is not OrderStatus.REJECTED:
                self.pub_sock.send_multipart(ack)
            self._publish_dispatch(
                trades, events, self._book_reject(leg.symbol, do_match)
            )
            self._mark_dirty(leg.symbol)
            # A failed combo posts no further legs: they could only be acked
            # and cancelled at once.
            if combo.status is ComboStatus.FAILED:
                break
        return True

    def _handle_combo_order(self, payload: dict[str, Any]) -> None:
        """Handle ``order.combo``: gateway + session gates, then _accept_combo."""
        self.metrics.count(self.metrics.orders_in, payload.get("gateway_id"))
        combo = ComboOrder.from_submission_dict(payload)

        # Gateway auth
        ok, reason = self._gateway_status(combo.gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                self._combo_ack(combo.gateway_id, combo.combo_id, False, reason)
            )
            return
        if self._sessions_enabled and not accepts_orders(self._session_state):
            self.pub_sock.send_multipart(
                self._combo_ack(
                    combo.gateway_id, combo.combo_id, False, "Market is closed"
                )
            )
            return
        self._accept_combo(combo, publish_ack=True)

    def _handle_combo_cancel(self, payload: dict[str, Any]) -> None:
        """Handle ``order.combo_cancel``: cancel a combo and all its resting legs.

        The client names the combo by ITS id (``combo_id``), whereas the
        engine keys ``_combos`` by an internal id, hence the linear search
        below (combos are few).  Only the owner can cancel, and a combo that
        already reached a terminal status cannot be cancelled again.
        """
        gateway_id = str(payload.get("gateway_id", "")).upper()
        combo_id = payload.get("combo_id", "")

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                self._combo_ack(gateway_id, combo_id, False, reason)
            )
            return

        # Find the combo by user-provided combo_id
        combo = None
        for c in self._combos.values():
            if c.combo_id == combo_id and c.gateway_id == gateway_id:
                combo = c
                break
        if not combo:
            self.pub_sock.send_multipart(
                self._combo_ack(gateway_id, combo_id, False, "Combo not found")
            )
            return
        if combo.status in (
            ComboStatus.MATCHED,
            ComboStatus.FAILED,
            ComboStatus.CANCELLED,
            ComboStatus.REJECTED,
        ):
            self.pub_sock.send_multipart(
                self._combo_ack(
                    gateway_id, combo_id, False, f"Combo already {combo.status.value}"
                )
            )
            return

        self._cascade_cancel_combo(combo, ComboStatus.CANCELLED)

    def _check_combo_after_child_event(self, child_order: Order) -> None:
        """Called after any child order fill/cancel/expire/reject to update combo state.

        The hook that connects ordinary order processing to combo bookkeeping.
        Recomputes the parent's per-leg status and filled quantity, then
        either fails the whole combo (a leg ended without filling) or lets
        ``_update_combo_status`` move it forward.  A no-op for orders that
        are not combo legs, and for combos already in a terminal state.
        """
        combo_id = self._order_to_combo.get(child_order.id)
        if not combo_id:
            return
        combo = self._combos.get(combo_id)
        if not combo:
            return
        if combo.status in (
            ComboStatus.MATCHED,
            ComboStatus.FAILED,
            ComboStatus.CANCELLED,
            ComboStatus.REJECTED,
        ):
            return

        idx = child_order.leg_index
        if idx is None:
            return
        combo.leg_statuses[idx] = child_order.status.value
        combo.leg_fill_qty[idx] = child_order.quantity - child_order.remaining_qty

        if child_order.status in (
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
            OrderStatus.REJECTED,
        ):
            self._cascade_cancel_combo(
                combo,
                ComboStatus.FAILED,
                reason=f"Leg {idx} ({child_order.symbol}) "
                f"{child_order.status.value}",
            )
            return

        self._update_combo_status(combo)

    def _update_combo_status(self, combo: ComboOrder) -> None:
        """Transition combo status based on current leg states.

        Forward-only: PENDING -> PARTIALLY_MATCHED when any leg has traded,
        -> MATCHED when every leg is completely filled.  Each transition is
        announced once with ``combo.status``.
        """
        if combo.is_fully_filled:
            combo.status = ComboStatus.MATCHED
            self.pub_sock.send_multipart(
                make_combo_status_msg(
                    combo.gateway_id, combo.combo_id, ComboStatus.MATCHED.value
                )
            )
            log.info(f"COMBO {combo.combo_id} MATCHED (all legs filled)")
            return

        # Check if at least one leg has partial or full fill
        has_fill = any(
            s in (OrderStatus.PARTIAL.value, OrderStatus.FILLED.value)
            for s in combo.leg_statuses.values()
        )
        if has_fill and combo.status == ComboStatus.PENDING:
            combo.status = ComboStatus.PARTIALLY_MATCHED
            self.pub_sock.send_multipart(
                make_combo_status_msg(
                    combo.gateway_id,
                    combo.combo_id,
                    ComboStatus.PARTIALLY_MATCHED.value,
                )
            )

    def _cascade_cancel_combo(
        self, combo: ComboOrder, terminal_status: ComboStatus, reason: str = ""
    ) -> None:
        """Cancel all resting child legs and mark combo as terminal.

        Used for both a user cancel (CANCELLED) and a failed leg (FAILED).
        The status is set FIRST so that the cancels below, which re-enter
        ``_check_combo_after_child_event`` through other paths, find a
        terminal combo and do nothing (no recursion, no duplicate FAILED).
        Legs that already filled are not cancellable and are simply skipped
        by ``book.cancel_order`` returning None.
        """
        combo.status = terminal_status

        for child_id in combo.child_order_ids:
            symbol = self._order_symbol.get(child_id)
            book = self.books.get(symbol) if symbol else None
            if book:
                cancelled = book.cancel_order(child_id)
                if cancelled:
                    self.pub_sock.send_multipart(
                        make_cancelled_msg(
                            combo.gateway_id, child_id, order=cancelled.to_dict()
                        )
                    )
                    self._mark_dirty(symbol)  # type: ignore[arg-type]
            self._order_symbol.pop(child_id, None)
            self._order_to_combo.pop(child_id, None)

        self.pub_sock.send_multipart(
            make_combo_status_msg(
                combo.gateway_id,
                combo.combo_id,
                terminal_status.value,
                reason=reason,
            )
        )
        log.info(
            f"COMBO {combo.combo_id} {terminal_status.value}"
            + (f" — {reason}" if reason else "")
        )

    # ------------------------------------------------------------------
    # Session / auction transitions
    # ------------------------------------------------------------------

    def _reply_session_transition(
        self,
        payload: dict[str, Any],
        accepted: bool,
        to_state: str = "",
        reason: str = "",
    ) -> None:
        """Answer an interactive transition request, if one asked to be told.

        `pm-scheduler` sends no command_id and gets no reply — it drives the
        timetable and reads the outcome off the public session.state
        broadcast. An operator issuing a manual transition does supply one,
        and previously received nothing at all when the request was discarded.
        """
        reply_to = payload.get("reply_to") or {}
        command_id = str(reply_to.get("command_id", ""))
        gateway_id = str(reply_to.get("gateway_id", ""))
        if not command_id or not gateway_id:
            return
        self.pub_sock.send_multipart(
            make_session_transition_ack_msg(
                gateway_id, command_id, accepted, to_state=to_state, reason=reason
            )
        )

    def _publish_admin_action(
        self,
        gateway_id: str,
        command_id: str,
        action: str,
        scope: dict[str, Any],
        accepted: bool,
        reason: str = "",
    ) -> None:
        """Publish the uniform admin-monitor record for one admin command.

        Sent in addition to (never instead of) the command's own ack — the
        ack is what the calling gateway correlates on; this is purely for
        /admin/monitor to have one consistent shape to watch across every
        admin-gated command. No-op if ``command_id`` is empty: without one
        there is nothing for a monitor client to correlate against, and
        every call site here already has one (either supplied by the caller
        or minted for this purpose).
        """
        self.pub_sock.send_multipart(
            make_admin_action_msg(
                gateway_id, command_id, action, scope, accepted, reason=reason
            )
        )

    def _handle_session_transition(self, payload: dict[str, Any]) -> None:
        """Handle a session.transition message from the scheduler."""
        if not self._sessions_enabled:
            self._reply_session_transition(
                payload, False, reason="Sessions are not enabled on this engine"
            )
            return

        try:
            to_state = SessionState(payload["to_state"])
        except (KeyError, ValueError) as exc:
            log.warning("Invalid session transition: %s", exc)
            self._reply_session_transition(
                payload, False, reason=f"Invalid session transition: {exc}"
            )
            return

        from_state = self._session_state

        # Validate transition
        allowed = VALID_TRANSITIONS.get(from_state, set())
        if to_state not in allowed:
            log.warning(
                "Invalid transition %s → %s (allowed: %s)",
                from_state.value,
                to_state.value,
                ", ".join(s.value for s in allowed),
            )
            return

        # Adopted from this command, whatever it says -- including nothing --
        # but only once the transition is known to be going ahead. A rejected
        # command must leave every trace of itself behind.
        #
        # A manual or admin-driven transition carries no timetable, and so
        # *clears* whatever the scheduler last advertised: the engine has
        # just moved somewhere the schedule did not predict, and the old
        # target has stopped being a fact about anything. Leaving it would
        # count a terminal down to a transition nobody is going to perform,
        # which is the failure this field exists to avoid (T-M6).
        upcoming = payload.get("next") or {}
        self._next_session_state = str(upcoming.get("state", ""))
        self._next_session_at = str(upcoming.get("at", ""))

        # --- Uncrossing on exit from auction / no-matching phases ---
        needs_uncross = not is_matching_enabled(from_state) and (
            is_matching_enabled(to_state) or to_state == SessionState.CLOSED
        )
        if needs_uncross:
            self._run_uncross(reason="SCHEDULED")

        # The end of the day terminates ACE. Runs after the scheduled uncross
        # because the backstop can leave a book crossed on purpose, and the
        # sweep must not undo that at the true equilibrium.
        if to_state == SessionState.CLOSED:
            self._run_closing_backstop()

        # --- Expire auction-only orders when their window closes ---
        if from_state == SessionState.OPENING_AUCTION:
            self._expire_tif(TIF.ATO)
        if from_state == SessionState.CLOSING_AUCTION:
            self._expire_tif(TIF.ATC)

        # --- Apply the transition ---
        self._session_state = to_state

        if to_state == SessionState.CLOSED:
            # M14: the close is the day boundary — expire all resting DAY orders
            # so they do not silently carry into the next trading day (they were
            # previously only expired at process shutdown).
            self._expire_tif(TIF.DAY)
            # End-of-day reset for any still-halted symbols (e.g. L3 rest-of-day).
            for symbol, cb in self._circuit_breakers.items():
                if cb.halted:
                    cb.deactivate()
                    self._halted_symbols[symbol] = False

        if to_state == SessionState.PRE_OPEN:
            # M14: reset per-symbol 'daily' counters at the start of a new
            # trading day so a multi-day run does not report cumulative volume.
            for book in self.books.values():
                self.metrics.carry_daily(book)  # health counters stay monotonic
                book.daily_qty = 0
                book.daily_value_ticks = 0
                book.daily_trades = 0

        # AR-0.6: echo the requester's own command_id (never gateway_id --
        # see spec/messages/session.yaml) on the public broadcast, so a
        # schedule-driven transition (no reply_to at all) is distinguishable
        # from an operator-driven one from the payload alone.
        reply_to = payload.get("reply_to") or {}
        transition_command_id = str(reply_to.get("command_id", ""))

        self.pub_sock.send_multipart(
            make_session_state_msg(
                to_state.value,
                prev_state=from_state.value,
                next_state=self._next_session_state,
                next_at=self._next_session_at,
                command_id=transition_command_id,
            )
        )
        # After the broadcast, so a requester that sees its ack knows the
        # public state has already been published.
        self._reply_session_transition(payload, True, to_state=to_state.value)
        self._publish_checkpoints("PHASE")
        log.info(f"Session: {from_state.value} → {to_state.value}")

    def _handle_session_next(self, payload: dict[str, Any]) -> None:
        """Adopt the scheduler's announcement of the next transition.

        Stored, not broadcast: callers read it back through the session-state
        query. An announcement the session machine could not follow from the
        current state is stale or misdirected, and is ignored rather than
        advertised as a countdown nobody will complete.
        """
        if not self._sessions_enabled:
            return
        upcoming = payload.get("next") or {}
        try:
            next_state = SessionState(str(upcoming.get("state", "")))
        except ValueError:
            log.warning("Invalid session announcement: %s", upcoming)
            return
        next_at = str(upcoming.get("at", ""))
        if not next_at or next_state not in VALID_TRANSITIONS.get(
            self._session_state, set()
        ):
            log.warning(
                "Ignoring announced transition %s → %s at %r",
                self._session_state.value,
                next_state.value,
                next_at,
            )
            return
        self._next_session_state = next_state.value
        self._next_session_at = next_at

    def _expire_tif(self, tif: TIF) -> None:
        """Expire all resting orders with the given TIF."""
        for book in self.books.values():
            for order in book.resting_orders():
                if order.tif == tif:
                    cancelled = book.cancel_order(order.id)
                    if cancelled:
                        cancelled.status = OrderStatus.EXPIRED
                        self.pub_sock.send_multipart(
                            make_expired_msg(
                                cancelled.gateway_id,
                                cancelled.id,
                                order=cancelled.to_dict(),
                            )
                        )
                        self._order_symbol.pop(cancelled.id, None)
                        if cancelled.combo_parent_id:
                            self._check_combo_after_child_event(cancelled)
                        self._mark_dirty(book.symbol)

    def _uncross_match_type(self, reason: str) -> str:
        """``trade.executed.match_type`` of an uncross's prints. A scheduled
        uncross runs before the session moves on, so the session state is
        still the phase being left."""
        if reason == "SCHEDULED":
            if self._session_state == SessionState.CLOSING_AUCTION:
                return "CLOSING_AUCTION"
            return "OPENING_AUCTION"
        return {
            "REOPEN": "REOPEN_AUCTION",
            "RECOVERY": "RECOVERY_AUCTION",
            "BACKSTOP": "BACKSTOP",
            "ADMIN_MANUAL": "FORCE_UNCROSS",
        }[reason]

    def _run_uncross(
        self,
        symbol_filter: str | None = None,
        *,
        reason: str,
        price_override: int | None = None,
    ) -> dict[str, tuple[int | None, int]]:
        """Run the equilibrium-price uncrossing on every (or one) symbol book.

        Parameters
        ----------
        symbol_filter : When provided, only uncross this specific symbol.
                        Used by ``_flush_circuit_breakers()`` for per-symbol
                        reopening auctions.
        reason :        Why this uncross is happening — ``SCHEDULED``,
                        ``REOPEN``, ``RECOVERY``, ``BACKSTOP`` or
                        ``ADMIN_MANUAL``. Published on every ``auction.result``
                        so a consumer can tell a reopening auction from the
                        closing one.
        price_override: Print at this price instead of the computed
                        equilibrium. Used by the closing backstop (where the
                        corridor boundary is imposed on a symbol that could not
                        reopen inside it) and by an ``ADMIN_MANUAL`` reopen. For
                        ``ADMIN_MANUAL`` the override is honoured even when
                        ``compute_equilibrium`` finds no natural equilibrium —
                        the operator is asserting the opening price.

        Returns
        -------
        Mapping of each uncrossed symbol to ``(printed_price_ticks, traded_qty)``
        — ``printed_price_ticks`` is ``None`` when nothing printed. Callers that
        do not need the outcome (the session sweep, recovery) ignore it.
        """
        outcomes: dict[str, tuple[int | None, int]] = {}
        match_type = self._uncross_match_type(reason)
        for symbol, book in self.books.items():
            if symbol_filter is not None and symbol != symbol_filter:
                continue
            # A halted symbol's reopen is governed by ACE, not by the session
            # sweep. Uncrossing it here would print outside its corridor and
            # bypass the extension ladder entirely. The per-symbol REOPEN call
            # arrives after deactivate(), so it is unaffected by this guard.
            if self._halted_symbols.get(symbol):
                continue
            self._auctions_run += 1
            auction_id = f"AUC-{current_run_seq() or 0:06d}-{self._auctions_run:06d}"
            result = compute_equilibrium(book)
            # An ADMIN_MANUAL reopen may assert a print price even when the book
            # has no natural equilibrium (a failed auction). Every other caller
            # only overrides a price the book already discovered.
            force_manual = reason == "ADMIN_MANUAL" and price_override is not None
            if price_override is not None and (
                result.eq_price is not None or force_manual
            ):
                result = AuctionResult(
                    eq_price=price_override,
                    eq_qty=result.eq_qty,
                    surplus=result.surplus,
                    imbalance_side=result.imbalance_side,
                )
            trades: list[Any] = []
            if result.eq_price is not None and result.eq_qty > 0:
                # Bind before any reassignment of `result` below, which would
                # otherwise discard the `is not None` narrowing.
                fill_px = result.eq_price
                trades, events = execute_uncross(book, fill_px)
                if price_override is not None:
                    # Fewer shares trade at a clamped price than at the true
                    # equilibrium; report what actually executed.
                    result = AuctionResult(
                        eq_price=result.eq_price,
                        eq_qty=sum(t.quantity for t in trades),
                        surplus=result.surplus,
                        imbalance_side=result.imbalance_side,
                    )

                for t in trades:
                    t.match_type, t.auction_id = match_type, auction_id
                # X8b: the book's quote and OCO hooks are not called inside
                # execute_uncross (its two-sided walk must not be mutated
                # mid-way), so their follow-ups run here -- before the stops
                # below, which must not trade with a leg they pull.
                self._publish_dispatch(trades, events)

            # Trigger stop and trailing-stop orders whose stop price is now
            # reached by the equilibrium price.  execute_uncross() sets
            # last_trade_price but does not run the stops; without this
            # block, auction-phase stop orders never fire at uncross time.
            # run_stops() is the same cascade a continuous trade runs, so the
            # stops execute in the same order (rule G2, insight I19).
            if trades:
                sub_trades, sub_events = book.run_stops(now_ns())
                self._publish_dispatch(sub_trades, sub_events)

                log.info(
                    f"UNCROSS {symbol}: {len(trades)} trade(s) "
                    f"@ {result.eq_price}, qty={result.eq_qty}, "
                    f"surplus={result.surplus} ({result.imbalance_side})"
                )
            else:
                log.info(f"UNCROSS {symbol}: no crossable interest")

            self.pub_sock.send_multipart(
                make_auction_result_msg(
                    symbol=symbol,
                    eq_price=(
                        from_ticks(result.eq_price, symbol)
                        if result.eq_price is not None
                        else None
                    ),
                    eq_qty=result.eq_qty,
                    trades_count=len(trades) if result.eq_price else 0,
                    imbalance_side=result.imbalance_side,
                    imbalance_qty=result.surplus,
                    reason=reason,
                    eq_price_ticks=result.eq_price,
                    auction_id=auction_id,
                )
            )
            outcomes[symbol] = (
                result.eq_price if trades else None,
                result.eq_qty if trades else 0,
            )

        return outcomes

    # ------------------------------------------------------------------
    # OCO-order handlers
    #
    # OCO = "One Cancels the Other": two orders on the SAME symbol (typically
    # a profit-target limit and a protective stop) linked by a shared
    # ``oco_group_id``.  As soon as one of them ends -- filled, cancelled,
    # rejected -- the other must be cancelled.  Think of it as a bracket: only
    # one outcome may happen.
    #
    #   self._oco_groups   oco id   -> [leg1 order id, leg2 order id]
    #   self._order_to_oco order id -> oco id
    #
    # The cancel of the sibling is triggered from TWO places, deliberately:
    #   1. inside the matching run, via ``OrderBook.on_oco_leg_done`` (set up
    #      in ``_book``), so the sibling is gone before the next fill of the
    #      same sweep or stop cascade could trade with it;
    #   2. afterwards, in ``_publish_dispatch`` / ``_handle_cancel``, as a
    #      safety net for ends the book did not see.
    # Both call ``_check_oco_after_event``, which is idempotent.
    # ------------------------------------------------------------------

    def _handle_oco_order(self, payload: dict[str, Any]) -> None:
        """
        Accept an OCO (One-Cancels-Other) pair.

        Payload schema:
          {
            "oco_id":     str,    # user-supplied label
            "gateway_id": str,
            "symbol":     str,    # both legs must be on the same symbol
            "quantity":   int,
            "tif":        str,
            "leg1": {"side": str, "order_type": str, "price_ticks": int|null, "stop_price_ticks": int|null, "trail_offset_ticks": int|null},
            "leg2": {"side": str, "order_type": str, "price_ticks": int|null, "stop_price_ticks": int|null, "trail_offset_ticks": int|null},
          }
        """
        # Flow: gates -> parse both legs -> per-leg field checks -> register
        # the pair -> ACK the pair -> post leg 1, then leg 2 (each: ACK leg,
        # book.process, publish).  Every reject is an ``oco.ack`` with
        # accepted=False and neither leg ever reaches a book.
        self.metrics.count(self.metrics.orders_in, payload.get("gateway_id"))
        gateway_id = str(payload.get("gateway_id", "")).upper()
        oco_id = payload.get("oco_id", "")

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                self._oco_ack(gateway_id, oco_id, False, reason)
            )
            return

        symbol = str(payload.get("symbol", "")).upper()
        quantity = int(payload.get("quantity", 0))
        tif = TIF(payload.get("tif", "DAY"))

        if self._allowed_symbols and symbol not in self._allowed_symbols:
            self.pub_sock.send_multipart(
                self._oco_ack(
                    gateway_id, oco_id, False, f"Symbol not configured: {symbol}"
                )
            )
            return

        if quantity <= 0:
            self.pub_sock.send_multipart(
                self._oco_ack(gateway_id, oco_id, False, "Quantity must be positive")
            )
            return

        # Parse both legs
        leg1_raw = payload.get("leg1", {})
        leg2_raw = payload.get("leg2", {})

        def _leg_ticks(raw: dict[str, Any], key: str) -> int | None:
            """Read one leg price. Ticks only.

            A float here means a submitting gateway skipped its ``to_ticks``
            conversion. Silently accepting it would price the leg 100x low on a
            two-decimal instrument, so it is rejected as an invalid leg.
            """
            value = raw.get(key)
            if value is None:
                return None
            if not isinstance(value, int):
                raise ValueError(f"{key} must be integer ticks, not display money")
            return value

        # The OCO has no SMP field on any protocol, so both legs take the
        # gateway's default -- resolved here like every other order (X9:
        # unresolved legs swept as NONE and traded with their owner).
        smp_action = self._resolve_smp_action(gateway_id, None)

        def _parse_leg(raw: dict[str, Any]) -> Order | None:
            try:
                return Order.create(
                    symbol=symbol,
                    side=Side(raw["side"]),
                    order_type=OrderType(raw["order_type"]),
                    quantity=quantity,
                    gateway_id=gateway_id,
                    tif=tif,
                    # Ticks on the wire: the submitting gateway converted.
                    price_ticks=_leg_ticks(raw, "price_ticks"),
                    stop_price_ticks=_leg_ticks(raw, "stop_price_ticks"),
                    trail_offset_ticks=_leg_ticks(raw, "trail_offset_ticks"),
                    smp_action=smp_action,
                    client_tag=(
                        str(payload["client_tag"])
                        if payload.get("client_tag") is not None
                        else None
                    ),
                )
            except KeyError, ValueError:
                return None

        leg1 = _parse_leg(leg1_raw)
        leg2 = _parse_leg(leg2_raw)

        if leg1 is None or leg2 is None:
            self.pub_sock.send_multipart(
                self._oco_ack(
                    gateway_id,
                    oco_id,
                    False,
                    "Invalid leg definition — check order_type and required price fields",
                )
            )
            return

        # Validate that legs with limit/stop prices have those prices
        for i, leg in enumerate((leg1, leg2), 1):
            if (
                leg.order_type in (OrderType.LIMIT, OrderType.IOC, OrderType.FOK)
                and leg.price_ticks is None
            ):
                self.pub_sock.send_multipart(
                    self._oco_ack(
                        gateway_id,
                        oco_id,
                        False,
                        f"Leg {i} ({leg.order_type.value}) requires price",
                    )
                )
                return
            if (
                leg.order_type in (OrderType.STOP, OrderType.STOP_LIMIT)
                and leg.stop_price_ticks is None
            ):
                self.pub_sock.send_multipart(
                    self._oco_ack(
                        gateway_id,
                        oco_id,
                        False,
                        f"Leg {i} ({leg.order_type.value}) requires stop_price",
                    )
                )
                return
            if (
                leg.order_type == OrderType.TRAILING_STOP
                and leg.trail_offset_ticks is None
            ):
                self.pub_sock.send_multipart(
                    self._oco_ack(
                        gateway_id,
                        oco_id,
                        False,
                        f"Leg {i} (TRAILING_STOP) requires trail_offset",
                    )
                )
                return

        if self._sessions_enabled and not accepts_orders(self._session_state):
            self.pub_sock.send_multipart(
                self._oco_ack(gateway_id, oco_id, False, "Market is closed")
            )
            return

        # Assign shared OCO group ID to both legs.  This id is what the book
        # looks at (``_oco_leg_ended``, ``_apply_fill``) to know a leg is
        # part of a pair and to call back into the engine when it ends.
        leg1.oco_group_id = oco_id
        leg2.oco_group_id = oco_id

        # Register the pair
        self._oco_groups[oco_id] = [leg1.id, leg2.id]
        self._order_to_oco[leg1.id] = oco_id
        self._order_to_oco[leg2.id] = oco_id
        self._order_symbol[leg1.id] = symbol
        self._order_symbol[leg2.id] = symbol

        # Acknowledge first, then post both orders
        self.pub_sock.send_multipart(
            self._oco_ack(
                gateway_id, oco_id, True, order_id_1=leg1.id, order_id_2=leg2.id
            )
        )

        # X18: a halted symbol's legs rest without matching, as an ordinary
        # order's do (gate 8); a leg that cannot rest is rejected by the book.
        do_match = is_matching_enabled(
            self._session_state
        ) and not self._halted_symbols.get(symbol)
        reject = self._book_reject(symbol, do_match)
        book = self._book(symbol)

        # The legs are posted sequentially, NOT simultaneously: leg 1 is fully
        # processed (it may fill at once and so end the pair) before leg 2 is
        # even offered to the book.
        for leg in (leg1, leg2):
            # Resolve trailing stop initial price if needed
            if (
                leg.order_type == OrderType.TRAILING_STOP
                and leg.stop_price_ticks is None
            ):
                if book.last_trade_price is not None:
                    if leg.side == Side.SELL:
                        leg.stop_price_ticks = book.last_trade_price - leg.trail_offset_ticks  # type: ignore[operator]
                    else:
                        leg.stop_price_ticks = book.last_trade_price + leg.trail_offset_ticks  # type: ignore[operator]

            # ACK each leg individually so the gateway can track them -- a
            # leg the book may still reject only after process(), and only if
            # it was not rejected (X5, _book_may_reject).
            ack = self._order_ack(
                gateway_id,
                leg.id,
                accepted=True,
                # order_to_display_dict(leg) is the full order record
                # (mirrors the combo leg ack below) rather than a
                # hand-picked subset — it's what carries oco_group_id
                # (H1, so "Cancel group" can find this leg) and
                # stop_price/visible_qty/trail_offset/smp_action (C3, so
                # Replace and power-user Undo have the fields those order
                # types need), docs-design/reviews/
                # EduMatcher-Trader-GUI-Review.md. Safe to call here,
                # before book.process(leg, ...) below: remaining_qty
                # still equals quantity at this pre-match moment.
                order=ack_detail(leg),
            )
            if leg is leg2 and leg1.status in _ENDED_STATUSES:
                # X17: leg 1 ended on entry -- filled, cancelled or rejected
                # (X12b) -- so leg 2 never reaches the book, where it could
                # trade at once (a stop already breached). The book's hook
                # has unregistered the group; leg 2's owner hears what a
                # resting sibling's owner would.
                self.pub_sock.send_multipart(ack)
                leg2.status = OrderStatus.CANCELLED
                self.pub_sock.send_multipart(
                    make_oco_cancelled_msg(
                        gateway_id,
                        oco_id,
                        leg2.id,
                        reason=f"OCO sibling {leg1.id[:8]} reached {leg1.status.value}",
                    )
                )
                break
            defer_ack = _book_may_reject(leg, do_match)
            if not defer_ack:
                self.pub_sock.send_multipart(ack)
            trades, events = book.process(leg, match=do_match)
            if defer_ack and leg.status is not OrderStatus.REJECTED:
                self.pub_sock.send_multipart(ack)
            # The book pulls the other leg the moment this one ends, even in
            # the cascade it triggers (X15): leg 1 before leg 2 is posted
            # (X17 above), leg 2's sibling at once (no deferral, X8d).
            self._publish_dispatch(trades, events, reject)
            self._mark_dirty(symbol)

        log.info(f"OCO {oco_id}: legs {leg1.id[:8]} and {leg2.id[:8]} posted")

    def _handle_oco_cancel(self, payload: dict[str, Any]) -> None:
        """Handle ``order.oco_cancel``: cancel both legs of an OCO pair.

        Unlike ``_check_oco_after_event`` (sibling cancel after one leg ended)
        this cancels BOTH legs because the client asked to drop the pair.
        """
        gateway_id = str(payload.get("gateway_id", "")).upper()
        oco_id = payload.get("oco_id", "")

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self.pub_sock.send_multipart(
                self._oco_ack(gateway_id, oco_id, False, reason)
            )
            return

        order_ids = self._oco_groups.get(oco_id)
        if not order_ids:
            self.pub_sock.send_multipart(
                self._oco_ack(gateway_id, oco_id, False, "OCO not found")
            )
            return

        for order_id in list(order_ids):
            symbol = self._order_symbol.get(order_id)
            book = self.books.get(symbol) if symbol else None
            if book:
                cancelled = book.cancel_order(order_id)
                if cancelled:
                    self.pub_sock.send_multipart(
                        make_cancelled_msg(
                            gateway_id, order_id, order=cancelled.to_dict()
                        )
                    )
                    self._mark_dirty(symbol)  # type: ignore[arg-type]
            self._order_symbol.pop(order_id, None)
            self._order_to_oco.pop(order_id, None)

        self._oco_groups.pop(oco_id, None)

        log.info(f"OCO {oco_id} cancelled by {gateway_id}")

    def _check_oco_after_event(self, order: Order) -> None:
        """
        Called when an OCO leg reaches a terminal state.
        Cancels the sibling leg and removes the group from tracking.

        Idempotent: it is deliberately invoked from more than one place for
        the same event (the book's callback, then ``_publish_dispatch``).
        The first call removes the group from ``_oco_groups``; later calls
        find nothing and return at the first guard.  Do not "simplify" by
        removing either call site -- the callback is what makes the sibling
        disappear *during* a sweep, the dispatch call covers the rest.
        """
        oco_id = order.oco_group_id
        if not oco_id:
            return
        order_ids = self._oco_groups.get(oco_id)
        if not order_ids:
            return

        sibling_ids = [oid for oid in order_ids if oid != order.id]
        for sibling_id in sibling_ids:
            symbol = self._order_symbol.get(sibling_id)
            book = self.books.get(symbol) if symbol else None
            if book:
                cancelled = book.cancel_order(sibling_id)
                if cancelled:
                    self.pub_sock.send_multipart(
                        make_oco_cancelled_msg(
                            order.gateway_id,
                            oco_id,
                            sibling_id,
                            reason=f"OCO sibling {order.id[:8]} reached {order.status.value}",
                        )
                    )
                    self._mark_dirty(symbol)  # type: ignore[arg-type]
            self._order_symbol.pop(sibling_id, None)
            self._order_to_oco.pop(sibling_id, None)

        self._order_to_oco.pop(order.id, None)
        self._oco_groups.pop(oco_id, None)

        log.info(
            f"OCO {oco_id}: sibling cancelled after {order.id[:8]} {order.status.value}"
        )

    def _handle_cancel(self, payload: dict[str, Any]) -> None:
        """Handle ``order.cancel``: find the order, check ownership, cancel it.

        The engine keeps one global ``order_id -> symbol`` map
        (``_order_symbol``) so it can go straight to the right book without
        searching all of them.  The book itself does the work
        (``OrderBook.cancel_order``: mark the heap entry dead, fix the
        indexes); here we only police who may cancel what and report the
        result.  An unknown or already-finished order id is answered with an
        ORDER_NOT_FOUND reject, never silence.
        """
        self.metrics.count(self.metrics.cancels_in, payload.get("gateway_id"))
        order_id = payload["order_id"]
        gateway_id = str(payload["gateway_id"]).upper()
        request_tag = payload.get("request_tag")
        self._dbg_count("cancel_requests")

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self._dbg_count("cancel_reject_gateway")
            self._reject(
                gateway_id=gateway_id,
                order_id=order_id,
                code=self._gateway_reject_code(reason),
                reason=reason,
                client_tag=None,
                request_tag=request_tag,
            )
            return

        # O(1) lookup via global order→symbol map
        symbol = self._order_symbol.get(order_id)
        book = self.books.get(symbol) if symbol else None

        # Ownership check: a gateway may only cancel its own orders.
        if book is not None:
            resting = book.get_order(order_id)
            if resting is not None and resting.gateway_id != gateway_id:
                self._dbg_count("cancel_reject_ownership")
                self._reject(
                    gateway_id=gateway_id,
                    order_id=order_id,
                    code="NOT_OWNER",
                    reason="Cannot cancel an order owned by another gateway",
                    client_tag=resting.client_tag,
                    request_tag=request_tag,
                )
                return

        cancelled = book.cancel_order(order_id) if book else None

        if cancelled:
            self._dbg_count("cancel_accepted")
            self._order_symbol.pop(order_id, None)
            self.pub_sock.send_multipart(
                make_cancelled_msg(
                    gateway_id,
                    order_id,
                    client_tag=cancelled.client_tag,
                    request_tag=request_tag,
                    order=cancelled.to_dict(),
                )
            )
            self._mark_dirty(cancelled.symbol)
            log.info(f"CANCELLED {order_id[:8]}")
            # If this was a combo child, cascade-cancel the parent combo
            if cancelled.combo_parent_id:
                self._check_combo_after_child_event(cancelled)
            # If this was an OCO leg, cancel the sibling
            if cancelled.oco_group_id:
                self._check_oco_after_event(cancelled)
            return

        # Order not found — send rejection ack
        self._reject(
            gateway_id=gateway_id,
            order_id=order_id,
            code="ORDER_NOT_FOUND",
            reason="Order not found",
            client_tag=None,
            request_tag=request_tag,
        )
        self._dbg_count("cancel_reject_not_found")

    def _handle_amend(self, payload: dict[str, Any]) -> None:
        """Handle ``order.amend``: change price and/or quantity of a resting order.

        An amend is a change to an order that is already on the book, so the
        question that decides everything is: does the order keep its place in
        the queue?  ``OrderBook.amend_order`` answers it -- reducing only the
        quantity keeps time priority; changing the price or increasing the
        quantity sends the order to the back of the queue (``priority_reset``).

        This handler is the gatekeeper around that call, and applies to an
        amend the same protections a new order gets (so amending cannot be
        used to dodge them): parse -> gateway -> find the order -> ownership
        -> tick size -> session -> halt -> collar -> size limits.  Then
        ``book.amend_order``, an ``order.amended`` confirmation, and finally
        the "marketable amend" case below.

        Careful with units: the request carries DISPLAY money for ``price``
        (all other engine-inbound messages carry integer ticks); it is
        converted with ``to_ticks_exact`` here.
        """
        self.metrics.count(self.metrics.amends_in, payload.get("gateway_id"))
        order_id = payload["order_id"]
        gateway_id = str(payload["gateway_id"]).upper()
        new_price = payload.get("price")
        new_qty = payload.get("qty")
        request_tag = payload.get("request_tag")
        self._dbg_count("amend_requests")

        # M12: amend quantity arrives raw from JSON.  Coerce it to int (like
        # prices are converted) so a float/string never propagates into
        # quantity/remaining_qty; reject values that are not a valid number.
        if new_qty is not None:
            try:
                new_qty = int(new_qty)
            except TypeError, ValueError:
                self._dbg_count("amend_reject_payload")
                self._reject(
                    gateway_id=gateway_id,
                    order_id=order_id,
                    code="INVALID_VALUE",
                    reason="Amend quantity must be an integer",
                    client_tag=None,
                    request_tag=request_tag,
                )
                return

        ok, reason = self._gateway_status(gateway_id)
        if not ok:
            self._dbg_count("amend_reject_gateway")
            self._reject(
                gateway_id=gateway_id,
                order_id=order_id,
                code=self._gateway_reject_code(reason),
                reason=reason,
                client_tag=None,
                request_tag=request_tag,
            )
            return

        if new_price is None and new_qty is None:
            self._dbg_count("amend_reject_payload")
            self._reject(
                gateway_id=gateway_id,
                order_id=order_id,
                code="MISSING_FIELD",
                reason="Amend requires at least PRICE or QTY",
                client_tag=None,
                request_tag=request_tag,
            )
            return

        # O(1) lookup via global order→symbol map
        symbol = self._order_symbol.get(order_id)
        book = self.books.get(symbol) if symbol else None
        if book is None:
            self._dbg_count("amend_reject_not_found")
            self._reject(
                gateway_id=gateway_id,
                order_id=order_id,
                code="ORDER_NOT_FOUND",
                reason="Order not found",
                client_tag=None,
                request_tag=request_tag,
            )
            return
        assert symbol is not None

        # Ownership check: a gateway may only amend its own orders.
        resting = book.get_order(order_id)
        if resting is not None and resting.gateway_id != gateway_id:
            self._dbg_count("amend_reject_ownership")
            self._reject(
                gateway_id=gateway_id,
                order_id=order_id,
                code="NOT_OWNER",
                reason="Cannot amend an order owned by another gateway",
                client_tag=resting.client_tag,
                request_tag=request_tag,
            )
            return

        # #9: apply the same gates a NEW order at this price would face, so
        # fat-finger / session / halt protections cannot be bypassed by amending
        # instead of re-entering.
        #
        # The tick gate is one of those. order.amend is the one engine-inbound
        # message that carries display money rather than ticks (the gateways
        # cannot convert it without knowing the resting order's symbol), so
        # unlike order.new this check belongs here — which is also why it
        # covers every transport at once.
        try:
            new_price_ticks = (
                to_ticks_exact(float(new_price), symbol)
                if new_price is not None
                else None
            )
        except TickViolation as exc:
            self._dbg_count("amend_reject_tick")
            self._reject(
                gateway_id=gateway_id,
                order_id=order_id,
                code="TICK_VIOLATION",
                reason=str(exc),
                client_tag=resting.client_tag if resting is not None else None,
                request_tag=request_tag,
            )
            return

        # Session gating — reject amends while the market does not accept orders.
        if self._sessions_enabled and not accepts_orders(self._session_state):
            self._dbg_count("amend_reject_session")
            self._reject(
                gateway_id=gateway_id,
                order_id=order_id,
                code="MARKET_CLOSED",
                reason="Market is closed",
                client_tag=resting.client_tag if resting is not None else None,
                request_tag=request_tag,
            )
            return

        # Matching is disabled while the symbol is halted or the session is a
        # non-continuous phase; a marketable amend then rests without crossing.
        do_match = is_matching_enabled(self._session_state)
        if self._halted_symbols.get(symbol):
            do_match = False

        # Price collar check on the amended price (same band as a new order).
        if self._enforce_collars and new_price_ticks is not None:
            collar = self._collars.get(symbol)
            if collar is not None:
                result = validate_collar(new_price_ticks, collar, book.last_trade_price)
                if result.rejected:
                    self._dbg_count("amend_reject_collar")
                    log.debug(
                        "collar reject order_id=%s symbol=%s price=%s last_trade=%s reason=%s",
                        order_id,
                        symbol,
                        new_price_ticks,
                        book.last_trade_price,
                        result.reason,
                    )
                    self._reject(
                        gateway_id=gateway_id,
                        order_id=order_id,
                        code="COLLAR_BREACH",
                        reason=result.reason,
                        client_tag=resting.client_tag if resting is not None else None,
                        request_tag=request_tag,
                    )
                    return

        # G12: the same order-size / notional caps a new order faces. `new_qty`
        # is the amended order's *total* quantity and `new_price_ticks` its new
        # price; either may be absent, in which case the resting value stands —
        # the same resolution OrderBook.amend_order performs.
        limits = self._order_limits.get(symbol)
        if limits is not None and resting is not None:
            amended_qty = new_qty if new_qty is not None else resting.quantity
            amended_price = (
                new_price_ticks if new_price_ticks is not None else resting.price_ticks
            )
            breach = validate_order_limits(
                amended_qty,
                (
                    from_ticks(amended_price, symbol)
                    if amended_price is not None
                    else None
                ),
                limits,
            )
            if breach is not None:
                self._dbg_count("amend_reject_order_limits")
                log.debug(
                    "order_limits reject order_id=%s symbol=%s qty=%s price=%s reason=%s",
                    order_id,
                    symbol,
                    amended_qty,
                    amended_price,
                    breach[1],
                )
                self._reject(
                    gateway_id=gateway_id,
                    order_id=order_id,
                    code=breach[0],
                    reason=breach[1],
                    client_tag=resting.client_tag,
                    request_tag=request_tag,
                )
                return

        # ---- All gates passed; do the amend. ----
        #
        # Captured before book.amend_order() mutates the resting Order object
        # in place -- resting and amended are the same object once that call
        # returns, so this is the last point old_price/old_qty are readable.
        old_price_ticks = resting.price_ticks if resting is not None else None
        old_qty = resting.quantity if resting is not None else None

        now = now_ns()
        amended, priority_reset, err = book.amend_order(
            order_id,
            new_price=new_price_ticks,
            new_qty=new_qty,
            now=now,
        )

        if amended is None:
            self._dbg_count("amend_reject_book")
            self._reject(
                gateway_id=gateway_id,
                order_id=order_id,
                code=self._amend_reject_code(err),
                reason=err,
                client_tag=resting.client_tag if resting is not None else None,
                request_tag=request_tag,
            )
            return

        # Publish amended confirmation
        self.pub_sock.send_multipart(
            make_amended_msg(
                gateway_id,
                order_id,
                price=(
                    from_ticks(amended.price_ticks, amended.symbol)
                    if amended.price_ticks is not None
                    else None
                ),
                qty=amended.quantity,
                remaining_qty=amended.remaining_qty,
                priority_reset=priority_reset,
                client_tag=amended.client_tag,
                request_tag=request_tag,
                old_price=(
                    from_ticks(old_price_ticks, amended.symbol)
                    if old_price_ticks is not None
                    else None
                ),
                old_qty=old_qty,
                symbol=amended.symbol,
                price_ticks=amended.price_ticks,
                priority_seq=amended.arrival_seq,
            )
        )
        self._dbg_count("amend_accepted")
        self._mark_dirty(amended.symbol)
        prio_str = " (priority reset)" if priority_reset else " (priority kept)"
        log.info(
            f"AMENDED {order_id[:8]} price={amended.price_ticks} "
            f"qty={amended.quantity}{prio_str}"
        )

        # H2: a marketable amend must not leave the book crossed.  If the
        # amended order now crosses the opposite best, pull the re-inserted
        # resting copy and run it through matching (cancel/replace semantics).
        #
        # Why this is needed: amend_order() only repositions the order, it
        # never trades.  Example: resting bid 99, best ask 100; the owner
        # amends the bid to 101.  Left alone the book would show bid 101 >
        # ask 100 with no trade.  So we take the order back out and process it
        # as a fresh aggressive order, exactly as if it had just arrived at
        # 101 -- it then trades with the ask at 100.  (Skipped when matching
        # is off, i.e. during an auction or halt: a crossed book is expected
        # there and resolved by the uncross.)
        if (
            do_match
            and amended.price_ticks is not None
            and amended.status
            not in (
                OrderStatus.FILLED,
                OrderStatus.CANCELLED,
                OrderStatus.REJECTED,
                OrderStatus.EXPIRED,
            )
        ):
            if amended.side == Side.BUY:
                best_ask = book.best_ask_ticks()
                marketable = best_ask is not None and amended.price_ticks >= best_ask
            else:
                best_bid = book.best_bid_ticks()
                marketable = best_bid is not None and amended.price_ticks <= best_bid

            if marketable:
                # The status reset is needed because cancel_order marks the
                # order CANCELLED; process() would otherwise treat it as dead.
                # Remove the resting copy (deducts qty index, invalidates entry)
                # then re-process the same order through the matching path.
                book.cancel_order(order_id)
                amended.status = OrderStatus.NEW
                trades, events = book.process(amended, match=True, now=now)
                self._publish_dispatch(trades, events)
                self._mark_dirty(amended.symbol)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _resting_gtc_orders(self) -> list[Order]:
        """Resting orders that should survive a restart.

        Covers both TIF=GTC and TIF=DAY: a process restart is no longer a
        day boundary (see docs-design/EduMatcher-Revised-Quote-Persistence.md
        §12-§13) — DAY orders persist here the same as GTC ones, and are
        purged instead at startup restore if their business day has passed
        (Engine._restore_gtc). Quote legs (origin=QUOTE) are no longer a
        special case: they persist by the same TIF rule as any other order
        (see §5.2 of the same document). `_restore_gtc` rebuilds
        `self._quote_index` from restored quote-origin orders so a
        surviving quote is fully quote-managed again after restart, not
        just resting as a plain order — see §5.3.
        """
        resting: list[Order] = []
        for book in self.books.values():
            for order in book.resting_orders():
                if order.tif in (TIF.GTC, TIF.DAY):
                    resting.append(order)
        return resting

    def _flush_persistence(self, force: bool = False) -> None:
        """Checkpoint the resting book, at most once per interval.

        Persisting only at shutdown meant the entire resting book was lost to
        anything that was not a polite exit — SIGKILL, OOM, container
        eviction, power loss, or any unhandled exception in the loop. This
        bounds that loss to the checkpoint interval instead.

        Unlike :meth:`_shutdown`, this never mutates state: it does not
        expire anything and publishes nothing, so it is safe to run
        mid-session on the poll tick.
        """
        now = time.monotonic()
        if not force and now - self._last_persist < _PERSIST_INTERVAL_SEC:
            return
        self._last_persist = now
        started = time.perf_counter()
        try:
            save_gtc_orders(self._resting_gtc_orders(), GTC_ORDERS_FILE)
            save_gtc_combos(list(self._combos.values()), GTC_COMBOS_FILE)
            save_book_stats(self.books, BOOK_STATS_FILE)
            self.metrics.gtc_flush_ms = (time.perf_counter() - started) * 1000.0
        except Exception as exc:
            # A failed checkpoint must not end the session — the previous
            # checkpoint is still intact on disk because the writes are
            # atomic, so the correct response is to complain and carry on.
            self._dbg_count("persist_errors")
            log.error("Checkpoint failed: %s", exc)
        else:
            self._dbg_count("persist_checkpoints")

    def _shutdown(self) -> None:
        log.info("Shutting down …")
        self._running = False

        # A process exit (clean or otherwise) is not a day boundary — TIF=DAY
        # orders are no longer expired here. Both TIF=GTC and TIF=DAY resting
        # orders are persisted and restored on the next startup; a TIF=DAY
        # order is only discarded there if its business day has already
        # passed (Engine._restore_gtc). True end-of-day expiry is driven by
        # the scheduler's transition to CLOSED (Engine._expire_tif), which is
        # unaffected by this change. See
        # docs-design/EduMatcher-Revised-Quote-Persistence.md §12-§13.
        #
        # Combos are out of scope for that design: save_gtc_combos() below
        # still persists only TIF.GTC combo parents, so a restored TIF.DAY
        # combo leg (now persisted here as a plain order, since it is no
        # longer expired) comes back with a combo_parent_id that no longer
        # resolves to anything in self._combos/_order_to_combo — it restores
        # as an ordinary standalone resting order, silently detached from
        # its former combo. _check_combo_after_child_event() no-ops safely
        # on the unresolved id rather than raising, so this is a known,
        # scoped-out limitation, not a crash risk.
        #
        # Quote-origin orders (MM quote legs) are also no longer excluded
        # here: they persist by the same TIF rule as any other resting
        # order. See docs-design/EduMatcher-Revised-Quote-Persistence.md §5.
        all_resting = self._resting_gtc_orders()
        save_gtc_orders(all_resting, GTC_ORDERS_FILE)
        log.info(f"Saved {len(all_resting)} resting order(s) to {GTC_ORDERS_FILE}")

        # Persist resting GTC combos
        save_gtc_combos(list(self._combos.values()), GTC_COMBOS_FILE)
        n_combos = sum(
            1
            for c in self._combos.values()
            if c.tif == TIF.GTC
            and c.status in (ComboStatus.PENDING, ComboStatus.PARTIALLY_MATCHED)
        )
        if n_combos:
            log.info(f"Saved {n_combos} GTC combo(s) to {GTC_COMBOS_FILE}")

        save_book_stats(self.books, BOOK_STATS_FILE)
        log.info(
            f"Saved book statistics for {len(self.books)} symbol(s) to {BOOK_STATS_FILE}"
        )

        # The books as they end, for the audit (S25), then the broadcast EOD
        # -- subscribers record closing prices before sockets close.
        self._publish_checkpoints("EOD")
        eod_books = [book.snapshot() for book in self.books.values()]
        self.pub_sock.send_multipart(make_eod_msg(eod_books))

        self.pull_sock.close()
        self.pub_sock.close()
        if self._drop_copy is not None:
            self._drop_copy.close()
        if self._reporter is not None:
            self._reporter.stop()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    #: A dispatched topic ending in this is a read query, not a decision the
    #: exchange made. Queries are excluded from the command echo below — see
    #: `_echo_command`. Derived rather than listed so a new command is
    #: recorded automatically and a new query is not.
    _QUERY_SUFFIX = "_request"

    def _echo_command(self, topic: str, frames: list[bytes]) -> bool:
        """Re-publish an inbound command so the audit trail contains it.

        Returns whether the message is now in the trail, because nothing the
        engine publishes next may cite an id no reader can find.

        `pm-audit` subscribes to this PUB socket and nothing else, and ZMQ
        PUSH/PULL cannot be tapped — so without this, no command the exchange
        was ever asked to perform is recorded. Every effect cites a
        `causation_id` naming a message that exists nowhere, and a command
        that produced *no* effect leaves no trace at all: a cancel the engine
        ignored, a request rejected before any handler ran. That last case is
        the whole reason this is worth doing.

        The frames are re-published exactly as received, including the
        sender's own envelope frame — see `CausalPublisher.send_with_envelope`
        for why the id must not be re-minted. Nothing is decoded, encoded or
        copied, which is what makes this about half the cost of an ordinary
        publish.

        Called *before* dispatch, which is a deliberate trade of about two
        microseconds of order-to-ack latency for two properties:

        **The raw log reads in causal order.** Re-publishing after the handler
        would still narrate correctly — the sender's ULID was minted before any
        of the effects, and `pm-audit-replay` orders by that — but nothing else
        does. `pm-audit-cli timeline`, `grep` and `less` show receipt order, and
        a request appearing after its own ack is the kind of thing a reader
        spends an hour on before concluding it was an artefact.

        **The record survives a hard crash inside the handler.** Write-ahead
        ordering: the command the post-mortem most needs is the one whose
        handling did not finish. A `finally` would cover a handler that raises,
        but not a segfault or a SIGKILL mid-dispatch.

        Best-effort regardless: a raise here would escape the receive loop and
        end it. Recording must never be able to stop the exchange.
        """
        if (
            len(frames) < 3
            or topic.endswith(self._QUERY_SUFFIX)
            or topic == TOPIC_GATEWAY_HEARTBEAT
        ):
            # Fewer than three frames means no envelope: a client that builds
            # its own PUSH socket instead of going through `make_pusher`.
            # There is no id to preserve, and minting one would invent a
            # causal root that nothing cites.
            return False
        try:
            self.pub_sock.send_with_envelope(frames[:2], frames[2])
        except Exception as exc:  # pragma: no cover - transport failure
            self._dbg_count("command_echo_failures")
            log.warning("Command echo failed for %s: %s", topic, exc)
            return False
        return True

    def _dispatch_pull_message(self, topic: str, payload: dict[str, Any]) -> None:
        """Route one decoded PULL-socket message to its handler.

        Every branch is wrapped in a single try/except so one bad message
        can never take down the receive loop. A topic that matches no
        branch falls into the `else` below rather than being silently
        dropped: it's logged at WARNING (visible by default, no need to
        raise the log level) and counted in `self._unknown_topic_count` so
        the gap is observable instead of invisible. This is a deliberate
        third failure mode, distinct from `self._error_count` (a *known*
        handler raised) — "no handler is registered for this topic at all"
        is a routing/completeness bug, not a runtime exception, and
        operators benefit from being able to tell the two apart.

        When a *known* handler raises, the except path also sends a reject —
        see `_reject_after_error`. Logging alone left the submitting gateway
        waiting on an ack that would never arrive.
        """
        fills_before = self._fills_published
        try:
            if topic == TOPIC_ORDER_NEW:
                self._handle_new_order(payload)
            elif topic == TOPIC_ORDER_CANCEL:
                self._handle_cancel(payload)
            elif topic == TOPIC_ORDER_AMEND:
                self._handle_amend(payload)
            elif topic == TOPIC_ORDER_COMBO:
                self._handle_combo_order(payload)
            elif topic == TOPIC_ORDER_COMBO_CANCEL:
                self._handle_combo_cancel(payload)
            elif topic == TOPIC_ORDER_OCO:
                self._handle_oco_order(payload)
            elif topic == TOPIC_ORDER_OCO_CANCEL:
                self._handle_oco_cancel(payload)
            elif topic == TOPIC_QUOTE_NEW:
                self._handle_quote_new(payload)
            elif topic == TOPIC_QUOTE_CANCEL:
                self._handle_quote_cancel(payload)
            elif topic == TOPIC_GATEWAY_CONNECT:
                self._handle_gateway_connect(payload)
            elif topic == TOPIC_GATEWAY_DISCONNECT:
                self._handle_gateway_disconnect(payload)
            elif topic == TOPIC_GATEWAY_HEARTBEAT:
                self._handle_gateway_heartbeat(payload)
            elif topic == TOPIC_SYMBOLS_REQUEST:
                self._handle_symbols_request(payload)
            elif topic == TOPIC_REFERENCE_REQUEST:
                self._handle_reference_request(payload)
            elif topic == TOPIC_REFERENCE_RELOAD:
                self._handle_reference_reload(payload)
            elif topic == TOPIC_BOOK_SNAPSHOT_REQUEST:
                self._handle_book_snapshot_request(payload)
            elif topic == TOPIC_ORDERS_REQUEST:
                self._handle_orders_request(payload)
            elif topic == TOPIC_PRICE_LEVEL_ORDERS_REQUEST:
                self._handle_price_level_orders_request(payload)
            elif topic == TOPIC_QUOTE_BOOTSTRAP_REQUEST:
                self._handle_quote_bootstrap_request(payload)
            elif topic == TOPIC_QUOTE_LEGS_REQUEST:
                self._handle_quote_legs_request(payload)
            elif topic == TOPIC_KILL_SWITCH:
                self._handle_kill_switch(payload)
            elif topic == TOPIC_KILL_SWITCH_GATEWAY:
                self._handle_kill_switch_gateway(payload)
            elif topic == TOPIC_KILL_SWITCH_GLOBAL:
                self._handle_kill_switch_global(payload)
            elif topic == TOPIC_CIRCUIT_BREAKER_HALT_ALL:
                self._handle_circuit_breaker_halt_all(payload)
            elif topic == TOPIC_CIRCUIT_BREAKER_RESUME_ALL:
                self._handle_circuit_breaker_resume_all(payload)
            elif topic == TOPIC_SYMBOL_HALT:
                self._handle_symbol_halt(payload)
            elif topic == TOPIC_SYMBOL_RESUME:
                self._handle_symbol_resume(payload)
            elif topic == TOPIC_CANCEL_SYMBOL:
                self._handle_cancel_symbol(payload)
            elif topic == TOPIC_FORCE_UNCROSS:
                self._handle_force_uncross(payload)
            elif topic == TOPIC_SESSION_TRANSITION:
                self._handle_session_transition(payload)
            elif topic == TOPIC_SESSION_NEXT:
                self._handle_session_next(payload)
            elif topic == TOPIC_SESSION_STATE_REQUEST:
                self._handle_session_state_request(payload)
            elif topic == TOPIC_SESSION_SCHEDULE_REQUEST:
                self._handle_session_schedule_request(payload)
            elif topic == TOPIC_GATEWAYS_REQUEST:
                self._handle_gateways_request(payload)
            elif topic == TOPIC_VOLUME_REQUEST:
                self._handle_volume_request(payload)
            elif topic == TOPIC_HALT_STATUS_REQUEST:
                self._handle_halt_status_request(payload)
            elif topic == TOPIC_RISK_STATE_REQUEST:
                self._handle_risk_state_request(payload)
            elif topic == TOPIC_POSITION_REQUEST:
                self._handle_position_request(payload)
            else:
                self._unknown_topic_count += 1
                log.warning(
                    "No dispatch handler for topic %s (#%d) — " "message dropped",
                    topic,
                    self._unknown_topic_count,
                )
                self.pub_sock.send_multipart(
                    make_diagnostic_msg(
                        component="UNROUTED_TOPIC",
                        detail=topic,
                        count=self._unknown_topic_count,
                    )
                )
        except Exception as exc:
            self._dbg_count("handler_errors")
            self._error_count += 1
            log.error(
                "Error processing %s (#%d): %s",
                topic,
                self._error_count,
                exc,
            )
            # Wire-visible marker with the real exception text -- the
            # client-facing reject below deliberately stays generic (see
            # _reject_after_error's docstring), so this is the only place a
            # post-mortem can see what actually broke without grepping the
            # process log. Best-effort: a publish failure here must not
            # shadow the original exception or skip the reject below.
            try:
                self.pub_sock.send_multipart(
                    make_diagnostic_msg(
                        component="DISPATCH_ERROR",
                        detail=topic,
                        error=str(exc),
                        count=self._error_count,
                    )
                )
            except Exception:
                log.error("Diagnostic publish for %s failed", topic)
            self._reject_after_error(topic, payload, fills_before)
        # What the command's book changes did not publish yet (an amend's
        # new priority, a stop that only armed).
        if self._trace:
            self._flush_trace()

    def _reject_after_error(
        self, topic: str, payload: dict[str, Any], fills_before: int
    ) -> None:
        """Answer an order whose handler raised, so its fate is not indefinite.

        Every other path through the order handlers terminates in an ACK or a
        reasoned NACK. An exception part-way through used to terminate in
        neither, and the difference is not visible to the client: the API
        gateway eventually raises TimeoutError, which is indistinguishable
        from a slow engine, and ALF/BALF simply wait forever.

        Two distinct reasons, because a bare "rejected" is a lie if anything
        already printed. `fills_before` is the fill count as of entry to the
        handler, so a fill published during the handler — even one belonging
        to a *resting counterparty* rather than this order — moves the reject
        to the partial-execution wording. That is deliberately conservative:
        over-warning costs a participant a reconciliation against the drop
        copy, while under-warning tells them an executed order never traded.
        """
        if topic not in _ORDER_TOPICS:
            return
        gateway_id = str(payload.get("gateway_id", ""))
        order_id = payload.get("order_id") or payload.get("id")
        if not gateway_id or not order_id:
            # Nothing to address: the payload that broke the handler may be
            # the very thing missing these fields. Say so rather than
            # pretending the contract held.
            log.error(
                "No reject sent for %s — payload carries no gateway_id/order_id",
                topic,
            )
            return
        if self._fills_published > fills_before:
            reason = (
                "Internal error after execution — "
                "fills already printed, reconcile against the drop copy"
            )
        else:
            reason = "Internal error processing order"
        try:
            self._reject(
                gateway_id=gateway_id,
                order_id=str(order_id),
                code="INTERNAL_ERROR",
                reason=reason,
                client_tag=(
                    str(payload["client_tag"])
                    if payload.get("client_tag") is not None
                    else None
                ),
                request_tag=(
                    str(payload["request_tag"])
                    if payload.get("request_tag") is not None
                    else None
                ),
            )
        except Exception as send_exc:
            # The reject is best-effort: raising here would escape run() and
            # take the venue down over a message that already failed once.
            log.error("Reject for %s could not be sent: %s", order_id, send_exc)
        else:
            log.info("REJECTED %s — %s", str(order_id)[:8], reason)

    def attach_reporter(
        self, reporter: HealthReporter, book_metrics_interval_sec: float = 10.0
    ) -> None:
        """Ship this engine's metrics through ``reporter`` (from main())."""
        self._reporter = reporter
        self._book_metrics_interval_sec = book_metrics_interval_sec

    def _flush_metrics(self) -> None:
        """Publish the beacon's application metrics when the reporter is due."""
        reporter = self._reporter
        if reporter is None or not reporter.due():
            return
        reporter.publish(self.metric_samples())

    def metric_samples(self, *, now: float | None = None) -> list[MetricSample]:
        """Every engine metric of design §8.2-§8.4, read from live state.

        Book gauges are O(books) and refreshed only every
        ``book_metrics_interval_sec``; in between the previous ones are reused.
        Starts a new latency/busy interval.
        """
        now = time.monotonic() if now is None else now
        m = self.metrics
        out = m.counter_samples()
        out.extend(m.timing_samples())

        connected_by_role: dict[str, int] = {}
        connected: set[str] = set()
        for session in self._sessions.values():
            if session.connected:
                role = session.role.value
                connected_by_role[role] = connected_by_role.get(role, 0) + 1
                connected.add(m.label(session.gateway_id))
        out.append(gauge("engine.participants_connected", len(connected)))
        for role, n in sorted(connected_by_role.items()):
            out.append(gauge("engine.participants_connected", n, role))
        for label in sorted(m.known_gateways | connected):
            out.append(gauge("engine.participant_connected", label in connected, label))

        resting: dict[str, int] = {label: 0 for label in m.known_gateways}
        for book in self.books.values():
            for gateway_id, n in book.resting_count_by_gateway():
                label = m.label(gateway_id)
                resting[label] = resting.get(label, 0) + n
        for label, n in sorted(resting.items()):
            out.append(gauge("engine.resting_orders", n, label))

        for symbol, book in sorted(self.books.items()):
            trades, qty, value_ticks = m.trade_totals(book)
            out.append(counter("engine.trades", trades, symbol))
            out.append(counter("engine.traded_qty", qty, symbol))
            out.append(
                counter("engine.traded_value", from_ticks(value_ticks, symbol), symbol)
            )
            out.append(
                gauge(
                    "engine.book_halted",
                    self._halted_symbols.get(symbol, False),
                    symbol,
                )
            )

        for component, n in (
            ("DISPATCH_ERROR", self._error_count),
            ("UNROUTED_TOPIC", self._unknown_topic_count),
            ("UNDECODABLE_MESSAGE", self._undecodable_count),
            ("MAINTENANCE_FLUSH", self._flush_error_count),
        ):
            out.append(counter("engine.diagnostics", n, component))

        out.append(gauge("engine.books", len(self.books)))
        out.append(
            gauge(
                "engine.session_state",
                SESSION_STATE_ORDER.index(self._session_state),
            )
        )
        out.append(gauge("engine.halted_symbols", sum(self._halted_symbols.values())))
        out.append(gauge("engine.gtc_flush_ms", m.gtc_flush_ms))

        if now >= self._next_book_metrics:
            self._next_book_metrics = now + self._book_metrics_interval_sec
            self._book_metric_samples = book_samples(
                self.books[symbol] for symbol in sorted(self.books)
            )
        out.extend(self._book_metric_samples)
        return out

    def _run_maintenance(self) -> None:
        """Run the per-tick maintenance flushes, each guarded separately.

        Every one of these publishes on `pub_sock`. Unguarded, a ZMQError
        here ended run() — which skipped _shutdown(), and with it the only
        code that persisted the resting book. Degraded market data is a much
        smaller loss than the book.

        Guarded per call rather than as a block, because a failure to publish
        a snapshot must not skip the circuit-breaker timers behind it: those
        resume halted symbols and are a safety function, not a convenience.
        """
        for flush in (
            # Throttled snapshot publish — runs every poll tick (max 200ms)
            self._flush_snapshots,
            # Check circuit breaker timers — resume halted symbols
            self._flush_circuit_breakers,
            # Checkpoint the resting book so an abrupt exit loses at most
            # _PERSIST_INTERVAL_SEC of changes rather than all of it.
            self._flush_persistence,
            # Publish where each symbol would uncross, while a call phase runs
            self._flush_auction_indicative,
            self._flush_debug_summary,
            self._expire_silent_gateways,
            # Hand the health beacon its samples; guarded like the rest, so a
            # bug in metrics code cannot stop the circuit-breaker timers.
            self._flush_metrics,
        ):
            try:
                flush()
            except Exception as exc:
                self._flush_error_count += 1
                flush_name = getattr(flush, "__name__", "?")
                log.error(
                    "Maintenance flush %s failed (#%d): %s",
                    # getattr, not .__name__: a handler that raises while
                    # reporting a failure defeats the guard entirely.
                    flush_name,
                    self._flush_error_count,
                    exc,
                )
                # Best-effort, and itself guarded: this publish must never
                # become the reason a maintenance-flush failure skips the
                # circuit-breaker timers behind it (see this method's
                # docstring) or takes down run()'s poll loop.
                try:
                    self.pub_sock.send_multipart(
                        make_diagnostic_msg(
                            component="MAINTENANCE_FLUSH",
                            detail=flush_name,
                            error=str(exc),
                            count=self._flush_error_count,
                        )
                    )
                except Exception:
                    log.error("Diagnostic publish for flush %s failed", flush_name)

    def run(self) -> None:
        """Start the engine and serve messages until SIGINT / SIGTERM.

        The whole exchange is this one ``while`` loop, on one thread:

            wait up to 200 ms for a message on the PULL socket
              -> if one arrived: decode it, echo it, ``_dispatch_pull_message``
            run the maintenance tick (snapshots, timers, persistence)

        Because nothing else runs concurrently, an order is always handled
        start to finish -- ack, matching, fills, trades published -- before the
        next one is even looked at.  That is the guarantee behind price-time
        priority: "arrival order" is simply the order messages come off the
        socket.  The 200 ms poll timeout only bounds how long maintenance can
        be delayed on an idle exchange; under load the loop never waits.
        """
        run_seq = load_and_bump_run_seq(RUN_SEQ_FILE)
        set_run_seq(run_seq)
        self._startup(run_seq)

        # Create drop copy publisher here (not in __init__) so that unit tests
        # that call handlers directly never attempt to bind ZMQ port 5557.
        try:
            self._drop_copy = DropCopyPublisher(
                zmq.Context.instance(),
                buffer_size=self.drop_copy_buffer_size,
            )
            log.info("Drop copy PUB bound on port 5557")
        except zmq.ZMQError as exc:
            log.warning("Drop copy unavailable — %s", exc)

        self._running = True

        poller = zmq.Poller()
        poller.register(self.pull_sock, zmq.POLLIN)

        log.info(
            f"Listening on PULL={ENGINE_PULL_BIND_ADDR}  PUB={ENGINE_PUB_BIND_ADDR}"
        )

        # Signal handlers only set the stop flag.  Calling _shutdown() directly
        # from a signal handler is unsafe: the handler can interrupt mid-message
        # (e.g. inside _handle_new_order) and close pub_sock while the handler
        # still holds references, causing unhandled ZMQErrors in _flush_snapshots.
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "_running", False))
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "_running", False))

        # Health instrumentation, bound once: the loop below runs per message.
        # Message and pass counts are locals, and only 1 in SAMPLE_EVERY
        # messages / maintenance passes is timed (design A4.10, I31).
        metrics = self.metrics
        clock_ns = time.perf_counter_ns
        tick = self._reporter.tick if self._reporter is not None else None
        msg_count = 0
        pass_count = 0
        metrics.watch_gc()

        while self._running:
            if tick is not None:
                tick()
            try:
                # Blocks until a message arrives OR 200 ms pass (so the
                # maintenance tick below still runs on a quiet market).
                socks = dict(poller.poll(timeout=200))  # 200 ms tick
            except zmq.ZMQError:
                break
            if self.pull_sock in socks:
                # Receiving and decoding sit inside the guard, not only the
                # dispatch behind them. decode() raises on input any peer
                # controls — a single frame, malformed JSON, a non-UTF8 topic
                # — and the PULL socket accepts from anyone who connects,
                # with gateway identity checked inside the handlers, i.e.
                # after this point. Unguarded, one such message ended the loop,
                # which skipped _shutdown() and with it the only code that
                # persisted the resting book.
                #   frames  = [topic, JSON payload, (optional) envelope]
                #   topic   = e.g. "order.new"; payload = dict of the request
                #   cause   = the sender's message id, for audit causality
                try:
                    frames = self.pull_sock.recv_multipart()
                    topic, payload = decode(frames)
                    cause = decode_push_envelope(frames)
                except Exception as exc:
                    # No decodable topic means no gateway to reject to, so the
                    # message can only be discarded — but it is counted, so
                    # the condition is visible rather than silent.
                    self._undecodable_count += 1
                    self._dbg_count("undecodable_messages")
                    log.warning(
                        "Discarding undecodable PULL message (#%d): %s",
                        self._undecodable_count,
                        exc,
                    )
                    # No topic to report (that is exactly what failed to
                    # decode) -- detail is left empty, per
                    # spec/messages/system.yaml::diagnostic.
                    try:
                        self.pub_sock.send_multipart(
                            make_diagnostic_msg(
                                component="UNDECODABLE_MESSAGE",
                                error=str(exc),
                                count=self._undecodable_count,
                            )
                        )
                    except Exception:
                        log.error("Diagnostic publish for undecodable message failed")
                else:
                    self._dbg_count("pull_messages")
                    self._dbg_count(f"topic_{topic}")
                    # Everything published while handling this message is
                    # attributed to it, and inherits its causal chain. Cleared
                    # in `finally` so a handler that raises cannot leak the
                    # attribution onto the next message, or onto maintenance
                    # work below — which has no external cause and must not
                    # claim one.
                    if cause is None:
                        self._dbg_count("pull_messages_without_envelope")
                    # Record the request before acting on it. Placing this
                    # after the dispatch would cost no order-to-ack latency
                    # and still narrate correctly -- the sender's ULID was
                    # minted before every effect, and pm-audit-replay orders
                    # by that -- but the raw log would then show a command
                    # after its own ack, which is a trap for everyone reading
                    # the file with grep. The ~2 us buys causal order in the
                    # bytes, and a record that survives a crash mid-dispatch.
                    recorded = self._echo_command(topic, frames)
                    # Attribute the effects to it only if it IS in the trail.
                    # A query is deliberately not echoed, so a reply citing it
                    # names a message the engine chose never to publish —
                    # indistinguishable, to any reader, from one that was
                    # dropped. A read's answer starts its own chain instead.
                    self.pub_sock.set_cause(cause if recorded else None)
                    msg_count += 1
                    sampled = not msg_count & SAMPLE_MASK or metrics.sample_next
                    gc_before = metrics.gc_ns if sampled else 0
                    started_ns = clock_ns() if sampled else 0
                    # ---- The message is handled HERE, to completion. ----
                    # Timing is sampled (1 in N messages), so the clock reads
                    # around this call cost nothing on the other N-1.
                    try:
                        self._dispatch_pull_message(topic, payload)
                    finally:
                        self.pub_sock.clear_cause()
                        if sampled:
                            metrics.record_dispatch(
                                clock_ns() - started_ns,
                                msg_count,
                                started_ns=started_ns,
                                gc_ns=metrics.gc_ns - gc_before,
                                order=topic in _ORDER_ENTRY_TOPICS,
                            )
            pass_count += 1
            if pass_count & SAMPLE_MASK:
                self._run_maintenance()
            else:
                started_ns = clock_ns()
                self._run_maintenance()
                metrics.record_maintenance(
                    clock_ns() - started_ns, pass_count, msg_count
                )

        metrics.unwatch_gc()
        self._flush_debug_summary(force=True)
        self._shutdown()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EduMatcher matching engine")
    add_version_argument(parser, "pm-engine")
    parser.add_argument(
        "--log-level",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
        help="Logging level override (default: WARNING)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase log verbosity (-v: INFO, -vv: DEBUG)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Reduce log output to warnings/errors",
    )
    parser.add_argument(
        "--log-target",
        choices=["server", "stdout", "file"],
        default=None,
        help=(
            "Where this process's own operational log records go: "
            "server (default, auto-detected pm-log-srv), stdout, or file"
        ),
    )
    parser.add_argument(
        "--log-file",
        default=None,
        metavar="PATH",
        help="Operational log file path — required when --log-target file",
    )
    parser.add_argument(
        "--log-failover-timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Grace window before falling back to a local log file once "
            "pm-log-srv becomes unreachable (default: 30, from config)"
        ),
    )
    return parser


def _configure_logging(args: argparse.Namespace) -> int:
    log_level = getattr(args, "log_level", None)
    verbose = getattr(args, "verbose", 0)
    quiet = getattr(args, "quiet", False)

    if log_level:
        level_name = str(log_level).upper()
        level = getattr(logging, level_name, logging.WARNING)
    elif verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    elif quiet:
        level = logging.WARNING
    else:
        level = logging.WARNING

    client_config = load_default_log_client_config()
    server_config = load_default_log_server_config()
    failover_timeout = getattr(args, "log_failover_timeout", None)
    handler = resolve_handler(
        log_target=getattr(args, "log_target", None),
        log_file=getattr(args, "log_file", None),
        client_name=_CLIENT_NAME,
        instance=None,
        host=resolve_host_default(),
        port=server_config.port,
        connect_timeout_sec=client_config.connect_timeout_sec,
        failover_timeout_sec=(
            failover_timeout
            if failover_timeout is not None
            else client_config.failover_timeout_sec
        ),
        failover_dir=client_config.failover_dir,
    )
    logging.basicConfig(level=level, format=_LOG_FORMAT, handlers=[handler])
    return int(level)


def main() -> None:
    from edumatcher.config_artifact import report_deployment

    parser = build_parser()
    args = parser.parse_args()
    log_level = _configure_logging(args)
    log.info("starting pm-engine with log level %s", logging.getLevelName(log_level))
    report_deployment(log)
    engine = Engine()
    reporter = HealthReporter.from_compiled_config(_CLIENT_NAME)
    if reporter is not None:
        from edumatcher.monitor.config import load_default_monitor_config

        engine.attach_reporter(
            reporter, load_default_monitor_config().book_metrics_interval_sec
        )
        reporter.start()
    engine.run()


if __name__ == "__main__":
    main()

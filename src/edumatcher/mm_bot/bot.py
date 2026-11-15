"""MMBot — state machine and event loop for the market-maker bot.

Supports quoting one symbol (today's default shape) or several symbols at
once from a single process behind a single gateway ID. See
docs-design/EduMatcher-MM-Bot-review.md §5a for the design rationale: the
engine has no per-gateway symbol limit (QuoteIndex keys quotes by
``(gateway_id, symbol)``), so multi-symbol support is purely a matter of
this bot tracking one ``_SymbolState`` per symbol instead of holding scalar
per-symbol attributes on ``self``.
"""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
import logging
import random
import signal
import time
from enum import Enum
from typing import Any

import zmq

from edumatcher.health import HealthReporter, counter, gauge
from edumatcher.messaging.bus import PushSocket, make_pusher, make_subscriber
from edumatcher.models.generated.health import MetricSample
from edumatcher.models.envelope import new_ulid
from edumatcher.models.price import (
    get_tick_decimals,
    register_tick_decimals,
    to_ticks,
)
from edumatcher.models.message import (
    GATEWAY_HEARTBEAT_INTERVAL_SEC,
    decode,
    make_book_snapshot_request_msg,
    make_gateway_connect_msg,
    make_gateway_disconnect_msg,
    make_gateway_heartbeat_msg,
    make_position_request_msg,
    make_quote_bootstrap_request_msg,
    make_quote_cancel_msg,
    make_quote_legs_request_msg,
    make_quote_new_msg,
    make_session_state_request_msg,
    make_symbols_request_msg,
)
from edumatcher.mm_bot.params import TIER2_DEFAULTS
from edumatcher.mm_bot.pricer import PassiveParams, PricingStrategy, create_strategy
from edumatcher.config import SIM_PUB_ADDR
from edumatcher.models.generated.sim import TOPIC_SIM_VALUE
from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED
from edumatcher.models.generated.session import TOPIC_SESSION_STATE
from edumatcher.models.generated.circuit_breaker import (
    topic_circuit_breaker_halt,
    topic_circuit_breaker_resume,
)
from edumatcher.models.generated.book import (
    PREFIX_BOOK_SNAPSHOT,
    topic_book_snapshot,
)
from edumatcher.models.generated.order import (
    topic_order_cancelled,
    topic_order_fill,
)
from edumatcher.models.generated.quote import (
    topic_quote_ack,
    topic_quote_status,
)
from edumatcher.models.generated.system import (
    topic_gateway_auth,
    topic_position_snapshot,
    topic_quote_bootstrap,
    topic_quote_legs,
    topic_session_status,
    topic_symbols,
)

log = logging.getLogger(__name__)


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
_DEBUG_SUMMARY_INTERVAL_SEC = 5.0
#: Shortest interval between two passes of the timers over every symbol: the
#: poll timeout's floor. Ticking after every message cost most of the bot's
#: CPU at 300 symbols, where messages arrive in the thousands a second.
_TICK_MIN_SEC = 0.05
#: With a health reporter attached the quoting loop wakes at least this often,
#: so its designed idle wait stays well under pm-monitor's 1 s DEGRADED line
#: for ``loop_lag_ms``; a patient symbol's 2.5 s poll read as a late loop
#: forever (review R8). A few idle wake-ups a second cost nothing.
_LIVENESS_POLL_MS = 500


def _update_position(
    prior_position: int,
    prior_avg_cost: float,
    side: str,
    fill_qty: int,
    fill_price: float,
) -> tuple[int, float]:
    """Update a signed net position and VWAP average cost after one fill.

    Same cross-zero-through-flat algorithm as
    ``engine/main.py::MatchingEngine._update_position`` (kept in sync
    deliberately -- both compute the same ledger from the same fills, one
    server-side per gateway, one here purely local to this bot): buying
    adds to the position, selling subtracts. Average cost is recomputed
    (volume-weighted) when the position grows in its current direction,
    held steady when a fill only reduces it, reset to the fill price when
    a single fill crosses the position through zero to the other side, and
    zeroed out exactly at flat.

    Returns (new_position, new_avg_cost).
    """
    if side == "BUY":
        new_position = prior_position + fill_qty
        if prior_position >= 0:
            # Opening or adding to a long position.
            new_cost = (
                prior_avg_cost * prior_position + fill_price * fill_qty
            ) / new_position
        elif new_position < 0:
            # Reducing a short, still net short: avg_cost unchanged.
            new_cost = prior_avg_cost
        elif new_position == 0:
            # Closed the short exactly flat.
            new_cost = 0.0
        else:
            # Crossed from short to long: reset cost to fill price.
            new_cost = fill_price
    else:  # SELL
        new_position = prior_position - fill_qty
        if prior_position <= 0:
            # Opening or adding to a short position.
            abs_new = abs(new_position)
            new_cost = (
                prior_avg_cost * abs(prior_position) + fill_price * fill_qty
            ) / abs_new
        elif new_position > 0:
            # Reducing a long, still net long: avg_cost unchanged.
            new_cost = prior_avg_cost
        elif new_position == 0:
            # Closed the long exactly flat.
            new_cost = 0.0
        else:
            # Crossed from long to short: reset cost to fill price.
            new_cost = fill_price

    return new_position, (new_cost if new_position != 0 else 0.0)


@dataclass
class _SymbolState:
    """Everything MMBot tracks that is scoped to one symbol.

    One instance per symbol the bot quotes. A single-symbol bot (today's
    default shape) holds exactly one of these; a multi-symbol bot holds one
    per ``--symbols`` entry, each progressing through the same state machine
    independently — a fill, cancel, drift, or QLEGS divergence on one symbol
    never touches another symbol's entry.
    """

    tick_size: float = 0.01
    # The symbol's MM obligation, set only when the engine enforces it for
    # this gateway (an unenforced one is not applied by the engine either).
    mm_max_spread_ticks: int | None = None
    mm_min_qty: int | None = None
    gap: float = 0.0
    gap_was_explicit: bool = False
    pricer: PricingStrategy | None = None
    state: BotState = BotState.CONNECTING
    quote_id: str | None = None
    # The id of the last quote.new sent; with quote_id, what counts as this
    # symbol's current quote when a quote.status arrives (an ack can be lost).
    sent_quote_id: str | None = None
    bid_order_id: str | None = None
    ask_order_id: str | None = None
    quoted_at_mid: float | None = None
    reissue_at: float | None = None
    last_quote_sent_at: float = 0.0
    last_qlegs_reconcile: float = 0.0
    last_heartbeat: float = 0.0
    awaiting_cancel_for_reissue: bool = False
    pending_fills: list[dict[str, Any]] = field(default_factory=list)
    # Quote rejections since the last accepted quote, and the reasons already
    # reported at WARNING in that run (later ones of a reason go to DEBUG).
    consecutive_rejects: int = 0
    reject_reasons_warned: set[str] = field(default_factory=set)
    # --- Tier-2 parameters. Resolved before construction (CLI scopes and/or
    # the config file, see mm_bot/resolve.py) and fixed for the run, except
    # `gap`, which startup may derive from the symbol's MM spread obligation
    # when the operator did not choose one.
    strategy: str = "symmetric"
    qty: int = 500
    max_position: int | None = None
    drift_ticks: int = 3
    tif: str = "DAY"
    reissue_delay_sec: float = 0.2
    heartbeat_interval_sec: float = 5.0
    bootstrap_timeout_sec: float = 1.0
    cancel_timeout_sec: float = 1.0
    qlegs_reconcile_interval_sec: float = 15.0
    initial_min: float | None = None
    initial_max: float | None = None
    # passive-strategy knobs; ignored by every other strategy.
    retreat_ticks: int = TIER2_DEFAULTS["retreat_ticks"]
    behind_ticks: int = TIER2_DEFAULTS["behind_ticks"]
    min_cover_qty: int = TIER2_DEFAULTS["min_cover_qty"]
    fade_ticks: int = TIER2_DEFAULTS["fade_ticks"]
    fade_sec: float = TIER2_DEFAULTS["fade_sec"]
    # Pull the mid toward pm-market-sim's true value (0 = off), and the last
    # value seen for this symbol.
    anchor_sim: float = TIER2_DEFAULTS["anchor_sim"]
    sim_value: float | None = None
    # Where this bot's own legs rest and how much of each is left, so the
    # passive strategy can remove them from book snapshots (_others_levels).
    # Set when a quote is sent or adopted; cleared with the quote state.
    own_bid_price: float | None = None
    own_ask_price: float | None = None
    own_bid_qty: int = 0
    own_ask_qty: int = 0
    # Set once the symbol has failed a startup check (§5a.4 per-symbol
    # failure isolation) so the rest of the bot can skip it without
    # crashing the whole process. None while startup is still in progress
    # or has succeeded.
    startup_failed_reason: str | None = None
    # Net position and VWAP average cost: seeded from the engine's
    # per-gateway ledger at start-up (system.position_request), then kept up
    # to date locally from this symbol's own fills (see _update_position).
    # Feeds the "inventory_skew" pricing strategy; unused by "symmetric".
    net_position: int = 0
    avg_cost: float = 0.0


#: Tier-2 constructor keys whose ``_SymbolState`` field has the same name.
_DIRECT_PARAM_KEYS = (
    "gap",
    "gap_was_explicit",
    "strategy",
    "qty",
    "max_position",
    "drift_ticks",
    "tif",
    "heartbeat_interval_sec",
    "bootstrap_timeout_sec",
    "cancel_timeout_sec",
    "qlegs_reconcile_interval_sec",
    "initial_min",
    "initial_max",
    "retreat_ticks",
    "behind_ticks",
    "min_cover_qty",
    "fade_ticks",
    "fade_sec",
    "anchor_sim",
)


def _others_levels(
    levels: list[dict[str, Any]],
    own_price: float | None,
    own_qty: int,
    tick_size: float,
) -> list[tuple[float, int]]:
    """Book levels as (price, qty) with this bot's own leg taken out.

    A level is only reduced when it holds at least the bot's remaining leg
    quantity — a snapshot published before the leg reached the book (or
    after it left) is then passed through unchanged instead of having some
    other trader's quantity subtracted. A level whose only order was the
    bot's leg disappears.
    """
    out: list[tuple[float, int]] = []
    for lvl in levels:
        price = float(lvl.get("price", 0.0))
        qty = int(lvl.get("qty", 0))
        count = int(lvl.get("count", 1))
        if (
            own_price is not None
            and own_qty > 0
            and round(price / tick_size) == round(own_price / tick_size)
            and qty >= own_qty
        ):
            if count <= 1:
                continue
            qty -= own_qty
        out.append((price, qty))
    return out


def _price_text(symbol: str, price: float | None, extra_digits: int = 0) -> str:
    """A price for a log line, at the symbol's tick precision (a mid, which
    can fall between ticks, with ``extra_digits`` more) — not a raw float
    such as ``150.51999999999998``."""
    if price is None:
        return "None"
    return f"{price:.{get_tick_decimals(symbol) + extra_digits}f}"


def _make_symbol_state(symbol: str, params: dict[str, Any], now: float) -> _SymbolState:
    """Build one symbol's state from its resolved Tier-2 parameters."""
    unknown = set(params) - set(_DIRECT_PARAM_KEYS) - {"reissue_delay_ms"}
    if unknown:
        raise ValueError(
            f"[{symbol}] unknown parameter(s): {', '.join(sorted(unknown))}"
        )
    state = _SymbolState(
        **{key: params[key] for key in _DIRECT_PARAM_KEYS if key in params}
    )
    # The wire/CLI unit is milliseconds; everything inside the bot is
    # seconds, matching time.monotonic().
    state.reissue_delay_sec = params["reissue_delay_ms"] / 1000.0
    state.last_heartbeat = now
    return state


class MMBot:
    """Autonomous market-maker bot for one or more symbols.

    A single ``--symbol AAPL`` invocation (or the ``symbol=`` constructor
    kwarg) behaves exactly as before this class supported multiple symbols.
    Passing ``symbols=["AAPL", "MSFT", ...]`` instead quotes all of them
    from one process behind one gateway ID — see
    docs-design/EduMatcher-MM-Bot-review.md §5a.
    """

    def __init__(
        self,
        *,
        gateway_id: str,
        symbol: str | None = None,
        symbols: list[str] | None = None,
        strategy: str,
        gap: float,
        gap_was_explicit: bool,
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
        max_position: int | None = None,
        overrides: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        resolved_symbols = _resolve_symbols_arg(symbol=symbol, symbols=symbols)

        self.gateway_id = gateway_id
        self.symbols = resolved_symbols
        self.verbose = verbose

        self._startup_session_timeout_sec = startup_session_timeout_sec
        self._shutdown_timeout_sec = shutdown_timeout_sec
        self._engine_pull = engine_pull
        self._engine_pub = engine_pub

        # Runtime state
        self._running = False
        # Set by SIGINT/SIGTERM and shutdown(): start-up's waits read it, so a
        # stop during start-up ends it without quoting.
        self._stop_requested = False
        self._session_state: str | None = None

        # Every keyword argument above is the baseline applied to *every*
        # symbol; `overrides[symbol]` replaces individual Tier-2 values for
        # one symbol on top of it. A single-symbol bot never needs
        # `overrides` at all, which is why the baseline is still a flat
        # keyword list rather than a mandatory per-symbol structure.
        baseline: dict[str, Any] = {
            "gap": gap,
            "gap_was_explicit": gap_was_explicit,
            "strategy": strategy,
            "qty": qty,
            "max_position": max_position,
            "drift_ticks": drift_ticks,
            "tif": tif,
            "reissue_delay_ms": reissue_delay_ms,
            "heartbeat_interval_sec": heartbeat_interval_sec,
            "bootstrap_timeout_sec": bootstrap_timeout_sec,
            "cancel_timeout_sec": cancel_timeout_sec,
            "qlegs_reconcile_interval_sec": qlegs_reconcile_interval_sec,
            "initial_min": initial_min,
            "initial_max": initial_max,
        }
        now = time.monotonic()
        unknown_symbols = set(overrides or {}) - set(resolved_symbols)
        if unknown_symbols:
            raise ValueError(
                "overrides names symbol(s) this bot does not quote: "
                f"{', '.join(sorted(unknown_symbols))}"
            )
        self._symbols_state: dict[str, _SymbolState] = {
            sym: _make_symbol_state(
                sym, {**baseline, **(overrides or {}).get(sym, {})}, now
            )
            for sym in resolved_symbols
        }

        # quote.ack and quote.status are per-*gateway* topics, and quote.status
        # carries quote_id but not symbol, so a multi-symbol bot maps one to
        # the other itself. `_send_quote` mints the quote_id and the engine
        # echoes it on every reply, so this is populated at **send** time —
        # early enough that a status for a quote rejected or cancelled before
        # its ack still resolves.
        #
        # Bounded: a bot that reissues every few seconds would otherwise
        # accumulate an entry per quote for the life of the process. Only the
        # most recent few per symbol can still attract a late quote.status, so
        # older entries are evicted in insertion order.
        # Per-symbol topic -> (kind, symbol), so a message finds its symbol
        # with one lookup instead of building every symbol's topics (P1).
        self._symbol_topics: dict[str, tuple[str, str]] = {}
        for sym in resolved_symbols:
            self._symbol_topics[topic_book_snapshot(sym)] = ("book", sym)
            self._symbol_topics[topic_circuit_breaker_halt(sym)] = ("halt", sym)
            self._symbol_topics[topic_circuit_breaker_resume(sym)] = ("resume", sym)

        self._quote_id_to_symbol: OrderedDict[str, str] = OrderedDict()
        self._quote_id_index_cap = max(32, 8 * len(resolved_symbols))

        # Every leg order id this bot has quoted -> (symbol, "BID"/"ASK"),
        # current and retired. The engine may publish a quote's
        # quote.status INACTIVE_* (and the sibling's cancel) before the
        # order.fill that caused it (engine/main.py `_publish_dispatch`), and
        # a partly filled leg keeps resting until the reissue replaces it, so
        # a fill routinely arrives for a leg the bot no longer tracks as its
        # current quote. Bounded like the quote-id index above.
        self._leg_to_symbol: OrderedDict[str, tuple[str, str]] = OrderedDict()
        self._leg_index_cap = max(64, 16 * len(resolved_symbols))

        self._pending_fills: list[dict[str, Any]] = []
        # The start-up QBOOT reply, kept for the reference-price step.
        self._boot_payload: dict[str, Any] | None = None
        self._debug_counts: defaultdict[str, int] = defaultdict(int)
        # Health beacon (operator dashboard, B5.4): main() attaches a reporter.
        self._reporter: HealthReporter | None = None
        self._msgs_out = 0
        self._msgs_in = 0
        self._debug_last_summary = time.monotonic()

        # Engine session: authenticated, and when it last heard from us. The
        # engine frees the gateway ID after three missed beats, so a bot that
        # dies without a disconnect does not block its own restart.
        self._authenticated = False
        self._last_engine_heartbeat = 0.0

        # Sockets (created in run())
        self._push_sock: PushSocket | None = None
        self._sub_sock: zmq.Socket[bytes] | None = None

    # ------------------------------------------------------------------
    # Backward-compatible single-symbol accessors
    #
    # These proxy to self._symbols_state[self._primary_symbol] — the first
    # symbol in self.symbols. Every pre-multi-symbol test, and any external
    # code, that touches bot.symbol / bot._quote_id / bot._pricer / etc.
    # directly keeps working unchanged for a bot constructed with exactly
    # one symbol, since there is only ever one entry to proxy to. Do not
    # use these from new multi-symbol-aware code — index
    # self._symbols_state[symbol] explicitly instead.
    # ------------------------------------------------------------------

    @property
    def _primary_symbol(self) -> str:
        return self.symbols[0]

    @property
    def symbol(self) -> str:
        return self._primary_symbol

    @property
    def _primary(self) -> _SymbolState:
        return self._symbols_state[self._primary_symbol]

    @property
    def gap(self) -> float:
        return self._primary.gap

    @gap.setter
    def gap(self, value: float) -> None:
        self._primary.gap = value

    @property
    def net_position(self) -> int:
        """Locally tracked net position for the primary (or only) symbol.

        For a multi-symbol bot, index ``self._symbols_state[symbol]
        .net_position`` directly instead.
        """
        return self._primary.net_position

    @property
    def avg_cost(self) -> float:
        """Locally tracked VWAP average cost for the primary (or only)
        symbol. 0.0 when flat. See ``net_position`` for the multi-symbol
        equivalent."""
        return self._primary.avg_cost

    @property
    def _tick_size(self) -> float:
        return self._primary.tick_size

    @_tick_size.setter
    def _tick_size(self, value: float) -> None:
        self._primary.tick_size = value

    @property
    def _mm_max_spread_ticks(self) -> int | None:
        return self._primary.mm_max_spread_ticks

    @_mm_max_spread_ticks.setter
    def _mm_max_spread_ticks(self, value: int | None) -> None:
        self._primary.mm_max_spread_ticks = value

    @property
    def _pricer(self) -> PricingStrategy | None:
        return self._primary.pricer

    @_pricer.setter
    def _pricer(self, value: PricingStrategy | None) -> None:
        self._primary.pricer = value

    @property
    def _state(self) -> BotState:
        return self._primary.state

    @_state.setter
    def _state(self, value: BotState) -> None:
        self._primary.state = value

    @property
    def _quote_id(self) -> str | None:
        return self._primary.quote_id

    @_quote_id.setter
    def _quote_id(self, value: str | None) -> None:
        self._primary.quote_id = value

    @property
    def _bid_order_id(self) -> str | None:
        return self._primary.bid_order_id

    @_bid_order_id.setter
    def _bid_order_id(self, value: str | None) -> None:
        self._primary.bid_order_id = value

    @property
    def _ask_order_id(self) -> str | None:
        return self._primary.ask_order_id

    @_ask_order_id.setter
    def _ask_order_id(self, value: str | None) -> None:
        self._primary.ask_order_id = value

    @property
    def _quoted_at_mid(self) -> float | None:
        return self._primary.quoted_at_mid

    @_quoted_at_mid.setter
    def _quoted_at_mid(self, value: float | None) -> None:
        self._primary.quoted_at_mid = value

    @property
    def _reissue_at(self) -> float | None:
        return self._primary.reissue_at

    @_reissue_at.setter
    def _reissue_at(self, value: float | None) -> None:
        self._primary.reissue_at = value

    @property
    def _last_quote_sent_at(self) -> float:
        return self._primary.last_quote_sent_at

    @_last_quote_sent_at.setter
    def _last_quote_sent_at(self, value: float) -> None:
        self._primary.last_quote_sent_at = value

    @property
    def _last_qlegs_reconcile(self) -> float:
        return self._primary.last_qlegs_reconcile

    @_last_qlegs_reconcile.setter
    def _last_qlegs_reconcile(self, value: float) -> None:
        self._primary.last_qlegs_reconcile = value

    @property
    def _awaiting_cancel_for_reissue(self) -> bool:
        return self._primary.awaiting_cancel_for_reissue

    @_awaiting_cancel_for_reissue.setter
    def _awaiting_cancel_for_reissue(self, value: bool) -> None:
        self._primary.awaiting_cancel_for_reissue = value

    @property
    def strategy(self) -> str:
        return self._primary.strategy

    @strategy.setter
    def strategy(self, value: str) -> None:
        self._primary.strategy = value

    @property
    def qty(self) -> int:
        return self._primary.qty

    @qty.setter
    def qty(self, value: int) -> None:
        self._primary.qty = value

    @property
    def drift_ticks(self) -> int:
        return self._primary.drift_ticks

    @drift_ticks.setter
    def drift_ticks(self, value: int) -> None:
        self._primary.drift_ticks = value

    @property
    def tif(self) -> str:
        return self._primary.tif

    @tif.setter
    def tif(self, value: str) -> None:
        self._primary.tif = value

    @property
    def _max_position(self) -> int | None:
        return self._primary.max_position

    @_max_position.setter
    def _max_position(self, value: int | None) -> None:
        self._primary.max_position = value

    @property
    def _reissue_delay_sec(self) -> float:
        return self._primary.reissue_delay_sec

    @_reissue_delay_sec.setter
    def _reissue_delay_sec(self, value: float) -> None:
        self._primary.reissue_delay_sec = value

    @property
    def _heartbeat_interval_sec(self) -> float:
        return self._primary.heartbeat_interval_sec

    @_heartbeat_interval_sec.setter
    def _heartbeat_interval_sec(self, value: float) -> None:
        self._primary.heartbeat_interval_sec = value

    @property
    def _bootstrap_timeout_sec(self) -> float:
        return self._primary.bootstrap_timeout_sec

    @_bootstrap_timeout_sec.setter
    def _bootstrap_timeout_sec(self, value: float) -> None:
        self._primary.bootstrap_timeout_sec = value

    @property
    def _cancel_timeout_sec(self) -> float:
        return self._primary.cancel_timeout_sec

    @_cancel_timeout_sec.setter
    def _cancel_timeout_sec(self, value: float) -> None:
        self._primary.cancel_timeout_sec = value

    @property
    def _qlegs_reconcile_interval_sec(self) -> float:
        return self._primary.qlegs_reconcile_interval_sec

    @_qlegs_reconcile_interval_sec.setter
    def _qlegs_reconcile_interval_sec(self, value: float) -> None:
        self._primary.qlegs_reconcile_interval_sec = value

    @property
    def _initial_min(self) -> float | None:
        return self._primary.initial_min

    @_initial_min.setter
    def _initial_min(self, value: float | None) -> None:
        self._primary.initial_min = value

    @property
    def _initial_max(self) -> float | None:
        return self._primary.initial_max

    @_initial_max.setter
    def _initial_max(self, value: float | None) -> None:
        self._primary.initial_max = value

    @property
    def _last_heartbeat(self) -> float:
        return self._primary.last_heartbeat

    @_last_heartbeat.setter
    def _last_heartbeat(self, value: float) -> None:
        # Kept as a whole-bot setter: tests and the startup path reset "the"
        # heartbeat clock, and with one clock per symbol that means all of
        # them.
        for st in self._symbols_state.values():
            st.last_heartbeat = value

    # Kept as a real instance attribute (not proxied) intentionally: the
    # pre-ack fill buffer historically held fills for the *one* symbol
    # before its first quote.ack, buffered before the bot even knows which
    # _SymbolState a fill belongs to (that mapping only exists once a quote
    # has been sent — see _handle_order_fill). A multi-symbol bot buffers
    # here the same way; _process_pending_fills re-dispatches each one
    # through the normal, now symbol-aware, order_fill handling.
    @property
    def _pending_fills_compat(self) -> list[dict[str, Any]]:
        return self._pending_fills

    def _log(self, text: str) -> None:
        log.info("[%s] %s", self.gateway_id, text)

    def _warn(self, text: str) -> None:
        # Startup failures must be visible without --verbose: the bot exits
        # (or drops a symbol) because of them.
        log.warning("[%s] startup warning: %s", self.gateway_id, text)

    def _debug(self, text: str) -> None:
        # verbose (-v/-vv) previously gated this via a private print() channel;
        # kept at INFO (rather than DEBUG) so -v alone still shows these, same
        # as before the print()-to-logger conversion.
        if self.verbose:
            self._log(text)

    def _dbg_count(self, key: str, amount: int = 1) -> None:
        if not self.verbose:
            return
        self._debug_counts[key] += amount
        self._flush_debug_summary()

    def _flush_debug_summary(self, force: bool = False) -> None:
        if not self.verbose:
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
        self._debug(f"flow summary: {summary}")
        self._debug_counts.clear()
        self._debug_last_summary = now

    def _set_state(self, symbol: str, new_state: "BotState") -> None:
        st = self._symbols_state[symbol]
        if new_state is st.state:
            return
        self._debug(f"[{symbol}] state: {st.state.value} -> {new_state.value}")
        st.state = new_state

    @staticmethod
    def _topic_family(topic: str) -> str:
        if topic.startswith(PREFIX_BOOK_SNAPSHOT):
            return "book"
        if topic.startswith("trade."):
            return "trade"
        if topic.startswith("quote."):
            return "quote"
        if topic.startswith("order."):
            return "order"
        if topic.startswith("session."):
            return "session"
        if topic.startswith("system."):
            return "system"
        if topic.startswith("circuit_breaker."):
            return "circuit_breaker"
        return "other"

    def _active_symbols(self) -> list[str]:
        """Symbols still in play — excludes any that failed startup (§5a.4)."""
        return [
            sym
            for sym, st in self._symbols_state.items()
            if st.startup_failed_reason is None
        ]

    def _poll_timeout_ms(self, active: list[str]) -> int:
        """How long the event loop may block before running the timers.

        Half the shortest timing interval of any active symbol, so the most
        impatient symbol's reissue/heartbeat still fires promptly, with a
        50 ms floor — ``reissue_delay_sec`` may legitimately be 0, and
        without the floor that would spin.
        """
        shortest_sec = min(
            min(
                self._symbols_state[sym].heartbeat_interval_sec,
                self._symbols_state[sym].reissue_delay_sec,
            )
            for sym in active
        )
        return max(50, int(shortest_sec * 1000 / 2))

    def _setup_sockets(self) -> None:
        self._push_sock = make_pusher(self._engine_pull)
        per_symbol_topics: list[str] = []
        for sym in self.symbols:
            per_symbol_topics.append(topic_book_snapshot(sym))
            per_symbol_topics.append(topic_circuit_breaker_halt(sym))
            per_symbol_topics.append(topic_circuit_breaker_resume(sym))
        self._sub_sock = make_subscriber(
            self._engine_pub,
            topic_gateway_auth(self.gateway_id),
            topic_symbols(self.gateway_id),
            topic_quote_bootstrap(self.gateway_id),
            topic_quote_legs(self.gateway_id),
            TOPIC_TRADE_EXECUTED,
            topic_order_fill(self.gateway_id),
            topic_order_cancelled(self.gateway_id),
            topic_quote_ack(self.gateway_id),
            topic_quote_status(self.gateway_id),
            TOPIC_SESSION_STATE,
            topic_session_status(self.gateway_id),
            topic_position_snapshot(self.gateway_id),
            *per_symbol_topics,
        )
        if any(st.anchor_sim > 0 for st in self._symbols_state.values()):
            # The same socket also listens to pm-market-sim's own PUB.
            self._sub_sock.connect(SIM_PUB_ADDR)
            self._sub_sock.setsockopt(zmq.SUBSCRIBE, TOPIC_SIM_VALUE.encode())

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
            self._msgs_out += 1
            self._dbg_count("outgoing_total")
            if frames:
                topic = frames[0].decode("utf-8", errors="replace")
                self._dbg_count(f"outgoing_topic_{self._topic_family(topic)}")

    def _send_quietly(self, frames: list[bytes]) -> bool:
        """Send, or return False while the engine is not reachable.

        The engine PUSH socket never blocks, so until the connection is up
        (the engine still starting, or restarting) a send raises zmq.Again.
        """
        try:
            self._send(frames)
        except zmq.Again:
            return False
        return True

    def _send_engine_heartbeat(self, now: float) -> None:
        self._send_quietly(make_gateway_heartbeat_msg(self.gateway_id))
        self._last_engine_heartbeat = now

    def _authenticate(self, timeout_sec: float = 3.0) -> bool:
        """Send gateway_connect and wait for auth ACK."""
        assert self._sub_sock is not None
        deadline = time.monotonic() + timeout_sec
        time.sleep(0.05)
        while not self._send_quietly(make_gateway_connect_msg(self.gateway_id)):
            if time.monotonic() >= deadline or self._stop_requested:
                self._log("engine not reachable")
                return False
            time.sleep(0.1)
        for sym in self.symbols:
            self._set_state(sym, BotState.AUTHENTICATING)

        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)

        while time.monotonic() < deadline and not self._stop_requested:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            socks = dict(poller.poll(timeout=min(remaining_ms, 200)))
            if self._sub_sock not in socks:
                continue
            topic, payload = decode(self._sub_sock.recv_multipart())
            if topic == topic_gateway_auth(self.gateway_id):
                accepted = bool(payload.get("accepted", False))
                if accepted:
                    self._log("authenticated")
                    self._authenticated = True
                    self._send_engine_heartbeat(time.monotonic())
                else:
                    reason = str(payload.get("reason", "unknown"))
                    self._warn(f"auth rejected: {reason}")
                return accepted
            # Also capture session.state that arrives during auth
            if topic == TOPIC_SESSION_STATE:
                self._session_state = str(payload.get("state", "")).upper()
                self._debug(f"session state (during auth): {self._session_state}")

        self._warn("authentication timed out")
        return False

    def _request_symbols(self, timeout_sec: float = 3.0) -> list[str]:
        """Request symbol list and register tick/MM-obligation metadata.

        Registers metadata for every symbol this bot quotes that appears in
        the reply. A symbol that never appears is left for the startup
        sequence to fail closed on (single-symbol: whole-process failure,
        same as before; multi-symbol: that one symbol excluded — see
        _run_loop and §5a.4).
        """
        assert self._sub_sock is not None
        self._send(make_symbols_request_msg(self.gateway_id))

        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        deadline = time.monotonic() + timeout_sec

        while time.monotonic() < deadline and not self._stop_requested:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            socks = dict(poller.poll(timeout=min(remaining_ms, 200)))
            if self._sub_sock not in socks:
                continue
            topic, payload = decode(self._sub_sock.recv_multipart())
            if topic == topic_symbols(self.gateway_id):
                entries = payload.get("symbols", [])
                symbols = [str(e.get("symbol", "")).upper() for e in entries]
                self._debug(f"symbols received: {symbols}")
                for meta in entries:
                    meta_symbol = str(meta.get("symbol", "")).upper()
                    st = self._symbols_state.get(meta_symbol)
                    if st is None:
                        continue
                    if "tick_decimals" in meta:
                        tick_decimals = int(meta["tick_decimals"])
                        st.tick_size = 10**-tick_decimals
                        register_tick_decimals(meta_symbol, tick_decimals)
                    # The engine applies the obligation only when it enforces
                    # it; the reply carries the values either way.
                    if meta.get("enforce_mm_obligation") is True:
                        for key in ("mm_max_spread_ticks", "mm_min_qty"):
                            try:
                                setattr(st, key, int(meta[key]))
                            except KeyError, TypeError, ValueError:
                                setattr(st, key, None)
                return symbols
            if topic == TOPIC_SESSION_STATE:
                self._session_state = str(payload.get("state", "")).upper()

        self._log("symbols request timed out")
        return []

    def _startup_reply_timeout_sec(self) -> float:
        """How long the gateway-wide QBOOT/QLEGS waits last: the longest
        ``bootstrap_timeout_sec`` of any symbol."""
        return max(st.bootstrap_timeout_sec for st in self._symbols_state.values())

    def _request_bootstrap(self) -> dict[str, Any] | None:
        """Request QBOOT for every symbol of this gateway (an empty symbol
        filter) and wait for the reply within the timeout.

        One request for the gateway, not one per symbol: the reply topic is
        per gateway, so per-symbol waits could take each other's late reply.
        """
        assert self._sub_sock is not None
        self._send(make_quote_bootstrap_request_msg(self.gateway_id, ""))

        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        deadline = time.monotonic() + self._startup_reply_timeout_sec()

        while time.monotonic() < deadline and not self._stop_requested:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            socks = dict(poller.poll(timeout=min(remaining_ms, 100)))
            if self._sub_sock not in socks:
                continue
            topic, payload = decode(self._sub_sock.recv_multipart())
            if topic == topic_quote_bootstrap(self.gateway_id):
                return payload
            # Capture other events during wait
            self._buffer_event(topic, payload)

        self._debug("QBOOT request timed out — continuing with fallback")
        return None

    def _request_qlegs(self) -> dict[str, Any] | None:
        """Request the QLEGS snapshot of every symbol of this gateway and
        wait for the reply (see `_request_bootstrap`)."""
        assert self._sub_sock is not None
        self._send(make_quote_legs_request_msg(self.gateway_id, "", "ACTIVE"))

        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        deadline = time.monotonic() + self._startup_reply_timeout_sec()

        while time.monotonic() < deadline and not self._stop_requested:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            socks = dict(poller.poll(timeout=min(remaining_ms, 100)))
            if self._sub_sock not in socks:
                continue
            topic, payload = decode(self._sub_sock.recv_multipart())
            if topic == topic_quote_legs(self.gateway_id):
                return payload
            self._buffer_event(topic, payload)

        self._debug("QLEGS request timed out")
        return None

    def _buffer_event(self, topic: str, payload: dict[str, Any]) -> None:
        """Buffer events received during startup waits."""
        if topic == TOPIC_SESSION_STATE:
            self._session_state = str(payload.get("state", "")).upper()
            return
        kind, sym = self._symbol_topics.get(topic, ("", ""))
        if kind == "book":
            self._handle_book(payload, symbol=sym)
            return
        if topic == TOPIC_TRADE_EXECUTED:
            self._handle_trade(payload)
        elif topic == topic_order_fill(self.gateway_id):
            # A fill on an adopted quote; one before the position snapshot is
            # replaced by the snapshot, which already holds it.
            self._handle_order_fill(payload)

    def _seed_positions(self) -> None:
        """Take each symbol's net position and average cost from the engine.

        The snapshot overwrites whatever was counted so far: fills the
        engine published before it are in it, later ones follow it on the
        same PUB stream. Without a reply the positions stay at zero.
        """
        assert self._sub_sock is not None
        self._send(make_position_request_msg(self.gateway_id))
        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        deadline = time.monotonic() + self._startup_reply_timeout_sec()

        while time.monotonic() < deadline and not self._stop_requested:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            socks = dict(poller.poll(timeout=min(remaining_ms, 100)))
            if self._sub_sock not in socks:
                continue
            topic, payload = decode(self._sub_sock.recv_multipart())
            if topic != topic_position_snapshot(self.gateway_id):
                self._buffer_event(topic, payload)
                continue
            held = {
                str(p.get("symbol", "")).upper(): p
                for p in payload.get("positions", [])
            }
            for symbol, st in self._symbols_state.items():
                entry = held.get(symbol, {})
                st.net_position = int(entry.get("net_qty", 0))
                st.avg_cost = float(entry.get("avg_cost", 0.0))
                if hasattr(st.pricer, "update_position"):
                    st.pricer.update_position(st.net_position)  # type: ignore[union-attr]
                if st.net_position:
                    self._log(
                        f"[{symbol}] position from the engine: {st.net_position} "
                        f"@ {st.avg_cost}"
                    )
            return

        self._warn(
            "no position snapshot from the engine; positions start at 0 "
            "(inventory_skew quotes as if flat)"
        )

    def _try_adopt_from_bootstrap(
        self, symbol: str, boot_payload: dict[str, Any] | None
    ) -> bool:
        """Try to adopt an active quote from QBOOT. Returns True if adopted."""
        if not boot_payload:
            return False
        st = self._symbols_state[symbol]
        assert st.pricer is not None

        quotes = boot_payload.get("quotes", [])
        for q in quotes:
            if (
                str(q.get("symbol", "")).upper() == symbol
                and str(q.get("state", "")).upper() == "ACTIVE"
            ):
                st.quote_id = str(q.get("quote_id", ""))
                st.bid_order_id = str(q.get("bid_order_id", ""))
                st.ask_order_id = str(q.get("ask_order_id", ""))
                if st.quote_id:
                    self._quote_id_to_symbol[st.quote_id] = symbol
                self._index_legs(symbol, st.bid_order_id, st.ask_order_id)
                bid_price = q.get("bid_price")
                ask_price = q.get("ask_price")
                if bid_price is not None and ask_price is not None:
                    mid = (float(bid_price) + float(ask_price)) / 2.0
                    st.pricer.set_mid(mid)
                    st.quoted_at_mid = mid
                    st.own_bid_price, st.own_ask_price = (
                        float(bid_price),
                        float(ask_price),
                    )
                    st.own_bid_qty = int(q.get("bid_qty", st.qty))
                    st.own_ask_qty = int(q.get("ask_qty", st.qty))
                    self._log(
                        f"[{symbol}] adopted existing quote {st.quote_id} "
                        f"bid={bid_price} ask={ask_price}"
                    )
                    return True
        return False

    def _resolve_bootstrap_reference(
        self, boot_payload: dict[str, Any] | None, symbol: str | None = None
    ) -> bool:
        """Resolve initial reference price (non-adopt). Returns True if resolved."""
        symbol = symbol if symbol is not None else self._primary_symbol
        st = self._symbols_state[symbol]
        assert st.pricer is not None

        # 1. Book- or trade-derived mid. Book updates and trade.executed events
        #    received during startup waits already set the mid via the handlers,
        #    so any existing mid covers both the book and last-trade fallbacks.
        if st.pricer.mid_price is not None:
            self._debug(
                f"[{symbol}] reference from book/trade: "
                f"{_price_text(symbol, st.pricer.mid_price, 1)}"
            )
            return True

        # 2. QBOOT inactive quote prices as reference
        if boot_payload:
            quotes = boot_payload.get("quotes", [])
            for q in quotes:
                if str(q.get("symbol", "")).upper() == symbol:
                    bid_price = q.get("bid_price")
                    ask_price = q.get("ask_price")
                    if bid_price is not None and ask_price is not None:
                        mid = (float(bid_price) + float(ask_price)) / 2.0
                        st.pricer.set_mid(mid)
                        self._debug(
                            f"[{symbol}] reference from bootstrap quote: "
                            f"{_price_text(symbol, mid, 1)}"
                        )
                        return True

        # 3. Random bootstrap range
        if st.initial_min is not None and st.initial_max is not None:
            price = random.uniform(st.initial_min, st.initial_max)
            # Round to nearest tick
            price = round(
                round(price / st.tick_size) * st.tick_size,
                st.pricer.price_decimals,
            )
            st.pricer.set_mid(price)
            self._log(
                f"[{symbol}] bootstrap from random range: {_price_text(symbol, price)}"
            )
            return True

        return False

    def _wait_for_session(self, timeout_sec: float) -> bool:
        """Learn the session phase. Returns True if known in time.

        ``session.state`` is only broadcast on a transition, so the phase is
        also asked for: a bot started while the market sits in one phase
        (closed overnight, say) would otherwise wait for the next transition
        and give up.
        """
        if self._session_state is not None:
            return True

        assert self._sub_sock is not None
        self._send(make_session_state_request_msg(self.gateway_id))
        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        deadline = time.monotonic() + timeout_sec

        while time.monotonic() < deadline and not self._stop_requested:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            socks = dict(poller.poll(timeout=min(remaining_ms, 200)))
            if self._sub_sock not in socks:
                continue
            topic, payload = decode(self._sub_sock.recv_multipart())
            if topic in (TOPIC_SESSION_STATE, topic_session_status(self.gateway_id)):
                self._session_state = str(payload.get("state", "")).upper()
                return True
            self._buffer_event(topic, payload)

        return False

    def _send_quote(self, symbol: str | None = None) -> None:
        """Compute prices and send a fresh quote for one symbol."""
        symbol = symbol if symbol is not None else self._primary_symbol
        st = self._symbols_state[symbol]
        assert st.pricer is not None
        if st.pricer.mid_price is None:
            self._debug(f"[{symbol}] cannot send quote — no mid price")
            return

        prior_quoted_mid = st.quoted_at_mid
        bid, ask = st.pricer.compute_prices()
        if st.max_position is not None and abs(st.net_position) >= st.max_position:
            log.debug(
                "[%s] inventory skew saturated: net_position=%d max_position=%d bid=%s ask=%s",
                symbol,
                st.net_position,
                st.max_position,
                bid,
                ask,
            )
        log.debug(
            "[%s] requote: prior_quoted_mid=%s current_mid=%s new_bid=%s new_ask=%s net_position=%d",
            symbol,
            prior_quoted_mid,
            st.pricer.mid_price,
            bid,
            ask,
            st.net_position,
        )
        quote_id = f"{self.gateway_id}-{symbol}-{new_ulid()}"
        quote_payload: dict[str, Any] = {
            "gateway_id": self.gateway_id,
            "symbol": symbol,
            # The pricer works in display money; the wire carries ticks
            # (design section 15.2, quotes joined in 6.1b).
            "tick_decimals": get_tick_decimals(symbol),
            "bid_price_ticks": to_ticks(bid, symbol),
            "ask_price_ticks": to_ticks(ask, symbol),
            "bid_qty": st.qty,
            "ask_qty": st.qty,
            "tif": st.tif,
            # Client-supplied correlation id. The engine echoes it on
            # quote.ack, stamps it on both leg orders, and carries it on
            # quote.status — it only mints one of its own when the client
            # sends none (engine/main.py: `if not quote_id`). Supplying it
            # here is what lets every reply be matched to this symbol by id
            # instead of by arrival order.
            "quote_id": quote_id,
        }
        self._send(make_quote_new_msg(quote_payload))
        st.quoted_at_mid = st.pricer.mid_price
        st.own_bid_price, st.own_ask_price = bid, ask
        st.own_bid_qty = st.own_ask_qty = st.qty
        st.last_quote_sent_at = time.monotonic()
        st.sent_quote_id = quote_id
        self._set_state(symbol, BotState.REISSUING)
        # Indexed at send time, not ack time: quote.status for a quote that is
        # rejected or cancelled before its ack is processed would otherwise
        # arrive with a quote_id this bot had never heard of.
        self._quote_id_to_symbol[quote_id] = symbol
        while len(self._quote_id_to_symbol) > self._quote_id_index_cap:
            self._quote_id_to_symbol.popitem(last=False)
        self._debug(f"[{symbol}] QUOTE sent bid={bid} ask={ask}")

    def _index_legs(self, symbol: str, bid_order_id: str, ask_order_id: str) -> None:
        """Remember which symbol and side two leg order ids belong to."""
        for order_id, side in ((bid_order_id, "BID"), (ask_order_id, "ASK")):
            if order_id:
                self._leg_to_symbol[order_id] = (symbol, side)
        while len(self._leg_to_symbol) > self._leg_index_cap:
            self._leg_to_symbol.popitem(last=False)

    def _cancel_quote(self, symbol: str) -> None:
        """Send quote.cancel for one symbol."""
        self._send(make_quote_cancel_msg(self.gateway_id, symbol))
        self._debug(f"[{symbol}] CANCEL sent")

    def _clear_quote_state(self, symbol: str) -> None:
        """Forget the locally tracked quote and its leg identifiers."""
        st = self._symbols_state[symbol]
        if st.quote_id is not None:
            self._quote_id_to_symbol.pop(st.quote_id, None)
        st.quote_id = None
        st.bid_order_id = None
        st.ask_order_id = None
        st.own_bid_price = st.own_ask_price = None
        st.own_bid_qty = st.own_ask_qty = 0

    def _cancel_and_reissue(self, symbol: str | None = None) -> None:
        """Replace one symbol's active quote with a fresh one at current mid."""
        symbol = symbol if symbol is not None else self._primary_symbol
        st = self._symbols_state[symbol]
        if st.quote_id is not None:
            if st.awaiting_cancel_for_reissue:
                return
            self._cancel_quote(symbol)
            st.awaiting_cancel_for_reissue = True
            st.reissue_at = time.monotonic() + st.cancel_timeout_sec
            self._set_state(symbol, BotState.REPRICING)
            return
        self._send_quote(symbol)

    # ------------------------------------------------------------------
    # Event handlers
    #
    # Handlers for per-symbol topics (book, circuit breaker) take an
    # explicit `symbol` — the caller (usually _dispatch) already knows it
    # from the topic string. Handlers for per-gateway topics (quote/order
    # events) resolve which symbol they're about from the payload
    # (order_fill/order_cancelled carry `symbol` directly; quote_ack/status
    # only carry `quote_id`, resolved via _quote_id_to_symbol).
    # ------------------------------------------------------------------

    def _handle_book(self, payload: dict[str, Any], symbol: str | None = None) -> None:
        """Handle book.SYMBOL event."""
        symbol = symbol if symbol is not None else self._primary_symbol
        st = self._symbols_state.get(symbol)
        if st is None or st.pricer is None:
            return
        bids = payload.get("bids", [])
        asks = payload.get("asks", [])
        # Anchored to a known value, the value sets the mid (see _anchor);
        # the book still feeds the passive plan's levels.
        held = st.pricer.mid_price if st.anchor_sim > 0 and st.sim_value else None
        update_book = getattr(st.pricer, "update_book", None)
        if update_book is not None:
            # passive: price off other traders' liquidity only.
            update_book(
                _others_levels(bids, st.own_bid_price, st.own_bid_qty, st.tick_size),
                _others_levels(asks, st.own_ask_price, st.own_ask_qty, st.tick_size),
            )
        else:
            best_bid_raw = bids[0].get("price") if bids else None
            best_ask_raw = asks[0].get("price") if asks else None
            best_bid = float(best_bid_raw) if best_bid_raw is not None else None
            best_ask = float(best_ask_raw) if best_ask_raw is not None else None
            st.pricer.update_mid(best_bid, best_ask)
        if held is not None:
            st.pricer.set_mid(held)
        self._debug(
            f"[{symbol}] book mid={_price_text(symbol, st.pricer.mid_price, 1)}"
        )

    def _anchor(self, st: _SymbolState) -> None:
        """Close ``anchor_sim`` of the gap between the mid and the true value.

        Applied at every ``sim.value`` (once per model step). Once a value is
        known the book no longer moves the mid, so the mid converges on the
        value: re-deriving it from the book at every update made it a fixed
        blend of the value and whatever stale order sat in the book.
        """
        if st.anchor_sim <= 0 or st.sim_value is None or st.pricer is None:
            return
        mid = st.pricer.mid_price
        if mid is None:
            st.pricer.set_mid(st.sim_value)
        else:
            st.pricer.set_mid(mid + st.anchor_sim * (st.sim_value - mid))

    def _handle_sim_value(self, payload: dict[str, Any]) -> None:
        """Take in the true values and anchor to them now: a quiet book
        publishes no updates, and a mid anchored only on book updates would
        stay wherever the value was when the book last changed."""
        for entry in payload.get("values", []):
            symbol = str(entry.get("symbol", "")).upper()
            st = self._symbols_state.get(symbol)
            if st is not None and st.anchor_sim > 0:
                st.sim_value = float(entry["value"])
                self._anchor(st)
                self._reprice_if_drifted(symbol)

    def _reprice_if_drifted(self, symbol: str) -> None:
        st = self._symbols_state[symbol]
        if (
            st.state == BotState.QUOTING
            and st.pricer
            and st.quoted_at_mid is not None
            and st.pricer.has_drifted(st.quoted_at_mid)
        ):
            self._debug(f"[{symbol}] drift detected — repricing")
            self._set_state(symbol, BotState.REPRICING)
            self._cancel_and_reissue(symbol)

    def _handle_trade(self, payload: dict[str, Any]) -> None:
        """Handle trade.executed — update mid if no book data."""
        symbol = str(payload.get("symbol", "")).upper()
        st = self._symbols_state.get(symbol)
        if st is None or st.pricer is None:
            return
        price = payload.get("price")
        if price is not None and st.pricer.mid_price is None:
            st.pricer.set_mid(float(price))
            self._debug(
                f"[{symbol}] mid from trade: {_price_text(symbol, float(price))}"
            )

    def _handle_quote_ack(self, payload: dict[str, Any]) -> None:
        """Handle quote.ack — record IDs or handle rejection.

        Matched by ``quote_id`` (minted by `_send_quote` and echoed by the
        engine), else by the ack's own ``symbol``; an ack matching neither is
        not this bot's and is ignored.
        """
        ack_quote_id = str(payload.get("quote_id", ""))
        symbol = self._quote_id_to_symbol.get(ack_quote_id) if ack_quote_id else None
        if symbol is None:
            symbol = str(payload.get("symbol", "")).upper()
            if symbol not in self._symbols_state:
                self._dbg_count("quote_ack_unknown")
                log.debug("quote.ack for no quoted symbol ignored: %s", payload)
                return
        st = self._symbols_state.get(symbol)
        if st is None:
            return
        accepted = bool(payload.get("accepted", False))
        if accepted and st.state == BotState.PAUSED:
            # Sent before a halt or a phase change paused the symbol: the
            # engine took it, so pull it again. Its legs are indexed so a fill
            # in between is still counted.
            self._index_legs(
                symbol,
                str(payload.get("bid_order_id", "")),
                str(payload.get("ask_order_id", "")),
            )
            self._cancel_quote(symbol)
            self._debug(f"[{symbol}] quote ACK while paused — cancelled")
            return
        if accepted:
            st.consecutive_rejects = 0
            st.reject_reasons_warned.clear()
            st.quote_id = str(payload.get("quote_id", ""))
            st.bid_order_id = str(payload.get("bid_order_id", ""))
            st.ask_order_id = str(payload.get("ask_order_id", ""))
            self._index_legs(symbol, st.bid_order_id, st.ask_order_id)
            # Already indexed at send time; re-assert only if the engine
            # minted an id of its own (it does that when a client sends none,
            # which this bot no longer does — but a rolling upgrade might).
            if st.quote_id and st.quote_id not in self._quote_id_to_symbol:
                self._quote_id_to_symbol[st.quote_id] = symbol
            self._set_state(symbol, BotState.QUOTING)
            self._debug(f"[{symbol}] quote ACK id={st.quote_id}")
            # Process buffered fills
            self._process_pending_fills()
        else:
            reason = str(payload.get("reason", "unknown"))
            st.consecutive_rejects += 1
            # A refusal the engine will repeat (a size or spread rule, a
            # closed market) must be visible at the default level, once.
            if reason not in st.reject_reasons_warned:
                st.reject_reasons_warned.add(reason)
                log.warning(
                    "[%s] [%s] quote REJECTED: %s", self.gateway_id, symbol, reason
                )
            else:
                log.debug(
                    "[%s] [%s] quote REJECTED again (%d in a row): %s",
                    self.gateway_id,
                    symbol,
                    st.consecutive_rejects,
                    reason,
                )
            # Retry, backing off: the delay doubles per consecutive refusal,
            # up to one heartbeat interval.
            base = max(st.reissue_delay_sec, _TICK_MIN_SEC)
            delay = min(
                base * 2 ** (st.consecutive_rejects - 1), st.heartbeat_interval_sec
            )
            st.reissue_at = time.monotonic() + delay

    def _handle_quote_status(self, payload: dict[str, Any]) -> None:
        """Handle quote.status — detect INACTIVE/CANCELLED.

        The payload carries no ``symbol``, so it is resolved through the
        quote id. It acts only on the symbol's current quote: the one acked
        (``quote_id``) or the one in flight (``sent_quote_id``). A status for
        a quote the bot has already replaced or forgotten (a replace's
        CANCELLED, a late confirmation) is ignored — applying it would clear
        the live quote it does not describe.
        """
        quote_id = str(payload.get("quote_id", ""))
        symbol = self._symbol_for_quote_id(quote_id)
        if symbol is None:
            self._dbg_count("quote_status_unknown_id")
            return
        st = self._symbols_state.get(symbol)
        if st is None:
            return
        if quote_id not in (st.quote_id, st.sent_quote_id):
            self._dbg_count("quote_status_stale")
            return

        status = str(payload.get("status", "")).upper()
        self._debug(f"[{symbol}] quote.status: {status}")

        if st.state in (BotState.PAUSED, BotState.WAITING_FOR_SESSION):
            return

        if status in ("INACTIVE_BID_FILLED", "INACTIVE_ASK_FILLED"):
            # Engine inactivated the quote; schedule fresh reissue.
            st.reissue_at = time.monotonic() + st.reissue_delay_sec
            self._clear_quote_state(symbol)
            if st.awaiting_cancel_for_reissue:
                self._debug(
                    f"[{symbol}] awaiting_cancel_for_reissue: True -> False "
                    "(inactivated)"
                )
            st.awaiting_cancel_for_reissue = False

        elif status == "CANCELLED":
            # Only reissue for CANCELLED if we still track a quote or are
            # awaiting cancel confirmation.  A stale CANCELLED that arrives
            # after an INACTIVE we already handled must be ignored to prevent
            # a duplicate reissue.
            if st.quote_id is not None or st.awaiting_cancel_for_reissue:
                st.reissue_at = time.monotonic()  # immediate
                self._clear_quote_state(symbol)
                if st.awaiting_cancel_for_reissue:
                    self._debug(
                        f"[{symbol}] awaiting_cancel_for_reissue: True -> False "
                        "(cancelled)"
                    )
                st.awaiting_cancel_for_reissue = False

    def _symbol_for_quote_id(self, quote_id: str) -> str | None:
        """The symbol *quote_id* was sent or adopted for, or None."""
        if not quote_id:
            return None
        symbol = self._quote_id_to_symbol.get(quote_id)
        if symbol is not None:
            return symbol
        # A quote set without a send or an ack (tests drive the state).
        for sym, st in self._symbols_state.items():
            if quote_id in (st.quote_id, st.sent_quote_id):
                return sym
        return None

    def _handle_order_fill(self, payload: dict[str, Any]) -> None:
        """Handle order.fill — check if it belongs to one of our quotes."""
        order_id = str(payload.get("order_id", ""))

        leg = self._leg_for_order_id(order_id, payload.get("symbol"))
        if leg is None:
            # The order_id doesn't match any symbol's known legs. That is
            # ambiguous, not definitive, while the symbol has not acked yet
            # -- this fill could belong to it once its order IDs are known.
            # A fill naming its symbol is buffered only while *that* symbol
            # waits for its ack: with hundreds of symbols one of them is
            # nearly always between quotes, and buffering on "any symbol
            # waits" kept every fill of an old leg forever, re-scanned on
            # every quote.ack. A fill without a symbol falls back to that
            # rule (checking "has ANY symbol acked" was the earlier bug: a
            # fill for a still-pending symbol was silently dropped).
            hinted = self._symbols_state.get(str(payload.get("symbol") or ""))
            candidates = (
                [hinted] if hinted is not None else self._symbols_state.values()
            )
            if any(
                st.bid_order_id is None and st.ask_order_id is None for st in candidates
            ):
                self._pending_fills.append(payload)
            return  # not a leg we recognise (or not yet)

        symbol, side = leg
        st = self._symbols_state[symbol]
        fill_qty = int(payload.get("fill_qty", 0))
        fill_price = float(payload.get("fill_price", 0.0))
        self._debug(
            f"[{symbol}] fill: {side} {fill_qty}@{payload.get('fill_price', '?')}"
        )

        # A filled BID leg means the bot bought; a filled ASK leg means it
        # sold. Update the local position ledger the same way regardless of
        # which pricing strategy is active -- inventory_skew reads it below,
        # symmetric simply never looks.
        order_side = "BUY" if side == "BID" else "SELL"
        prior_position, prior_avg_cost = st.net_position, st.avg_cost
        st.net_position, st.avg_cost = _update_position(
            st.net_position, st.avg_cost, order_side, fill_qty, fill_price
        )
        log.debug(
            "[%s] position update: %d->%d avg_cost=%.4f->%.4f (fill %s %d@%s)",
            symbol,
            prior_position,
            st.net_position,
            prior_avg_cost,
            st.avg_cost,
            order_side,
            fill_qty,
            fill_price,
        )
        if hasattr(st.pricer, "update_position"):
            st.pricer.update_position(st.net_position)  # type: ignore[union-attr]
        # Only a leg of the current quote is still among the bot's own levels.
        if order_id == st.bid_order_id:
            st.own_bid_qty = max(0, st.own_bid_qty - fill_qty)
        elif order_id == st.ask_order_id:
            st.own_ask_qty = max(0, st.own_ask_qty - fill_qty)
        if hasattr(st.pricer, "on_fill"):
            st.pricer.on_fill(side, time.monotonic())  # type: ignore[union-attr]

        # Reset or start the reissue timer — but only when no cancel is already
        # in flight.  Overwriting the cancel-confirmation timeout with a shorter
        # fill-delay would lose the timeout if the cancel ACK never arrives,
        # leaving the bot stuck in REPRICING with no recovery timer.
        if not st.awaiting_cancel_for_reissue:
            st.reissue_at = time.monotonic() + st.reissue_delay_sec

    def _leg_for_order_id(
        self, order_id: str, symbol: object = None
    ) -> tuple[str, str] | None:
        """(symbol, "BID"/"ASK") of the leg *order_id*, or None.

        Every leg this bot was acked or adopted is in ``_leg_to_symbol``,
        retired ones included. A current leg set without an ack (tests drive
        the state directly) is found on its symbol's quote: order events name
        their symbol, so only that symbol is checked; without one, every
        symbol is scanned.
        """
        leg = self._leg_to_symbol.get(order_id)
        if leg is not None:
            return leg
        hinted = self._symbols_state.get(str(symbol or ""))
        candidates = (
            [(str(symbol), hinted)]
            if hinted is not None
            else list(self._symbols_state.items())
        )
        for sym, st in candidates:
            if order_id == st.bid_order_id:
                return sym, "BID"
            if order_id == st.ask_order_id:
                return sym, "ASK"
        return None

    def _handle_order_cancelled(self, payload: dict[str, Any]) -> None:
        """Handle order.cancelled — track leg cleanup."""
        order_id = str(payload.get("order_id", ""))
        leg = self._leg_for_order_id(order_id, payload.get("symbol"))
        if leg is not None:
            self._debug(f"[{leg[0]}] leg cancelled: {order_id}")

    def _handle_session_state(self, payload: dict[str, Any]) -> None:
        """Handle session.state transitions — applies to every symbol."""
        new_state = str(payload.get("state", "")).upper()
        old_state = self._session_state
        self._session_state = new_state
        self._debug(f"session: {old_state} -> {new_state}")

        for symbol in self._active_symbols():
            st = self._symbols_state[symbol]
            if new_state in _QUOTING_SESSIONS:
                if st.state in (BotState.PAUSED, BotState.WAITING_FOR_SESSION):
                    self._set_state(symbol, BotState.WAITING_FOR_SESSION)
                    # Trigger reissue if we have reference
                    if st.pricer and st.pricer.mid_price is not None:
                        st.reissue_at = time.monotonic()
            else:
                # Non-trading phase — cancel and pause. REISSUING too: the
                # quote in flight would otherwise rest through the phase.
                if st.state in (
                    BotState.QUOTING,
                    BotState.REPRICING,
                    BotState.REISSUING,
                ):
                    self._cancel_quote(symbol)
                    self._clear_quote_state(symbol)
                self._set_state(symbol, BotState.PAUSED)
                st.reissue_at = None

    def _handle_circuit_breaker_halt(self, symbol: str | None = None) -> None:
        """Handle circuit_breaker.halt.SYMBOL for one symbol."""
        symbol = symbol if symbol is not None else self._primary_symbol
        self._log(f"[{symbol}] circuit breaker HALT")
        st = self._symbols_state.get(symbol)
        if st is None:
            return
        if st.state in (BotState.QUOTING, BotState.REPRICING, BotState.REISSUING):
            self._cancel_quote(symbol)
            self._clear_quote_state(symbol)
        self._set_state(symbol, BotState.PAUSED)
        st.reissue_at = None

    def _handle_circuit_breaker_resume(self, symbol: str | None = None) -> None:
        """Handle circuit_breaker.resume.SYMBOL for one symbol."""
        symbol = symbol if symbol is not None else self._primary_symbol
        self._log(f"[{symbol}] circuit breaker RESUME")
        st = self._symbols_state.get(symbol)
        if st is None:
            return
        self._set_state(symbol, BotState.WAITING_FOR_SESSION)
        # Nothing else moves a waiting symbol on while the session stays
        # open, so the reissue is scheduled here.
        if (
            self._session_state in _QUOTING_SESSIONS
            and st.pricer is not None
            and st.pricer.mid_price is not None
        ):
            st.reissue_at = time.monotonic()

    def _process_pending_fills(self) -> None:
        """Process fills that arrived before any quote.ack."""
        pending, self._pending_fills = self._pending_fills, []
        for fill in pending:
            self._handle_order_fill(fill)

    # ------------------------------------------------------------------
    # Main event loop
    # ------------------------------------------------------------------

    def _dispatch(self, topic: str, payload: dict[str, Any]) -> None:
        """Route an incoming message to the appropriate handler."""
        self._msgs_in += 1
        self._dbg_count("incoming_total")
        self._dbg_count(f"incoming_topic_{self._topic_family(topic)}")

        kind, symbol = self._symbol_topics.get(topic, ("", ""))
        if kind == "book":
            self._handle_book(payload, symbol=symbol)
            self._reprice_if_drifted(symbol)
            return
        if kind == "halt":
            self._handle_circuit_breaker_halt(symbol)
            return
        if kind == "resume":
            self._handle_circuit_breaker_resume(symbol)
            return

        if topic == TOPIC_TRADE_EXECUTED:
            self._handle_trade(payload)
        elif topic == TOPIC_SIM_VALUE:
            self._handle_sim_value(payload)
        elif topic == topic_quote_ack(self.gateway_id):
            self._handle_quote_ack(payload)
        elif topic == topic_quote_status(self.gateway_id):
            self._handle_quote_status(payload)
        elif topic == topic_order_fill(self.gateway_id):
            self._handle_order_fill(payload)
        elif topic == topic_order_cancelled(self.gateway_id):
            self._handle_order_cancelled(payload)
        elif topic == TOPIC_SESSION_STATE:
            self._handle_session_state(payload)
        elif topic == topic_quote_legs(self.gateway_id):
            self._reconcile_qlegs(payload)
        else:
            self._dbg_count("incoming_unhandled")

    def _tick(self) -> None:
        """Periodic housekeeping — reissue timer, heartbeat, QLEGS. Runs
        independently for every symbol still active (§5a.4)."""
        now = time.monotonic()
        self._dbg_count("tick_calls")
        if (
            self._authenticated
            and now - self._last_engine_heartbeat >= GATEWAY_HEARTBEAT_INTERVAL_SEC
        ):
            self._send_engine_heartbeat(now)

        qlegs_due = False
        for symbol in self._active_symbols():
            qlegs_due = self._tick_symbol(symbol, now) or qlegs_due
        if qlegs_due:
            # One snapshot for the whole gateway: the reply names no symbol,
            # so only a gateway-wide one says which quotes are missing.
            self._send(make_quote_legs_request_msg(self.gateway_id, "", "ACTIVE"))
            self._dbg_count("qlegs_reconcile_requests")

    def _tick_symbol(self, symbol: str, now: float) -> bool:
        """Run one symbol's timers. True when its QLEGS check is due."""
        st = self._symbols_state[symbol]

        # Reissue timer
        if st.reissue_at is not None and now >= st.reissue_at:
            st.reissue_at = None
            if st.state in (
                BotState.QUOTING,
                BotState.REPRICING,
                BotState.REISSUING,
                BotState.WAITING_FOR_SESSION,
            ):
                if (
                    self._session_state in _QUOTING_SESSIONS
                    and st.pricer
                    and st.pricer.mid_price is not None
                ):
                    if st.state == BotState.REPRICING and st.quote_id is not None:
                        self._log(
                            f"[{symbol}] cancel confirmation timeout — forcing "
                            "quote replacement"
                        )
                        self._clear_quote_state(symbol)
                        st.awaiting_cancel_for_reissue = False
                    self._cancel_and_reissue(symbol)
                elif st.state == BotState.WAITING_FOR_SESSION:
                    pass  # wait for session
                else:
                    self._set_state(symbol, BotState.WAITING_FOR_SESSION)

        # Time-driven requote (passive: a fade has expired). Book-driven
        # drift is checked in _dispatch; this covers changes with no event.
        if (
            st.state == BotState.QUOTING
            and st.quote_id is not None
            and hasattr(st.pricer, "requote_due")
            and st.pricer.requote_due(now)  # type: ignore[union-attr]
        ):
            self._debug(f"[{symbol}] requote due — repricing")
            self._set_state(symbol, BotState.REPRICING)
            self._cancel_and_reissue(symbol)

        # Heartbeat guard — recover if we are in an active state but hold no
        # live quote and have no reissue already scheduled. This covers a
        # dropped quote.ack that would otherwise strand the bot in REISSUING.
        # Require a full heartbeat interval since the last quote send so we do
        # not pre-empt an ack that is legitimately still in flight.
        #
        # The clock is per symbol, so a symbol configured with a short
        # heartbeat recovers at its own cadence regardless of what the others
        # are set to.
        if now - st.last_heartbeat >= st.heartbeat_interval_sec:
            if (
                st.state in (BotState.QUOTING, BotState.REISSUING, BotState.REPRICING)
                and st.quote_id is None
                and st.reissue_at is None
                and now - st.last_quote_sent_at >= st.heartbeat_interval_sec
                and self._session_state in _QUOTING_SESSIONS
                and st.pricer
                and st.pricer.mid_price is not None
            ):
                self._log(f"[{symbol}] heartbeat: no active quote — reissuing")
                log.debug(
                    "[%s] heartbeat reissue reason: quote_id=%s reissue_at=%s "
                    "elapsed_since_last_quote=%.1fs",
                    symbol,
                    st.quote_id,
                    st.reissue_at,
                    now - st.last_quote_sent_at,
                )
                self._dbg_count("heartbeat_reissues")
                self._cancel_and_reissue(symbol)
            st.last_heartbeat = now

        # Periodic QLEGS reconciliation — request only (non-blocking), sent
        # by _tick. The reply is handled in _dispatch so steady-state
        # fills/status events are never dropped while waiting for it.
        if now - st.last_qlegs_reconcile >= st.qlegs_reconcile_interval_sec:
            st.last_qlegs_reconcile = now
            return st.state == BotState.QUOTING and st.quote_id is not None
        return False

    def _reconcile_qlegs(self, payload: dict[str, Any]) -> None:
        """Reconcile a gateway-wide QLEGS snapshot against every symbol.

        The bot asks for the whole gateway's ``ACTIVE`` legs (the reply names
        no symbol, so only then does a missing symbol mean a missing quote).
        Each leg carries its ``symbol``. Every symbol actively quoting a
        tracked quote is checked; a divergence (no legs, another quote_id,
        other leg order ids) clears that symbol's local state and schedules
        an immediate reissue. Legs of symbols this bot does not quote are
        ignored.
        """
        if not payload.get("complete", True):
            self._debug("QLEGS reply marked incomplete by engine")
        legs_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for leg in payload.get("legs", []):
            legs_by_symbol[str(leg.get("symbol", "")).upper()].append(leg)
        for symbol in self._active_symbols():
            st = self._symbols_state[symbol]
            if st.state == BotState.QUOTING and st.quote_id is not None:
                self._reconcile_symbol_legs(symbol, legs_by_symbol.get(symbol, []))

    def _reconcile_symbol_legs(self, symbol: str, legs: list[dict[str, Any]]) -> None:
        st = self._symbols_state[symbol]
        if not legs:
            # Engine says no legs but we think we have a quote
            self._log(
                f"[{symbol}] QLEGS mismatch: no legs but local quote exists — "
                "reissuing"
            )
            self._clear_quote_state(symbol)
            st.reissue_at = time.monotonic()
            return

        # Check if our IDs match
        seen_order_ids: set[str] = set()
        for leg in legs:
            leg_qid = str(leg.get("quote_id", ""))
            leg_order_id = str(leg.get("order_id", ""))
            if leg_qid and st.quote_id and leg_qid != st.quote_id:
                self._log(f"[{symbol}] QLEGS mismatch: quote_id divergence — reissuing")
                log.debug(
                    "[%s] QLEGS quote_id divergence: local=%s engine=%s",
                    symbol,
                    st.quote_id,
                    leg_qid,
                )
                self._clear_quote_state(symbol)
                st.reissue_at = time.monotonic()
                return
            if leg_order_id:
                seen_order_ids.add(leg_order_id)

        expected_order_ids = {oid for oid in (st.bid_order_id, st.ask_order_id) if oid}
        if (
            expected_order_ids
            and seen_order_ids
            and expected_order_ids != seen_order_ids
        ):
            self._log(f"[{symbol}] QLEGS mismatch: leg order_id divergence — reissuing")
            log.debug(
                "[%s] QLEGS order_id divergence: expected=%s seen=%s",
                symbol,
                sorted(expected_order_ids),
                sorted(seen_order_ids),
            )
            self._clear_quote_state(symbol)
            st.reissue_at = time.monotonic()

    def attach_reporter(self, reporter: HealthReporter) -> None:
        """Ship this bot's health beacon through ``reporter`` (main()).

        Ticked by the quoting loop only: start-up (authentication, symbol
        bootstrap, waiting for a session) reads as ``starting``.
        """
        self._reporter = reporter

    def metric_samples(self) -> list[MetricSample]:
        """Design B5.4: traffic both ways and the symbols being quoted."""
        return [
            counter("mmbot.msgs_out", self._msgs_out),
            counter("mmbot.msgs_in", self._msgs_in),
            gauge("mmbot.symbols_active", len(self._active_symbols())),
        ]

    def run(self) -> int:
        """Run the bot event loop. Returns exit code."""
        self._log(
            f"starting: gateway={self.gateway_id} symbols={','.join(self.symbols)}"
        )
        for sym in self.symbols:
            st = self._symbols_state[sym]
            self._log(
                f"[{sym}] strategy={st.strategy} gap={st.gap} qty={st.qty} "
                f"tif={st.tif} drift_ticks={st.drift_ticks}"
                + (
                    f" max_position={st.max_position}"
                    if st.max_position is not None
                    else ""
                )
            )
        self._setup_sockets()
        self._running = True

        # Install signal handlers
        def _sig_handler(signum: int, frame: Any) -> None:
            self._running = False
            self._stop_requested = True

        signal.signal(signal.SIGINT, _sig_handler)
        signal.signal(signal.SIGTERM, _sig_handler)

        try:
            return self._run_loop()
        finally:
            if self._authenticated:
                self._send_quietly(make_gateway_disconnect_msg(self.gateway_id))
            self._close_sockets()

    def _run_loop(self) -> int:
        """Internal event loop."""
        rc = self._start_up()
        if rc is not None:
            return rc
        active = self._active_symbols()

        # Main event loop
        assert self._sub_sock is not None
        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        poll_timeout_ms = self._poll_timeout_ms(active)

        next_tick = 0.0
        reporter = self._reporter
        if reporter is not None:
            poll_timeout_ms = min(poll_timeout_ms, _LIVENESS_POLL_MS)
        while self._running:
            if reporter is not None:
                reporter.tick_and_publish(self.metric_samples)
            socks = dict(poller.poll(timeout=poll_timeout_ms))
            if self._sub_sock in socks:
                topic, payload = decode(self._sub_sock.recv_multipart())
                self._dispatch(topic, payload)
            now = time.monotonic()
            if now >= next_tick:
                self._tick()
                next_tick = now + _TICK_MIN_SEC

        # Shutdown
        self._flush_debug_summary(force=True)
        self._do_shutdown()
        return 0

    def _start_up(self) -> int | None:
        """Steps 1-7 of the start-up sequence. Returns the exit code when
        start-up ends the run, None when the bot goes on to quote."""
        # A stop (SIGINT/SIGTERM) during start-up ends it before any quote
        # is sent: each step's wait gives up at once, and exit code is 0.
        # Step 1: Authenticate (gateway-wide — one auth covers every symbol)
        authenticated = self._authenticate()
        if self._stop_requested:
            return 0
        if not authenticated:
            self._warn("startup failed: authentication")
            return 1

        # Step 2: Request symbols (registers tick/MM-obligation metadata for
        # every symbol found in the reply)
        symbols_seen = self._request_symbols()
        if self._stop_requested:
            return 0
        if not symbols_seen:
            # Without it every tick size and obligation would be a guess.
            self._warn("startup failed: no symbol list from the engine")
            return 1

        # Step 3, per symbol: gap validation, pricer creation. A symbol that
        # fails is excluded from the rest of the run (§5a.4 per-symbol failure
        # isolation) rather than failing the whole process — unless it is the
        # *only* symbol, in which case failing it is exactly the original
        # single-symbol failure behavior.
        for symbol in list(self.symbols):
            self._startup_one_symbol(symbol, symbols_seen)

        # Steps 4-5, once for the gateway: QBOOT adoption, QLEGS check, and
        # the position the gateway already holds.
        self._adopt_existing_quotes()
        self._seed_positions()
        if self._stop_requested:
            return 0

        active = self._active_symbols()
        if not active:
            self._warn("startup failed: no symbol survived startup checks")
            return 1
        for symbol in self.symbols:
            if symbol not in active:
                st = self._symbols_state[symbol]
                self._warn(
                    f"[{symbol}] excluded from quoting: {st.startup_failed_reason}"
                )

        # Step 6: Wait for session state (gateway-wide)
        session_known = self._wait_for_session(self._startup_session_timeout_sec)
        if self._stop_requested:
            return 0
        if not session_known:
            self._warn("startup failed: no session.state received within timeout")
            return 1

        # Step 7: Determine initial state, per active symbol. This can
        # exclude a symbol too (no reference price available anywhere) —
        # recompute the active set afterwards and, same as after steps 3-5,
        # fail the whole process if nothing survived.
        for symbol in active:
            self._resolve_initial_state(symbol)

        active = self._active_symbols()
        if not active:
            self._warn("startup failed: no symbol survived startup checks")
            return 1

        self._log(f"running symbols={active} session={self._session_state}")
        now = time.monotonic()
        for symbol in active:
            self._symbols_state[symbol].last_qlegs_reconcile = now
            self._symbols_state[symbol].last_heartbeat = now
        return None

    def _startup_one_symbol(self, symbol: str, symbols_seen: list[str]) -> None:
        st = self._symbols_state[symbol]

        if symbol not in symbols_seen:
            st.startup_failed_reason = f"{symbol} not in symbol list"
            self._warn(f"[{symbol}] startup failed: not in symbol list")
            return

        # Derive or validate gap against symbol MM spread obligation when
        # available.
        if st.mm_max_spread_ticks is not None:
            if not st.gap_was_explicit:
                st.gap = (st.mm_max_spread_ticks / 2.0) * st.tick_size
                self._log(
                    f"[{symbol}] gap defaulted from MM obligation: {st.gap:.6f} "
                    f"(max_spread_ticks={st.mm_max_spread_ticks})"
                )
            if st.gap > st.mm_max_spread_ticks * st.tick_size:
                st.startup_failed_reason = (
                    f"--gap exceeds mm_max_spread_ticks obligation "
                    f"({st.gap:.6f} > {st.mm_max_spread_ticks} * {st.tick_size:.6f})"
                )
                self._warn(f"[{symbol}] startup failed: {st.startup_failed_reason}")
                return
        if st.mm_min_qty is not None and st.qty < st.mm_min_qty:
            st.startup_failed_reason = (
                f"--qty {st.qty} is below the mm_min_qty obligation {st.mm_min_qty}"
            )
            self._warn(f"[{symbol}] startup failed: {st.startup_failed_reason}")
            return

        # Initialize pricing strategy
        try:
            st.pricer = create_strategy(
                st.strategy,
                tick_size=st.tick_size,
                gap=st.gap,
                drift_ticks=st.drift_ticks,
                max_position=st.max_position,
                passive=PassiveParams(
                    retreat_ticks=st.retreat_ticks,
                    behind_ticks=st.behind_ticks,
                    min_cover_qty=st.min_cover_qty,
                    fade_ticks=st.fade_ticks,
                    fade_sec=st.fade_sec,
                ),
                max_spread_ticks=st.mm_max_spread_ticks,
            )
        except ValueError as exc:
            st.startup_failed_reason = f"invalid strategy/gap/tick configuration: {exc}"
            self._warn(f"[{symbol}] startup failed: {st.startup_failed_reason}")
            return
        if st.strategy == "passive" and st.mm_max_spread_ticks is not None:
            room = (st.mm_max_spread_ticks - round(st.gap / st.tick_size)) // 2
            if st.retreat_ticks > room:
                self._log(
                    f"[{symbol}] retreat_ticks {st.retreat_ticks} narrowed to "
                    f"{max(0, room)} by mm_max_spread_ticks="
                    f"{st.mm_max_spread_ticks}"
                )

        # Ask for the book now: a quiet book publishes no update, and without
        # one the reference fallback finds no mid. The reply arrives during
        # the QBOOT/QLEGS waits, which pass it to _handle_book.
        self._send(make_book_snapshot_request_msg(symbol))

    def _adopt_existing_quotes(self) -> None:
        """Adopt each active symbol's live quote from one gateway-wide QBOOT,
        then drop an adoption the QLEGS snapshot contradicts."""
        active = self._active_symbols()
        if not active:
            return
        self._boot_payload = self._request_bootstrap()
        for symbol in active:
            self._try_adopt_from_bootstrap(symbol, self._boot_payload)

        qlegs_payload = self._request_qlegs()
        if not qlegs_payload:
            return
        legs = qlegs_payload.get("legs", [])
        for symbol in active:
            st = self._symbols_state[symbol]
            if not st.quote_id:
                continue
            for leg in legs:
                if str(leg.get("symbol", "")).upper() != symbol:
                    continue
                if str(leg.get("quote_id", "")) != st.quote_id:
                    self._log(
                        f"[{symbol}] startup QLEGS mismatch — clearing " "adopted state"
                    )
                    self._clear_quote_state(symbol)
                    break

    def _resolve_initial_state(self, symbol: str) -> None:
        st = self._symbols_state[symbol]
        boot_payload = self._boot_payload
        has_adopted = st.quote_id is not None
        if has_adopted:
            if self._session_state in _QUOTING_SESSIONS:
                st.state = BotState.QUOTING
            else:
                st.state = BotState.PAUSED
        else:
            resolved = self._resolve_bootstrap_reference(boot_payload, symbol=symbol)
            if not resolved:
                st.startup_failed_reason = (
                    "no reference price available "
                    "(no book, no trade, no bootstrap, no random range)"
                )
                self._warn(f"[{symbol}] startup failed: {st.startup_failed_reason}")
                return
            if self._session_state in _QUOTING_SESSIONS:
                st.state = BotState.WAITING_FOR_SESSION
                self._send_quote(symbol)
            else:
                st.state = BotState.PAUSED

    def _do_shutdown(self) -> None:
        """Send cancel for every symbol still quoting and wait for
        confirmation (bounded by one shared shutdown timeout, same as the
        original single-symbol behavior)."""
        active = self._active_symbols()
        quoting = [
            sym
            for sym in active
            if self._symbols_state[sym].state
            in (BotState.QUOTING, BotState.REPRICING, BotState.REISSUING)
        ]
        for sym in quoting:
            self._cancel_quote(sym)

        if quoting and self._sub_sock:
            pending = set(quoting)
            poller = zmq.Poller()
            poller.register(self._sub_sock, zmq.POLLIN)
            deadline = time.monotonic() + self._shutdown_timeout_sec
            while time.monotonic() < deadline and pending:
                remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
                socks = dict(poller.poll(timeout=min(remaining_ms, 100)))
                if self._sub_sock in socks:
                    topic, payload = decode(self._sub_sock.recv_multipart())
                    if topic == topic_quote_status(self.gateway_id):
                        quote_id = str(payload.get("quote_id", ""))
                        confirmed_sym = self._quote_id_to_symbol.get(quote_id)
                        if confirmed_sym is not None and confirmed_sym in pending:
                            pending.discard(confirmed_sym)
                            self._debug(f"[{confirmed_sym}] shutdown: cancel confirmed")
                self._flush_debug_summary(force=True)
        self._log("shutdown complete")

    def shutdown(self) -> None:
        """External shutdown trigger."""
        self._running = False
        self._stop_requested = True


def _resolve_symbols_arg(*, symbol: str | None, symbols: list[str] | None) -> list[str]:
    """Normalize the symbol/symbols constructor kwargs to one clean list.

    Exactly one of ``symbol`` (legacy singular) or ``symbols`` (plural) is
    expected to carry real content; both may not be given non-empty values
    at once, and at least one must be.
    """
    if symbols:
        seen: dict[str, None] = {}
        for s in symbols:
            s = s.strip().upper()
            if s:
                seen[s] = None
        resolved = list(seen)
        if not resolved:
            raise ValueError("symbols must contain at least one non-empty entry")
        if symbol and symbol.strip().upper() not in resolved:
            raise ValueError(
                f"symbol={symbol!r} was also given but is not in symbols={symbols!r}"
            )
        return resolved
    if symbol and symbol.strip():
        return [symbol.strip().upper()]
    raise ValueError("MMBot requires either symbol= or a non-empty symbols=")

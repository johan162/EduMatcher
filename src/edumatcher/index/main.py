"""
pm-index — calculates the configured market indices from the engine's trades.

Usage:
  poetry run pm-index              # resume from each index's state file
  poetry run pm-index --reset      # discard the state files, start from config
  poetry run pm-index -v           # INFO (-vv: DEBUG); the default is WARNING

Subscribes to the engine's ``trade.executed``, ``session.state``,
``system.eod``, its own session-status reply and ``book.{symbol}`` for every
constituent. Publishes ``index.update`` (throttled to
``publish_interval_sec``; a throttled level is sent once the interval has
passed) and answers ``index.history_request``, ``index.corp_action``,
``index.constituent_change`` and ``index.rebalance`` on its PULL socket.

The day: the open/high/low start at ``PRE_OPEN``; ``CLOSED`` publishes the
close. ``system.eod`` (sent at every engine stop) also finalises, and makes
pm-index ask for the session status again; a reply in a trading phase undoes
that latch, and every reply requests a book snapshot per constituent, whose
last price catches the index up on trades it missed.

Files, per index: the state file (divisor, constituents, share counts, last
prices, and the day while the session is open) is the restore authority; it
is checkpointed at most every 30 s while prices move, on every phase change,
at shutdown and with every command. The history file is an append-only
structural log (INIT, CORP_ACTION, ADD_CONSTITUENT, DELIST, REBALANCE).

A command is applied to a copy of the index, written to the state file and
the history, and only then swapped in, published and acknowledged; a write
failure rejects it and changes nothing.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import copy
import errno
import json
import logging
import math
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import zmq

from edumatcher.config_artifact import exit_on_config_error
from edumatcher.health import HealthReporter
from edumatcher.config import (
    COMPILED_CONFIG_FILE,
    ENGINE_PUB_ADDR,
    ENGINE_PULL_ADDR,
    INDEX_HEALTH_BIND_ADDR,
    INDEX_PUB_ADDR,
    INDEX_PULL_ADDR,
)
from edumatcher.engine.persistence import atomic_write_text
from edumatcher.healthcheck import answer_health_ping
from edumatcher.index.calculator import ConstituentConfig, IndexCalculator
from edumatcher.index.config_loader import (
    IndexRuntimeConfig,
    index_runtime_configs,
    load_index_runtime_configs,
)
from edumatcher.index.history import STRUCTURAL_RECORD_TYPES, IndexHistory
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler
from edumatcher.messaging.bus import (
    make_publisher,
    make_puller,
    make_pusher,
    make_replier,
    make_subscriber,
)
from edumatcher.models.message import (
    decode,
    make_index_constituent_change_ack_msg,
    make_index_corp_action_ack_msg,
    make_index_error_msg,
    make_index_history_msg,
    make_index_rebalance_ack_msg,
    make_book_snapshot_request_msg,
    make_index_update_msg,
    make_session_state_request_msg,
)
from edumatcher.models.generated.book import TOPIC_BOOK_SNAPSHOT, topic_book_snapshot
from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED
from edumatcher.models.generated.session import TOPIC_SESSION_STATE
from edumatcher.models.generated.index import (
    TOPIC_INDEX_CONSTITUENT_CHANGE,
    TOPIC_INDEX_CORP_ACTION,
    TOPIC_INDEX_HISTORY_REQUEST,
    TOPIC_INDEX_REBALANCE,
    DaySummary,
)
from edumatcher.models.generated.system import TOPIC_EOD, topic_session_status
from edumatcher.models.session import SessionState

log = logging.getLogger(__name__)
_DEBUG_SUMMARY_INTERVAL_SEC = 5.0
_SESSION_STATUS_GATEWAY_ID = "PM_INDEX"
_SESSION_STATUS_RETRY_SEC = 1.0
_SESSION_STATUS_WARNING_SEC = 3.0
#: The phases of a trading day after PRE_OPEN and before CLOSED.
_TRADING_DAY_STATES = frozenset(
    {
        SessionState.OPENING_AUCTION.value,
        SessionState.CONTINUOUS.value,
        SessionState.CLOSING_AUCTION.value,
    }
)

#: ``book.{symbol}`` up to the symbol, as bytes: what the loop compares a raw
#: topic frame with before it pays for decoding a book it did not ask for.
_BOOK_TOPIC_PREFIX = TOPIC_BOOK_SNAPSHOT.removesuffix("{symbol}").encode()

#: Most messages handled per socket per poll wake-up before the loop polls
#: again (P2), as pm-stats' _DRAIN_PER_WAKE.
_DRAIN_PER_WAKE = 1_000

#: Longest a trade-driven price change stays unwritten while trading. Writing
#: the state file on every trade would cost a file write per print; every
#: phase change and shutdown checkpoints as well (K7).
CHECKPOINT_INTERVAL_SEC = 30.0

#: Longest identifier this process will echo back into a reply, matching the
#: `max_len` the index spec declares for gateway_id / index_id / symbol.
_MAX_ID_LEN = 32


def _clamp_id(value: object, limit: int = _MAX_ID_LEN) -> str:
    """Normalise an identifier arriving from the wire, bounded.

    The bound is what makes the replies safe to build. Every rejection path
    here quotes the identifier it could not resolve, and since 5.2f those
    replies are generated constructors that *validate* — so an inbound
    index_id of five thousand characters would raise MessageValidationError
    instead of producing a reply: the dispatch guard only logs it, and the
    caller waits out its timeout. Before adoption the same input merely
    published an oversized reason.

    Truncating loses nothing real: an identifier longer than the spec allows
    cannot name an index or a gateway that exists, so a clamped one fails the
    same lookup and produces the same rejection.
    """
    return str(value).upper()[:limit]


def _extend_day(day: DaySummary | None, level: float) -> DaySummary:
    """The day's open/high/low with ``level`` included; the first level opens it."""
    if day is None:
        return DaySummary(open=level, high=level, low=level)
    return DaySummary(open=day.open, high=max(day.high, level), low=min(day.low, level))


def _reason(exc: Exception) -> str:
    """A rejection reason from ``exc``; ``str(KeyError(m))`` is ``m`` quoted."""
    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    return str(exc)


def _int_field(payload: dict[str, Any], key: str, default: int) -> int:
    """An integer command field; a bad value is a ValueError the caller rejects.

    ``default`` applies only when the key is absent. A present but wrong value
    (None, bool, NaN, a fraction, text) is refused rather than truncated or
    coerced: ``int(None)`` raising TypeError out of a handler was K8 / I3.
    """
    if key not in payload:
        return default
    value = payload[key]
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{key} must be an integer")
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError(f"{key} must be an integer")
        return int(value)
    try:
        return int(value)
    except TypeError, ValueError:
        raise ValueError(f"{key} must be an integer") from None


def _float_field(payload: dict[str, Any], key: str, default: float) -> float:
    """A finite numeric command field; a bad value is a ValueError."""
    if key not in payload:
        return default
    value = payload[key]
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{key} must be a number")
    try:
        number = float(value)
    except TypeError, ValueError:
        raise ValueError(f"{key} must be a number") from None
    if not math.isfinite(number):
        raise ValueError(f"{key} must be a finite number")
    return number


_CLIENT_NAME = "pm-index"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"


@dataclass
class _ManagedIndex:
    cfg: IndexRuntimeConfig
    calc: IndexCalculator
    history: IndexHistory
    session_state: str = "UNKNOWN"
    last_publish_time: float = 0.0
    #: A level was computed inside the publish interval and not broadcast;
    #: the loop publishes it once the interval has passed (C1).
    pending: bool = False
    eod_finalized_for_session: bool = False
    #: The session's open/high/low, or None before the first level is
    #: computed. One optional record rather than three optional floats: the
    #: three were only ever set and cleared together, and holding them
    #: separately left a half-set state representable in the one place it
    #: could actually arise (design section 16.2).
    day: DaySummary | None = None
    #: Prices moved since the state file was last written (K7 checkpoint).
    dirty: bool = False
    last_checkpoint: float = 0.0
    #: The history file's last flush failed; logged once, not every pass.
    history_flush_failed: bool = False


@dataclass(frozen=True)
class _RestoredState:
    """What the state file says about one index; all None/empty on a fresh start."""

    divisor: float | None = None
    last_prices: dict[str, float] = field(default_factory=dict)
    #: The live constituent set and its share counts, which may differ from
    #: the static config after a runtime ADD / DELIST / share change.
    constituents: list[str] | None = None
    shares: dict[str, int] = field(default_factory=dict)
    #: The session's day so far, restored only when the session had not
    #: ended at the stop (C10); a day that has ended is not continued.
    day: DaySummary | None = None
    eod_finalized: bool = False


class IndexProcess:
    def __init__(self, config_path: Path | None = None, reset: bool = False) -> None:
        """Run the index calculation process.

        With no ``config_path`` the indices come from the compiled artifact, so
        pm-index and pm-engine agree about constituents and their reference
        data. An explicit path still parses YAML directly, for tests and tools
        working on an authored file.
        """
        self._config_path = config_path
        self._reset = reset
        self._running = True
        self._session_status_received = False
        self._session_status_warning_logged = False
        # Health beacon, attached by main(); vitals only (design A6.6).
        self._reporter: HealthReporter | None = None

        self._indices: dict[str, _ManagedIndex] = {}
        self._constituent_to_indices: dict[str, set[str]] = {}
        #: Constituents whose book snapshot pm-index asked for and has not
        #: had yet; the engine's periodic book.{symbol} is ignored (C11).
        self._awaiting_snapshot: set[str] = set()

        self._sub_sock = make_subscriber(
            ENGINE_PUB_ADDR,
            TOPIC_TRADE_EXECUTED,
            TOPIC_SESSION_STATE,
            TOPIC_EOD,
            topic_session_status(_SESSION_STATUS_GATEWAY_ID),
        )
        self._engine_push = make_pusher(ENGINE_PULL_ADDR)
        self._pull_sock = make_puller(INDEX_PULL_ADDR)
        self._pub_sock = make_publisher(INDEX_PUB_ADDR)
        # Bound, not connected: pm-index-cli health's ZMQ ping is the only
        # thing that speaks to this socket, proving the poll loop itself is
        # alive rather than just the OS process.
        try:
            self._health_rep = make_replier(INDEX_HEALTH_BIND_ADDR)
        except BaseException:
            self._sub_sock.close()
            self._engine_push.close()
            self._pull_sock.close()
            self._pub_sock.close()
            raise
        self._debug_counts: defaultdict[str, int] = defaultdict(int)
        self._debug_last_summary = time.monotonic()
        log.debug(
            "index process initialized config=%s reset=%s sub=%s pull=%s pub=%s health=%s",
            self._config_path,
            self._reset,
            ENGINE_PUB_ADDR,
            INDEX_PULL_ADDR,
            INDEX_PUB_ADDR,
            INDEX_HEALTH_BIND_ADDR,
        )

    def _runtime_configs(self) -> list[IndexRuntimeConfig]:
        """Return the enriched index configs, from the artifact or a YAML path.

        `outstanding_shares` and `reference_prices` are gathered from the
        constituent symbols rather than being fields of their own, so the
        compiled artifact already holds everything this needs.
        """
        if self._config_path is not None:
            return load_index_runtime_configs(self._config_path)

        from edumatcher.config_artifact import load_compiled_config

        compiled = load_compiled_config()
        if compiled is None:
            log.warning(
                "no compiled configuration at %s — no indices will be "
                "calculated. Run pm-config-deploy to install one.",
                COMPILED_CONFIG_FILE,
            )
            return []
        return index_runtime_configs(compiled.engine)

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
        log.debug("index flow summary: %s", summary)
        self._debug_counts.clear()
        self._debug_last_summary = now

    def _state_path(self, cfg: IndexRuntimeConfig) -> Path:
        return Path(cfg.state_file)

    def _load_state(self, cfg: IndexRuntimeConfig) -> _RestoredState:
        state_path = self._state_path(cfg)
        log.debug("loading index state index_id=%s path=%s", cfg.id, state_path)
        if self._reset and state_path.exists():
            state_path.unlink()
            log.info(
                "removed state file due to --reset index_id=%s path=%s",
                cfg.id,
                state_path,
            )
            return _RestoredState()

        if not state_path.exists():
            return _RestoredState()

        payload = json.loads(state_path.read_text(encoding="utf-8"))
        state_id = str(payload.get("index_id", "")).upper()
        if state_id and state_id != cfg.id:
            raise ValueError(
                f"State file '{state_path}' belongs to index '{state_id}', expected '{cfg.id}'. Use --reset."
            )

        constituents = [str(sym).upper() for sym in payload.get("constituents", [])]
        if constituents and constituents != sorted(cfg.constituents):
            log.warning(
                "index %s: the persisted constituent set %s differs from the "
                "configured %s (runtime ADD/DELIST); keeping the persisted one. "
                "Use --reset to return to the configuration.",
                cfg.id,
                constituents,
                sorted(cfg.constituents),
            )

        divisor_raw = payload.get("divisor")
        divisor = float(divisor_raw) if divisor_raw is not None else None

        last_prices_raw = payload.get("last_prices", {})
        last_prices: dict[str, float] = {}
        if isinstance(last_prices_raw, dict):
            for symbol, price in last_prices_raw.items():
                try:
                    last_prices[str(symbol).upper()] = float(price)
                except TypeError, ValueError:
                    continue

        shares_raw = payload.get("outstanding_shares", {})
        shares: dict[str, int] = {}
        if isinstance(shares_raw, dict):
            for symbol, count in shares_raw.items():
                try:
                    shares[str(symbol).upper()] = int(count)
                except TypeError, ValueError:
                    continue

        eod_finalized = payload.get("eod_finalized") is True
        day: DaySummary | None = None
        day_values = [payload.get(key) for key in ("day_open", "day_high", "day_low")]
        if not eod_finalized and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in day_values
        ):
            open_, high, low = (float(v) for v in day_values)
            day = DaySummary(open=open_, high=high, low=low)
        return _RestoredState(
            divisor=divisor,
            last_prices=last_prices,
            constituents=constituents or None,
            shares=shares,
            day=day,
            eod_finalized=eod_finalized,
        )

    def _write_state(
        self,
        idx: _ManagedIndex,
        calc: IndexCalculator,
        day: DaySummary | None,
        last_level: float,
    ) -> None:
        state_path = self._state_path(idx.cfg)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "index_id": idx.cfg.id,
            "description": idx.cfg.description,
            "divisor": calc.divisor,
            "constituents": calc.constituent_symbols(),
            "outstanding_shares": {
                symbol: calc.shares_outstanding(symbol)
                for symbol in calc.constituent_symbols()
            },
            "last_prices": {
                symbol: calc.last_price(symbol) for symbol in calc.constituent_symbols()
            },
            # The day is restored while the session is still open, so a
            # restart mid-session keeps the day's open/high/low (C10).
            "day_open": day.open if day else None,
            "day_high": day.high if day else None,
            "day_low": day.low if day else None,
            "eod_finalized": idx.eod_finalized_for_session,
            "last_level": last_level,
            "last_updated": time.time(),
        }
        # Staged and renamed: the file is the restore authority (K7) and is
        # written every checkpoint, so a kill mid-write must leave the
        # previous one whole -- a truncated file would stop startup.
        atomic_write_text(state_path, json.dumps(payload, indent=2))
        log.debug(
            "persisted index state index_id=%s level=%s path=%s",
            idx.cfg.id,
            last_level,
            state_path,
        )

    def _persist_state(self, idx: _ManagedIndex, last_level: float) -> None:
        self._write_state(idx, idx.calc, idx.day, last_level)
        idx.dirty = False
        idx.last_checkpoint = time.monotonic()

    def _initialise(self) -> None:
        configs = self._runtime_configs()
        log.info("loaded %d index runtime config(s)", len(configs))
        for cfg in configs:
            restored = self._load_state(cfg)
            divisor = restored.divisor
            is_fresh_start = divisor is None
            live_symbols = restored.constituents or list(cfg.constituents)
            constituents = [
                ConstituentConfig(
                    symbol=symbol,
                    shares_outstanding=restored.shares.get(
                        symbol, cfg.outstanding_shares.get(symbol, 0)
                    ),
                    initial_price=cfg.reference_prices.get(
                        symbol, restored.last_prices.get(symbol, 0.0)
                    ),
                )
                for symbol in live_symbols
            ]
            calc = IndexCalculator(
                constituents=constituents,
                base_value=cfg.base_value,
                divisor=divisor,
                last_prices=restored.last_prices,
            )
            history = IndexHistory(cfg.history_file)
            managed = _ManagedIndex(
                cfg=cfg,
                calc=calc,
                history=history,
                eod_finalized_for_session=restored.eod_finalized,
                day=restored.day,
            )
            self._indices[cfg.id] = managed
            for symbol in live_symbols:
                self._constituent_to_indices.setdefault(symbol, set()).add(cfg.id)
                self._subscribe_book(symbol)

            level = calc.recalculate()
            if is_fresh_start:
                history.append(
                    {
                        "type": "INIT",
                        "ts_ns": time.time_ns(),
                        "index_id": cfg.id,
                        "base_value": cfg.base_value,
                        "divisor": calc.divisor,
                        "constituents": live_symbols,
                        "level": level,
                    }
                )
                log.debug("initialized fresh index history index_id=%s", cfg.id)
            self._persist_state(managed, level)
            log.info(
                "index ready index_id=%s constituents=%d level=%s",
                cfg.id,
                len(live_symbols),
                level,
            )

    def _update_day_ohlc(self, idx: _ManagedIndex, level: float) -> None:
        idx.day = _extend_day(idx.day, level)

    def _commit(
        self, idx: _ManagedIndex, calc: IndexCalculator, record: dict[str, Any]
    ) -> float:
        """Make ``calc``, a changed copy of ``idx.calc``, the index's state.

        The state file (the restore authority) is written first, then the
        history record, and only then is the copy swapped in and the level
        published. An OSError from either write leaves memory, the wire and
        the state file as they were and propagates; the caller rejects, and a
        retry applies the command once (C5).
        """
        level = calc.recalculate()
        day = _extend_day(idx.day, level)
        self._write_state(idx, calc, day, level)
        try:
            idx.history.write_through(
                {
                    "type": record["type"],
                    "ts_ns": time.time_ns(),
                    "index_id": idx.cfg.id,
                    **record,
                    "level": level,
                }
            )
        except OSError:
            try:
                self._write_state(idx, idx.calc, idx.day, idx.calc.recalculate())
            except OSError as exc:
                log.error(
                    "index %s: could not restore the state file after a failed "
                    "history write; it holds the rejected command: %s",
                    idx.cfg.id,
                    exc,
                )
            raise
        idx.calc = calc
        idx.day = day
        idx.dirty = False
        idx.last_checkpoint = time.monotonic()
        self._publish_level(idx, level, force=True)
        return level

    def _publish_level(
        self, idx: _ManagedIndex, level: float, force: bool = False
    ) -> None:
        now = time.monotonic()
        if not force and now - idx.last_publish_time < idx.cfg.publish_interval_sec:
            idx.pending = True
            return

        aggregate_cap = idx.calc.aggregate_cap()
        frames = make_index_update_msg(
            index_id=idx.cfg.id,
            level=level,
            aggregate_cap=aggregate_cap,
            divisor=idx.calc.divisor,
            session_state=idx.session_state,
            day=idx.day.to_dict() if idx.day is not None else None,
        )
        self._pub_sock.send_multipart(frames)
        idx.last_publish_time = now
        idx.pending = False
        self._dbg_count("index_updates_published")

    def _finalize_eod(self) -> None:
        log.info("finalizing EOD for %d index(es)", len(self._indices))
        for idx in self._indices.values():
            if idx.eod_finalized_for_session:
                continue
            level = idx.calc.recalculate()
            self._update_day_ohlc(idx, level)
            idx.session_state = "CLOSED"

            # The EOD close is just another level update — it is published
            # live (below) and picked up by pm-stats' index_level_snapshots /
            # index_daily_stats tables like every other tick. It is not
            # written to the structural JSONL audit log.
            self._publish_level(idx, level, force=True)
            idx.eod_finalized_for_session = True
            idx.dirty = True
            idx.last_publish_time = 0.0
        self._checkpoint(force=True)

    def _handle_engine_eod(self) -> None:
        """system.eod is the engine's last message at every stop, the end of
        the day or not. Finalise, and ask for the session status again: an
        engine that comes back mid-session says so only in its reply (C4)."""
        self._finalize_eod()
        self._session_status_received = False

    def _handle_trade(self, payload: dict[str, Any], catch_up: bool = False) -> None:
        """Apply a trade's price. A ``catch_up`` price (a book snapshot's
        last_price) may be yesterday's, so it extends the day but does not
        open it: the day's open is the session's first print (C2)."""
        symbol_raw = payload.get("symbol")
        price_raw = payload.get("price")
        if not isinstance(symbol_raw, str):
            return
        if not isinstance(price_raw, (int, float, str)):
            return
        try:
            price = float(price_raw)
        except TypeError, ValueError:
            return
        if not (math.isfinite(price) and price > 0.0):
            self._dbg_count("trade_price_rejected")
            return
        symbol = symbol_raw.upper()
        target_indices = self._constituent_to_indices.get(symbol, set())
        if not target_indices:
            self._dbg_count("trade_symbol_not_indexed")
            log.debug("trade symbol=%s not used by any configured index", symbol)
            return
        self._dbg_count("trade_updates")
        for index_id in target_indices:
            idx = self._indices[index_id]
            idx.calc.update_price(symbol, price)
            idx.dirty = True
            level = idx.calc.recalculate()
            # Guarded: the arguments are evaluated whether or not the record
            # is emitted.
            if log.isEnabledFor(logging.DEBUG):
                log.debug(
                    "trade applied index_id=%s symbol=%s price=%.6f level=%.6f "
                    "divisor=%.6f cap=%.6f",
                    index_id,
                    symbol,
                    price,
                    level,
                    idx.calc.divisor,
                    idx.calc.aggregate_cap(),
                )
            if not catch_up or idx.day is not None:
                self._update_day_ohlc(idx, level)
            self._publish_level(idx, level)

    def _reset_for_new_session(self) -> None:
        for idx in self._indices.values():
            idx.eod_finalized_for_session = False
            idx.day = None

    def _resume_session(self) -> None:
        """The engine is trading again after a stop: the session has not
        ended, so a close latched by its system.eod must not stand (C4)."""
        for idx in self._indices.values():
            idx.eod_finalized_for_session = False

    def _apply_phase(self, state: str) -> None:
        """Day bookkeeping for the engine's phase. PRE_OPEN, the only state
        after CLOSED, starts the day: the opening uncross prints before the
        engine publishes the phase that follows it, so a later phase must not
        clear the day (C2)."""
        if state == SessionState.PRE_OPEN.value:
            self._reset_for_new_session()
        elif state == SessionState.CLOSED.value:
            self._finalize_eod()
        elif state in _TRADING_DAY_STATES:
            self._resume_session()

    def _handle_session_state(self, payload: dict[str, Any]) -> None:
        state = str(payload.get("state", "")).upper()
        log.info("received session.state=%s", state)
        for idx in self._indices.values():
            idx.session_state = state or idx.session_state
        self._apply_phase(state)
        self._checkpoint(force=True)

    def _request_session_status(self) -> None:
        try:
            self._engine_push.send_multipart(
                make_session_state_request_msg(_SESSION_STATUS_GATEWAY_ID)
            )
        except zmq.Again as exc:
            if not self._session_status_warning_logged:
                log.warning("could not request engine session status: %s", exc)
                self._session_status_warning_logged = True

    def _handle_session_status(self, payload: dict[str, Any]) -> None:
        try:
            state = SessionState(str(payload.get("state", "")).upper()).value
        except ValueError:
            log.warning("invalid initial session status: %s", payload)
            return

        log.info("received initial engine session status=%s", state)
        self._session_status_received = True
        self._request_snapshots()
        if state != SessionState.CLOSED.value:
            self._apply_phase(state)
        for idx in self._indices.values():
            idx.session_state = state
            self._publish_level(idx, idx.calc.recalculate(), force=True)

    def _subscribe_book(self, symbol: str) -> None:
        # Subscribed for good rather than per request: a subscription made
        # just before the request can reach the engine after its reply.
        self._sub_sock.setsockopt(zmq.SUBSCRIBE, topic_book_snapshot(symbol).encode())

    def _request_snapshots(self) -> None:
        """Ask the engine for every constituent's book, whose last_price
        catches the index up on trades it missed while it or the engine was
        down (C11). No sequence checking: a missed print is replaced by the
        next one, and this covers the restarts."""
        for symbol in sorted(
            s for s, ids in self._constituent_to_indices.items() if ids
        ):
            try:
                self._engine_push.send_multipart(make_book_snapshot_request_msg(symbol))
            except zmq.Again:
                log.debug("could not request book snapshot symbol=%s", symbol)
                continue
            self._awaiting_snapshot.add(symbol)

    def _handle_book_snapshot(self, symbol: str, payload: dict[str, Any]) -> None:
        if symbol not in self._awaiting_snapshot:
            return
        self._awaiting_snapshot.discard(symbol)
        # _handle_trade refuses a missing or unusable price, as for a trade.
        self._handle_trade(
            {"symbol": symbol, "price": payload.get("last_price")}, catch_up=True
        )

    def _handle_history_request(self, payload: dict[str, Any]) -> None:
        gateway_id = _clamp_id(payload.get("gateway_id", ""))
        if not gateway_id:
            return
        log.debug("handling history request gateway_id=%s", gateway_id)

        index_id = _clamp_id(payload.get("index_id", ""))
        idx = self._indices.get(index_id)
        if idx is None:
            self._pub_sock.send_multipart(
                make_index_error_msg(gateway_id, f"Unknown index_id '{index_id}'")
            )
            return

        default_from_ns = time.time_ns() - 30 * 86400 * 1_000_000_000
        try:
            from_ts_ns = _int_field(payload, "from_ts_ns", default_from_ns)
            to_ts_ns = _int_field(payload, "to_ts_ns", time.time_ns())
            max_records = _int_field(payload, "max_records", 10_000)
        except ValueError as exc:
            self._pub_sock.send_multipart(make_index_error_msg(gateway_id, str(exc)))
            return
        if to_ts_ns < from_ts_ns:
            self._pub_sock.send_multipart(
                make_index_error_msg(gateway_id, "to_ts_ns must be >= from_ts_ns")
            )
            return

        default_types = sorted(STRUCTURAL_RECORD_TYPES)
        types_raw = payload.get("types", default_types)
        if not isinstance(types_raw, list):
            types_raw = default_types
        record_types = {str(t).upper() for t in types_raw}

        try:
            records, warnings = idx.history.query(
                from_ts_ns, to_ts_ns, record_types, max_records
            )
        except ValueError as exc:
            self._pub_sock.send_multipart(make_index_error_msg(gateway_id, str(exc)))
            return

        self._pub_sock.send_multipart(
            make_index_history_msg(gateway_id, index_id, records, warnings=warnings)
        )
        log.debug(
            "history response gateway_id=%s index_id=%s records=%d warnings=%d",
            gateway_id,
            index_id,
            len(records),
            len(warnings),
        )

    def _handle_corp_action(self, payload: dict[str, Any]) -> None:
        gateway_id = _clamp_id(payload.get("gateway_id", ""))
        index_id = _clamp_id(payload.get("index_id", ""))
        command_id = str(payload.get("command_id", ""))[:64]
        action = _clamp_id(payload.get("action", ""))
        symbol = _clamp_id(payload.get("symbol", ""))
        log.info(
            "received corp action gateway_id=%s index_id=%s action=%s symbol=%s",
            gateway_id,
            index_id,
            action,
            symbol,
        )

        idx = self._indices.get(index_id)
        if not gateway_id or idx is None:
            if gateway_id:
                self._pub_sock.send_multipart(
                    make_index_error_msg(gateway_id, f"Unknown index_id '{index_id}'")
                )
            return

        old_divisor = idx.calc.divisor
        calc = copy.deepcopy(idx.calc)
        try:
            if action == "SPLIT":
                numerator = _int_field(payload, "ratio_numerator", 0)
                denominator = _int_field(payload, "ratio_denominator", 0)
                calc.apply_split(
                    symbol,
                    ratio_numerator=numerator,
                    ratio_denominator=denominator,
                )
                detail = f"{numerator}:{denominator}"
            elif action == "CASH_DIVIDEND":
                dividend = _float_field(payload, "dividend_per_share", 0.0)
                calc.apply_cash_dividend(symbol, dividend_per_share=dividend)
                detail = f"div={dividend}"
            elif action == "SHARES_ISSUANCE":
                if ("new_shares_outstanding" in payload) == ("shares_delta" in payload):
                    raise ValueError(
                        "exactly one of new_shares_outstanding and shares_delta "
                        "is required"
                    )
                if "shares_delta" in payload:
                    # Resolved against the live count, which only pm-index
                    # holds: splits and rebalances change it without a
                    # record a client could read it back from (C6).
                    delta = _int_field(payload, "shares_delta", 0)
                    new_shares = calc.shares_outstanding(symbol) + delta
                    if new_shares <= 0:
                        raise ValueError(
                            f"shares_delta {delta:+d} would leave {symbol} with "
                            f"{new_shares} shares"
                        )
                    detail = f"shares={new_shares} delta={delta:+d}"
                else:
                    new_shares = _int_field(payload, "new_shares_outstanding", 0)
                    detail = f"shares={new_shares}"
                calc.apply_shares_issuance(symbol, new_shares_outstanding=new_shares)
            else:
                raise ValueError(f"Unsupported corporate action '{action}'")
            level = self._commit(
                idx,
                calc,
                {
                    "type": "CORP_ACTION",
                    "symbol": symbol,
                    "action": action,
                    "detail": detail,
                    "old_divisor": old_divisor,
                    "new_divisor": calc.divisor,
                },
            )
        except (KeyError, ValueError, OSError) as exc:
            self._pub_sock.send_multipart(
                make_index_corp_action_ack_msg(
                    gateway_id,
                    accepted=False,
                    reason=_reason(exc),
                    index_id=index_id,
                    command_id=command_id,
                )
            )
            return

        self._pub_sock.send_multipart(
            make_index_corp_action_ack_msg(
                gateway_id,
                accepted=True,
                reason="",
                index_id=index_id,
                level=level,
                divisor=idx.calc.divisor,
                old_divisor=old_divisor,
                command_id=command_id,
                shares_outstanding=idx.calc.shares_outstanding(symbol),
            )
        )

    def _handle_constituent_change(self, payload: dict[str, Any]) -> None:
        gateway_id = _clamp_id(payload.get("gateway_id", ""))
        index_id = _clamp_id(payload.get("index_id", ""))
        command_id = str(payload.get("command_id", ""))[:64]
        change_type = _clamp_id(payload.get("change_type", ""))
        symbol = _clamp_id(payload.get("symbol", ""))
        log.info(
            "received constituent change gateway_id=%s index_id=%s change=%s symbol=%s",
            gateway_id,
            index_id,
            change_type,
            symbol,
        )

        idx = self._indices.get(index_id)
        if not gateway_id or idx is None:
            if gateway_id:
                self._pub_sock.send_multipart(
                    make_index_error_msg(gateway_id, f"Unknown index_id '{index_id}'")
                )
            return

        old_divisor = idx.calc.divisor
        calc = copy.deepcopy(idx.calc)
        try:
            if change_type == "DELIST":
                calc.delist_symbol(symbol)
                record: dict[str, Any] = {
                    "type": "DELIST",
                    "symbol": symbol,
                    "old_divisor": old_divisor,
                    "new_divisor": calc.divisor,
                }
            elif change_type == "ADD":
                if symbol not in idx.cfg.tradeable_symbols:
                    raise ValueError(f"{symbol} is not a configured symbol")
                shares = _int_field(payload, "shares_outstanding", 0)
                initial_price = _float_field(payload, "initial_price", 0.0)
                calc.add_constituent(symbol, shares, initial_price)
                record = {
                    "type": "ADD_CONSTITUENT",
                    "symbol": symbol,
                    "shares_outstanding": shares,
                    "reference_price": initial_price,
                    "old_divisor": old_divisor,
                    "new_divisor": calc.divisor,
                }
            else:
                raise ValueError(f"Unsupported change_type '{change_type}'")
            level = self._commit(idx, calc, record)
        except (KeyError, ValueError, OSError) as exc:
            self._pub_sock.send_multipart(
                make_index_constituent_change_ack_msg(
                    gateway_id,
                    accepted=False,
                    reason=_reason(exc),
                    index_id=index_id,
                    command_id=command_id,
                )
            )
            return
        if change_type == "DELIST":
            self._constituent_to_indices.get(symbol, set()).discard(index_id)
        else:
            self._constituent_to_indices.setdefault(symbol, set()).add(index_id)
            self._subscribe_book(symbol)

        self._pub_sock.send_multipart(
            make_index_constituent_change_ack_msg(
                gateway_id,
                accepted=True,
                reason="",
                index_id=index_id,
                level=level,
                divisor=idx.calc.divisor,
                old_divisor=old_divisor,
                command_id=command_id,
            )
        )

    def _handle_rebalance(self, payload: dict[str, Any]) -> None:
        """Batch shares-outstanding update for existing constituents.

        Mechanically identical to the SHARES_ISSUANCE corporate action,
        applied once per {symbol, new_shares_outstanding} pair in the batch,
        followed by a single recalculate/publish/persist — not one per
        symbol. The whole batch is validated (shape, unknown symbols,
        non-positive share counts) first, then applied to a copy of the
        index that is swapped in only once persisted, so an invalid entry or
        a failure anywhere rejects the batch without applying any of it.
        """
        gateway_id = _clamp_id(payload.get("gateway_id", ""))
        index_id = _clamp_id(payload.get("index_id", ""))
        command_id = str(payload.get("command_id", ""))[:64]
        updates_raw = payload.get("updates")
        log.info(
            "received rebalance gateway_id=%s index_id=%s updates=%s",
            gateway_id,
            index_id,
            updates_raw,
        )

        idx = self._indices.get(index_id)
        if not gateway_id or idx is None:
            if gateway_id:
                self._pub_sock.send_multipart(
                    make_index_error_msg(gateway_id, f"Unknown index_id '{index_id}'")
                )
            return

        def _reject(reason: str) -> None:
            self._pub_sock.send_multipart(
                make_index_rebalance_ack_msg(
                    gateway_id,
                    accepted=False,
                    reason=reason,
                    index_id=index_id,
                    command_id=command_id,
                )
            )

        if not isinstance(updates_raw, list) or not updates_raw:
            _reject("updates must be a non-empty list")
            return

        known_symbols = set(idx.calc.constituent_symbols())
        parsed: list[tuple[str, int]] = []
        seen_symbols: set[str] = set()
        for i, entry in enumerate(updates_raw):
            if not isinstance(entry, dict):
                _reject(f"updates[{i}] must be a mapping")
                return
            symbol_raw = entry.get("symbol")
            if not isinstance(symbol_raw, str) or not symbol_raw.strip():
                _reject(f"updates[{i}].symbol must be a non-empty string")
                return
            symbol = _clamp_id(symbol_raw.strip())
            if symbol not in known_symbols:
                _reject(f"updates[{i}]: {symbol} is not a constituent of {index_id}")
                return
            if symbol in seen_symbols:
                _reject(f"updates[{i}]: duplicate symbol {symbol}")
                return
            try:
                if "new_shares_outstanding" not in entry:
                    raise ValueError("missing")
                new_shares = _int_field(entry, "new_shares_outstanding", 0)
            except ValueError:
                _reject(f"updates[{i}].new_shares_outstanding must be an integer")
                return
            if new_shares <= 0:
                _reject(f"updates[{i}].new_shares_outstanding must be positive")
                return
            seen_symbols.add(symbol)
            parsed.append((symbol, new_shares))

        old_divisor = idx.calc.divisor
        calc = copy.deepcopy(idx.calc)
        applied = [symbol for symbol, _ in parsed]
        try:
            for symbol, new_shares in parsed:
                calc.apply_shares_issuance(symbol, new_shares)
            level = self._commit(
                idx,
                calc,
                {
                    "type": "REBALANCE",
                    "symbols": applied,
                    "updates": [
                        {"symbol": symbol, "new_shares_outstanding": shares}
                        for symbol, shares in parsed
                    ],
                    "old_divisor": old_divisor,
                    "new_divisor": calc.divisor,
                },
            )
        except (ValueError, OSError) as exc:
            _reject(str(exc))
            return

        self._pub_sock.send_multipart(
            make_index_rebalance_ack_msg(
                gateway_id,
                accepted=True,
                index_id=index_id,
                level=level,
                divisor=idx.calc.divisor,
                updated_symbols=len(applied),
                command_id=command_id,
                old_divisor=old_divisor,
            )
        )

    def _handle_sub_message(self, frames: list[bytes]) -> None:
        """One message from the engine feed; a bad one is logged, never fatal."""
        if frames and frames[0].startswith(_BOOK_TOPIC_PREFIX):
            symbol = frames[0][len(_BOOK_TOPIC_PREFIX) :].decode(errors="replace")
            if symbol not in self._awaiting_snapshot:
                return
        try:
            topic, payload = decode(frames)
        except Exception as exc:
            log.warning("malformed sub frame: %s", exc)
            return
        self._dbg_count("sub_messages")
        try:
            if topic == TOPIC_TRADE_EXECUTED:
                self._handle_trade(payload)
            elif topic == TOPIC_SESSION_STATE:
                self._handle_session_state(payload)
            elif topic == topic_session_status(_SESSION_STATUS_GATEWAY_ID):
                self._handle_session_status(payload)
            elif topic == TOPIC_EOD:
                self._handle_engine_eod()
            elif topic.startswith(_BOOK_TOPIC_PREFIX.decode()):
                self._handle_book_snapshot(topic[len(_BOOK_TOPIC_PREFIX) :], payload)
        except Exception as exc:
            log.warning("error handling %s: %s", topic, exc)

    def _handle_pull_message(self, frames: list[bytes]) -> None:
        """One command to this process; a bad one is logged, never fatal."""
        try:
            topic, payload = decode(frames)
        except Exception as exc:
            log.warning("malformed pull frame: %s", exc)
            return
        self._dbg_count("pull_messages")
        try:
            if topic == TOPIC_INDEX_HISTORY_REQUEST:
                self._handle_history_request(payload)
            elif topic == TOPIC_INDEX_CORP_ACTION:
                self._handle_corp_action(payload)
            elif topic == TOPIC_INDEX_CONSTITUENT_CHANGE:
                self._handle_constituent_change(payload)
            elif topic == TOPIC_INDEX_REBALANCE:
                self._handle_rebalance(payload)
        except Exception as exc:
            log.warning("error handling %s: %s", topic, exc)

    def _publish_pending(self, now: float) -> None:
        """Broadcast each throttled level whose publish interval has passed."""
        for idx in self._indices.values():
            if (
                idx.pending
                and now - idx.last_publish_time >= idx.cfg.publish_interval_sec
            ):
                self._publish_level(idx, idx.calc.recalculate())

    def _checkpoint(self, now: float | None = None, force: bool = False) -> None:
        """Write the state of every index whose prices moved since its last write.

        ``force`` ignores the interval (phase change, shutdown); otherwise an
        index is written only once ``CHECKPOINT_INTERVAL_SEC`` has passed.
        """
        now = time.monotonic() if now is None else now
        for idx in self._indices.values():
            if not idx.dirty:
                continue
            if not force and now - idx.last_checkpoint < CHECKPOINT_INTERVAL_SEC:
                continue
            try:
                self._persist_state(idx, idx.calc.recalculate())
            except OSError as exc:
                # The state file is a checkpoint: failing to write it must not
                # stop the live index (C8). It stays dirty and is retried at
                # the next interval, not on every pass.
                idx.last_checkpoint = now
                log.error(
                    "index %s: state checkpoint failed, retrying in %.0f s: %s",
                    idx.cfg.id,
                    CHECKPOINT_INTERVAL_SEC,
                    exc,
                )

    def _flush_history(self) -> None:
        """Flush every history file; a failure keeps the records buffered for
        the next pass and is logged once until a flush succeeds (C8)."""
        for idx in self._indices.values():
            try:
                idx.history.flush()
            except OSError as exc:
                if not idx.history_flush_failed:
                    log.error(
                        "index %s: history flush failed, retrying: %s",
                        idx.cfg.id,
                        exc,
                    )
                idx.history_flush_failed = True
                continue
            idx.history_flush_failed = False

    def run(self) -> None:
        self._initialise()
        self._request_session_status()
        next_status_request = time.monotonic() + _SESSION_STATUS_RETRY_SEC
        status_warning_at = time.monotonic() + _SESSION_STATUS_WARNING_SEC
        log.info("index process entering main poll loop")

        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        poller.register(self._pull_sock, zmq.POLLIN)
        poller.register(self._health_rep, zmq.POLLIN)

        reporter = self._reporter
        while self._running:
            if reporter is not None:
                reporter.tick()
            now = time.monotonic()
            if not self._session_status_received and now >= next_status_request:
                if now >= status_warning_at and not self._session_status_warning_logged:
                    log.warning(
                        "engine session status has not been received; index updates "
                        "may report an unknown current phase until the engine replies"
                    )
                    self._session_status_warning_logged = True
                self._request_session_status()
                next_status_request = now + _SESSION_STATUS_RETRY_SEC
            try:
                socks = dict(poller.poll(timeout=200))
            except zmq.ZMQError as exc:
                if exc.errno != errno.EINTR:
                    raise
                # A signal: its handler has run, and stop() is what ends the
                # loop (C9).
                continue

            if self._health_rep in socks:
                answer_health_ping(self._health_rep)

            # Take what is already queued, up to a bound, before polling
            # again: one poll per message was a syscall, a checkpoint scan
            # and a history flush per trade (P2).
            if self._sub_sock in socks:
                self._drain(self._sub_sock, self._handle_sub_message)

            if self._pull_sock in socks:
                self._drain(self._pull_sock, self._handle_pull_message)

            self._publish_pending(time.monotonic())
            self._checkpoint()
            self._flush_history()

    def _drain(self, sock: Any, handle: Callable[[list[bytes]], None]) -> None:
        handle(sock.recv_multipart())
        drained = 1
        while drained < _DRAIN_PER_WAKE and sock.poll(0):
            handle(sock.recv_multipart())
            drained += 1

    def stop(self) -> None:
        """Ask the poll loop to exit; run() returns within one poll timeout."""
        log.info("stop requested")
        self._running = False

    def attach_reporter(self, reporter: HealthReporter) -> None:
        """Ship this process's health beacon through ``reporter`` (main()).
        No application metrics in this plan (design A6.6): vitals only."""
        self._reporter = reporter

    def close(self) -> None:
        if self._reporter is not None:
            self._reporter.stop()
        self._flush_debug_summary(force=True)
        log.info("closing index process")
        self._checkpoint(force=True)
        for idx in self._indices.values():
            try:
                idx.history.close()  # flushes
            except OSError as exc:
                log.error(
                    "index %s: history file could not be written at close; "
                    "its unwritten records are lost: %s",
                    idx.cfg.id,
                    exc,
                )
        self._sub_sock.close()
        self._engine_push.close()
        self._pull_sock.close()
        self._pub_sock.close()
        self._health_rep.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EduMatcher index process")
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-index")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Ignore/delete persisted index state and initialise from config",
    )
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
        help=(
            "Explicit WARNING log level (the default); -v and --log-level take precedence"
        ),
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


@exit_on_config_error
def main() -> None:
    from edumatcher.config_artifact import report_deployment

    parser = build_parser()
    args = parser.parse_args()
    log_level = _configure_logging(args)
    log.info("starting pm-index with log level %s", logging.getLevelName(log_level))
    report_deployment()
    try:
        proc = IndexProcess(reset=bool(args.reset))
    except Exception as exc:
        log.critical("fatal startup error: %s", exc)
        sys.exit(1)
    # Without these, SIGTERM (docker stop, pm-opctl stop) killed the process
    # outright: close() never ran, so pending history writes were never flushed
    # and the sockets never released. Installed here rather than in run() so
    # tests that drive run() directly keep pytest's own handlers.
    signal.signal(signal.SIGINT, lambda *_: proc.stop())
    signal.signal(signal.SIGTERM, lambda *_: proc.stop())
    reporter = HealthReporter.start_from_compiled_config(_CLIENT_NAME)
    if reporter is not None:
        proc.attach_reporter(reporter)
    try:
        proc.run()
    except Exception as exc:
        log.critical("fatal runtime error: %s", exc)
        raise
    finally:
        proc.close()


if __name__ == "__main__":
    main()

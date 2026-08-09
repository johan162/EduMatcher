from __future__ import annotations

import argparse
from collections import defaultdict
import errno
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import zmq

from edumatcher.config import (
    COMPILED_CONFIG_FILE,
    ENGINE_PUB_ADDR,
    INDEX_PUB_ADDR,
    INDEX_PULL_ADDR,
)
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
from edumatcher.messaging.bus import make_publisher, make_puller, make_subscriber
from edumatcher.models.message import (
    decode,
    make_index_constituent_change_ack_msg,
    make_index_corp_action_ack_msg,
    make_index_error_msg,
    make_index_history_msg,
    make_index_rebalance_ack_msg,
    make_index_update_msg,
)
from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED
from edumatcher.models.generated.session import TOPIC_SESSION_STATE
from edumatcher.models.generated.index import (
    TOPIC_INDEX_CONSTITUENT_CHANGE,
    TOPIC_INDEX_CORP_ACTION,
    TOPIC_INDEX_HISTORY_REQUEST,
    TOPIC_INDEX_REBALANCE,
    DaySummary,
)

log = logging.getLogger(__name__)
_DEBUG_SUMMARY_INTERVAL_SEC = 5.0

#: Longest identifier this process will echo back into a reply, matching the
#: `max_len` the index spec declares for gateway_id / index_id / symbol.
_MAX_ID_LEN = 32


def _clamp_id(value: object, limit: int = _MAX_ID_LEN) -> str:
    """Normalise an identifier arriving from the wire, bounded.

    The bound is what makes the replies safe to build. Every rejection path
    here quotes the identifier it could not resolve, and since 5.2f those
    replies are generated constructors that *validate* — so an inbound
    index_id of five thousand characters would raise MessageValidationError
    out of a handler that has no exception guard, and take pm-index down while
    answering a malformed request. Before adoption the same input merely
    published an oversized reason.

    Truncating loses nothing real: an identifier longer than the spec allows
    cannot name an index or a gateway that exists, so a clamped one fails the
    same lookup and produces the same rejection.
    """
    return str(value).upper()[:limit]


_CLIENT_NAME = "pm-index"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"


@dataclass
class _ManagedIndex:
    cfg: IndexRuntimeConfig
    calc: IndexCalculator
    history: IndexHistory
    session_state: str = "PRE_OPEN"
    last_publish_time: float = 0.0
    eod_finalized_for_session: bool = False
    #: The session's open/high/low, or None before the first level is
    #: computed. One optional record rather than three optional floats: the
    #: three were only ever set and cleared together, and holding them
    #: separately left a half-set state representable in the one place it
    #: could actually arise (design section 16.2).
    day: DaySummary | None = None
    day_close: float | None = None


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

        self._indices: dict[str, _ManagedIndex] = {}
        self._constituent_to_indices: dict[str, set[str]] = {}

        self._sub_sock = make_subscriber(
            ENGINE_PUB_ADDR,
            TOPIC_TRADE_EXECUTED,
            TOPIC_SESSION_STATE,
            "system.eod",
        )
        self._pull_sock = make_puller(INDEX_PULL_ADDR)
        self._pub_sock = make_publisher(INDEX_PUB_ADDR)
        self._debug_counts: defaultdict[str, int] = defaultdict(int)
        self._debug_last_summary = time.monotonic()
        log.debug(
            "index process initialized config=%s reset=%s sub=%s pull=%s pub=%s",
            self._config_path,
            self._reset,
            ENGINE_PUB_ADDR,
            INDEX_PULL_ADDR,
            INDEX_PUB_ADDR,
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

    def _load_state(
        self, cfg: IndexRuntimeConfig
    ) -> tuple[float | None, dict[str, float]]:
        state_path = self._state_path(cfg)
        log.debug("loading index state index_id=%s path=%s", cfg.id, state_path)
        if self._reset and state_path.exists():
            state_path.unlink()
            log.info(
                "removed state file due to --reset index_id=%s path=%s",
                cfg.id,
                state_path,
            )
            return None, {}

        if not state_path.exists():
            return None, {}

        payload = json.loads(state_path.read_text(encoding="utf-8"))
        state_id = str(payload.get("index_id", "")).upper()
        if state_id and state_id != cfg.id:
            raise ValueError(
                f"State file '{state_path}' belongs to index '{state_id}', expected '{cfg.id}'. Use --reset."
            )

        constituents = [str(sym).upper() for sym in payload.get("constituents", [])]
        if constituents and constituents != cfg.constituents:
            raise ValueError(
                f"State/config constituent mismatch for index '{cfg.id}'. Use --reset."
            )

        divisor_raw = payload.get("divisor")
        divisor = float(divisor_raw) if divisor_raw is not None else None

        last_prices_raw = payload.get("last_prices", {})
        last_prices: dict[str, float] = {}
        if isinstance(last_prices_raw, dict):
            for symbol, price in last_prices_raw.items():
                try:
                    last_prices[str(symbol).upper()] = float(price)
                except (TypeError, ValueError):
                    continue
        return divisor, last_prices

    def _persist_state(self, idx: _ManagedIndex, last_level: float) -> None:
        state_path = self._state_path(idx.cfg)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "index_id": idx.cfg.id,
            "description": idx.cfg.description,
            "divisor": idx.calc.divisor,
            "constituents": idx.calc.constituent_symbols(),
            "last_prices": {
                symbol: idx.calc.last_price(symbol)
                for symbol in idx.calc.constituent_symbols()
            },
            # The state file keeps three flat keys: it is a persisted
            # diagnostic, not the wire, and nothing reads them back.
            "day_open": idx.day.open if idx.day else None,
            "day_high": idx.day.high if idx.day else None,
            "day_low": idx.day.low if idx.day else None,
            "last_level": last_level,
            "last_updated": time.time(),
        }
        state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        log.debug(
            "persisted index state index_id=%s level=%s path=%s",
            idx.cfg.id,
            last_level,
            state_path,
        )

    def _initialise(self) -> None:
        configs = self._runtime_configs()
        log.info("loaded %d index runtime config(s)", len(configs))
        for cfg in configs:
            divisor, last_prices = self._load_state(cfg)
            is_fresh_start = divisor is None
            constituents = [
                ConstituentConfig(
                    symbol=symbol,
                    shares_outstanding=cfg.outstanding_shares[symbol],
                    initial_price=cfg.reference_prices[symbol],
                )
                for symbol in cfg.constituents
            ]
            calc = IndexCalculator(
                constituents=constituents,
                base_value=cfg.base_value,
                divisor=divisor,
                last_prices=last_prices,
            )
            history = IndexHistory(cfg.history_file)
            managed = _ManagedIndex(cfg=cfg, calc=calc, history=history)
            self._indices[cfg.id] = managed
            for symbol in cfg.constituents:
                self._constituent_to_indices.setdefault(symbol, set()).add(cfg.id)

            level = calc.recalculate()
            if is_fresh_start:
                history.append(
                    {
                        "type": "INIT",
                        "timestamp": time.time(),
                        "index_id": cfg.id,
                        "base_value": cfg.base_value,
                        "divisor": calc.divisor,
                        "constituents": cfg.constituents,
                        "level": level,
                    }
                )
                log.debug("initialized fresh index history index_id=%s", cfg.id)
            self._persist_state(managed, level)
            log.info(
                "index ready index_id=%s constituents=%d level=%s",
                cfg.id,
                len(cfg.constituents),
                level,
            )

    def _update_day_ohlc(self, idx: _ManagedIndex, level: float) -> None:
        if idx.day is None:
            idx.day = DaySummary(open=level, high=level, low=level)
            return
        idx.day = DaySummary(
            open=idx.day.open,
            high=max(idx.day.high, level),
            low=min(idx.day.low, level),
        )

    def _publish_level(
        self, idx: _ManagedIndex, level: float, force: bool = False
    ) -> None:
        now = time.monotonic()
        if not force and now - idx.last_publish_time < idx.cfg.publish_interval_sec:
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
        self._dbg_count("index_updates_published")

    def _finalize_eod(self) -> None:
        log.info("finalizing EOD for %d index(es)", len(self._indices))
        for idx in self._indices.values():
            if idx.eod_finalized_for_session:
                continue
            level = idx.calc.recalculate()
            idx.day_close = level
            self._update_day_ohlc(idx, level)
            idx.session_state = "CLOSED"

            # The EOD close is just another level update — it is published
            # live (below) and picked up by pm-stats' index_level_snapshots /
            # index_daily_stats tables like every other tick. It is not
            # written to the structural JSONL audit log.
            self._publish_level(idx, level, force=True)
            self._persist_state(idx, level)
            idx.eod_finalized_for_session = True
            idx.last_publish_time = 0.0

    def _handle_trade(self, payload: dict[str, Any]) -> None:
        symbol_raw = payload.get("symbol")
        price_raw = payload.get("price")
        if not isinstance(symbol_raw, str):
            return
        if not isinstance(price_raw, (int, float, str)):
            return
        try:
            price = float(price_raw)
        except (TypeError, ValueError):
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
            level = idx.calc.recalculate()
            log.debug(
                "trade applied index_id=%s symbol=%s price=%.6f level=%.6f divisor=%.6f cap=%.6f",
                index_id,
                symbol,
                price,
                level,
                idx.calc.divisor,
                idx.calc.aggregate_cap(),
            )
            self._update_day_ohlc(idx, level)
            self._publish_level(idx, level)

    def _reset_for_new_session(self) -> None:
        for idx in self._indices.values():
            idx.eod_finalized_for_session = False
            idx.day = None
            idx.day_close = None

    def _handle_session_state(self, payload: dict[str, Any]) -> None:
        state = str(payload.get("state", "")).upper()
        log.info("received session.state=%s", state)
        for idx in self._indices.values():
            idx.session_state = state or idx.session_state
        if state in {"OPENING_AUCTION", "CONTINUOUS"}:
            self._reset_for_new_session()
        if state == "CLOSED":
            self._finalize_eod()

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

        default_from = time.time() - 30 * 86400
        from_ts = float(payload.get("from_ts", default_from))
        to_ts = float(payload.get("to_ts", time.time()))
        if to_ts < from_ts:
            self._pub_sock.send_multipart(
                make_index_error_msg(gateway_id, "to_ts must be >= from_ts")
            )
            return

        default_types = sorted(STRUCTURAL_RECORD_TYPES)
        types_raw = payload.get("types", default_types)
        if not isinstance(types_raw, list):
            types_raw = default_types
        record_types = {str(t).upper() for t in types_raw}
        max_records = int(payload.get("max_records", 10_000))

        try:
            records, warnings = idx.history.query(
                from_ts, to_ts, record_types, max_records
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

        try:
            old_divisor = idx.calc.divisor
            if action == "SPLIT":
                idx.calc.apply_split(
                    symbol,
                    ratio_numerator=int(payload.get("ratio_numerator", 0)),
                    ratio_denominator=int(payload.get("ratio_denominator", 0)),
                )
                detail = f"{int(payload.get('ratio_numerator', 0))}:{int(payload.get('ratio_denominator', 0))}"
            elif action == "CASH_DIVIDEND":
                idx.calc.apply_cash_dividend(
                    symbol,
                    dividend_per_share=float(payload.get("dividend_per_share", 0.0)),
                )
                detail = f"div={float(payload.get('dividend_per_share', 0.0))}"
            elif action == "SHARES_ISSUANCE":
                idx.calc.apply_shares_issuance(
                    symbol,
                    new_shares_outstanding=int(
                        payload.get("new_shares_outstanding", 0)
                    ),
                )
                detail = f"shares={int(payload.get('new_shares_outstanding', 0))}"
            else:
                raise ValueError(f"Unsupported corporate action '{action}'")
        except (KeyError, ValueError) as exc:
            self._pub_sock.send_multipart(
                make_index_corp_action_ack_msg(
                    gateway_id,
                    accepted=False,
                    reason=str(exc),
                    index_id=index_id,
                )
            )
            return

        level = idx.calc.recalculate()
        self._update_day_ohlc(idx, level)
        self._publish_level(idx, level, force=True)
        idx.history.append(
            {
                "type": "CORP_ACTION",
                "timestamp": time.time(),
                "index_id": idx.cfg.id,
                "symbol": symbol,
                "action": action,
                "detail": detail,
                "old_divisor": old_divisor,
                "new_divisor": idx.calc.divisor,
                "level": level,
            }
        )
        self._persist_state(idx, level)

        self._pub_sock.send_multipart(
            make_index_corp_action_ack_msg(
                gateway_id,
                accepted=True,
                reason="",
                index_id=index_id,
                level=level,
                divisor=idx.calc.divisor,
            )
        )

    def _handle_constituent_change(self, payload: dict[str, Any]) -> None:
        gateway_id = _clamp_id(payload.get("gateway_id", ""))
        index_id = _clamp_id(payload.get("index_id", ""))
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

        try:
            old_divisor = idx.calc.divisor
            if change_type == "DELIST":
                idx.calc.delist_symbol(symbol)
                self._constituent_to_indices.get(symbol, set()).discard(index_id)
                event_type = "DELIST"
                event_payload: dict[str, Any] = {
                    "symbol": symbol,
                    "old_divisor": old_divisor,
                    "new_divisor": idx.calc.divisor,
                }
            elif change_type == "ADD":
                shares = int(payload.get("shares_outstanding", 0))
                initial_price = float(payload.get("initial_price", 0.0))
                idx.calc.add_constituent(symbol, shares, initial_price)
                self._constituent_to_indices.setdefault(symbol, set()).add(index_id)
                event_type = "ADD_CONSTITUENT"
                event_payload = {
                    "symbol": symbol,
                    "shares_outstanding": shares,
                    "reference_price": initial_price,
                    "old_divisor": old_divisor,
                    "new_divisor": idx.calc.divisor,
                }
            else:
                raise ValueError(f"Unsupported change_type '{change_type}'")
        except (KeyError, ValueError) as exc:
            self._pub_sock.send_multipart(
                make_index_constituent_change_ack_msg(
                    gateway_id,
                    accepted=False,
                    reason=str(exc),
                    index_id=index_id,
                )
            )
            return

        level = idx.calc.recalculate()
        self._update_day_ohlc(idx, level)
        self._publish_level(idx, level, force=True)
        idx.history.append(
            {
                "type": event_type,
                "timestamp": time.time(),
                "index_id": idx.cfg.id,
                "level": level,
                **event_payload,
            }
        )
        self._persist_state(idx, level)

        self._pub_sock.send_multipart(
            make_index_constituent_change_ack_msg(
                gateway_id,
                accepted=True,
                reason="",
                index_id=index_id,
                level=level,
                divisor=idx.calc.divisor,
            )
        )

    def _handle_rebalance(self, payload: dict[str, Any]) -> None:
        """Batch shares-outstanding update for existing constituents.

        Mechanically identical to the SHARES_ISSUANCE corporate action,
        applied once per {symbol, new_shares_outstanding} pair in the batch,
        followed by a single recalculate/publish/persist — not one per
        symbol. The whole batch is validated (shape, unknown symbols,
        non-positive share counts) *before* any mutation, so an invalid
        entry anywhere in the batch rejects it without applying any of it —
        the same all-or-nothing guarantee the single-action corp-action
        handlers get for free by only ever doing one mutation.
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
                new_shares = int(entry["new_shares_outstanding"])
            except (KeyError, TypeError, ValueError):
                _reject(f"updates[{i}].new_shares_outstanding must be an integer")
                return
            if new_shares <= 0:
                _reject(f"updates[{i}].new_shares_outstanding must be positive")
                return
            seen_symbols.add(symbol)
            parsed.append((symbol, new_shares))

        old_divisor = idx.calc.divisor
        applied: list[str] = []
        try:
            for symbol, new_shares in parsed:
                idx.calc.apply_shares_issuance(symbol, new_shares)
                applied.append(symbol)
        except ValueError as exc:
            # Only the aggregate-cap-non-positive guard inside
            # apply_shares_issuance can still fail here — everything
            # pre-validated above. Whatever already applied in this batch
            # stays applied; the corp-action handlers accept the same
            # limitation for a single mutation, and this is no worse.
            log.error(
                "rebalance partially applied before failure index_id=%s applied=%s: %s",
                index_id,
                applied,
                exc,
            )
            _reject(f"applied {len(applied)} of {len(parsed)} update(s), then: {exc}")
            return

        level = idx.calc.recalculate()
        self._update_day_ohlc(idx, level)
        self._publish_level(idx, level, force=True)
        idx.history.append(
            {
                "type": "REBALANCE",
                "timestamp": time.time(),
                "index_id": idx.cfg.id,
                "symbols": applied,
                "old_divisor": old_divisor,
                "new_divisor": idx.calc.divisor,
                "level": level,
            }
        )
        self._persist_state(idx, level)

        self._pub_sock.send_multipart(
            make_index_rebalance_ack_msg(
                gateway_id,
                accepted=True,
                index_id=index_id,
                level=level,
                divisor=idx.calc.divisor,
                updated_symbols=len(applied),
                command_id=command_id,
            )
        )

    def run(self) -> None:
        self._initialise()
        log.info("index process entering main poll loop")

        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        poller.register(self._pull_sock, zmq.POLLIN)

        while self._running:
            try:
                socks = dict(poller.poll(timeout=200))
            except zmq.ZMQError as exc:
                if exc.errno != errno.EINTR:
                    raise
                break

            if self._sub_sock in socks:
                frames = self._sub_sock.recv_multipart()
                try:
                    topic, payload = decode(frames)
                except Exception as exc:
                    log.warning("malformed sub frame: %s", exc)
                else:
                    self._dbg_count("sub_messages")
                    if topic == TOPIC_TRADE_EXECUTED:
                        self._handle_trade(payload)
                    elif topic == TOPIC_SESSION_STATE:
                        self._handle_session_state(payload)
                    elif topic == "system.eod":
                        self._finalize_eod()

            if self._pull_sock in socks:
                frames = self._pull_sock.recv_multipart()
                try:
                    topic, payload = decode(frames)
                except Exception as exc:
                    log.warning("malformed pull frame: %s", exc)
                else:
                    self._dbg_count("pull_messages")
                    if topic == TOPIC_INDEX_HISTORY_REQUEST:
                        self._handle_history_request(payload)
                    elif topic == TOPIC_INDEX_CORP_ACTION:
                        self._handle_corp_action(payload)
                    elif topic == TOPIC_INDEX_CONSTITUENT_CHANGE:
                        self._handle_constituent_change(payload)
                    elif topic == TOPIC_INDEX_REBALANCE:
                        self._handle_rebalance(payload)

            for idx in self._indices.values():
                idx.history.flush()

    def close(self) -> None:
        self._flush_debug_summary(force=True)
        log.info("closing index process")
        for idx in self._indices.values():
            idx.history.flush()
            idx.history.close()
        self._sub_sock.close()
        self._pull_sock.close()
        self._pub_sock.close()


def _build_parser() -> argparse.ArgumentParser:
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

    parser = _build_parser()
    args = parser.parse_args()
    log_level = _configure_logging(args)
    log.info("starting pm-index with log level %s", logging.getLevelName(log_level))
    report_deployment(log)
    try:
        proc = IndexProcess(reset=bool(args.reset))
    except Exception as exc:
        log.error("fatal startup error: %s", exc)
        sys.exit(1)
    try:
        proc.run()
    except Exception as exc:
        log.error("fatal runtime error: %s", exc)
        raise
    finally:
        proc.close()


if __name__ == "__main__":
    main()

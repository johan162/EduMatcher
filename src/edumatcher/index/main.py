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
    ENGINE_CONFIG_FILE,
    ENGINE_PUB_ADDR,
    INDEX_PUB_ADDR,
    INDEX_PULL_ADDR,
)
from edumatcher.index.calculator import ConstituentConfig, IndexCalculator
from edumatcher.index.config_loader import (
    IndexRuntimeConfig,
    load_index_runtime_configs,
)
from edumatcher.index.history import STRUCTURAL_RECORD_TYPES, IndexHistory
from edumatcher.messaging.bus import make_publisher, make_puller, make_subscriber
from edumatcher.models.message import (
    decode,
    make_index_constituent_change_ack_msg,
    make_index_corp_action_ack_msg,
    make_index_error_msg,
    make_index_history_msg,
    make_index_update_msg,
)

log = logging.getLogger(__name__)
_DEBUG_SUMMARY_INTERVAL_SEC = 5.0


@dataclass
class _ManagedIndex:
    cfg: IndexRuntimeConfig
    calc: IndexCalculator
    history: IndexHistory
    session_state: str = "PRE_OPEN"
    last_publish_time: float = 0.0
    eod_finalized_for_session: bool = False
    day_open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    day_close: float | None = None


class IndexProcess:
    def __init__(self, config_path: Path, reset: bool = False) -> None:
        self._config_path = config_path
        self._reset = reset
        self._running = True

        self._indices: dict[str, _ManagedIndex] = {}
        self._constituent_to_indices: dict[str, set[str]] = {}

        self._sub_sock = make_subscriber(
            ENGINE_PUB_ADDR,
            "trade.executed",
            "session.state",
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
            "day_open": idx.day_open,
            "day_high": idx.day_high,
            "day_low": idx.day_low,
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
        configs = load_index_runtime_configs(self._config_path)
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
        if idx.day_open is None:
            idx.day_open = level
            idx.day_high = level
            idx.day_low = level
            return
        idx.day_high = max(idx.day_high or level, level)
        idx.day_low = min(idx.day_low or level, level)

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
            day_open=idx.day_open,
            day_high=idx.day_high,
            day_low=idx.day_low,
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
            idx.day_open = None
            idx.day_high = None
            idx.day_low = None
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
        gateway_id = str(payload.get("gateway_id", "")).upper()
        if not gateway_id:
            return
        log.debug("handling history request gateway_id=%s", gateway_id)

        index_id = str(payload.get("index_id", "")).upper()
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
        gateway_id = str(payload.get("gateway_id", "")).upper()
        index_id = str(payload.get("index_id", "")).upper()
        action = str(payload.get("action", "")).upper()
        symbol = str(payload.get("symbol", "")).upper()
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
        gateway_id = str(payload.get("gateway_id", "")).upper()
        index_id = str(payload.get("index_id", "")).upper()
        change_type = str(payload.get("change_type", "")).upper()
        symbol = str(payload.get("symbol", "")).upper()
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
                    if topic == "trade.executed":
                        self._handle_trade(payload)
                    elif topic == "session.state":
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
                    if topic == "index.history_request":
                        self._handle_history_request(payload)
                    elif topic == "index.corp_action":
                        self._handle_corp_action(payload)
                    elif topic == "index.constituent_change":
                        self._handle_constituent_change(payload)

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
        "--config",
        "-c",
        default=str(ENGINE_CONFIG_FILE),
        help="Engine config YAML path",
    )
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
    return parser


def _configure_logging(args: argparse.Namespace) -> int:
    if args.log_level:
        level_name = str(args.log_level).upper()
        level = getattr(logging, level_name, logging.WARNING)
    elif args.verbose >= 2:
        level = logging.DEBUG
    elif args.verbose == 1:
        level = logging.INFO
    elif args.quiet:
        level = logging.WARNING
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    return int(level)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    log_level = _configure_logging(args)
    log.info("starting pm-index with log level %s", logging.getLevelName(log_level))
    log.debug("resolved index config path=%s reset=%s", args.config, bool(args.reset))
    try:
        proc = IndexProcess(config_path=Path(str(args.config)), reset=bool(args.reset))
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

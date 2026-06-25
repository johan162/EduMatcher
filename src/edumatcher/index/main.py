from __future__ import annotations

import argparse
import json
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
from edumatcher.index.history import IndexHistory
from edumatcher.messaging.bus import make_publisher, make_puller, make_subscriber
from edumatcher.models.message import (
    decode,
    make_index_constituent_change_ack_msg,
    make_index_corp_action_ack_msg,
    make_index_error_msg,
    make_index_history_msg,
    make_index_update_msg,
)


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

    def _state_path(self, cfg: IndexRuntimeConfig) -> Path:
        return Path(cfg.state_file)

    def _load_state(
        self, cfg: IndexRuntimeConfig
    ) -> tuple[float | None, dict[str, float]]:
        state_path = self._state_path(cfg)
        if self._reset and state_path.exists():
            state_path.unlink()
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

    def _initialise(self) -> None:
        configs = load_index_runtime_configs(self._config_path)
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
            self._persist_state(managed, level)

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
        idx.history.append(
            {
                "type": "LEVEL",
                "timestamp": time.time(),
                "index_id": idx.cfg.id,
                "level": level,
                "session_state": idx.session_state,
                "aggregate_cap": aggregate_cap,
                "divisor": idx.calc.divisor,
            }
        )
        idx.last_publish_time = now

    def _finalize_eod(self) -> None:
        for idx in self._indices.values():
            if idx.eod_finalized_for_session:
                continue
            level = idx.calc.recalculate()
            idx.day_close = level
            self._update_day_ohlc(idx, level)
            idx.session_state = "CLOSED"

            idx.history.append(
                {
                    "type": "EOD",
                    "timestamp": time.time(),
                    "index_id": idx.cfg.id,
                    "level": level,
                    "session_state": "CLOSED",
                    "aggregate_cap": idx.calc.aggregate_cap(),
                    "divisor": idx.calc.divisor,
                    "open": idx.day_open,
                    "high": idx.day_high,
                    "low": idx.day_low,
                    "close": idx.day_close,
                }
            )
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
        for index_id in target_indices:
            idx = self._indices[index_id]
            idx.calc.update_price(symbol, price)
            level = idx.calc.recalculate()
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

        types_raw = payload.get("types", ["LEVEL", "EOD"])
        if not isinstance(types_raw, list):
            types_raw = ["LEVEL", "EOD"]
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

    def _handle_corp_action(self, payload: dict[str, Any]) -> None:
        gateway_id = str(payload.get("gateway_id", "")).upper()
        index_id = str(payload.get("index_id", "")).upper()
        action = str(payload.get("action", "")).upper()
        symbol = str(payload.get("symbol", "")).upper()

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

        poller = zmq.Poller()
        poller.register(self._sub_sock, zmq.POLLIN)
        poller.register(self._pull_sock, zmq.POLLIN)

        while self._running:
            socks = dict(poller.poll(timeout=200))

            if self._sub_sock in socks:
                frames = self._sub_sock.recv_multipart()
                topic, payload = decode(frames)
                if topic == "trade.executed":
                    self._handle_trade(payload)
                elif topic == "session.state":
                    self._handle_session_state(payload)
                elif topic == "system.eod":
                    self._finalize_eod()

            if self._pull_sock in socks:
                frames = self._pull_sock.recv_multipart()
                topic, payload = decode(frames)
                if topic == "index.history_request":
                    self._handle_history_request(payload)
                elif topic == "index.corp_action":
                    self._handle_corp_action(payload)
                elif topic == "index.constituent_change":
                    self._handle_constituent_change(payload)

            for idx in self._indices.values():
                idx.history.flush()

    def close(self) -> None:
        for idx in self._indices.values():
            idx.history.flush()
            idx.history.close()
        self._sub_sock.close()
        self._pull_sock.close()
        self._pub_sock.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EduMatcher index process")
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
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    proc = IndexProcess(config_path=Path(str(args.config)), reset=bool(args.reset))
    try:
        proc.run()
    finally:
        proc.close()


if __name__ == "__main__":
    main()

"""WP-IDX02 (C2, C4, C10): the day's open/high/low and the close across
session phases, engine stops and pm-index restarts.

See docs-design/reviews/EduMatcher-Index-Review-2026-11.md.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

import edumatcher.index.main as index_main
from edumatcher.index.config_loader import IndexRuntimeConfig
from edumatcher.models.message import decode, encode


class _Sock:
    def __init__(self) -> None:
        self.options: list[tuple[int, bytes]] = []
        self.sent: list[list[bytes]] = []

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        pass

    def setsockopt(self, option: int, value: bytes) -> None:
        self.options.append((option, value))


class _Exchange:
    """The five patched sockets and one index config, shared by restarts."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.pub = _Sock()
        self.engine_push = _Sock()
        monkeypatch.setattr(index_main, "make_subscriber", lambda *_a, **_k: _Sock())
        monkeypatch.setattr(
            index_main, "make_pusher", lambda *_a, **_k: self.engine_push
        )
        monkeypatch.setattr(index_main, "make_puller", lambda *_a, **_k: _Sock())
        monkeypatch.setattr(index_main, "make_publisher", lambda *_a, **_k: self.pub)
        monkeypatch.setattr(index_main, "make_replier", lambda *_a, **_k: _Sock())
        cfg = IndexRuntimeConfig(
            id="EDU100",
            description="Education 100",
            base_value=1000.0,
            publish_interval_sec=0.0,
            history_file=str(tmp_path / "history.jsonl"),
            state_file=str(tmp_path / "state.json"),
            constituents=["AAPL", "MSFT"],
            outstanding_shares={"AAPL": 100, "MSFT": 100},
            reference_prices={"AAPL": 100.0, "MSFT": 100.0},
            tradeable_symbols=frozenset({"AAPL", "MSFT", "GOOG", "AMZN"}),
        )
        monkeypatch.setattr(index_main, "load_index_runtime_configs", lambda _p: [cfg])
        self._config_path = tmp_path / "engine.yaml"

    def start(self) -> index_main.IndexProcess:
        proc = index_main.IndexProcess(config_path=self._config_path)
        proc._initialise()
        return proc

    def updates(self) -> list[dict[str, Any]]:
        out = []
        for frames in self.pub.sent:
            topic, payload = decode(frames)
            if topic == "index.update":
                out.append(payload)
        return out


@pytest.fixture()
def exchange(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[_Exchange, None, None]:
    yield _Exchange(tmp_path, monkeypatch)


@pytest.fixture()
def proc(exchange: _Exchange) -> Generator[index_main.IndexProcess, None, None]:
    p = exchange.start()
    yield p
    p.close()


def _state(proc: index_main.IndexProcess, state: str) -> None:
    proc._handle_sub_message(encode("session.state", {"state": state}))


def _status(proc: index_main.IndexProcess, state: str) -> None:
    proc._handle_sub_message(encode("system.session_status.PM_INDEX", {"state": state}))


def _trade(proc: index_main.IndexProcess, symbol: str, price: float) -> None:
    proc._handle_sub_message(
        encode("trade.executed", {"symbol": symbol, "price": price})
    )


def _eod(proc: index_main.IndexProcess) -> None:
    proc._handle_sub_message(encode("system.eod", {"books": []}))


@pytest.mark.parametrize(
    "phases", [["PRE_OPEN", "OPENING_AUCTION"], ["PRE_OPEN"]], ids=["auction", "direct"]
)
def test_the_opening_print_is_the_days_open(
    proc: index_main.IndexProcess, exchange: _Exchange, phases: list[str]
) -> None:
    """The engine publishes the uncross's trades before the CONTINUOUS that
    follows them; the CONTINUOUS must not clear the day (C2)."""
    for phase in phases:
        _state(proc, phase)
    _trade(proc, "AAPL", 150.0)  # the opening uncross: level 1250
    _state(proc, "CONTINUOUS")
    _trade(proc, "MSFT", 101.0)  # level 1255

    day = exchange.updates()[-1]["day"]
    assert day == {"open": 1250.0, "high": 1255.0, "low": 1250.0}


def test_pre_open_after_the_close_starts_a_new_day(
    proc: index_main.IndexProcess,
) -> None:
    _state(proc, "CONTINUOUS")
    _trade(proc, "AAPL", 110.0)
    _state(proc, "CLOSED")
    idx = proc._indices["EDU100"]
    assert idx.eod_finalized_for_session is True

    _state(proc, "PRE_OPEN")

    assert idx.day is None
    assert idx.eod_finalized_for_session is False


def test_an_engine_stop_mid_session_does_not_suppress_the_real_close(
    proc: index_main.IndexProcess, exchange: _Exchange
) -> None:
    """system.eod is the engine's last message at every stop (C4)."""
    _status(proc, "CONTINUOUS")
    _trade(proc, "AAPL", 110.0)
    _eod(proc)
    _status(proc, "CONTINUOUS")
    _trade(proc, "AAPL", 120.0)
    exchange.pub.sent.clear()

    _state(proc, "CLOSED")

    closes = [u for u in exchange.updates() if u["session_state"] == "CLOSED"]
    assert closes and closes[-1]["level"] == pytest.approx(1100.0)


def test_an_engine_stop_does_not_clear_the_day(
    proc: index_main.IndexProcess, exchange: _Exchange
) -> None:
    _status(proc, "CONTINUOUS")
    _trade(proc, "AAPL", 90.0)  # 950, the low
    _trade(proc, "AAPL", 110.0)
    _eod(proc)
    _state(proc, "CONTINUOUS")
    _trade(proc, "AAPL", 105.0)

    assert exchange.updates()[-1]["day"] == {
        "open": 950.0,
        "high": 1050.0,
        "low": 950.0,
    }


def test_an_engine_stop_makes_pm_index_ask_for_the_session_status_again(
    proc: index_main.IndexProcess, exchange: _Exchange
) -> None:
    """Without it, an engine that comes back without a session.state (sessions
    disabled) never tells pm-index the session goes on."""
    _status(proc, "CONTINUOUS")
    assert proc._session_status_received is True

    _eod(proc)

    assert proc._session_status_received is False


def test_a_restart_mid_session_keeps_the_days_open(
    exchange: _Exchange,
) -> None:
    first = exchange.start()
    _status(first, "CONTINUOUS")
    _trade(first, "AAPL", 90.0)  # open 950
    _trade(first, "AAPL", 110.0)  # high 1050
    first.close()

    second = exchange.start()
    try:
        exchange.pub.sent.clear()
        _status(second, "CONTINUOUS")
        assert exchange.updates()[-1]["day"] == {
            "open": 950.0,
            "high": 1050.0,
            "low": 950.0,
        }
    finally:
        second.close()


def test_a_restart_after_the_close_starts_a_fresh_day(
    exchange: _Exchange,
) -> None:
    first = exchange.start()
    _status(first, "CONTINUOUS")
    _trade(first, "AAPL", 110.0)
    _state(first, "CLOSED")
    first.close()

    second = exchange.start()
    try:
        assert second._indices["EDU100"].day is None
        assert second._indices["EDU100"].eod_finalized_for_session is True
    finally:
        second.close()


def test_a_pre_open_status_after_a_restart_drops_a_day_that_never_closed(
    exchange: _Exchange,
) -> None:
    """pm-index stopped before yesterday's close: the restored day is stale
    once the engine says the new day's PRE_OPEN is under way."""
    first = exchange.start()
    _status(first, "CONTINUOUS")
    _trade(first, "AAPL", 110.0)
    first.close()

    second = exchange.start()
    try:
        assert second._indices["EDU100"].day is not None
        _status(second, "PRE_OPEN")
        assert second._indices["EDU100"].day is None
    finally:
        second.close()

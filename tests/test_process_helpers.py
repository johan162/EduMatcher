"""
Tests for process helper functions and classes that don't require live ZMQ:
  - clearing.main.PositionRecord
  - stats.main._DayAccum
  - ticker.main._build_line
  - viewer.main._build_display
  - scheduler.main._load_schedule / _time_today
"""

from __future__ import annotations

import argparse
import errno
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, cast

import pytest
import zmq

from edumatcher.clearing.main import PositionRecord
from edumatcher.stats.main import _DayAccum
from edumatcher.ticker.main import _build_line
from edumatcher.viewer.main import _build_display
from edumatcher.scheduler.main import (
    DEFAULT_SCHEDULE,
    _load_schedule,
    _time_today,
)

# ===========================================================================
# PositionRecord (clearing)
# ===========================================================================


class TestPositionRecord:
    def _make(self) -> PositionRecord:
        return PositionRecord(symbol="AAPL", gateway_id="GW01")

    # Opening positions
    def test_open_long_position(self) -> None:
        rec = self._make()
        rec.apply_fill(100, 150.0, is_buy=True)
        assert rec.position == 100
        assert rec.avg_cost == 150.0
        assert rec.realized_pnl == 0.0

    def test_open_short_position(self) -> None:
        rec = self._make()
        rec.apply_fill(50, 200.0, is_buy=False)
        assert rec.position == -50
        assert rec.avg_cost == 200.0

    # Unrealized P&L
    def test_unrealized_pnl_long_profit(self) -> None:
        rec = self._make()
        rec.apply_fill(100, 100.0, is_buy=True)
        rec.last_price = 110.0
        assert rec.unrealized_pnl == pytest.approx(1000.0)

    def test_unrealized_pnl_short_profit(self) -> None:
        rec = self._make()
        rec.apply_fill(100, 100.0, is_buy=False)
        rec.last_price = 90.0
        assert rec.unrealized_pnl == pytest.approx(1000.0)

    def test_unrealized_pnl_zero_position(self) -> None:
        rec = self._make()
        assert rec.unrealized_pnl == 0.0

    # Adding to position (VWAP update)
    def test_add_to_long_updates_vwap(self) -> None:
        rec = self._make()
        rec.apply_fill(100, 100.0, is_buy=True)
        rec.apply_fill(100, 110.0, is_buy=True)
        assert rec.position == 200
        assert rec.avg_cost == pytest.approx(105.0)

    def test_add_to_short_updates_vwap(self) -> None:
        rec = self._make()
        rec.apply_fill(100, 100.0, is_buy=False)
        rec.apply_fill(100, 90.0, is_buy=False)
        assert rec.position == -200
        assert rec.avg_cost == pytest.approx(95.0)

    # Reducing position
    def test_reduce_long_realizes_profit(self) -> None:
        rec = self._make()
        rec.apply_fill(100, 100.0, is_buy=True)
        rec.apply_fill(50, 120.0, is_buy=False)
        assert rec.realized_pnl == pytest.approx(1000.0)  # 50 * (120-100)
        assert rec.position == 50

    def test_reduce_short_realizes_profit(self) -> None:
        rec = self._make()
        rec.apply_fill(100, 100.0, is_buy=False)
        rec.apply_fill(50, 80.0, is_buy=True)
        assert rec.realized_pnl == pytest.approx(1000.0)  # 50 * (100-80)
        assert rec.position == -50

    # Closing position fully
    def test_close_long_zeroes_position(self) -> None:
        rec = self._make()
        rec.apply_fill(100, 100.0, is_buy=True)
        rec.apply_fill(100, 110.0, is_buy=False)
        assert rec.position == 0.0
        assert rec.avg_cost == 0.0
        assert rec.realized_pnl == pytest.approx(1000.0)

    # Reversing position (long → short)
    def test_reverse_long_to_short(self) -> None:
        rec = self._make()
        rec.apply_fill(100, 100.0, is_buy=True)
        rec.apply_fill(150, 110.0, is_buy=False)
        # 100 closed at profit, 50 new short
        assert rec.position == -50
        assert rec.realized_pnl == pytest.approx(1000.0)

    # Reversing short → long
    def test_reverse_short_to_long(self) -> None:
        rec = self._make()
        rec.apply_fill(100, 100.0, is_buy=False)
        rec.apply_fill(150, 90.0, is_buy=True)
        assert rec.position == 50
        assert rec.realized_pnl == pytest.approx(1000.0)


# ===========================================================================
# _DayAccum (stats)
# ===========================================================================


class TestDayAccum:
    def _make(self) -> _DayAccum:
        return _DayAccum(date="2026-05-06", symbol="AAPL")

    def test_first_trade_sets_open(self) -> None:
        acc = self._make()
        acc.on_trade(150.0, 100)
        assert acc.open_price == 150.0
        assert acc.close_price == 150.0
        assert acc.high_price == 150.0
        assert acc.low_price == 150.0
        assert acc.volume == 100
        assert acc.trade_count == 1

    def test_high_low_tracking(self) -> None:
        acc = self._make()
        acc.on_trade(100.0, 50)
        acc.on_trade(120.0, 50)
        acc.on_trade(90.0, 50)
        assert acc.high_price == 120.0
        assert acc.low_price == 90.0
        assert acc.close_price == 90.0
        assert acc.open_price == 100.0

    def test_vwap_calculation(self) -> None:
        acc = self._make()
        acc.on_trade(100.0, 100)
        acc.on_trade(200.0, 100)
        # VWAP = (100*100 + 200*100) / 200 = 150
        assert acc.vwap == pytest.approx(150.0)

    def test_vwap_none_when_no_trades(self) -> None:
        acc = self._make()
        assert acc.vwap is None

    def test_largest_trade_tracking(self) -> None:
        acc = self._make()
        acc.on_trade(100.0, 50)
        acc.on_trade(105.0, 200)
        acc.on_trade(110.0, 100)
        assert acc.largest_trade_qty == 200
        assert acc.largest_trade_price == 105.0

    def test_on_eod_book(self) -> None:
        acc = self._make()
        acc.on_eod_book(149.5, 150.5)
        assert acc.close_bid == 149.5
        assert acc.close_ask == 150.5

    def test_on_eod_book_none_values(self) -> None:
        acc = self._make()
        acc.on_eod_book(None, None)
        assert acc.close_bid is None
        assert acc.close_ask is None

    def test_volume_accumulates(self) -> None:
        acc = self._make()
        for _ in range(5):
            acc.on_trade(100.0, 20)
        assert acc.volume == 100
        assert acc.trade_count == 5


# ===========================================================================
# _build_line (ticker)
# ===========================================================================


class TestBuildLine:
    def test_empty_symbols_no_error(self) -> None:
        line = _build_line([], {}, {})
        assert line is not None

    def test_single_symbol_no_data(self) -> None:
        line = _build_line(["AAPL"], {}, {})
        text = line.plain
        assert "AAPL" in text

    def test_last_price_from_live(self) -> None:
        live = {"AAPL": {"last_price": 155.0, "best_bid": None, "best_ask": None}}
        line = _build_line(["AAPL"], {}, live)
        assert "155.00" in line.plain

    def test_last_price_from_daily_fallback(self) -> None:
        daily = {"AAPL": {"close_price": 148.0, "open_price": 145.0}}
        line = _build_line(["AAPL"], daily, {})
        assert "148.00" in line.plain

    def test_pct_change_positive(self) -> None:
        daily = {"AAPL": {"open_price": 100.0, "close_price": 110.0}}
        live = {"AAPL": {"last_price": 110.0, "best_bid": None, "best_ask": None}}
        line = _build_line(["AAPL"], daily, live)
        assert "+10.00%" in line.plain

    def test_pct_change_negative(self) -> None:
        daily = {"AAPL": {"open_price": 100.0, "close_price": 90.0}}
        live = {"AAPL": {"last_price": 90.0, "best_bid": None, "best_ask": None}}
        line = _build_line(["AAPL"], daily, live)
        assert "-10.00%" in line.plain

    def test_high_low_shown(self) -> None:
        daily = {"AAPL": {"high_price": 160.0, "low_price": 140.0}}
        line = _build_line(["AAPL"], daily, {})
        assert "H:160.00" in line.plain
        assert "L:140.00" in line.plain

    def test_volume_shown(self) -> None:
        daily = {"AAPL": {"volume": 12345, "trade_count": 42}}
        line = _build_line(["AAPL"], daily, {})
        assert "12,345" in line.plain
        assert "42T" in line.plain

    def test_bid_ask_shown(self) -> None:
        live = {"AAPL": {"last_price": None, "best_bid": 149.5, "best_ask": 150.5}}
        line = _build_line(["AAPL"], {}, live)
        assert "149.50" in line.plain
        assert "150.50" in line.plain

    def test_bid_only(self) -> None:
        live = {"AAPL": {"last_price": None, "best_bid": 149.5, "best_ask": None}}
        line = _build_line(["AAPL"], {}, live)
        assert "149.50" in line.plain

    def test_ask_only(self) -> None:
        live = {"AAPL": {"last_price": None, "best_bid": None, "best_ask": 150.5}}
        line = _build_line(["AAPL"], {}, live)
        assert "150.50" in line.plain

    def test_multiple_symbols_separated(self) -> None:
        live = {
            "AAPL": {"last_price": 150.0, "best_bid": None, "best_ask": None},
            "MSFT": {"last_price": 400.0, "best_bid": None, "best_ask": None},
        }
        line = _build_line(["AAPL", "MSFT"], {}, live)
        plain = line.plain
        assert "AAPL" in plain
        assert "MSFT" in plain
        assert "◆" in plain

    def test_no_last_price_shows_dash(self) -> None:
        line = _build_line(["AAPL"], {}, {})
        assert "—" in line.plain


# ===========================================================================
# _build_display (viewer)
# ===========================================================================


class TestBuildDisplay:
    def _snapshot(self) -> dict:
        return {
            "bids": [{"price": 149.5, "qty": 100, "count": 2}],
            "asks": [{"price": 150.5, "qty": 200, "count": 3}],
            "last_price": 150.0,
            "last_qty": 50,
            "last_buy_price": 149.9,
            "last_sell_price": 150.1,
            "recent_trades": [
                {"price": 150.0, "quantity": 50, "timestamp": 1746518400.0}
            ],
        }

    def test_returns_panel(self) -> None:
        from rich.panel import Panel

        result = _build_display(self._snapshot(), "AAPL", 5)
        assert isinstance(result, Panel)

    def test_empty_snapshot_no_error(self) -> None:
        result = _build_display({}, "MSFT", 5)
        assert result is not None

    def test_depth_limits_levels(self) -> None:
        snap = {
            "bids": [{"price": 100 - i, "qty": 10, "count": 1} for i in range(20)],
            "asks": [{"price": 101 + i, "qty": 10, "count": 1} for i in range(20)],
        }
        result = _build_display(snap, "AAPL", 3)
        assert result is not None

    def test_no_trades_no_error(self) -> None:
        snap: dict = {"bids": [], "asks": [], "recent_trades": []}
        result = _build_display(snap, "AAPL", 5)
        assert result is not None

    def test_none_prices_show_dash(self) -> None:
        snap = {
            "last_price": None,
            "last_qty": None,
            "last_buy_price": None,
            "last_sell_price": None,
        }
        result = _build_display(snap, "AAPL", 5)
        assert result is not None


# ===========================================================================
# Scheduler helpers
# ===========================================================================


class TestSchedulerHelpers:
    def test_time_today_parses(self) -> None:
        dt = _time_today("09:30")
        now = datetime.now()
        assert dt.hour == 9
        assert dt.minute == 30
        assert dt.year == now.year

    def test_load_schedule_falls_back_to_defaults_if_no_file(self) -> None:
        schedule = _load_schedule(None)
        assert schedule == DEFAULT_SCHEDULE

    def test_load_schedule_falls_back_to_defaults_if_missing_file(
        self, tmp_path: Path
    ) -> None:
        schedule = _load_schedule(tmp_path / "nonexistent.yaml")
        assert schedule == DEFAULT_SCHEDULE

    def test_load_schedule_from_yaml(self, tmp_path: Path) -> None:
        p = tmp_path / "cfg.yaml"
        p.write_text(textwrap.dedent("""
            schedule:
              pre_open: "08:00"
              opening_auction_start: "09:00"
              continuous_start: "09:30"
              closing_auction_start: "15:50"
              closing_auction_end: "16:00"
            """))
        schedule = _load_schedule(p)
        times = [t for t, _state in schedule]
        assert "09:30" in times

    def test_load_schedule_no_schedule_section_uses_defaults(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "cfg.yaml"
        p.write_text("symbols:\n  AAPL: {}\n")
        schedule = _load_schedule(p)
        assert schedule == DEFAULT_SCHEDULE

    def test_load_schedule_bad_yaml_falls_back(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.yaml"
        p.write_text(": : : invalid yaml :::\n")
        # Should not raise — falls back to defaults
        schedule = _load_schedule(p)
        assert schedule == DEFAULT_SCHEDULE


# ===========================================================================
# Viewer / Ticker main-loop coverage
# ===========================================================================


class TestViewerMain:
    def test_main_processes_book_update_and_closes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import edumatcher.viewer.main as viewer_main

        class _FakeSub:
            def __init__(self) -> None:
                self.closed = False

            def recv_multipart(self) -> list[bytes]:
                return [b"book.AAPL", b"{}"]

            def close(self) -> None:
                self.closed = True

        class _FakePush:
            def __init__(self) -> None:
                self.sent: list[list[bytes]] = []
                self.closed = False

            def send_multipart(self, msg: list[bytes]) -> None:
                self.sent.append(msg)

            def close(self) -> None:
                self.closed = True

        class _FakePoller:
            def __init__(self, sub: _FakeSub) -> None:
                self._sub = sub
                self._calls = 0

            def register(self, _sock: object, _evt: object) -> None:
                return

            def poll(self, timeout: int) -> list[tuple[object, int]]:
                _ = timeout
                self._calls += 1
                if self._calls == 1:
                    return [(self._sub, 1)]
                raise zmq.ZMQError(errno.EINTR)

        class _FakeLive:
            def __init__(self, **_kwargs: object) -> None:
                self.updated = 0
                self.refreshed = 0

            def __enter__(self) -> "_FakeLive":
                return self

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                _ = (exc_type, exc, tb)

            def update(self, _panel: object) -> None:
                self.updated += 1

            def refresh(self) -> None:
                self.refreshed += 1

        class _FakeThread:
            def __init__(self, target: Callable[[], None], daemon: bool) -> None:
                self._target = target
                self._daemon = daemon

            def start(self) -> None:
                _ = self._daemon
                self._target()

        sub = _FakeSub()
        push = _FakePush()

        monkeypatch.setattr(
            "edumatcher.viewer.main.argparse.ArgumentParser.parse_args",
            lambda _self: argparse.Namespace(symbol="aapl", depth=3),
        )
        monkeypatch.setattr(viewer_main, "make_subscriber", lambda *_args: sub)
        monkeypatch.setattr(viewer_main, "make_pusher", lambda *_args: push)
        monkeypatch.setattr(
            viewer_main,
            "make_book_snapshot_request_msg",
            lambda _symbol: [b"book.snapshot_request", b"{}"],
        )
        monkeypatch.setattr(
            viewer_main,
            "decode",
            lambda _frames: (
                "book.AAPL",
                {"bids": [], "asks": [], "recent_trades": []},
            ),
        )
        monkeypatch.setattr("edumatcher.viewer.main.time.sleep", lambda _s: None)
        monkeypatch.setattr("edumatcher.viewer.main.threading.Thread", _FakeThread)
        monkeypatch.setattr(viewer_main, "Live", _FakeLive)
        monkeypatch.setattr(
            "edumatcher.viewer.main.zmq.Poller",
            lambda: _FakePoller(sub),
        )

        viewer_main.main()

        assert sub.closed is True
        assert len(push.sent) == 1
        assert push.closed is True

    def test_main_handles_keyboard_interrupt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import edumatcher.viewer.main as viewer_main

        class _FakeSub:
            def __init__(self) -> None:
                self.closed = False

            def close(self) -> None:
                self.closed = True

        class _FakeLive:
            def __init__(self, **_kwargs: object) -> None:
                return

            def __enter__(self) -> "_FakeLive":
                return self

            def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
                _ = (exc_type, exc, tb)

            def update(self, _panel: object) -> None:
                return

            def refresh(self) -> None:
                raise KeyboardInterrupt()

        sub = _FakeSub()

        monkeypatch.setattr(
            "edumatcher.viewer.main.argparse.ArgumentParser.parse_args",
            lambda _self: argparse.Namespace(symbol="MSFT", depth=2),
        )
        monkeypatch.setattr(viewer_main, "make_subscriber", lambda *_args: sub)
        monkeypatch.setattr(
            "edumatcher.viewer.main.threading.Thread",
            lambda target, daemon: type("_T", (), {"start": lambda self: target()})(),
        )
        monkeypatch.setattr("edumatcher.viewer.main.time.sleep", lambda _s: None)
        monkeypatch.setattr(
            viewer_main,
            "make_pusher",
            lambda *_args: type(
                "_P",
                (),
                {"send_multipart": lambda self, _msg: None, "close": lambda self: None},
            )(),
        )
        monkeypatch.setattr(
            viewer_main, "make_book_snapshot_request_msg", lambda _symbol: [b"x", b"y"]
        )
        monkeypatch.setattr(viewer_main, "Live", _FakeLive)
        monkeypatch.setattr(
            "edumatcher.viewer.main.zmq.Poller",
            lambda: type(
                "_Poller",
                (),
                {
                    "register": lambda self, _sock, _evt: None,
                    "poll": lambda self, timeout: [],
                },
            )(),
        )

        viewer_main.main()
        assert sub.closed is True


class TestTickerMain:
    def test_receive_updates_live_data(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import edumatcher.ticker.main as ticker_main

        class _FakeSub:
            def __init__(self) -> None:
                self._msgs = [[b"book.AAPL", b"{}"]]

            def recv_multipart(self) -> list[bytes]:
                return self._msgs.pop(0)

            def close(self) -> None:
                return

        class _FakePoller:
            def __init__(self, sub: _FakeSub) -> None:
                self._sub = sub
                self._calls = 0

            def register(self, _sock: object, _evt: object) -> None:
                return

            def poll(self, timeout: int) -> list[tuple[object, int]]:
                _ = timeout
                self._calls += 1
                if self._calls == 1:
                    return [(self._sub, 1)]
                raise zmq.ZMQError(errno.EINTR)

        sub = _FakeSub()
        proc = ticker_main.TickerProcess(
            db_path=tmp_path / "stats.db",
            display_interval=10.0,
            db_interval=30.0,
        )
        proc.sub.close()
        proc.sub = cast(Any, sub)

        monkeypatch.setattr(
            "edumatcher.ticker.main.zmq.Poller",
            lambda: _FakePoller(sub),
        )
        monkeypatch.setattr(
            ticker_main,
            "decode",
            lambda _frames: (
                "book.AAPL",
                {
                    "last_price": 150.25,
                    "bids": [{"price": 150.2}],
                    "asks": [{"price": 150.3}],
                },
            ),
        )

        proc._receive()

        assert "AAPL" in proc._live
        assert proc._live["AAPL"]["best_bid"] == 150.2
        assert proc._live["AAPL"]["best_ask"] == 150.3
        assert proc._symbols == ["AAPL"]

    def test_run_prints_waiting_then_stops(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import edumatcher.ticker.main as ticker_main

        class _FakeSub:
            def __init__(self) -> None:
                self.closed = False

            def close(self) -> None:
                self.closed = True

        class _FakeThread:
            def __init__(self, target: Callable[[], None], daemon: bool) -> None:
                self._target = target
                self._daemon = daemon

            def start(self) -> None:
                _ = (self._target, self._daemon)

            def join(self, timeout: float | None = None) -> None:
                _ = timeout

        proc = ticker_main.TickerProcess(
            db_path=tmp_path / "stats.db",
            display_interval=1.0,
            db_interval=5.0,
        )
        sub = _FakeSub()
        proc.sub.close()
        proc.sub = cast(Any, sub)

        printed: list[object] = []

        monkeypatch.setattr("edumatcher.ticker.main.signal.signal", lambda *_args: None)
        monkeypatch.setattr("edumatcher.ticker.main.threading.Thread", _FakeThread)
        monkeypatch.setattr(
            ticker_main.console, "print", lambda msg, *a, **k: printed.append(msg)
        )
        monkeypatch.setattr(proc, "_refresh_db", lambda: None)
        monkeypatch.setattr("edumatcher.ticker.main.time.monotonic", lambda: 100.0)

        def _sleep_and_stop(_secs: float) -> None:
            proc._running = False

        monkeypatch.setattr("edumatcher.ticker.main.time.sleep", _sleep_and_stop)

        proc.run()

        assert sub.closed is True
        assert any("waiting for market data" in str(msg) for msg in printed)

    def test_main_parses_args_and_runs_process(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import edumatcher.ticker.main as ticker_main

        captured: dict[str, object] = {}

        class _FakeProcess:
            def __init__(
                self, db_path: Path, display_interval: float, db_interval: float
            ) -> None:
                captured["db_path"] = db_path
                captured["display_interval"] = display_interval
                captured["db_interval"] = db_interval

            def run(self) -> None:
                captured["ran"] = True

        monkeypatch.setattr(
            "edumatcher.ticker.main.argparse.ArgumentParser.parse_args",
            lambda _self: argparse.Namespace(
                db="/tmp/stats.db", interval=12.5, db_interval=44.0
            ),
        )
        monkeypatch.setattr(ticker_main, "TickerProcess", _FakeProcess)

        ticker_main.main()

        assert captured["ran"] is True
        assert captured["db_path"] == Path("/tmp/stats.db")
        assert captured["display_interval"] == 12.5
        assert captured["db_interval"] == 44.0

"""Focused behavior checks for engine review work package WP-ENG08."""

from __future__ import annotations

from datetime import date
import errno
import signal
from types import SimpleNamespace

import holidays
import pytest
import zmq

from edumatcher.engine.circuit_breaker import CircuitBreakerConfig, CircuitBreakerState
from edumatcher.engine.config_loader import DAY_KEYS, DaySchedule, ScheduleConfig
import edumatcher.engine.main as engine_main
import edumatcher.engine.order_book as order_book_module
import edumatcher.engine.schedule_resolve as schedule_resolve
from edumatcher.engine.order_book import OrderBook
from edumatcher.models.message import encode
from edumatcher.models.order import Order, OrderType, Side, SmpAction, TIF
from edumatcher.models.trade import reset_trade_ids_for_tests
from tests.engine_harness import (
    connect,
    make_engine,
    msgs,
    order_payload,
    submit_quote,
)


def _run_with_fake_poll_clock(
    engine,
    monkeypatch,
    *,
    messages: int,
    idle_passes: int,
    step_ns: int,
    on_maintenance=None,
) -> list[int]:
    state = {"now": 0, "polls": 0}
    frames = encode("system.performance_test", {})

    class Pull:
        def recv_multipart(self) -> list[bytes]:
            return list(frames)

        def close(self) -> None:
            pass

    pull = Pull()

    class Poller:
        def register(self, *_args, **_kwargs) -> None:
            pass

        def poll(self, timeout: int | None = None) -> dict[object, int]:
            state["polls"] += 1
            state["now"] += step_ns
            if state["polls"] > messages + idle_passes:
                engine._running = False
                raise zmq.ZMQError(errno.EINTR)
            return {pull: 1} if state["polls"] <= messages else {}

    engine.pull_sock = pull
    monkeypatch.setattr(zmq, "Poller", Poller)
    monkeypatch.setattr(engine_main, "DropCopyPublisher", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine_main, "load_and_bump_run_seq", lambda _: 1)
    monkeypatch.setattr(engine_main, "now_ns", lambda: state["now"])
    monkeypatch.setattr(signal, "signal", lambda *_args: None)
    monkeypatch.setattr(engine, "_restore_gtc", lambda: None)
    monkeypatch.setattr(engine, "_load_config", lambda: None)
    monkeypatch.setattr(engine, "_dispatch_pull_message", lambda *_args: None)
    monkeypatch.setattr(engine, "_echo_command", lambda *_args: False)
    monkeypatch.setattr(engine, "_flush_debug_summary", lambda **_kwargs: None)
    monkeypatch.setattr(engine, "_shutdown", lambda: None)
    reset_trade_ids_for_tests()
    monkeypatch.setattr(
        engine_main,
        "time",
        SimpleNamespace(
            perf_counter_ns=lambda: state["now"],
            perf_counter=lambda: state["now"] / 1e9,
            monotonic=lambda: state["now"] / 1e9,
            time=lambda: state["now"] / 1e9,
            time_ns=lambda: state["now"],
            sleep=lambda *_args: None,
        ),
    )

    maintenance_times: list[int] = []

    def run_maintenance() -> None:
        maintenance_times.append(state["now"])
        if on_maintenance is not None:
            on_maintenance(state["now"])

    monkeypatch.setattr(engine, "_run_maintenance", run_maintenance)
    engine.run()
    return maintenance_times


def test_run_throttles_busy_maintenance_but_keeps_idle_ticks(
    monkeypatch, tmp_path
) -> None:
    engine, _ = make_engine(monkeypatch, tmp_path)

    times = _run_with_fake_poll_clock(
        engine, monkeypatch, messages=1000, idle_passes=3, step_ns=1_000
    )

    assert len(times) == 4  # one burst slice, then one per idle poll


def test_due_circuit_breaker_reopens_within_one_busy_slice(
    monkeypatch, tmp_path
) -> None:
    engine, _ = make_engine(monkeypatch, tmp_path)
    breaker = CircuitBreakerState(
        symbol="AAPL", config=CircuitBreakerConfig(symbol="AAPL")
    )
    breaker.halted = True
    resume_at_ns = 200_000_000
    breaker.resume_at_ns = resume_at_ns
    breaker.halt_source = "CB"
    engine._circuit_breakers["AAPL"] = breaker
    engine._halted_symbols["AAPL"] = True
    reopened_at: list[int] = []

    def flush_breaker(now: int) -> None:
        engine._flush_circuit_breakers()
        if not breaker.halted:
            reopened_at.append(now)

    _run_with_fake_poll_clock(
        engine,
        monkeypatch,
        messages=205,
        idle_passes=0,
        step_ns=1_000_000,
        on_maintenance=flush_breaker,
    )

    assert len(reopened_at) == 1
    assert 0 <= reopened_at[0] - resume_at_ns <= 10_000_000


def test_fillable_quantity_stops_walking_after_the_required_amount(
    monkeypatch,
) -> None:
    book = OrderBook("AAPL")
    for i in range(100):
        resting = Order.create(
            symbol="AAPL",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=1,
            gateway_id="GW02",
            tif=TIF.DAY,
            price_ticks=10_100 + i,
            tick_decimals=2,
        )
        book.process(resting, match=False)

    calls = 0
    original = order_book_module._smp_policy

    def count_policy(*args):
        nonlocal calls
        calls += 1
        return original(*args)

    monkeypatch.setattr(order_book_module, "_smp_policy", count_policy)
    available = book.fillable_quantity(
        Side.BUY,
        None,
        gateway_id="GW01",
        smp_action=SmpAction.NONE,
        need=1,
    )

    assert available == 1
    assert calls == 1


def test_aon_fillable_and_unprevented_quantities_share_one_walk(
    monkeypatch,
) -> None:
    book = OrderBook("AAPL")
    for gateway_id, price in (
        ("GW01", 10_100),
        ("GW02", 10_101),
        ("GW02", 10_102),
        ("GW03", 10_103),
    ):
        resting = Order.create(
            symbol="AAPL",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=1,
            gateway_id=gateway_id,
            tif=TIF.DAY,
            price_ticks=price,
            tick_decimals=2,
        )
        book.process(resting, match=False)

    calls = 0
    original = order_book_module._smp_policy

    def count_policy(*args):
        nonlocal calls
        calls += 1
        return original(*args)

    monkeypatch.setattr(order_book_module, "_smp_policy", count_policy)
    fillable, unprevented = book.fillable_quantities(
        Side.BUY,
        None,
        gateway_id="GW01",
        smp_action=SmpAction.CANCEL_RESTING,
        need=2,
    )

    assert (fillable, unprevented) == (3, 4)
    assert calls == 4


def test_quote_and_orders_queries_use_indexes_without_changing_wire_bytes(
    monkeypatch, tmp_path
) -> None:
    engine, pub_sock = make_engine(
        monkeypatch, tmp_path, symbols=("AAPL", "MSFT"), mm_gateways=("GW01",)
    )
    connect(engine, "GW01")
    submit_quote(engine, "GW01", 100.0, 101.0, symbol="AAPL")
    engine._handle_new_order(
        order_payload(Side.BUY, OrderType.LIMIT, 5, "GW01", price=99.0, symbol="MSFT")
    )

    request_cases = (
        (lambda: engine._handle_quote_bootstrap_request({"gateway_id": "GW01"}),),
        (
            lambda: engine._handle_quote_legs_request(
                {"gateway_id": "GW01", "show": "ACTIVE"}
            ),
        ),
        (lambda: engine._handle_orders_request({"gateway_id": "GW01"}),),
    )
    first_frames = []
    for (request,) in request_cases:
        request()
        first_frames.append(pub_sock.sent[-1])

    monkeypatch.setattr(
        OrderBook,
        "resting_orders",
        lambda _self: pytest.fail("request scanned all resting orders"),
    )

    for (request,), expected in zip(request_cases, first_frames):
        request()
        assert pub_sock.sent[-1] == expected


def test_session_schedule_request_reuses_same_date_holiday_results(
    monkeypatch, tmp_path
) -> None:
    calls = 0

    class Calendar(dict):
        default_language = "en"

    calendar = Calendar({date(2026, 12, 25): "Christmas"})

    def build_calendar(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return calendar

    monkeypatch.setattr(holidays, "country_holidays", build_calendar)
    engine, pub_sock = make_engine(monkeypatch, tmp_path)
    assert engine._engine_config is not None
    engine._engine_config.locale.country = "WP-ENG08-TEST"
    day = DaySchedule("08:00", "09:50", "10:00", "16:50", "17:00")
    engine._engine_config.schedule = ScheduleConfig(
        days={key: day for key in DAY_KEYS}, holidays=None
    )

    engine._handle_session_schedule_request({"gateway_id": "GW01"})
    first = schedule_resolve.upcoming_holidays("WP-ENG08-TEST", engine._business_date())
    first_build_count = calls
    engine._handle_session_schedule_request({"gateway_id": "GW01"})
    second = schedule_resolve.upcoming_holidays(
        "WP-ENG08-TEST", engine._business_date()
    )

    assert first == second
    assert first_build_count > 0
    assert calls == first_build_count
    assert len(msgs(pub_sock, "system.session_schedule.GW01")) == 2

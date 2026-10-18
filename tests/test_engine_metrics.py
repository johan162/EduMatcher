"""Operator dashboard WP-A4: the engine's health metrics.

Built on ``tests/engine_harness.py`` (fake sockets, handlers called directly).
The suite-wide reject invariant lives in ``conftest.py``; this module adds the
per-counter checks, the book memory guard and the reporter wiring.
"""

from __future__ import annotations

import ast
import gc
import json
import sys
import threading
import time
import tracemalloc
from pathlib import Path
from typing import Any

import pytest
import zmq

import edumatcher.engine.main as _engine_main
from edumatcher.engine.metrics import (
    ENTRY_BYTES,
    GATEWAY_COUNTERS,
    LATENCY_RING,
    MAX_DYNAMIC_LABELS,
    ORDER_BYTES,
    SESSION_STATE_ORDER,
    UNKNOWN_LABEL,
    EngineMetrics,
    memory_estimate,
    percentile,
)
from edumatcher.engine.order_book import OrderBook
from edumatcher.health import HealthReporter
from edumatcher.models.generated.health import MetricSample, parse_health_beacon
from edumatcher.models.order import Order, OrderType, Side, TIF
from edumatcher.models.trade import reset_trade_ids_for_tests
from tests.conftest import free_port
from tests.engine_harness import connect, make_engine, msgs, order_payload
from tests.engine_invariants import (
    RejectTallyingSocket,
    assert_reject_count_matches,
)

#: The engine module, typed Any: the tests reach the topic constants, builders
#: and stdlib modules it imports, which it does not re-export.
em: Any = _engine_main

GWS = ("GW01", "GW02", "GW03")


def _value(samples: list[MetricSample], name: str, label: str = "") -> float:
    found = [s.value for s in samples if s.name == name and s.label == label]
    assert len(found) == 1, f"{name}{{{label}}}: {found}"
    return found[0]


def _labels(samples: list[MetricSample], name: str) -> set[str]:
    return {s.label for s in samples if s.name == name}


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    eng, _pub = make_engine(monkeypatch, tmp_path)
    return eng


def _submit(engine: Any, gw: str, side: Side, qty: int, price: float) -> None:
    engine._dispatch_pull_message(
        em.TOPIC_ORDER_NEW, order_payload(side, OrderType.LIMIT, qty, gw, price)
    )


class TestAFreshEngine:
    """A4.1: zeros are published, for every configured gateway."""

    def test_every_counter_is_zero_for_every_configured_gateway(
        self, engine: Any
    ) -> None:
        samples = engine.metric_samples()
        for name in GATEWAY_COUNTERS:
            assert _labels(samples, f"engine.{name}") == set(GWS)
            for gw in GWS:
                assert _value(samples, f"engine.{name}", gw) == 0
        assert _value(samples, "engine.msgs_in") == 0

    def test_diagnostics_are_published_even_when_zero(self, engine: Any) -> None:
        samples = engine.metric_samples()
        assert _labels(samples, "engine.diagnostics") == {
            "DISPATCH_ERROR",
            "UNROUTED_TOPIC",
            "UNDECODABLE_MESSAGE",
            "MAINTENANCE_FLUSH",
        }

    def test_every_sample_validates(self, engine: Any) -> None:
        """Anything failing here would be dropped by the sampler thread."""
        connect(engine)
        _submit(engine, "GW01", Side.BUY, 10, 100.0)
        for sample in engine.metric_samples():
            sample.validate()


class TestInboundCounters:
    """A4.2: counted at the top of each handler, rejected or not."""

    def test_orders_in_counts_rejected_submissions_too(self, engine: Any) -> None:
        connect(engine, "GW01")
        for _ in range(3):
            _submit(engine, "GW01", Side.BUY, 10, 100.0)
        # GW02 never connected: rejected, but it was submitted.
        _submit(engine, "GW02", Side.BUY, 10, 100.0)
        assert engine.metrics.orders_in == {"GW01": 3, "GW02": 1}
        assert engine.metrics.rejects == {"GW02": 1}

    @pytest.mark.parametrize(
        ("topic", "counter_name"),
        [
            ("TOPIC_ORDER_CANCEL", "cancels_in"),
            ("TOPIC_ORDER_AMEND", "amends_in"),
            ("TOPIC_QUOTE_NEW", "quotes_in"),
            ("TOPIC_ORDER_COMBO", "orders_in"),
            ("TOPIC_ORDER_OCO", "orders_in"),
        ],
    )
    def test_other_inbound_requests(
        self, engine: Any, topic: str, counter_name: str
    ) -> None:
        connect(engine, "GW01")
        engine._dispatch_pull_message(
            getattr(em, topic), {"gateway_id": "GW01", "order_id": "nope"}
        )
        assert getattr(engine.metrics, counter_name) == {"GW01": 1}


class TestLabelsAreBounded:
    """K4: a client cannot grow the engine's metric state by inventing ids."""

    def test_an_unconfigured_gateway_is_counted_as_unknown(self, engine: Any) -> None:
        for i in range(500):
            _submit(engine, f"EVIL{i:04d}", Side.BUY, 1, 100.0)
        assert engine.metrics.orders_in == {UNKNOWN_LABEL: 500}
        assert engine.metrics.rejects == {UNKNOWN_LABEL: 500}

    def test_lower_case_ids_count_under_the_configured_name(self, engine: Any) -> None:
        engine.metrics.count(engine.metrics.orders_in, "gw01")
        assert engine.metrics.orders_in == {"GW01": 1}

    @pytest.mark.parametrize("raw", [None, 42, ["GW01"], "", "G" * 33])
    def test_odd_ids_are_unknown(self, raw: object) -> None:
        m = EngineMetrics()
        m.set_known_gateways(frozenset({"GW01"}))
        assert m.label(raw) == UNKNOWN_LABEL

    def test_without_config_the_first_ids_are_kept_then_capped(self) -> None:
        m = EngineMetrics()
        for i in range(MAX_DYNAMIC_LABELS + 10):
            m.count(m.orders_in, f"GW{i:03d}")
        assert len(m.orders_in) == MAX_DYNAMIC_LABELS + 1
        assert m.orders_in[UNKNOWN_LABEL] == 10


class TestTheRejectFunnel:
    """A4.3 (F4): one counting point, and nothing may bypass it."""

    def test_rejects_are_counted_once_per_published_reject(self, engine: Any) -> None:
        connect(engine, "GW01")
        engine._dispatch_pull_message(  # unknown symbol
            em.TOPIC_ORDER_NEW,
            order_payload(Side.BUY, OrderType.LIMIT, 1, "GW01", 1.0, symbol="ZZZZ"),
        )
        engine._dispatch_pull_message(  # FOK with no liquidity
            em.TOPIC_ORDER_NEW,
            order_payload(Side.BUY, OrderType.FOK, 5, "GW01", 100.0),
        )
        assert engine.metrics.rejects["GW01"] >= 2
        assert_reject_count_matches(engine)

    def test_the_invariant_catches_a_bypass(self, engine: Any) -> None:
        """Guards the guard: a reject sent around the funnel is noticed."""
        assert isinstance(engine.pub_sock, RejectTallyingSocket)
        engine.pub_sock.send_multipart(
            em.make_ack_msg("GW01", "o1", False, "bypass")  # deliberately direct
        )
        with pytest.raises(AssertionError, match="bypasses"):
            assert_reject_count_matches(engine)
        engine.metrics.count(engine.metrics.rejects, "GW01")  # keep teardown green

    def test_the_engine_never_calls_an_ack_builder_directly(self) -> None:
        """Source check: the four builders appear only inside their wrapper."""
        builders = {
            "make_ack_msg": "_order_ack",
            "make_combo_ack_msg": "_combo_ack",
            "make_oco_ack_msg": "_oco_ack",
            "make_quote_ack_msg": "_quote_ack",
        }
        tree = ast.parse(Path(_engine_main.__file__).read_text(encoding="utf-8"))
        offenders: list[str] = []
        for func in ast.walk(tree):
            if not isinstance(func, ast.FunctionDef):
                continue
            for node in ast.walk(func):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in builders
                    and builders[node.func.id] != func.name
                ):
                    offenders.append(f"{func.name}:{node.lineno} {node.func.id}")
        assert not offenders, f"route these through the funnel: {offenders}"

    def test_admin_and_auth_rejects_are_not_order_rejects(self, engine: Any) -> None:
        engine._handle_gateway_connect({"gateway_id": "NOT_CONFIGURED"})
        engine._dispatch_pull_message(
            em.TOPIC_KILL_SWITCH, {"gateway_id": "GW01", "symbol": "AAPL"}
        )
        assert engine.metrics.rejects == {}
        assert engine.metrics.auth_rejects == {UNKNOWN_LABEL: 1}


class TestTradesAndFills:
    """A4.4"""

    def test_fills_per_side_and_trades_match_system_volume(self, engine: Any) -> None:
        pub = engine.pub_sock
        connect(engine, "GW01", "GW02")
        _submit(engine, "GW01", Side.SELL, 10, 100.0)
        _submit(engine, "GW01", Side.SELL, 10, 100.5)
        _submit(engine, "GW02", Side.BUY, 15, 101.0)  # two trades
        assert engine.metrics.fills == {"GW01": 2, "GW02": 2}

        engine._handle_volume_request({"gateway_id": "GW01"})
        volume = msgs(pub, "system.volume.GW01")[-1]
        row = next(r for r in volume["symbols"] if r["symbol"] == "AAPL")
        samples = engine.metric_samples()
        assert _value(samples, "engine.trades", "AAPL") == row["trades"] == 2
        assert _value(samples, "engine.traded_qty", "AAPL") == row["qty"] == 15
        assert _value(samples, "engine.traded_value", "AAPL") == pytest.approx(
            row["value"]
        )


class TestParticipants:
    """A4.5"""

    def test_connects_disconnects_and_the_connected_gauge(self, engine: Any) -> None:
        connect(engine, "GW01", "GW02")
        engine._handle_gateway_connect({"gateway_id": "GW01"})  # already connected
        engine._handle_gateway_disconnect({"gateway_id": "GW02", "reason": "bye"})
        m = engine.metrics
        assert m.connects == {"GW01": 1, "GW02": 1}
        assert m.auth_rejects == {"GW01": 1}
        assert m.disconnects == {"GW02": 1}

        samples = engine.metric_samples()
        engine._dispatch_pull_message(em.TOPIC_GATEWAYS_REQUEST, {"gateway_id": "GW01"})
        roster = msgs(engine.pub_sock, "system.gateways.GW01")[-1]["gateways"]
        assert _value(samples, "engine.participants_connected") == sum(
            g["connected"] for g in roster
        )
        assert _value(samples, "engine.participants_connected", "TRADER") == 1
        assert _value(samples, "engine.participant_connected", "GW01") == 1
        assert _value(samples, "engine.participant_connected", "GW02") == 0

    def test_a_heartbeat_timeout_counts_as_both(
        self, engine: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connect(engine, "GW01")
        engine._handle_gateway_heartbeat({"gateway_id": "GW01", "interval_sec": 1})
        later = time.monotonic() + 3600
        monkeypatch.setattr(em.time, "monotonic", lambda: later)
        engine._next_silence_check = 0.0
        engine._expire_silent_gateways()
        assert engine.metrics.heartbeat_timeouts == {"GW01": 1}
        assert engine.metrics.disconnects == {"GW01": 1}

    def test_resting_orders_per_gateway(self, engine: Any) -> None:
        connect(engine, "GW01", "GW02")
        _submit(engine, "GW01", Side.BUY, 10, 99.0)
        _submit(engine, "GW01", Side.BUY, 10, 98.0)
        _submit(engine, "GW02", Side.SELL, 10, 105.0)
        samples = engine.metric_samples()
        assert _value(samples, "engine.resting_orders", "GW01") == 2
        assert _value(samples, "engine.resting_orders", "GW02") == 1
        assert _value(samples, "engine.resting_orders", "GW03") == 0


class TestBooks:
    """A4.6"""

    def test_gauges_match_a_scripted_book(self, engine: Any) -> None:
        connect(engine, "GW01", "GW02")
        _submit(engine, "GW01", Side.BUY, 10, 99.0)
        _submit(engine, "GW01", Side.BUY, 10, 99.0)
        _submit(engine, "GW01", Side.BUY, 10, 98.0)
        _submit(engine, "GW02", Side.SELL, 10, 105.0)
        engine._dispatch_pull_message(
            em.TOPIC_ORDER_NEW,
            order_payload(Side.SELL, OrderType.STOP, 5, "GW02", stop_price=90.0),
        )
        samples = engine.metric_samples()
        assert _value(samples, "engine.books") == 1
        assert _value(samples, "engine.book_bid_levels", "AAPL") == 2
        assert _value(samples, "engine.book_ask_levels", "AAPL") == 1
        assert _value(samples, "engine.book_stop_orders", "AAPL") == 1
        assert _value(samples, "engine.book_resting_orders", "AAPL") == 5
        assert _value(samples, "engine.book_heap_garbage_pct", "AAPL") == 0
        assert _value(samples, "engine.book_est_bytes", "AAPL") > 5 * ORDER_BYTES
        assert _value(samples, "engine.book_halted", "AAPL") == 0

    def test_garbage_shows_after_cancels(self) -> None:
        book = OrderBook("AAPL")
        orders = [_limit(Side.BUY, 9900 - i) for i in range(10)]
        for order in orders:
            book.process(order, now=1)
        for order in orders[:4]:
            book.cancel_order(order.id)
        stats = book.book_stats()
        assert (stats.heap_entries, stats.live_entries) == (10, 6)
        assert stats.heap_garbage_pct == pytest.approx(40.0)

    def test_book_gauges_refresh_only_every_interval(self, engine: Any) -> None:
        connect(engine, "GW01")
        engine._book_metrics_interval_sec = 10.0
        _submit(engine, "GW01", Side.BUY, 10, 99.0)
        engine.metric_samples(now=100.0)
        _submit(engine, "GW01", Side.BUY, 10, 98.0)
        stale = engine.metric_samples(now=105.0)
        fresh = engine.metric_samples(now=110.0)
        assert _value(stale, "engine.book_resting_orders", "AAPL") == 1
        assert _value(fresh, "engine.book_resting_orders", "AAPL") == 2

    def test_the_memory_estimate_is_within_15_percent_of_tracemalloc(self) -> None:
        """Guard test (design §8.3). If this fails, ORDER_BYTES/ENTRY_BYTES/
        TRADE_BYTES in engine/metrics.py no longer describe the objects --
        re-measure them (build a book of resting orders under tracemalloc and
        divide) rather than widening the tolerance."""
        gc.collect()
        tracemalloc.start()
        try:
            before = tracemalloc.take_snapshot()
            book = OrderBook("AAPL")
            for i in range(10_000):
                side = Side.BUY if i % 2 == 0 else Side.SELL
                offset = 1 + i % 100
                price = 10_000 - offset if side is Side.BUY else 10_000 + offset
                book.process(_limit(side, price, gw=f"GW{i % 8:02d}"), now=1)
            gc.collect()
            after = tracemalloc.take_snapshot()
        finally:
            tracemalloc.stop()
        traced = sum(stat.size_diff for stat in after.compare_to(before, "filename"))
        estimate = memory_estimate(book)
        assert abs(estimate - traced) / traced < 0.15, (
            f"estimate {estimate} vs traced {traced}: re-measure ORDER_BYTES "
            f"({ORDER_BYTES}) and ENTRY_BYTES ({ENTRY_BYTES})"
        )


def _limit(side: Side, price: int, gw: str = "GW01") -> Order:
    return Order.create(
        symbol="AAPL",
        side=side,
        order_type=OrderType.LIMIT,
        quantity=10,
        gateway_id=gw,
        tif=TIF.DAY,
        price_ticks=price,
    )


class TestProcessingMetrics:
    """A4.7"""

    def test_percentiles_of_a_known_ring(self) -> None:
        m = EngineMetrics()
        for us in range(1, 101):
            m.record_dispatch(us * 1000)
        samples = m.timing_samples()
        assert _value(samples, "engine.handle_us_p50") == 50
        assert _value(samples, "engine.handle_us_p99") == 99
        assert _value(samples, "engine.handle_us_max") == 100
        assert m.msgs_in == 100

    def test_each_interval_starts_empty(self) -> None:
        m = EngineMetrics()
        m.record_dispatch(5_000_000)
        m.timing_samples()
        assert _value(m.timing_samples(), "engine.handle_us_max") == 0

    def test_only_the_last_ring_full_counts(self) -> None:
        m = EngineMetrics()
        for _ in range(LATENCY_RING):
            m.record_dispatch(9_000_000)
        for _ in range(LATENCY_RING):
            m.record_dispatch(1_000)
        assert _value(m.timing_samples(), "engine.handle_us_max") == 1

    @pytest.mark.parametrize(("busy", "pct"), [(0, 0.0), (25, 25.0), (250, 100.0)])
    def test_busy_pct_is_bounded(self, busy: int, pct: float) -> None:
        m = EngineMetrics()
        start = m._window_start_ns
        m.record_busy(busy)
        samples = m.timing_samples(now_ns=start + 100)
        assert _value(samples, "engine.busy_pct") == pytest.approx(pct)

    def test_percentile_edges(self) -> None:
        assert percentile([], 99) == 0.0
        assert percentile([7], 50) == 7.0
        assert percentile([1, 2, 3, 4], 50) == 2.0

    def test_session_state_is_an_index_into_the_published_order(
        self, engine: Any
    ) -> None:
        state = _value(engine.metric_samples(), "engine.session_state")
        assert SESSION_STATE_ORDER[int(state)] == engine._session_state


class _DueReporter:
    def __init__(self) -> None:
        self.published: list[list[MetricSample]] = []

    def due(self) -> bool:
        return True

    def publish(self, samples: list[MetricSample]) -> None:
        self.published.append(list(samples))


class TestFlushMetrics:
    """A4.8"""

    def test_due_reporter_receives_the_samples(self, engine: Any) -> None:
        reporter = _DueReporter()
        engine._reporter = reporter
        engine._flush_metrics()
        assert reporter.published and reporter.published[0]

    def test_no_reporter_is_a_no_op(self, engine: Any) -> None:
        engine._flush_metrics()  # must not raise

    def test_a_failure_becomes_a_diagnostic_and_the_other_flushes_run(
        self, engine: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine._reporter = _DueReporter()
        monkeypatch.setattr(
            engine, "metric_samples", lambda **_: (_ for _ in ()).throw(KeyError("x"))
        )
        ran: list[str] = []
        monkeypatch.setattr(
            engine, "_flush_circuit_breakers", lambda: ran.append("circuit_breakers")
        )
        engine._run_maintenance()
        diags = msgs(engine.pub_sock, "system.diagnostic")
        assert [d["detail"] for d in diags] == ["_flush_metrics"]
        assert diags[0]["component"] == "MAINTENANCE_FLUSH"
        assert ran == ["circuit_breakers"]


@pytest.mark.real_health_reporter
class TestTheRunLoopBeacons:
    """A4.9: the real run() loop ticks, and its beacon carries the metrics."""

    def test_an_idle_engine_beacons_a_fresh_loop(
        self, engine: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        port = free_port()
        sink: zmq.Socket[bytes] = zmq.Context.instance().socket(zmq.PULL)
        sink.setsockopt(zmq.LINGER, 0)
        sink.bind(f"tcp://127.0.0.1:{port}")

        class IdlePoller:
            def register(self, *_a: Any, **_k: Any) -> None:
                pass

            def poll(self, timeout: int | None = None) -> dict[Any, int]:
                time.sleep((timeout or 0) / 1000)
                return {}

        class IdlePull:
            """Plain class: run() keys a dict on the pull socket, and the
            harness FakeSock is an (unhashable) dataclass."""

            def close(self) -> None:
                pass

        engine.pull_sock = IdlePull()
        monkeypatch.setattr(em.zmq, "Poller", IdlePoller)
        monkeypatch.setattr(em, "DropCopyPublisher", lambda *a, **k: None)
        # run() sets the run sequence, which make_engine already did.
        reset_trade_ids_for_tests()
        monkeypatch.setattr(em, "load_and_bump_run_seq", lambda _: 1)
        monkeypatch.setattr(em.signal, "signal", lambda *_a: None)
        monkeypatch.setattr(engine, "_restore_gtc", lambda: None)
        monkeypatch.setattr(engine, "_load_config", lambda: None)

        reporter = HealthReporter(
            "pm-engine", host="127.0.0.1", port=port, interval_sec=0.2
        )
        engine.attach_reporter(reporter, book_metrics_interval_sec=0.2)
        reporter.start()
        runner = threading.Thread(target=engine.run, daemon=True)
        runner.start()
        try:
            beacon = None
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                assert sink.poll(3000), "no beacon from the engine"
                beacon = parse_health_beacon(sink.recv_multipart())
                if any(m.name == "engine.orders_in" for m in beacon.metrics):
                    break
            assert beacon is not None
            assert beacon.process == "pm-engine"
            assert beacon.loop_age_ms < 400  # 200 ms poll tick, idle
            assert {"GW01", "GW02", "GW03"} <= {
                m.label for m in beacon.metrics if m.name == "engine.orders_in"
            }
        finally:
            engine._running = False
            runner.join(timeout=5)
            sink.close()
        assert not runner.is_alive()
        assert reporter._thread is None  # _shutdown stopped it


def test_beacon_payload_is_not_absurd(engine: Any) -> None:
    """Size check for the dashboard budget (design §11.1): a 3-gateway,
    1-symbol engine beacon stays small."""
    connect(engine)
    _submit(engine, "GW01", Side.BUY, 10, 99.0)
    payload = json.dumps([s.to_dict() for s in engine.metric_samples()])
    assert len(payload) < 16_000, len(payload)
    assert sys.getsizeof(payload) > 0


def test_the_beacon_carries_every_metric_of_the_design(engine: Any) -> None:
    """Design §8.2-§8.4 (book metrics renamed engine.book_*, I24). The
    dashboard reads these names (D3.1); a rename must be deliberate."""
    connect(engine)
    _submit(engine, "GW01", Side.BUY, 10, 99.0)
    names = {s.name for s in engine.metric_samples()}
    assert names == {
        "engine.msgs_in",
        *(f"engine.{name}" for name in GATEWAY_COUNTERS),
        "engine.handle_us_p50",
        "engine.handle_us_p99",
        "engine.handle_us_max",
        "engine.busy_pct",
        "engine.participants_connected",
        "engine.participant_connected",
        "engine.resting_orders",
        "engine.trades",
        "engine.traded_qty",
        "engine.traded_value",
        "engine.diagnostics",
        "engine.books",
        "engine.session_state",
        "engine.halted_symbols",
        "engine.gtc_flush_ms",
        "engine.book_resting_orders",
        "engine.book_stop_orders",
        "engine.book_bid_levels",
        "engine.book_ask_levels",
        "engine.book_heap_entries",
        "engine.book_heap_garbage_pct",
        "engine.book_est_bytes",
        "engine.book_halted",
    }

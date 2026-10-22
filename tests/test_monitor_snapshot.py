"""The snapshot's trading, participant, book and gateway blocks (WP-B3.5)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from edumatcher.models.generated.health import HealthSnapshot
from edumatcher.monitor.activity import GATEWAYS
from edumatcher.monitor.collector import Monitor
from edumatcher.monitor.config import MonitorConfig
from edumatcher.monitor.thresholds import RAISE_AFTER
from tests.conftest import free_ports
from tests.test_monitor_main import QuietHost, _beacon_frames

STOCKHOLM = ZoneInfo("Europe/Stockholm")
#: Stands for "the traffic counter of beacon n" in GATEWAY_CASES.
TRAFFIC = -1.0
OPEN = datetime(2026, 10, 19, 9, 0, tzinfo=STOCKHOLM).timestamp()


class _Clocks:
    def __init__(self) -> None:
        self.mono = 1000.0
        self.wall = OPEN

    def advance(self, sec: float) -> None:
        self.mono += sec
        self.wall += sec


@pytest.fixture
def clocks() -> _Clocks:
    return _Clocks()


@pytest.fixture
def mon(clocks: _Clocks) -> Iterator[Monitor]:
    pull, pub = free_ports(2)
    m = Monitor(
        MonitorConfig(pull_port=pull, pub_port=pub),
        STOCKHOLM,
        clock=lambda: clocks.mono,
        wall_clock=lambda: clocks.wall,
        roles={"GW1": "TRADER", "MM01": "MARKET_MAKER"},
        host_sampler=QuietHost(),
        local_host="box",
    )
    try:
        yield m
    finally:
        m.close()


def _c(name: str, value: float, label: str = "") -> dict[str, Any]:
    return {"name": name, "kind": "COUNTER", "label": label, "value": value}


def _g(name: str, value: float, label: str = "") -> dict[str, Any]:
    return {"name": name, "kind": "GAUGE", "label": label, "value": value}


def _engine(
    seq: int, gw1_orders: float, mm_orders: float, *, final: bool = False, **extra: Any
) -> list[bytes]:
    metrics = [
        _c("engine.orders_in", gw1_orders, "GW1"),
        _c("engine.orders_in", mm_orders, "MM01"),
        _c("engine.rejects", extra.get("gw1_rejects", 0), "GW1"),
        _c("engine.fills", extra.get("gw1_fills", 0), "GW1"),
        _c("engine.trades", extra.get("trades", 0), "AAA"),
        _c("engine.traded_value", extra.get("value", 0.0), "AAA"),
        _c("engine.connects", 1, "GW1"),
        _g("engine.participant_connected", 1, "GW1"),
        _g("engine.participant_connected", extra.get("mm_connected", 0), "MM01"),
        _g("engine.resting_orders", 4, "GW1"),
        _g("engine.handle_us_p50", 12.0),
        _g("engine.handle_us_p99", 80.0),
        _g("engine.busy_pct", 3.5),
        _g("engine.session_state", 2),  # CONTINUOUS
        _g("engine.book_resting_orders", 9, "AAA"),
        _g("engine.book_bid_levels", 3, "AAA"),
        _g("engine.book_ask_levels", 2, "AAA"),
        _g("engine.book_heap_garbage_pct", 10.0, "AAA"),
        _g("engine.book_est_bytes", 4096, "AAA"),
        _g("engine.book_halted", 0, "AAA"),
    ]
    started = int((OPEN - 3600) * 1e9)  # started this morning
    return _beacon_frames(seq=seq, metrics=metrics, started_at_ns=started, final=final)


def _snapshot(mon: Monitor) -> HealthSnapshot:
    snap = HealthSnapshot.from_dict(mon.snapshot())
    snap.validate()
    return snap


def test_a_scripted_engine_stream(mon: Monitor, clocks: _Clocks) -> None:
    # 30 beacons, 2 s apart: GW1 +4 orders and MM01 +2 orders per beacon
    for i in range(30):
        mon.receive(
            _engine(
                i,
                gw1_orders=4 * i,
                mm_orders=2 * i,
                gw1_rejects=i // 2,
                gw1_fills=i,
                trades=i,
                value=100.0 * i,
                mm_connected=1 if i >= 10 else 0,
            ),
            clocks.mono,
        )
        clocks.advance(2.0)
    snap = _snapshot(mon)

    t = snap.trading
    assert t.orders.today == 6 * 29  # the first value is from this process's start
    # the last 60 s held 30 beacons x 6 orders, minus the first (a baseline
    # value, not windowed) -- and one of them just aged out
    assert t.orders.per_sec_now == pytest.approx(6 * 29 / 60.0, rel=0.05)
    assert t.orders.avg_per_min == pytest.approx(6 * 29 / 60.0)
    assert t.trades.today == 29
    assert t.traded_value_today == pytest.approx(2900.0)
    assert t.reject_pct_5m == pytest.approx(100.0 * 14 / (6 * 29))
    assert (t.handle_p50_us, t.handle_p99_us, t.busy_pct) == (12.0, 80.0, 3.5)
    assert snap.exchange.session_state == "CONTINUOUS"
    assert snap.exchange.trading_date == "2026-10-19"

    gw1, mm = snap.participants
    assert (gw1.id, gw1.role, gw1.connected, gw1.connected_since) == (
        "GW1",
        "TRADER",
        True,
        None,  # connected before pm-monitor saw it
    )
    assert gw1.orders.today == 4 * 29
    assert gw1.reject_pct == pytest.approx(100.0 * 14 / (4 * 29))
    assert (gw1.fills_today, gw1.resting_orders, gw1.connects_today) == (29, 4, 1)
    assert (mm.id, mm.role, mm.connected) == ("MM01", "MARKET_MAKER", True)
    assert mm.connected_since is not None  # seen going 0 -> 1
    assert mm.orders.today == 2 * 29

    (book,) = snap.books
    assert (book.symbol, book.resting_orders, book.bid_levels, book.ask_levels) == (
        "AAA",
        9,
        3,
        2,
    )
    assert (book.est_bytes, book.trades_today, book.halted) == (4096, 29, False)


def test_a_configured_participant_with_no_activity_is_listed(mon: Monitor) -> None:
    snap = _snapshot(mon)
    assert [(p.id, p.role, p.connected) for p in snap.participants] == [
        ("GW1", "TRADER", False),
        ("MM01", "MARKET_MAKER", False),
    ]


GATEWAY_CASES = [
    (
        "pm-alf-gwy",
        [_g("gwy.connected_clients", 3), _g("gwy.clients_max", 50),
         _c("gwy.commands_received_total", TRAFFIC), _c("gwy.disconnects_total", 2),
         _c("gwy.slow_client_disconnects", 1)],
        ("ALF", 3, 50, 2, 1),
    ),
    (
        "pm-balf-gwy",
        [_g("gwy.connected_clients", 1), _g("gwy.clients_max", 10),
         _c("gwy.frames_received_total", TRAFFIC), _c("gwy.disconnects_total", 0),
         _c("gwy.slow_client_disconnects", 0)],
        ("BALF", 1, 10, 0, 0),
    ),
    (
        "pm-md-gwy",
        [_g("md.clients", 5), _g("md.clients_max", 100), _c("md.msgs_out", TRAFFIC),
         _c("md.disconnects", 3, "peer_closed"), _c("md.disconnects", 2, "slow_client")],
        ("MD", 5, 100, 5, 2),
    ),
    (
        "pm-ralf-gwy",
        [_g("gwy.clients", 2), _c("gwy.msgs_out", TRAFFIC),
         _c("gwy.disconnects", 1, "idle_timeout"), _c("gwy.slow_clients", 1)],
        ("RALF", 2, None, 1, 1),
    ),
    (
        "pm-dc-gwy",
        [_g("gwy.clients", 2), _c("gwy.msgs_out", TRAFFIC), _c("gwy.slow_clients", 0)],
        ("DC", 2, None, 0, 0),
    ),
    (
        "pm-api-gwy",
        [_g("api.ws_sessions", 2, "events"), _g("api.ws_sessions", 1, "admin/monitor"),
         _c("api.http_requests", TRAFFIC)],
        ("API", 3, None, 0, 0),
    ),
    (
        "pm-log-srv",
        [_g("log.sessions", 12), _c("log.events_in", TRAFFIC)],
        ("LOG", 12, None, 0, 0),
    ),
]  # fmt: skip


def test_every_gateway_kind_is_mapped() -> None:
    assert {case[0] for case in GATEWAY_CASES} == set(GATEWAYS)


@pytest.mark.parametrize(
    ("process", "metrics", "expected"),
    [case for case in GATEWAY_CASES],
    ids=[case[0] for case in GATEWAY_CASES],
)
def test_gateway_stats_by_process_name(
    mon: Monitor,
    clocks: _Clocks,
    process: str,
    metrics: list[dict[str, Any]],
    expected: tuple[Any, ...],
) -> None:
    started = int((OPEN - 3600) * 1e9)
    for i in range(11):  # traffic +10 per 2 s beacon: 5 msgs/s
        sent = [{**m, "value": 10 * i} if m["value"] == TRAFFIC else m for m in metrics]
        mon.receive(
            _beacon_frames(process=process, seq=i, metrics=sent, started_at_ns=started),
            clocks.mono,
        )
        clocks.advance(2.0)
    (gw,) = _snapshot(mon).gateways
    kind, clients, clients_max, disconnects, slow = expected
    assert gw.key == f"{process}@box"
    assert (gw.kind, gw.clients, gw.clients_max) == (kind, clients, clients_max)
    assert gw.msgs_per_sec == pytest.approx(100 / 60.0)
    assert (gw.disconnects_today, gw.slow_disconnects_today) == (disconnects, slow)


def test_a_slow_client_disconnect_is_a_threshold(mon: Monitor, clocks: _Clocks) -> None:
    started = int((OPEN - 3600) * 1e9)
    for i, slow in enumerate([0, 0, 1]):
        mon.receive(
            _beacon_frames(
                process="pm-md-gwy",
                seq=i,
                metrics=[_c("md.disconnects", slow, "slow_client")],
                started_at_ns=started,
            ),
            clocks.mono,
        )
        clocks.advance(2.0)
    snap = _snapshot(mon)
    assert [(b.rule, b.subject, b.level) for b in snap.thresholds] == [
        ("slow_client_disconnects", "pm-md-gwy@box", "WARN")
    ]
    assert [p.state for p in snap.processes] == ["DEGRADED"]


def test_history_that_cannot_be_written_makes_pm_monitor_degraded(
    clocks: _Clocks,
) -> None:
    """metrics.db wanted but not open: every store tick is lost history,
    counted in pm-monitor's own beacon, and the metrics_store_errors rule
    shows it on the dashboard as pm-monitor DEGRADED (I123)."""
    pull, pub = free_ports(2)
    mon = Monitor(
        MonitorConfig(pull_port=pull, pub_port=pub),
        STOCKHOLM,
        clock=lambda: clocks.mono,
        wall_clock=lambda: clocks.wall,
        host_sampler=QuietHost(),
        local_host="box",
        history_unavailable=True,
    )
    try:
        started = int((OPEN - 3600) * 1e9)
        for i in range(3):
            mon.store_tick()
            mon.receive(
                _beacon_frames(
                    process="pm-monitor",
                    seq=i,
                    metrics=[_c("monitor.store_errors", mon.store_errors)],
                    started_at_ns=started,
                ),
                clocks.mono,
            )
            clocks.advance(2.0)
        snap = _snapshot(mon)
        assert [(b.rule, b.subject, b.level) for b in snap.thresholds] == [
            ("metrics_store_errors", "pm-monitor@box", "WARN")
        ]
        assert [p.state for p in snap.processes] == ["DEGRADED"]
    finally:
        mon.close()


def test_todays_rejects_by_reason_most_first(mon: Monitor, clocks: _Clocks) -> None:
    """engine.rejects_by_code becomes trading.rejects_by_code: what makes the
    reject ratio actionable (I123)."""
    started = int((OPEN - 3600) * 1e9)
    for i, (spread, closed) in enumerate([(0, 0), (4, 1), (9, 1)]):
        mon.receive(
            _beacon_frames(
                process="pm-engine",
                seq=i,
                metrics=[
                    _c("engine.rejects_by_code", spread, "MM_MAX_SPREAD"),
                    _c("engine.rejects_by_code", closed, "MARKET_CLOSED"),
                ],
                started_at_ns=started,
            ),
            clocks.mono,
        )
        clocks.advance(2.0)
    reasons = [(r.code, r.count) for r in _snapshot(mon).trading.rejects_by_code]
    assert reasons == [("MM_MAX_SPREAD", 9), ("MARKET_CLOSED", 1)]


def _mm_stream(mon: Monitor, clocks: _Clocks, beacons: int, per_beacon: int) -> None:
    """A market maker whose quotes are refused half the time, no orders."""
    started = int((OPEN - 3600) * 1e9)
    for i in range(beacons):
        n = per_beacon * i
        mon.receive(
            _beacon_frames(
                seq=i,
                started_at_ns=started,
                metrics=[
                    _c("engine.quotes_in", n, "MM01"),
                    _c("engine.rejects", n // 2, "MM01"),
                    _c("engine.orders_in", 0, "MM01"),
                ],
            ),
            clocks.mono,
        )
        clocks.advance(2.0)


def test_quote_rejects_are_a_share_of_all_requests(
    mon: Monitor, clocks: _Clocks
) -> None:
    """Rejects count quotes, cancels and amends too, so the ratio does: a
    market maker's refused refreshes once read as 300 % of zero orders."""
    _mm_stream(mon, clocks, beacons=11, per_beacon=10)
    snap = _snapshot(mon)
    assert snap.trading.orders.today == 0
    assert snap.trading.reject_pct_5m == pytest.approx(50.0)
    (mm,) = [p for p in snap.participants if p.id == "MM01"]
    assert mm.reject_pct == pytest.approx(50.0)
    assert [(b.rule, b.level) for b in snap.thresholds] == [("reject_pct_5m", "CRIT")]


def test_a_reject_ratio_on_a_handful_of_requests_is_not_judged(
    mon: Monitor, clocks: _Clocks
) -> None:
    _mm_stream(mon, clocks, beacons=4, per_beacon=4)  # 12 requests in 5 min
    snap = _snapshot(mon)
    assert snap.trading.reject_pct_5m == pytest.approx(50.0)
    assert snap.thresholds == []


@pytest.mark.parametrize(("entries", "breached"), [(3, False), (100, True)])
def test_heap_garbage_needs_a_real_heap(
    mon: Monitor, clocks: _Clocks, entries: int, breached: bool
) -> None:
    mon.receive(
        _beacon_frames(
            metrics=[
                _g("engine.book_heap_entries", entries, "AAA"),
                _g("engine.book_heap_garbage_pct", 66.0, "AAA"),
            ]
        ),
        clocks.mono,
    )
    snaps = [_snapshot(mon) for _ in range(RAISE_AFTER)]
    snap = snaps[-1]
    rules = [(b.rule, b.subject) for b in snap.thresholds]
    assert rules == ([("heap_garbage_pct", "AAA")] if breached else [])


def test_a_stopped_engine_has_no_connections_or_latency(
    mon: Monitor, clocks: _Clocks
) -> None:
    """Review R2: the last beacon of a gone engine is history, not now."""
    mon.receive(_engine(0, 0, 0, mm_connected=1), clocks.mono)
    clocks.advance(2.0)
    mon.receive(_engine(1, 4, 2, mm_connected=1), clocks.mono)
    live = _snapshot(mon)
    assert live.trading.handle_p99_us == 80.0
    assert all(p.connected for p in live.participants)

    mon.receive(_engine(2, 4, 2, mm_connected=1, final=True), clocks.mono)
    stopped = _snapshot(mon)
    assert [p.state for p in stopped.processes] == ["STOPPED"]
    assert stopped.exchange.status == "DOWN"
    assert (stopped.trading.handle_p99_us, stopped.trading.busy_pct) == (0.0, 0.0)
    assert not any(p.connected for p in stopped.participants)
    assert all(p.connected_since is None for p in stopped.participants)
    assert stopped.trading.orders.today == 6  # the day's counts stay


def test_a_stopped_gateway_has_no_clients(mon: Monitor, clocks: _Clocks) -> None:
    started = int((OPEN - 3600) * 1e9)
    metrics = [_g("md.clients", 5), _c("md.msgs_out", 0)]
    mon.receive(
        _beacon_frames(process="pm-md-gwy", metrics=metrics, started_at_ns=started),
        clocks.mono,
    )
    assert _snapshot(mon).gateways[0].clients == 5
    mon.receive(
        _beacon_frames(
            process="pm-md-gwy",
            seq=1,
            final=True,
            metrics=metrics,
            started_at_ns=started,
        ),
        clocks.mono,
    )
    assert _snapshot(mon).gateways[0].clients == 0

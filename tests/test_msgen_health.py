"""Operator dashboard WP-A1: the ``health`` family.

Three messages: ``health.beacon`` (every long-running process to pm-monitor),
``health.snapshot`` and ``health.event`` (pm-monitor to the dashboard
bridge). The snapshot is the deepest record tree in the spec — a snapshot
holds processes, a process holds its metric samples and a sparkline — so the
tests below check that validation reaches the leaves, not only the top.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from edumatcher.models import message as M
from edumatcher.models.generated import health as G
from edumatcher.models.generated import registry
from edumatcher.models.generated._runtime import MessageValidationError


def _sample(**overrides: Any) -> dict[str, Any]:
    sample: dict[str, Any] = {
        "name": "engine.orders_in",
        "kind": "COUNTER",
        "label": "GW01",
        "value": 42.0,
    }
    sample.update(overrides)
    return sample


def _beacon(**overrides: Any) -> dict[str, Any]:
    beacon: dict[str, Any] = {
        "process": "pm-api-gwy",
        "instance": "desk",
        "pid": 4242,
        "host": "exchange-host",
        "boot_id": "0123456789abcdef",
        "seq": 7,
        "started_at_ns": 1_760_000_000_000_000_000,
        "interval_sec": 2.0,
        "rss_bytes": 118_000_000,
        "cpu_pct": 6.5,
        "threads": 9,
        "fds": 31,
        "loop_age_ms": 12.0,
        "loop_lag_ms": 41.0,
        "final": False,
        "metrics": [_sample(), _sample(name="api.ws_sessions", kind="GAUGE")],
    }
    beacon.update(overrides)
    return beacon


def _rates(avg_per_day: float | None = 1_210_000.0) -> dict[str, Any]:
    return {
        "today": 184_302,
        "per_sec_now": 212.4,
        "avg_per_min": 3071.0,
        "avg_per_hour": 184_260.0,
        "avg_per_day": avg_per_day,
    }


def _process(**overrides: Any) -> dict[str, Any]:
    process: dict[str, Any] = {
        "key": "pm-api-gwy/desk@exchange-host",
        "process": "pm-api-gwy",
        "instance": "desk",
        "host": "exchange-host",
        "group": "EXCHANGE",
        "pid": 4242,
        "state": "HEALTHY",
        "restarted_recently": False,
        "uptime_sec": 18_720.0,
        "rss_bytes": 118_000_000,
        "cpu_pct": 6.0,
        "threads": 9,
        "fds": None,
        "loop_age_ms": 0.0,
        "loop_lag_ms": 12.0,
        "last_beacon_age_ms": 800.0,
        "spark": {"rss": [117_000_000, 118_000_000], "cpu": [5.5, 6.0]},
        "metrics": [_sample()],
    }
    process.update(overrides)
    return process


def _snapshot(**overrides: Any) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "ts": "2026-10-11T11:42:05.123Z",
        "seq": 3600,
        "exchange": {
            "status": "OPERATIONAL",
            "session_state": "CONTINUOUS",
            "trading_date": "2026-10-11",
            "session_timezone": "Europe/Stockholm",
        },
        "host": {
            "cpu_pct": 62.0,
            "cpu_per_core": [60.0, 64.0],
            "load1": 1.5,
            "load5": 1.2,
            "load15": 0.9,
            "mem_total_bytes": 16 << 30,
            "mem_used_bytes": 11 << 30,
            "mem_available_bytes": 5 << 30,
            "swap_used_bytes": 0,
            "disk_free_bytes": 300 << 30,
            "disk_total_bytes": 500 << 30,
            "files": [{"name": "log.db", "size_bytes": 1 << 30}],
        },
        "processes": [
            _process(),
            _process(
                key="pm-index@",
                process="pm-index",
                instance=None,
                host="",
                pid=0,
                state="MISSING",
                spark={"rss": [], "cpu": []},
                metrics=[],
            ),
        ],
        "trading": {
            "orders": _rates(),
            "trades": _rates(avg_per_day=None),
            "traded_value_today": 9_876_543.21,
            "reject_pct_5m": 0.4,
            "handle_p50_us": 80.0,
            "handle_p99_us": 640.0,
            "busy_pct": 12.5,
        },
        "participants": [
            {
                "id": "MM-01",
                "role": "MARKET_MAKER",
                "connected": True,
                "connected_since": "2026-10-11T06:58:00.000Z",
                "orders": _rates(avg_per_day=None),
                "reject_pct": 0.3,
                "fills_today": 900,
                "resting_orders": 40,
                "connects_today": 1,
                "disconnects_today": 0,
                "heartbeat_timeouts_today": 0,
            }
        ],
        "books": [
            {
                "symbol": "AAA",
                "resting_orders": 1204,
                "stop_orders": 12,
                "bid_levels": 84,
                "ask_levels": 91,
                "est_bytes": 4_100_000,
                "heap_garbage_pct": 12.0,
                "trades_today": 8102,
                "halted": False,
            }
        ],
        "gateways": [
            {
                "key": "pm-md-gwy@exchange-host",
                "kind": "MD",
                "clients": 31,
                "clients_max": 256,
                "msgs_per_sec": 950.0,
                "disconnects_today": 3,
                "slow_disconnects_today": 0,
            }
        ],
        "thresholds": [
            {
                "rule": "engine_handle_p99_us",
                "subject": "pm-engine@exchange-host",
                "level": "WARN",
                "value": 2345.0,
                "threshold": 2000.0,
                "since": "2026-10-11T11:40:00.000Z",
            }
        ],
    }
    snapshot.update(overrides)
    return snapshot


def _event(**overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "seq": 12,
        "ts": "2026-10-11T11:42:05.000Z",
        "kind": "DISCONNECT",
        "severity": "WARN",
        "subject": "TR-07",
        "detail": "heartbeat_timeout",
    }
    event.update(overrides)
    return event


class TestEachMessageRoundTrips:
    """make_* -> decode -> parse_* returns the payload unchanged."""

    def test_beacon(self) -> None:
        frames = G.make_health_beacon(**_beacon())
        topic, payload = M.decode(frames)
        assert topic == G.TOPIC_HEALTH_BEACON == "health.beacon"
        assert payload == _beacon()
        assert G.parse_health_beacon(frames).to_dict() == _beacon()

    def test_snapshot(self) -> None:
        frames = G.make_health_snapshot(**_snapshot())
        topic, payload = M.decode(frames)
        assert topic == G.TOPIC_HEALTH_SNAPSHOT == "health.snapshot"
        assert payload == _snapshot()
        assert G.parse_health_snapshot(frames).to_dict() == _snapshot()

    def test_event(self) -> None:
        frames = G.make_health_event(**_event())
        topic, payload = M.decode(frames)
        assert topic == G.TOPIC_HEALTH_EVENT == "health.event"
        assert payload == _event()
        assert G.parse_health_event(frames).to_dict() == _event()

    def test_frames_are_topic_and_json_only(self) -> None:
        """No sequence frame: the PUSH path is not a SequencedPublisher."""
        assert len(G.make_health_beacon(**_beacon())) == 2


class TestTheBeaconPresenceRules:
    def test_zero_metrics_is_valid(self) -> None:
        """A process with no application metrics still beacons its vitals."""
        beacon = G.parse_health_beacon(G.make_health_beacon(**_beacon(metrics=[])))
        assert beacon.metrics == []

    def test_no_instance_and_no_fds_are_omitted_not_null(self) -> None:
        kw = _beacon()
        del kw["instance"], kw["fds"]
        _topic, payload = M.decode(G.make_health_beacon(**kw))
        assert "instance" not in payload
        assert "fds" not in payload

    def test_final_defaults_to_false(self) -> None:
        kw = _beacon()
        del kw["final"]
        assert G.parse_health_beacon(G.make_health_beacon(**kw)).final is False

    def test_a_label_defaults_to_empty(self) -> None:
        sample = _sample()
        del sample["label"]
        beacon = G.parse_health_beacon(
            G.make_health_beacon(**_beacon(metrics=[sample]))
        )
        assert beacon.metrics[0].label == ""

    def test_a_long_fqdn_host_fits(self) -> None:
        """The host bound is LogRow's 128, not 64: a beacon that fails validation
        in the sampler thread would silence the process for good."""
        host = "node-" + "x" * 100 + ".example.internal"
        assert len(host) > 64
        G.make_health_beacon(**_beacon(host=host))


class TestValidationRejects:
    @pytest.mark.parametrize(
        ("field", "value", "match"),
        [
            ("process", "p" * 33, "process"),
            ("process", "", "process"),
            ("seq", -1, "seq"),
            ("pid", 0, "pid"),
            ("interval_sec", 0.0, "interval_sec"),
            ("boot_id", "0123456789abcdef0", "boot_id"),
            ("loop_age_ms", -1.0, "loop_age_ms"),
        ],
    )
    def test_a_bad_beacon_field(self, field: str, value: Any, match: str) -> None:
        with pytest.raises(MessageValidationError, match=match):
            G.make_health_beacon(**_beacon(**{field: value}))

    def test_a_kind_outside_the_enum(self) -> None:
        with pytest.raises(MessageValidationError, match="kind"):
            G.make_health_beacon(**_beacon(metrics=[_sample(kind="HISTOGRAM")]))

    def test_an_over_long_label(self) -> None:
        with pytest.raises(MessageValidationError, match="label"):
            G.make_health_beacon(**_beacon(metrics=[_sample(label="L" * 33)]))

    def test_an_empty_metric_name(self) -> None:
        with pytest.raises(MessageValidationError, match="name"):
            G.make_health_beacon(**_beacon(metrics=[_sample(name="")]))

    def test_validation_reaches_a_sample_three_levels_down(self) -> None:
        """snapshot -> processes[] -> metrics[] -> kind."""
        snapshot = _snapshot()
        snapshot["processes"][0]["metrics"] = [_sample(kind="BOGUS")]
        with pytest.raises(MessageValidationError, match="kind"):
            G.make_health_snapshot(**snapshot)

    def test_a_sparkline_is_bounded(self) -> None:
        snapshot = _snapshot()
        snapshot["processes"][0]["spark"]["cpu"] = [1.0] * 61
        with pytest.raises(MessageValidationError, match="cpu"):
            G.make_health_snapshot(**snapshot)

    @pytest.mark.parametrize(
        ("path", "value"),
        [
            (("processes", 0, "state"), "UNKNOWN"),
            (("processes", 0, "group"), "CLIENT"),
            (("exchange", "status"), "FINE"),
            (("thresholds", 0, "level"), "INFO"),
            (("gateways", 0, "kind"), "CALF"),
            (("books", 0, "heap_garbage_pct"), 100.5),
        ],
    )
    def test_a_bad_snapshot_leaf(self, path: tuple[Any, ...], value: Any) -> None:
        snapshot = copy.deepcopy(_snapshot())
        node: Any = snapshot
        for step in path[:-1]:
            node = node[step]
        node[path[-1]] = value
        with pytest.raises(MessageValidationError, match=str(path[-1])):
            G.make_health_snapshot(**snapshot)

    def test_an_event_kind_outside_the_enum(self) -> None:
        with pytest.raises(MessageValidationError, match="kind"):
            G.make_health_event(**_event(kind="ALERT"))


class TestTheSnapshotShape:
    def test_avg_per_day_is_null_before_the_first_full_day(self) -> None:
        """The dashboard shows "—" for null, so null must survive the wire."""
        _topic, payload = M.decode(G.make_health_snapshot(**_snapshot()))
        assert payload["trading"]["trades"]["avg_per_day"] is None

    def test_a_missing_process_has_null_instance_not_absent(self) -> None:
        """ProcessHealth.instance is always emitted, so a TS reader sees
        ``string | null`` and never ``undefined``."""
        _topic, payload = M.decode(G.make_health_snapshot(**_snapshot()))
        missing = payload["processes"][1]
        assert "instance" in missing and missing["instance"] is None

    def test_files_is_a_list_of_records_not_a_map(self) -> None:
        snapshot = G.parse_health_snapshot(G.make_health_snapshot(**_snapshot()))
        assert snapshot.host.files[0].name == "log.db"

    def test_empty_lists_are_valid(self) -> None:
        """A fresh pm-monitor with nothing seen yet still publishes."""
        G.make_health_snapshot(
            **_snapshot(
                processes=[], participants=[], books=[], gateways=[], thresholds=[]
            )
        )


class TestTheRegistry:
    @pytest.mark.parametrize(
        ("topic", "transport"),
        [
            ("health.beacon", ("monitor_push",)),
            ("health.snapshot", ("monitor_pub",)),
            ("health.event", ("monitor_pub",)),
        ],
    )
    def test_each_topic_is_registered(
        self, topic: str, transport: tuple[str, ...]
    ) -> None:
        entry = registry.TOPIC_REGISTRY[topic]
        assert entry["family"] == "health"
        assert entry["transport"] == transport

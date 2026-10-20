"""Operator dashboard WP-A3: the ``monitor:`` section loader.

The loader checks shape and ranges; cross-field rules live in the verifier
(``test_cverifier.py``, M029/M030) and port collisions in M018.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest
import yaml

from edumatcher import config as C
from edumatcher.monitor.config import (
    THRESHOLD_RULES,
    MonitorConfig,
    MonitorRetention,
    MonitorThresholds,
    ThresholdBand,
    load_default_monitor_config,
    load_monitor_config,
    monitor_config_from_raw,
    validate_monitor_section,
)


def _load(block: Any) -> MonitorConfig:
    return monitor_config_from_raw({"monitor": block})


class TestDefaults:
    def test_an_absent_block_is_all_defaults_and_enabled(self) -> None:
        cfg = monitor_config_from_raw({"symbols": {}})
        assert cfg == MonitorConfig()
        assert cfg.enabled is True

    def test_an_empty_block_is_all_defaults(self) -> None:
        assert _load(None) == MonitorConfig()
        assert _load({}) == MonitorConfig()

    def test_the_defaults_are_the_design_values(self) -> None:
        cfg = MonitorConfig()
        assert (cfg.pull_port, cfg.pub_port) == (5610, 5611)
        assert cfg.bind_address == "127.0.0.1"
        assert cfg.beacon_interval_sec == 2.0
        assert cfg.hung_after_sec == 5.0
        assert cfg.silent_after_beacons == 3
        assert cfg.book_metrics_interval_sec == 10.0
        assert cfg.retention == MonitorRetention(raw_hours=6, minute_days=7)
        assert cfg.thresholds.disk_free_pct == ThresholdBand(15.0, 5.0)
        assert cfg.thresholds.engine_handle_p99_us == ThresholdBand(2000.0, 10000.0)

    def test_the_defaults_equal_the_config_module_constants(self) -> None:
        """A3.7: one place decides the default endpoint."""
        cfg = MonitorConfig()
        assert cfg.host == C.MONITOR_HOST
        assert cfg.pull_port == C.MONITOR_PULL_PORT
        assert cfg.pub_port == C.MONITOR_PUB_PORT

    def test_connect_addresses(self) -> None:
        cfg = _load({"host": "mon.internal", "pull_port": 7000, "pub_port": 7001})
        assert cfg.pull_connect_addr == "tcp://mon.internal:7000"
        assert cfg.pub_connect_addr == "tcp://mon.internal:7001"

    def test_every_threshold_rule_is_a_band(self) -> None:
        thresholds = MonitorThresholds()
        assert THRESHOLD_RULES == tuple(
            f.name for f in dataclasses.fields(MonitorThresholds)
        )
        for rule in THRESHOLD_RULES:
            assert isinstance(getattr(thresholds, rule), ThresholdBand)


class TestOverrides:
    def test_a_full_block(self) -> None:
        cfg = _load(
            {
                "enabled": False,
                "bind_address": "0.0.0.0",
                "host": "10.0.0.5",
                "pull_port": 6610,
                "pub_port": 6611,
                "beacon_interval_sec": 1,
                "hung_after_sec": 4.5,
                "silent_after_beacons": 5,
                "book_metrics_interval_sec": 30,
                "retention": {"raw_hours": 12, "minute_days": 3},
                "thresholds": {"host_cpu_pct": {"warn": 70, "crit": 90}},
            }
        )
        assert cfg.enabled is False
        assert cfg.bind_address == "0.0.0.0"
        assert cfg.host == "10.0.0.5"
        assert (cfg.pull_port, cfg.pub_port) == (6610, 6611)
        assert cfg.beacon_interval_sec == 1.0
        assert isinstance(cfg.beacon_interval_sec, float)
        assert cfg.hung_after_sec == 4.5
        assert cfg.silent_after_beacons == 5
        assert cfg.book_metrics_interval_sec == 30.0
        assert cfg.retention == MonitorRetention(raw_hours=12, minute_days=3)
        assert cfg.thresholds.host_cpu_pct == ThresholdBand(70.0, 90.0)

    def test_an_omitted_threshold_rule_keeps_its_default(self) -> None:
        cfg = _load({"thresholds": {"host_cpu_pct": {"warn": 70, "crit": 90}}})
        assert cfg.thresholds.host_mem_pct == MonitorThresholds().host_mem_pct

    def test_bind_address_is_stored_as_authored(self, monkeypatch: Any) -> None:
        """The env override is applied by pm-monitor when it binds, so an
        artifact compiled outside the container does not bake in the wrong
        host."""
        monkeypatch.setattr(C, "EDUMATCHER_GATEWAY_BIND_HOST", "0.0.0.0")
        assert _load({}).bind_address == "127.0.0.1"


class TestInvalidValuesNameTheirPath:
    @pytest.mark.parametrize(
        ("block", "path"),
        [
            ("not-a-mapping", "monitor"),
            ({"enabled": "false"}, "monitor.enabled"),
            ({"enabled": 0}, "monitor.enabled"),
            ({"bind_address": ""}, "monitor.bind_address"),
            ({"host": 5}, "monitor.host"),
            ({"pull_port": 0}, "monitor.pull_port"),
            ({"pub_port": 70000}, "monitor.pub_port"),
            ({"pub_port": True}, "monitor.pub_port"),
            ({"pull_port": "5610"}, "monitor.pull_port"),
            ({"beacon_interval_sec": 0}, "monitor.beacon_interval_sec"),
            ({"hung_after_sec": -1}, "monitor.hung_after_sec"),
            ({"silent_after_beacons": 0}, "monitor.silent_after_beacons"),
            ({"silent_after_beacons": 2.5}, "monitor.silent_after_beacons"),
            ({"book_metrics_interval_sec": "x"}, "monitor.book_metrics_interval_sec"),
            ({"retention": []}, "monitor.retention"),
            ({"retention": {"raw_hours": 0}}, "monitor.retention.raw_hours"),
            ({"retention": {"minute_days": 1.5}}, "monitor.retention.minute_days"),
            ({"thresholds": 5}, "monitor.thresholds"),
            ({"thresholds": {"host_cpu_pct": 80}}, "monitor.thresholds.host_cpu_pct"),
            (
                {"thresholds": {"host_cpu_pct": {"warn": 80}}},
                "monitor.thresholds.host_cpu_pct.crit",
            ),
            (
                {"thresholds": {"reject_pct_5m": {"warn": -1, "crit": 30}}},
                "monitor.thresholds.reject_pct_5m.warn",
            ),
        ],
    )
    def test_it_raises_with_the_field_path(self, block: Any, path: str) -> None:
        with pytest.raises(ValueError, match=path.replace(".", r"\.")):
            validate_monitor_section({"monitor": block})

    def test_cross_field_rules_are_not_the_loaders_job(self) -> None:
        """warn above crit loads; the verifier's M029 refuses it at deploy."""
        cfg = _load({"thresholds": {"host_cpu_pct": {"warn": 95, "crit": 80}}})
        assert cfg.thresholds.host_cpu_pct == ThresholdBand(95.0, 80.0)


class TestFileAndArtifactLoading:
    def test_a_missing_file_is_defaults(self, tmp_path: Path) -> None:
        assert load_monitor_config(tmp_path / "nope.yaml") == MonitorConfig()

    def test_a_file_with_a_block(self, tmp_path: Path) -> None:
        path = tmp_path / "engine_config.yaml"
        path.write_text(yaml.safe_dump({"monitor": {"pull_port": 6000}}))
        assert load_monitor_config(path).pull_port == 6000

    def test_no_deployed_artifact_is_defaults(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            "edumatcher.config_artifact.load_compiled_config", lambda: None
        )
        assert load_default_monitor_config() == MonitorConfig()

    def test_a_deployed_artifact_supplies_the_section(self, monkeypatch: Any) -> None:
        custom = MonitorConfig(pull_port=6000)

        class _Compiled:
            monitor = custom

        monkeypatch.setattr(
            "edumatcher.config_artifact.load_compiled_config", lambda: _Compiled()
        )
        assert load_default_monitor_config() is custom

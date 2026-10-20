"""pm-config-gen and the top-level `monitor` block."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from edumatcher.config_deploy import compile_config
from edumatcher.config_gen.cli import main as config_gen_main
from edumatcher.cverifier import layer3_semantic
from edumatcher.monitor.config import (
    MonitorConfig,
    MonitorRetention,
    MonitorThresholds,
    ThresholdBand,
    monitor_config_from_raw,
)

BASE = ["--symbols", "AAPL", "--participants", "GW01"]


def _generate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *options: str
) -> tuple[dict[str, Any], Path]:
    out = tmp_path / "engine_config.yaml"
    monkeypatch.setattr(
        "sys.argv", ["pm-config-gen", *BASE, *options, "--output", str(out), "--force"]
    )
    config_gen_main()
    return yaml.safe_load(out.read_text()), out


def _refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *options: str) -> None:
    with pytest.raises(SystemExit) as exc:
        _generate(monkeypatch, tmp_path, *options)
    assert exc.value.code == 2


class TestEmission:
    def test_no_monitor_option_writes_no_block(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        raw, _ = _generate(monkeypatch, tmp_path)
        assert "monitor" not in raw

    def test_monitor_writes_every_field_at_its_default(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        raw, _ = _generate(monkeypatch, tmp_path, "--monitor")
        block = raw["monitor"]
        assert set(block) == {
            "enabled",
            "bind_address",
            "host",
            "pull_port",
            "pub_port",
            "beacon_interval_sec",
            "hung_after_sec",
            "silent_after_beacons",
            "book_metrics_interval_sec",
            "retention",
            "thresholds",
        }
        assert len(block["thresholds"]) == 7
        assert monitor_config_from_raw(raw) == MonitorConfig()

    def test_every_override_lands(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        raw, _ = _generate(
            monkeypatch,
            tmp_path,
            "--monitor-disabled",
            "--monitor-bind-address", "0.0.0.0",
            "--monitor-host", "monitor.lan",
            "--monitor-pull-port", "6610",
            "--monitor-pub-port", "6611",
            "--monitor-beacon-interval-sec", "1.5",
            "--monitor-hung-after-sec", "8",
            "--monitor-silent-after-beacons", "4",
            "--monitor-book-metrics-interval-sec", "30",
            "--monitor-raw-hours", "2",
            "--monitor-minute-days", "14",
            "--monitor-threshold", "host_cpu_pct:70:90",
            "--monitor-threshold", "disk_free_pct:20:10",
        )  # fmt: skip
        config = monitor_config_from_raw(raw)
        assert config == MonitorConfig(
            enabled=False,
            bind_address="0.0.0.0",
            host="monitor.lan",
            pull_port=6610,
            pub_port=6611,
            beacon_interval_sec=1.5,
            hung_after_sec=8.0,
            silent_after_beacons=4,
            book_metrics_interval_sec=30.0,
            retention=MonitorRetention(raw_hours=2, minute_days=14),
            thresholds=MonitorThresholds(
                host_cpu_pct=ThresholdBand(70.0, 90.0),
                disk_free_pct=ThresholdBand(20.0, 10.0),
            ),
        )

    def test_any_monitor_option_implies_the_block(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        raw, _ = _generate(monkeypatch, tmp_path, "--monitor-raw-hours", "3")
        assert raw["monitor"]["retention"]["raw_hours"] == 3
        assert raw["monitor"]["enabled"] is True

    def test_the_block_has_its_section_hint(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _, out = _generate(monkeypatch, tmp_path, "--monitor")
        text = out.read_text()
        assert "# health beacons and pm-monitor (operator dashboard)\nmonitor:" in text


class TestRefusals:
    """pm-config-gen never writes a block pm-config-deploy would refuse."""

    @pytest.mark.parametrize(
        "options",
        [
            ("--monitor-threshold", "host_cpu_pct:70"),  # format
            ("--monitor-threshold", "cpu:70:90"),  # unknown rule
            ("--monitor-threshold", "host_cpu_pct:a:90"),  # not a number
            ("--monitor-threshold", "host_cpu_pct:70:90",
             "--monitor-threshold", "host_cpu_pct:60:80"),  # twice
            ("--monitor-threshold", "host_cpu_pct:90:70"),  # M029
            ("--monitor-threshold", "disk_free_pct:5:15"),  # M029, inverted rule
            ("--monitor-hung-after-sec", "2"),  # M030: not above the 2 s interval
            ("--monitor-pull-port", "5611"),  # equal to the pub port
            ("--monitor-beacon-interval-sec", "0"),  # loader: > 0
            ("--monitor-pub-port", "70000"),  # loader: port range
            ("--monitor-silent-after-beacons", "0"),  # loader: > 0
        ],
    )  # fmt: skip
    def test_refused(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        options: tuple[str, ...],
    ) -> None:
        _refused(monkeypatch, tmp_path, *options)

    def test_a_host_that_cannot_reach_the_bind_is_a_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        raw, _ = _generate(monkeypatch, tmp_path, "--monitor-bind-address", "10.0.0.5")
        assert raw["monitor"]["bind_address"] == "10.0.0.5"
        assert "(M031)" in capsys.readouterr().err


def test_a_generated_block_verifies_and_compiles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The round trip pm-config-deploy makes: verify, then compile."""
    raw, out = _generate(
        monkeypatch,
        tmp_path,
        "--monitor-hung-after-sec", "8",
        "--monitor-threshold", "reject_pct_5m:5:20",
    )  # fmt: skip
    results: list[Any] = []
    layer3_semantic._check_monitor_semantic(raw, results)
    assert results == []
    compiled = compile_config(out)
    assert compiled.monitor.hung_after_sec == 8.0
    assert compiled.monitor.thresholds.reject_pct_5m == ThresholdBand(5.0, 20.0)

"""The ``monitor:`` section of ``engine_config.yaml``.

Read by ``pm-monitor`` (where to bind, how to judge health, how long to keep
history) and by every process that sends a health beacon (where to send it and
how often). Same shape as ``edumatcher.log_srv.config``: a frozen dataclass of
resolved settings, a loader for the optional YAML block, a validator for the
verifier, and a reader of the compiled artifact. See
docs-design/EduMatcher-Operator-Dashboard.md §14.

The loader checks shape and ranges only. Rules that relate two fields to each
other -- a warn band below its crit band, ``hung_after_sec`` above the beacon
interval, distinct ports -- are verifier layer-3 checks (M029-M031), which
``pm-config-deploy`` runs before it compiles, so an incoherent section never
reaches an artifact.

``bind_address`` is stored as authored, not resolved: ``pm-monitor`` applies
``EDUMATCHER_GATEWAY_BIND_HOST`` when it binds, so the override follows the
environment the process runs in rather than the one the artifact was compiled
in.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

import yaml

from edumatcher.config import MONITOR_HOST, MONITOR_PUB_PORT, MONITOR_PULL_PORT

DEFAULT_BIND_ADDRESS = "127.0.0.1"
DEFAULT_BEACON_INTERVAL_SEC = 2.0
DEFAULT_HUNG_AFTER_SEC = 5.0
DEFAULT_SILENT_AFTER_BEACONS = 3
DEFAULT_BOOK_METRICS_INTERVAL_SEC = 10.0
DEFAULT_RAW_HOURS = 6
DEFAULT_MINUTE_DAYS = 7

#: Threshold rules where a *low* value is bad, so warn sits above crit.
INVERTED_THRESHOLDS = frozenset({"disk_free_pct"})


@dataclass(frozen=True)
class ThresholdBand:
    """A warn level and a crit level for one rule (design §9.6)."""

    warn: float
    crit: float


@dataclass(frozen=True)
class MonitorThresholds:
    """Every configurable threshold rule, with the §9.6 defaults."""

    host_cpu_pct: ThresholdBand = ThresholdBand(80.0, 95.0)
    host_mem_pct: ThresholdBand = ThresholdBand(80.0, 92.0)
    disk_free_pct: ThresholdBand = ThresholdBand(15.0, 5.0)
    engine_handle_p99_us: ThresholdBand = ThresholdBand(2000.0, 10000.0)
    reject_pct_5m: ThresholdBand = ThresholdBand(10.0, 30.0)
    rss_growth_pct_1h: ThresholdBand = ThresholdBand(50.0, 100.0)
    heap_garbage_pct: ThresholdBand = ThresholdBand(50.0, 80.0)


@dataclass(frozen=True)
class MonitorRetention:
    """How long ``metrics.db`` keeps each resolution (design §9.5)."""

    raw_hours: int = DEFAULT_RAW_HOURS
    minute_days: int = DEFAULT_MINUTE_DAYS


@dataclass(frozen=True)
class MonitorConfig:
    """Resolved ``monitor:`` section.

    Present in every compiled artifact. ``enabled: false`` means no process
    constructs a health reporter and ``pm-monitor`` refuses to start.
    """

    enabled: bool = True
    bind_address: str = DEFAULT_BIND_ADDRESS
    host: str = MONITOR_HOST
    pull_port: int = MONITOR_PULL_PORT
    pub_port: int = MONITOR_PUB_PORT
    beacon_interval_sec: float = DEFAULT_BEACON_INTERVAL_SEC
    hung_after_sec: float = DEFAULT_HUNG_AFTER_SEC
    silent_after_beacons: int = DEFAULT_SILENT_AFTER_BEACONS
    book_metrics_interval_sec: float = DEFAULT_BOOK_METRICS_INTERVAL_SEC
    retention: MonitorRetention = field(default_factory=MonitorRetention)
    thresholds: MonitorThresholds = field(default_factory=MonitorThresholds)

    @property
    def pull_connect_addr(self) -> str:
        """Where a beaconing process connects its PUSH socket."""
        return f"tcp://{self.host}:{self.pull_port}"

    @property
    def pub_connect_addr(self) -> str:
        """Where a subscriber (the dashboard bridge) connects its SUB socket."""
        return f"tcp://{self.host}:{self.pub_port}"


#: Keys the loader reads, per level. The verifier's S121 sets are pinned to
#: these dataclasses by tests/test_cverifier.py.
THRESHOLD_RULES: tuple[str, ...] = tuple(f.name for f in fields(MonitorThresholds))


def _mapping(raw: object, path: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be a mapping")
    return raw


def _bool(raw: object, path: str) -> bool:
    # Strict on purpose: bool("false") is True, so a quoted "false" coerced
    # here would silently leave monitoring on.
    if not isinstance(raw, bool):
        raise ValueError(f"{path} must be true or false")
    return raw


def _text(raw: object, path: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return raw.strip()


def _int(raw: object, path: str, low: int, high: int | None = None) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"{path} must be an integer")
    if raw < low or (high is not None and raw > high):
        bound = f"in {low}-{high}" if high is not None else f">= {low}"
        raise ValueError(f"{path} must be {bound}, got {raw}")
    return raw


def _positive(raw: object, path: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{path} must be a number")
    if raw <= 0:
        raise ValueError(f"{path} must be > 0, got {raw}")
    return float(raw)


def _non_negative(raw: object, path: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{path} must be a number")
    if raw < 0:
        raise ValueError(f"{path} must be >= 0, got {raw}")
    return float(raw)


def _retention(raw: object) -> MonitorRetention:
    if raw is None:
        return MonitorRetention()
    block = _mapping(raw, "monitor.retention")
    return MonitorRetention(
        raw_hours=_int(
            block.get("raw_hours", DEFAULT_RAW_HOURS), "monitor.retention.raw_hours", 1
        ),
        minute_days=_int(
            block.get("minute_days", DEFAULT_MINUTE_DAYS),
            "monitor.retention.minute_days",
            1,
        ),
    )


def _thresholds(raw: object) -> MonitorThresholds:
    defaults = MonitorThresholds()
    if raw is None:
        return defaults
    block = _mapping(raw, "monitor.thresholds")
    bands: dict[str, ThresholdBand] = {}
    for rule in THRESHOLD_RULES:
        if rule not in block:
            continue
        path = f"monitor.thresholds.{rule}"
        band = _mapping(block[rule], path)
        for edge in ("warn", "crit"):
            if edge not in band:
                raise ValueError(f"{path}.{edge} is required")
        bands[rule] = ThresholdBand(
            warn=_non_negative(band["warn"], f"{path}.warn"),
            crit=_non_negative(band["crit"], f"{path}.crit"),
        )
    return replace(defaults, **bands)


def monitor_config_from_raw(raw: dict[str, Any]) -> MonitorConfig:
    """Resolve the ``monitor`` block of an already-parsed config document.

    Public because ``pm-config-show`` resolves the block it displays through
    this rather than restating the defaults.
    """
    section = raw.get("monitor")
    if section is None:
        return MonitorConfig()
    block = _mapping(section, "monitor")
    return MonitorConfig(
        enabled=_bool(block.get("enabled", True), "monitor.enabled"),
        bind_address=_text(
            block.get("bind_address", DEFAULT_BIND_ADDRESS), "monitor.bind_address"
        ),
        host=_text(block.get("host", MONITOR_HOST), "monitor.host"),
        pull_port=_int(
            block.get("pull_port", MONITOR_PULL_PORT), "monitor.pull_port", 1, 65535
        ),
        pub_port=_int(
            block.get("pub_port", MONITOR_PUB_PORT), "monitor.pub_port", 1, 65535
        ),
        beacon_interval_sec=_positive(
            block.get("beacon_interval_sec", DEFAULT_BEACON_INTERVAL_SEC),
            "monitor.beacon_interval_sec",
        ),
        hung_after_sec=_positive(
            block.get("hung_after_sec", DEFAULT_HUNG_AFTER_SEC),
            "monitor.hung_after_sec",
        ),
        silent_after_beacons=_int(
            block.get("silent_after_beacons", DEFAULT_SILENT_AFTER_BEACONS),
            "monitor.silent_after_beacons",
            1,
        ),
        book_metrics_interval_sec=_positive(
            block.get("book_metrics_interval_sec", DEFAULT_BOOK_METRICS_INTERVAL_SEC),
            "monitor.book_metrics_interval_sec",
        ),
        retention=_retention(block.get("retention")),
        thresholds=_thresholds(block.get("thresholds")),
    )


def load_monitor_config(path: Path) -> MonitorConfig:
    """Load the optional ``monitor:`` block from engine config YAML."""
    if not path.exists():
        return MonitorConfig()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return MonitorConfig()
    return monitor_config_from_raw(raw)


def validate_monitor_section(raw: dict[str, Any]) -> None:
    """Validate the monitor section using the runtime loader's semantics."""
    monitor_config_from_raw(raw)


def load_default_monitor_config() -> MonitorConfig:
    """Return the monitor section of the deployed compiled configuration.

    Absent artifact means defaults, as for the log-server section: a process
    on a machine with no deployed configuration still finds pm-monitor on its
    default port.

    The import is deferred because ``config_artifact`` imports this module.
    """
    from edumatcher.config_artifact import load_compiled_config

    compiled = load_compiled_config()
    return MonitorConfig() if compiled is None else compiled.monitor

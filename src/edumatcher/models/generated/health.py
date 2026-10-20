# GENERATED FROM spec/messages/health.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""Generated bindings for the ``health`` message family.

Family version 1. Every symbol here is derived from ``spec/messages/health.yaml``; edit
the spec, not this file.

``pm-msgen check`` fails the build if this file and the spec disagree. See
../../../../docs/books/architecture-and-development/part-4-developing/040-message-
generation.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, cast

from edumatcher.models import message as _msg
from edumatcher.models.generated._runtime import MessageValidationError

FAMILY = "health"
FAMILY_VERSION = 1


_METRIC_SAMPLE_KIND_VALUES = ("COUNTER", "GAUGE")
MetricSampleKind = Literal["COUNTER", "GAUGE"]


@dataclass(frozen=True, slots=True)
class MetricSample:
    """One application metric of a process at the time of its beacon. A list entry
    rather than a map value, so the dimension (`label`) is a field and a metric
    with no dimension simply carries the empty label.
    """

    name: str
    kind: MetricSampleKind
    value: float  # unit: dimensionless
    label: str = ""

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.name) < 1:
            raise MessageValidationError(
                f"name: length {len(self.name)} is below min_len 1"
            )
        if len(self.name) > 64:
            raise MessageValidationError(
                f"name: length {len(self.name)} exceeds max_len 64"
            )
        if self.kind not in _METRIC_SAMPLE_KIND_VALUES:
            raise MessageValidationError(
                f"kind: {self.kind!r} is not one of {_METRIC_SAMPLE_KIND_VALUES!r}"
            )
        if len(self.label) > 32:
            raise MessageValidationError(
                f"label: length {len(self.label)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "MetricSample":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            name=str(p["name"]),
            kind=cast(MetricSampleKind, str(p["kind"])),
            label=str(p.get("label", "")),
            value=float(p["value"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "name": self.name,
            "kind": self.kind,
            "label": self.label,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class FileSize:
    """The size of one data file pm-monitor watches under the data directory."""

    name: str
    size_bytes: int  # unit: bytes

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.name) > 32:
            raise MessageValidationError(
                f"name: length {len(self.name)} exceeds max_len 32"
            )
        if self.size_bytes < 0:
            raise MessageValidationError(
                f"size_bytes: {self.size_bytes!r} must be >= 0"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "FileSize":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            name=str(p["name"]),
            size_bytes=int(p["size_bytes"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "name": self.name,
            "size_bytes": self.size_bytes,
        }


_EXCHANGE_STATUS_STATUS_VALUES = ("OPERATIONAL", "DEGRADED", "IMPAIRED", "DOWN")
ExchangeStatusStatus = Literal["OPERATIONAL", "DEGRADED", "IMPAIRED", "DOWN"]


@dataclass(frozen=True, slots=True)
class ExchangeStatus:
    """The one-line answer to "is the exchange OK?" (design section 10)."""

    status: ExchangeStatusStatus
    session_state: str
    trading_date: str
    session_timezone: str

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.status not in _EXCHANGE_STATUS_STATUS_VALUES:
            raise MessageValidationError(
                f"status: {self.status!r} is not one of {_EXCHANGE_STATUS_STATUS_VALUES!r}"
            )
        if len(self.session_state) > 32:
            raise MessageValidationError(
                f"session_state: length {len(self.session_state)} exceeds max_len 32"
            )
        if len(self.trading_date) > 10:
            raise MessageValidationError(
                f"trading_date: length {len(self.trading_date)} exceeds max_len 10"
            )
        if len(self.session_timezone) > 64:
            raise MessageValidationError(
                f"session_timezone: length {len(self.session_timezone)} exceeds max_len 64"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "ExchangeStatus":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            status=cast(ExchangeStatusStatus, str(p["status"])),
            session_state=str(p["session_state"]),
            trading_date=str(p["trading_date"]),
            session_timezone=str(p["session_timezone"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "status": self.status,
            "session_state": self.session_state,
            "trading_date": self.trading_date,
            "session_timezone": self.session_timezone,
        }


@dataclass(frozen=True, slots=True)
class HostStats:
    """The host pm-monitor runs on (design section 8.1)."""

    cpu_pct: float  # unit: percent
    cpu_per_core: list[float]
    load1: float  # unit: dimensionless
    load5: float  # unit: dimensionless
    load15: float  # unit: dimensionless
    mem_total_bytes: int  # unit: bytes
    mem_used_bytes: int  # unit: bytes
    mem_available_bytes: int  # unit: bytes
    swap_used_bytes: int  # unit: bytes
    disk_free_bytes: int  # unit: bytes
    disk_total_bytes: int  # unit: bytes
    files: list[FileSize]

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.cpu_pct < 0:
            raise MessageValidationError(f"cpu_pct: {self.cpu_pct!r} must be >= 0")
        if self.mem_total_bytes < 0:
            raise MessageValidationError(
                f"mem_total_bytes: {self.mem_total_bytes!r} must be >= 0"
            )
        if self.mem_used_bytes < 0:
            raise MessageValidationError(
                f"mem_used_bytes: {self.mem_used_bytes!r} must be >= 0"
            )
        if self.mem_available_bytes < 0:
            raise MessageValidationError(
                f"mem_available_bytes: {self.mem_available_bytes!r} must be >= 0"
            )
        if self.swap_used_bytes < 0:
            raise MessageValidationError(
                f"swap_used_bytes: {self.swap_used_bytes!r} must be >= 0"
            )
        if self.disk_free_bytes < 0:
            raise MessageValidationError(
                f"disk_free_bytes: {self.disk_free_bytes!r} must be >= 0"
            )
        if self.disk_total_bytes < 0:
            raise MessageValidationError(
                f"disk_total_bytes: {self.disk_total_bytes!r} must be >= 0"
            )
        for files_item in self.files:
            files_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "HostStats":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            cpu_pct=float(p["cpu_pct"]),
            cpu_per_core=[float(item) for item in p["cpu_per_core"]],
            load1=float(p["load1"]),
            load5=float(p["load5"]),
            load15=float(p["load15"]),
            mem_total_bytes=int(p["mem_total_bytes"]),
            mem_used_bytes=int(p["mem_used_bytes"]),
            mem_available_bytes=int(p["mem_available_bytes"]),
            swap_used_bytes=int(p["swap_used_bytes"]),
            disk_free_bytes=int(p["disk_free_bytes"]),
            disk_total_bytes=int(p["disk_total_bytes"]),
            files=[FileSize.from_dict(item) for item in p["files"]],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "cpu_pct": self.cpu_pct,
            "cpu_per_core": self.cpu_per_core,
            "load1": self.load1,
            "load5": self.load5,
            "load15": self.load15,
            "mem_total_bytes": self.mem_total_bytes,
            "mem_used_bytes": self.mem_used_bytes,
            "mem_available_bytes": self.mem_available_bytes,
            "swap_used_bytes": self.swap_used_bytes,
            "disk_free_bytes": self.disk_free_bytes,
            "disk_total_bytes": self.disk_total_bytes,
            "files": [item.to_dict() for item in self.files],
        }


@dataclass(frozen=True, slots=True)
class Sparkline:
    """The last samples of a process, oldest first, for inline sparklines."""

    rss: list[int]
    cpu: list[float]

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.rss) > 60:
            raise MessageValidationError("rss: more than 60 item(s)")
        if len(self.cpu) > 60:
            raise MessageValidationError("cpu: more than 60 item(s)")

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "Sparkline":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            rss=[int(item) for item in p["rss"]],
            cpu=[float(item) for item in p["cpu"]],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "rss": self.rss,
            "cpu": self.cpu,
        }


_PROCESS_HEALTH_GROUP_VALUES = ("EXCHANGE", "BOT")
ProcessHealthGroup = Literal["EXCHANGE", "BOT"]
_PROCESS_HEALTH_STATE_VALUES = (
    "HEALTHY",
    "DEGRADED",
    "HUNG",
    "SILENT",
    "DEAD",
    "MISSING",
    "STOPPED",
)
ProcessHealthState = Literal[
    "HEALTHY",
    "DEGRADED",
    "HUNG",
    "SILENT",
    "DEAD",
    "MISSING",
    "STOPPED",
]


@dataclass(frozen=True, slots=True)
class ProcessHealth:
    """One process as pm-monitor sees it: a process that beacons, or one the active
    emo profile expects and that has never beaconed (MISSING, with zero figures
    and an empty host).
    """

    key: str
    process: str
    host: str
    group: ProcessHealthGroup
    pid: int  # unit: dimensionless
    state: ProcessHealthState
    restarted_recently: bool
    uptime_sec: float  # unit: duration_seconds
    rss_bytes: int  # unit: bytes
    cpu_pct: float  # unit: percent
    threads: int  # unit: dimensionless
    loop_age_ms: float  # unit: duration_millis
    loop_lag_ms: float  # unit: duration_millis
    last_beacon_age_ms: float  # unit: duration_millis
    spark: Sparkline
    metrics: list[MetricSample]
    instance: str | None = None
    starting: bool = False
    fds: int | None = None  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.key) < 1:
            raise MessageValidationError(
                f"key: length {len(self.key)} is below min_len 1"
            )
        if len(self.key) > 200:
            raise MessageValidationError(
                f"key: length {len(self.key)} exceeds max_len 200"
            )
        if len(self.process) > 32:
            raise MessageValidationError(
                f"process: length {len(self.process)} exceeds max_len 32"
            )
        if self.instance is not None:
            if len(self.instance) > 32:
                raise MessageValidationError(
                    f"instance: length {len(self.instance)} exceeds max_len 32"
                )
        if len(self.host) > 128:
            raise MessageValidationError(
                f"host: length {len(self.host)} exceeds max_len 128"
            )
        if self.group not in _PROCESS_HEALTH_GROUP_VALUES:
            raise MessageValidationError(
                f"group: {self.group!r} is not one of {_PROCESS_HEALTH_GROUP_VALUES!r}"
            )
        if self.pid < 0:
            raise MessageValidationError(f"pid: {self.pid!r} must be >= 0")
        if self.state not in _PROCESS_HEALTH_STATE_VALUES:
            raise MessageValidationError(
                f"state: {self.state!r} is not one of {_PROCESS_HEALTH_STATE_VALUES!r}"
            )
        if self.uptime_sec < 0:
            raise MessageValidationError(
                f"uptime_sec: {self.uptime_sec!r} must be >= 0"
            )
        if self.rss_bytes < 0:
            raise MessageValidationError(f"rss_bytes: {self.rss_bytes!r} must be >= 0")
        if self.cpu_pct < 0:
            raise MessageValidationError(f"cpu_pct: {self.cpu_pct!r} must be >= 0")
        if self.threads < 0:
            raise MessageValidationError(f"threads: {self.threads!r} must be >= 0")
        if self.loop_age_ms < 0:
            raise MessageValidationError(
                f"loop_age_ms: {self.loop_age_ms!r} must be >= 0"
            )
        if self.loop_lag_ms < 0:
            raise MessageValidationError(
                f"loop_lag_ms: {self.loop_lag_ms!r} must be >= 0"
            )
        if self.last_beacon_age_ms < 0:
            raise MessageValidationError(
                f"last_beacon_age_ms: {self.last_beacon_age_ms!r} must be >= 0"
            )
        self.spark.validate()
        for metrics_item in self.metrics:
            metrics_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "ProcessHealth":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            key=str(p["key"]),
            process=str(p["process"]),
            instance=None if p.get("instance") is None else str(p["instance"]),
            host=str(p["host"]),
            group=cast(ProcessHealthGroup, str(p["group"])),
            pid=int(p["pid"]),
            state=cast(ProcessHealthState, str(p["state"])),
            restarted_recently=bool(p["restarted_recently"]),
            starting=bool(p.get("starting", False)),
            uptime_sec=float(p["uptime_sec"]),
            rss_bytes=int(p["rss_bytes"]),
            cpu_pct=float(p["cpu_pct"]),
            threads=int(p["threads"]),
            fds=None if p.get("fds") is None else int(p["fds"]),
            loop_age_ms=float(p["loop_age_ms"]),
            loop_lag_ms=float(p["loop_lag_ms"]),
            last_beacon_age_ms=float(p["last_beacon_age_ms"]),
            spark=Sparkline.from_dict(p["spark"]),
            metrics=[MetricSample.from_dict(item) for item in p["metrics"]],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "key": self.key,
            "process": self.process,
            "instance": self.instance,
            "host": self.host,
            "group": self.group,
            "pid": self.pid,
            "state": self.state,
            "restarted_recently": self.restarted_recently,
            "starting": self.starting,
            "uptime_sec": self.uptime_sec,
            "rss_bytes": self.rss_bytes,
            "cpu_pct": self.cpu_pct,
            "threads": self.threads,
            "fds": self.fds,
            "loop_age_ms": self.loop_age_ms,
            "loop_lag_ms": self.loop_lag_ms,
            "last_beacon_age_ms": self.last_beacon_age_ms,
            "spark": self.spark.to_dict(),
            "metrics": [item.to_dict() for item in self.metrics],
        }


@dataclass(frozen=True, slots=True)
class RateStats:
    """A counter turned into the figures of design section 9.4. Every increment is
    reset-corrected, so a process restart neither loses nor double-counts.
    """

    today: int  # unit: dimensionless
    per_sec_now: float  # unit: dimensionless
    avg_per_min: float  # unit: dimensionless
    avg_per_hour: float  # unit: dimensionless
    avg_per_day: float | None = None  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.today < 0:
            raise MessageValidationError(f"today: {self.today!r} must be >= 0")
        if self.per_sec_now < 0:
            raise MessageValidationError(
                f"per_sec_now: {self.per_sec_now!r} must be >= 0"
            )
        if self.avg_per_min < 0:
            raise MessageValidationError(
                f"avg_per_min: {self.avg_per_min!r} must be >= 0"
            )
        if self.avg_per_hour < 0:
            raise MessageValidationError(
                f"avg_per_hour: {self.avg_per_hour!r} must be >= 0"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "RateStats":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            today=int(p["today"]),
            per_sec_now=float(p["per_sec_now"]),
            avg_per_min=float(p["avg_per_min"]),
            avg_per_hour=float(p["avg_per_hour"]),
            avg_per_day=(
                None if p.get("avg_per_day") is None else float(p["avg_per_day"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "today": self.today,
            "per_sec_now": self.per_sec_now,
            "avg_per_min": self.avg_per_min,
            "avg_per_hour": self.avg_per_hour,
            "avg_per_day": self.avg_per_day,
        }


@dataclass(frozen=True, slots=True)
class RejectCount:
    """Rejects of one reason today: a RejectCode, or a label the engine gives a
    reject known only by its text (MM_MAX_SPREAD, MM_MIN_QTY, UNKNOWN).
    """

    code: str
    count: int  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.code) < 1:
            raise MessageValidationError(
                f"code: length {len(self.code)} is below min_len 1"
            )
        if len(self.code) > 32:
            raise MessageValidationError(
                f"code: length {len(self.code)} exceeds max_len 32"
            )
        if self.count < 0:
            raise MessageValidationError(f"count: {self.count!r} must be >= 0")

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "RejectCount":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            code=str(p["code"]),
            count=int(p["count"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "code": self.code,
            "count": self.count,
        }


@dataclass(frozen=True, slots=True)
class TradingStats:
    """Exchange-wide trading activity, summed over gateways and symbols."""

    orders: RateStats
    trades: RateStats
    traded_value_today: float  # unit: money
    reject_pct_5m: float  # unit: percent
    handle_p50_us: float  # unit: duration_micros
    handle_p99_us: float  # unit: duration_micros
    busy_pct: float  # unit: percent
    rejects_by_code: list[RejectCount]

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        self.orders.validate()
        self.trades.validate()
        if self.traded_value_today < 0:
            raise MessageValidationError(
                f"traded_value_today: {self.traded_value_today!r} must be >= 0"
            )
        if self.reject_pct_5m < 0:
            raise MessageValidationError(
                f"reject_pct_5m: {self.reject_pct_5m!r} must be >= 0"
            )
        if self.handle_p50_us < 0:
            raise MessageValidationError(
                f"handle_p50_us: {self.handle_p50_us!r} must be >= 0"
            )
        if self.handle_p99_us < 0:
            raise MessageValidationError(
                f"handle_p99_us: {self.handle_p99_us!r} must be >= 0"
            )
        if self.busy_pct < 0:
            raise MessageValidationError(f"busy_pct: {self.busy_pct!r} must be >= 0")
        for rejects_by_code_item in self.rejects_by_code:
            rejects_by_code_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "TradingStats":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            orders=RateStats.from_dict(p["orders"]),
            trades=RateStats.from_dict(p["trades"]),
            traded_value_today=float(p["traded_value_today"]),
            reject_pct_5m=float(p["reject_pct_5m"]),
            handle_p50_us=float(p["handle_p50_us"]),
            handle_p99_us=float(p["handle_p99_us"]),
            busy_pct=float(p["busy_pct"]),
            rejects_by_code=(
                [RejectCount.from_dict(item) for item in p["rejects_by_code"]]
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "orders": self.orders.to_dict(),
            "trades": self.trades.to_dict(),
            "traded_value_today": self.traded_value_today,
            "reject_pct_5m": self.reject_pct_5m,
            "handle_p50_us": self.handle_p50_us,
            "handle_p99_us": self.handle_p99_us,
            "busy_pct": self.busy_pct,
            "rejects_by_code": [item.to_dict() for item in self.rejects_by_code],
        }


@dataclass(frozen=True, slots=True)
class ParticipantStats:
    """One configured participant (gateway id) as the engine counts it."""

    id: str
    role: str
    connected: bool
    orders: RateStats
    reject_pct: float  # unit: percent
    fills_today: int  # unit: dimensionless
    resting_orders: int  # unit: dimensionless
    connects_today: int  # unit: dimensionless
    disconnects_today: int  # unit: dimensionless
    heartbeat_timeouts_today: int  # unit: dimensionless
    connected_since: str | None = None

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.id) > 32:
            raise MessageValidationError(
                f"id: length {len(self.id)} exceeds max_len 32"
            )
        if len(self.role) > 32:
            raise MessageValidationError(
                f"role: length {len(self.role)} exceeds max_len 32"
            )
        if self.connected_since is not None:
            if len(self.connected_since) > 32:
                raise MessageValidationError(
                    f"connected_since: length {len(self.connected_since)} exceeds max_len 32"
                )
        self.orders.validate()
        if self.reject_pct < 0:
            raise MessageValidationError(
                f"reject_pct: {self.reject_pct!r} must be >= 0"
            )
        if self.fills_today < 0:
            raise MessageValidationError(
                f"fills_today: {self.fills_today!r} must be >= 0"
            )
        if self.resting_orders < 0:
            raise MessageValidationError(
                f"resting_orders: {self.resting_orders!r} must be >= 0"
            )
        if self.connects_today < 0:
            raise MessageValidationError(
                f"connects_today: {self.connects_today!r} must be >= 0"
            )
        if self.disconnects_today < 0:
            raise MessageValidationError(
                f"disconnects_today: {self.disconnects_today!r} must be >= 0"
            )
        if self.heartbeat_timeouts_today < 0:
            raise MessageValidationError(
                f"heartbeat_timeouts_today: {self.heartbeat_timeouts_today!r} must be >= 0"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "ParticipantStats":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            id=str(p["id"]),
            role=str(p["role"]),
            connected=bool(p["connected"]),
            connected_since=(
                None if p.get("connected_since") is None else str(p["connected_since"])
            ),
            orders=RateStats.from_dict(p["orders"]),
            reject_pct=float(p["reject_pct"]),
            fills_today=int(p["fills_today"]),
            resting_orders=int(p["resting_orders"]),
            connects_today=int(p["connects_today"]),
            disconnects_today=int(p["disconnects_today"]),
            heartbeat_timeouts_today=int(p["heartbeat_timeouts_today"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "id": self.id,
            "role": self.role,
            "connected": self.connected,
            "connected_since": self.connected_since,
            "orders": self.orders.to_dict(),
            "reject_pct": self.reject_pct,
            "fills_today": self.fills_today,
            "resting_orders": self.resting_orders,
            "connects_today": self.connects_today,
            "disconnects_today": self.disconnects_today,
            "heartbeat_timeouts_today": self.heartbeat_timeouts_today,
        }


@dataclass(frozen=True, slots=True)
class BookStats:
    """One order book (design section 8.3); refreshed every
    book_metrics_interval_sec.
    """

    symbol: str
    resting_orders: int  # unit: dimensionless
    stop_orders: int  # unit: dimensionless
    bid_levels: int  # unit: dimensionless
    ask_levels: int  # unit: dimensionless
    est_bytes: int  # unit: bytes
    heap_garbage_pct: float  # unit: percent
    trades_today: int  # unit: dimensionless
    halted: bool

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if self.resting_orders < 0:
            raise MessageValidationError(
                f"resting_orders: {self.resting_orders!r} must be >= 0"
            )
        if self.stop_orders < 0:
            raise MessageValidationError(
                f"stop_orders: {self.stop_orders!r} must be >= 0"
            )
        if self.bid_levels < 0:
            raise MessageValidationError(
                f"bid_levels: {self.bid_levels!r} must be >= 0"
            )
        if self.ask_levels < 0:
            raise MessageValidationError(
                f"ask_levels: {self.ask_levels!r} must be >= 0"
            )
        if self.est_bytes < 0:
            raise MessageValidationError(f"est_bytes: {self.est_bytes!r} must be >= 0")
        if self.heap_garbage_pct < 0:
            raise MessageValidationError(
                f"heap_garbage_pct: {self.heap_garbage_pct!r} must be >= 0"
            )
        if self.heap_garbage_pct > 100:
            raise MessageValidationError(
                f"heap_garbage_pct: {self.heap_garbage_pct!r} must be <= 100"
            )
        if self.trades_today < 0:
            raise MessageValidationError(
                f"trades_today: {self.trades_today!r} must be >= 0"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "BookStats":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            symbol=str(p["symbol"]),
            resting_orders=int(p["resting_orders"]),
            stop_orders=int(p["stop_orders"]),
            bid_levels=int(p["bid_levels"]),
            ask_levels=int(p["ask_levels"]),
            est_bytes=int(p["est_bytes"]),
            heap_garbage_pct=float(p["heap_garbage_pct"]),
            trades_today=int(p["trades_today"]),
            halted=bool(p["halted"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "symbol": self.symbol,
            "resting_orders": self.resting_orders,
            "stop_orders": self.stop_orders,
            "bid_levels": self.bid_levels,
            "ask_levels": self.ask_levels,
            "est_bytes": self.est_bytes,
            "heap_garbage_pct": self.heap_garbage_pct,
            "trades_today": self.trades_today,
            "halted": self.halted,
        }


_GATEWAY_STATS_KIND_VALUES = ("ALF", "BALF", "MD", "RALF", "DC", "API", "LOG")
GatewayStatsKind = Literal["ALF", "BALF", "MD", "RALF", "DC", "API", "LOG"]


@dataclass(frozen=True, slots=True)
class GatewayStats:
    """One process that holds client connections: the ALF, BALF, MD, RALF and drop-
    copy gateways, the API gateway (WebSocket sessions) and pm-log-srv (LALF
    sessions). One shape for all, so row 6 of the dashboard is a loop.
    """

    key: str
    kind: GatewayStatsKind
    clients: int  # unit: dimensionless
    msgs_per_sec: float  # unit: dimensionless
    disconnects_today: int  # unit: dimensionless
    slow_disconnects_today: int  # unit: dimensionless
    clients_max: int | None = None  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.key) < 1:
            raise MessageValidationError(
                f"key: length {len(self.key)} is below min_len 1"
            )
        if len(self.key) > 200:
            raise MessageValidationError(
                f"key: length {len(self.key)} exceeds max_len 200"
            )
        if self.kind not in _GATEWAY_STATS_KIND_VALUES:
            raise MessageValidationError(
                f"kind: {self.kind!r} is not one of {_GATEWAY_STATS_KIND_VALUES!r}"
            )
        if self.clients < 0:
            raise MessageValidationError(f"clients: {self.clients!r} must be >= 0")
        if self.msgs_per_sec < 0:
            raise MessageValidationError(
                f"msgs_per_sec: {self.msgs_per_sec!r} must be >= 0"
            )
        if self.disconnects_today < 0:
            raise MessageValidationError(
                f"disconnects_today: {self.disconnects_today!r} must be >= 0"
            )
        if self.slow_disconnects_today < 0:
            raise MessageValidationError(
                f"slow_disconnects_today: {self.slow_disconnects_today!r} must be >= 0"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "GatewayStats":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            key=str(p["key"]),
            kind=cast(GatewayStatsKind, str(p["kind"])),
            clients=int(p["clients"]),
            clients_max=None if p.get("clients_max") is None else int(p["clients_max"]),
            msgs_per_sec=float(p["msgs_per_sec"]),
            disconnects_today=int(p["disconnects_today"]),
            slow_disconnects_today=int(p["slow_disconnects_today"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "key": self.key,
            "kind": self.kind,
            "clients": self.clients,
            "clients_max": self.clients_max,
            "msgs_per_sec": self.msgs_per_sec,
            "disconnects_today": self.disconnects_today,
            "slow_disconnects_today": self.slow_disconnects_today,
        }


_ACTIVE_BREACH_LEVEL_VALUES = ("WARN", "CRIT")
ActiveBreachLevel = Literal["WARN", "CRIT"]


@dataclass(frozen=True, slots=True)
class ActiveBreach:
    """One threshold currently in breach (design section 9.6)."""

    rule: str
    subject: str
    level: ActiveBreachLevel
    value: float  # unit: dimensionless
    threshold: float  # unit: dimensionless
    since: str

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.rule) > 64:
            raise MessageValidationError(
                f"rule: length {len(self.rule)} exceeds max_len 64"
            )
        if len(self.subject) > 200:
            raise MessageValidationError(
                f"subject: length {len(self.subject)} exceeds max_len 200"
            )
        if self.level not in _ACTIVE_BREACH_LEVEL_VALUES:
            raise MessageValidationError(
                f"level: {self.level!r} is not one of {_ACTIVE_BREACH_LEVEL_VALUES!r}"
            )
        if len(self.since) > 32:
            raise MessageValidationError(
                f"since: length {len(self.since)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "ActiveBreach":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            rule=str(p["rule"]),
            subject=str(p["subject"]),
            level=cast(ActiveBreachLevel, str(p["level"])),
            value=float(p["value"]),
            threshold=float(p["threshold"]),
            since=str(p["since"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "rule": self.rule,
            "subject": self.subject,
            "level": self.level,
            "value": self.value,
            "threshold": self.threshold,
            "since": self.since,
        }


TOPIC_HEALTH_BEACON = "health.beacon"
_TOPIC_HEALTH_BEACON_BYTES = "health.beacon".encode()


_HEALTH_BEACON_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "process",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "The name the process uses in its LALF HELLO, e.g. `pm-engine`.",
        "constraints": {"min_len": 1, "max_len": 32},
    },
    {
        "name": "instance",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "The --instance name where a process runs more than once, e.g. `desk`.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "pid",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
        "constraints": {"gt": 0},
    },
    {
        "name": "host",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "socket.gethostname().",
        "constraints": {"min_len": 1, "max_len": 128},
    },
    {
        "name": "boot_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Random per process start; a change means a restart even when the PID is reused.",
        "constraints": {"min_len": 1, "max_len": 16},
    },
    {
        "name": "seq",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "Per boot_id; a gap means lost beacons.",
        "constraints": {"ge": 0},
    },
    {
        "name": "started_at_ns",
        "type": "int",
        "unit": "epoch_nanos",
        "required": True,
        "doc": "Process start, for uptime only; ages use pm-monitor's receive clock.",
        "constraints": {"ge": 0},
    },
    {
        "name": "interval_sec",
        "type": "float",
        "unit": "duration_seconds",
        "required": True,
        "doc": "The sender's beacon interval; pm-monitor's silence timers scale with it.",
        "constraints": {"gt": 0},
    },
    {
        "name": "rss_bytes",
        "type": "int",
        "unit": "bytes",
        "required": True,
        "doc": "",
        "constraints": {"ge": 0},
    },
    {
        "name": "cpu_pct",
        "type": "float",
        "unit": "percent",
        "required": True,
        "doc": "Percent of one core since the previous beacon.",
        "constraints": {"ge": 0},
    },
    {
        "name": "threads",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
        "constraints": {"ge": 0},
    },
    {
        "name": "fds",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "Open file descriptors; absent where the OS has no such count.",
        "constraints": {"ge": 0},
    },
    {
        "name": "loop_age_ms",
        "type": "float",
        "unit": "duration_millis",
        "required": True,
        "doc": "Time since the main loop last called tick().",
        "constraints": {"ge": 0},
    },
    {
        "name": "loop_lag_ms",
        "type": "float",
        "unit": "duration_millis",
        "required": True,
        "doc": "Longest gap between two tick() calls since the previous beacon.",
        "constraints": {"ge": 0},
    },
    {
        "name": "final",
        "type": "bool",
        "unit": None,
        "required": False,
        "doc": "True on the last beacon of a clean shutdown: STOPPED, not DEAD.",
    },
    {
        "name": "starting",
        "type": "bool",
        "unit": None,
        "required": False,
        "doc": "True until the main loop has ticked once. The reporter starts before a process's loop exists (restoring state, loading config), and that time is not a hung loop; loop_age_ms still grows, so a process stuck starting stays visible.",
    },
    {
        "name": "metrics",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "Application metrics (design section 8); may be empty.",
    },
)


@dataclass(frozen=True, slots=True)
class HealthBeacon:
    """Every long-running pm-* process to pm-monitor, every beacon_interval_sec: the
    process's own memory, CPU, threads and file descriptors, how long ago its main
    loop last completed an iteration, and its application counters and gauges.
    Sent from a daemon thread, not from the main loop. That is the point: when the
    main loop hangs the thread keeps reporting, with a growing loop_age_ms, so pm-
    monitor can tell HUNG (beacons arrive, loop stuck) from SILENT (no beacons,
    PID alive) from DEAD (no beacons, no PID). A beacon built on the main loop
    would simply stop, and silence cannot make that distinction.

    PUSH with SNDHWM 10, LINGER 0 and a non-blocking send to pm-monitor's PULL
    (monitor.pull_port, default 5610). When pm-monitor is down the beacon is dropped and
    counted in health.beacons_dropped; an exchange process never blocks on it.
    """

    process: str
    pid: int  # unit: dimensionless
    host: str
    boot_id: str
    seq: int  # unit: dimensionless
    started_at_ns: int  # unit: epoch_nanos
    interval_sec: float  # unit: duration_seconds
    rss_bytes: int  # unit: bytes
    cpu_pct: float  # unit: percent
    threads: int  # unit: dimensionless
    loop_age_ms: float  # unit: duration_millis
    loop_lag_ms: float  # unit: duration_millis
    metrics: list[MetricSample]
    instance: str | None = None
    fds: int | None = None  # unit: dimensionless
    final: bool = False
    starting: bool = False

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.process) < 1:
            raise MessageValidationError(
                f"process: length {len(self.process)} is below min_len 1"
            )
        if len(self.process) > 32:
            raise MessageValidationError(
                f"process: length {len(self.process)} exceeds max_len 32"
            )
        if self.instance is not None:
            if len(self.instance) > 32:
                raise MessageValidationError(
                    f"instance: length {len(self.instance)} exceeds max_len 32"
                )
        if self.pid <= 0:
            raise MessageValidationError(f"pid: {self.pid!r} must be > 0")
        if len(self.host) < 1:
            raise MessageValidationError(
                f"host: length {len(self.host)} is below min_len 1"
            )
        if len(self.host) > 128:
            raise MessageValidationError(
                f"host: length {len(self.host)} exceeds max_len 128"
            )
        if len(self.boot_id) < 1:
            raise MessageValidationError(
                f"boot_id: length {len(self.boot_id)} is below min_len 1"
            )
        if len(self.boot_id) > 16:
            raise MessageValidationError(
                f"boot_id: length {len(self.boot_id)} exceeds max_len 16"
            )
        if self.seq < 0:
            raise MessageValidationError(f"seq: {self.seq!r} must be >= 0")
        if self.started_at_ns < 0:
            raise MessageValidationError(
                f"started_at_ns: {self.started_at_ns!r} must be >= 0"
            )
        if self.interval_sec <= 0:
            raise MessageValidationError(
                f"interval_sec: {self.interval_sec!r} must be > 0"
            )
        if self.rss_bytes < 0:
            raise MessageValidationError(f"rss_bytes: {self.rss_bytes!r} must be >= 0")
        if self.cpu_pct < 0:
            raise MessageValidationError(f"cpu_pct: {self.cpu_pct!r} must be >= 0")
        if self.threads < 0:
            raise MessageValidationError(f"threads: {self.threads!r} must be >= 0")
        if self.fds is not None:
            if self.fds < 0:
                raise MessageValidationError(f"fds: {self.fds!r} must be >= 0")
        if self.loop_age_ms < 0:
            raise MessageValidationError(
                f"loop_age_ms: {self.loop_age_ms!r} must be >= 0"
            )
        if self.loop_lag_ms < 0:
            raise MessageValidationError(
                f"loop_lag_ms: {self.loop_lag_ms!r} must be >= 0"
            )
        for metrics_item in self.metrics:
            metrics_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "HealthBeacon":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            process=str(p["process"]),
            instance=None if p.get("instance") is None else str(p["instance"]),
            pid=int(p["pid"]),
            host=str(p["host"]),
            boot_id=str(p["boot_id"]),
            seq=int(p["seq"]),
            started_at_ns=int(p["started_at_ns"]),
            interval_sec=float(p["interval_sec"]),
            rss_bytes=int(p["rss_bytes"]),
            cpu_pct=float(p["cpu_pct"]),
            threads=int(p["threads"]),
            fds=None if p.get("fds") is None else int(p["fds"]),
            loop_age_ms=float(p["loop_age_ms"]),
            loop_lag_ms=float(p["loop_lag_ms"]),
            final=bool(p.get("final", False)),
            starting=bool(p.get("starting", False)),
            metrics=[MetricSample.from_dict(item) for item in p["metrics"]],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "process": self.process,
            "pid": self.pid,
            "host": self.host,
            "boot_id": self.boot_id,
            "seq": self.seq,
            "started_at_ns": self.started_at_ns,
            "interval_sec": self.interval_sec,
            "rss_bytes": self.rss_bytes,
            "cpu_pct": self.cpu_pct,
            "threads": self.threads,
            "loop_age_ms": self.loop_age_ms,
            "loop_lag_ms": self.loop_lag_ms,
            "final": self.final,
            "starting": self.starting,
            "metrics": [item.to_dict() for item in self.metrics],
        }
        if self.instance is not None:
            payload["instance"] = self.instance
        if self.fds is not None:
            payload["fds"] = self.fds
        return payload


def is_health_beacon(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_HEALTH_BEACON


def make_health_beacon(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = HealthBeacon.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_HEALTH_BEACON, obj.to_dict())


def parse_health_beacon(frames: list[bytes]) -> "HealthBeacon":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = HealthBeacon.from_dict(payload)
    obj.validate()
    return obj


def describe_health_beacon() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _HEALTH_BEACON_FIELDS


TOPIC_HEALTH_SNAPSHOT = "health.snapshot"
_TOPIC_HEALTH_SNAPSHOT_BYTES = "health.snapshot".encode()


_HEALTH_SNAPSHOT_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "ts",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "ISO-8601 UTC with milliseconds; pm-monitor's clock.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "seq",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "Per pm-monitor start.",
        "constraints": {"ge": 0},
    },
    {
        "name": "exchange",
        "type": "nested",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "host",
        "type": "nested",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "processes",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "trading",
        "type": "nested",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "participants",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "books",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "gateways",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "thresholds",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "Breaches active now; empty when all is well.",
    },
)


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    """pm-monitor to the dashboard bridge, once a second: everything the dashboard
    shows live, already derived. Rates, averages, health states and thresholds are
    computed once here, so every browser shows the same figures and none re-
    derives them.

    PUB on monitor.pub_port (default 5611). About 120 KB at 112 participants and 300
    symbols (the AI-trader simulation), most of it the participants and books blocks;
    pm-engine's own per-participant and per-symbol samples are left out of its process
    record. A bridge that has seen no snapshot for 3 s reports pm-monitor as down.
    """

    ts: str
    seq: int  # unit: dimensionless
    exchange: ExchangeStatus
    host: HostStats
    processes: list[ProcessHealth]
    trading: TradingStats
    participants: list[ParticipantStats]
    books: list[BookStats]
    gateways: list[GatewayStats]
    thresholds: list[ActiveBreach]

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.ts) > 32:
            raise MessageValidationError(
                f"ts: length {len(self.ts)} exceeds max_len 32"
            )
        if self.seq < 0:
            raise MessageValidationError(f"seq: {self.seq!r} must be >= 0")
        self.exchange.validate()
        self.host.validate()
        for processes_item in self.processes:
            processes_item.validate()
        self.trading.validate()
        for participants_item in self.participants:
            participants_item.validate()
        for books_item in self.books:
            books_item.validate()
        for gateways_item in self.gateways:
            gateways_item.validate()
        for thresholds_item in self.thresholds:
            thresholds_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "HealthSnapshot":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            ts=str(p["ts"]),
            seq=int(p["seq"]),
            exchange=ExchangeStatus.from_dict(p["exchange"]),
            host=HostStats.from_dict(p["host"]),
            processes=[ProcessHealth.from_dict(item) for item in p["processes"]],
            trading=TradingStats.from_dict(p["trading"]),
            participants=(
                [ParticipantStats.from_dict(item) for item in p["participants"]]
            ),
            books=[BookStats.from_dict(item) for item in p["books"]],
            gateways=[GatewayStats.from_dict(item) for item in p["gateways"]],
            thresholds=[ActiveBreach.from_dict(item) for item in p["thresholds"]],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "ts": self.ts,
            "seq": self.seq,
            "exchange": self.exchange.to_dict(),
            "host": self.host.to_dict(),
            "processes": [item.to_dict() for item in self.processes],
            "trading": self.trading.to_dict(),
            "participants": [item.to_dict() for item in self.participants],
            "books": [item.to_dict() for item in self.books],
            "gateways": [item.to_dict() for item in self.gateways],
            "thresholds": [item.to_dict() for item in self.thresholds],
        }


def is_health_snapshot(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_HEALTH_SNAPSHOT


def make_health_snapshot(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = HealthSnapshot.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_HEALTH_SNAPSHOT, obj.to_dict())


def parse_health_snapshot(frames: list[bytes]) -> "HealthSnapshot":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = HealthSnapshot.from_dict(payload)
    obj.validate()
    return obj


def describe_health_snapshot() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _HEALTH_SNAPSHOT_FIELDS


TOPIC_HEALTH_EVENT = "health.event"
_TOPIC_HEALTH_EVENT_BYTES = "health.event".encode()
_HEALTH_EVENT_KIND_VALUES = (
    "CONNECT",
    "AUTH_REJECT",
    "DISCONNECT",
    "DIAGNOSTIC",
    "SESSION",
    "HALT",
    "RESUME",
    "PROCESS_STATUS",
    "THRESHOLD",
)
HealthEventKind = Literal[
    "CONNECT",
    "AUTH_REJECT",
    "DISCONNECT",
    "DIAGNOSTIC",
    "SESSION",
    "HALT",
    "RESUME",
    "PROCESS_STATUS",
    "THRESHOLD",
]
_HEALTH_EVENT_SEVERITY_VALUES = ("INFO", "WARN", "CRIT")
HealthEventSeverity = Literal["INFO", "WARN", "CRIT"]


_HEALTH_EVENT_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "seq",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "The metrics.db events.seq of this event.",
        "constraints": {"ge": 0},
    },
    {
        "name": "ts",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "ISO-8601 UTC with milliseconds.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "kind",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "",
        "values": _HEALTH_EVENT_KIND_VALUES,
    },
    {
        "name": "severity",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "How the dashboard colours it; a heartbeat_timeout disconnect is WARN.",
        "values": _HEALTH_EVENT_SEVERITY_VALUES,
    },
    {
        "name": "subject",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "A gateway id, a process key, a symbol, or a threshold rule.",
        "constraints": {"max_len": 200},
    },
    {
        "name": "detail",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "e.g. `heartbeat_timeout`, `HEALTHY -> HUNG`, `CONTINUOUS -> CLOSING_AUCTION`.",
        "constraints": {"max_len": 512},
    },
)


@dataclass(frozen=True, slots=True)
class HealthEvent:
    """pm-monitor to the dashboard bridge, as it happens: an engine lifecycle event
    (connect, disconnect, diagnostic, session transition, halt) or one pm-monitor
    generated itself (a process changed health state, a threshold was breached or
    cleared). These are the dashboard's annotations and its event log, and the
    rows of metrics.db `events`.
    """

    seq: int  # unit: dimensionless
    ts: str
    kind: HealthEventKind
    severity: HealthEventSeverity
    subject: str
    detail: str = ""

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.seq < 0:
            raise MessageValidationError(f"seq: {self.seq!r} must be >= 0")
        if len(self.ts) > 32:
            raise MessageValidationError(
                f"ts: length {len(self.ts)} exceeds max_len 32"
            )
        if self.kind not in _HEALTH_EVENT_KIND_VALUES:
            raise MessageValidationError(
                f"kind: {self.kind!r} is not one of {_HEALTH_EVENT_KIND_VALUES!r}"
            )
        if self.severity not in _HEALTH_EVENT_SEVERITY_VALUES:
            raise MessageValidationError(
                f"severity: {self.severity!r} is not one of {_HEALTH_EVENT_SEVERITY_VALUES!r}"
            )
        if len(self.subject) > 200:
            raise MessageValidationError(
                f"subject: length {len(self.subject)} exceeds max_len 200"
            )
        if len(self.detail) > 512:
            raise MessageValidationError(
                f"detail: length {len(self.detail)} exceeds max_len 512"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "HealthEvent":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            seq=int(p["seq"]),
            ts=str(p["ts"]),
            kind=cast(HealthEventKind, str(p["kind"])),
            severity=cast(HealthEventSeverity, str(p["severity"])),
            subject=str(p["subject"]),
            detail=str(p.get("detail", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "seq": self.seq,
            "ts": self.ts,
            "kind": self.kind,
            "severity": self.severity,
            "subject": self.subject,
            "detail": self.detail,
        }


def is_health_event(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_HEALTH_EVENT


def make_health_event(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = HealthEvent.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_HEALTH_EVENT, obj.to_dict())


def make_health_event_unchecked(
    *,
    seq: int,
    ts: str,
    kind: HealthEventKind,
    severity: HealthEventSeverity,
    subject: str,
    detail: str = "",
) -> list[bytes]:
    """Identical frames to ``make_health_event``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_HEALTH_EVENT_BYTES,
        _msg.dumps(
            {
                "seq": int(seq),
                "ts": str(ts),
                "kind": str(kind),
                "severity": str(severity),
                "subject": str(subject),
                "detail": str(detail),
            }
        ),
    ]


def parse_health_event(frames: list[bytes]) -> "HealthEvent":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = HealthEvent.from_dict(payload)
    obj.validate()
    return obj


def describe_health_event() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _HEALTH_EVENT_FIELDS


FAMILY_TOPICS: tuple[str, ...] = (
    TOPIC_HEALTH_BEACON,
    TOPIC_HEALTH_SNAPSHOT,
    TOPIC_HEALTH_EVENT,
)

# GENERATED FROM spec/messages/health.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""REST body models for the ``health`` message family.

Family version 1. Derived from ``spec/messages/health.yaml`` by the rest emitter; edit
the spec, not this file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MetricSampleKind = Literal["COUNTER", "GAUGE"]
ExchangeStatusStatus = Literal["OPERATIONAL", "DEGRADED", "IMPAIRED", "DOWN"]
ProcessHealthGroup = Literal["EXCHANGE", "BOT"]
ProcessHealthState = Literal[
    "HEALTHY",
    "DEGRADED",
    "HUNG",
    "SILENT",
    "DEAD",
    "MISSING",
    "STOPPED",
]
GatewayStatsKind = Literal["ALF", "BALF", "MD", "RALF", "DC", "API", "LOG"]
ActiveBreachLevel = Literal["WARN", "CRIT"]
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
HealthEventSeverity = Literal["INFO", "WARN", "CRIT"]


class MetricSample(BaseModel):
    """One application metric of a process at the time of its beacon. A list entry
    rather than a map value, so the dimension (`label`) is a field and a metric
    with no dimension simply carries the empty label.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    name: str = Field(min_length=1, max_length=64)
    """Dotted name, `<family>.<metric>`, e.g. `engine.orders_in`."""
    kind: MetricSampleKind
    """A COUNTER is monotonic since process start; a GAUGE is a level."""
    label: str = Field(max_length=32)
    """The single dimension: a gateway id, a symbol, a component, a reason. Bounded
    by configuration or by a closed set in code, never by what a client sends.
    """
    value: float


class FileSize(BaseModel):
    """The size of one data file pm-monitor watches under the data directory."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    name: str = Field(max_length=32)
    """Logical file name, e.g. `log.db`, `audit`, `metrics.db`."""
    size_bytes: int = Field(ge=0)
    """0 when the file does not exist. Unit: bytes."""


class ExchangeStatus(BaseModel):
    """The one-line answer to "is the exchange OK?" (design section 10)."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    status: ExchangeStatusStatus
    """DOWN when no pm-engine is running: it is DEAD, SILENT, HUNG, MISSING or
    STOPPED, or pm-monitor has never heard of one. IMPAIRED when any other
    expected exchange process is DEAD, SILENT, HUNG or MISSING (or STOPPED while
    the active emo profile expects it). DEGRADED when any exchange process is
    DEGRADED. Otherwise OPERATIONAL. Participant bots never count.
    """
    session_state: str = Field(max_length=32)
    """The engine's session state name; empty before the engine reports one."""
    trading_date: str = Field(max_length=10)
    """YYYY-MM-DD in the session timezone; what "today" means below."""
    session_timezone: str = Field(max_length=64)
    """IANA name from engine.locale.session_timezone."""


class HostStats(BaseModel):
    """The host pm-monitor runs on (design section 8.1)."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    cpu_pct: float = Field(ge=0)
    """Unit: percent."""
    cpu_per_core: list[float]
    """Percent per logical CPU, in psutil order."""
    load1: float
    load5: float
    load15: float
    mem_total_bytes: int = Field(ge=0)
    """Unit: bytes."""
    mem_used_bytes: int = Field(ge=0)
    """Unit: bytes."""
    mem_available_bytes: int = Field(ge=0)
    """Unit: bytes."""
    swap_used_bytes: int = Field(ge=0)
    """Unit: bytes."""
    disk_free_bytes: int = Field(ge=0)
    """On the filesystem holding the data directory. Unit: bytes."""
    disk_total_bytes: int = Field(ge=0)
    """Unit: bytes."""
    files: list[FileSize]


class Sparkline(BaseModel):
    """The last samples of a process, oldest first, for inline sparklines."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    rss: list[int] = Field(max_length=60)
    """RSS in bytes, one per beacon."""
    cpu: list[float] = Field(max_length=60)
    """CPU percent of one core, one per beacon."""


class ProcessHealth(BaseModel):
    """One process as pm-monitor sees it: a process that beacons, or one the active
    emo profile expects and that has never beaconed (MISSING, with zero figures
    and an empty host).
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    key: str = Field(min_length=1, max_length=200)
    """`process/instance@host`, or `process@host` without an instance; a MISSING
    process has no host and no `@`. Stable identity for routes and history.
    """
    process: str = Field(max_length=32)
    instance: str | None = Field(max_length=32)
    host: str = Field(max_length=128)
    group: ProcessHealthGroup
    """BOT for participant bots (pm-mm-bot, pm-ai-swarm), which never affect the
    exchange status.
    """
    pid: int = Field(ge=0)
    """0 when the process has never beaconed."""
    state: ProcessHealthState
    """Design section 10; first matching rule wins."""
    restarted_recently: bool
    """boot_id changed within the last 10 minutes."""
    starting: bool
    """The latest beacon said the main loop has not ticked yet. The state stays
    HEALTHY through a start-up grace, so this is what tells a process still
    starting from one that is running.
    """
    uptime_sec: float = Field(ge=0)
    """Unit: duration_seconds."""
    rss_bytes: int = Field(ge=0)
    """Unit: bytes."""
    cpu_pct: float = Field(ge=0)
    """Percent of one core; may exceed 100 for a multi-threaded process. Unit:
    percent.
    """
    threads: int = Field(ge=0)
    fds: int | None
    """null where the OS has no file-descriptor count."""
    loop_age_ms: float = Field(ge=0)
    """Unit: duration_millis."""
    loop_lag_ms: float = Field(ge=0)
    """Unit: duration_millis."""
    last_beacon_age_ms: float = Field(ge=0)
    """Measured with pm-monitor's receive clock. Unit: duration_millis."""
    spark: Sparkline
    metrics: list[MetricSample]
    """The application metrics of the latest beacon, as sent -- except pm-engine's
    labelled samples (one per participant or symbol, thousands at 300 symbols):
    the trading, participants and books blocks carry those derived, and metrics.db
    keeps them. Its unlabelled samples and engine.diagnostics are kept.
    """


class RateStats(BaseModel):
    """A counter turned into the figures of design section 9.4. Every increment is
    reset-corrected, so a process restart neither loses nor double-counts.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    today: int = Field(ge=0)
    """Sum of increments since the start of the trading date."""
    per_sec_now: float = Field(ge=0)
    """Increments over the last 60 s divided by 60."""
    avg_per_min: float = Field(ge=0)
    """Increments over the last 60 min divided by 60."""
    avg_per_hour: float = Field(ge=0)
    """today divided by hours since the session opened (else midnight)."""
    avg_per_day: float | None
    """Mean daily total over the last 7 trading days with data; null before the first
    full day.
    """


class RejectCount(BaseModel):
    """Rejects of one reason today: a RejectCode, or a label the engine gives a
    reject known only by its text (MM_MAX_SPREAD, MM_MIN_QTY, UNKNOWN).
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    code: str = Field(min_length=1, max_length=32)
    count: int = Field(ge=0)


class TradingStats(BaseModel):
    """Exchange-wide trading activity, summed over gateways and symbols."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    orders: RateStats
    """engine.orders_in: inbound new orders, including those then rejected."""
    trades: RateStats
    traded_value_today: float = Field(ge=0)
    """Unit: money."""
    reject_pct_5m: float = Field(ge=0)
    """Rejected acks over inbound requests (new orders, combos, OCOs, cancels,
    amends, quotes) in the last 5 minutes, the same set engine.rejects counts; 0
    when none. Unit: percent.
    """
    handle_p50_us: float = Field(ge=0)
    """engine.handle_us_p50: order-entry messages, sampled 1 in 16, over the last
    minute. Unit: duration_micros.
    """
    handle_p99_us: float = Field(ge=0)
    """engine.handle_us_p99, over the same samples. Unit: duration_micros."""
    handle_p99_ex_gc_us: float = Field(ge=0)
    """engine.handle_us_p99_ex_gc: the same p99 with each sample's garbage-collection
    time taken out. Unit: duration_micros.
    """
    handle_samples: int = Field(ge=0)
    """engine.handle_samples: how many samples the percentiles stand on; below 100
    the p99 is their maximum.
    """
    other_p99_us: float = Field(ge=0)
    """engine.other_us_p99: every message but order entry -- heartbeats, connects,
    queries, admin. Unit: duration_micros.
    """
    gc_pause_max_us: float = Field(ge=0)
    """engine.gc_pause_us_max: the engine's longest garbage collection in the last
    minute, sampled or not. Unit: duration_micros.
    """
    gc_time_pct: float = Field(ge=0)
    """engine.gc_time_pct: share of the engine's last beacon interval spent
    collecting garbage. Unit: percent.
    """
    busy_pct: float = Field(ge=0)
    """Engine share of wall time spent handling; near 100 means saturated. Unit:
    percent.
    """
    rejects_by_code: list[RejectCount]
    """Today's rejects (engine.rejects_by_code) by reason, most first: what makes
    reject_pct_5m actionable.
    """


class ParticipantStats(BaseModel):
    """One configured participant (gateway id) as the engine counts it."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    id: str = Field(max_length=32)
    role: str = Field(max_length=32)
    connected: bool
    connected_since: str | None = Field(max_length=32)
    """ISO-8601 UTC of the current session's connect; null when not connected or not
    seen.
    """
    orders: RateStats
    reject_pct: float = Field(ge=0)
    """Rejected acks over inbound requests today (as TradingStats.reject_pct_5m); 0
    when none. Unit: percent.
    """
    fills_today: int = Field(ge=0)
    resting_orders: int = Field(ge=0)
    connects_today: int = Field(ge=0)
    disconnects_today: int = Field(ge=0)
    heartbeat_timeouts_today: int = Field(ge=0)


class BookStats(BaseModel):
    """One order book (design section 8.3); refreshed every
    book_metrics_interval_sec.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    resting_orders: int = Field(ge=0)
    gtc_orders: int = Field(ge=0)
    """Resting orders with TIF=GTC: the long orders that survive the close. A subset
    of resting_orders.
    """
    stop_orders: int = Field(ge=0)
    bid_levels: int = Field(ge=0)
    ask_levels: int = Field(ge=0)
    est_bytes: int = Field(ge=0)
    """An estimate from measured per-object constants, never an exact figure. Unit:
    bytes.
    """
    heap_garbage_pct: float = Field(ge=0, le=100)
    """Unit: percent."""
    trades_today: int = Field(ge=0)
    halted: bool


class GatewayStats(BaseModel):
    """One process that holds client connections: the ALF, BALF, MD, RALF and drop-
    copy gateways, the API gateway (WebSocket sessions) and pm-log-srv (LALF
    sessions). One shape for all, so row 6 of the dashboard is a loop.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    key: str = Field(min_length=1, max_length=200)
    """The ProcessHealth key of the same process."""
    kind: GatewayStatsKind
    clients: int = Field(ge=0)
    clients_max: int | None
    """The configured connection limit; null where none exists."""
    msgs_per_sec: float = Field(ge=0)
    """Main traffic counter of the kind (commands in, messages out, log events in)
    over the last 60 s.
    """
    disconnects_today: int = Field(ge=0)
    slow_disconnects_today: int = Field(ge=0)
    """Clients cut off for not reading; the back-pressure signal."""


class ActiveBreach(BaseModel):
    """One threshold currently in breach (design section 9.6)."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    rule: str = Field(max_length=64)
    """The configuration key, e.g. `engine_handle_p99_us`."""
    subject: str = Field(max_length=200)
    """What breached: a process key, `host`, a symbol or `exchange`."""
    level: ActiveBreachLevel
    value: float
    threshold: float
    since: str = Field(max_length=32)
    """ISO-8601 UTC of the breach."""


class HealthBeacon(BaseModel):
    """Every long-running pm-* process to pm-monitor, every beacon_interval_sec: the
    process's own memory, CPU, threads and file descriptors, how long ago its main
    loop last completed an iteration, and its application counters and gauges.
    Sent from a daemon thread, not from the main loop. That is the point: when the
    main loop hangs the thread keeps reporting, with a growing loop_age_ms, so pm-
    monitor can tell HUNG (beacons arrive, loop stuck) from SILENT (no beacons,
    PID alive) from DEAD (no beacons, no PID). A beacon built on the main loop
    would simply stop, and silence cannot make that distinction.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    process: str = Field(min_length=1, max_length=32)
    """The name the process uses in its LALF HELLO, e.g. `pm-engine`."""
    instance: str | None = Field(default=None, max_length=32)
    """The --instance name where a process runs more than once, e.g. `desk`."""
    pid: int = Field(gt=0)
    host: str = Field(min_length=1, max_length=128)
    """socket.gethostname()."""
    boot_id: str = Field(min_length=1, max_length=16)
    """Random per process start; a change means a restart even when the PID is
    reused.
    """
    seq: int = Field(ge=0)
    """Per boot_id; a gap means lost beacons."""
    started_at_ns: int = Field(ge=0)
    """Process start, for uptime only; ages use pm-monitor's receive clock. Unit:
    epoch_nanos.
    """
    interval_sec: float = Field(gt=0)
    """The sender's beacon interval; pm-monitor's silence timers scale with it. Unit:
    duration_seconds.
    """
    rss_bytes: int = Field(ge=0)
    """Unit: bytes."""
    cpu_pct: float = Field(ge=0)
    """Percent of one core since the previous beacon. Unit: percent."""
    threads: int = Field(ge=0)
    fds: int | None = Field(default=None, ge=0)
    """Open file descriptors; absent where the OS has no such count."""
    loop_age_ms: float = Field(ge=0)
    """Time since the main loop last called tick(). Unit: duration_millis."""
    loop_lag_ms: float = Field(ge=0)
    """Longest gap between two tick() calls since the previous beacon. Unit:
    duration_millis.
    """
    final: bool
    """True on the last beacon of a clean shutdown: STOPPED, not DEAD."""
    starting: bool
    """True until the main loop has ticked once. The reporter starts before a
    process's loop exists (restoring state, loading config), and that time is not
    a hung loop; loop_age_ms still grows, so a process stuck starting stays
    visible.
    """
    metrics: list[MetricSample]
    """Application metrics (design section 8); may be empty."""


class HealthSnapshot(BaseModel):
    """pm-monitor to the dashboard bridge, once a second: everything the dashboard
    shows live, already derived. Rates, averages, health states and thresholds are
    computed once here, so every browser shows the same figures and none re-
    derives them.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    ts: str = Field(max_length=32)
    """ISO-8601 UTC with milliseconds; pm-monitor's clock."""
    seq: int = Field(ge=0)
    """Per pm-monitor start."""
    exchange: ExchangeStatus
    host: HostStats
    processes: list[ProcessHealth]
    trading: TradingStats
    participants: list[ParticipantStats]
    books: list[BookStats]
    gateways: list[GatewayStats]
    thresholds: list[ActiveBreach]
    """Breaches active now; empty when all is well."""


class HealthEvent(BaseModel):
    """pm-monitor to the dashboard bridge, as it happens: an engine lifecycle event
    (connect, disconnect, diagnostic, session transition, halt) or one pm-monitor
    generated itself (a process changed health state, a threshold was breached or
    cleared). These are the dashboard's annotations and its event log, and the
    rows of metrics.db `events`.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    seq: int = Field(ge=0)
    """The metrics.db events.seq of this event."""
    ts: str = Field(max_length=32)
    """ISO-8601 UTC with milliseconds."""
    kind: HealthEventKind
    severity: HealthEventSeverity
    """How the dashboard colours it; a heartbeat_timeout disconnect is WARN."""
    subject: str = Field(max_length=200)
    """A gateway id, a process key, a symbol, or a threshold rule."""
    detail: str = Field(max_length=512)
    """e.g. `heartbeat_timeout`, `HEALTHY -> HUNG`, `CONTINUOUS -> CLOSING_AUCTION`."""

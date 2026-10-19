/**
 * `health.snapshot` and `health.event` as pm-monitor publishes them
 * (`spec/messages/health.yaml`, design §11.1).
 *
 * The keys are the wire's own snake_case: the bridge passes each payload
 * through unchanged, so there is no mapping layer to drift and nothing is
 * re-derived. tests/test_dash_types_mirror.py fails when a field here and
 * the spec disagree.
 *
 * MAINTENANCE: when spec/messages/health.yaml changes, update this file.
 */

export type ProcessState = "HEALTHY" | "DEGRADED" | "HUNG" | "SILENT" | "DEAD" | "MISSING" | "STOPPED";
export type ExchangeStatusName = "OPERATIONAL" | "DEGRADED" | "IMPAIRED" | "DOWN";
export type ProcessGroup = "EXCHANGE" | "BOT";
export type MetricKind = "COUNTER" | "GAUGE";
export type GatewayKind = "ALF" | "BALF" | "MD" | "RALF" | "DC" | "API" | "LOG";
export type BreachLevel = "WARN" | "CRIT";
export type EventKind =
  | "CONNECT"
  | "AUTH_REJECT"
  | "DISCONNECT"
  | "DIAGNOSTIC"
  | "SESSION"
  | "HALT"
  | "RESUME"
  | "PROCESS_STATUS"
  | "THRESHOLD";
export type EventSeverity = "INFO" | "WARN" | "CRIT";

export interface MetricSample {
  name: string;
  kind: MetricKind;
  label: string;
  value: number;
}

export interface FileSize {
  name: string;
  size_bytes: number;
}

export interface ExchangeStatus {
  status: ExchangeStatusName;
  session_state: string;
  trading_date: string;
  session_timezone: string;
}

export interface HostStats {
  cpu_pct: number;
  cpu_per_core: number[];
  load1: number;
  load5: number;
  load15: number;
  mem_total_bytes: number;
  mem_used_bytes: number;
  mem_available_bytes: number;
  swap_used_bytes: number;
  disk_free_bytes: number;
  disk_total_bytes: number;
  files: FileSize[];
}

export interface Sparkline {
  rss: number[];
  cpu: number[];
}

export interface ProcessHealth {
  key: string;
  process: string;
  instance: string | null;
  host: string;
  group: ProcessGroup;
  pid: number;
  state: ProcessState;
  restarted_recently: boolean;
  starting: boolean;
  uptime_sec: number;
  rss_bytes: number;
  cpu_pct: number;
  threads: number;
  fds: number | null;
  loop_age_ms: number;
  loop_lag_ms: number;
  last_beacon_age_ms: number;
  spark: Sparkline;
  metrics: MetricSample[];
}

export interface RateStats {
  today: number;
  per_sec_now: number;
  avg_per_min: number;
  avg_per_hour: number;
  avg_per_day: number | null;
}

export interface TradingStats {
  orders: RateStats;
  trades: RateStats;
  traded_value_today: number;
  reject_pct_5m: number;
  handle_p50_us: number;
  handle_p99_us: number;
  busy_pct: number;
}

export interface ParticipantStats {
  id: string;
  role: string;
  connected: boolean;
  connected_since: string | null;
  orders: RateStats;
  reject_pct: number;
  fills_today: number;
  resting_orders: number;
  connects_today: number;
  disconnects_today: number;
  heartbeat_timeouts_today: number;
}

export interface BookStats {
  symbol: string;
  resting_orders: number;
  stop_orders: number;
  bid_levels: number;
  ask_levels: number;
  est_bytes: number;
  heap_garbage_pct: number;
  trades_today: number;
  halted: boolean;
}

export interface GatewayStats {
  key: string;
  kind: GatewayKind;
  clients: number;
  clients_max: number | null;
  msgs_per_sec: number;
  disconnects_today: number;
  slow_disconnects_today: number;
}

export interface ActiveBreach {
  rule: string;
  subject: string;
  level: BreachLevel;
  value: number;
  threshold: number;
  since: string;
}

/** `health.snapshot`, once a second. */
export interface HealthSnapshot {
  ts: string;
  seq: number;
  exchange: ExchangeStatus;
  host: HostStats;
  processes: ProcessHealth[];
  trading: TradingStats;
  participants: ParticipantStats[];
  books: BookStats[];
  gateways: GatewayStats[];
  thresholds: ActiveBreach[];
}

/** `health.event`, as it happens; `seq` is its metrics.db `events.seq`. */
export interface HealthEvent {
  seq: number;
  ts: string;
  kind: EventKind;
  severity: EventSeverity;
  subject: string;
  detail: string;
}

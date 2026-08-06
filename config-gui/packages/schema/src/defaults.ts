/**
 * Default constants for the config builder.
 *
 * Mirrors `src/edumatcher/config_gen/defaults.py` field-for-field. Keep the two
 * in sync: the design (§12.4) recommends generating this file from the Python
 * module in CI, but until that pipeline exists these values are transcribed by
 * hand and must be updated whenever `defaults.py` changes.
 */

/** Country used for pm-scheduler's bank-holiday/weekend calendar when unset. */
export const DEFAULT_COUNTRY = "Sweden";

export const DEFAULT_SNAPSHOT_INTERVAL_SEC = 0.5;
export const DEFAULT_QUOTE_HISTORY_MAXLEN = 30;
export const DEFAULT_DROP_COPY_BUFFER_SIZE = 10_000;
export const DEFAULT_RECENT_TRADES_MAXLEN = 20;
export const DEFAULT_DEPTH_SNAPSHOT_TOLERANCE_TICKS = 100;
export const DEFAULT_TICK_DECIMALS = 2;

export const DEFAULT_STATIC_BAND_PCT = 0.2;
export const DEFAULT_DYNAMIC_BAND_PCT = 0.02;

export const DEFAULT_CB_WINDOW_NS = 300_000_000_000;

/** Built-in circuit-breaker ladder: name, price shift %, halt minutes (null = rest of day). */
export const DEFAULT_CB_LADDER: ReadonlyArray<{
  name: string;
  priceShiftPct: number;
  haltMinutes: number | null;
}> = [
  {
    name: "L1",
    priceShiftPct: 0.07,
    haltMinutes: 5,
  },
  {
    name: "L2",
    priceShiftPct: 0.13,
    haltMinutes: 15,
  },
  {
    name: "L3",
    priceShiftPct: 0.2,
    haltMinutes: null,
  },
];

/**
 * Built-in ACE ladder. Nasdaq's published shape (Rule 4120(c)(7)): an initial
 * +/-10% corridor, one 10% widening, then 20% every period. The final rung
 * repeats indefinitely, which is why no maximum-extensions setting exists.
 */
export const DEFAULT_ACE_INITIAL_BAND_PCT = 0.1;
export const DEFAULT_ACE_RANDOM_END_MAX_NS = 30_000_000_000;
export const DEFAULT_ACE_EXPANSIONS: ReadonlyArray<{
  widenPct: number;
  minDurationNs: number;
}> = [
  { widenPct: 0.1, minDurationNs: 120_000_000_000 },
  { widenPct: 0.2, minDurationNs: 300_000_000_000 },
];

export const DEFAULT_MM_SPREAD_TICKS = 20;
export const DEFAULT_MM_MIN_QTY = 100;
export const DEFAULT_MM_STUB_QTY = 1000;

/** Opening two-sided quote width (in ticks) used when seeding an IPO quote. */
export const DEFAULT_OPENING_SPREAD_TICKS = 2;
/** Reasonable default issued-share count suggested at listing (1 billion). */
export const DEFAULT_OUTSTANDING_SHARES = 1_000_000_000;

export const DEFAULT_POST_TRADE_GATEWAY = {
  name: "ralf-gwy01",
  bindAddress: "0.0.0.0",
  port: 5580,
  replayRetentionSec: 86_400,
  heartbeatIntervalSec: 1,
  idleTimeoutSec: 5,
  maxClientQueue: 10_000,
  allowedRoles: ["CLEARING", "DROP_COPY", "AUDIT"] as string[],
} as const;

export const DEFAULT_MARKET_DATA_GATEWAY = {
  enabled: true,
  name: "md-gwy01",
  bindAddress: "0.0.0.0",
  port: 5570,
  heartbeatIntervalSec: 1,
  idleTimeoutSec: 5,
  replayWindowSec: 30,
  maxSymbolsPerClient: 200,
  maxClientQueue: 10_000,
  depthLevels: 10,
} as const;

export const DEFAULT_BALF_GATEWAY = {
  name: "balf-gwy01",
  bindAddress: "0.0.0.0",
  port: 5560,
  heartbeatIntervalSec: 1,
  heartbeatTimeoutSec: 5,
  idleTimeoutSec: 30,
  authTimeoutSec: 10,
  maxConnections: 64,
  maxClientQueue: 10_000,
  maxMessagesPerSecond: 100,
  maxErrorsBeforeDisconnect: 10,
  errorWindowSec: 60,
  duplicateSessionPolicy: "REJECT_NEW" as "REJECT_NEW" | "EVICT_OLD",
} as const;

export const DEFAULT_DC_GATEWAY = {
  name: "dc-gwy01",
  bindAddress: "0.0.0.0",
  port: 5590,
  heartbeatIntervalSec: 5,
  idleTimeoutSec: 30,
  maxClientQueue: 10_000,
} as const;

export const DEFAULT_LOG_SERVER = {
  enabled: true,
  name: "log-srv01",
  bindAddress: "0.0.0.0",
  port: 5600,
  dbPath: "data/log.db",
  retentionDays: 30 as number | null,
  maxMessageBytes: 65_536,
  maxClientQueue: 10_000,
  writeBatchSize: 50,
  writeBatchIntervalMs: 100,
  heartbeatIntervalSec: 5,
  // LALF-PS — pm-log-srv's ZeroMQ log-distribution interface. Mirrors the
  // DEFAULT_LOG_SERVER_* constants in src/edumatcher/config_gen/defaults.py.
  pubsubEnabled: true,
  pubPort: 5601,
  pullPort: 5602,
  leaseSec: 30,
  maxLeaseSec: 300,
  maxSubscribers: 32,
  notifyIntervalMs: 250,
  backfillChunkRows: 500,
  maxBackfillMinutes: 1_440,
  maxBackfillRows: 100_000,
  maxPendingRows: 20_000,
  pubSndhwm: 10_000,
} as const;

export const DEFAULT_API_GATEWAY = {
  name: "default",
  host: "0.0.0.0",
  port: 8080,
  swaggerEnabled: true,
  logLevel: "info" as "debug" | "info" | "warning" | "error",
  statsDb: "data/stats.db",
  generateKeys: true,
  generateReadonlyKey: false,
  rateLimitWritesPerSecond: 10,
  rateLimitBurst: 20,
  engineAuthSec: 3.0,
  engineReplySec: 3.0,
  waitAckSec: 3.0,
  orderRetentionSec: 3600,
} as const;

export const DEFAULT_SCHEDULE = {
  preOpen: "09:00",
  openingAuction: "09:25",
  continuous: "09:30",
  closingAuction: "16:00",
  closingEnd: "16:05",
} as const;

export const DEFAULT_INDEX_BASE_VALUE = 1000.0;
export const DEFAULT_INDEX_PUBLISH_INTERVAL_SEC = 1.0;
export const DEFAULT_INDEX_DATA_DIR = "data/indexes";

export const MAX_INDICES = 5;
export const COMBO_MIN_LEGS = 2;
export const COMBO_MAX_LEGS = 10;

/** Disconnect behaviour derived from a gateway role when the user has not overridden it. */
export function defaultDisconnectBehaviour(
  role: "TRADER" | "MARKET_MAKER" | "ADMIN",
): "CANCEL_ALL" | "CANCEL_QUOTES_ONLY" | "LEAVE_ALL" {
  switch (role) {
    case "MARKET_MAKER":
      return "CANCEL_QUOTES_ONLY";
    case "ADMIN":
      return "LEAVE_ALL";
    case "TRADER":
    default:
      return "CANCEL_ALL";
  }
}

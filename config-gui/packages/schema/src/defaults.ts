/**
 * Default constants for the config builder.
 *
 * Mirrors `src/edumatcher/config_gen/defaults.py` field-for-field. Keep the two
 * in sync: the design (§12.4) recommends generating this file from the Python
 * module in CI, but until that pipeline exists these values are transcribed by
 * hand and must be updated whenever `defaults.py` changes.
 */

export const DEFAULT_SNAPSHOT_INTERVAL_SEC = 0.5;
export const DEFAULT_TICK_DECIMALS = 2;

export const DEFAULT_STATIC_BAND_PCT = 0.2;
export const DEFAULT_DYNAMIC_BAND_PCT = 0.02;

export const DEFAULT_CB_WINDOW_NS = 300_000_000_000;

/** Built-in circuit-breaker ladder: name, price shift %, halt minutes (null = rest of day). */
export const DEFAULT_CB_LADDER: ReadonlyArray<{
  name: string;
  priceShiftPct: number;
  haltMinutes: number | null;
  resumptionMode: "AUCTION" | "CONTINUOUS";
}> = [
  { name: "L1", priceShiftPct: 0.07, haltMinutes: 5, resumptionMode: "AUCTION" },
  { name: "L2", priceShiftPct: 0.13, haltMinutes: 15, resumptionMode: "AUCTION" },
  { name: "L3", priceShiftPct: 0.2, haltMinutes: null, resumptionMode: "AUCTION" },
];

export const DEFAULT_MM_SPREAD_TICKS = 20;
export const DEFAULT_MM_MIN_QTY = 100;
export const DEFAULT_MM_STUB_QTY = 1000;

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

export const DEFAULT_API_GATEWAY = {
  name: "default",
  host: "127.0.0.1",
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

/**
 * Zod schemas mirroring the `EngineConfigDraft` interfaces in `types.ts`.
 *
 * Used by the backend to validate request bodies and by the frontend as the
 * single source of validation truth. Kept structurally identical to the TS
 * interfaces; `z.infer` types are cross-checked against them in tests.
 */

import { z } from "zod";
import {
  API_LOG_LEVELS,
  COMBO_TYPES,
  DISCONNECT_BEHAVIOURS,
  DUPLICATE_SESSION_POLICIES,
  ORDER_TYPES,
  PARTICIPANT_ROLES,
  QUOTE_REFRESH_POLICIES,
  SIDES,
  SMP_ACTIONS,
  TIF_VALUES,
} from "./types.js";

const timeString = z
  .string()
  .regex(/^([01]\d|2[0-3]):[0-5]\d$/, "Expected HH:MM (24-hour)");

export const scheduleSchema = z.object({
  preOpen: timeString,
  openingAuction: timeString,
  continuous: timeString,
  closingAuction: timeString,
  closingEnd: timeString,
});

/**
 * The schedule section as written -- shortcuts and overrides both optional,
 * not resolved. The weekend/sat/sun mutual-exclusion rule (CV20) is a
 * cross-field diagnostic, not a shape check, so it is not enforced here --
 * same split as the indices-count limit (CV10), which also lives only in
 * diagnostics.
 */
export const weeklyScheduleDraftSchema = z.object({
  weekdays: scheduleSchema.optional(),
  mon: scheduleSchema.optional(),
  tue: scheduleSchema.optional(),
  wed: scheduleSchema.optional(),
  thu: scheduleSchema.optional(),
  fri: scheduleSchema.optional(),
  sat: scheduleSchema.optional(),
  sun: scheduleSchema.optional(),
  weekend: scheduleSchema.optional(),
  holidays: scheduleSchema.optional(),
});

export const expansionRungSchema = z.object({
  widenPct: z.number().gt(0).lt(1),
  minDurationNs: z.number().int().positive(),
});

export const reopeningSchema = z.object({
  enabled: z.boolean(),
  initialBandPct: z.number().gt(0).lt(1),
  expansions: z.array(expansionRungSchema).min(1),
  randomEndMaxNs: z.number().int().nonnegative(),
  randomSeed: z.number().int().optional(),
});

export const reopeningOverrideSchema = z.object({
  enabled: z.boolean().optional(),
  initialBandPct: z.number().gt(0).lt(1).optional(),
  randomEndMaxNs: z.number().int().nonnegative().optional(),
});

export const cbLevelSchema = z.object({
  priceShiftPct: z.number().gt(0).lt(1),
  // > 0 or null (rest of day); 0 is rejected by the engine loader.
  haltDurationNs: z.number().int().positive().nullable(),
});

export const mmQuoteStubSchema = z.object({
  gatewayId: z.string(),
  bidPrice: z.number().nullable(),
  askPrice: z.number().nullable(),
  bidQty: z.number().int().positive(),
  askQty: z.number().int().positive(),
  tif: z.enum(TIF_VALUES),
  seedOnce: z.boolean(),
});

export const mmQuoteSeedSchema = z.object({
  gatewayId: z.string(),
  quoteId: z.string().optional(),
  bidPrice: z.number().nullable(),
  askPrice: z.number().nullable(),
  bidQty: z.number().int().positive(),
  askQty: z.number().int().positive(),
  tif: z.enum(TIF_VALUES),
  seedOnce: z.boolean(),
});

export const symbolConfigSchema = z.object({
  tickDecimals: z.number().int().min(0).max(8),
  level: z.string().optional(),
  outstandingShares: z.number().int().positive().optional(),
  lastBuyPrice: z.number().nullable().optional(),
  lastSellPrice: z.number().nullable().optional(),
  collar: z
    .object({
      staticBandPct: z.number().gt(0).lt(1).optional(),
      dynamicBandPct: z.number().gt(0).lt(1).optional(),
    })
    .optional(),
  orderLimits: z
    .object({
      maxOrderQty: z.number().int().positive().optional(),
      maxOrderValue: z.number().positive().optional(),
    })
    .optional(),
  circuitBreaker: z
    .object({
      referenceWindowNs: z.number().int().positive().optional(),
      levels: z.record(z.string(), cbLevelSchema.partial()),
      reopening: reopeningOverrideSchema.optional(),
    })
    .optional(),
  marketMaker: z
    .object({
      enforceMmObligation: z.boolean().optional(),
      mmMaxSpreadTicks: z.number().int().positive().optional(),
      mmMinQty: z.number().int().positive().optional(),
    })
    .optional(),
  marketMakerQuotes: z.array(mmQuoteSeedSchema).optional(),
});

export const gatewayMmObligationOverrideSchema = z.object({
  enforceMmObligation: z.boolean().optional(),
  maxSpreadTicks: z.number().int().positive().optional(),
  minQty: z.number().int().positive().optional(),
});

export const gatewayConfigSchema = z.object({
  id: z.string().min(1),
  role: z.enum(PARTICIPANT_ROLES),
  disconnectBehaviour: z.enum(DISCONNECT_BEHAVIOURS),
  description: z.string().optional(),
  smpAction: z.enum(SMP_ACTIONS),
  quoteRefreshPolicy: z.enum(QUOTE_REFRESH_POLICIES).optional(),
  enforceMmObligation: z.boolean().optional(),
  mmMaxSpreadTicks: z.number().int().positive().optional(),
  mmMinQty: z.number().int().positive().optional(),
  mmObligations: z
    .record(z.string(), gatewayMmObligationOverrideSchema)
    .optional(),
});

export const riskLevelSchema = z.object({
  staticBandPct: z.number().gt(0).lt(1).optional(),
  dynamicBandPct: z.number().gt(0).lt(1).optional(),
});

export const indexConfigSchema = z.object({
  id: z.string().regex(/^[A-Za-z0-9]+$/, "Index id must be alphanumeric"),
  description: z.string().regex(/\S/, "Index description must not be empty"),
  constituents: z.array(z.string()),
  baseValue: z.number().positive(),
  publishIntervalSec: z.number().positive(),
  historyFile: z.string().optional(),
  stateFile: z.string().optional(),
});

export const comboLegSchema = z.object({
  symbol: z.string().min(1),
  side: z.enum(SIDES),
  orderType: z.enum(ORDER_TYPES),
  quantity: z.number().int().positive(),
  price: z.number().nullable().optional(),
  stopPrice: z.number().nullable().optional(),
  smpAction: z.enum(SMP_ACTIONS).optional(),
});

export const comboConfigSchema = z.object({
  comboId: z.string().min(1),
  comboType: z.enum(COMBO_TYPES),
  tif: z.enum(TIF_VALUES),
  legs: z.array(comboLegSchema),
});

// Field law from 990-app-config-spec.md §6: every interval, timeout and
// limit is > 0. `Int` fields are integers; `Secs` fields may be fractional.
const networkBase = {
  include: z.boolean(),
  name: z.string().min(1),
  bindAddress: z.string().min(1),
  port: z.number().int().min(1).max(65535),
  heartbeatIntervalSec: z.number().int().positive(),
  idleTimeoutSec: z.number().int().positive(),
  maxClientQueue: z.number().int().positive(),
};

export const alfGatewayProcSchema = z.object({
  ...networkBase,
  enabled: z.boolean(),
  handshakeTimeoutSec: z.number().int().positive(),
  maxConnections: z.number().int().positive(),
  maxCommandsPerSecond: z.number().int().positive(),
  maxErrorsBeforeDisconnect: z.number().int().positive(),
  errorWindowSec: z.number().int().positive(),
});

export const postTradeGatewaySchema = z.object({
  ...networkBase,
  replayRetentionSec: z.number().int().positive(),
  allowedRoles: z.array(z.string()),
});

export const marketDataGatewaySchema = z.object({
  ...networkBase,
  enabled: z.boolean(),
  replayWindowSec: z.number().int().positive(),
  maxConnections: z.number().int().positive(),
  maxMessagesPerSecond: z.number().int().positive(),
  maxSymbolsPerClient: z.number().int().positive(),
  depthLevels: z.number().int().positive(),
});

export const balfGatewaySchema = z.object({
  ...networkBase,
  enabled: z.boolean(),
  heartbeatIntervalSec: z.number().positive(),
  idleTimeoutSec: z.number().positive(),
  heartbeatTimeoutSec: z.number().positive(),
  authTimeoutSec: z.number().positive(),
  maxConnections: z.number().int().positive(),
  maxMessagesPerSecond: z.number().int().positive(),
  maxErrorsBeforeDisconnect: z.number().int().positive(),
  errorWindowSec: z.number().positive(),
  duplicateSessionPolicy: z.enum(DUPLICATE_SESSION_POLICIES),
});

export const dcGatewaySchema = z.object({
  include: z.boolean(),
  name: z.string().min(1),
  bindAddress: z.string().min(1),
  port: z.number().int().min(1).max(65535),
  heartbeatIntervalSec: z.number().positive(),
  idleTimeoutSec: z.number().positive(),
  maxClientQueue: z.number().int().positive(),
});

// The cross-field port/lease rules (pm-cverifier S102/S103) live in the
// diagnostics package, which reports them only when the section is written.
export const logServerSchema = z.object({
  include: z.boolean(),
  enabled: z.boolean(),
  name: z.string().min(1),
  bindAddress: z.string().min(1),
  port: z.number().int().min(1).max(65535),
  dbPath: z.string().min(1),
  retentionDays: z.number().int().nonnegative().nullable(),
  maxMessageBytes: z.number().int().positive(),
  maxClientQueue: z.number().int().positive(),
  writeBatchSize: z.number().int().positive(),
  writeBatchIntervalMs: z.number().int().positive(),
  heartbeatIntervalSec: z.number().positive(),
  // LALF-PS
  pubsubEnabled: z.boolean(),
  pubPort: z.number().int().min(1).max(65535),
  pullPort: z.number().int().min(1).max(65535),
  leaseSec: z.number().int().positive(),
  maxLeaseSec: z.number().int().positive(),
  maxSubscribers: z.number().int().positive(),
  notifyIntervalMs: z.number().int().positive(),
  backfillChunkRows: z.number().int().positive(),
  maxBackfillMinutes: z.number().int().positive(),
  maxBackfillRows: z.number().int().positive(),
  maxPendingRows: z.number().int().positive(),
  pubSndhwm: z.number().int().positive(),
});

export const apiCredentialSchema = z.object({
  apiKey: z.string().min(1),
  gatewayId: z.string().min(1).nullable(),
  description: z.string().optional(),
});

export const apiGatewaySchema = z.object({
  name: z.string().min(1),
  enabled: z.boolean(),
  host: z.string().min(1),
  port: z.number().int().min(1).max(65535),
  swaggerEnabled: z.boolean(),
  logLevel: z.enum(API_LOG_LEVELS),
  statsDb: z.string().min(1),
  auditDb: z.string().min(1).optional(),
  credentials: z.array(apiCredentialSchema),
  rateLimitWritesPerSecond: z.number().int().positive(),
  rateLimitBurst: z.number().int().positive(),
  engineAuthSec: z.number().positive(),
  engineReplySec: z.number().positive(),
  waitAckSec: z.number().positive(),
  // nonnegative, not positive: 0 is a valid value meaning "never evict".
  orderRetentionSec: z.number().int().nonnegative(),
});

export const engineConfigDraftSchema = z.object({
  sessionsEnabled: z.boolean(),
  requireMmSeedQuotes: z.boolean(),
  country: z.string().min(1),
  emitSchedule: z.boolean(),
  snapshotIntervalSec: z.number().positive(),
  quoteHistoryMaxlen: z.number().int().positive(),
  dropCopyBufferSize: z.number().int().positive(),
  recentTradesMaxlen: z.number().int().positive(),
  depthSnapshotToleranceTicks: z.number().int().positive(),
  enforceCollars: z.boolean(),
  enforceCircuitBreakers: z.boolean(),
  schedule: weeklyScheduleDraftSchema,
  tickDecimals: z.number().int().min(0).max(8),
  symbols: z.record(z.string(), symbolConfigSchema),
  symbolOrder: z.array(z.string()),
  gateways: z.array(gatewayConfigSchema),
  riskControls: z.object({
    globalStaticBandPct: z.number().gt(0).lt(1).optional(),
    globalDynamicBandPct: z.number().gt(0).lt(1).optional(),
    defaultLevel: z.string().optional(),
    levels: z.record(z.string(), riskLevelSchema),
  }),
  circuitBreakerDefaults: z.object({
    include: z.boolean(),
    windowNs: z.number().int().positive(),
    levels: z.record(z.string(), cbLevelSchema),
    levelOrder: z.array(z.string()),
    reopening: reopeningSchema,
  }),
  mmObligationDefaults: z.object({
    enforceMmObligation: z.boolean(),
    mmMaxSpreadTicks: z.number().int().positive(),
    mmMinQty: z.number().int().positive(),
  }),
  seeding: z.object({
    mmMidRange: z.object({ min: z.number(), max: z.number() }).optional(),
    seedLastPricesFromMm: z.boolean(),
    seedLastPrices: z.boolean(),
  }),
  indices: z.array(indexConfigSchema),
  combos: z.array(comboConfigSchema),
  alfGateway: alfGatewayProcSchema,
  postTradeGateway: postTradeGatewaySchema,
  marketDataGateway: marketDataGatewaySchema,
  balfGateway: balfGatewaySchema,
  dcGateway: dcGatewaySchema,
  logServer: logServerSchema,
  apiGateways: z.array(apiGatewaySchema),
  output: z.object({
    filename: z.string().min(1),
    commentDefaultFields: z.boolean(),
  }),
  unmappedYaml: z.record(z.string(), z.unknown()),
});

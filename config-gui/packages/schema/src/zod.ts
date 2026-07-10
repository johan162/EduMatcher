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
  RESUMPTION_MODES,
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

export const cbLevelSchema = z.object({
  priceShiftPct: z.number().gt(0).lt(1),
  haltDurationNs: z.number().int().nonnegative().nullable(),
  resumptionMode: z.enum(RESUMPTION_MODES),
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
  circuitBreaker: z
    .object({
      referenceWindowNs: z.number().int().positive().optional(),
      levels: z.record(z.string(), cbLevelSchema.partial()),
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
  quoteRefreshPolicy: z.enum(QUOTE_REFRESH_POLICIES).optional(),
  enforceMmObligation: z.boolean().optional(),
  mmMaxSpreadTicks: z.number().int().positive().optional(),
  mmMinQty: z.number().int().positive().optional(),
  mmObligations: z.record(z.string(), gatewayMmObligationOverrideSchema).optional(),
});

export const riskLevelSchema = z.object({
  staticBandPct: z.number().gt(0).lt(1),
  dynamicBandPct: z.number().gt(0).lt(1),
});

export const indexConfigSchema = z.object({
  id: z.string().min(1),
  description: z.string().optional(),
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
  smpAction: z.enum(SMP_ACTIONS),
});

export const comboConfigSchema = z.object({
  comboId: z.string().min(1),
  comboType: z.enum(COMBO_TYPES),
  tif: z.enum(TIF_VALUES),
  legs: z.array(comboLegSchema),
});

const networkBase = {
  enabled: z.boolean(),
  name: z.string().min(1),
  bindAddress: z.string().min(1),
  port: z.number().int().min(1).max(65535),
  heartbeatIntervalSec: z.number().nonnegative(),
  idleTimeoutSec: z.number().nonnegative(),
  maxClientQueue: z.number().int().positive(),
};

export const postTradeGatewaySchema = z.object({
  ...networkBase,
  replayRetentionSec: z.number().int().nonnegative(),
  allowedRoles: z.array(z.string()),
});

export const marketDataGatewaySchema = z.object({
  ...networkBase,
  replayWindowSec: z.number().int().nonnegative(),
  maxSymbolsPerClient: z.number().int().positive(),
});

export const balfGatewaySchema = z.object({
  ...networkBase,
  heartbeatTimeoutSec: z.number().nonnegative(),
  authTimeoutSec: z.number().nonnegative(),
  maxConnections: z.number().int().positive(),
  maxMessagesPerSecond: z.number().int().positive(),
  maxErrorsBeforeDisconnect: z.number().int().positive(),
  errorWindowSec: z.number().int().positive(),
  duplicateSessionPolicy: z.enum(DUPLICATE_SESSION_POLICIES),
});

export const apiCredentialSchema = z.object({
  apiKey: z.string(),
  gatewayId: z.string().nullable(),
  description: z.string().optional(),
});

export const apiGatewaySchema = z.object({
  name: z.string().min(1),
  enabled: z.boolean(),
  host: z.string().min(1),
  port: z.number().int().min(1).max(65535),
  swaggerEnabled: z.boolean(),
  logLevel: z.enum(API_LOG_LEVELS),
  statsDb: z.string(),
  gatewayIds: z.array(z.string()),
  generateKeys: z.boolean(),
  generateReadonlyKey: z.boolean(),
  credentials: z.array(apiCredentialSchema),
  rateLimitWritesPerSecond: z.number().int().nonnegative(),
  rateLimitBurst: z.number().int().nonnegative(),
  engineAuthSec: z.number().positive(),
  engineReplySec: z.number().positive(),
  waitAckSec: z.number().positive(),
});

export const engineConfigDraftSchema = z.object({
  sessionsEnabled: z.boolean(),
  emitSchedule: z.boolean(),
  snapshotIntervalSec: z.number().positive(),
  enforceCollars: z.boolean(),
  enforceCircuitBreakers: z.boolean(),
  schedule: scheduleSchema,
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
    enabled: z.boolean(),
    windowNs: z.number().int().positive(),
    levels: z.record(z.string(), cbLevelSchema),
    levelOrder: z.array(z.string()),
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
    randomSeed: z.number().int().optional(),
  }),
  indices: z.array(indexConfigSchema),
  combos: z.array(comboConfigSchema),
  postTradeGateway: postTradeGatewaySchema,
  marketDataGateway: marketDataGatewaySchema,
  balfGateway: balfGatewaySchema,
  apiGateways: z.array(apiGatewaySchema),
  output: z.object({
    filename: z.string().min(1),
    commentDefaultFields: z.boolean(),
  }),
  unmappedYaml: z.record(z.string(), z.unknown()),
});

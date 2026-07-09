/** Factory helpers producing fully-defaulted draft fragments. */

import {
  DEFAULT_API_GATEWAY,
  DEFAULT_BALF_GATEWAY,
  DEFAULT_CB_LADDER,
  DEFAULT_CB_WINDOW_NS,
  DEFAULT_DYNAMIC_BAND_PCT,
  DEFAULT_INDEX_BASE_VALUE,
  DEFAULT_INDEX_PUBLISH_INTERVAL_SEC,
  DEFAULT_MARKET_DATA_GATEWAY,
  DEFAULT_MM_MIN_QTY,
  DEFAULT_MM_SPREAD_TICKS,
  DEFAULT_POST_TRADE_GATEWAY,
  DEFAULT_SCHEDULE,
  DEFAULT_SNAPSHOT_INTERVAL_SEC,
  DEFAULT_STATIC_BAND_PCT,
  DEFAULT_TICK_DECIMALS,
  defaultDisconnectBehaviour,
} from "./defaults.js";
import type {
  ApiGatewayConfig,
  BalfGatewayConfig,
  CbLevel,
  ComboConfig,
  EngineConfigDraft,
  GatewayConfig,
  IndexConfig,
  MarketDataGatewayConfig,
  ParticipantRole,
  PostTradeGatewayConfig,
} from "./types.js";

const MINUTE_NS = 60 * 1_000_000_000;

export function minutesToNs(minutes: number | null): number | null {
  if (minutes === null || minutes === 0) return null;
  return minutes * MINUTE_NS;
}

export function nsToMinutes(ns: number | null): number | null {
  if (ns === null) return null;
  return Math.round(ns / MINUTE_NS);
}

export function defaultCbLevels(): {
  levels: Record<string, CbLevel>;
  levelOrder: string[];
} {
  const levels: Record<string, CbLevel> = {};
  const levelOrder: string[] = [];
  for (const entry of DEFAULT_CB_LADDER) {
    levels[entry.name] = {
      priceShiftPct: entry.priceShiftPct,
      haltDurationNs: minutesToNs(entry.haltMinutes),
      resumptionMode: entry.resumptionMode,
    };
    levelOrder.push(entry.name);
  }
  return { levels, levelOrder };
}

export function createPostTradeGateway(): PostTradeGatewayConfig {
  return {
    enabled: false,
    name: DEFAULT_POST_TRADE_GATEWAY.name,
    bindAddress: DEFAULT_POST_TRADE_GATEWAY.bindAddress,
    port: DEFAULT_POST_TRADE_GATEWAY.port,
    heartbeatIntervalSec: DEFAULT_POST_TRADE_GATEWAY.heartbeatIntervalSec,
    idleTimeoutSec: DEFAULT_POST_TRADE_GATEWAY.idleTimeoutSec,
    maxClientQueue: DEFAULT_POST_TRADE_GATEWAY.maxClientQueue,
    replayRetentionSec: DEFAULT_POST_TRADE_GATEWAY.replayRetentionSec,
    allowedRoles: [...DEFAULT_POST_TRADE_GATEWAY.allowedRoles],
  };
}

export function createMarketDataGateway(): MarketDataGatewayConfig {
  return {
    enabled: false,
    name: DEFAULT_MARKET_DATA_GATEWAY.name,
    bindAddress: DEFAULT_MARKET_DATA_GATEWAY.bindAddress,
    port: DEFAULT_MARKET_DATA_GATEWAY.port,
    heartbeatIntervalSec: DEFAULT_MARKET_DATA_GATEWAY.heartbeatIntervalSec,
    idleTimeoutSec: DEFAULT_MARKET_DATA_GATEWAY.idleTimeoutSec,
    maxClientQueue: DEFAULT_MARKET_DATA_GATEWAY.maxClientQueue,
    replayWindowSec: DEFAULT_MARKET_DATA_GATEWAY.replayWindowSec,
    maxSymbolsPerClient: DEFAULT_MARKET_DATA_GATEWAY.maxSymbolsPerClient,
  };
}

export function createBalfGateway(): BalfGatewayConfig {
  return {
    enabled: false,
    name: DEFAULT_BALF_GATEWAY.name,
    bindAddress: DEFAULT_BALF_GATEWAY.bindAddress,
    port: DEFAULT_BALF_GATEWAY.port,
    heartbeatIntervalSec: DEFAULT_BALF_GATEWAY.heartbeatIntervalSec,
    idleTimeoutSec: DEFAULT_BALF_GATEWAY.idleTimeoutSec,
    maxClientQueue: DEFAULT_BALF_GATEWAY.maxClientQueue,
    heartbeatTimeoutSec: DEFAULT_BALF_GATEWAY.heartbeatTimeoutSec,
    authTimeoutSec: DEFAULT_BALF_GATEWAY.authTimeoutSec,
    maxConnections: DEFAULT_BALF_GATEWAY.maxConnections,
    maxMessagesPerSecond: DEFAULT_BALF_GATEWAY.maxMessagesPerSecond,
    maxErrorsBeforeDisconnect: DEFAULT_BALF_GATEWAY.maxErrorsBeforeDisconnect,
    errorWindowSec: DEFAULT_BALF_GATEWAY.errorWindowSec,
    duplicateSessionPolicy: DEFAULT_BALF_GATEWAY.duplicateSessionPolicy,
  };
}

export function createApiGateway(name: string = DEFAULT_API_GATEWAY.name): ApiGatewayConfig {
  return {
    name,
    enabled: true,
    host: DEFAULT_API_GATEWAY.host,
    port: DEFAULT_API_GATEWAY.port,
    swaggerEnabled: DEFAULT_API_GATEWAY.swaggerEnabled,
    logLevel: DEFAULT_API_GATEWAY.logLevel,
    statsDb: DEFAULT_API_GATEWAY.statsDb,
    gatewayIds: [],
    generateKeys: DEFAULT_API_GATEWAY.generateKeys,
    generateReadonlyKey: DEFAULT_API_GATEWAY.generateReadonlyKey,
    credentials: [],
    rateLimitWritesPerSecond: DEFAULT_API_GATEWAY.rateLimitWritesPerSecond,
    rateLimitBurst: DEFAULT_API_GATEWAY.rateLimitBurst,
    engineAuthSec: DEFAULT_API_GATEWAY.engineAuthSec,
    engineReplySec: DEFAULT_API_GATEWAY.engineReplySec,
    waitAckSec: DEFAULT_API_GATEWAY.waitAckSec,
  };
}

export function createGateway(
  id: string,
  role: ParticipantRole = "TRADER",
): GatewayConfig {
  return { id, role, disconnectBehaviour: defaultDisconnectBehaviour(role) };
}

export function createIndex(id: string): IndexConfig {
  return {
    id,
    description: "",
    constituents: [],
    baseValue: DEFAULT_INDEX_BASE_VALUE,
    publishIntervalSec: DEFAULT_INDEX_PUBLISH_INTERVAL_SEC,
  };
}

export function createCombo(comboId: string): ComboConfig {
  return { comboId, comboType: "AON", tif: "DAY", legs: [] };
}

/** A blank, fully-defaulted draft — the "New" starting point. */
export function createBlankDraft(): EngineConfigDraft {
  const cb = defaultCbLevels();
  return {
    sessionsEnabled: false,
    emitSchedule: true,
    snapshotIntervalSec: DEFAULT_SNAPSHOT_INTERVAL_SEC,
    enforceCollars: true,
    enforceCircuitBreakers: true,
    schedule: {
      preOpen: DEFAULT_SCHEDULE.preOpen,
      openingAuction: DEFAULT_SCHEDULE.openingAuction,
      continuous: DEFAULT_SCHEDULE.continuous,
      closingAuction: DEFAULT_SCHEDULE.closingAuction,
      closingEnd: DEFAULT_SCHEDULE.closingEnd,
    },
    tickDecimals: DEFAULT_TICK_DECIMALS,
    symbols: {},
    symbolOrder: [],
    gateways: [],
    riskControls: {
      globalStaticBandPct: undefined,
      globalDynamicBandPct: undefined,
      defaultLevel: undefined,
      levels: {},
    },
    circuitBreakerDefaults: {
      enabled: true,
      windowNs: DEFAULT_CB_WINDOW_NS,
      levels: cb.levels,
      levelOrder: cb.levelOrder,
    },
    mmObligationDefaults: {
      enforceMmObligation: false,
      mmMaxSpreadTicks: DEFAULT_MM_SPREAD_TICKS,
      mmMinQty: DEFAULT_MM_MIN_QTY,
    },
    seeding: {
      mmMidRange: undefined,
      seedLastPricesFromMm: false,
      seedLastPrices: false,
      randomSeed: undefined,
    },
    indices: [],
    combos: [],
    postTradeGateway: createPostTradeGateway(),
    marketDataGateway: createMarketDataGateway(),
    balfGateway: createBalfGateway(),
    apiGateways: [],
    output: { filename: "engine_config.yaml", commentDefaultFields: false },
    unmappedYaml: {},
  };
}

/** Effective static/dynamic band for the derived DEFAULT collar level. */
export function effectiveDefaultCollar(draft: EngineConfigDraft):
  | { staticBandPct: number; dynamicBandPct: number }
  | undefined {
  const { globalStaticBandPct, globalDynamicBandPct } = draft.riskControls;
  if (globalStaticBandPct === undefined && globalDynamicBandPct === undefined) {
    return undefined;
  }
  return {
    staticBandPct: globalStaticBandPct ?? DEFAULT_STATIC_BAND_PCT,
    dynamicBandPct: globalDynamicBandPct ?? DEFAULT_DYNAMIC_BAND_PCT,
  };
}

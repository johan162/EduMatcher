/**
 * Draft -> plain engine_config document (ordered dict), mirroring
 * `src/edumatcher/config_gen/builder.py`'s `ConfigBuilder.build`.
 *
 * The output object's key insertion order matches builder.py so the renderer's
 * section ordering behaves identically. Values are plain JSON-compatible types.
 *
 * MAINTENANCE: keep aligned with builder.py. Any new engine_config field added
 * to pm-config-gen must be added here (and to the schema/types) too.
 */

import {
  DEFAULT_DYNAMIC_BAND_PCT,
  DEFAULT_INDEX_DATA_DIR,
  DEFAULT_MM_STUB_QTY,
  DEFAULT_STATIC_BAND_PCT,
  effectiveDefaultCollar,
  quoteAroundMidpoint,
  seededMidpoint,
  type EngineConfigDraft,
  type SymbolConfig,
} from "@edumatcher/schema";

export type PlainConfig = Record<string, unknown>;

/** Convert a decimal display price to integer ticks using the given precision. */
export function priceToTicks(price: number, tickDecimals: number): number {
  return Math.round(price * Math.pow(10, tickDecimals));
}

function marketMakerGatewayIds(draft: EngineConfigDraft): string[] {
  return draft.gateways
    .filter((g) => g.role === "MARKET_MAKER")
    .map((g) => g.id);
}

function shouldEmitMmDefaults(draft: EngineConfigDraft): boolean {
  if (marketMakerGatewayIds(draft).length > 0) return true;
  if (draft.mmObligationDefaults.enforceMmObligation) return true;
  return Object.values(draft.symbols).some((s) => s.marketMaker !== undefined);
}

function buildMmDefaults(draft: EngineConfigDraft): PlainConfig {
  const payload: PlainConfig = {
    enforce_mm_obligation: draft.mmObligationDefaults.enforceMmObligation,
    mm_max_spread_ticks: draft.mmObligationDefaults.mmMaxSpreadTicks,
    mm_min_qty: draft.mmObligationDefaults.mmMinQty,
  };
  const symbolOverrides: PlainConfig = {};
  for (const symbol of draft.symbolOrder) {
    const mm = draft.symbols[symbol]?.marketMaker;
    if (!mm) continue;
    if (
      mm.mmMaxSpreadTicks === undefined &&
      mm.mmMinQty === undefined &&
      mm.enforceMmObligation === undefined
    ) {
      continue;
    }
    symbolOverrides[symbol] = {
      enforce_mm_obligation:
        mm.enforceMmObligation ?? draft.mmObligationDefaults.enforceMmObligation,
      mm_max_spread_ticks:
        mm.mmMaxSpreadTicks ?? draft.mmObligationDefaults.mmMaxSpreadTicks,
      mm_min_qty: mm.mmMinQty ?? draft.mmObligationDefaults.mmMinQty,
    };
  }
  if (Object.keys(symbolOverrides).length > 0) {
    payload.symbols = symbolOverrides;
  }
  return payload;
}

function buildRiskControls(draft: EngineConfigDraft): PlainConfig | null {
  const levels: PlainConfig = {};
  let defaultLevel: string | undefined;

  const globalCollar = effectiveDefaultCollar(draft);
  if (globalCollar) {
    levels.DEFAULT = {
      collar: {
        static_band_pct: globalCollar.staticBandPct,
        dynamic_band_pct: globalCollar.dynamicBandPct,
      },
    };
    defaultLevel = draft.riskControls.defaultLevel ?? "DEFAULT";
  }

  for (const [name, level] of Object.entries(draft.riskControls.levels)) {
    levels[name] = {
      collar: {
        static_band_pct: level.staticBandPct,
        dynamic_band_pct: level.dynamicBandPct ?? DEFAULT_DYNAMIC_BAND_PCT,
      },
    };
  }

  if (draft.riskControls.defaultLevel && !defaultLevel) {
    defaultLevel = draft.riskControls.defaultLevel;
  }

  if (Object.keys(levels).length === 0) return null;

  const payload: PlainConfig = { levels };
  if (defaultLevel !== undefined) payload.default_level = defaultLevel;
  return payload;
}

function buildCbDefaults(draft: EngineConfigDraft): PlainConfig {
  const levels: PlainConfig = {};
  for (const name of draft.circuitBreakerDefaults.levelOrder) {
    const level = draft.circuitBreakerDefaults.levels[name];
    if (!level) continue;
    levels[name] = {
      price_shift_pct: level.priceShiftPct,
      halt_duration_ns: level.haltDurationNs,
      resumption_mode: level.resumptionMode,
    };
  }
  return {
    reference_window_ns: draft.circuitBreakerDefaults.windowNs,
    levels,
  };
}

function buildGateways(draft: EngineConfigDraft): PlainConfig[] {
  return draft.gateways.map((gw) => {
    const payload: PlainConfig = {
      id: gw.id,
      role: gw.role,
      disconnect_behaviour: gw.disconnectBehaviour,
    };
    if (gw.description) payload.description = gw.description;
    // quote_refresh_policy only applies to market makers; default preserved.
    if (gw.role === "MARKET_MAKER") {
      payload.quote_refresh_policy = gw.quoteRefreshPolicy ?? "INACTIVATE_ON_ANY_FILL";
    }
    // Per-gateway flat MM obligation overrides — emitted only when explicitly set.
    if (gw.enforceMmObligation !== undefined) {
      payload.enforce_mm_obligation = gw.enforceMmObligation;
    }
    if (gw.mmMaxSpreadTicks !== undefined) payload.mm_max_spread_ticks = gw.mmMaxSpreadTicks;
    if (gw.mmMinQty !== undefined) payload.mm_min_qty = gw.mmMinQty;
    // Per-symbol obligation overrides (nested keys: max_spread_ticks / min_qty).
    if (gw.mmObligations && Object.keys(gw.mmObligations).length > 0) {
      const obligations: PlainConfig = {};
      for (const [symbol, override] of Object.entries(gw.mmObligations)) {
        const entry: PlainConfig = {};
        if (override.enforceMmObligation !== undefined) {
          entry.enforce_mm_obligation = override.enforceMmObligation;
        }
        if (override.maxSpreadTicks !== undefined) entry.max_spread_ticks = override.maxSpreadTicks;
        if (override.minQty !== undefined) entry.min_qty = override.minQty;
        obligations[symbol] = entry;
      }
      payload.mm_obligations = obligations;
    }
    return payload;
  });
}

function buildMmQuoteSeed(
  gatewayId: string,
  tickDecimals: number,
  midpoint: number | null,
): PlainConfig {
  const prices = midpoint === null ? null : quoteAroundMidpoint(midpoint, tickDecimals);
  return {
    gateway_id: gatewayId,
    bid_price: prices?.bidPrice ?? null,
    ask_price: prices?.askPrice ?? null,
    bid_qty: DEFAULT_MM_STUB_QTY,
    ask_qty: DEFAULT_MM_STUB_QTY,
    tif: "DAY",
    seed_once: true,
  };
}

function buildSymbol(
  draft: EngineConfigDraft,
  symbol: string,
  config: SymbolConfig,
  mmGatewayIds: string[],
): PlainConfig {
  const tickDecimals = config.tickDecimals ?? draft.tickDecimals;
  const payload: PlainConfig = { tick_decimals: tickDecimals };

  if (config.level) payload.level = config.level;

  const midpoint = seededMidpoint(draft, draft.tickDecimals);
  // Explicit per-symbol last prices always win over global seeding.
  if (config.lastBuyPrice !== undefined || config.lastSellPrice !== undefined) {
    if (config.lastBuyPrice !== undefined) payload.last_buy_price = config.lastBuyPrice;
    if (config.lastSellPrice !== undefined) payload.last_sell_price = config.lastSellPrice;
  } else if (draft.seeding.seedLastPricesFromMm && midpoint !== null) {
    payload.last_buy_price = midpoint;
    payload.last_sell_price = midpoint;
  } else if (draft.seeding.seedLastPrices) {
    payload.last_buy_price = null;
    payload.last_sell_price = null;
  }

  if (config.collar?.staticBandPct !== undefined || config.collar?.dynamicBandPct !== undefined) {
    const collar: PlainConfig = {};
    if (config.collar.staticBandPct !== undefined) {
      collar.static_band_pct = config.collar.staticBandPct;
    }
    if (config.collar.dynamicBandPct !== undefined) {
      collar.dynamic_band_pct = config.collar.dynamicBandPct;
    }
    payload.collar = collar;
  }

  if (config.circuitBreaker) {
    const hasLevels = Object.keys(config.circuitBreaker.levels).length > 0;
    const hasWindow = config.circuitBreaker.referenceWindowNs !== undefined;
    if (hasLevels || hasWindow) {
      const cb: PlainConfig = {};
      if (hasWindow) cb.reference_window_ns = config.circuitBreaker.referenceWindowNs;
      if (hasLevels) {
        const cbLevels: PlainConfig = {};
        for (const name of Object.keys(config.circuitBreaker.levels).sort()) {
          const lvl = config.circuitBreaker.levels[name];
          if (!lvl) continue;
          const lvlPayload: PlainConfig = {};
          if (lvl.priceShiftPct !== undefined) lvlPayload.price_shift_pct = lvl.priceShiftPct;
          if (lvl.haltDurationNs !== undefined) lvlPayload.halt_duration_ns = lvl.haltDurationNs;
          if (lvl.resumptionMode !== undefined) lvlPayload.resumption_mode = lvl.resumptionMode;
          cbLevels[name] = lvlPayload;
        }
        cb.levels = cbLevels;
      }
      payload.circuit_breaker = cb;
    }
  }

  if (mmGatewayIds.length > 0) {
    // Explicit per-symbol quotes (possibly multiple MMs) take precedence over
    // the auto-generated one-stub-per-MM-gateway fallback.
    if (config.marketMakerQuotes && config.marketMakerQuotes.length > 0) {
      payload.market_maker_quotes = config.marketMakerQuotes.map((q) => {
        const seed: PlainConfig = { gateway_id: q.gatewayId };
        if (q.quoteId) seed.quote_id = q.quoteId;
        seed.bid_price = q.bidPrice;
        seed.ask_price = q.askPrice;
        seed.bid_qty = q.bidQty;
        seed.ask_qty = q.askQty;
        seed.tif = q.tif;
        seed.seed_once = q.seedOnce;
        return seed;
      });
    } else {
      payload.market_maker_quotes = mmGatewayIds.map((gatewayId) =>
        buildMmQuoteSeed(gatewayId, draft.tickDecimals, midpoint),
      );
    }
  }

  if (config.outstandingShares !== undefined) {
    payload.outstanding_shares = config.outstandingShares;
  }

  return payload;
}

function buildSymbols(draft: EngineConfigDraft): PlainConfig {
  const mmGatewayIds = marketMakerGatewayIds(draft);
  const symbols: PlainConfig = {};
  for (const symbol of draft.symbolOrder) {
    const config = draft.symbols[symbol];
    if (!config) continue;
    symbols[symbol] = buildSymbol(draft, symbol, config, mmGatewayIds);
  }
  return symbols;
}

function buildIndices(draft: EngineConfigDraft): PlainConfig[] {
  return draft.indices.map((idx) => ({
    id: idx.id,
    description: idx.description || `Index ${idx.id}`,
    base_value: idx.baseValue,
    publish_interval_sec: idx.publishIntervalSec,
    history_file: idx.historyFile || `${DEFAULT_INDEX_DATA_DIR}/${idx.id}_history.jsonl`,
    state_file: idx.stateFile || `${DEFAULT_INDEX_DATA_DIR}/${idx.id}_state.json`,
    constituents: [...idx.constituents],
  }));
}

function effectiveTickDecimals(draft: EngineConfigDraft, symbol: string): number {
  return draft.symbols[symbol]?.tickDecimals ?? draft.tickDecimals;
}

function buildCombos(draft: EngineConfigDraft): PlainConfig[] {
  return draft.combos.map((combo) => ({
    combo_id: combo.comboId,
    combo_type: combo.comboType,
    tif: combo.tif,
    legs: combo.legs.map((leg) => {
      const td = effectiveTickDecimals(draft, leg.symbol);
      return {
        symbol: leg.symbol,
        side: leg.side,
        order_type: leg.orderType,
        quantity: leg.quantity,
        price: leg.price === null || leg.price === undefined ? null : priceToTicks(leg.price, td),
        stop_price:
          leg.stopPrice === null || leg.stopPrice === undefined
            ? null
            : priceToTicks(leg.stopPrice, td),
        smp_action: leg.smpAction,
      };
    }),
  }));
}

function buildApiGateways(draft: EngineConfigDraft): PlainConfig {
  const payload: PlainConfig = {};
  for (const gw of draft.apiGateways) {
    if (!gw.enabled) continue;
    payload[gw.name] = {
      enabled: gw.enabled,
      host: gw.host,
      port: gw.port,
      swagger_enabled: gw.swaggerEnabled,
      log_level: gw.logLevel,
      stats_db: gw.statsDb,
      credentials: gw.credentials.map((c) => ({
        api_key: c.apiKey,
        gateway_id: c.gatewayId,
        description: c.description ?? "",
      })),
      rate_limit: {
        writes_per_second: gw.rateLimitWritesPerSecond,
        burst: gw.rateLimitBurst,
      },
      timeouts: {
        engine_auth_sec: gw.engineAuthSec,
        engine_reply_sec: gw.engineReplySec,
        wait_ack_sec: gw.waitAckSec,
      },
    };
  }
  return payload;
}

/** Build the ordered engine_config document from a draft. */
export function buildConfigDocument(draft: EngineConfigDraft): PlainConfig {
  const cfg: PlainConfig = {
    sessions_enabled: draft.sessionsEnabled,
    enforce_collars: draft.enforceCollars,
    enforce_circuit_breakers: draft.enforceCircuitBreakers,
    engine_tuning: {
      snapshot_interval_sec: draft.snapshotIntervalSec,
      quote_history_maxlen: draft.quoteHistoryMaxlen,
      drop_copy_buffer_size: draft.dropCopyBufferSize,
      recent_trades_maxlen: draft.recentTradesMaxlen,
      depth_snapshot_tolerance_ticks: draft.depthSnapshotToleranceTicks,
    },
  };

  if (shouldEmitMmDefaults(draft)) {
    cfg.mm_obligation_defaults = buildMmDefaults(draft);
  }

  const riskControls = buildRiskControls(draft);
  if (riskControls !== null) cfg.risk_controls = riskControls;

  if (
    draft.enforceCircuitBreakers &&
    draft.circuitBreakerDefaults.levelOrder.length > 0
  ) {
    cfg.circuit_breaker_defaults = buildCbDefaults(draft);
  }

  cfg.gateways = { alf: buildGateways(draft) };

  if (draft.postTradeGateway.enabled) {
    cfg.post_trade_gateway = buildNetworkGateway(draft, "postTrade");
  }
  if (draft.marketDataGateway.enabled) {
    cfg.market_data_gateway = buildNetworkGateway(draft, "marketData");
  }
  if (draft.balfGateway.enabled) {
    cfg.balf_gateway = buildNetworkGateway(draft, "balf");
  }
  const apiGateways = buildApiGateways(draft);
  if (Object.keys(apiGateways).length > 0) cfg.api_gateways = apiGateways;

  cfg.symbols = buildSymbols(draft);

  if (draft.combos.length > 0) cfg.market_maker_combos = buildCombos(draft);
  if (draft.indices.length > 0) cfg.indices = buildIndices(draft);

  if (draft.sessionsEnabled && draft.emitSchedule) {
    cfg.schedule = {
      pre_open: draft.schedule.preOpen,
      opening_auction_start: draft.schedule.openingAuction,
      continuous_start: draft.schedule.continuous,
      closing_auction_start: draft.schedule.closingAuction,
      closing_auction_end: draft.schedule.closingEnd,
    };
  }

  // Re-attach any imported YAML the GUI does not model (design §9).
  for (const [key, value] of Object.entries(draft.unmappedYaml)) {
    if (!(key in cfg)) cfg[key] = value;
  }

  return cfg;
}

function buildNetworkGateway(
  draft: EngineConfigDraft,
  which: "postTrade" | "marketData" | "balf",
): PlainConfig {
  if (which === "postTrade") {
    const g = draft.postTradeGateway;
    return {
      name: g.name,
      bind_address: g.bindAddress,
      port: g.port,
      replay_retention_sec: g.replayRetentionSec,
      heartbeat_interval_sec: g.heartbeatIntervalSec,
      idle_timeout_sec: g.idleTimeoutSec,
      max_client_queue: g.maxClientQueue,
      allowed_roles: [...g.allowedRoles],
    };
  }
  if (which === "marketData") {
    const g = draft.marketDataGateway;
    return {
      enabled: g.enabled,
      name: g.name,
      bind_address: g.bindAddress,
      port: g.port,
      heartbeat_interval_sec: g.heartbeatIntervalSec,
      idle_timeout_sec: g.idleTimeoutSec,
      replay_window_sec: g.replayWindowSec,
      max_symbols_per_client: g.maxSymbolsPerClient,
      max_client_queue: g.maxClientQueue,
      depth_levels: g.depthLevels,
    };
  }
  const g = draft.balfGateway;
  return {
    name: g.name,
    bind_address: g.bindAddress,
    port: g.port,
    heartbeat_interval_sec: g.heartbeatIntervalSec,
    heartbeat_timeout_sec: g.heartbeatTimeoutSec,
    idle_timeout_sec: g.idleTimeoutSec,
    auth_timeout_sec: g.authTimeoutSec,
    max_connections: g.maxConnections,
    max_client_queue: g.maxClientQueue,
    max_messages_per_second: g.maxMessagesPerSecond,
    max_errors_before_disconnect: g.maxErrorsBeforeDisconnect,
    error_window_sec: g.errorWindowSec,
    duplicate_session_policy: g.duplicateSessionPolicy,
  };
}

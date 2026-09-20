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
  DEFAULT_COUNTRY,
  DEFAULT_INDEX_DATA_DIR,
  effectiveDefaultCollar,
  writtenLastPrices,
  writtenMmQuotes,
  type EngineConfigDraft,
  type SymbolConfig,
} from "@edumatcher/schema";

export type PlainConfig = Record<string, unknown>;

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
        mm.enforceMmObligation ??
        draft.mmObligationDefaults.enforceMmObligation,
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

  // Only the keys the level sets: the engine fills a missing one with its
  // default, and a level with neither carries no collar at all.
  for (const [name, level] of Object.entries(draft.riskControls.levels)) {
    if (
      level.staticBandPct === undefined &&
      level.dynamicBandPct === undefined
    ) {
      levels[name] = {};
      continue;
    }
    const collar: PlainConfig = {};
    if (level.staticBandPct !== undefined)
      collar.static_band_pct = level.staticBandPct;
    if (level.dynamicBandPct !== undefined)
      collar.dynamic_band_pct = level.dynamicBandPct;
    levels[name] = { collar };
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
    };
  }
  const r = draft.circuitBreakerDefaults.reopening;
  const reopening: PlainConfig = {
    enabled: r.enabled,
    initial_band_pct: r.initialBandPct,
    random_end_max_ns: r.randomEndMaxNs,
    expansions: r.expansions.map((rung) => ({
      widen_pct: rung.widenPct,
      min_duration_ns: rung.minDurationNs,
    })),
  };
  // Engine-wide by construction — pm-cverifier rejects it per symbol (S110).
  if (r.randomSeed !== undefined) reopening.random_seed = r.randomSeed;
  const payload: PlainConfig = {
    reference_window_ns: draft.circuitBreakerDefaults.windowNs,
  };
  // An empty ladder is written as no `levels` key: the engine then applies
  // its built-in L1/L2/L3 (writing `levels: {}` would mean the same, but
  // omission is what the spec documents).
  if (Object.keys(levels).length > 0) payload.levels = levels;
  payload.reopening = reopening;
  return payload;
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
      payload.quote_refresh_policy =
        gw.quoteRefreshPolicy ?? "INACTIVATE_ON_ANY_FILL";
    }
    // NONE is the engine default; builder.py omits it too.
    if (gw.smpAction !== "NONE") payload.smp_action = gw.smpAction;
    // Per-gateway flat MM obligation overrides — emitted only when explicitly set.
    if (gw.enforceMmObligation !== undefined) {
      payload.enforce_mm_obligation = gw.enforceMmObligation;
    }
    if (gw.mmMaxSpreadTicks !== undefined)
      payload.mm_max_spread_ticks = gw.mmMaxSpreadTicks;
    if (gw.mmMinQty !== undefined) payload.mm_min_qty = gw.mmMinQty;
    // Per-symbol obligation overrides (nested keys: max_spread_ticks / min_qty).
    if (gw.mmObligations && Object.keys(gw.mmObligations).length > 0) {
      const obligations: PlainConfig = {};
      for (const [symbol, override] of Object.entries(gw.mmObligations)) {
        const entry: PlainConfig = {};
        if (override.enforceMmObligation !== undefined) {
          entry.enforce_mm_obligation = override.enforceMmObligation;
        }
        if (override.maxSpreadTicks !== undefined)
          entry.max_spread_ticks = override.maxSpreadTicks;
        if (override.minQty !== undefined) entry.min_qty = override.minQty;
        obligations[symbol] = entry;
      }
      payload.mm_obligations = obligations;
    }
    return payload;
  });
}

function buildSymbol(
  draft: EngineConfigDraft,
  config: SymbolConfig,
): PlainConfig {
  const payload: PlainConfig = { tick_decimals: config.tickDecimals };

  if (config.level) payload.level = config.level;

  // Shared with the read-only views, so what they show is what is written.
  const lastPrices = writtenLastPrices(draft, config);
  if ("lastBuyPrice" in lastPrices)
    payload.last_buy_price = lastPrices.lastBuyPrice;
  if ("lastSellPrice" in lastPrices)
    payload.last_sell_price = lastPrices.lastSellPrice;

  if (
    config.collar?.staticBandPct !== undefined ||
    config.collar?.dynamicBandPct !== undefined
  ) {
    const collar: PlainConfig = {};
    if (config.collar.staticBandPct !== undefined) {
      collar.static_band_pct = config.collar.staticBandPct;
    }
    if (config.collar.dynamicBandPct !== undefined) {
      collar.dynamic_band_pct = config.collar.dynamicBandPct;
    }
    payload.collar = collar;
  }

  if (
    config.orderLimits?.maxOrderQty !== undefined ||
    config.orderLimits?.maxOrderValue !== undefined
  ) {
    const orderLimits: PlainConfig = {};
    if (config.orderLimits.maxOrderQty !== undefined) {
      orderLimits.max_order_qty = config.orderLimits.maxOrderQty;
    }
    if (config.orderLimits.maxOrderValue !== undefined) {
      orderLimits.max_order_value = config.orderLimits.maxOrderValue;
    }
    payload.order_limits = orderLimits;
  }

  if (config.circuitBreaker) {
    const hasLevels = Object.keys(config.circuitBreaker.levels).length > 0;
    const hasWindow = config.circuitBreaker.referenceWindowNs !== undefined;
    const ro = config.circuitBreaker.reopening;
    const hasReopening = ro !== undefined && Object.keys(ro).length > 0;
    if (hasLevels || hasWindow || hasReopening) {
      const cb: PlainConfig = {};
      if (hasWindow)
        cb.reference_window_ns = config.circuitBreaker.referenceWindowNs;
      if (hasLevels) {
        const cbLevels: PlainConfig = {};
        for (const name of Object.keys(config.circuitBreaker.levels).sort()) {
          const lvl = config.circuitBreaker.levels[name];
          if (!lvl) continue;
          const lvlPayload: PlainConfig = {};
          if (lvl.priceShiftPct !== undefined)
            lvlPayload.price_shift_pct = lvl.priceShiftPct;
          if (lvl.haltDurationNs !== undefined)
            lvlPayload.halt_duration_ns = lvl.haltDurationNs;
          cbLevels[name] = lvlPayload;
        }
        cb.levels = cbLevels;
      }
      if (hasReopening && ro) {
        // Only the keys actually overridden — the engine merges the rest
        // field-by-field from circuit_breaker_defaults.
        const reopening: PlainConfig = {};
        if (ro.enabled !== undefined) reopening.enabled = ro.enabled;
        if (ro.initialBandPct !== undefined)
          reopening.initial_band_pct = ro.initialBandPct;
        if (ro.randomEndMaxNs !== undefined)
          reopening.random_end_max_ns = ro.randomEndMaxNs;
        cb.reopening = reopening;
      }
      payload.circuit_breaker = cb;
    }
  }

  // Explicit per-symbol quotes (possibly multiple MMs) take precedence over
  // the auto-generated one-stub-per-MM-gateway fallback.
  const quotes = writtenMmQuotes(draft, config);
  if (quotes.length > 0) {
    payload.market_maker_quotes = quotes.map((q) => {
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
  }

  if (config.outstandingShares !== undefined) {
    payload.outstanding_shares = config.outstandingShares;
  }

  return payload;
}

function buildSymbols(draft: EngineConfigDraft): PlainConfig {
  const symbols: PlainConfig = {};
  for (const symbol of draft.symbolOrder) {
    const config = draft.symbols[symbol];
    if (!config) continue;
    symbols[symbol] = buildSymbol(draft, config);
  }
  return symbols;
}

function buildIndices(draft: EngineConfigDraft): PlainConfig[] {
  return draft.indices.map((idx) => ({
    id: idx.id,
    // Written as entered; an empty one is a diagnostic, not a made-up name.
    description: idx.description,
    base_value: idx.baseValue,
    publish_interval_sec: idx.publishIntervalSec,
    history_file:
      idx.historyFile || `${DEFAULT_INDEX_DATA_DIR}/${idx.id}_history.jsonl`,
    state_file:
      idx.stateFile || `${DEFAULT_INDEX_DATA_DIR}/${idx.id}_state.json`,
    constituents: [...idx.constituents],
  }));
}

function buildCombos(draft: EngineConfigDraft): PlainConfig[] {
  return draft.combos.map((combo) => ({
    combo_id: combo.comboId,
    combo_type: combo.comboType,
    tif: combo.tif,
    legs: combo.legs.map((leg) => {
      const payload: PlainConfig = {
        symbol: leg.symbol,
        side: leg.side,
        order_type: leg.orderType,
        quantity: leg.quantity,
        price: leg.price ?? null,
        stop_price: leg.stopPrice ?? null,
      };
      // Omitted = the seeding gateway's smp_action; explicit NONE overrides it.
      if (leg.smpAction !== undefined) payload.smp_action = leg.smpAction;
      return payload;
    }),
  }));
}

function buildApiGateways(draft: EngineConfigDraft): PlainConfig {
  const payload: PlainConfig = {};
  // A disabled instance is written with `enabled: false`, not dropped: its
  // settings are still part of the file.
  for (const gw of draft.apiGateways) {
    payload[gw.name] = {
      enabled: gw.enabled,
      host: gw.host,
      port: gw.port,
      swagger_enabled: gw.swaggerEnabled,
      log_level: gw.logLevel,
      stats_db: gw.statsDb,
      ...(gw.auditDb !== undefined ? { audit_db: gw.auditDb } : {}),
      order_retention_sec: gw.orderRetentionSec,
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
    require_mm_seed_quotes: draft.requireMmSeedQuotes,
    engine_tuning: {
      snapshot_interval_sec: draft.snapshotIntervalSec,
      quote_history_maxlen: draft.quoteHistoryMaxlen,
      drop_copy_buffer_size: draft.dropCopyBufferSize,
      recent_trades_maxlen: draft.recentTradesMaxlen,
      depth_snapshot_tolerance_ticks: draft.depthSnapshotToleranceTicks,
    },
  };

  // Mirrors builder.py: only emit country when it differs from the
  // scheduler's own built-in default, so a config left at "Sweden" stays as
  // minimal as pm-config-gen would produce it.
  if (draft.country !== DEFAULT_COUNTRY) {
    cfg.country = draft.country;
  }

  if (shouldEmitMmDefaults(draft)) {
    cfg.mm_obligation_defaults = buildMmDefaults(draft);
  }

  const riskControls = buildRiskControls(draft);
  if (riskControls !== null) cfg.risk_controls = riskControls;

  // Written independently of enforce_circuit_breakers: switching enforcement
  // off must not delete the ladder from the file.
  if (draft.circuitBreakerDefaults.include) {
    cfg.circuit_breaker_defaults = buildCbDefaults(draft);
  }

  cfg.gateways = { alf: buildGateways(draft) };

  if (draft.alfGateway.include) {
    cfg.alf_gateway = buildNetworkGateway(draft, "alf");
  }
  if (draft.postTradeGateway.include) {
    cfg.post_trade_gateway = buildNetworkGateway(draft, "postTrade");
  }
  if (draft.marketDataGateway.include) {
    cfg.market_data_gateway = buildNetworkGateway(draft, "marketData");
  }
  if (draft.balfGateway.include) {
    cfg.balf_gateway = buildNetworkGateway(draft, "balf");
  }
  if (draft.dcGateway.include) {
    cfg.dc_gateway = buildNetworkGateway(draft, "dc");
  }
  if (draft.logServer.include) {
    cfg.log_server = buildLogServer(draft);
  }
  const apiGateways = buildApiGateways(draft);
  if (Object.keys(apiGateways).length > 0) cfg.api_gateways = apiGateways;

  cfg.symbols = buildSymbols(draft);

  if (draft.combos.length > 0) cfg.market_maker_combos = buildCombos(draft);
  if (draft.indices.length > 0) cfg.indices = buildIndices(draft);

  // pm-scheduler reads `schedule` whatever sessions_enabled says, so the
  // block is written whenever it is switched on (an imported one included).
  if (draft.emitSchedule) {
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
  which: "alf" | "postTrade" | "marketData" | "balf" | "dc",
): PlainConfig {
  if (which === "alf") {
    const g = draft.alfGateway;
    return {
      enabled: g.enabled,
      name: g.name,
      bind_address: g.bindAddress,
      port: g.port,
      heartbeat_interval_sec: g.heartbeatIntervalSec,
      handshake_timeout_sec: g.handshakeTimeoutSec,
      idle_timeout_sec: g.idleTimeoutSec,
      max_connections: g.maxConnections,
      max_client_queue: g.maxClientQueue,
      max_commands_per_second: g.maxCommandsPerSecond,
      max_errors_before_disconnect: g.maxErrorsBeforeDisconnect,
      error_window_sec: g.errorWindowSec,
    };
  }
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
      max_connections: g.maxConnections,
      max_messages_per_second: g.maxMessagesPerSecond,
      max_symbols_per_client: g.maxSymbolsPerClient,
      max_client_queue: g.maxClientQueue,
      depth_levels: g.depthLevels,
    };
  }
  if (which === "balf") {
    const g = draft.balfGateway;
    return {
      enabled: g.enabled,
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
  // which === "dc"
  const dc = draft.dcGateway;
  return {
    name: dc.name,
    bind_address: dc.bindAddress,
    port: dc.port,
    heartbeat_interval_sec: dc.heartbeatIntervalSec,
    idle_timeout_sec: dc.idleTimeoutSec,
    max_client_queue: dc.maxClientQueue,
  };
}

/**
 * Build the `log_server` block for `pm-log-srv`. Kept separate from
 * `buildNetworkGateway` since its field set (db_path, retention_days,
 * write-batching knobs) doesn't fit that helper's shape, and — like
 * market_data_gateway — it emits an explicit `enabled` key rather than
 * relying on bare block presence (mirrors `LogServerSpec` in
 * `src/edumatcher/config_gen/builder.py`).
 */
function buildLogServer(draft: EngineConfigDraft): PlainConfig {
  const g = draft.logServer;
  return {
    enabled: g.enabled,
    name: g.name,
    bind_address: g.bindAddress,
    port: g.port,
    db_path: g.dbPath,
    retention_days: g.retentionDays,
    max_message_bytes: g.maxMessageBytes,
    max_client_queue: g.maxClientQueue,
    write_batch_size: g.writeBatchSize,
    write_batch_interval_ms: g.writeBatchIntervalMs,
    heartbeat_interval_sec: g.heartbeatIntervalSec,
    // LALF-PS. Emitted unconditionally, including when pubsub_enabled is
    // false: the loader defaults every one of these, so writing them out
    // only when the interface is on would mean a user who disables it then
    // re-enables it silently loses whatever ports and limits they had set.
    pubsub_enabled: g.pubsubEnabled,
    pub_port: g.pubPort,
    pull_port: g.pullPort,
    lease_sec: g.leaseSec,
    max_lease_sec: g.maxLeaseSec,
    max_subscribers: g.maxSubscribers,
    notify_interval_ms: g.notifyIntervalMs,
    backfill_chunk_rows: g.backfillChunkRows,
    max_backfill_minutes: g.maxBackfillMinutes,
    max_backfill_rows: g.maxBackfillRows,
    max_pending_rows: g.maxPendingRows,
    pub_sndhwm: g.pubSndhwm,
  };
}

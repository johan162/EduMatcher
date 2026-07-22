/**
 * Parse an existing engine_config.yaml into an EngineConfigDraft (design §9).
 *
 * This is a direct YAML -> object mapping. Any top-level section the GUI does
 * not model is preserved in `draft.unmappedYaml` and re-attached on export so
 * imports round-trip without data loss.
 */

import yaml from "js-yaml";
import {
  createBlankDraft,
  createGateway,
  DEFAULT_MM_STUB_QTY,
  type ApiGatewayConfig,
  type CbLevel,
  type ComboConfig,
  type EngineConfigDraft,
  type GatewayConfig,
  type GatewayMmObligationOverride,
  type IndexConfig,
  type MmQuoteSeed,
  type ParticipantRole,
  type QuoteRefreshPolicy,
  type ResumptionMode,
  type RiskLevel,
  type SymbolConfig,
  type Tif,
} from "@edumatcher/schema";

const KNOWN_TOP_LEVEL_KEYS = new Set([
  "sessions_enabled",
  "enforce_collars",
  "enforce_circuit_breakers",
  "engine_tuning",
  "snapshot_interval_sec",
  "mm_obligation_defaults",
  "risk_controls",
  "circuit_breaker_defaults",
  "gateways",
  "post_trade_gateway",
  "market_data_gateway",
  "balf_gateway",
  "api_gateways",
  "symbols",
  "market_maker_combos",
  "indices",
  "schedule",
]);

type Dict = Record<string, unknown>;

const isDict = (v: unknown): v is Dict =>
  typeof v === "object" && v !== null && !Array.isArray(v);

const asNumber = (v: unknown): number | undefined =>
  typeof v === "number" ? v : undefined;

const asBool = (v: unknown, fallback: boolean): boolean =>
  typeof v === "boolean" ? v : fallback;

const asString = (v: unknown): string | undefined =>
  typeof v === "string" ? v : undefined;

export interface ImportResult {
  draft: EngineConfigDraft;
  /** Top-level section names preserved as unmapped passthrough. */
  unmapped: string[];
}

export function parseYamlToDraft(text: string): ImportResult {
  const raw = yaml.load(text, { json: true });
  if (!isDict(raw)) {
    throw new Error("Config root must be a YAML mapping.");
  }

  const draft = createBlankDraft();
  const unmapped: string[] = [];

  draft.sessionsEnabled = asBool(raw.sessions_enabled, draft.sessionsEnabled);
  draft.enforceCollars = asBool(raw.enforce_collars, draft.enforceCollars);
  draft.enforceCircuitBreakers = asBool(
    raw.enforce_circuit_breakers,
    draft.enforceCircuitBreakers,
  );
  const engineTuning = isDict(raw.engine_tuning) ? raw.engine_tuning : undefined;
  draft.snapshotIntervalSec =
    asNumber(engineTuning?.snapshot_interval_sec) ??
    asNumber(raw.snapshot_interval_sec) ??
    draft.snapshotIntervalSec;
  draft.quoteHistoryMaxlen =
    asNumber(engineTuning?.quote_history_maxlen) ?? draft.quoteHistoryMaxlen;
  draft.dropCopyBufferSize =
    asNumber(engineTuning?.drop_copy_buffer_size) ?? draft.dropCopyBufferSize;
  draft.recentTradesMaxlen =
    asNumber(engineTuning?.recent_trades_maxlen) ?? draft.recentTradesMaxlen;
  draft.depthSnapshotToleranceTicks =
    asNumber(engineTuning?.depth_snapshot_tolerance_ticks) ??
    draft.depthSnapshotToleranceTicks;

  parseGateways(raw.gateways, draft);
  parseSymbols(raw.symbols, draft);
  parseMmDefaults(raw.mm_obligation_defaults, draft);
  parseRiskControls(raw.risk_controls, draft);
  parseCircuitBreakerDefaults(raw.circuit_breaker_defaults, draft);
  parseNetworkGateways(raw, draft);
  parseApiGateways(raw.api_gateways, draft);
  parseIndices(raw.indices, draft);
  parseCombos(raw.market_maker_combos, draft);
  parseSchedule(raw.schedule, draft);

  for (const [key, value] of Object.entries(raw)) {
    if (!KNOWN_TOP_LEVEL_KEYS.has(key)) {
      draft.unmappedYaml[key] = value;
      unmapped.push(key);
    }
  }

  return { draft, unmapped };
}

function parseGateways(node: unknown, draft: EngineConfigDraft): void {
  if (!isDict(node) || !Array.isArray(node.alf)) return;
  const gateways: GatewayConfig[] = [];
  for (const entry of node.alf) {
    if (!isDict(entry)) continue;
    const id = asString(entry.id);
    if (!id) continue;
    const role = (asString(entry.role) as ParticipantRole) ?? "TRADER";
    const base = createGateway(id, role);
    // P3.9: when disconnect_behaviour is omitted, reflect the engine loader's
    // real default (CANCEL_QUOTES_ONLY for every role) rather than the
    // role-derived value createGateway() uses for freshly authored gateways.
    // This keeps import -> re-export faithful to what the engine would have done
    // with the original omitted field.
    const disconnect = asString(entry.disconnect_behaviour);
    base.disconnectBehaviour = disconnect
      ? (disconnect as GatewayConfig["disconnectBehaviour"])
      : "CANCEL_QUOTES_ONLY";
    const description = asString(entry.description);
    if (description) base.description = description;
    const refresh = asString(entry.quote_refresh_policy);
    if (refresh) base.quoteRefreshPolicy = refresh as QuoteRefreshPolicy;

    // Per-gateway flat MM obligation overrides.
    if (typeof entry.enforce_mm_obligation === "boolean") {
      base.enforceMmObligation = entry.enforce_mm_obligation;
    }
    const maxSpread = asNumber(entry.mm_max_spread_ticks);
    if (maxSpread !== undefined) base.mmMaxSpreadTicks = maxSpread;
    const minQty = asNumber(entry.mm_min_qty);
    if (minQty !== undefined) base.mmMinQty = minQty;

    // Per-symbol obligation overrides (nested keys: max_spread_ticks / min_qty).
    if (isDict(entry.mm_obligations)) {
      const obligations: Record<string, GatewayMmObligationOverride> = {};
      for (const [sym, override] of Object.entries(entry.mm_obligations)) {
        if (!isDict(override)) continue;
        const parsed: GatewayMmObligationOverride = {};
        if (typeof override.enforce_mm_obligation === "boolean") {
          parsed.enforceMmObligation = override.enforce_mm_obligation;
        }
        const oms = asNumber(override.max_spread_ticks);
        if (oms !== undefined) parsed.maxSpreadTicks = oms;
        const omq = asNumber(override.min_qty);
        if (omq !== undefined) parsed.minQty = omq;
        obligations[sym.toUpperCase()] = parsed;
      }
      if (Object.keys(obligations).length > 0) base.mmObligations = obligations;
    }
    gateways.push(base);
  }
  draft.gateways = gateways;
}

function parseSymbols(node: unknown, draft: EngineConfigDraft): void {
  if (!isDict(node)) return;
  const symbols: Record<string, SymbolConfig> = {};
  const order: string[] = [];
  for (const [symbol, value] of Object.entries(node)) {
    if (!isDict(value)) continue;
    const config: SymbolConfig = {
      tickDecimals: asNumber(value.tick_decimals) ?? draft.tickDecimals,
    };
    const level = asString(value.level);
    if (level) config.level = level;
    const outstanding = asNumber(value.outstanding_shares);
    if (outstanding !== undefined) config.outstandingShares = outstanding;
    if ("last_buy_price" in value) config.lastBuyPrice = asNumber(value.last_buy_price) ?? null;
    if ("last_sell_price" in value) config.lastSellPrice = asNumber(value.last_sell_price) ?? null;
    if (isDict(value.collar)) {
      config.collar = {
        staticBandPct: asNumber(value.collar.static_band_pct),
        dynamicBandPct: asNumber(value.collar.dynamic_band_pct),
      };
    }
    if (isDict(value.circuit_breaker)) {
      const cbRaw = value.circuit_breaker;
      const levels: Record<string, Partial<CbLevel>> = {};
      if (isDict(cbRaw.levels)) {
        for (const [name, lvl] of Object.entries(cbRaw.levels)) {
          if (!isDict(lvl)) continue;
          const partial: Partial<CbLevel> = {};
          const shift = asNumber(lvl.price_shift_pct);
          if (shift !== undefined) partial.priceShiftPct = shift;
          if ("halt_duration_ns" in lvl) partial.haltDurationNs = asNumber(lvl.halt_duration_ns) ?? null;
          const mode = asString(lvl.resumption_mode);
          if (mode) partial.resumptionMode = mode as ResumptionMode;
          levels[name] = partial;
        }
      }
      const windowNs = asNumber(cbRaw.reference_window_ns);
      if (windowNs !== undefined || Object.keys(levels).length > 0) {
        config.circuitBreaker = { levels };
        if (windowNs !== undefined) config.circuitBreaker.referenceWindowNs = windowNs;
      }
    }
    if (Array.isArray(value.market_maker_quotes)) {
      const quotes: MmQuoteSeed[] = [];
      for (const raw of value.market_maker_quotes) {
        if (!isDict(raw)) continue;
        const gatewayId = asString(raw.gateway_id);
        if (!gatewayId) continue;
        const quoteId = asString(raw.quote_id);
        quotes.push({
          gatewayId: gatewayId.toUpperCase(),
          ...(quoteId ? { quoteId } : {}),
          bidPrice: asNumber(raw.bid_price) ?? null,
          askPrice: asNumber(raw.ask_price) ?? null,
          bidQty: asNumber(raw.bid_qty) ?? DEFAULT_MM_STUB_QTY,
          askQty: asNumber(raw.ask_qty) ?? DEFAULT_MM_STUB_QTY,
          tif: (asString(raw.tif) as Tif) ?? "DAY",
          seedOnce: typeof raw.seed_once === "boolean" ? raw.seed_once : true,
        });
      }
      if (quotes.length > 0) config.marketMakerQuotes = quotes;
    }
    symbols[symbol] = config;
    order.push(symbol);
  }
  draft.symbols = symbols;
  draft.symbolOrder = order;
}

function parseMmDefaults(node: unknown, draft: EngineConfigDraft): void {
  if (!isDict(node)) return;
  draft.mmObligationDefaults.enforceMmObligation = asBool(
    node.enforce_mm_obligation,
    draft.mmObligationDefaults.enforceMmObligation,
  );
  draft.mmObligationDefaults.mmMaxSpreadTicks =
    asNumber(node.mm_max_spread_ticks) ?? draft.mmObligationDefaults.mmMaxSpreadTicks;
  draft.mmObligationDefaults.mmMinQty =
    asNumber(node.mm_min_qty) ?? draft.mmObligationDefaults.mmMinQty;

  if (isDict(node.symbols)) {
    for (const [symbol, override] of Object.entries(node.symbols)) {
      if (!isDict(override)) continue;
      const target = draft.symbols[symbol];
      if (!target) continue;
      target.marketMaker = {
        enforceMmObligation:
          typeof override.enforce_mm_obligation === "boolean"
            ? override.enforce_mm_obligation
            : undefined,
        mmMaxSpreadTicks: asNumber(override.mm_max_spread_ticks),
        mmMinQty: asNumber(override.mm_min_qty),
      };
    }
  }
}

function parseRiskControls(node: unknown, draft: EngineConfigDraft): void {
  if (!isDict(node) || !isDict(node.levels)) return;
  const levels: Record<string, RiskLevel> = {};
  for (const [name, value] of Object.entries(node.levels)) {
    if (!isDict(value) || !isDict(value.collar)) continue;
    const staticBandPct = asNumber(value.collar.static_band_pct);
    const dynamicBandPct = asNumber(value.collar.dynamic_band_pct);
    if (name === "DEFAULT") {
      draft.riskControls.globalStaticBandPct = staticBandPct;
      draft.riskControls.globalDynamicBandPct = dynamicBandPct;
      continue;
    }
    levels[name] = {
      staticBandPct: staticBandPct ?? 0.2,
      dynamicBandPct: dynamicBandPct ?? 0.02,
    };
  }
  draft.riskControls.levels = levels;
  const defaultLevel = asString(node.default_level);
  if (defaultLevel) draft.riskControls.defaultLevel = defaultLevel;
}

function parseCircuitBreakerDefaults(node: unknown, draft: EngineConfigDraft): void {
  if (!isDict(node) || !isDict(node.levels)) return;
  draft.circuitBreakerDefaults.enabled = true;
  draft.circuitBreakerDefaults.windowNs =
    asNumber(node.reference_window_ns) ?? draft.circuitBreakerDefaults.windowNs;
  const levels: Record<string, CbLevel> = {};
  const order: string[] = [];
  for (const [name, value] of Object.entries(node.levels)) {
    if (!isDict(value)) continue;
    levels[name] = {
      priceShiftPct: asNumber(value.price_shift_pct) ?? 0.07,
      haltDurationNs: "halt_duration_ns" in value ? (asNumber(value.halt_duration_ns) ?? null) : null,
      resumptionMode: (asString(value.resumption_mode) as ResumptionMode) ?? "AUCTION",
    };
    order.push(name);
  }
  draft.circuitBreakerDefaults.levels = levels;
  draft.circuitBreakerDefaults.levelOrder = order;
}

function parseNetworkGateways(raw: Dict, draft: EngineConfigDraft): void {
  const pt = raw.post_trade_gateway;
  if (isDict(pt)) {
    const g = draft.postTradeGateway;
    g.enabled = true;
    g.name = asString(pt.name) ?? g.name;
    g.bindAddress = asString(pt.bind_address) ?? g.bindAddress;
    g.port = asNumber(pt.port) ?? g.port;
    g.replayRetentionSec = asNumber(pt.replay_retention_sec) ?? g.replayRetentionSec;
    g.heartbeatIntervalSec = asNumber(pt.heartbeat_interval_sec) ?? g.heartbeatIntervalSec;
    g.idleTimeoutSec = asNumber(pt.idle_timeout_sec) ?? g.idleTimeoutSec;
    g.maxClientQueue = asNumber(pt.max_client_queue) ?? g.maxClientQueue;
    if (Array.isArray(pt.allowed_roles)) {
      g.allowedRoles = pt.allowed_roles.filter((r): r is string => typeof r === "string");
    }
  }

  const md = raw.market_data_gateway;
  if (isDict(md)) {
    const g = draft.marketDataGateway;
    g.enabled = asBool(md.enabled, true);
    g.name = asString(md.name) ?? g.name;
    g.bindAddress = asString(md.bind_address) ?? g.bindAddress;
    g.port = asNumber(md.port) ?? g.port;
    g.heartbeatIntervalSec = asNumber(md.heartbeat_interval_sec) ?? g.heartbeatIntervalSec;
    g.idleTimeoutSec = asNumber(md.idle_timeout_sec) ?? g.idleTimeoutSec;
    g.replayWindowSec = asNumber(md.replay_window_sec) ?? g.replayWindowSec;
    g.maxSymbolsPerClient = asNumber(md.max_symbols_per_client) ?? g.maxSymbolsPerClient;
    g.maxClientQueue = asNumber(md.max_client_queue) ?? g.maxClientQueue;
    g.depthLevels = asNumber(md.depth_levels) ?? g.depthLevels;
  }

  const balf = raw.balf_gateway;
  if (isDict(balf)) {
    const g = draft.balfGateway;
    g.enabled = true;
    g.name = asString(balf.name) ?? g.name;
    g.bindAddress = asString(balf.bind_address) ?? g.bindAddress;
    g.port = asNumber(balf.port) ?? g.port;
    g.heartbeatIntervalSec = asNumber(balf.heartbeat_interval_sec) ?? g.heartbeatIntervalSec;
    g.heartbeatTimeoutSec = asNumber(balf.heartbeat_timeout_sec) ?? g.heartbeatTimeoutSec;
    g.idleTimeoutSec = asNumber(balf.idle_timeout_sec) ?? g.idleTimeoutSec;
    g.authTimeoutSec = asNumber(balf.auth_timeout_sec) ?? g.authTimeoutSec;
    g.maxConnections = asNumber(balf.max_connections) ?? g.maxConnections;
    g.maxClientQueue = asNumber(balf.max_client_queue) ?? g.maxClientQueue;
    g.maxMessagesPerSecond = asNumber(balf.max_messages_per_second) ?? g.maxMessagesPerSecond;
    g.maxErrorsBeforeDisconnect =
      asNumber(balf.max_errors_before_disconnect) ?? g.maxErrorsBeforeDisconnect;
    g.errorWindowSec = asNumber(balf.error_window_sec) ?? g.errorWindowSec;
    const policy = asString(balf.duplicate_session_policy);
    if (policy === "REJECT_NEW" || policy === "EVICT_OLD") g.duplicateSessionPolicy = policy;
  }
}

function parseApiGateways(node: unknown, draft: EngineConfigDraft): void {
  if (!isDict(node)) return;
  const gateways: ApiGatewayConfig[] = [];
  for (const [name, value] of Object.entries(node)) {
    if (!isDict(value)) continue;
    const rateLimit = isDict(value.rate_limit) ? value.rate_limit : {};
    const timeouts = isDict(value.timeouts) ? value.timeouts : {};
    const credentials = Array.isArray(value.credentials)
      ? value.credentials.filter(isDict).map((c) => ({
          apiKey: asString(c.api_key) ?? "",
          gatewayId: asString(c.gateway_id) ?? null,
          description: asString(c.description) ?? "",
        }))
      : [];
    gateways.push({
      name,
      enabled: asBool(value.enabled, true),
      host: asString(value.host) ?? "127.0.0.1",
      port: asNumber(value.port) ?? 8080,
      swaggerEnabled: asBool(value.swagger_enabled, true),
      logLevel: (asString(value.log_level) as ApiGatewayConfig["logLevel"]) ?? "info",
      statsDb: asString(value.stats_db) ?? "data/stats.db",
      gatewayIds: credentials
        .map((c) => c.gatewayId)
        .filter((id): id is string => id !== null),
      generateKeys: false,
      generateReadonlyKey: false,
      credentials,
      rateLimitWritesPerSecond: asNumber(rateLimit.writes_per_second) ?? 10,
      rateLimitBurst: asNumber(rateLimit.burst) ?? 20,
      engineAuthSec: asNumber(timeouts.engine_auth_sec) ?? 3.0,
      engineReplySec: asNumber(timeouts.engine_reply_sec) ?? 3.0,
      waitAckSec: asNumber(timeouts.wait_ack_sec) ?? 3.0,
    });
  }
  draft.apiGateways = gateways;
}

function parseIndices(node: unknown, draft: EngineConfigDraft): void {
  if (!Array.isArray(node)) return;
  const indices: IndexConfig[] = [];
  for (const entry of node) {
    if (!isDict(entry)) continue;
    const id = asString(entry.id);
    if (!id) continue;
    indices.push({
      id,
      description: asString(entry.description) ?? "",
      constituents: Array.isArray(entry.constituents)
        ? entry.constituents.filter((c): c is string => typeof c === "string")
        : [],
      baseValue: asNumber(entry.base_value) ?? 1000.0,
      publishIntervalSec: asNumber(entry.publish_interval_sec) ?? 1.0,
      historyFile: asString(entry.history_file),
      stateFile: asString(entry.state_file),
    });
  }
  draft.indices = indices;
}

function parseCombos(node: unknown, draft: EngineConfigDraft): void {
  if (!Array.isArray(node)) return;
  const combos: ComboConfig[] = [];
  for (const entry of node) {
    if (!isDict(entry)) continue;
    const comboId = asString(entry.combo_id);
    if (!comboId) continue;
    const legs = Array.isArray(entry.legs)
      ? entry.legs.filter(isDict).map((leg) => {
          const symbol = asString(leg.symbol) ?? "";
          const td = draft.symbols[symbol]?.tickDecimals ?? draft.tickDecimals;
          const factor = Math.pow(10, td);
          const priceTicks = asNumber(leg.price);
          const stopTicks = asNumber(leg.stop_price);
          return {
            symbol,
            side: (asString(leg.side) as "BUY" | "SELL") ?? "BUY",
            orderType: (asString(leg.order_type) as ComboConfig["legs"][number]["orderType"]) ?? "LIMIT",
            quantity: asNumber(leg.quantity) ?? 0,
            price: priceTicks === undefined ? null : priceTicks / factor,
            stopPrice: stopTicks === undefined ? null : stopTicks / factor,
            smpAction: (asString(leg.smp_action) as ComboConfig["legs"][number]["smpAction"]) ?? "NONE",
          };
        })
      : [];
    combos.push({
      comboId,
      comboType: (asString(entry.combo_type) as "AON") ?? "AON",
      tif: (asString(entry.tif) as ComboConfig["tif"]) ?? "DAY",
      legs,
    });
  }
  draft.combos = combos;
}

function parseSchedule(node: unknown, draft: EngineConfigDraft): void {
  if (!isDict(node)) return;
  draft.emitSchedule = true;
  draft.schedule = {
    preOpen: asString(node.pre_open) ?? draft.schedule.preOpen,
    openingAuction: asString(node.opening_auction_start) ?? draft.schedule.openingAuction,
    continuous: asString(node.continuous_start) ?? draft.schedule.continuous,
    closingAuction: asString(node.closing_auction_start) ?? draft.schedule.closingAuction,
    closingEnd: asString(node.closing_auction_end) ?? draft.schedule.closingEnd,
  };
}

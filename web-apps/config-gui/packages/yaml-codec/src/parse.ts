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
  DEFAULT_DYNAMIC_BAND_PCT,
  DEFAULT_MM_MIN_QTY,
  DEFAULT_STATIC_BAND_PCT,
  ENGINE_DEFAULT_MM_MAX_SPREAD_TICKS,
  type ApiGatewayConfig,
  type BalfGatewayConfig,
  type CbLevel,
  type ComboConfig,
  type EngineConfigDraft,
  type GatewayConfig,
  type GatewayMmObligationOverride,
  type IndexConfig,
  type ExpansionRung,
  type MmQuoteSeed,
  type ParticipantRole,
  type QuoteRefreshPolicy,
  type ReopeningOverride,
  type RiskLevel,
  type SmpAction,
  type SymbolConfig,
  type Tif,
} from "@edumatcher/schema";

const KNOWN_TOP_LEVEL_KEYS = new Set([
  "sessions_enabled",
  "require_mm_seed_quotes",
  "country",
  "enforce_collars",
  "enforce_circuit_breakers",
  "engine_tuning",
  "snapshot_interval_sec",
  "mm_obligation_defaults",
  "risk_controls",
  "circuit_breaker_defaults",
  "gateways",
  "alf_gateway",
  "post_trade_gateway",
  "market_data_gateway",
  "balf_gateway",
  "dc_gateway",
  "log_server",
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

/**
 * Symbols, gateway ids, index ids, level names and every enum value are
 * upper-cased by the loaders (spec §1.6). Doing the same here keeps
 * cross-references intact (`gateway_id: mm01` must still find `id: MM01`)
 * and makes an out-of-range enum value surface as a diagnostic rather than
 * a blank select.
 */
const asUpper = (v: unknown): string | undefined =>
  typeof v === "string" ? v.trim().toUpperCase() : undefined;

/**
 * Unquoted `9:30` reads as the string "9:30" here (YAML 1.2), while the
 * engine loader normalises it to "09:30". Normalise the same way so the
 * schedule is not reported as malformed.
 */
function asHhmm(v: unknown): string | undefined {
  const s = asString(v)?.trim();
  if (s === undefined) return undefined;
  return /^\d:\d\d$/.test(s) ? `0${s}` : s;
}

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

  // Absent keys take the engine loader's defaults, not the defaults this GUI
  // proposes for a new config — otherwise re-export would silently change
  // what the file means.
  draft.sessionsEnabled = asBool(raw.sessions_enabled, true);
  draft.requireMmSeedQuotes = asBool(raw.require_mm_seed_quotes, true);
  draft.mmObligationDefaults = {
    enforceMmObligation: false,
    mmMaxSpreadTicks: ENGINE_DEFAULT_MM_MAX_SPREAD_TICKS,
    mmMinQty: DEFAULT_MM_MIN_QTY,
  };
  draft.country = asString(raw.country) ?? draft.country;
  draft.enforceCollars = asBool(raw.enforce_collars, draft.enforceCollars);
  draft.enforceCircuitBreakers = asBool(
    raw.enforce_circuit_breakers,
    draft.enforceCircuitBreakers,
  );
  const engineTuning = isDict(raw.engine_tuning)
    ? raw.engine_tuning
    : undefined;
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
    const id = asUpper(entry.id);
    if (!id) continue;
    const role = (asUpper(entry.role) as ParticipantRole) ?? "TRADER";
    const base = createGateway(id, role);
    // P3.9: when disconnect_behaviour is omitted, reflect the engine loader's
    // real default (CANCEL_QUOTES_ONLY for every role) rather than the
    // role-derived value createGateway() uses for freshly authored gateways.
    // This keeps import -> re-export faithful to what the engine would have done
    // with the original omitted field.
    const disconnect = asUpper(entry.disconnect_behaviour);
    base.disconnectBehaviour = disconnect
      ? (disconnect as GatewayConfig["disconnectBehaviour"])
      : "CANCEL_QUOTES_ONLY";
    const description = asString(entry.description);
    if (description) base.description = description;
    const refresh = asUpper(entry.quote_refresh_policy);
    if (refresh) base.quoteRefreshPolicy = refresh as QuoteRefreshPolicy;
    const smp = asUpper(entry.smp_action);
    if (smp) base.smpAction = smp as SmpAction;

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
  for (const [rawSymbol, rawValue] of Object.entries(node)) {
    // `AAPL:` / `AAPL: {}` is a valid empty spec (spec §5.1).
    if (rawValue !== null && !isDict(rawValue)) continue;
    const value: Dict = rawValue ?? {};
    const symbol = rawSymbol.trim().toUpperCase();
    const config: SymbolConfig = {
      tickDecimals: asNumber(value.tick_decimals) ?? draft.tickDecimals,
    };
    const level = asUpper(value.level);
    if (level) config.level = level;
    const outstanding = asNumber(value.outstanding_shares);
    if (outstanding !== undefined) config.outstandingShares = outstanding;
    if ("last_buy_price" in value)
      config.lastBuyPrice = asNumber(value.last_buy_price) ?? null;
    if ("last_sell_price" in value)
      config.lastSellPrice = asNumber(value.last_sell_price) ?? null;
    if (isDict(value.collar)) {
      config.collar = {
        staticBandPct: asNumber(value.collar.static_band_pct),
        dynamicBandPct: asNumber(value.collar.dynamic_band_pct),
      };
    }
    if (isDict(value.order_limits)) {
      const limits: { maxOrderQty?: number; maxOrderValue?: number } = {};
      const maxQty = asNumber(value.order_limits.max_order_qty);
      if (maxQty !== undefined) limits.maxOrderQty = maxQty;
      const maxValue = asNumber(value.order_limits.max_order_value);
      if (maxValue !== undefined) limits.maxOrderValue = maxValue;
      if (Object.keys(limits).length > 0) config.orderLimits = limits;
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
          if ("halt_duration_ns" in lvl)
            partial.haltDurationNs = asNumber(lvl.halt_duration_ns) ?? null;
          levels[name.toUpperCase()] = partial;
        }
      }
      const windowNs = asNumber(cbRaw.reference_window_ns);
      const reopening = parseReopeningOverride(cbRaw.reopening);
      if (
        windowNs !== undefined ||
        reopening !== undefined ||
        Object.keys(levels).length > 0
      ) {
        config.circuitBreaker = { levels };
        if (windowNs !== undefined)
          config.circuitBreaker.referenceWindowNs = windowNs;
        if (reopening !== undefined) config.circuitBreaker.reopening = reopening;
      }
    }
    if (Array.isArray(value.market_maker_quotes)) {
      const quotes: MmQuoteSeed[] = [];
      for (const raw of value.market_maker_quotes) {
        if (!isDict(raw)) continue;
        const gatewayId = asUpper(raw.gateway_id);
        if (!gatewayId) continue;
        const quoteId = asString(raw.quote_id)?.trim();
        quotes.push({
          gatewayId,
          ...(quoteId ? { quoteId } : {}),
          bidPrice: asNumber(raw.bid_price) ?? null,
          askPrice: asNumber(raw.ask_price) ?? null,
          // A missing quantity is not invented: 0 is shown and reported, as
          // the engine refuses the quote.
          bidQty: asNumber(raw.bid_qty) ?? 0,
          askQty: asNumber(raw.ask_qty) ?? 0,
          tif: (asUpper(raw.tif) as Tif) ?? "DAY",
          seedOnce: typeof raw.seed_once === "boolean" ? raw.seed_once : true,
        });
      }
      if (quotes.length > 0) config.marketMakerQuotes = quotes;
    }
    // `aapl` and `AAPL` are one symbol to the loader; the later one wins.
    if (!(symbol in symbols)) order.push(symbol);
    symbols[symbol] = config;
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
    asNumber(node.mm_max_spread_ticks) ??
    draft.mmObligationDefaults.mmMaxSpreadTicks;
  draft.mmObligationDefaults.mmMinQty =
    asNumber(node.mm_min_qty) ?? draft.mmObligationDefaults.mmMinQty;

  if (isDict(node.symbols)) {
    for (const [symbol, override] of Object.entries(node.symbols)) {
      if (!isDict(override)) continue;
      const target = draft.symbols[symbol.trim().toUpperCase()];
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
  if (!isDict(node)) return;
  const defaultLevel = asUpper(node.default_level);
  if (defaultLevel) draft.riskControls.defaultLevel = defaultLevel;
  if (!isDict(node.levels)) return;
  const levels: Record<string, RiskLevel> = {};
  for (const [rawName, value] of Object.entries(node.levels)) {
    if (!isDict(value)) continue;
    const name = rawName.trim().toUpperCase();
    // `collar: {}` is a collar at the engine defaults; no `collar` key is no
    // collar at all. Only keys actually present are kept, so re-export
    // writes the same collar the engine merges from the original.
    const level: RiskLevel = {};
    if (isDict(value.collar)) {
      const staticBandPct = asNumber(value.collar.static_band_pct);
      const dynamicBandPct = asNumber(value.collar.dynamic_band_pct);
      if (staticBandPct === undefined && dynamicBandPct === undefined) {
        level.staticBandPct = DEFAULT_STATIC_BAND_PCT;
        level.dynamicBandPct = DEFAULT_DYNAMIC_BAND_PCT;
      } else {
        if (staticBandPct !== undefined) level.staticBandPct = staticBandPct;
        if (dynamicBandPct !== undefined) level.dynamicBandPct = dynamicBandPct;
      }
    }
    // DEFAULT becomes the GUI's global collar only when it is the default
    // level with a collar — the shape this GUI itself writes. Anything else
    // stays a plain named level so its meaning is unchanged on re-export.
    if (
      name === "DEFAULT" &&
      defaultLevel === "DEFAULT" &&
      (level.staticBandPct !== undefined || level.dynamicBandPct !== undefined)
    ) {
      draft.riskControls.globalStaticBandPct = level.staticBandPct;
      draft.riskControls.globalDynamicBandPct = level.dynamicBandPct;
      continue;
    }
    levels[name] = level;
  }
  draft.riskControls.levels = levels;
}

function parseCircuitBreakerDefaults(
  node: unknown,
  draft: EngineConfigDraft,
): void {
  // Absent block: nothing is written back and symbols without their own
  // circuit_breaker get none. The factory ladder stays in the draft only so
  // that switching the block on starts from the engine's built-in values.
  if (!isDict(node)) {
    draft.circuitBreakerDefaults.include = false;
    return;
  }
  draft.circuitBreakerDefaults.include = true;
  draft.circuitBreakerDefaults.windowNs =
    asNumber(node.reference_window_ns) ?? draft.circuitBreakerDefaults.windowNs;
  const levels: Record<string, CbLevel> = {};
  const order: string[] = [];
  if (isDict(node.levels)) {
    for (const [rawName, value] of Object.entries(node.levels)) {
      if (!isDict(value)) continue;
      const name = rawName.trim().toUpperCase();
      levels[name] = {
        // A missing shift is not invented: NaN is reported (the engine
        // requires price_shift_pct) rather than silently becoming 7%.
        priceShiftPct: asNumber(value.price_shift_pct) ?? Number.NaN,
        haltDurationNs:
          "halt_duration_ns" in value
            ? (asNumber(value.halt_duration_ns) ?? null)
            : null,
      };
      order.push(name);
    }
  }
  // No `levels` key: the engine applies its built-in ladder, and an empty
  // draft ladder is written back without the key.
  draft.circuitBreakerDefaults.levels = levels;
  draft.circuitBreakerDefaults.levelOrder = order;
  parseReopeningDefaults(node.reopening, draft);
}

/**
 * Exchange-wide ACE block. Absent keys keep the factory defaults, so an
 * authored file that omits `reopening:` round-trips to the same defaults the
 * engine loader would have applied.
 */
function parseReopeningDefaults(node: unknown, draft: EngineConfigDraft): void {
  if (!isDict(node)) return;
  const r = draft.circuitBreakerDefaults.reopening;
  if (typeof node.enabled === "boolean") r.enabled = node.enabled;
  r.initialBandPct = asNumber(node.initial_band_pct) ?? r.initialBandPct;
  r.randomEndMaxNs = asNumber(node.random_end_max_ns) ?? r.randomEndMaxNs;
  const seed = asNumber(node.random_seed);
  if (seed !== undefined) r.randomSeed = seed;
  if (Array.isArray(node.expansions)) {
    const rungs: ExpansionRung[] = [];
    for (const entry of node.expansions) {
      if (!isDict(entry)) continue;
      const widenPct = asNumber(entry.widen_pct);
      const minDurationNs = asNumber(entry.min_duration_ns);
      if (widenPct === undefined || minDurationNs === undefined) continue;
      rungs.push({ widenPct, minDurationNs });
    }
    // An empty ladder is not expressible: the engine loader refuses it.
    if (rungs.length > 0) r.expansions = rungs;
  }
}

/** Per-symbol ACE override — the three scalars only; the ladder is exchange-wide. */
function parseReopeningOverride(node: unknown): ReopeningOverride | undefined {
  if (!isDict(node)) return undefined;
  const override: ReopeningOverride = {};
  if (typeof node.enabled === "boolean") override.enabled = node.enabled;
  const band = asNumber(node.initial_band_pct);
  if (band !== undefined) override.initialBandPct = band;
  const tail = asNumber(node.random_end_max_ns);
  if (tail !== undefined) override.randomEndMaxNs = tail;
  return Object.keys(override).length > 0 ? override : undefined;
}

function parseNetworkGateways(raw: Dict, draft: EngineConfigDraft): void {
  const alf = raw.alf_gateway;
  if (isDict(alf)) {
    const g = draft.alfGateway;
    g.include = true;
    g.enabled = asBool(alf.enabled, true);
    g.name = asString(alf.name) ?? g.name;
    g.bindAddress = asString(alf.bind_address) ?? g.bindAddress;
    g.port = asNumber(alf.port) ?? g.port;
    g.heartbeatIntervalSec =
      asNumber(alf.heartbeat_interval_sec) ?? g.heartbeatIntervalSec;
    g.handshakeTimeoutSec =
      asNumber(alf.handshake_timeout_sec) ?? g.handshakeTimeoutSec;
    g.idleTimeoutSec = asNumber(alf.idle_timeout_sec) ?? g.idleTimeoutSec;
    g.maxConnections = asNumber(alf.max_connections) ?? g.maxConnections;
    g.maxClientQueue = asNumber(alf.max_client_queue) ?? g.maxClientQueue;
    g.maxCommandsPerSecond =
      asNumber(alf.max_commands_per_second) ?? g.maxCommandsPerSecond;
    g.maxErrorsBeforeDisconnect =
      asNumber(alf.max_errors_before_disconnect) ?? g.maxErrorsBeforeDisconnect;
    g.errorWindowSec = asNumber(alf.error_window_sec) ?? g.errorWindowSec;
  }

  const pt = raw.post_trade_gateway;
  if (isDict(pt)) {
    const g = draft.postTradeGateway;
    g.include = true;
    g.name = asString(pt.name) ?? g.name;
    g.bindAddress = asString(pt.bind_address) ?? g.bindAddress;
    g.port = asNumber(pt.port) ?? g.port;
    g.replayRetentionSec =
      asNumber(pt.replay_retention_sec) ?? g.replayRetentionSec;
    g.heartbeatIntervalSec =
      asNumber(pt.heartbeat_interval_sec) ?? g.heartbeatIntervalSec;
    g.idleTimeoutSec = asNumber(pt.idle_timeout_sec) ?? g.idleTimeoutSec;
    g.maxClientQueue = asNumber(pt.max_client_queue) ?? g.maxClientQueue;
    if (Array.isArray(pt.allowed_roles)) {
      g.allowedRoles = pt.allowed_roles
        .filter((r): r is string => typeof r === "string")
        .map((r) => r.trim().toUpperCase());
    }
  }

  const md = raw.market_data_gateway;
  if (isDict(md)) {
    const g = draft.marketDataGateway;
    g.include = true;
    g.enabled = asBool(md.enabled, true);
    g.name = asString(md.name) ?? g.name;
    g.bindAddress = asString(md.bind_address) ?? g.bindAddress;
    g.port = asNumber(md.port) ?? g.port;
    g.heartbeatIntervalSec =
      asNumber(md.heartbeat_interval_sec) ?? g.heartbeatIntervalSec;
    g.idleTimeoutSec = asNumber(md.idle_timeout_sec) ?? g.idleTimeoutSec;
    g.replayWindowSec = asNumber(md.replay_window_sec) ?? g.replayWindowSec;
    g.maxConnections = asNumber(md.max_connections) ?? g.maxConnections;
    g.maxMessagesPerSecond =
      asNumber(md.max_messages_per_second) ?? g.maxMessagesPerSecond;
    g.maxSymbolsPerClient =
      asNumber(md.max_symbols_per_client) ?? g.maxSymbolsPerClient;
    g.maxClientQueue = asNumber(md.max_client_queue) ?? g.maxClientQueue;
    g.depthLevels = asNumber(md.depth_levels) ?? g.depthLevels;
  }

  const balf = raw.balf_gateway;
  if (isDict(balf)) {
    const g = draft.balfGateway;
    g.include = true;
    g.enabled = asBool(balf.enabled, true);
    g.name = asString(balf.name) ?? g.name;
    g.bindAddress = asString(balf.bind_address) ?? g.bindAddress;
    g.port = asNumber(balf.port) ?? g.port;
    g.heartbeatIntervalSec =
      asNumber(balf.heartbeat_interval_sec) ?? g.heartbeatIntervalSec;
    g.heartbeatTimeoutSec =
      asNumber(balf.heartbeat_timeout_sec) ?? g.heartbeatTimeoutSec;
    g.idleTimeoutSec = asNumber(balf.idle_timeout_sec) ?? g.idleTimeoutSec;
    g.authTimeoutSec = asNumber(balf.auth_timeout_sec) ?? g.authTimeoutSec;
    g.maxConnections = asNumber(balf.max_connections) ?? g.maxConnections;
    g.maxClientQueue = asNumber(balf.max_client_queue) ?? g.maxClientQueue;
    g.maxMessagesPerSecond =
      asNumber(balf.max_messages_per_second) ?? g.maxMessagesPerSecond;
    g.maxErrorsBeforeDisconnect =
      asNumber(balf.max_errors_before_disconnect) ??
      g.maxErrorsBeforeDisconnect;
    g.errorWindowSec = asNumber(balf.error_window_sec) ?? g.errorWindowSec;
    const policy = asUpper(balf.duplicate_session_policy);
    if (policy) {
      g.duplicateSessionPolicy =
        policy as BalfGatewayConfig["duplicateSessionPolicy"];
    }
  }

  const dc = raw.dc_gateway;
  if (isDict(dc)) {
    const g = draft.dcGateway;
    g.include = true;
    g.name = asString(dc.name) ?? g.name;
    g.bindAddress = asString(dc.bind_address) ?? g.bindAddress;
    g.port = asNumber(dc.port) ?? g.port;
    g.heartbeatIntervalSec =
      asNumber(dc.heartbeat_interval_sec) ?? g.heartbeatIntervalSec;
    g.idleTimeoutSec = asNumber(dc.idle_timeout_sec) ?? g.idleTimeoutSec;
    g.maxClientQueue = asNumber(dc.max_client_queue) ?? g.maxClientQueue;
  }

  const ls = raw.log_server;
  if (isDict(ls)) {
    const g = draft.logServer;
    g.include = true;
    g.enabled = asBool(ls.enabled, true);
    g.name = asString(ls.name) ?? g.name;
    g.bindAddress = asString(ls.bind_address) ?? g.bindAddress;
    g.port = asNumber(ls.port) ?? g.port;
    g.dbPath = asString(ls.db_path) ?? g.dbPath;
    // retention_days: null/0 both mean unbounded retention (§6.5); a bare
    // `null` in YAML must stick, not silently fall back to the 30-day
    // default the way asNumber(undefined) ?? default would.
    if (ls.retention_days === null) {
      g.retentionDays = null;
    } else {
      const retentionDays = asNumber(ls.retention_days);
      if (retentionDays !== undefined) g.retentionDays = retentionDays;
    }
    g.maxMessageBytes = asNumber(ls.max_message_bytes) ?? g.maxMessageBytes;
    g.maxClientQueue = asNumber(ls.max_client_queue) ?? g.maxClientQueue;
    g.writeBatchSize = asNumber(ls.write_batch_size) ?? g.writeBatchSize;
    g.writeBatchIntervalMs =
      asNumber(ls.write_batch_interval_ms) ?? g.writeBatchIntervalMs;
    g.heartbeatIntervalSec =
      asNumber(ls.heartbeat_interval_sec) ?? g.heartbeatIntervalSec;

    // LALF-PS. Every field is optional in the YAML, so an absent key must
    // keep the factory default rather than becoming undefined.
    g.pubsubEnabled = asBool(ls.pubsub_enabled, g.pubsubEnabled);
    g.pubPort = asNumber(ls.pub_port) ?? g.pubPort;
    g.pullPort = asNumber(ls.pull_port) ?? g.pullPort;
    g.leaseSec = asNumber(ls.lease_sec) ?? g.leaseSec;
    g.maxLeaseSec = asNumber(ls.max_lease_sec) ?? g.maxLeaseSec;
    g.maxSubscribers = asNumber(ls.max_subscribers) ?? g.maxSubscribers;
    g.notifyIntervalMs = asNumber(ls.notify_interval_ms) ?? g.notifyIntervalMs;
    g.backfillChunkRows =
      asNumber(ls.backfill_chunk_rows) ?? g.backfillChunkRows;
    g.maxBackfillMinutes =
      asNumber(ls.max_backfill_minutes) ?? g.maxBackfillMinutes;
    g.maxBackfillRows = asNumber(ls.max_backfill_rows) ?? g.maxBackfillRows;
    g.maxPendingRows = asNumber(ls.max_pending_rows) ?? g.maxPendingRows;
    g.pubSndhwm = asNumber(ls.pub_sndhwm) ?? g.pubSndhwm;
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
          gatewayId: asUpper(c.gateway_id) ?? null,
          description: asString(c.description) ?? "",
        }))
      : [];
    const auditDb = asString(value.audit_db);
    gateways.push({
      name,
      enabled: asBool(value.enabled, true),
      host: asString(value.host) ?? "0.0.0.0",
      port: asNumber(value.port) ?? 8080,
      swaggerEnabled: asBool(value.swagger_enabled, true),
      logLevel:
        (asString(value.log_level) as ApiGatewayConfig["logLevel"]) ?? "info",
      statsDb: asString(value.stats_db) ?? "data/stats.db",
      ...(auditDb !== undefined ? { auditDb } : {}),
      // ?? not ||: an explicit 0 must survive, it means "never evict".
      orderRetentionSec: asNumber(value.order_retention_sec) ?? 3600,
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
    const id = asUpper(entry.id);
    if (!id) continue;
    indices.push({
      id,
      description: asString(entry.description) ?? "",
      constituents: Array.isArray(entry.constituents)
        ? entry.constituents
            .filter((c): c is string => typeof c === "string")
            .map((c) => c.trim().toUpperCase())
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
          const symbol = asUpper(leg.symbol) ?? "";
          const price = asNumber(leg.price);
          const stopPrice = asNumber(leg.stop_price);
          // Omitted smp_action means "the seeding gateway's default", which an
          // explicit NONE would override — so absence is kept as absence.
          const smp = asUpper(leg.smp_action);
          return {
            symbol,
            side: (asUpper(leg.side) as "BUY" | "SELL") ?? "BUY",
            orderType:
              (asUpper(
                leg.order_type,
              ) as ComboConfig["legs"][number]["orderType"]) ?? "LIMIT",
            quantity: asNumber(leg.quantity) ?? 0,
            price: price ?? null,
            stopPrice: stopPrice ?? null,
            ...(smp ? { smpAction: smp as SmpAction } : {}),
          };
        })
      : [];
    combos.push({
      comboId: comboId.trim(),
      comboType: (asUpper(entry.combo_type) as "AON") ?? "AON",
      tif: (asUpper(entry.tif) as ComboConfig["tif"]) ?? "DAY",
      legs,
    });
  }
  draft.combos = combos;
}

function parseSchedule(node: unknown, draft: EngineConfigDraft): void {
  // Presence decides emission both ways: an absent block must stay absent.
  draft.emitSchedule = isDict(node);
  if (!isDict(node)) return;
  draft.schedule = {
    preOpen: asHhmm(node.pre_open) ?? draft.schedule.preOpen,
    openingAuction:
      asHhmm(node.opening_auction_start) ?? draft.schedule.openingAuction,
    continuous: asHhmm(node.continuous_start) ?? draft.schedule.continuous,
    closingAuction:
      asHhmm(node.closing_auction_start) ?? draft.schedule.closingAuction,
    closingEnd: asHhmm(node.closing_auction_end) ?? draft.schedule.closingEnd,
  };
}

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
  RESERVED_CONFIG_NAMES,
  SPLIT_FILES,
  type ApiGatewayConfig,
  type BalfGatewayConfig,
  type CbLevel,
  type ComboConfig,
  type DisconnectBehaviour,
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
  type WeeklyScheduleDraft,
  DEFAULT_SCHEDULE,
  MONITOR_THRESHOLD_RULES,
} from "@edumatcher/schema";

const KNOWN_TOP_LEVEL_KEYS = new Set([
  "sessions_enabled",
  "require_mm_seed_quotes",
  "enforce_collars",
  "enforce_circuit_breakers",
  "engine_tuning",
  "mm_obligation_defaults",
  "risk_controls",
  "circuit_breaker_defaults",
  "participant_defaults",
  "participants",
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
  "locale",
  "monitor",
  "auction_indicative_interval_sec",
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
  /** Things the user should know about the import, e.g. a changed file layout. */
  notes: string[];
}

export interface ConfigFile {
  name: string;
  text: string;
}

const INCLUDE_KEY = "include";

const CREDENTIALS_FILE_KEY = "credentials_file";

function loadYaml(file: ConfigFile): unknown {
  try {
    return yaml.load(file.text, { json: true }) ?? null;
  } catch (err) {
    throw new Error(`${file.name}: not valid YAML: ${err instanceof Error ? err.message : String(err)}`);
  }
}

function asMapping(name: string, raw: unknown): Record<string, unknown> {
  if (raw === null) return {};
  if (!isDict(raw)) throw new Error(`${name}: must be a YAML mapping.`);
  return raw;
}

/**
 * The path, relative to the main file, that `entry` in the file `owner`
 * names; refuses what the engine refuses.
 *
 * MAINTENANCE: keep aligned with `_relative_file` / `_refuse_reserved` in
 * src/edumatcher/config_include.py.
 */
function resolveEntry(owner: string, entry: string, what: string, mainName: string): string {
  if (entry.startsWith("/") || entry.split("/").includes("..")) {
    throw new Error(`${owner}: ${what} '${entry}' must be a relative path without '..'.`);
  }
  const dir = owner.includes("/") ? owner.slice(0, owner.lastIndexOf("/") + 1) : "";
  const path = (dir + entry).split("/").filter((p) => p !== "" && p !== ".").join("/");
  if (RESERVED_CONFIG_NAMES.includes(path)) {
    throw new Error(
      `${mainName}: '${path}' is a reserved name (pm-config-deploy installs its own file there); rename it or move it into a subdirectory.`,
    );
  }
  return path;
}

/**
 * Merge an included file into `merged` the way the engine does: lists
 * concatenate, mappings merge one level deep, anything else is an error.
 *
 * MAINTENANCE: keep aligned with `_merge` in src/edumatcher/config_include.py.
 */
function mergeInclude(
  merged: Record<string, unknown>,
  origin: Record<string, string>,
  extra: Record<string, unknown>,
  name: string,
): void {
  for (const [key, value] of Object.entries(extra)) {
    if (!(key in merged)) {
      merged[key] = value;
      origin[key] = name;
      continue;
    }
    const have = merged[key];
    if (Array.isArray(have) && Array.isArray(value)) {
      merged[key] = [...have, ...value];
    } else if (isDict(have) && isDict(value)) {
      const clash = Object.keys(value).filter((k) => k in have).sort();
      if (clash.length > 0) throw new Error(`${name}: '${key}.${clash[0]}' is already defined in ${origin[key]}.`);
      merged[key] = { ...have, ...value };
    } else {
      throw new Error(
        `${name}: '${key}' is already defined in ${origin[key]} and cannot be merged (only lists and mappings merge).`,
      );
    }
  }
}

/**
 * Import a config given as one file, or as a main file plus the files its
 * `include:` list and its API gateways' `credentials_file` keys name. The
 * browser only knows file names, so such a path is matched to a selected
 * file by its last component. Every selected file must be one of these.
 *
 * A config read from includes is exported split again; when its files are
 * laid out differently from the SPLIT_FILES layout the export writes, a note
 * says so. A gateway's credentials file is kept, and written back on export.
 */
export function parseConfigFiles(files: ConfigFile[]): ImportResult {
  if (files.length === 0) throw new Error("No file selected.");
  const loaded = files.map((file) => ({ name: file.name, raw: loadYaml(file) }));
  // The main file is the one with `include:`; failing that, the only mapping
  // (a credentials file is a list).
  const withInclude = loaded.filter((f) => isDict(f.raw) && INCLUDE_KEY in f.raw);
  const mappings = loaded.filter((f) => isDict(f.raw));
  if (withInclude.length > 1) {
    throw new Error(
      `Only one selected file may have an 'include:' list; found one in ${withInclude.map((f) => f.name).join(", ")}.`,
    );
  }
  if (files.length > 1 && withInclude.length === 0 && mappings.length !== 1) {
    throw new Error(
      "Several config files were selected but none has an 'include:' list. Select one config file, or a main file together with the files it names.",
    );
  }
  const main = withInclude[0] ?? mappings[0] ?? loaded[0]!;
  const mainRaw = asMapping(main.name, main.raw);
  const byName = new Map(loaded.filter((f) => f !== main).map((f) => [f.name, f]));
  // Selected file name -> the path it was taken for.
  const used = new Map<string, string>();
  const take = (path: string, owner: string, what: string, entry: string) => {
    const name = path.split("/").pop()!;
    const previous = used.get(name);
    if (previous !== undefined && previous !== path) {
      throw new Error(`${previous} and ${path} are both named ${name}; the browser cannot tell them apart.`);
    }
    const selected = byName.get(name);
    if (!selected) {
      throw new Error(`${owner} names ${what} '${entry}'. Import again and select it together with ${main.name}.`);
    }
    used.set(name, path);
    return selected;
  };

  const entries = mainRaw[INCLUDE_KEY] ?? [];
  if (!Array.isArray(entries) || !entries.every((e) => typeof e === "string")) {
    throw new Error(`${main.name}: 'include' must be a list of file names.`);
  }
  const merged: Record<string, unknown> = { ...mainRaw };
  delete merged[INCLUDE_KEY];
  const origin: Record<string, string> = Object.fromEntries(Object.keys(merged).map((k) => [k, main.name]));
  // The file each API gateway is defined in, which its credentials_file is relative to.
  const apiOwner = new Map<string, string>();
  const recordApiOwners = (raw: Record<string, unknown>, owner: string) => {
    if (isDict(raw.api_gateways)) for (const name of Object.keys(raw.api_gateways)) apiOwner.set(name, owner);
  };
  recordApiOwners(mainRaw, main.name);
  const includePaths: string[] = [];
  for (const entry of entries as string[]) {
    const path = resolveEntry(main.name, entry, "include", main.name);
    if (includePaths.includes(path)) throw new Error(`${main.name}: include '${entry}' is listed twice.`);
    includePaths.push(path);
    const included = take(path, main.name, "the include", entry);
    const raw = asMapping(included.name, included.raw);
    if (INCLUDE_KEY in raw) {
      throw new Error(`${included.name}: includes cannot be nested; list every file in ${main.name}.`);
    }
    mergeInclude(merged, origin, raw, path);
    recordApiOwners(raw, path);
  }

  // Replace each API gateway's credentials_file by the credentials it holds.
  const credentialsFiles = new Map<string, string>();
  if (isDict(merged.api_gateways)) {
    const gateways: Record<string, unknown> = { ...merged.api_gateways };
    for (const [name, value] of Object.entries(gateways)) {
      if (!isDict(value) || !(CREDENTIALS_FILE_KEY in value)) continue;
      const owner = apiOwner.get(name) ?? main.name;
      const where = `api_gateways.${name}`;
      const { [CREDENTIALS_FILE_KEY]: entry, ...block } = value;
      if (typeof entry !== "string") throw new Error(`${owner}: ${where}.credentials_file must be a name.`);
      if ("credentials" in block) throw new Error(`${owner}: ${where} has both 'credentials' and 'credentials_file'.`);
      const path = resolveEntry(owner, entry, `${where}.credentials_file`, main.name);
      const selected = take(path, owner, `the credentials file`, entry);
      if (selected.raw !== null && !Array.isArray(selected.raw)) {
        throw new Error(`${selected.name}: must be a YAML list of credentials.`);
      }
      gateways[name] = { ...block, credentials: selected.raw ?? [] };
      credentialsFiles.set(name, entry);
    }
    merged.api_gateways = gateways;
  }

  const unused = [...byName.keys()].filter((name) => !used.has(name));
  if (unused.length > 0) throw new Error(`${main.name} does not name ${unused.join(", ")}.`);

  const result = draftFromMapping(merged);
  for (const gw of result.draft.apiGateways) {
    const file = credentialsFiles.get(gw.name);
    if (file !== undefined) gw.credentialsFile = file;
  }
  if (entries.length > 0) {
    result.draft.output.splitIncludes = true;
    // Exact when each SPLIT_FILES file holds just its own key, as the export writes it.
    const layoutMatches =
      JSON.stringify(entries) === JSON.stringify(Object.values(SPLIT_FILES)) &&
      Object.entries(SPLIT_FILES).every(([key, file]) => {
        const keys = Object.keys(asMapping(file, byName.get(file)!.raw));
        return keys.length === 1 && keys[0] === key && !(key in mainRaw);
      });
    if (!layoutMatches) {
      result.notes.push(
        `The included files are laid out differently from what this builder writes: export puts the symbols in ${SPLIT_FILES.symbols}, the participants in ${SPLIT_FILES.participants}, and everything else in the main file.`,
      );
    }
  }
  return result;
}

/** Import a single config file (no `include:` files available). */
export function parseYamlToDraft(text: string): ImportResult {
  return parseConfigFiles([{ name: "engine_config.yaml", text }]);
}

function draftFromMapping(raw: Record<string, unknown>): ImportResult {
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
  parseLocale(raw, draft);
  draft.auctionIndicativeIntervalSec =
    asNumber(raw.auction_indicative_interval_sec) ?? draft.auctionIndicativeIntervalSec;
  draft.enforceCollars = asBool(raw.enforce_collars, draft.enforceCollars);
  draft.enforceCircuitBreakers = asBool(
    raw.enforce_circuit_breakers,
    draft.enforceCircuitBreakers,
  );
  const engineTuning = isDict(raw.engine_tuning)
    ? raw.engine_tuning
    : undefined;
  draft.snapshotIntervalSec =
    asNumber(engineTuning?.snapshot_interval_sec) ?? draft.snapshotIntervalSec;
  draft.quoteHistoryMaxlen =
    asNumber(engineTuning?.quote_history_maxlen) ?? draft.quoteHistoryMaxlen;
  draft.dropCopyBufferSize =
    asNumber(engineTuning?.drop_copy_buffer_size) ?? draft.dropCopyBufferSize;
  draft.recentTradesMaxlen =
    asNumber(engineTuning?.recent_trades_maxlen) ?? draft.recentTradesMaxlen;
  draft.depthSnapshotToleranceTicks =
    asNumber(engineTuning?.depth_snapshot_tolerance_ticks) ??
    draft.depthSnapshotToleranceTicks;

  parseGatewayDefault(raw.participant_defaults, draft);
  parseGateways(raw.participants, draft);
  parseSymbols(raw.symbols, draft);
  parseMmDefaults(raw.mm_obligation_defaults, draft);
  parseRiskControls(raw.risk_controls, draft);
  parseCircuitBreakerDefaults(raw.circuit_breaker_defaults, draft);
  parseNetworkGateways(raw, draft);
  parseApiGateways(raw.api_gateways, draft);
  parseIndices(raw.indices, draft);
  parseCombos(raw.market_maker_combos, draft);
  parseSchedule(raw.schedule, draft);
  parseMonitor(raw.monitor, draft);

  for (const [key, value] of Object.entries(raw)) {
    if (!KNOWN_TOP_LEVEL_KEYS.has(key)) {
      draft.unmappedYaml[key] = value;
      unmapped.push(key);
    }
  }

  return { draft, unmapped, notes: [] };
}

/** `locale.country` / `locale.session_timezone`. */
function parseLocale(raw: Dict, draft: EngineConfigDraft): void {
  const locale = isDict(raw.locale) ? raw.locale : {};
  draft.country = asString(locale.country) ?? draft.country;
  draft.sessionTimezone = asString(locale.session_timezone) ?? draft.sessionTimezone;
}

/** The `monitor` block over its defaults; absent keys keep MonitorConfig's. */
function parseMonitor(node: unknown, draft: EngineConfigDraft): void {
  if (!isDict(node)) return;
  const m = draft.monitor;
  m.include = true;
  m.enabled = asBool(node.enabled, m.enabled);
  m.bindAddress = asString(node.bind_address) ?? m.bindAddress;
  m.host = asString(node.host) ?? m.host;
  m.pullPort = asNumber(node.pull_port) ?? m.pullPort;
  m.pubPort = asNumber(node.pub_port) ?? m.pubPort;
  m.beaconIntervalSec = asNumber(node.beacon_interval_sec) ?? m.beaconIntervalSec;
  m.hungAfterSec = asNumber(node.hung_after_sec) ?? m.hungAfterSec;
  m.silentAfterBeacons = asNumber(node.silent_after_beacons) ?? m.silentAfterBeacons;
  m.bookMetricsIntervalSec =
    asNumber(node.book_metrics_interval_sec) ?? m.bookMetricsIntervalSec;
  const retention = isDict(node.retention) ? node.retention : {};
  m.rawHours = asNumber(retention.raw_hours) ?? m.rawHours;
  m.minuteDays = asNumber(retention.minute_days) ?? m.minuteDays;
  const thresholds = isDict(node.thresholds) ? node.thresholds : {};
  for (const rule of MONITOR_THRESHOLD_RULES) {
    const band = thresholds[rule];
    if (!isDict(band)) continue;
    m.thresholds[rule] = {
      warn: asNumber(band.warn) ?? m.thresholds[rule].warn,
      crit: asNumber(band.crit) ?? m.thresholds[rule].crit,
    };
  }
}

function parseGatewayDefault(node: unknown, draft: EngineConfigDraft): void {
  if (!isDict(node)) return;
  const smp = asUpper(node.smp_action);
  if (smp) draft.gatewayDefault.smpAction = smp as SmpAction;
  const disconnect = asUpper(node.disconnect_behaviour);
  if (disconnect) {
    draft.gatewayDefault.disconnectBehaviour = disconnect as DisconnectBehaviour;
  }
}

function parseGateways(node: unknown, draft: EngineConfigDraft): void {
  if (!Array.isArray(node)) return;
  const gateways: GatewayConfig[] = [];
  for (const entry of node) {
    if (!isDict(entry)) continue;
    const id = asUpper(entry.id);
    if (!id) continue;
    const role = (asUpper(entry.role) as ParticipantRole) ?? "TRADER";
    const base = createGateway(id, role);
    // P3.9: when disconnect_behaviour is omitted, reflect the engine loader's
    // real default (CANCEL_QUOTES_ONLY for every role) rather than the
    // role-derived value createGateway() uses for freshly authored gateways.
    // This keeps import -> re-export faithful to what the engine would have done
    // with the original omitted field. With a participant_defaults value the
    // gateway keeps inheriting it instead.
    const disconnect = asUpper(entry.disconnect_behaviour);
    if (disconnect) {
      base.disconnectBehaviour = disconnect as DisconnectBehaviour;
    } else if (draft.gatewayDefault.disconnectBehaviour !== undefined) {
      delete base.disconnectBehaviour;
    } else {
      base.disconnectBehaviour = "CANCEL_QUOTES_ONLY";
    }
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
    g.maxConnections = asNumber(pt.max_connections) ?? g.maxConnections;
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
    g.maxConnections = asNumber(dc.max_connections) ?? g.maxConnections;
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

    const client = isDict(ls.client) ? ls.client : {};
    g.client = {
      connectTimeoutSec: asNumber(client.connect_timeout_sec) ?? g.client.connectTimeoutSec,
      failoverTimeoutSec: asNumber(client.failover_timeout_sec) ?? g.client.failoverTimeoutSec,
      failoverDir: asString(client.failover_dir) ?? g.client.failoverDir,
    };
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
    const optional = {
      clearingDb: asString(value.clearing_db),
      marketDataCacheSec: asNumber(value.market_data_cache_sec),
      enginePullAddr: asString(value.engine_pull_addr),
      enginePubAddr: asString(value.engine_pub_addr),
      indexPullAddr: asString(value.index_pull_addr),
      indexPubAddr: asString(value.index_pub_addr),
    };
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
      ...Object.fromEntries(
        Object.entries(optional).filter(([, v]) => v !== undefined),
      ),
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

/** The ten keys `schedule:` recognises -- mirrors config_loader's own set. */
const SCHEDULE_BLOCK_KEYS = [
  "weekdays",
  "mon",
  "tue",
  "wed",
  "thu",
  "fri",
  "sat",
  "sun",
  "weekend",
  "holidays",
] as const;

/**
 * One day block, tolerantly. A missing/malformed field falls back to
 * `DEFAULT_SCHEDULE` rather than rejecting the import -- config_loader
 * itself hard-errors on an incomplete block, but this is a best-effort GUI
 * import; diagnostics (not the parser) tell the user something is wrong.
 */
function asDaySchedule(node: unknown): NonNullable<WeeklyScheduleDraft["weekdays"]> {
  const block = isDict(node) ? node : {};
  return {
    preOpen: asHhmm(block.pre_open) ?? DEFAULT_SCHEDULE.preOpen,
    openingAuction:
      asHhmm(block.opening_auction_start) ?? DEFAULT_SCHEDULE.openingAuction,
    continuous: asHhmm(block.continuous_start) ?? DEFAULT_SCHEDULE.continuous,
    closingAuction:
      asHhmm(block.closing_auction_start) ?? DEFAULT_SCHEDULE.closingAuction,
    closingEnd: asHhmm(block.closing_auction_end) ?? DEFAULT_SCHEDULE.closingEnd,
  };
}

function parseSchedule(node: unknown, draft: EngineConfigDraft): void {
  // Presence decides emission both ways: an absent block must stay absent.
  draft.emitSchedule = isDict(node);
  if (!isDict(node)) return;
  const schedule: WeeklyScheduleDraft = {};
  for (const key of SCHEDULE_BLOCK_KEYS) {
    if (isDict(node[key])) schedule[key] = asDaySchedule(node[key]);
  }
  draft.schedule = schedule;
}

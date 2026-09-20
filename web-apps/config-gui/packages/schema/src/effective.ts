/**
 * Pure resolver that computes the *effective* configuration for a single symbol
 * — the values the engine will actually use after applying all inheritance and
 * merge rules (global defaults, risk levels, the circuit-breaker ladder, and
 * market-maker obligation precedence). Used by the read-only Symbol Overview.
 *
 * The resolution mirrors `src/edumatcher/engine/config_loader.py`:
 *   - collar: symbol.collar overrides level.collar; missing keys fall back to
 *     the engine defaults (0.20 / 0.02); a collar applies only when a level or
 *     symbol collar is present.
 *   - circuit breaker: symbol levels merge field-by-field over the defaults;
 *     reference window falls back to the global window.
 *   - MM obligation: symbol override (mm_obligation_defaults.symbols) over the
 *     global defaults; per-gateway overrides are surfaced separately.
 */

import {
  DEFAULT_ACE_EXPANSIONS,
  DEFAULT_ACE_INITIAL_BAND_PCT,
  DEFAULT_ACE_RANDOM_END_MAX_NS,
  DEFAULT_CB_LADDER,
  DEFAULT_CB_WINDOW_NS,
  DEFAULT_DYNAMIC_BAND_PCT,
  DEFAULT_MM_STUB_QTY,
  DEFAULT_STATIC_BAND_PCT,
} from "./defaults.js";
import { effectiveDefaultCollar, minutesToNs } from "./factory.js";
import type {
  CbLevel,
  EngineConfigDraft,
  GatewayMmObligationOverride,
  MmQuoteSeed,
  ReopeningConfig,
  ReopeningOverride,
  SymbolConfig,
  Tif,
} from "./types.js";

// ---- Shared market-maker seeding math (single source of truth) --------------

/** Deterministic mid-range midpoint snapped to the tick grid (arithmetic mean). */
export function seededMidpoint(
  draft: EngineConfigDraft,
  tickDecimals: number,
): number | null {
  const range = draft.seeding.mmMidRange;
  if (!range) return null;
  const tick = Math.pow(10, -tickDecimals);
  const midpoint = (range.min + range.max) / 2;
  const steps = Math.round(midpoint / tick);
  return Number((steps * tick).toFixed(tickDecimals));
}

/** One-tick-either-side quote around a midpoint, snapped to the tick grid. */
export function quoteAroundMidpoint(
  midpoint: number,
  tickDecimals: number,
): { bidPrice: number; askPrice: number } {
  const tick = Math.pow(10, -tickDecimals);
  return {
    bidPrice: Number((midpoint - tick).toFixed(tickDecimals)),
    askPrice: Number((midpoint + tick).toFixed(tickDecimals)),
  };
}

/** Seeded bid/ask for the configured mid-range, or null when no range is set. */
export function seededQuotePrices(
  draft: EngineConfigDraft,
  tickDecimals: number,
): { bidPrice: number; askPrice: number } | null {
  const midpoint = seededMidpoint(draft, tickDecimals);
  return midpoint === null ? null : quoteAroundMidpoint(midpoint, tickDecimals);
}

// ---- What the codec writes for one symbol (single source of truth) ---------
//
// The codec's build step and every read-only view call these, so what the GUI
// shows is by construction what the file says. Seeded prices are always
// snapped to the symbol's OWN tick_decimals — a symbol at 0 decimals cannot
// take a 2-decimal seed, and the engine refuses an off-grid price.

/**
 * `last_buy_price` / `last_sell_price` as written. A property that is absent
 * from the result is a key omitted from the file.
 */
export function writtenLastPrices(
  draft: EngineConfigDraft,
  config: SymbolConfig,
): { lastBuyPrice?: number | null; lastSellPrice?: number | null } {
  // Explicit per-symbol last prices always win over global seeding.
  if (config.lastBuyPrice !== undefined || config.lastSellPrice !== undefined) {
    const out: { lastBuyPrice?: number | null; lastSellPrice?: number | null } =
      {};
    if (config.lastBuyPrice !== undefined) out.lastBuyPrice = config.lastBuyPrice;
    if (config.lastSellPrice !== undefined)
      out.lastSellPrice = config.lastSellPrice;
    return out;
  }
  const midpoint = seededMidpoint(draft, config.tickDecimals);
  if (draft.seeding.seedLastPricesFromMm && midpoint !== null) {
    return { lastBuyPrice: midpoint, lastSellPrice: midpoint };
  }
  if (draft.seeding.seedLastPrices) {
    return { lastBuyPrice: null, lastSellPrice: null };
  }
  return {};
}

export type EffectiveMmQuote = MmQuoteSeed & { origin: "explicit" | "seeded" | "stub" };

/**
 * `market_maker_quotes` as written; an empty list means the key is omitted.
 *
 * Explicit quotes are written whenever the symbol has any — even with no
 * MARKET_MAKER gateway configured, where diagnostics report them rather than
 * the export silently dropping what the user can still see. Otherwise one
 * stub per MARKET_MAKER gateway, seeded from the mid-range when set; with no
 * mid-range the stubs carry null prices, and none are written at all when
 * `require_mm_seed_quotes` is off (mirrors builder.py).
 */
export function writtenMmQuotes(
  draft: EngineConfigDraft,
  config: SymbolConfig,
): EffectiveMmQuote[] {
  if (config.marketMakerQuotes && config.marketMakerQuotes.length > 0) {
    return config.marketMakerQuotes.map((q) => ({ ...q, origin: "explicit" as const }));
  }
  const mmGatewayIds = draft.gateways
    .filter((g) => g.role === "MARKET_MAKER")
    .map((g) => g.id);
  if (mmGatewayIds.length === 0) return [];
  const prices = seededQuotePrices(draft, config.tickDecimals);
  if (prices === null && !draft.requireMmSeedQuotes) return [];
  return mmGatewayIds.map((gatewayId) => ({
    gatewayId,
    bidPrice: prices?.bidPrice ?? null,
    askPrice: prices?.askPrice ?? null,
    bidQty: DEFAULT_MM_STUB_QTY,
    askQty: DEFAULT_MM_STUB_QTY,
    tif: "DAY" as Tif,
    seedOnce: true,
    origin: prices ? ("seeded" as const) : ("stub" as const),
  }));
}

// ---- Effective-symbol view --------------------------------------------------

export type ValueSource = "override" | "level" | "global" | "default";

export interface EffectiveCollar {
  applies: boolean;
  enforcedGlobally: boolean;
  staticBandPct?: number;
  staticSource?: ValueSource;
  dynamicBandPct?: number;
  dynamicSource?: ValueSource;
  /** Level name the collar was drawn from, when applicable. */
  levelName?: string;
}

/**
 * One symbol's order-size / notional caps. Configured per symbol and nowhere
 * else, so unlike a collar there is no level or engine default to fall back
 * on: `applies` is false when the symbol itself sets neither cap.
 */
export interface EffectiveOrderLimits {
  applies: boolean;
  maxOrderQty?: number;
  maxOrderValue?: number;
}

export interface EffectiveCbLevel {
  name: string;
  /**
   * Undefined only for a symbol-only level that sets no shift — the engine
   * refuses that (price_shift_pct is required), and diagnostics say so.
   */
  priceShiftPct: number | undefined;
  shiftOverridden: boolean;
  haltDurationNs: number | null;
  haltOverridden: boolean;
}

/** Resolved ACE settings for one symbol, with provenance for the UI. */
export interface EffectiveReopening {
  enabled: boolean;
  enabledOverridden: boolean;
  initialBandPct: number;
  initialBandOverridden: boolean;
  randomEndMaxNs: number;
  randomEndOverridden: boolean;
  /** Corridor half-widths after 0..n extensions, for previewing the ladder. */
  bandPctByExpansion: number[];
}

export interface EffectiveCircuitBreaker {
  /**
   * False when neither `circuit_breaker_defaults` nor the symbol's own
   * `circuit_breaker` is written: the engine then runs the symbol with no
   * circuit breaker at all.
   */
  applies: boolean;
  enforcedGlobally: boolean;
  referenceWindowNs: number;
  windowOverridden: boolean;
  /** True when no level is configured and the engine's built-in ladder applies. */
  builtInLadder: boolean;
  /** In the engine's order: ascending price shift. */
  levels: EffectiveCbLevel[];
  reopening: EffectiveReopening;
}

/** The engine's built-in ACE settings, used when circuit_breaker_defaults is absent. */
function builtInReopening(): ReopeningConfig {
  return {
    enabled: true,
    initialBandPct: DEFAULT_ACE_INITIAL_BAND_PCT,
    expansions: DEFAULT_ACE_EXPANSIONS.map((r) => ({ ...r })),
    randomEndMaxNs: DEFAULT_ACE_RANDOM_END_MAX_NS,
  };
}

/**
 * Mirrors config_loader: symbol levels merge over the defaults by level key
 * (field-by-field), the built-in ladder applies only when the merge is empty,
 * and levels are ordered by price shift.
 */
function resolveCircuitBreaker(
  draft: EngineConfigDraft,
  symbolCb: SymbolConfig["circuitBreaker"],
): EffectiveCircuitBreaker {
  const cbDefaults = draft.circuitBreakerDefaults;
  const symbolHasCb =
    symbolCb !== undefined &&
    (Object.keys(symbolCb.levels).length > 0 ||
      symbolCb.referenceWindowNs !== undefined ||
      (symbolCb.reopening !== undefined &&
        Object.keys(symbolCb.reopening).length > 0));
  const baseLevels: Record<string, CbLevel> = cbDefaults.include
    ? cbDefaults.levels
    : {};
  const names = [
    ...(cbDefaults.include ? cbDefaults.levelOrder : []),
    ...Object.keys(symbolCb?.levels ?? {}).filter(
      (n) => !(cbDefaults.include && n in baseLevels),
    ),
  ];
  let levels: EffectiveCbLevel[] = names.map((name) => {
    const g = baseLevels[name];
    const o = symbolCb?.levels[name];
    const haltOverridden = o !== undefined && o.haltDurationNs !== undefined;
    return {
      name,
      priceShiftPct: o?.priceShiftPct ?? g?.priceShiftPct,
      shiftOverridden: o?.priceShiftPct !== undefined,
      haltDurationNs: haltOverridden
        ? (o!.haltDurationNs as number | null)
        : (g?.haltDurationNs ?? null),
      haltOverridden,
    };
  });
  const builtInLadder = levels.length === 0;
  if (builtInLadder) {
    levels = DEFAULT_CB_LADDER.map((l) => ({
      name: l.name,
      priceShiftPct: l.priceShiftPct,
      shiftOverridden: false,
      haltDurationNs: minutesToNs(l.haltMinutes),
      haltOverridden: false,
    }));
  }
  levels.sort(
    (a, b) =>
      (a.priceShiftPct ?? Number.POSITIVE_INFINITY) -
      (b.priceShiftPct ?? Number.POSITIVE_INFINITY),
  );
  return {
    applies: cbDefaults.include || symbolHasCb,
    enforcedGlobally: draft.enforceCircuitBreakers,
    referenceWindowNs:
      symbolCb?.referenceWindowNs ??
      (cbDefaults.include ? cbDefaults.windowNs : DEFAULT_CB_WINDOW_NS),
    windowOverridden: symbolCb?.referenceWindowNs !== undefined,
    builtInLadder,
    levels,
    reopening: resolveReopening(
      cbDefaults.include ? cbDefaults.reopening : builtInReopening(),
      symbolCb?.reopening,
    ),
  };
}

/**
 * Corridor half-width after `n` extensions.
 *
 * Widening is additive on the reference price rather than compounding on the
 * previous width, and the ladder's final rung repeats indefinitely — which is
 * what lets the corridor eventually contain any finite price, and why there is
 * no maximum-extensions setting. Mirrors ReopeningConfig.band_pct_at() in
 * engine/circuit_breaker.py; the two must agree or the GUI previews a
 * corridor the engine will not use.
 */
export function bandPctAt(reopening: ReopeningConfig, n: number): number {
  let pct = reopening.initialBandPct;
  if (reopening.expansions.length === 0) return pct;
  for (let i = 0; i < n; i += 1) {
    const rung =
      reopening.expansions[Math.min(i, reopening.expansions.length - 1)]!;
    pct += rung.widenPct;
  }
  return pct;
}

function resolveReopening(
  global: ReopeningConfig,
  override: ReopeningOverride | undefined,
): EffectiveReopening {
  return {
    enabled: override?.enabled ?? global.enabled,
    enabledOverridden: override?.enabled !== undefined,
    initialBandPct: override?.initialBandPct ?? global.initialBandPct,
    initialBandOverridden: override?.initialBandPct !== undefined,
    randomEndMaxNs: override?.randomEndMaxNs ?? global.randomEndMaxNs,
    randomEndOverridden: override?.randomEndMaxNs !== undefined,
    bandPctByExpansion: Array.from({ length: 5 }, (_, i) =>
      bandPctAt(
        {
          ...global,
          initialBandPct: override?.initialBandPct ?? global.initialBandPct,
        },
        i,
      ),
    ),
  };
}

export interface EffectiveMmObligation {
  enforce: boolean;
  enforceOverridden: boolean;
  maxSpreadTicks: number;
  maxSpreadOverridden: boolean;
  minQty: number;
  minQtyOverridden: boolean;
  /** Per-gateway obligation overrides for this symbol, if any. */
  perGatewayOverrides: Array<{ gatewayId: string } & GatewayMmObligationOverride>;
}

export interface EffectiveSymbol {
  name: string;
  tickDecimals: number;
  lastBuyPrice: number | null;
  lastSellPrice: number | null;
  outstandingShares?: number;
  level?: string;
  levelSource: "symbol" | "default" | "none";
  collar: EffectiveCollar;
  orderLimits: EffectiveOrderLimits;
  circuitBreaker: EffectiveCircuitBreaker;
  marketMakerRelevant: boolean;
  mmObligation: EffectiveMmObligation;
  mmQuotes: EffectiveMmQuote[];
  indices: string[];
  combos: string[];
}

/**
 * The risk level a symbol resolves to and the collar that results. Exported
 * as {@link resolveEffectiveCollar} for views that need only the collar.
 */
function resolveLevelAndCollar(
  draft: EngineConfigDraft,
  config: SymbolConfig,
): {
  level: string | undefined;
  levelSource: "symbol" | "default" | "none";
  collar: EffectiveCollar;
} {
  // --- Risk level applied to the symbol -------------------------------------
  const defaultLevelName =
    draft.riskControls.defaultLevel ??
    (effectiveDefaultCollar(draft) ? "DEFAULT" : undefined);
  let level: string | undefined;
  let levelSource: "symbol" | "default" | "none";
  if (config.level) {
    level = config.level;
    levelSource = "symbol";
  } else if (defaultLevelName) {
    level = defaultLevelName;
    levelSource = "default";
  } else {
    levelSource = "none";
  }

  // --- Collar ---------------------------------------------------------------
  // A named level wins over the derived DEFAULT: the codec writes the named
  // one second, so a clash (reported by diagnostics) resolves the same way.
  let levelCollar: { staticBandPct?: number; dynamicBandPct?: number } | undefined;
  const namedLevel = level ? draft.riskControls.levels[level] : undefined;
  if (namedLevel) {
    if (
      namedLevel.staticBandPct !== undefined ||
      namedLevel.dynamicBandPct !== undefined
    ) {
      levelCollar = {
        staticBandPct: namedLevel.staticBandPct,
        dynamicBandPct: namedLevel.dynamicBandPct,
      };
    }
  } else if (level === "DEFAULT") {
    levelCollar = effectiveDefaultCollar(draft);
  }
  const symbolCollar = config.collar;
  const symbolHasCollar =
    symbolCollar?.staticBandPct !== undefined || symbolCollar?.dynamicBandPct !== undefined;

  let collar: EffectiveCollar;
  if (levelCollar === undefined && !symbolHasCollar) {
    collar = { applies: false, enforcedGlobally: draft.enforceCollars };
  } else {
    const staticFromSymbol = symbolCollar?.staticBandPct;
    const staticFromLevel = levelCollar?.staticBandPct;
    const dynFromSymbol = symbolCollar?.dynamicBandPct;
    const dynFromLevel = levelCollar?.dynamicBandPct;
    collar = {
      applies: true,
      enforcedGlobally: draft.enforceCollars,
      levelName: levelCollar ? level : undefined,
      staticBandPct: staticFromSymbol ?? staticFromLevel ?? DEFAULT_STATIC_BAND_PCT,
      staticSource:
        staticFromSymbol !== undefined ? "override" : staticFromLevel !== undefined ? "level" : "default",
      dynamicBandPct: dynFromSymbol ?? dynFromLevel ?? DEFAULT_DYNAMIC_BAND_PCT,
      dynamicSource:
        dynFromSymbol !== undefined ? "override" : dynFromLevel !== undefined ? "level" : "default",
    };
  }

  return { level, levelSource, collar };
}

/** The collar the engine applies to one symbol, with provenance. */
export function resolveEffectiveCollar(
  draft: EngineConfigDraft,
  config: SymbolConfig,
): EffectiveCollar {
  return resolveLevelAndCollar(draft, config).collar;
}

export function resolveEffectiveSymbol(
  draft: EngineConfigDraft,
  name: string,
): EffectiveSymbol | null {
  const config = draft.symbols[name];
  if (!config) return null;

  const tickDecimals = config.tickDecimals;

  const { level, levelSource, collar } = resolveLevelAndCollar(draft, config);

  // --- Order limits ---------------------------------------------------------
  // Symbol scope only: no level default, no global default, no fallback.
  const symbolLimits = config.orderLimits;
  const orderLimits: EffectiveOrderLimits =
    symbolLimits?.maxOrderQty === undefined &&
    symbolLimits?.maxOrderValue === undefined
      ? { applies: false }
      : {
          applies: true,
          maxOrderQty: symbolLimits?.maxOrderQty,
          maxOrderValue: symbolLimits?.maxOrderValue,
        };

  // --- Circuit breaker ------------------------------------------------------
  const circuitBreaker = resolveCircuitBreaker(draft, config.circuitBreaker);

  // --- Market maker ---------------------------------------------------------
  const mmQuotes = writtenMmQuotes(draft, config);
  const marketMakerRelevant =
    mmQuotes.length > 0 || draft.gateways.some((g) => g.role === "MARKET_MAKER");
  const mmDefaults = draft.mmObligationDefaults;
  const symMm = config.marketMaker;
  const mmObligation: EffectiveMmObligation = {
    enforce: symMm?.enforceMmObligation ?? mmDefaults.enforceMmObligation,
    enforceOverridden: symMm?.enforceMmObligation !== undefined,
    maxSpreadTicks: symMm?.mmMaxSpreadTicks ?? mmDefaults.mmMaxSpreadTicks,
    maxSpreadOverridden: symMm?.mmMaxSpreadTicks !== undefined,
    minQty: symMm?.mmMinQty ?? mmDefaults.mmMinQty,
    minQtyOverridden: symMm?.mmMinQty !== undefined,
    perGatewayOverrides: draft.gateways
      .filter((g) => g.mmObligations && g.mmObligations[name])
      .map((g) => ({ gatewayId: g.id, ...g.mmObligations![name]! })),
  };

  const lastPrices = writtenLastPrices(draft, config);

  return {
    name,
    tickDecimals,
    lastBuyPrice: lastPrices.lastBuyPrice ?? null,
    lastSellPrice: lastPrices.lastSellPrice ?? null,
    outstandingShares: config.outstandingShares,
    level,
    levelSource,
    collar,
    orderLimits,
    circuitBreaker,
    marketMakerRelevant,
    mmObligation,
    mmQuotes,
    indices: draft.indices.filter((i) => i.constituents.includes(name)).map((i) => i.id),
    combos: draft.combos.filter((c) => c.legs.some((l) => l.symbol === name)).map((c) => c.comboId),
  };
}

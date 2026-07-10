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
  DEFAULT_DYNAMIC_BAND_PCT,
  DEFAULT_MM_STUB_QTY,
  DEFAULT_STATIC_BAND_PCT,
} from "./defaults.js";
import { effectiveDefaultCollar } from "./factory.js";
import type {
  EngineConfigDraft,
  GatewayMmObligationOverride,
  MmQuoteSeed,
  ResumptionMode,
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

export interface EffectiveCbLevel {
  name: string;
  priceShiftPct: number;
  shiftOverridden: boolean;
  haltDurationNs: number | null;
  haltOverridden: boolean;
  resumptionMode: ResumptionMode;
  resumptionOverridden: boolean;
}

export interface EffectiveCircuitBreaker {
  enforcedGlobally: boolean;
  referenceWindowNs: number;
  windowOverridden: boolean;
  levels: EffectiveCbLevel[];
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

export type EffectiveMmQuote = MmQuoteSeed & { origin: "explicit" | "seeded" | "stub" };

export interface EffectiveSymbol {
  name: string;
  tickDecimals: number;
  tickOverridden: boolean;
  lastBuyPrice: number | null;
  lastSellPrice: number | null;
  outstandingShares?: number;
  level?: string;
  levelSource: "symbol" | "default" | "none";
  collar: EffectiveCollar;
  circuitBreaker: EffectiveCircuitBreaker;
  marketMakerRelevant: boolean;
  mmObligation: EffectiveMmObligation;
  mmQuotes: EffectiveMmQuote[];
  indices: string[];
  combos: string[];
}

export function resolveEffectiveSymbol(
  draft: EngineConfigDraft,
  name: string,
): EffectiveSymbol | null {
  const config = draft.symbols[name];
  if (!config) return null;

  const tickDecimals = config.tickDecimals;
  const tickOverridden = config.tickDecimals !== draft.tickDecimals;

  // --- Risk level applied to the symbol -------------------------------------
  const defaultLevelName =
    draft.riskControls.defaultLevel ?? (effectiveDefaultCollar(draft) ? "DEFAULT" : undefined);
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
  let levelCollar: { staticBandPct: number; dynamicBandPct: number } | undefined;
  if (level === "DEFAULT") {
    levelCollar = effectiveDefaultCollar(draft);
  } else if (level && draft.riskControls.levels[level]) {
    const l = draft.riskControls.levels[level]!;
    levelCollar = { staticBandPct: l.staticBandPct, dynamicBandPct: l.dynamicBandPct };
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

  // --- Circuit breaker ------------------------------------------------------
  const cbDefaults = draft.circuitBreakerDefaults;
  const symbolCb = config.circuitBreaker;
  const circuitBreaker: EffectiveCircuitBreaker = {
    enforcedGlobally: draft.enforceCircuitBreakers,
    referenceWindowNs: symbolCb?.referenceWindowNs ?? cbDefaults.windowNs,
    windowOverridden: symbolCb?.referenceWindowNs !== undefined,
    levels: cbDefaults.levelOrder.map((lvlName) => {
      const g = cbDefaults.levels[lvlName]!;
      const o = symbolCb?.levels[lvlName];
      const haltOverridden = o !== undefined && o.haltDurationNs !== undefined;
      return {
        name: lvlName,
        priceShiftPct: o?.priceShiftPct ?? g.priceShiftPct,
        shiftOverridden: o?.priceShiftPct !== undefined,
        haltDurationNs: haltOverridden ? (o!.haltDurationNs as number | null) : g.haltDurationNs,
        haltOverridden,
        resumptionMode: o?.resumptionMode ?? g.resumptionMode,
        resumptionOverridden: o?.resumptionMode !== undefined,
      };
    }),
  };

  // --- Market maker ---------------------------------------------------------
  const mmGatewayIds = draft.gateways
    .filter((g) => g.role === "MARKET_MAKER")
    .map((g) => g.id);
  const marketMakerRelevant = mmGatewayIds.length > 0;
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

  let mmQuotes: EffectiveMmQuote[] = [];
  if (config.marketMakerQuotes && config.marketMakerQuotes.length > 0) {
    mmQuotes = config.marketMakerQuotes.map((q) => ({ ...q, origin: "explicit" as const }));
  } else if (marketMakerRelevant) {
    // Mirror the codec's fallback: one stub per MM gateway, seeded from the
    // mid-range when configured, otherwise a null-price stub to fill in.
    const prices = seededQuotePrices(draft, draft.tickDecimals);
    mmQuotes = mmGatewayIds.map((gatewayId) => ({
      gatewayId,
      bidPrice: prices?.bidPrice ?? null,
      askPrice: prices?.askPrice ?? null,
      bidQty: DEFAULT_MM_STUB_QTY,
      askQty: DEFAULT_MM_STUB_QTY,
      tif: "DAY" as Tif,
      seedOnce: true,
      origin: prices ? "seeded" : "stub",
    }));
  }

  return {
    name,
    tickDecimals,
    tickOverridden,
    lastBuyPrice: config.lastBuyPrice ?? null,
    lastSellPrice: config.lastSellPrice ?? null,
    outstandingShares: config.outstandingShares,
    level,
    levelSource,
    collar,
    circuitBreaker,
    marketMakerRelevant,
    mmObligation,
    mmQuotes,
    indices: draft.indices.filter((i) => i.constituents.includes(name)).map((i) => i.id),
    combos: draft.combos.filter((c) => c.legs.some((l) => l.symbol === name)).map((c) => c.comboId),
  };
}

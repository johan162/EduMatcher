/**
 * Row model for the per-symbol override table.
 *
 * Kept as pure functions, separate from the React tab, for two reasons: an
 * exchange may list several hundred symbols, so filtering and paging want to
 * be cheap and memoisable; and the inherit-vs-override rules are the part
 * worth testing, which is awkward through a rendered table.
 */

import { bandPctAt } from "./effective.js";
import type { EngineConfigDraft, SymbolConfig } from "./types.js";

/** Scalar per-symbol settings the table can edit inline. */
export type OverrideField =
  | "tickDecimals"
  | "staticBandPct"
  | "dynamicBandPct"
  | "aceEnabled"
  | "aceInitialBandPct"
  | "aceRandomEndMaxNs";

/**
 * One cell: the value in force plus whether it comes from the symbol or is
 * inherited. The table greys inherited values, so this distinction is the
 * whole point of the row model rather than a display detail.
 */
export interface OverrideCell<T> {
  value: T;
  overridden: boolean;
}

export interface SymbolOverrideRow {
  symbol: string;
  tickDecimals: OverrideCell<number>;
  staticBandPct: OverrideCell<number | undefined>;
  dynamicBandPct: OverrideCell<number | undefined>;
  aceEnabled: OverrideCell<boolean>;
  aceInitialBandPct: OverrideCell<number>;
  aceRandomEndMaxNs: OverrideCell<number>;
  /** True when any field on the row deviates from the exchange default. */
  hasAnyOverride: boolean;
}

function cell<T>(
  override: T | undefined,
  inherited: T,
): OverrideCell<T> {
  return override === undefined
    ? { value: inherited, overridden: false }
    : { value: override, overridden: true };
}

export function buildOverrideRow(
  draft: EngineConfigDraft,
  symbol: string,
): SymbolOverrideRow {
  const config: SymbolConfig | undefined = draft.symbols[symbol];
  const ace = draft.circuitBreakerDefaults.reopening;
  const ro = config?.circuitBreaker?.reopening;

  const row: SymbolOverrideRow = {
    symbol,
    // tickDecimals is always present on a symbol, so it is never "inherited"
    // in the sense the other columns are.
    tickDecimals: { value: config?.tickDecimals ?? 2, overridden: false },
    staticBandPct: cell(
      config?.collar?.staticBandPct,
      draft.riskControls.globalStaticBandPct,
    ),
    dynamicBandPct: cell(
      config?.collar?.dynamicBandPct,
      draft.riskControls.globalDynamicBandPct,
    ),
    aceEnabled: cell(ro?.enabled, ace.enabled),
    aceInitialBandPct: cell(ro?.initialBandPct, ace.initialBandPct),
    aceRandomEndMaxNs: cell(ro?.randomEndMaxNs, ace.randomEndMaxNs),
    hasAnyOverride: false,
  };
  row.hasAnyOverride =
    row.staticBandPct.overridden ||
    row.dynamicBandPct.overridden ||
    row.aceEnabled.overridden ||
    row.aceInitialBandPct.overridden ||
    row.aceRandomEndMaxNs.overridden;
  return row;
}

export interface OverrideQuery {
  /** Case-insensitive substring match on the symbol name. */
  search?: string;
  /** Show only symbols that deviate from the exchange defaults. */
  onlyOverridden?: boolean;
  page: number;
  pageSize: number;
}

export interface OverridePage {
  rows: SymbolOverrideRow[];
  /** Rows matching the filter, before paging. */
  total: number;
  pageCount: number;
  /** Clamped page index — a filter change can strand you past the last page. */
  page: number;
}

export function selectOverridePage(
  draft: EngineConfigDraft,
  query: OverrideQuery,
): OverridePage {
  const needle = query.search?.trim().toUpperCase() ?? "";
  const matched: SymbolOverrideRow[] = [];
  for (const symbol of draft.symbolOrder) {
    if (needle && !symbol.toUpperCase().includes(needle)) continue;
    const row = buildOverrideRow(draft, symbol);
    if (query.onlyOverridden && !row.hasAnyOverride) continue;
    matched.push(row);
  }

  const pageSize = Math.max(1, query.pageSize);
  const pageCount = Math.max(1, Math.ceil(matched.length / pageSize));
  const page = Math.min(Math.max(0, query.page), pageCount - 1);
  const start = page * pageSize;
  return {
    rows: matched.slice(start, start + pageSize),
    total: matched.length,
    pageCount,
    page,
  };
}

/**
 * Corridor bounds a symbol would reopen inside after `n` extensions, for the
 * row's preview. Uses the symbol's effective initial band but the exchange
 * ladder, which is exactly the split the engine enforces.
 */
export function previewCorridor(
  draft: EngineConfigDraft,
  row: SymbolOverrideRow,
  referencePrice: number,
  n: number,
): { low: number; high: number } {
  const pct = bandPctAt(
    {
      ...draft.circuitBreakerDefaults.reopening,
      initialBandPct: row.aceInitialBandPct.value,
    },
    n,
  );
  return { low: referencePrice * (1 - pct), high: referencePrice * (1 + pct) };
}

/** Ensure the nested override path exists, then hand it to the mutator. */
function withReopening(
  config: SymbolConfig,
  mutate: (r: NonNullable<NonNullable<SymbolConfig["circuitBreaker"]>["reopening"]>) => void,
): void {
  config.circuitBreaker ??= { levels: {} };
  config.circuitBreaker.reopening ??= {};
  mutate(config.circuitBreaker.reopening);
  if (Object.keys(config.circuitBreaker.reopening).length === 0) {
    delete config.circuitBreaker.reopening;
  }
  // Drop an override container that no longer holds anything, so export does
  // not emit an empty `circuit_breaker:` mapping.
  const cb = config.circuitBreaker;
  if (
    Object.keys(cb.levels).length === 0 &&
    cb.referenceWindowNs === undefined &&
    cb.reopening === undefined
  ) {
    delete config.circuitBreaker;
  }
}

/**
 * Apply or clear one field on one symbol. `value === undefined` clears the
 * override so the symbol goes back to inheriting.
 *
 * Mutates in place — callers run this inside the draft store's Immer update.
 */
export function applyOverride(
  draft: EngineConfigDraft,
  symbol: string,
  field: OverrideField,
  value: number | boolean | undefined,
): void {
  const config = draft.symbols[symbol];
  if (!config) return;

  switch (field) {
    case "tickDecimals":
      if (typeof value === "number") config.tickDecimals = value;
      return;
    case "staticBandPct":
    case "dynamicBandPct": {
      config.collar ??= {};
      if (value === undefined) delete config.collar[field];
      else if (typeof value === "number") config.collar[field] = value;
      if (
        config.collar.staticBandPct === undefined &&
        config.collar.dynamicBandPct === undefined
      ) {
        delete config.collar;
      }
      return;
    }
    case "aceEnabled":
      withReopening(config, (r) => {
        if (value === undefined) delete r.enabled;
        else r.enabled = Boolean(value);
      });
      return;
    case "aceInitialBandPct":
      withReopening(config, (r) => {
        if (value === undefined) delete r.initialBandPct;
        else if (typeof value === "number") r.initialBandPct = value;
      });
      return;
    case "aceRandomEndMaxNs":
      withReopening(config, (r) => {
        if (value === undefined) delete r.randomEndMaxNs;
        else if (typeof value === "number") r.randomEndMaxNs = value;
      });
      return;
  }
}

/** Bulk form of {@link applyOverride} — the point of row selection. */
export function applyOverrideToMany(
  draft: EngineConfigDraft,
  symbols: Iterable<string>,
  field: OverrideField,
  value: number | boolean | undefined,
): void {
  for (const symbol of symbols) applyOverride(draft, symbol, field, value);
}

/** Clear every override on the given symbols, returning them to inheriting. */
export function clearOverrides(
  draft: EngineConfigDraft,
  symbols: Iterable<string>,
): void {
  for (const symbol of symbols) {
    applyOverride(draft, symbol, "staticBandPct", undefined);
    applyOverride(draft, symbol, "dynamicBandPct", undefined);
    applyOverride(draft, symbol, "aceEnabled", undefined);
    applyOverride(draft, symbol, "aceInitialBandPct", undefined);
    applyOverride(draft, symbol, "aceRandomEndMaxNs", undefined);
  }
}

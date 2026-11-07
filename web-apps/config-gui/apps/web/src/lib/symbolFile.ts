import {
  DEFAULT_OUTSTANDING_SHARES,
  deriveIpoQuote,
  type EngineConfigDraft,
  type SymbolConfig,
} from "@edumatcher/schema";
import { uppercaseId } from "./format";

/**
 * Bulk symbol import/export as CSV or JSON. A row carries exactly the IPO
 * dialog's fields and creates the symbol the dialog would. A blank optional
 * field takes the dialog's default, except mm_gateway: blank means no
 * explicit quote, so a symbol without one survives an export round trip.
 */

export const SYMBOL_FILE_COLUMNS = [
  "symbol",
  "reference_price",
  "outstanding_shares",
  "tick_decimals",
  "mm_gateway",
  "spread_ticks",
  "quote_size",
] as const;

type Column = (typeof SYMBOL_FILE_COLUMNS)[number];
type Row = Partial<Record<Column, unknown>>;

export type SymbolFileFormat = "csv" | "json";

export interface ImportedSymbol {
  name: string;
  config: SymbolConfig;
}

const isColumn = (key: string): key is Column =>
  (SYMBOL_FILE_COLUMNS as readonly string[]).includes(key);

const unquote = (cell: string): string => {
  const t = cell.trim();
  return t.length >= 2 && t.startsWith('"') && t.endsWith('"') ? t.slice(1, -1).trim() : t;
};

/** Rows keyed by the label errors use ("line 3", "entry 2"). */
function parseCsv(text: string, errors: string[]): Array<[string, Row]> {
  const lines = text.replace(/^﻿/, "").split(/\r?\n/);
  const header = (lines[0] ?? "").split(",").map(unquote);
  if (header.length === 1 && header[0] === "") {
    errors.push("The file is empty.");
    return [];
  }
  for (const [i, key] of header.entries()) {
    if (!isColumn(key)) errors.push(`Unknown column "${key}".`);
    else if (header.indexOf(key) !== i) errors.push(`Column "${key}" appears twice.`);
  }
  for (const key of ["symbol", "reference_price"]) {
    if (!header.includes(key)) errors.push(`Missing required column "${key}".`);
  }
  if (errors.length > 0) return [];

  const rows: Array<[string, Row]> = [];
  lines.slice(1).forEach((line, i) => {
    if (line.trim() === "") return;
    const label = `line ${i + 2}`;
    const cells = line.split(",").map(unquote);
    if (cells.length !== header.length) {
      errors.push(`${label}: expected ${header.length} fields, found ${cells.length}.`);
      return;
    }
    const row: Row = {};
    header.forEach((key, j) => {
      if (cells[j] !== "") row[key as Column] = cells[j];
    });
    rows.push([label, row]);
  });
  return rows;
}

function parseJson(text: string, errors: string[]): Array<[string, Row]> {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (err) {
    errors.push(`Not valid JSON: ${err instanceof Error ? err.message : String(err)}`);
    return [];
  }
  if (!Array.isArray(data)) {
    errors.push("The JSON file must hold an array of symbol objects.");
    return [];
  }
  const rows: Array<[string, Row]> = [];
  data.forEach((item: unknown, i) => {
    const label = `entry ${i + 1}`;
    if (typeof item !== "object" || item === null || Array.isArray(item)) {
      errors.push(`${label}: not an object.`);
      return;
    }
    const row: Row = {};
    for (const [key, value] of Object.entries(item)) {
      if (!isColumn(key)) errors.push(`${label}: unknown key "${key}".`);
      else if (value !== null) row[key] = value;
    }
    rows.push([label, row]);
  });
  return rows;
}

/** A number, or a string holding one; anything else is invalid. */
function toNumber(value: unknown): number | undefined | "invalid" {
  if (value === undefined) return undefined;
  const n = typeof value === "string" ? Number(value) : value;
  return typeof n === "number" && Number.isFinite(n) ? n : "invalid";
}

/**
 * Parse and validate a whole file against the draft. Any error rejects the
 * file: `symbols` is only meaningful when `errors` is empty.
 */
export function readSymbolFile(
  text: string,
  format: SymbolFileFormat,
  draft: EngineConfigDraft,
): { symbols: ImportedSymbol[]; errors: string[] } {
  const errors: string[] = [];
  const rows = format === "json" ? parseJson(text, errors) : parseCsv(text, errors);
  if (errors.length === 0 && rows.length === 0) errors.push("The file holds no symbols.");

  const mmGatewayIds = draft.gateways.filter((g) => g.role === "MARKET_MAKER").map((g) => g.id);
  const seen = new Set<string>();
  const symbols: ImportedSymbol[] = [];

  for (const [label, row] of rows) {
    const rowErrors: string[] = [];
    const int = (key: Column, min: number, max = Number.MAX_SAFE_INTEGER): number | undefined => {
      const n = toNumber(row[key]);
      if (n === undefined) return undefined;
      if (n === "invalid" || !Number.isInteger(n) || n < min || n > max) {
        rowErrors.push(`${key} must be an integer ${max === Number.MAX_SAFE_INTEGER ? `>= ${min}` : `in ${min}..${max}`}.`);
        return undefined;
      }
      return n;
    };

    const name = typeof row.symbol === "string" ? uppercaseId(row.symbol) : "";
    if (name === "") rowErrors.push("symbol is required.");
    else if (draft.symbols[name]) rowErrors.push(`symbol ${name} already exists.`);
    else if (seen.has(name)) rowErrors.push(`symbol ${name} appears more than once.`);

    const referencePrice = toNumber(row.reference_price);
    if (referencePrice === undefined || referencePrice === "invalid" || referencePrice <= 0)
      rowErrors.push("reference_price must be a number > 0.");

    const outstandingShares = int("outstanding_shares", 1) ?? DEFAULT_OUTSTANDING_SHARES;
    const tickDecimals = int("tick_decimals", 0, 8) ?? draft.tickDecimals;
    const spreadTicks = int("spread_ticks", 1);
    const quoteSize = int("quote_size", 1);

    let gateway: string | undefined;
    if (row.mm_gateway !== undefined) {
      gateway = typeof row.mm_gateway === "string" ? uppercaseId(row.mm_gateway) : "";
      if (!mmGatewayIds.includes(gateway))
        rowErrors.push(`mm_gateway "${String(row.mm_gateway)}" is not a MARKET_MAKER gateway.`);
    } else if (spreadTicks !== undefined || quoteSize !== undefined) {
      rowErrors.push("spread_ticks and quote_size need an mm_gateway.");
    }

    if (rowErrors.length > 0) {
      errors.push(...rowErrors.map((e) => `${label}: ${e}`));
      continue;
    }
    const price = referencePrice as number;
    const config: SymbolConfig = {
      tickDecimals,
      lastBuyPrice: price,
      lastSellPrice: price,
      outstandingShares,
    };
    if (gateway) config.marketMakerQuotes = [deriveIpoQuote(gateway, price, tickDecimals, spreadTicks, quoteSize)];
    seen.add(name);
    symbols.push({ name, config });
  }
  return { symbols: errors.length === 0 ? symbols : [], errors };
}

/** Append imported symbols in file order. */
export function addImportedSymbols(d: EngineConfigDraft, symbols: ImportedSymbol[]): void {
  for (const { name, config } of symbols) {
    d.symbolOrder.push(name);
    d.symbols[name] = config;
  }
}

/**
 * Write every symbol's IPO fields. A symbol the IPO fields cannot describe
 * exactly (last buy != last sell, a hand-edited or second quote, no price)
 * is written as near as they allow and named in `warnings`.
 */
export function writeSymbolFile(
  draft: EngineConfigDraft,
  format: SymbolFileFormat,
): { text: string; warnings: string[] } {
  const warnings: string[] = [];
  const rows = draft.symbolOrder.map((name) => {
    const cfg = draft.symbols[name]!;
    const ref =
      typeof cfg.lastBuyPrice === "number"
        ? cfg.lastBuyPrice
        : typeof cfg.lastSellPrice === "number"
          ? cfg.lastSellPrice
          : undefined;
    const row: Partial<Record<Column, string | number>> = {
      symbol: name,
      reference_price: ref,
      outstanding_shares: cfg.outstandingShares,
      tick_decimals: cfg.tickDecimals,
    };
    const quotes = cfg.marketMakerQuotes ?? [];
    const q = quotes[0];
    let exact = ref !== undefined && cfg.lastBuyPrice === cfg.lastSellPrice && quotes.length <= 1;
    if (q) {
      row.mm_gateway = q.gatewayId;
      row.quote_size = q.bidQty;
      const spreadTicks =
        q.bidPrice !== null && q.askPrice !== null
          ? Math.round((q.askPrice - q.bidPrice) * Math.pow(10, cfg.tickDecimals))
          : undefined;
      row.spread_ticks = spreadTicks;
      if (exact && spreadTicks !== undefined) {
        const derived = deriveIpoQuote(q.gatewayId, ref!, cfg.tickDecimals, spreadTicks, q.bidQty);
        exact =
          q.quoteId === undefined &&
          q.bidPrice === derived.bidPrice &&
          q.askPrice === derived.askPrice &&
          q.askQty === derived.askQty &&
          q.tif === derived.tif &&
          q.seedOnce === derived.seedOnce;
      } else {
        exact = false;
      }
    }
    if (!exact) warnings.push(name);
    return row;
  });

  const text =
    format === "json"
      ? JSON.stringify(rows, null, 2) + "\n"
      : [SYMBOL_FILE_COLUMNS.join(","), ...rows.map((r) => SYMBOL_FILE_COLUMNS.map((c) => r[c] ?? "").join(","))].join("\n") + "\n";
  return { text, warnings };
}

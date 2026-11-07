import {
  DEFAULT_OUTSTANDING_SHARES,
  deriveIpoQuote,
  type EngineConfigDraft,
  type SymbolConfig,
} from "@edumatcher/schema";
import { uppercaseId } from "./format";
import { readTable, toNumber, writeTable, type TableFileFormat } from "./tableFile";

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

export interface ImportedSymbol {
  name: string;
  config: SymbolConfig;
}

/**
 * Parse and validate a whole file against the draft. Any error rejects the
 * file: `items` is only meaningful when `errors` is empty.
 */
export function readSymbolFile(
  text: string,
  format: TableFileFormat,
  draft: EngineConfigDraft,
): { items: ImportedSymbol[]; errors: string[] } {
  const errors: string[] = [];
  const rows = readTable(text, format, SYMBOL_FILE_COLUMNS, ["symbol", "reference_price"], "symbol", errors);

  const mmGatewayIds = draft.gateways.filter((g) => g.role === "MARKET_MAKER").map((g) => g.id);
  const seen = new Set<string>();
  const items: ImportedSymbol[] = [];

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
    items.push({ name, config });
  }
  return { items: errors.length === 0 ? items : [], errors };
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
 * exactly is written as near as they allow and named, with the reason, in
 * `warnings`.
 */
export function writeSymbolFile(
  draft: EngineConfigDraft,
  format: TableFileFormat,
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
    const reasons: string[] = [];
    if (ref === undefined) reasons.push("no last price");
    else if (cfg.lastBuyPrice !== cfg.lastSellPrice) reasons.push("last buy and last sell prices differ");

    const quotes = cfg.marketMakerQuotes ?? [];
    const q = quotes[0];
    if (quotes.length > 1) reasons.push("more than one market-maker quote");
    if (q) {
      row.mm_gateway = q.gatewayId;
      row.quote_size = q.bidQty;
      const spreadTicks =
        q.bidPrice !== null && q.askPrice !== null
          ? Math.round((q.askPrice - q.bidPrice) * Math.pow(10, cfg.tickDecimals))
          : undefined;
      row.spread_ticks = spreadTicks;
      const derived =
        spreadTicks !== undefined && ref !== undefined
          ? deriveIpoQuote(q.gatewayId, ref, cfg.tickDecimals, spreadTicks, q.bidQty)
          : undefined;
      const matches =
        derived !== undefined &&
        q.quoteId === undefined &&
        q.bidPrice === derived.bidPrice &&
        q.askPrice === derived.askPrice &&
        q.askQty === derived.askQty &&
        q.tif === derived.tif &&
        q.seedOnce === derived.seedOnce;
      if (!matches && ref !== undefined) reasons.push("market-maker quote not derived from the reference price");
    }
    if (reasons.length > 0) warnings.push(`${name}: ${reasons.join("; ")}.`);
    return row;
  });
  return { text: writeTable(rows, SYMBOL_FILE_COLUMNS, format), warnings };
}

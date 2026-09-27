/**
 * `pm-api-gwy` REST reads (design §7, WP4): the session timezone and date,
 * today's trades, the previous close, and the symbol universe.
 *
 * All with the read-only key, which never leaves this process.
 */

import type { SymbolInfo, TapeTrade } from "@edumatcher/book-types";
import { historyRowToTrade } from "../upstream/envelope.js";

export interface HistoryOptions {
  baseUrl: string;
  apiKey: string;
  /** Injectable for tests; defaults to the global fetch. */
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

/** `/history/trades` caps `limit` at 5000. */
const PAGE = 5000;
/** How far back to look for a previous close: a long weekend or holiday is well inside it. */
const PREV_CLOSE_WINDOW_DAYS = 14;

export class HistoryError extends Error {}

export class HistoryClient {
  private readonly base: string;
  private readonly doFetch: typeof fetch;
  private readonly timeoutMs: number;

  constructor(private readonly opts: HistoryOptions) {
    this.base = opts.baseUrl.replace(/\/+$/, "");
    this.doFetch = opts.fetchImpl ?? fetch;
    this.timeoutMs = opts.timeoutMs ?? 10_000;
  }

  /** The timezone pm-stats records in, and today's trading date in it. */
  async session(): Promise<{ timezone: string; date: string }> {
    const body = await this.get("/api/v1/history/session");
    const timezone = body["session_timezone"];
    const date = body["session_date"];
    if (typeof timezone !== "string" || typeof date !== "string") {
      throw new HistoryError("malformed /history/session reply");
    }
    return { timezone, date };
  }

  /** Every trade of the trading date, following the cursor to the end. */
  async trades(sym: string, date: string): Promise<TapeTrade[]> {
    const out: TapeTrade[] = [];
    let after: string | undefined;
    do {
      const params = new URLSearchParams({ symbol: sym, date, limit: String(PAGE) });
      if (after) params.set("after", after);
      const body = await this.get(`/api/v1/history/trades?${params}`);
      for (const row of rowsOf(body, "trades")) {
        const trade = historyRowToTrade(row);
        if (trade) out.push(trade);
      }
      after =
        body["has_more"] === true && typeof body["next_cursor"] === "string"
          ? body["next_cursor"]
          : undefined;
    } while (after);
    return out;
  }

  /** The newest non-null close strictly before `date`, if there is one. */
  async previousClose(sym: string, date: string): Promise<number | undefined> {
    const from = new Date(Date.parse(`${date}T00:00:00Z`) - PREV_CLOSE_WINDOW_DAYS * 86_400_000)
      .toISOString()
      .slice(0, 10);
    const params = new URLSearchParams({ symbol: sym, from });
    const body = await this.get(`/api/v1/history/daily?${params}`);
    let best: { date: string; close: number } | undefined;
    for (const row of rowsOf(body, "daily")) {
      const rowDate = row["date"];
      const close = row["close_price"];
      // ISO dates: string order is date order.
      if (typeof rowDate !== "string" || rowDate >= date) continue;
      if (typeof close !== "number" || !Number.isFinite(close)) continue;
      if (!best || rowDate > best.date) best = { date: rowDate, close };
    }
    return best?.close;
  }

  async symbols(): Promise<SymbolInfo[]> {
    const body = await this.get("/api/v1/reference/symbols");
    const out: SymbolInfo[] = [];
    for (const row of rowsOf(body, "symbols")) {
      const symbol = row["symbol"];
      const dec = row["tick_decimals"];
      if (typeof symbol === "string" && typeof dec === "number") out.push({ symbol, tickDecimals: dec });
    }
    return out;
  }

  private async get(path: string): Promise<Record<string, unknown>> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const res = await this.doFetch(`${this.base}${path}`, {
        headers: { Authorization: `Bearer ${this.opts.apiKey}` },
        signal: controller.signal,
      });
      if (!res.ok) throw new HistoryError(`${path.split("?")[0]} answered HTTP ${res.status}`);
      return (await res.json()) as Record<string, unknown>;
    } catch (err) {
      if (err instanceof HistoryError) throw err;
      throw new HistoryError(`${path.split("?")[0]} unreachable: ${String(err)}`);
    } finally {
      clearTimeout(timer);
    }
  }
}

function rowsOf(body: Record<string, unknown>, key: string): Record<string, unknown>[] {
  const rows = body[key];
  return Array.isArray(rows)
    ? rows.filter((r): r is Record<string, unknown> => typeof r === "object" && r !== null)
    : [];
}

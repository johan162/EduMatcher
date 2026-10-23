import { describe, expect, it } from "vitest";
import type { TradeRow } from "@edumatcher/terminal-types";
import { perMinute } from "../src/lib/minute-buckets.js";

const trade = (ts: string, price: number, quantity: number): TradeRow => ({
  ts,
  trade_id: ts,
  symbol: "AAPL",
  price,
  quantity,
  buy_gateway_id: null,
  sell_gateway_id: null,
});

describe("perMinute", () => {
  it("counts prints and sums traded value per epoch minute", () => {
    const out = perMinute([
      trade("2026-07-30T10:00:05Z", 10, 100),
      trade("2026-07-30T10:00:55Z", 11, 50),
      trade("2026-07-30T10:02:00Z", 12, 10),
    ]);
    const t0 = Date.parse("2026-07-30T10:00:00Z") / 1000;
    expect(out.trades).toEqual([
      { time: t0, value: 2 },
      { time: t0 + 120, value: 1 },
    ]);
    expect(out.value).toEqual([
      { time: t0, value: 1550 },
      { time: t0 + 120, value: 120 },
    ]);
  });

  it("leaves a minute without prints out, and skips unreadable rows", () => {
    const out = perMinute([trade("not a time", 10, 1), trade("2026-07-30T10:00:00Z", Number.NaN, 1)]);
    expect(out).toEqual({ trades: [], value: [] });
  });
});

/**
 * The upstream codec against real `pm-api-gwy` captures (WP0 fixtures) and
 * the edge cases the gateway is known to produce.
 */

import { describe, expect, it } from "vitest";
import bookCapture from "./fixtures/book.json";
import tradeCapture from "./fixtures/trade.json";
import historyCapture from "./fixtures/history-trades.json";
import {
  historyRowToTrade,
  parseEnvelope,
  resumeTradesFrame,
  subscribeFrame,
  toBookFrame,
  toLevels,
  toLiveTrade,
  unsubscribeFrame,
} from "../src/upstream/envelope.js";

describe("real captures", () => {
  it("decodes a captured book into the full ladder", () => {
    const env = parseEnvelope(JSON.stringify(bookCapture))!;
    const frame = toBookFrame(env, 2)!;
    expect(frame.sym).toBe("MSFT");
    expect(frame.seq).toBe(bookCapture.seq);
    expect(frame.tickDecimals).toBe(2);
    expect(frame.bids).toEqual(bookCapture.data.bids);
    expect(frame.asks).toEqual(bookCapture.data.asks);
    expect(frame.last).toBe(bookCapture.data.last_price);
    expect(frame.lastQty).toBe(bookCapture.data.last_qty);
  });

  it("decodes a captured print, to the millisecond", () => {
    const env = parseEnvelope(JSON.stringify(tradeCapture))!;
    expect(env.seq).toBe(3);
    expect(toLiveTrade(env.data)).toEqual({
      sym: "MSFT",
      trade: { id: "000001-000000003", tsMs: 1790529672341, px: 93.42, qty: 5, side: "SELL" },
    });
  });

  it("gives a live print and its history row the same trade id — what de-duplication keys on", () => {
    const live = toLiveTrade(tradeCapture.data)!.trade;
    const history = historyRowToTrade(historyCapture.trades[0] as Record<string, unknown>)!;
    expect(history.id).toBe(live.id);
    expect(history).toEqual({ ...live, tsMs: Date.parse("2026-09-27T17:21:12.341+00:00") });
  });
});

describe("edge cases", () => {
  it("rejects non-envelopes rather than throwing", () => {
    expect(parseEnvelope("not json")).toBeUndefined();
    expect(parseEnvelope("[1,2]")).toBeUndefined();
    expect(parseEnvelope('{"data":{}}')).toBeUndefined();
    expect(parseEnvelope('{"type":"x"}')).toEqual({ type: "x", data: {}, topic: undefined, seq: undefined });
  });

  it("keeps a never-traded symbol's last price absent, not zero", () => {
    const frame = toBookFrame(
      {
        type: "book",
        seq: 1,
        data: { symbol: "aapl", bids: [], asks: [], last_price: null, last_qty: null },
      },
      3,
    )!;
    expect(frame).toEqual({ type: "book", sym: "AAPL", seq: 1, tickDecimals: 3, bids: [], asks: [] });
  });

  it("skips a malformed level instead of discarding the ladder", () => {
    expect(
      toLevels([{ price: 1, qty: 2, count: 3 }, { price: "x", qty: 1 }, null, { price: 2, qty: 5 }]),
    ).toEqual([
      { price: 1, qty: 2, count: 3 },
      { price: 2, qty: 5, count: 0 },
    ]);
    expect(toLevels(undefined)).toEqual([]);
  });

  it("ignores prints and books without an id or symbol", () => {
    expect(toLiveTrade({ symbol: "A", price: 1, quantity: 1 })).toBeUndefined();
    expect(toBookFrame({ type: "book", data: {} }, 2)).toBeUndefined();
    expect(historyRowToTrade({ trade_id: "x", price: 1, quantity: 1 })).toBeUndefined();
  });

  it("maps an unknown aggressor side to empty", () => {
    expect(
      toLiveTrade({ id: "1", symbol: "A", price: 1, quantity: 1, aggressor_side: "??" })!.trade.side,
    ).toBe("");
  });
});

describe("control frames", () => {
  it("subscribes one symbol per item, with an optional trade replay hint", () => {
    expect(JSON.parse(subscribeFrame("AAPL"))).toEqual({
      action: "subscribe",
      items: [{ symbols: ["AAPL"], channels: ["book", "trades"] }],
    });
    expect(JSON.parse(subscribeFrame("AAPL", 42)).items[0].resume_from).toEqual({ trades: 42 });
    expect(JSON.parse(unsubscribeFrame("AAPL")).action).toBe("unsubscribe");
    expect(JSON.parse(resumeTradesFrame("AAPL", 7))).toEqual({
      action: "resume",
      topic: "trade.executed",
      symbols: ["AAPL"],
      from_seq: 7,
    });
  });
});

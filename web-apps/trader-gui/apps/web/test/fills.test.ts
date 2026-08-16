import { describe, it, expect } from "vitest";
import {
  fillRowFromEvent,
  fillRowFromHistory,
  filterFillRowsBySide,
  mergeFillRows,
} from "@/lib/fills";
import type { Fill, OrderHistoryEvent } from "@/types/index";

function historyFill(patch: Partial<OrderHistoryEvent> = {}): OrderHistoryEvent {
  return {
    seq: 1,
    ts: "2026-07-27T10:00:00.000Z",
    event_type: "FILL",
    order_id: "o1",
    gateway_id: "GW1",
    symbol: "AAPL",
    side: "BUY",
    order_type: "LIMIT",
    tif: "DAY",
    price: 150,
    quantity: 100,
    remaining_qty: 60,
    status: "PARTIAL",
    fill_price: 150.5,
    fill_qty: 40,
    trade_id: "t-100",
    reason: null,
    client_order_id: null,
    combo_parent_id: null,
    oco_group_id: null,
    priority_reset: null,
    ...patch,
  };
}

function liveFill(patch: Partial<Fill> = {}): Fill {
  return {
    gateway_id: "GW1",
    order_id: "o2",
    fill_qty: 25,
    fill_price: 151.0,
    remaining_qty: 0,
    status: "FILLED",
    trade_ids: ["t-200"],
    symbol: "AAPL",
    side: "SELL",
    ...patch,
  };
}

describe("fillRowFromHistory (§13.5)", () => {
  it("maps an order_events FILL row (single trade_id, no +N)", () => {
    const r = fillRowFromHistory(historyFill());
    expect(r).toMatchObject({
      symbol: "AAPL",
      side: "BUY",
      fillQty: 40,
      fillPrice: 150.5,
      remaining: 60,
      tradeId: "t-100",
      extraTradeCount: 0,
      orderId: "o1",
      live: false,
    });
  });

  it("coerces an unexpected side string to null", () => {
    expect(fillRowFromHistory(historyFill({ side: "AUCTION" as unknown as string })).side).toBeNull();
  });
});

describe("fillRowFromEvent (§13.5.1)", () => {
  it("reads trade_ids[0] and badges +N for a swept VWAP fill", () => {
    const r = fillRowFromEvent(liveFill({ trade_ids: ["a", "b", "c"] }), 1_700_000_000_000);
    expect(r.tradeId).toBe("a");
    expect(r.extraTradeCount).toBe(2);
    expect(r.live).toBe(true);
  });

  it("has no trade id for a fill with no trade behind it", () => {
    const r = fillRowFromEvent(liveFill({ trade_ids: [] }));
    expect(r.tradeId).toBeNull();
    expect(r.extraTradeCount).toBe(0);
  });
});

describe("mergeFillRows", () => {
  it("drops a live row whose trade id already appears in history (dedup)", () => {
    const history = [fillRowFromHistory(historyFill({ trade_id: "dup" }))];
    const live = [fillRowFromEvent(liveFill({ trade_ids: ["dup"] }))];
    expect(mergeFillRows(live, history)).toHaveLength(1);
  });

  it("keeps a live row with a distinct trade id, ahead of history", () => {
    const history = [fillRowFromHistory(historyFill({ trade_id: "old" }))];
    const live = [fillRowFromEvent(liveFill({ trade_ids: ["new"] }))];
    const merged = mergeFillRows(live, history);
    expect(merged).toHaveLength(2);
    expect(merged[0]!.live).toBe(true); // live rows first
  });

  it("always keeps a live row that has no trade id", () => {
    const history = [fillRowFromHistory(historyFill({ trade_id: "x" }))];
    const live = [fillRowFromEvent(liveFill({ trade_ids: [] }))];
    expect(mergeFillRows(live, history)).toHaveLength(2);
  });
});

describe("filterFillRowsBySide (§13.5.3)", () => {
  const rows = [
    fillRowFromHistory(historyFill({ side: "BUY", trade_id: "b" })),
    fillRowFromHistory(historyFill({ side: "SELL", trade_id: "s" })),
  ];
  it("ALL keeps everything", () => expect(filterFillRowsBySide(rows, "ALL")).toHaveLength(2));
  it("BUY keeps only buys", () => {
    const r = filterFillRowsBySide(rows, "BUY");
    expect(r).toHaveLength(1);
    expect(r[0]!.side).toBe("BUY");
  });
});

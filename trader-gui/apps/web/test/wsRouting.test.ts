import { describe, it, expect, beforeEach, vi } from "vitest";
import { ManagedSocket, type WebSocketLike } from "@/ws/ManagedSocket";
import {
  __marketDataMessageForTest as route,
  __setMarketDataSocketForTest,
  getSubscriptionPlan,
  getAppliedPairs,
  setFocusSymbols,
  setOverviewSubscription,
  wsOn,
} from "@/ws/WebSocketManager";
import { useBookStore } from "@/store/useBookStore";
import { useSessionStore } from "@/store/useSessionStore";
import { useHaltStore } from "@/store/useHaltStore";
import { useNotificationStore } from "@/store/useNotificationStore";

class FakeSocket implements WebSocketLike {
  static last: FakeSocket | null = null;
  readyState = 1;
  sent: string[] = [];
  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  onclose: ((ev: { code?: number }) => void) | null = null;
  constructor() {
    FakeSocket.last = this;
  }
  send(data: string): void {
    this.sent.push(data);
  }
  close(): void {
    this.readyState = 3;
  }
  get frames(): Record<string, unknown>[] {
    return this.sent.map((s) => JSON.parse(s) as Record<string, unknown>);
  }
}

/** An authenticated ManagedSocket over a fake transport. */
function installSocket(): FakeSocket {
  const socket = new ManagedSocket("ws://test/market-data", {
    authFrame: () => ({ api_key: "k" }),
    factory: () => new FakeSocket(),
  });
  socket.connect();
  const fake = FakeSocket.last!;
  fake.onopen?.({});
  fake.onmessage?.({ data: JSON.stringify({ type: "authenticated" }) });
  __setMarketDataSocketForTest(socket);
  fake.sent = []; // discard the auth frame
  return fake;
}

const bookEvent = (symbol: string, seq: number) => ({
  type: "book",
  topic: `book.${symbol}`,
  ts: "2026-08-12T09:30:00Z",
  seq,
  data: {
    symbol,
    tick_decimals: 2,
    bids: [{ price: 150, qty: 100, count: 1 }],
    asks: [{ price: 150.1, qty: 200, count: 2 }],
    recent_trades: [],
    last_price: 150.05,
    last_qty: 50,
    last_buy_price: null,
    last_sell_price: null,
  },
});

beforeEach(() => {
  useBookStore.setState({ books: {} });
  useHaltStore.setState({ halts: {} });
  useNotificationStore.setState({ entries: [], unread: 0 });
  useSessionStore.setState({
    phase: "CLOSED",
    prevPhase: null,
    phaseSince: null,
    nextTransitionAt: null,
    nextState: null,
    schedule: null,
  });
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

describe("market-data routing", () => {
  it("folds book, depth, trade and auction events into the book store", () => {
    installSocket();
    route(bookEvent("AAPL", 1));
    route({
      type: "depth",
      topic: "depth.AAPL",
      ts: "",
      seq: 1,
      data: { symbol: "AAPL", mid_price: 150.05, imbalance: 0.1 },
    });
    route({
      type: "trade",
      topic: "trade.executed",
      ts: "",
      seq: 1,
      data: { id: "t1", symbol: "AAPL", price: 151, quantity: 25, tick_decimals: 2 },
    });
    route({
      type: "auction.indicative",
      topic: "auction.indicative.AAPL",
      ts: "",
      seq: 1,
      data: {
        symbol: "AAPL",
        phase: "OPENING_AUCTION",
        eq_price: 150.5,
        eq_qty: 5000,
        imbalance_side: "BUY",
        imbalance_qty: 500,
      },
    });

    const entry = useBookStore.getState().books["AAPL"]!;
    expect(entry.bids[0]!.price).toBe(150);
    expect(entry.depth?.mid_price).toBe(150.05);
    expect(entry.lastPrice).toBe(151); // the trade, not the stale book snapshot
    expect(entry.recentTrades).toHaveLength(1);
    expect(entry.auction).toMatchObject({ eqPrice: 150.5, indicative: true });
  });

  it("routes a session event into the store and the event centre", () => {
    installSocket();
    route({
      type: "session",
      topic: "session.state",
      ts: "",
      data: {
        state: "CONTINUOUS",
        prev_state: "OPENING_AUCTION",
        next: { state: "CLOSING_AUCTION", at: "2099-01-01T17:20:00Z" },
      },
    });
    const s = useSessionStore.getState();
    expect(s.phase).toBe("CONTINUOUS");
    expect(s.prevPhase).toBe("OPENING_AUCTION");
    expect(s.nextState).toBe("CLOSING_AUCTION");
    expect(useNotificationStore.getState().unread).toBe(1);
  });

  it("discriminates circuit-breaker halt from resume on the topic", () => {
    installSocket();
    route({
      type: "circuit_breaker",
      topic: "circuit_breaker.halt.AAPL",
      ts: "",
      data: { symbol: "AAPL", level: "L2", resume_at_ns: null },
    });
    expect(useHaltStore.getState().isHalted("AAPL")).toBe(true);

    route({
      type: "circuit_breaker",
      topic: "circuit_breaker.resume.AAPL",
      ts: "",
      data: { symbol: "AAPL", reason: "TIMER" },
    });
    expect(useHaltStore.getState().isHalted("AAPL")).toBe(false);
  });
});

describe("seq gap repair", () => {
  it("sends one targeted resume for a gap, not a re-subscribe storm", () => {
    const fake = installSocket();
    route(bookEvent("AAPL", 10));
    route(bookEvent("AAPL", 14));

    expect(fake.frames).toEqual([
      { action: "resume", topic: "book.AAPL", from_seq: 10, symbols: ["AAPL"] },
    ]);

    // A second gapped event on the same topic while the resume is in flight
    // must not produce a second resume.
    route(bookEvent("AAPL", 20));
    expect(fake.frames).toHaveLength(1);
  });

  it("names the symbol for the venue-wide trades topic", () => {
    const fake = installSocket();
    setFocusSymbols(["AAPL"]);
    fake.sent = [];
    const trade = (seq: number) => ({
      type: "trade",
      topic: "trade.executed",
      ts: "",
      seq,
      data: { id: `t${seq}`, symbol: "AAPL", price: 1, quantity: 1, tick_decimals: 2 },
    });
    route(trade(1));
    route(trade(5));
    // `trade.executed` carries no symbol in the topic, so the server needs it
    // in `symbols` — but the topic itself has none to derive.
    expect(fake.frames[0]).toEqual({ action: "resume", topic: "trade.executed", from_seq: 1 });
  });

  it("falls back to a snapshot when the resume is rejected", () => {
    const fake = installSocket();
    route(bookEvent("AAPL", 10));
    route(bookEvent("AAPL", 14));
    fake.sent = [];

    route({
      type: "resume.rejected",
      topic: "",
      ts: "",
      data: { topic: "book.AAPL", from_seq: 10, reason: "too_old" },
    });
    expect(fake.frames).toEqual([{ action: "snapshot", symbols: ["AAPL"], channels: ["book"] }]);
  });

  it("clears the cached tape on trades.reset", () => {
    installSocket();
    route({
      type: "trade",
      topic: "trade.executed",
      ts: "",
      seq: 1,
      data: { id: "t1", symbol: "AAPL", price: 1, quantity: 1, tick_decimals: 2 },
    });
    expect(useBookStore.getState().books["AAPL"]!.recentTrades).toHaveLength(1);

    route({
      type: "trades.reset",
      topic: "trade.executed",
      ts: "",
      data: { symbol: "AAPL" },
    });
    expect(useBookStore.getState().books["AAPL"]!.recentTrades).toHaveLength(0);
  });

  it("treats a control frame as neither market data nor a seq source", () => {
    const fake = installSocket();
    const seen: unknown[] = [];
    const off = wsOn("subscription", (e) => seen.push(e));
    route({
      type: "subscription",
      topic: "",
      ts: "",
      data: { items: [], rejected: [{ reason: "no_channels" }] },
    });
    expect(seen).toHaveLength(1);
    expect(fake.frames).toHaveLength(0);
    off();
  });
});

describe("subscription plan", () => {
  it("sends only the delta when the focus symbol changes", () => {
    const fake = installSocket();
    // First sync declares the whole plan: the broad wildcard item plus the
    // focus item. Symbols sharing a channel set collapse into one item.
    setFocusSymbols(["AAPL"]);
    expect(fake.frames).toEqual([
      {
        action: "subscribe",
        items: [
          { symbols: ["*"], channels: ["book", "trades"] },
          { symbols: ["AAPL"], channels: ["auction", "depth"] },
        ],
      },
    ]);

    fake.sent = [];
    setFocusSymbols(["MSFT"]);
    // Unsubscribe precedes subscribe so the heavy-channel fan-out never
    // transiently doubles.
    expect(fake.frames).toEqual([
      { action: "unsubscribe", items: [{ symbols: ["AAPL"], channels: ["auction", "depth"] }] },
      { action: "subscribe", items: [{ symbols: ["MSFT"], channels: ["auction", "depth"] }] },
    ]);
  });

  it("sends nothing when the focus set is unchanged", () => {
    const fake = installSocket();
    setFocusSymbols(["AAPL", "MSFT"]);
    fake.sent = [];
    setFocusSymbols(["aapl", "MSFT"]);
    expect(fake.frames).toHaveLength(0);
  });

  it("caps the focus set", () => {
    installSocket();
    setFocusSymbols(Array.from({ length: 40 }, (_, i) => `SYM${i}`));
    expect(getSubscriptionPlan().focus).toHaveLength(25);
  });

  it("drops the wildcard item when the overview is disabled", () => {
    const fake = installSocket();
    setFocusSymbols(["AAPL"]);
    fake.sent = [];
    setOverviewSubscription(false);
    expect(getAppliedPairs().some((p) => p.startsWith("*|"))).toBe(false);
    // …and the focus item widens to cover book/trades itself.
    expect(getAppliedPairs().sort()).toEqual([
      "AAPL|auction",
      "AAPL|book",
      "AAPL|depth",
      "AAPL|trades",
    ]);
    setOverviewSubscription(true);
  });
});

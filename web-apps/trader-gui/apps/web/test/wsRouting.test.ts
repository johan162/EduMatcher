import { describe, it, expect, beforeEach, vi } from "vitest";
import { ManagedSocket, type WebSocketLike } from "@/ws/ManagedSocket";

// H5: WebSocketManager resyncs session + halts via REST on every market-data
// "authenticated" -- stub the REST layer so `installSocket()` (used by nearly
// every test in this file) never makes a real network call.
vi.mock("@/api/endpoints", () => ({
  getSession: vi.fn(),
  getHalts: vi.fn(),
}));

import {
  __marketDataMessageForTest as route,
  __setMarketDataSocketForTest,
  __privateMessageForTest as routePrivate,
  __setEventsSocketForTest,
  __getEventsSocketForTest,
  getSubscriptionPlan,
  getAppliedPairs,
  setFocusSymbols,
  setOverviewSubscription,
  wsOn,
} from "@/ws/WebSocketManager";
import { useBookStore, __resetTradeDedupForTest } from "@/store/useBookStore";
import { useSessionStore } from "@/store/useSessionStore";
import { useHaltStore } from "@/store/useHaltStore";
import { useNotificationStore } from "@/store/useNotificationStore";
import { getSession, getHalts } from "@/api/endpoints";

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

/** An authenticated ManagedSocket over a fake transport, for the events socket. */
function installEventsSocket(): FakeSocket {
  const socket = new ManagedSocket("ws://test/events", {
    authFrame: () => ({ api_key: "k" }),
    factory: () => new FakeSocket(),
  });
  socket.connect();
  const fake = FakeSocket.last!;
  fake.onopen?.({});
  fake.onmessage?.({ data: JSON.stringify({ type: "authenticated" }) });
  __setEventsSocketForTest(socket);
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
  __resetTradeDedupForTest();
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
  vi.mocked(getSession).mockReset().mockResolvedValue({ state: "CLOSED", sessions_enabled: true });
  vi.mocked(getHalts).mockReset().mockResolvedValue({ halted: [] });
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

  // H2 (docs-design/reviews/EduMatcher-Trader-GUI-Review.md): a market-data
  // reconnect or gap repair redelivers prints already processed --
  // SeqTracker.observe correctly reports these as "not a gap", but the
  // envelope must not reach the bus or the book store a second time.
  it("does not deliver a replayed trade id twice", () => {
    installSocket();
    const seen: unknown[] = [];
    wsOn("trade", (env) => seen.push(env));
    const t = {
      type: "trade",
      topic: "trade.executed",
      ts: "",
      seq: 1,
      data: { id: "t1", symbol: "AAPL", price: 151, quantity: 25, tick_decimals: 2 },
    };
    route(t);
    route(t); // replayed -- same id
    expect(seen).toHaveLength(1);
    expect(useBookStore.getState().books["AAPL"]!.recentTrades).toHaveLength(1);
  });

  // H2: emit() used to let one handler's exception abort every
  // later-registered handler for that envelope AND the switch below it in
  // handleMarketDataMessage -- recordTrade runs after emit(), so a faulty
  // bus listener silently dropped live trades from the book store too.
  it("isolates a bus handler's exception from the rest of the bus and from recordTrade", () => {
    installSocket();
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const seen: unknown[] = [];
    const unsubscribeThrower = wsOn("trade", () => {
      throw new Error("boom");
    });
    wsOn("trade", (env) => seen.push(env));
    route({
      type: "trade",
      topic: "trade.executed",
      ts: "",
      seq: 1,
      data: { id: "t1", symbol: "AAPL", price: 151, quantity: 25, tick_decimals: 2 },
    });
    expect(seen).toHaveLength(1);
    expect(useBookStore.getState().books["AAPL"]!.recentTrades).toHaveLength(1);
    expect(errSpy).toHaveBeenCalled();
    unsubscribeThrower();
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

describe("SeqTracker forgets unsubscribed topics on re-focus (L5)", () => {
  it("does not treat the first envelope after a re-focus as a gap", () => {
    const fake = installSocket();
    setFocusSymbols(["AAPL"]);
    fake.sent = [];

    // AAPL's depth channel advances to seq 5 while focused.
    route({
      type: "depth",
      topic: "depth.AAPL",
      ts: "",
      seq: 5,
      data: { symbol: "AAPL", mid_price: 150.05, imbalance: 0.1 },
    });

    // Un-focus AAPL (unsubscribes its depth/auction pair) and re-focus it.
    // The server's own depth.AAPL counter keeps advancing in the meantime,
    // so seq 8 -- not 6 -- is the first envelope the client actually
    // receives once it resubscribes.
    setFocusSymbols(["MSFT"]);
    setFocusSymbols(["AAPL"]);
    fake.sent = [];

    route({
      type: "depth",
      topic: "depth.AAPL",
      ts: "",
      seq: 8,
      data: { symbol: "AAPL", mid_price: 150.1, imbalance: 0.1 },
    });

    // Regression for L5: a stale high-water mark surviving the unsubscribe
    // would read this as "6 and 7 were missed" and fire a needless resume
    // for a topic that was just freshly (re)subscribed.
    expect(fake.frames).toHaveLength(0);
  });

  it("also forgets both auction topics (result and indicative) on unsubscribe", () => {
    const fake = installSocket();
    setFocusSymbols(["AAPL"]);
    fake.sent = [];
    route({
      type: "auction.result",
      topic: "auction.result.AAPL",
      ts: "",
      seq: 3,
      data: { symbol: "AAPL", price: 150, quantity: 100 },
    });
    route({
      type: "auction.indicative",
      topic: "auction.indicative.AAPL",
      ts: "",
      seq: 3,
      data: { symbol: "AAPL", price: 150, quantity: 100 },
    });

    setFocusSymbols(["MSFT"]);
    setFocusSymbols(["AAPL"]);
    fake.sent = [];

    route({
      type: "auction.result",
      topic: "auction.result.AAPL",
      ts: "",
      seq: 6,
      data: { symbol: "AAPL", price: 151, quantity: 100 },
    });
    route({
      type: "auction.indicative",
      topic: "auction.indicative.AAPL",
      ts: "",
      seq: 6,
      data: { symbol: "AAPL", price: 151, quantity: 100 },
    });

    expect(fake.frames).toHaveLength(0);
  });

  it("still detects a real gap on a topic that stayed subscribed throughout", () => {
    const fake = installSocket();
    setFocusSymbols(["AAPL"]);
    fake.sent = [];
    route({
      type: "depth",
      topic: "depth.AAPL",
      ts: "",
      seq: 1,
      data: { symbol: "AAPL", mid_price: 150.05, imbalance: 0.1 },
    });
    route({
      type: "depth",
      topic: "depth.AAPL",
      ts: "",
      seq: 4,
      data: { symbol: "AAPL", mid_price: 150.2, imbalance: 0.1 },
    });
    expect(fake.frames).toEqual([
      { action: "resume", topic: "depth.AAPL", from_seq: 1, symbols: ["AAPL"] },
    ]);
  });
});

describe("session/halts resync on authenticate (H5, H4)", () => {
  // `installSocket()`'s FakeSocket is a standalone ManagedSocket used only to
  // exercise subscribe/resume framing (§17.3.1) -- it is never wired via
  // `.on(handleMarketDataMessage)`, so its own "authenticated" delivery does
  // not reach the routing under test. `route()` (== handleMarketDataMessage)
  // is what every test in this file uses to simulate an incoming envelope,
  // "authenticated" included.

  it("applies the fetched session phase and halts on every authenticate", async () => {
    vi.mocked(getSession).mockResolvedValue({ state: "CONTINUOUS", sessions_enabled: true });
    vi.mocked(getHalts).mockResolvedValue({
      halted: [{ symbol: "AAPL", level: "L1", resume_at_ns: null }],
    });

    installSocket();
    route({ type: "authenticated" });

    await vi.waitFor(() => {
      expect(useSessionStore.getState().phase).toBe("CONTINUOUS");
      expect(useHaltStore.getState().isHalted("AAPL")).toBe(true);
    });
  });

  it("re-syncs on a reconnect's fresh authenticate, replacing stale halts", async () => {
    installSocket();
    vi.mocked(getHalts).mockResolvedValue({
      halted: [{ symbol: "AAPL", level: "L1", resume_at_ns: null }],
    });
    route({ type: "authenticated" });
    await vi.waitFor(() => expect(useHaltStore.getState().isHalted("AAPL")).toBe(true));

    // AAPL resumed and MSFT halted while disconnected; the reconnect's
    // "authenticated" is the only thing that can catch the GUI up.
    vi.mocked(getHalts).mockResolvedValue({
      halted: [{ symbol: "MSFT", level: "L1", resume_at_ns: null }],
    });
    route({ type: "authenticated" });

    await vi.waitFor(() => {
      expect(useHaltStore.getState().isHalted("AAPL")).toBe(false);
      expect(useHaltStore.getState().isHalted("MSFT")).toBe(true);
    });
  });

  it("logs but does not throw when the session/halts resync fails", async () => {
    installSocket();
    vi.mocked(getSession).mockRejectedValue(new Error("engine timeout"));
    vi.mocked(getHalts).mockRejectedValue(new Error("engine timeout"));
    vi.mocked(console.warn).mockClear();

    expect(() => route({ type: "authenticated" })).not.toThrow();

    await vi.waitFor(() => {
      expect(console.warn).toHaveBeenCalledWith(
        expect.stringContaining("session resync failed"),
        expect.any(Error),
      );
      expect(console.warn).toHaveBeenCalledWith(
        expect.stringContaining("halts resync failed"),
        expect.any(Error),
      );
    });
  });
});

describe("private-stream stream_seq gap detection (H6)", () => {
  // routers/ws.py numbers every private-stream frame -- authenticated,
  // orders.snapshot, and every order.*/fill/quote event -- with a
  // connection-wide stream_seq that still advances when the bounded queue
  // drops an event under backpressure. There is no per-topic resume for
  // this stream (unlike market data): the repair is to close the socket
  // and open a new one, whose fresh orders.snapshot is the reconciliation.

  it("does not reconnect when stream_seq is contiguous", () => {
    installEventsSocket();
    const before = __getEventsSocketForTest();
    routePrivate({ type: "authenticated", topic: "", ts: "", stream_seq: 1, data: {} });
    routePrivate({ type: "orders.snapshot", topic: "", ts: "", stream_seq: 2, data: {} });
    routePrivate({ type: "order.ack", topic: "order.ack.GW1", ts: "", stream_seq: 3, data: {} });
    expect(__getEventsSocketForTest()).toBe(before);
  });

  it("reconnects the events socket when stream_seq skips", () => {
    installEventsSocket();
    const before = __getEventsSocketForTest();
    routePrivate({ type: "authenticated", topic: "", ts: "", stream_seq: 1, data: {} });
    // stream_seq jumps from 1 to 3: event 2 was dropped by the queue.
    routePrivate({ type: "order.ack", topic: "order.ack.GW1", ts: "", stream_seq: 3, data: {} });
    expect(console.warn).toHaveBeenCalledWith(expect.stringContaining("stream_seq gap"));
    expect(__getEventsSocketForTest()).not.toBe(before);
  });

  it("does not reconnect on an envelope with no stream_seq", () => {
    installEventsSocket();
    const before = __getEventsSocketForTest();
    routePrivate({ type: "error", topic: "", ts: "", data: { message: "boom" } });
    expect(__getEventsSocketForTest()).toBe(before);
  });

  it("treats the first stream_seq seen as a baseline, not a gap", () => {
    installEventsSocket();
    const before = __getEventsSocketForTest();
    // A client that only just connected has nothing to compare the first
    // number against.
    routePrivate({ type: "authenticated", topic: "", ts: "", stream_seq: 42, data: {} });
    expect(__getEventsSocketForTest()).toBe(before);
  });
});

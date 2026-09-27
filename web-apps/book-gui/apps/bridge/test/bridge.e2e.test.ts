/**
 * The whole server side end to end: the real bridge against a fake
 * `pm-api-gwy`, with tabs as WebSocket clients (design §13, WP3–WP5).
 */

import { afterEach, describe, expect, it } from "vitest";
import type { SessionFrame } from "@edumatcher/book-types";
import { historyRow, type FakeApiGateway } from "./fake-api-gateway.js";
import { Tab, startRig, until, type Rig } from "./harness.js";

const tid = (n: number) => `000001-${String(n).padStart(9, "0")}`;

const BOOK = {
  bids: [
    { price: 166.95, qty: 312, count: 5 },
    { price: 166.94, qty: 138, count: 5 },
  ],
  asks: [{ price: 166.96, qty: 93, count: 1 }],
  last_price: 166.96,
  last_qty: 3,
};

/** Five trades of the day in history (three pages of two), and a gateway tail overlapping its end. */
function seedAapl(gw: FakeApiGateway): void {
  gw.historyTrades["AAPL"] = [
    historyRow("AAPL", tid(1), 100, 10, "07:00:00"),
    historyRow("AAPL", tid(2), 104, 20, "07:01:00"),
    historyRow("AAPL", tid(3), 99, 30, "07:02:00"),
    historyRow("AAPL", tid(4), 101, 40, "07:03:00"),
    historyRow("AAPL", tid(5), 102, 50, "07:04:00"),
  ];
  gw.daily["AAPL"] = [
    { date: "2026-09-25", symbol: "AAPL", close_price: 160 },
    { date: "2026-09-26", symbol: "AAPL", close_price: 165 },
    { date: "2026-09-27", symbol: "AAPL", close_price: 102 },
  ];
  gw.pushBook("AAPL", BOOK);
  // The gateway's cached 60 s tail: two prints history already has, one it does not yet.
  gw.pushTrade("AAPL", tid(4), 101, 40);
  gw.pushTrade("AAPL", tid(5), 102, 50);
  gw.pushTrade("AAPL", tid(6), 103, 60);
  gw.historyTrades["MSFT"] = [historyRow("MSFT", tid(7), 94, 5)];
  gw.pushBook("MSFT", { bids: [{ price: 94, qty: 1, count: 1 }], asks: [], last_price: 94, last_qty: 5 });
}

let rig: Rig | undefined;
const tabs: Tab[] = [];

async function open(): Promise<Tab> {
  const tab = await Tab.open(rig!.port);
  tabs.push(tab);
  return tab;
}

async function ready(setup = seedAapl): Promise<Rig> {
  rig = await startRig(setup);
  await until(() => rig!.bridge.uplink.state === "ACTIVE" && rig!.bridge.service.symbols.length > 0);
  return rig;
}

afterEach(async () => {
  for (const t of tabs.splice(0)) t.close();
  await rig?.stop();
  rig = undefined;
});

describe("connecting", () => {
  it("greets a tab with the symbol universe, its precision and the upstream state", async () => {
    await ready();
    const tab = await open();
    const hello = await tab.next("hello");
    expect(hello.symbols).toEqual([
      { symbol: "AAPL", tickDecimals: 2 },
      { symbol: "MSFT", tickDecimals: 2 },
      { symbol: "BRK", tickDecimals: 0 },
    ]);
    expect(hello.upstream).toBe("ACTIVE");
    expect(hello.source).toBe(`127.0.0.1:${rig!.gw.port}`);
  });

  it("never sends the API key to a tab", async () => {
    await ready();
    const tab = await open();
    tab.send({ t: "watch", sym: "AAPL" });
    await tab.next("session");
    expect(JSON.stringify(tab.frames)).not.toContain("ro-key");
  });
});

describe("watching a symbol", () => {
  it("delivers the full book and exact session statistics", async () => {
    await ready();
    const tab = await open();
    tab.send({ t: "watch", sym: "aapl" });

    const book = await tab.next("book");
    expect(book).toMatchObject({ sym: "AAPL", tickDecimals: 2, last: 166.96, lastQty: 3 });
    expect(book.bids).toEqual(BOOK.bids);
    expect(book.asks).toEqual(BOOK.asks);

    const session = await tab.next("session");
    // History (three pages) and the overlapping tail, each print counted once.
    expect(session.tape.map((t) => t.id)).toEqual([1, 2, 3, 4, 5, 6].map(tid));
    expect(session.stats).toEqual({
      open: 100,
      high: 104,
      low: 99,
      close: 103,
      prevClose: 165,
      volume: 210,
      tradeCount: 6,
      partial: false,
      sessionDate: "2026-09-27",
      timezone: "Europe/Stockholm",
    });
  });

  it("streams each new print once, with the statistics it produced", async () => {
    const { gw } = await ready();
    const tab = await open();
    tab.send({ t: "watch", sym: "AAPL" });
    await tab.next("session");

    gw.pushTrade("AAPL", tid(8), 110, 5);
    gw.pushTrade("AAPL", tid(8), 110, 5); // a replay overlap must not count twice
    gw.pushTrade("AAPL", tid(9), 98, 1);
    const last = await tab.next("trade", (f) => f.trade.id === tid(9));

    expect(
      tab.frames.filter((f) => f.type === "trade").map((f) => (f.type === "trade" ? f.trade.id : "")),
    ).toEqual([tid(8), tid(9)]);
    expect(last.stats).toMatchObject({ high: 110, low: 98, close: 98, volume: 216, tradeCount: 8 });
    expect(last.trade).toMatchObject({ px: 98, qty: 1, side: "BUY" });
  });

  it("forwards every new book to the tabs watching that symbol only", async () => {
    const { gw } = await ready();
    const onAapl = await open();
    const onMsft = await open();
    onAapl.send({ t: "watch", sym: "AAPL" });
    onMsft.send({ t: "watch", sym: "MSFT" });
    await onAapl.next("session");
    await onMsft.next("session");

    gw.pushBook("AAPL", { ...BOOK, last_price: 167.5 });
    await onAapl.next("book", (b) => b.last === 167.5);
    await new Promise((r) => setTimeout(r, 50));
    expect(onMsft.frames.some((f) => f.type === "book" && f.sym === "AAPL")).toBe(false);
  });

  it("shares one upstream subscription between tabs and gives a late tab the current state at once", async () => {
    const { gw } = await ready();
    const first = await open();
    first.send({ t: "watch", sym: "AAPL" });
    await first.next("session");

    const second = await open();
    second.send({ t: "watch", sym: "AAPL" });
    await second.next("book");
    const session = await second.next("session");

    expect(session.stats.volume).toBe(210);
    expect(gw.subscribesFor("AAPL")).toHaveLength(1);
  });

  it("releases the upstream subscription only when the last tab leaves", async () => {
    const { gw, bridge } = await ready();
    const a = await open();
    const b = await open();
    a.send({ t: "watch", sym: "AAPL" });
    b.send({ t: "watch", sym: "AAPL" });
    await a.next("session");
    await b.next("session");

    a.send({ t: "watch", sym: "MSFT" });
    await a.next("session", (f) => f.sym === "MSFT");
    expect(gw.controls.some((c) => c["action"] === "unsubscribe")).toBe(false);
    expect(bridge.service.watched()).toEqual({ AAPL: 1, MSFT: 1 });

    b.close();
    await gw.until(() => gw.controls.some((c) => c["action"] === "unsubscribe"));
    expect(JSON.stringify(gw.controls.find((c) => c["action"] === "unsubscribe"))).toContain("AAPL");
    await until(() => JSON.stringify(bridge.service.watched()) === JSON.stringify({ MSFT: 1 }));
  });

  it("refuses an unknown symbol and keeps the current one", async () => {
    await ready();
    const tab = await open();
    tab.send({ t: "watch", sym: "AAPL" });
    await tab.next("session");

    tab.send({ t: "watch", sym: "NOPE" });
    const err = await tab.next("error");
    expect(err).toMatchObject({ code: "UNKNOWN_SYMBOL", sym: "NOPE" });
    expect(rig!.bridge.service.watched()).toEqual({ AAPL: 1 });
  });
});

describe("history unavailable", () => {
  it("counts only live prints and says the statistics are partial", async () => {
    await ready((gw) => {
      seedAapl(gw);
      gw.historyStatus = 503;
    });
    const tab = await open();
    tab.send({ t: "watch", sym: "AAPL" });
    const session = await tab.next("session");

    // The gateway tail (ids 4..6) is all there is.
    expect(session.stats).toMatchObject({ partial: true, volume: 150, tradeCount: 3, timezone: "UTC" });
    expect(session.stats.since).toBeTypeOf("number");
    expect(session.stats.prevClose).toBeUndefined();
  });
});

describe("upstream loss", () => {
  it("reconnects, re-subscribes from the last print seen and fills the gap", async () => {
    const { gw, bridge } = await ready();
    const tab = await open();
    tab.send({ t: "watch", sym: "AAPL" });
    await tab.next("session");

    gw.dropAll();
    await tab.next("bridge_status", (f) => f.upstream === "RECONNECTING");
    gw.pushTrade("AAPL", tid(10), 120, 7); // printed while the bridge was away

    await tab.next("bridge_status", (f) => f.upstream === "ACTIVE");
    const trade = await tab.next("trade", (f) => f.trade.id === tid(10));
    expect(trade.stats).toMatchObject({ high: 120, volume: 217 });

    const resubscribe = gw.subscribesFor("AAPL").at(-1)!;
    expect(JSON.stringify(resubscribe)).toContain('"resume_from":{"trades":3}');
    expect(bridge.uplink.state).toBe("ACTIVE");
  });

  it("re-seeds from history when the gap is too old to replay", async () => {
    const { gw } = await ready();
    const tab = await open();
    tab.send({ t: "watch", sym: "AAPL" });
    const first = await tab.next("session");

    gw.resetNextResume = true;
    gw.historyTrades["AAPL"]!.push(historyRow("AAPL", tid(6), 103, 60, "07:05:00"));
    gw.historyTrades["AAPL"]!.push(historyRow("AAPL", tid(11), 90, 4, "07:06:00"));
    gw.dropAll();

    const reseeded = await tab.next("session", () => true, tab.frames.indexOf(first) + 1, 5000);
    expect(reseeded.stats).toMatchObject({ low: 90, close: 90, volume: 214, tradeCount: 7 });
  });

  it("asks for a trade replay when a book seq gap shows the socket dropped events", async () => {
    const { gw } = await ready();
    const tab = await open();
    tab.send({ t: "watch", sym: "AAPL" });
    await tab.next("session");

    gw.pushTrade("AAPL", tid(12), 130, 2, false); // lost on the way
    gw.pushBook("AAPL", BOOK, 3);

    const replayed = await tab.next("trade", (f) => f.trade.id === tid(12));
    expect(replayed.stats.high).toBe(130);
    expect(gw.controls.find((c) => c["action"] === "resume")).toMatchObject({
      topic: "trade.executed",
      symbols: ["AAPL"],
      from_seq: 3,
    });
  });

  it("reports DOWN when the gateway refuses the key", async () => {
    rig = await startRig(seedAapl, {}, "wrong-key");
    await until(() => rig!.bridge.uplink.state === "DOWN");
    const res = await fetch(`http://127.0.0.1:${rig.port}/api/bridge/status`);
    expect(await res.json()).toMatchObject({ upstream: "DOWN" });
  });
});

describe("status endpoint and limits", () => {
  it("reports what is being watched and by how many tabs", async () => {
    await ready();
    const a = await open();
    const b = await open();
    a.send({ t: "watch", sym: "AAPL" });
    b.send({ t: "watch", sym: "AAPL" });
    await a.next("session");
    await b.next("session");

    const res = await fetch(`http://127.0.0.1:${rig!.port}/api/bridge/status`);
    expect(await res.json()).toMatchObject({
      upstream: "ACTIVE",
      symbols: 3,
      watched: { AAPL: 2 },
      wsClients: 2,
    });
  });

  it("refuses a tab past max clients", async () => {
    rig = await startRig(seedAapl, { maxWsClients: 1 });
    await open();
    const extra = await open();
    await until(() => extra.socket.readyState === extra.socket.CLOSED);
  });

  it("keeps sessions ordered by trade id even when an older print arrives late", async () => {
    const { gw } = await ready();
    const tab = await open();
    tab.send({ t: "watch", sym: "AAPL" });
    await tab.next("session");
    gw.pushTrade("AAPL", tid(21), 111, 1);
    gw.pushTrade("AAPL", tid(20), 222, 1);
    const late = await tab.next("trade", (f) => f.trade.id === tid(20));
    expect(late.stats.close).toBe(111);

    const other = await open();
    other.send({ t: "watch", sym: "AAPL" });
    const session: SessionFrame = await other.next("session");
    expect(session.tape.slice(-2).map((t) => t.id)).toEqual([tid(20), tid(21)]);
  });
});

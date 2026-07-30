import { afterEach, describe, expect, it } from "vitest";
import type { ServerFrame } from "@edumatcher/terminal-types";
import { CalfUplink } from "../src/calf/uplink.js";
import { FakeCalfGateway, waitFor, type FakeGatewayOptions } from "./fake-calf-gateway.js";

const gateways: FakeCalfGateway[] = [];
const uplinks: CalfUplink[] = [];

afterEach(async () => {
  for (const uplink of uplinks.splice(0)) await uplink.stop();
  for (const gateway of gateways.splice(0)) await gateway.stop();
});

interface Harness {
  gateway: FakeCalfGateway;
  uplink: CalfUplink;
  frames: ServerFrame[];
  errors: Array<{ code: string }>;
}

async function connected(
  gatewayOpts: FakeGatewayOptions = { symbols: ["AAPL", "MSFT"] },
  uplinkOpts: Partial<ConstructorParameters<typeof CalfUplink>[0]> = {},
): Promise<Harness> {
  const gateway = new FakeCalfGateway(gatewayOpts);
  gateways.push(gateway);
  await gateway.start();

  const uplink = new CalfUplink({
    host: "127.0.0.1",
    port: gateway.port,
    clientId: "pm-terminal-bridge",
    indexIds: [],
    pingIntervalSec: 60,
    ...uplinkOpts,
  });
  uplinks.push(uplink);

  const frames: ServerFrame[] = [];
  const errors: Array<{ code: string }> = [];
  uplink.on("frame", (frame) => frames.push(frame));
  uplink.on("gatewayError", (err) => errors.push(err));

  uplink.start();
  if (!gatewayOpts.silent) {
    await waitFor(() => uplink.state === "ACTIVE", 2000, "the handshake");
    // The uplink writes its SUBs before going ACTIVE, but the gateway is a
    // separate process boundary — every gateway-side assertion needs the wire
    // to have caught up, not just the client's own state.
    await waitFor(() => gateway.linesStartingWith("SUB").length >= 1, 2000, "the initial SUB");
  }
  return { gateway, uplink, frames, errors };
}

const frameOf = <T extends ServerFrame["type"]>(frames: ServerFrame[], type: T) =>
  frames.filter((f): f is Extract<ServerFrame, { type: T }> => f.type === type);

/**
 * Drop the connection and wait for a fresh session.
 *
 * Waiting for RECONNECTING first matters: `state` is still ACTIVE for the
 * moment between the drop and the socket close event, so waiting only for
 * ACTIVE would return immediately and assert against the old session.
 */
async function reconnect({ gateway, uplink }: Harness): Promise<void> {
  gateway.dropConnections();
  await waitFor(() => uplink.state === "RECONNECTING", 2000, "the drop to be noticed");
  await waitFor(() => uplink.state === "ACTIVE", 5000, "the reconnect");
  await waitFor(() => gateway.linesStartingWith("HELLO").length >= 2, 2000, "the second handshake");
}

describe("handshake", () => {
  it("identifies itself and goes active once WELCOME arrives", async () => {
    const { gateway, uplink } = await connected();
    expect(gateway.linesStartingWith("HELLO")).toEqual(["HELLO|CLIENT=pm-terminal-bridge|PROTO=CALF1"]);
    expect(uplink.gateway).toBe("fake-gwy01");
  });

  it("learns the symbol universe from WELCOME", async () => {
    const { uplink } = await connected({ symbols: ["AAPL", "MSFT", "TSLA"] });
    expect(uplink.symbols()).toEqual(["AAPL", "MSFT", "TSLA"]);
  });

  it("stays down while the gateway never answers", async () => {
    const { uplink } = await connected({ silent: true });
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(uplink.state).not.toBe("ACTIVE");
  });
});

describe("initial subscriptions", () => {
  it("takes all four wildcard-eligible channels in one SUB", async () => {
    const { gateway } = await connected();
    expect(gateway.linesStartingWith("SUB")).toEqual(["SUB|CH=STATE,TOP,TRADE,AUCTION|SYM=*"]);
  });

  it("never asks for DEPTH or CB under a wildcard, which the gateway rejects", async () => {
    const { gateway } = await connected();
    const wildcardSubs = gateway.linesStartingWith("SUB").filter((line) => line.includes("SYM=*"));
    expect(wildcardSubs.some((line) => /CH=[^|]*\b(DEPTH|CB)\b/.test(line))).toBe(false);
  });

  it("subscribes to each configured index by id", async () => {
    const { gateway } = await connected({ symbols: ["AAPL"] }, { indexIds: ["EDU100", "EDU50"] });
    await waitFor(() => gateway.linesStartingWith("SUB").length === 2, 2000, "the INDEX SUB");
    expect(gateway.linesStartingWith("SUB")).toContain("SUB|CH=INDEX|SYM=EDU100,EDU50");
  });

  it("issues no INDEX subscription when none is configured", async () => {
    const { gateway } = await connected();
    expect(gateway.linesStartingWith("SUB").some((line) => line.includes("CH=INDEX"))).toBe(false);
  });

  it("skips channels the gateway did not advertise", async () => {
    const { gateway } = await connected({ chSupported: ["TOP", "TRADE", "STATE"], symbols: ["AAPL"] });
    expect(gateway.linesStartingWith("SUB")).toEqual(["SUB|CH=STATE,TOP,TRADE|SYM=*"]);
  });

  it("assumes full support from a gateway too old to advertise any", async () => {
    const { gateway } = await connected({ chSupported: null, symbols: ["AAPL"] });
    expect(gateway.linesStartingWith("SUB")).toEqual(["SUB|CH=STATE,TOP,TRADE,AUCTION|SYM=*"]);
  });
});

describe("per-symbol subscriptions", () => {
  it("subscribes on the first interested tab and unsubscribes after the last", async () => {
    const { gateway, uplink } = await connected();

    uplink.watch("DEPTH", "AAPL");
    await waitFor(() => gateway.received.includes("SUB|CH=DEPTH|SYM=AAPL"), 2000, "the DEPTH SUB");

    uplink.unwatch("DEPTH", "AAPL");
    await waitFor(() => gateway.received.includes("UNSUB|CH=DEPTH|SYM=AAPL"), 2000, "the DEPTH UNSUB");
  });

  it("holds one subscription for two tabs watching the same symbol", async () => {
    const { gateway, uplink } = await connected();

    uplink.watch("CB", "TSLA");
    uplink.watch("CB", "TSLA");
    await waitFor(() => gateway.linesStartingWith("SUB|CH=CB").length === 1, 2000, "the CB SUB");

    uplink.unwatch("CB", "TSLA");
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(gateway.linesStartingWith("UNSUB")).toHaveLength(0);
  });

  it("does not subscribe to a channel the gateway lacks", async () => {
    const { gateway, uplink } = await connected({
      chSupported: ["TOP", "TRADE", "STATE"],
      symbols: ["AAPL"],
    });
    uplink.watch("DEPTH", "AAPL");

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(gateway.linesStartingWith("SUB|CH=DEPTH")).toHaveLength(0);
  });
});

describe("stream decoding", () => {
  it("merges TOP deltas so every frame carries a complete book", async () => {
    const { gateway, frames } = await connected();

    gateway.emit("SNAP|CH=TOP|SYM=AAPL|SEQ=1|TS=t1|BID=150.10|BIDSZ=1400|ASK=150.12|ASKSZ=900");
    gateway.emit("MD|CH=TOP|SYM=AAPL|SEQ=2|TS=t2|BID=150.11");
    await waitFor(() => frameOf(frames, "top").length === 2, 2000, "two top frames");

    // The MD only moved the bid; the fanned-out frame still has both sides.
    expect(frameOf(frames, "top")[1]).toEqual({
      type: "top",
      sym: "AAPL",
      seq: 2,
      ts: "t2",
      bid: 150.11,
      bidSz: 1400,
      ask: 150.12,
      askSz: 900,
    });
  });

  it("decodes a trade print with its aggressor side", async () => {
    const { gateway, frames } = await connected();
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=7|TS=t|PX=150.12|QTY=200|SIDE=BUY");
    await waitFor(() => frameOf(frames, "trade").length === 1, 2000, "the trade frame");

    expect(frameOf(frames, "trade")[0]).toMatchObject({ sym: "AAPL", px: 150.12, qty: 200, side: "BUY" });
  });

  it("passes an exchange-wide session change through under SYM=*", async () => {
    const { gateway, frames } = await connected();
    gateway.emit("STATE|CH=STATE|SYM=*|SEQ=1|TS=t|SESSION=CONTINUOUS|PREV=OPENING_AUCTION");
    await waitFor(() => frameOf(frames, "state").length === 1, 2000, "the state frame");

    expect(frameOf(frames, "state")[0]).toMatchObject({ sym: "*", session: "CONTINUOUS" });
  });

  it("decodes a per-symbol halt arriving on the same wildcard subscription", async () => {
    const { gateway, frames } = await connected();
    gateway.emit("STATE|CH=STATE|SYM=TSLA|SEQ=2|TS=t|SESSION=HALTED|PREV=CONTINUOUS");
    await waitFor(() => frameOf(frames, "state").length === 1, 2000, "the state frame");

    expect(frameOf(frames, "state")[0]).toMatchObject({ sym: "TSLA", session: "HALTED" });
  });

  it("decodes a depth ladder into number triples", async () => {
    const { gateway, frames } = await connected();
    gateway.emit("DEPTH|CH=DEPTH|SYM=AAPL|SEQ=2|TS=t|LEVELS=10|BIDS=150.10:1400:4|ASKS=150.12:900:2");
    await waitFor(() => frameOf(frames, "depth").length === 1, 2000, "the depth frame");

    expect(frameOf(frames, "depth")[0]).toMatchObject({ bids: [[150.1, 1400, 4]], asks: [[150.12, 900, 2]] });
  });

  it("decodes an auction uncross", async () => {
    const { gateway, frames } = await connected();
    gateway.emit("AUCTION|CH=AUCTION|SYM=AAPL|SEQ=1|TS=t|EQPX=149.85|EQQTY=12400|TRADES=38|IMBQTY=0");
    await waitFor(() => frameOf(frames, "auction_result").length === 1, 2000, "the auction frame");

    expect(frameOf(frames, "auction_result")[0]).toMatchObject({ eqPrice: 149.85, eqQty: 12400 });
  });

  it("emits halt context with RESUMEAT as ISO text", async () => {
    const { gateway, frames } = await connected();
    gateway.emit("CB|CH=CB|SYM=TSLA|SEQ=4|TS=t|STATUS=HALTED|LEVEL=L2|RESUMEAT=2026-07-11T11:07:17.000Z");
    await waitFor(() => frameOf(frames, "halt_context").length === 1, 2000, "the halt frame");

    expect(frameOf(frames, "halt_context")[0]).toMatchObject({
      status: "HALTED",
      level: "L2",
      resumeAt: "2026-07-11T11:07:17.000Z",
    });
  });

  it("reassembles a line split across TCP chunks", async () => {
    const { gateway, frames } = await connected();
    gateway.emitRaw("TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t|PX=1");
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(frameOf(frames, "trade")).toHaveLength(0);

    gateway.emitRaw("50.12|QTY=200|SIDE=BUY\n");
    await waitFor(() => frameOf(frames, "trade").length === 1, 2000, "the completed trade");
    expect(frameOf(frames, "trade")[0]?.px).toBe(150.12);
  });

  it("splits several messages arriving in one chunk", async () => {
    const { gateway, frames } = await connected();
    gateway.emitRaw(
      "TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t|PX=1|QTY=1|SIDE=BUY\n" +
        "TRADE|CH=TRADE|SYM=AAPL|SEQ=2|TS=t|PX=2|QTY=1|SIDE=SELL\n",
    );
    await waitFor(() => frameOf(frames, "trade").length === 2, 2000, "both trades");
  });

  it("learns a symbol that appears live but was not in WELCOME", async () => {
    const { gateway, uplink } = await connected({ symbols: ["AAPL"] });
    gateway.emit("TRADE|CH=TRADE|SYM=NEWCO|SEQ=1|TS=t|PX=1|QTY=1|SIDE=BUY");
    await waitFor(() => uplink.symbols().includes("NEWCO"), 2000, "the new symbol");
  });

  it("does not mistake the wildcard for a symbol", async () => {
    const { gateway, uplink } = await connected({ symbols: ["AAPL"] });
    gateway.emit("STATE|CH=STATE|SYM=*|SEQ=1|TS=t|SESSION=CLOSED");
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(uplink.symbols()).toEqual(["AAPL"]);
  });

  it("surfaces a gateway ERR without tearing down the session", async () => {
    const { gateway, uplink, errors } = await connected();
    gateway.emit("ERR|CODE=INVALID_SYMBOL|SYM=NOPE");
    await waitFor(() => errors.length === 1, 2000, "the error");

    expect(errors[0]?.code).toBe("INVALID_SYMBOL");
    expect(uplink.state).toBe("ACTIVE");
  });

  it("skips an unparseable line and keeps processing the next one", async () => {
    const { gateway, frames, errors } = await connected();
    gateway.emitRaw("this is not calf\nTRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t|PX=1|QTY=1|SIDE=BUY\n");
    await waitFor(() => frameOf(frames, "trade").length === 1, 2000, "the good line");

    expect(errors.some((e) => e.code === "PARSE_ERROR")).toBe(true);
  });
});

describe("keepalive", () => {
  it("pings so the gateway's inbound-only idle timer never expires", async () => {
    // The gateway drops a client after idle_timeout_sec of no inbound bytes;
    // its own HB does not reset that clock, so the bridge must speak.
    const { gateway } = await connected({ symbols: ["AAPL"] }, { pingIntervalSec: 0.1 });
    await waitFor(() => gateway.linesStartingWith("PING").length >= 2, 3000, "two pings");
  });
});

describe("reconnect", () => {
  it("re-handshakes and reports RECONNECTING in between", async () => {
    const harness = await connected();
    await reconnect(harness);
    expect(harness.gateway.connectionCount).toBe(2);
  });

  it("re-establishes the wildcard subscriptions from scratch", async () => {
    const harness = await connected();
    await reconnect(harness);

    await waitFor(
      () => harness.gateway.linesStartingWith("SUB|CH=STATE,TOP,TRADE,AUCTION").length === 2,
      2000,
      "the wildcard re-subscribe",
    );
  });

  it("never sends a second HELLO on one connection, which the gateway rejects", async () => {
    const harness = await connected();
    await reconnect(harness);

    // Two connections, one HELLO each — not two HELLOs on either.
    expect(harness.gateway.linesStartingWith("HELLO")).toHaveLength(2);
    expect(harness.errors.some((e) => e.code === "BAD_MESSAGE")).toBe(false);
  });

  it("never attempts a RESUME, which no reconnect path can satisfy", async () => {
    const harness = await connected();
    await reconnect(harness);
    expect(harness.gateway.received.some((line) => line.includes("RESUME"))).toBe(false);
  });

  it("re-issues the per-symbol subscriptions still held by open tabs", async () => {
    const harness = await connected();
    harness.uplink.watch("DEPTH", "AAPL");
    harness.uplink.watch("CB", "TSLA");
    await waitFor(
      () => harness.gateway.linesStartingWith("SUB|CH=CB").length === 1,
      2000,
      "the first CB SUB",
    );

    await reconnect(harness);
    await waitFor(
      () => harness.gateway.linesStartingWith("SUB|CH=CB|SYM=TSLA").length === 2,
      2000,
      "the per-symbol re-subscribe",
    );
    expect(harness.gateway.linesStartingWith("SUB|CH=DEPTH|SYM=AAPL")).toHaveLength(2);
  });

  it("does not re-issue a subscription released while disconnected", async () => {
    const harness = await connected();
    harness.uplink.watch("DEPTH", "AAPL");
    await waitFor(
      () => harness.gateway.linesStartingWith("SUB|CH=DEPTH").length === 1,
      2000,
      "the DEPTH SUB",
    );

    harness.gateway.dropConnections();
    await waitFor(() => harness.uplink.state === "RECONNECTING", 2000, "the drop to be noticed");
    harness.uplink.unwatch("DEPTH", "AAPL");

    await waitFor(() => harness.uplink.state === "ACTIVE", 5000, "the reconnect");
    await waitFor(
      () => harness.gateway.linesStartingWith("HELLO").length === 2,
      2000,
      "the second handshake",
    );
    expect(harness.gateway.linesStartingWith("SUB|CH=DEPTH")).toHaveLength(1);
  });

  it("keeps merged top-of-book across a reconnect", async () => {
    const harness = await connected();
    harness.gateway.emit("SNAP|CH=TOP|SYM=AAPL|SEQ=1|TS=t|BID=150.10|BIDSZ=1400|ASK=150.12|ASKSZ=900");
    await waitFor(() => frameOf(harness.frames, "top").length === 1, 2000, "the snapshot");

    await reconnect(harness);

    harness.gateway.emit("MD|CH=TOP|SYM=AAPL|SEQ=1|TS=t2|BID=150.20");
    await waitFor(() => frameOf(harness.frames, "top").length === 2, 2000, "the post-reconnect delta");
    expect(frameOf(harness.frames, "top")[1]?.ask).toBe(150.12);
  });

  it("stops reconnecting once stopped", async () => {
    const { gateway, uplink } = await connected();
    await uplink.stop();
    gateway.dropConnections();

    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(uplink.state).toBe("DOWN");
    expect(gateway.connectionCount).toBe(1);
  });
});

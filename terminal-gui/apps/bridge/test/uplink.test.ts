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
  gaps: Array<{ ch: string; sym: string; ts: string }>;
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
  const gaps: Array<{ ch: string; sym: string; ts: string }> = [];
  uplink.on("frame", (frame) => frames.push(frame));
  uplink.on("gatewayError", (err) => errors.push(err));
  uplink.on("gap", (gap) => gaps.push(gap));

  uplink.start();
  if (!gatewayOpts.silent) {
    await waitFor(() => uplink.state === "ACTIVE", 2000, "the handshake");
    // The uplink writes its SUBs before going ACTIVE, but the gateway is a
    // separate process boundary — every gateway-side assertion needs the wire
    // to have caught up, not just the client's own state.
    await waitFor(() => gateway.linesStartingWith("SUB").length >= 1, 2000, "the initial SUB");
  }
  return { gateway, uplink, frames, errors, gaps };
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

  it("learns per-symbol display precision from REF=", async () => {
    const { uplink } = await connected({
      symbols: ["AAPL", "TSLA"],
      tickDecimals: { TSLA: 4 },
    });
    expect(uplink.tickDecimals()).toEqual({ AAPL: 2, TSLA: 4 });
  });

  it("reports no precision against a gateway predating REF", async () => {
    // Emptiness is what tells a browser tab it is falling back to the default
    // rather than having been told it.
    const { uplink } = await connected({ symbols: ["AAPL"] });
    expect(uplink.tickDecimals()).toEqual({});
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

describe("gap detection and repair (T-H4/T-H5)", () => {
  it("does not flag the first message on a stream as a gap", async () => {
    const { gateway, gaps } = await connected();
    // SEQ starts well above 1 — a first sighting still has no baseline to
    // have missed anything against.
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=40|TS=t|PX=1|QTY=1|SIDE=BUY");
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(gaps).toEqual([]);
  });

  it("does not flag consecutive sequence numbers", async () => {
    const { gateway, gaps } = await connected();
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t|PX=1|QTY=1|SIDE=BUY");
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=2|TS=t|PX=1|QTY=1|SIDE=BUY");
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(gaps).toEqual([]);
  });

  it("ignores an exact duplicate redelivery of the same SEQ", async () => {
    // A network or gateway-side retry redelivering a line verbatim must be a
    // no-op: not a gap (nothing was skipped) and not grounds to re-baseline.
    const { gateway, gaps } = await connected();
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t1|PX=1|QTY=1|SIDE=BUY");
    await new Promise((resolve) => setTimeout(resolve, 20));
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t1|PX=1|QTY=1|SIDE=BUY");
    await new Promise((resolve) => setTimeout(resolve, 20));

    // The true next message is consecutive with the original SEQ=1.
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=2|TS=t2|PX=1|QTY=1|SIDE=BUY");
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(gateway.linesStartingWith("RESUME")).toEqual([]);
    expect(gaps).toEqual([]);
  });

  it("requests each gap from the live baseline, not a stale one, when a second gap arrives before the first RESUME replies", async () => {
    const { gateway } = await connected();
    // No scripted reply — this test is about what the bridge asks for, not
    // what comes back.
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t1|PX=1|QTY=1|SIDE=BUY");
    await new Promise((resolve) => setTimeout(resolve, 20));

    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=5|TS=t5|PX=1|QTY=1|SIDE=BUY");
    await waitFor(
      () => gateway.linesStartingWith("RESUME|CH=TRADE|SYM=AAPL|LASTSEQ=1").length === 1,
      2000,
      "the first RESUME",
    );

    // A second gap opens before the first RESUME's reply ever arrives. The
    // request for it must cover 5 -> 10, not repeat 1 -> 5 — the two holes
    // are disjoint, and re-requesting the first would ask the gateway to
    // replay data this bridge is not missing.
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=10|TS=t10|PX=1|QTY=1|SIDE=BUY");
    await waitFor(
      () => gateway.linesStartingWith("RESUME|CH=TRADE|SYM=AAPL|LASTSEQ=5").length === 1,
      2000,
      "the second RESUME, from the live baseline",
    );
    expect(gateway.linesStartingWith("RESUME|CH=TRADE|SYM=AAPL")).toHaveLength(2);
  });

  it("resumes a TRADE gap instead of reporting it unrepaired", async () => {
    const { gateway, uplink, frames, gaps } = await connected();
    // Buffered by the gateway but never delivered: the two prints that went
    // missing. The replay will also carry back SEQ=4, which was delivered
    // live — see the duplicate test below.
    gateway.seedReplay([
      "TRADE|CH=TRADE|SYM=AAPL|SEQ=2|TS=t2|PX=150.00|QTY=50|SIDE=BUY",
      "TRADE|CH=TRADE|SYM=AAPL|SEQ=3|TS=t3|PX=150.05|QTY=75|SIDE=SELL",
    ]);

    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t1|PX=149.90|QTY=100|SIDE=BUY");
    await waitFor(() => frameOf(frames, "trade").length === 1, 2000, "the first print");
    // SEQ jumps 1 -> 4: two prints were missed.
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=4|TS=t4|PX=150.10|QTY=25|SIDE=BUY");

    await waitFor(
      () => gateway.linesStartingWith("RESUME|CH=TRADE|SYM=AAPL|LASTSEQ=1").length === 1,
      2000,
      "the RESUME request",
    );
    await waitFor(() => frameOf(frames, "trade").length === 4, 2000, "the backfilled prints");

    expect(frameOf(frames, "trade").map((t) => t.seq)).toEqual([1, 4, 2, 3]);
    expect(uplink.symbols()).toContain("AAPL");
    expect(gaps).toEqual([]);
  });

  it("emits a replayed print once, though RESUME returns everything past LASTSEQ", async () => {
    // `replay_since` answers with every buffered entry above LASTSEQ, and
    // LASTSEQ is the position from *before* the gap — so the reply necessarily
    // re-sends the message that revealed the gap, and anything delivered live
    // while the request was in flight. Emitting those again would print the
    // same trade on the tape twice, which is a missing print wearing the
    // opposite sign.
    const { gateway, frames } = await connected();
    gateway.seedReplay(["TRADE|CH=TRADE|SYM=AAPL|SEQ=2|TS=t2|PX=150.00|QTY=50|SIDE=BUY"]);

    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t1|PX=149.90|QTY=100|SIDE=BUY");
    await waitFor(() => frameOf(frames, "trade").length === 1, 2000, "the first print");
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=3|TS=t3|PX=150.10|QTY=25|SIDE=BUY");

    await waitFor(() => frameOf(frames, "trade").length === 3, 2000, "the backfilled print");
    // Settle: the replayed SEQ=1 and SEQ=3 would land in this window.
    await new Promise((resolve) => setTimeout(resolve, 50));

    const seqs = frameOf(frames, "trade").map((t) => t.seq);
    expect(seqs).toEqual([1, 3, 2]);
    expect(new Set(seqs).size).toBe(seqs.length);
  });

  it("drops the payload-less SNAP an older gateway sends after a TRADE REPLAY_MISS", async () => {
    // `_send_snapshot_for_stream` has no TRADE branch, so its SNAP carries an
    // envelope and nothing else. Routed by CH like any other line it reaches
    // `decodeTrade`, whose defaults would put a print of zero shares at zero
    // price on the tape — a fabricated trade, which is worse than the hole it
    // would be standing in for.
    const { gateway, frames, gaps } = await connected();
    gateway.setReplayMiss("TRADE", "AAPL");

    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t1|PX=149.90|QTY=100|SIDE=BUY");
    await waitFor(() => frameOf(frames, "trade").length === 1, 2000, "the first print");
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=9|TS=t9|PX=150.10|QTY=25|SIDE=BUY");

    await waitFor(() => gaps.length === 1, 2000, "the reported gap");
    await new Promise((resolve) => setTimeout(resolve, 50));

    const prints = frameOf(frames, "trade");
    expect(prints.map((t) => t.seq)).toEqual([1, 9]);
    expect(prints.every((t) => t.px > 0 && t.qty > 0)).toBe(true);
  });

  it("does not RESUME again after a REPLAY_MISS re-baselined the stream", async () => {
    // The SNAP that answers a REPLAY_MISS re-anchors the stream wherever the
    // gateway now is. Left uncounted, the next live message would look like a
    // fresh gap and RESUME against a window already proved too old — once per
    // print, indefinitely.
    const { gateway, gaps } = await connected();
    gateway.setReplayMiss("TRADE", "AAPL");

    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t1|PX=1|QTY=1|SIDE=BUY");
    await new Promise((resolve) => setTimeout(resolve, 30));
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=9|TS=t9|PX=1|QTY=1|SIDE=BUY");
    await waitFor(() => gaps.length === 1, 2000, "the reported gap");

    // The fake's REPLAY_MISS SNAP carries SEQ=9001; the stream continues there.
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=9002|TS=t10|PX=1|QTY=1|SIDE=BUY");
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(gateway.linesStartingWith("RESUME|CH=TRADE|SYM=AAPL")).toHaveLength(1);
    expect(gaps).toHaveLength(1);
  });

  it("times an unrepaired gap by the gateway's clock, not the bridge's", async () => {
    // The marker is interleaved with prints stamped by the gateway, so a
    // local timestamp would drift it to the wrong point in the tape. The
    // message that revealed the hole is also its upper bound.
    const { gateway, gaps } = await connected();
    gateway.setReplayMiss("TRADE", "AAPL");

    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=2026-07-30T14:32:06.000Z|PX=1|QTY=1|SIDE=BUY");
    await new Promise((resolve) => setTimeout(resolve, 30));
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=9|TS=2026-07-30T14:32:09.000Z|PX=1|QTY=1|SIDE=BUY");

    await waitFor(() => gaps.length === 1, 2000, "the reported gap");
    expect(gaps[0]?.ts).toBe("2026-07-30T14:32:09.000Z");
  });

  it("ignores a REPLAY_MISS for a stream it never asked to resume", async () => {
    // Nothing is known about where such a hole falls, and this bridge has no
    // standing to describe one it did not discover.
    const { gateway, gaps, errors } = await connected();
    gateway.emit("ERR|CODE=REPLAY_MISS|CH=TRADE|SYM=AAPL");
    await waitFor(() => errors.some((e) => e.code === "REPLAY_MISS"), 2000, "the ERR");
    expect(gaps).toEqual([]);
  });

  it("passes through a message with no usable SEQ without sequencing it", async () => {
    // readEnvelope defaults a missing SEQ to 0. Baselining there would make
    // the next real SEQ a gap and send RESUME|LASTSEQ=0, which the gateway
    // rejects with BAD_MESSAGE rather than REPLAY_MISS — a hole nobody is
    // told about.
    const { gateway, frames, gaps } = await connected();
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|TS=t0|PX=149.00|QTY=10|SIDE=BUY");
    await waitFor(() => frameOf(frames, "trade").length === 1, 2000, "the unsequenced print");

    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=5|TS=t5|PX=150.00|QTY=10|SIDE=BUY");
    await waitFor(() => frameOf(frames, "trade").length === 2, 2000, "the sequenced print");
    await new Promise((resolve) => setTimeout(resolve, 30));

    expect(gateway.linesStartingWith("RESUME")).toEqual([]);
    expect(gaps).toEqual([]);
  });

  it("does not let a late-arriving lower SEQ move the baseline backward", async () => {
    // A RESUME reply and live traffic are two separate writes with no
    // guaranteed relative order. A replayed line for an already-superseded
    // SEQ must not be recorded as the new "last seen" — doing so would make
    // the next ordinary, truly-consecutive message look like a gap.
    const { gateway, gaps } = await connected();
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t1|PX=1|QTY=1|SIDE=BUY");
    await new Promise((resolve) => setTimeout(resolve, 30));

    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=5|TS=t5|PX=1|QTY=1|SIDE=BUY");
    await waitFor(
      () => gateway.linesStartingWith("RESUME|CH=TRADE|SYM=AAPL|LASTSEQ=1").length === 1,
      2000,
      "the RESUME triggered by the 1 -> 5 jump",
    );

    // A stale reply for SEQ=3 arrives after the live SEQ=5 already advanced
    // the baseline. It must be ignored outright, not treated as a new gap
    // (5 -> 3 is not forward progress) and not recorded as "last seen".
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=3|TS=t3|PX=1|QTY=1|SIDE=BUY");
    await new Promise((resolve) => setTimeout(resolve, 30));

    // The true next live message is consecutive with 5, not with the stale 3
    // — if the baseline had been clobbered back to 3, this would wrongly look
    // like a second gap and trigger a second, spurious RESUME.
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=6|TS=t6|PX=1|QTY=1|SIDE=BUY");
    await new Promise((resolve) => setTimeout(resolve, 30));

    expect(gateway.linesStartingWith("RESUME|CH=TRADE|SYM=AAPL")).toHaveLength(1);
    expect(gaps).toEqual([]);
  });

  it("reports a TRADE gap the gateway can no longer replay", async () => {
    const { gateway, gaps } = await connected();
    gateway.setReplayMiss("TRADE", "AAPL");

    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t1|PX=149.90|QTY=100|SIDE=BUY");
    await new Promise((resolve) => setTimeout(resolve, 30));
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=9|TS=t9|PX=150.10|QTY=25|SIDE=BUY");

    await waitFor(() => gaps.length === 1, 2000, "the reported gap");
    expect(gaps[0]).toMatchObject({ ch: "TRADE", sym: "AAPL" });
  });

  it("leaves a TOP gap for the next SNAP rather than reporting it", async () => {
    // TOP baselines on SNAP, which the reconnect that would cause a real gap
    // already triggers — reporting this would be noise about a hole that
    // closed itself before anyone could see it open.
    const { gateway, gaps } = await connected();
    gateway.emit("SNAP|CH=TOP|SYM=AAPL|SEQ=1|TS=t1|BID=150.00");
    await new Promise((resolve) => setTimeout(resolve, 30));
    gateway.emit("MD|CH=TOP|SYM=AAPL|SEQ=9|TS=t9|BID=150.05");

    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(gaps).toEqual([]);
    expect(gateway.linesStartingWith("RESUME")).toEqual([]);
  });

  it("reports an AUCTION gap, which has no snapshot and is not resumed", async () => {
    const { gateway, gaps } = await connected();
    gateway.emit("AUCTION|CH=AUCTION|SYM=AAPL|SEQ=1|TS=t1|EQPX=149.85|EQQTY=100|TRADES=1|IMBQTY=0");
    await new Promise((resolve) => setTimeout(resolve, 30));
    gateway.emit("AUCTION|CH=AUCTION|SYM=AAPL|SEQ=3|TS=t3|EQPX=150.00|EQQTY=200|TRADES=2|IMBQTY=0");

    await waitFor(() => gaps.length === 1, 2000, "the reported gap");
    expect(gaps[0]).toMatchObject({ ch: "AUCTION", sym: "AAPL" });
    expect(gateway.linesStartingWith("RESUME")).toEqual([]);
  });

  it("tracks gaps per symbol independently", async () => {
    const { gateway, gaps } = await connected({ symbols: ["AAPL", "MSFT"] });
    gateway.setReplayMiss("TRADE", "AAPL");

    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t|PX=1|QTY=1|SIDE=BUY");
    gateway.emit("TRADE|CH=TRADE|SYM=MSFT|SEQ=1|TS=t|PX=1|QTY=1|SIDE=BUY");
    await new Promise((resolve) => setTimeout(resolve, 30));

    // Only AAPL's stream skips a sequence number; MSFT's stays consecutive.
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=5|TS=t|PX=1|QTY=1|SIDE=BUY");
    gateway.emit("TRADE|CH=TRADE|SYM=MSFT|SEQ=2|TS=t|PX=1|QTY=1|SIDE=BUY");

    await waitFor(() => gaps.length === 1, 2000, "the one reported gap");
    expect(gaps[0]).toMatchObject({ ch: "TRADE", sym: "AAPL" });
  });

  it("keeps its gap baseline across a reconnect, so a lost print is still noticed", async () => {
    const harness = await connected();
    harness.gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t1|PX=149.90|QTY=100|SIDE=BUY");
    await waitFor(() => frameOf(harness.frames, "trade").length === 1, 2000, "the print before the drop");

    await reconnect(harness);
    harness.gateway.setReplayMiss("TRADE", "AAPL");
    // The gateway lost the print that would have been SEQ=2 while this
    // bridge was disconnected; the next one it sees is SEQ=3.
    harness.gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=3|TS=t3|PX=150.00|QTY=50|SIDE=BUY");

    await waitFor(() => harness.gaps.length === 1, 2000, "the gap surviving the reconnect");
    expect(harness.gaps[0]).toMatchObject({ ch: "TRADE", sym: "AAPL" });
  });

  it("resumes only TRADE — every other channel is left to SNAP or reported unrepaired", async () => {
    // Pins RESUMABLE_CHANNELS's exact membership. A channel wrongly added to
    // it would start resuming data a SNAP is about to supersede (TOP/STATE/
    // DEPTH/CB) or one this change deliberately did not extend to (AUCTION),
    // so every non-TRADE channel gets the same "gap happened, no RESUME sent"
    // shape checked here in one place.
    const { gateway, gaps } = await connected();
    const cases: Array<{ line1: string; line2: string; ch: string; snapBacked: boolean }> = [
      {
        ch: "TOP",
        snapBacked: true,
        line1: "SNAP|CH=TOP|SYM=AAPL|SEQ=1|TS=t1|BID=150.00",
        line2: "MD|CH=TOP|SYM=AAPL|SEQ=9|TS=t9|BID=150.05",
      },
      {
        ch: "STATE",
        snapBacked: true,
        line1: "STATE|CH=STATE|SYM=AAPL|SEQ=1|TS=t1|SESSION=CONTINUOUS",
        line2: "STATE|CH=STATE|SYM=AAPL|SEQ=9|TS=t9|SESSION=HALTED|PREV=CONTINUOUS",
      },
      {
        ch: "DEPTH",
        snapBacked: true,
        line1: "SNAP|CH=DEPTH|SYM=AAPL|SEQ=1|TS=t1|LEVELS=10|BIDS=150.10:100:1|ASKS=150.12:100:1",
        line2: "DEPTH|CH=DEPTH|SYM=AAPL|SEQ=9|TS=t9|LEVELS=10|BIDS=150.09:100:1|ASKS=150.13:100:1",
      },
      {
        ch: "CB",
        snapBacked: true,
        line1: "SNAP|CH=CB|SYM=AAPL|SEQ=1|TS=t1|STATUS=NONE",
        line2: "CB|CH=CB|SYM=AAPL|SEQ=9|TS=t9|STATUS=HALTED|LEVEL=L1",
      },
      {
        ch: "AUCTION",
        snapBacked: false,
        line1: "AUCTION|CH=AUCTION|SYM=AAPL|SEQ=1|TS=t1|EQPX=149.85|EQQTY=100|TRADES=1|IMBQTY=0",
        line2: "AUCTION|CH=AUCTION|SYM=AAPL|SEQ=9|TS=t9|EQPX=150.00|EQQTY=200|TRADES=2|IMBQTY=0",
      },
    ];

    for (const { line1, line2, ch, snapBacked } of cases) {
      gateway.emit(line1);
      await new Promise((resolve) => setTimeout(resolve, 20));
      gateway.emit(line2);
      await new Promise((resolve) => setTimeout(resolve, 20));

      expect(gateway.linesStartingWith(`RESUME|CH=${ch}`)).toEqual([]);
      expect(gaps.some((g) => g.ch === ch)).toBe(!snapBacked);
    }
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

  it("attempts no RESUME when a reconnect loses nothing", async () => {
    // A stream with no prior SEQ recorded has no baseline to have lost —
    // establishing one is not resuming it. Covers the ordinary case where a
    // fresh connection has not yet seen a TRADE for any symbol.
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

describe("subscription accounting", () => {
  it("reports the edge when a per-symbol subscription opens", async () => {
    const harness = await connected();
    const events: Array<{ action: string; ch: string; sym: string; held: number }> = [];
    harness.uplink.on("subscription", (event) => events.push(event));

    harness.uplink.watch("DEPTH", "AAPL");

    expect(events).toEqual([{ action: "SUB", ch: "DEPTH", sym: "AAPL", held: 1 }]);
  });

  it("stays quiet for a second interested party, which opens nothing new", async () => {
    const harness = await connected();
    harness.uplink.watch("CB", "TSLA");
    const events: Array<{ action: string }> = [];
    harness.uplink.on("subscription", (event) => events.push(event));

    harness.uplink.watch("CB", "TSLA");

    expect(events).toEqual([]);
  });

  it("reports the closing edge and how many streams remain held", async () => {
    const harness = await connected();
    harness.uplink.watch("DEPTH", "AAPL");
    harness.uplink.watch("CB", "TSLA");
    const events: Array<{ action: string; sym: string; held: number }> = [];
    harness.uplink.on("subscription", (event) => events.push(event));

    harness.uplink.unwatch("DEPTH", "AAPL");

    expect(events).toEqual([{ action: "UNSUB", ch: "DEPTH", sym: "AAPL", held: 1 }]);
  });
});

describe("symbol discovery", () => {
  it("asks for the universe rather than relying on WELCOME alone", async () => {
    const harness = await connected();
    await waitFor(
      () => harness.gateway.linesStartingWith("SYMBOLS").length === 1,
      2000,
      "the SYMBOLS request",
    );
  });

  it("learns symbols a gateway that sent no WELCOME list still knows about", async () => {
    // Exactly the misconfigured case: pm-md-gwy started without an engine
    // config, so WELCOME carries no SYMBOLS= at all.
    const harness = await connected({ symbols: [], symbolsOnRequest: ["AAPL", "MSFT", "TSLA"] });

    await waitFor(() => harness.uplink.symbols().length === 3, 2000, "the symbol list");
    expect(harness.uplink.symbols()).toEqual(["AAPL", "MSFT", "TSLA"]);
  });

  it("re-asks after a reconnect, picking up anything listed since", async () => {
    const harness = await connected({ symbols: ["AAPL"] });
    await reconnect(harness);

    await waitFor(
      () => harness.gateway.linesStartingWith("SYMBOLS").length === 2,
      2000,
      "the second SYMBOLS request",
    );
  });

  it("merges the reply with symbols already seen on the wire", async () => {
    const harness = await connected({ symbols: ["AAPL"] });
    harness.gateway.emit("TRADE|CH=TRADE|SYM=NEWCO|SEQ=1|TS=t|PX=1|QTY=1|SIDE=BUY");

    await waitFor(() => harness.uplink.symbols().includes("NEWCO"), 2000, "the live symbol");
    expect(harness.uplink.symbols()).toContain("AAPL");
  });

  it("copes with a gateway that knows of no instruments at all", async () => {
    const harness = await connected({ symbols: [] });
    await waitFor(
      () => harness.gateway.linesStartingWith("SYMBOLS").length === 1,
      2000,
      "the SYMBOLS request",
    );
    expect(harness.uplink.symbols()).toEqual([]);
  });
});

describe("book snapshot for a newly connected tab", () => {
  it("hands over the current merged book for every symbol seen", async () => {
    /*
     * A browser that reconnects still has the pre-outage book on screen and
     * no way to know it is stale — the gateway will not resend a SNAP to
     * *this* bridge, whose own CALF session never dropped. Without this the
     * tab renders a stale price with the status strip back to "connected",
     * which is the one failure this terminal must not have.
     */
    const { gateway, uplink } = await connected();
    gateway.emit("SNAP|CH=TOP|SYM=AAPL|SEQ=1|TS=t1|BID=150.10|BIDSZ=1400|ASK=150.12|ASKSZ=900");
    gateway.emit("MD|CH=TOP|SYM=AAPL|SEQ=2|TS=t2|BID=150.11");
    gateway.emit("SNAP|CH=TOP|SYM=MSFT|SEQ=1|TS=t1|BID=421.00|ASK=421.05");
    await waitFor(() => frameOf(uplink.bookSnapshot(), "top").length === 2, 2000, "both symbols cached");

    const byName = Object.fromEntries(frameOf(uplink.bookSnapshot(), "top").map((f) => [f.sym, f]));

    // The merged view, not the last delta: an MD carries only what moved.
    expect(byName["AAPL"]).toMatchObject({ type: "top", bid: 150.11, ask: 150.12, askSz: 900 });
    expect(byName["MSFT"]).toMatchObject({ type: "top", bid: 421.0 });
  });

  it("marks the replay as carrying no stream position", async () => {
    // SEQ=0 is this codebase's existing "no usable position", and a consumer
    // must not gap-check a replay against the live stream it is not part of.
    const { gateway, uplink } = await connected();
    gateway.emit("SNAP|CH=TOP|SYM=AAPL|SEQ=7|TS=t1|BID=150.10");
    await waitFor(() => frameOf(uplink.bookSnapshot(), "top").length === 1, 2000, "the cached book");

    expect(frameOf(uplink.bookSnapshot(), "top")[0]).toMatchObject({ seq: 0, ts: "" });
  });

  it("is empty before anything has arrived, rather than inventing a book", async () => {
    const { uplink } = await connected();
    expect(uplink.bookSnapshot()).toEqual([]);
  });

  it("replays halt and session state, not just prices", async () => {
    /*
     * A HALT badge on a symbol that resumed during the outage, or its
     * absence on one that halted, is wrong in the direction that matters —
     * and the frames that would have corrected it were broadcast to nobody
     * while the tab was away.
     */
    const { gateway, uplink } = await connected();
    gateway.emit("STATE|CH=STATE|SYM=*|SEQ=1|TS=t1|SESSION=CLOSING_AUCTION");
    gateway.emit("STATE|CH=STATE|SYM=TSLA|SEQ=1|TS=t1|SESSION=HALTED|PREV=CONTINUOUS");
    gateway.emit("CB|CH=CB|SYM=TSLA|SEQ=1|TS=t1|STATUS=HALTED|LEVEL=L2");
    await waitFor(() => uplink.bookSnapshot().length === 3, 2000, "the cached state");

    const replay = uplink.bookSnapshot();
    expect(
      frameOf(replay, "state")
        .map((f) => f.sym)
        .sort(),
    ).toEqual(["*", "TSLA"]);
    expect(frameOf(replay, "halt_context")[0]).toMatchObject({ sym: "TSLA", level: "L2" });
  });

  it("keeps only the newest state per symbol, since it describes now", async () => {
    // A resume supersedes the halt that preceded it; replaying both would
    // hand a tab a contradiction to resolve.
    const { gateway, uplink } = await connected();
    gateway.emit("STATE|CH=STATE|SYM=TSLA|SEQ=1|TS=t1|SESSION=HALTED");
    gateway.emit("STATE|CH=STATE|SYM=TSLA|SEQ=2|TS=t2|SESSION=CONTINUOUS|PREV=HALTED");
    // Not on length: one entry is satisfied by the halt alone, so waiting on
    // it would read the cache before the resume landed.
    await waitFor(
      () => frameOf(uplink.bookSnapshot(), "state")[0]?.session === "CONTINUOUS",
      2000,
      "the resume to supersede the halt",
    );

    expect(frameOf(uplink.bookSnapshot(), "state")[0]).toMatchObject({ session: "CONTINUOUS" });
  });

  it("puts session and halt state before the prices they qualify", async () => {
    const { gateway, uplink } = await connected();
    gateway.emit("SNAP|CH=TOP|SYM=AAPL|SEQ=1|TS=t1|BID=150.10");
    gateway.emit("STATE|CH=STATE|SYM=*|SEQ=1|TS=t1|SESSION=CLOSED");
    await waitFor(() => uplink.bookSnapshot().length === 2, 2000, "both cached");

    // A tab should know the market is closed before it is handed a price to
    // render under that heading.
    expect(uplink.bookSnapshot()[0]?.type).toBe("state");
  });

  it("hands out detached copies, so a later delta cannot mutate what a tab was sent", async () => {
    const { gateway, uplink } = await connected();
    gateway.emit("SNAP|CH=TOP|SYM=AAPL|SEQ=1|TS=t1|BID=150.10");
    await waitFor(() => frameOf(uplink.bookSnapshot(), "top").length === 1, 2000, "the cached book");

    const sent = frameOf(uplink.bookSnapshot(), "top")[0];
    gateway.emit("MD|CH=TOP|SYM=AAPL|SEQ=2|TS=t2|BID=999.99");
    await new Promise((resolve) => setTimeout(resolve, 30));

    expect(sent).toMatchObject({ bid: 150.1 });
  });
});

describe("malformed market data", () => {
  it("drops a TRADE with no price rather than printing it at zero", async () => {
    // decodeTrade defaults a missing PX to 0 so its return type stays total,
    // and 0 renders on the tape as a real print of 0.00 for 0 shares. The
    // tape is allowed to be missing a print; it is not allowed to invent one.
    const { gateway, frames, errors } = await connected();
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t1|QTY=100|SIDE=BUY");
    await waitFor(() => errors.some((e) => e.code === "MALFORMED_TRADE"), 2000, "the rejection");

    expect(frameOf(frames, "trade")).toEqual([]);
  });

  it("drops a TRADE with no size for the same reason", async () => {
    const { gateway, frames, errors } = await connected();
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t1|PX=150.10|SIDE=BUY");
    await waitFor(() => errors.some((e) => e.code === "MALFORMED_TRADE"), 2000, "the rejection");

    expect(frameOf(frames, "trade")).toEqual([]);
  });

  it("still passes a well-formed print through untouched", async () => {
    const { gateway, frames } = await connected();
    gateway.emit("TRADE|CH=TRADE|SYM=AAPL|SEQ=1|TS=t1|PX=150.10|QTY=100|SIDE=BUY");
    await waitFor(() => frameOf(frames, "trade").length === 1, 2000, "the print");

    expect(frameOf(frames, "trade")[0]).toMatchObject({ px: 150.1, qty: 100, side: "BUY" });
  });
});

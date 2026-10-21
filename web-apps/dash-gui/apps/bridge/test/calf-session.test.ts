/** The md-gwy session uplink (WP-UI01): a plain TCP server in this process plays pm-md-gwy. */

import { createServer, type Server, type Socket } from "node:net";
import { afterEach, describe, expect, it } from "vitest";
import type { MarketSession } from "@edumatcher/dash-types";
import { CalfSessionUplink, sessionFromLine } from "../src/calf-session.js";

const until = async (cond: () => boolean, ms = 3000) => {
  const deadline = Date.now() + ms;
  while (!cond()) {
    if (Date.now() > deadline) throw new Error("timed out");
    await new Promise((r) => setTimeout(r, 20));
  }
};

/** Accepts connections, records what clients send, and lets the test write lines back. */
class FakeMdGwy {
  readonly received: string[] = [];
  readonly sockets: Socket[] = [];
  private server: Server | null = null;
  port = 0;

  async start(): Promise<void> {
    this.server = createServer((socket) => {
      this.sockets.push(socket);
      socket.on("error", () => undefined);
      socket.on("data", (chunk) => this.received.push(...chunk.toString("utf8").split("\n").filter(Boolean)));
    });
    await new Promise<void>((resolve) => this.server!.listen(0, "127.0.0.1", resolve));
    this.port = (this.server.address() as { port: number }).port;
  }

  send(line: string): void {
    this.sockets.at(-1)!.write(`${line}\n`);
  }

  async stop(): Promise<void> {
    for (const s of this.sockets) s.destroy();
    await new Promise<void>((resolve) => this.server?.close(() => resolve()));
  }
}

let gwy: FakeMdGwy | undefined;
let uplink: CalfSessionUplink | undefined;
afterEach(async () => {
  uplink?.stop();
  await gwy?.stop();
  uplink = gwy = undefined;
});

describe("sessionFromLine", () => {
  it("reads SNAP and STATE lines on the exchange-wide stream", () => {
    expect(
      sessionFromLine(
        "SNAP|CH=STATE|SYM=*|SEQ=1|TS=2026-10-21T10:00:00Z|SESSION=CONTINUOUS|NEXTPHASE=CLOSING_AUCTION|NEXTAT=2026-10-21T15:20:00Z",
      ),
    ).toEqual({ state: "CONTINUOUS", nextState: "CLOSING_AUCTION", nextAt: "2026-10-21T15:20:00Z" });
    expect(sessionFromLine("STATE|CH=STATE|SYM=*|SEQ=2|TS=x|SESSION=CLOSED|PREV=CLOSING_AUCTION")).toEqual({
      state: "CLOSED",
      nextState: null,
      nextAt: null,
    });
  });

  it("ignores per-symbol STATE, other channels, other messages, and half a next transition", () => {
    expect(sessionFromLine("STATE|CH=STATE|SYM=ABC|SEQ=1|SESSION=HALTED")).toBeNull();
    expect(sessionFromLine("SNAP|CH=TOP|SYM=*|SEQ=1")).toBeNull();
    expect(sessionFromLine("HB|TS=2026-10-21T10:00:00Z")).toBeNull();
    expect(sessionFromLine("SNAP|CH=STATE|SYM=*|SESSION=CONTINUOUS|NEXTPHASE=CLOSED")?.nextState).toBeNull();
  });
});

describe("over TCP", () => {
  it("subscribes to the exchange-wide STATE stream and follows transitions", async () => {
    gwy = new FakeMdGwy();
    await gwy.start();
    uplink = new CalfSessionUplink({ host: "127.0.0.1", port: gwy.port, clientId: "test-bridge" });
    const seen: MarketSession[] = [];
    uplink.on("session", (s) => seen.push(s));
    expect(uplink.latest.state).toBe("UNKNOWN");
    uplink.start();

    await until(() => gwy!.received.length >= 2);
    expect(gwy.received).toEqual(["HELLO|CLIENT=test-bridge|PROTO=CALF1", "SUB|CH=STATE|SYM=*"]);

    gwy.send("WELCOME|SERVER=md-gwy01");
    gwy.send(
      "SNAP|CH=STATE|SYM=*|SEQ=1|SESSION=PRE_OPEN|NEXTPHASE=OPENING_AUCTION|NEXTAT=2026-10-21T08:50:00Z",
    );
    gwy.send("HB|TS=x");
    // A line split across two packets.
    gwy.sockets[0]!.write("STATE|CH=STATE|SYM=*|SEQ=2|SESS");
    await new Promise((r) => setTimeout(r, 30));
    gwy.send("ION=OPENING_AUCTION|PREV=PRE_OPEN");
    await until(() => seen.length === 2);
    expect(seen).toEqual([
      { state: "PRE_OPEN", nextState: "OPENING_AUCTION", nextAt: "2026-10-21T08:50:00Z" },
      { state: "OPENING_AUCTION", nextState: null, nextAt: null },
    ]);
    expect(uplink.latest.state).toBe("OPENING_AUCTION");
  });

  it("is UNKNOWN while md-gwy is gone, and reconnects", async () => {
    gwy = new FakeMdGwy();
    await gwy.start();
    uplink = new CalfSessionUplink({ host: "127.0.0.1", port: gwy.port, clientId: "t", backoffMinMs: 20 });
    uplink.start();
    await until(() => gwy!.sockets.length === 1);
    gwy.send("SNAP|CH=STATE|SYM=*|SEQ=1|SESSION=CONTINUOUS");
    await until(() => uplink!.latest.state === "CONTINUOUS");

    gwy.sockets[0]!.destroy();
    await until(() => uplink!.latest.state === "UNKNOWN");
    await until(() => gwy!.sockets.length === 2);
  });

  it("treats a silent connection as dead", async () => {
    gwy = new FakeMdGwy();
    await gwy.start();
    uplink = new CalfSessionUplink({
      host: "127.0.0.1",
      port: gwy.port,
      clientId: "t",
      silenceSec: 0.2,
      backoffMinMs: 20,
    });
    uplink.start();
    await until(() => gwy!.sockets.length === 1);
    gwy.send("SNAP|CH=STATE|SYM=*|SEQ=1|SESSION=CONTINUOUS");
    await until(() => uplink!.latest.state === "CONTINUOUS");
    await until(() => uplink!.latest.state === "UNKNOWN");
    await until(() => gwy!.sockets.length === 2);
  });
});

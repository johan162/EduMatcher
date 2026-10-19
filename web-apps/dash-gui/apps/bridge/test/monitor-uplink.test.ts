/** The pm-monitor uplink (WP-C2.1): a real ZeroMQ PUB in this process plays pm-monitor. */

import * as zmq from "zeromq";
import { afterEach, describe, expect, it } from "vitest";
import { MonitorUplink } from "../src/monitor-uplink.js";
import { frames, snapshot } from "./harness.js";

let pub: zmq.Publisher | undefined;
let uplink: MonitorUplink | undefined;
afterEach(() => {
  uplink?.stop();
  pub?.close();
  uplink = pub = undefined;
});

async function publisher(): Promise<{ pub: zmq.Publisher; port: number }> {
  const p = new zmq.Publisher();
  await p.bind("tcp://127.0.0.1:*");
  return { pub: p, port: Number(p.lastEndpoint!.split(":").at(-1)) };
}

const until = async (cond: () => boolean, ms = 3000) => {
  const deadline = Date.now() + ms;
  while (!cond()) {
    if (Date.now() > deadline) throw new Error("timed out");
    await new Promise((r) => setTimeout(r, 20));
  }
};

describe("over ZeroMQ", () => {
  it("receives snapshots and events, then goes DOWN when they stop", async () => {
    const p = await publisher();
    pub = p.pub;
    uplink = new MonitorUplink({ host: "127.0.0.1", pubPort: p.port, downAfterSec: 0.4, checkIntervalMs: 20 });
    const states: string[] = [];
    const events: number[] = [];
    uplink.on("state", (s) => states.push(s));
    uplink.on("event", (e) => events.push(e.data.seq));
    uplink.start();

    // A SUB joins a moment after connect; publish until the first arrives.
    let seq = 0;
    while (uplink.snapshotsIn === 0) {
      await pub.send(frames("health.snapshot", snapshot(seq++)));
      await new Promise((r) => setTimeout(r, 20));
      if (seq > 150) throw new Error("no snapshot arrived");
    }
    expect(uplink.state).toBe("UP");
    expect(uplink.latest?.data.exchange.session_timezone).toBe("Europe/Stockholm");

    await pub.send(frames("health.event", { seq: 7, ts: "x", kind: "CONNECT", severity: "INFO", subject: "GW01", detail: "" }));
    await pub.send(frames("other.topic", {}));
    await until(() => events.length === 1);
    expect(events).toEqual([7]);

    await until(() => uplink!.state === "DOWN");
    expect(states).toEqual(["UP", "DOWN"]);
    expect(uplink.latest).toBeNull();
  });
});

describe("state and decoding", () => {
  it("is DOWN at start, UP on a snapshot, DOWN after exactly downAfterSec of silence", () => {
    let now = 1_000_000;
    uplink = new MonitorUplink({ host: "x", pubPort: 1, downAfterSec: 3, now: () => now });
    expect(uplink.state).toBe("DOWN");
    uplink.handle(frames("health.snapshot", snapshot(1)));
    expect(uplink.state).toBe("UP");
    now += 2999;
    uplink.checkSilence();
    expect(uplink.state).toBe("UP");
    now += 1;
    uplink.checkSilence();
    expect(uplink.state).toBe("DOWN");
    expect(uplink.stateSince).toBe(now);
  });

  it("an event alone does not make pm-monitor UP", () => {
    uplink = new MonitorUplink({ host: "x", pubPort: 1, downAfterSec: 3 });
    uplink.handle(frames("health.event", { seq: 1 }));
    expect(uplink.state).toBe("DOWN");
    expect(uplink.eventsIn).toBe(1);
  });

  it("keeps the payload text as received, and counts what it cannot read", () => {
    uplink = new MonitorUplink({ host: "x", pubPort: 1, downAfterSec: 3 });
    const text = '{"seq": 5,  "ts":"t"}';
    uplink.handle([Buffer.from("health.snapshot"), Buffer.from(text)]);
    expect(uplink.latest?.json).toBe(text);
    uplink.handle([Buffer.from("health.snapshot")]);
    uplink.handle([Buffer.from("health.snapshot"), Buffer.from("not json")]);
    uplink.handle([Buffer.from("health.event"), Buffer.from("[1,2]")]);
    expect(uplink.invalidIn).toBe(3);
    expect(uplink.snapshotsIn).toBe(1);
  });
});

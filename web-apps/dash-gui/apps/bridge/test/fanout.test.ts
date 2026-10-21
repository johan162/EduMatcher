/** `/ws` fan-out (WP-C2.2): what every tab receives, and a tab that does not read. */

import { afterEach, describe, expect, it } from "vitest";
import { frames, snapshot, startRig, Tab, type Rig } from "./harness.js";

let rig: Rig | undefined;
const tabs: Tab[] = [];
afterEach(async () => {
  for (const t of tabs.splice(0)) t.close();
  await rig?.stop();
  rig = undefined;
});

async function open(): Promise<Tab> {
  const tab = await Tab.open(rig!.port);
  tabs.push(tab);
  return tab;
}

describe("fan-out", () => {
  it("greets with hello and the session phase only while pm-monitor is DOWN", async () => {
    rig = await startRig();
    const tab = await open();
    expect(await tab.next("hello")).toMatchObject({ monitor: "DOWN", sessionTz: "UTC" });
    expect(await tab.next("market_session")).toEqual({
      type: "market_session",
      session: { state: "UNKNOWN", nextState: null, nextAt: null },
    });
    await new Promise((r) => setTimeout(r, 50));
    expect(tab.frames.map((f) => f.type)).toEqual(["hello", "market_session"]);
  });

  it("tells every tab when md-gwy's session phase changes", async () => {
    rig = await startRig();
    const tab = await open();
    await tab.next("market_session");
    const greeted = tab.frames.length;
    const session = { state: "CONTINUOUS", nextState: "CLOSING_AUCTION", nextAt: "2026-10-21T15:20:00Z" };
    rig.bridge.session.emit("session", session);
    expect(await tab.next("market_session", greeted)).toEqual({ type: "market_session", session });
  });

  it("sends hello and the latest snapshot on connect while UP", async () => {
    rig = await startRig();
    rig.bridge.uplink.handle(frames("health.snapshot", snapshot(41, "Asia/Kolkata")));
    const tab = await open();
    expect(await tab.next("hello")).toMatchObject({ monitor: "UP", sessionTz: "Asia/Kolkata" });
    expect((await tab.next("snapshot")).data.seq).toBe(41);
    expect(tab.frames.map((f) => f.type)).toEqual(["hello", "snapshot", "market_session"]);
  });

  it("forwards the same snapshot and event to every tab, unchanged", async () => {
    rig = await startRig();
    const a = await open();
    const b = await open();
    await a.next("hello");
    await b.next("hello");
    const snap = snapshot(7);
    rig.bridge.uplink.handle(frames("health.snapshot", snap));
    const event = { seq: 3, ts: "2026-10-19T08:00:01.000Z", kind: "CONNECT", severity: "INFO", subject: "GW01", detail: "" };
    rig.bridge.uplink.handle(frames("health.event", event));
    for (const tab of [a, b]) {
      expect((await tab.next("snapshot")).data).toEqual(snap);
      expect((await tab.next("event")).data).toEqual(event);
      expect(await tab.next("monitor_state")).toEqual({ type: "monitor_state", monitor: "UP" });
    }
  });

  it("tells every tab when pm-monitor goes DOWN", async () => {
    let now = 0;
    rig = await startRig({ monitor: { host: "127.0.0.1", pubPort: 1, downAfterSec: 3 } }, { connect: false, now: () => now });
    const tab = await open();
    rig.bridge.uplink.handle(frames("health.snapshot", snapshot(1)));
    await tab.next("snapshot");
    now += 3000;
    rig.bridge.uplink.checkSilence();
    const states = async () => {
      await new Promise((r) => setTimeout(r, 50));
      return tab.frames.filter((f) => f.type === "monitor_state").map((f) => (f.type === "monitor_state" ? f.monitor : ""));
    };
    expect(await states()).toEqual(["UP", "DOWN"]);
    // a tab connecting now gets no stale snapshot
    const late = await open();
    await late.next("hello");
    await new Promise((r) => setTimeout(r, 50));
    expect(late.frames.map((f) => f.type)).toEqual(["hello", "market_session"]);
  });

  it("cuts off a tab that does not read instead of buffering for it", async () => {
    rig = await startRig({ wsMaxBufferedBytes: 256 * 1024 });
    const slow = await open();
    const fast = await open();
    await slow.next("hello");
    await fast.next("hello");
    // Stop reading: TCP fills, then the bridge's outbound buffer grows.
    (slow.socket as unknown as { _socket: { pause(): void } })._socket.pause();
    const closed = new Promise<void>((resolve) => slow.socket.once("close", () => resolve()));

    const big = { ...snapshot(1), pad: "x".repeat(64 * 1024) };
    for (let i = 0; i < 400 && rig.bridge.hub.slowClosed === 0; i++) {
      rig.bridge.uplink.handle(frames("health.snapshot", { ...big, seq: i }));
      await new Promise((r) => setImmediate(r));
    }
    expect(rig.bridge.hub.slowClosed).toBe(1);
    (slow.socket as unknown as { _socket: { resume(): void } })._socket.resume();
    await closed;
    // the reader is unaffected
    expect(rig.bridge.hub.clientCount).toBe(1);
    expect(fast.socket.readyState).toBe(fast.socket.OPEN);
  });
});

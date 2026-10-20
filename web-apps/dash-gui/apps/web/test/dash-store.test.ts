import { beforeEach, describe, expect, it, vi } from "vitest";
import type { HealthEvent, HealthSnapshot } from "@edumatcher/dash-types";
import { MAX_EVENTS, useDashStore } from "../src/store/useDashStore.js";
import { fixtureSnapshot } from "./fixtures/snapshots.js";

const snap = (seq: number, tz = "Europe/Stockholm"): HealthSnapshot =>
  fixtureSnapshot({ seq, ts: new Date(Date.parse("2026-10-20T08:00:00Z") + seq * 1000).toISOString(), exchange: { session_timezone: tz } });
const event = (seq: number): HealthEvent => ({ seq, ts: "t", kind: "CONNECT", severity: "INFO", subject: "GW01", detail: "" });

beforeEach(() => {
  useDashStore.setState({ socket: "OPEN", monitor: null, bridgeVersion: null, sessionTz: "UTC", snapshot: null, events: [], recent: [] });
});

describe("useDashStore", () => {
  it("keeps the latest snapshot and its session timezone", () => {
    const { apply } = useDashStore.getState();
    apply({ type: "hello", version: "1", monitor: "UP", sessionTz: "UTC" });
    apply({ type: "snapshot", data: snap(1, "Asia/Kolkata") });
    apply({ type: "snapshot", data: snap(2, "Asia/Kolkata") });
    expect(useDashStore.getState().snapshot?.seq).toBe(2);
    expect(useDashStore.getState().sessionTz).toBe("Asia/Kolkata");
  });

  it("keeps the last snapshot, frozen, when pm-monitor or the socket goes away", () => {
    const { apply, setSocket } = useDashStore.getState();
    apply({ type: "hello", version: "1", monitor: "UP", sessionTz: "UTC" });
    apply({ type: "snapshot", data: snap(1) });
    apply({ type: "monitor_state", monitor: "DOWN" });
    expect(useDashStore.getState().snapshot?.seq).toBe(1);
    expect(useDashStore.getState().connection()).toBe("NO_MONITOR");
    setSocket("CLOSED");
    expect(useDashStore.getState().snapshot?.seq).toBe(1);
    expect(useDashStore.getState().connection()).toBe("OFFLINE");
  });

  it("appends live events and keeps the newest MAX_EVENTS", () => {
    const { apply } = useDashStore.getState();
    for (let s = 1; s < MAX_EVENTS + 10; s++) apply({ type: "event", data: event(s) });
    const events = useDashStore.getState().events;
    expect(events).toHaveLength(MAX_EVENTS);
    expect(events.at(-1)!.seq).toBe(MAX_EVENTS + 9);
  });

  it("a live event with an older seq starts the list again (a new metrics.db)", () => {
    const { apply } = useDashStore.getState();
    for (const s of [40, 41, 42]) apply({ type: "event", data: event(s) });
    apply({ type: "event", data: event(1) });
    expect(useDashStore.getState().events.map((e) => e.seq)).toEqual([1]);
  });

  it("a catch-up that answers after newer live events is merged in seq order, without duplicates", () => {
    const { apply, addEvents } = useDashStore.getState();
    apply({ type: "event", data: event(1) });
    apply({ type: "event", data: event(5) }); // live, while 2-4 were missed
    addEvents([event(2), event(3), event(4), event(5)]);
    expect(useDashStore.getState().events.map((e) => e.seq)).toEqual([1, 2, 3, 4, 5]);
  });

  it("a live event a catch-up already brought is a duplicate, not a new numbering (I118)", () => {
    // pm-monitor stores an event before publishing it: /api/events can answer with it first.
    const { apply, addEvents } = useDashStore.getState();
    apply({ type: "event", data: event(40) });
    addEvents([event(41), event(42)]);
    apply({ type: "event", data: event(42) });
    apply({ type: "event", data: event(41) });
    expect(useDashStore.getState().events.map((e) => e.seq)).toEqual([40, 41, 42]);
    apply({ type: "event", data: event(43) });
    expect(useDashStore.getState().events.map((e) => e.seq)).toEqual([40, 41, 42, 43]);
  });
});

describe("the range at load", () => {
  it("is the page's ?from=, so the first fetch asks for it (I118)", async () => {
    vi.stubGlobal("location", { search: "?from=now-6h" });
    vi.resetModules();
    const fresh = await import("../src/store/useDashStore.js");
    expect(fresh.useDashStore.getState().range).toBe("6h");
    vi.stubGlobal("location", { search: "?from=now-3w" });
    vi.resetModules();
    expect((await import("../src/store/useDashStore.js")).useDashStore.getState().range).toBe("1h");
    vi.unstubAllGlobals();
  });
});

describe("the sparklines' last minute", () => {
  it("keeps one sample per snapshot, the last 60", () => {
    const { apply } = useDashStore.getState();
    for (let seq = 1; seq <= 70; seq++) apply({ type: "snapshot", data: snap(seq) });
    const recent = useDashStore.getState().recent;
    expect(recent).toHaveLength(60);
    expect(recent.at(-1)).toMatchObject({ ordersPerSec: CAPTURED_ORDERS, participantsConnected: 2 });
    expect(recent[0]!.ts).toBe(Date.parse("2026-10-20T08:00:11Z"));
  });

  it("a snapshot repeated (same ts) replaces its sample", () => {
    const { apply } = useDashStore.getState();
    apply({ type: "snapshot", data: snap(1) });
    apply({ type: "snapshot", data: snap(1) });
    expect(useDashStore.getState().recent).toHaveLength(1);
  });
});

const CAPTURED_ORDERS = fixtureSnapshot().trading.orders.per_sec_now;

import { beforeEach, describe, expect, it } from "vitest";
import type { HealthEvent, HealthSnapshot } from "@edumatcher/dash-types";
import { MAX_EVENTS, useDashStore } from "../src/store/useDashStore.js";

const snap = (seq: number, tz = "Europe/Stockholm") =>
  ({ seq, ts: "t", exchange: { status: "OPERATIONAL", session_state: "", trading_date: "", session_timezone: tz } }) as unknown as HealthSnapshot;
const event = (seq: number): HealthEvent => ({ seq, ts: "t", kind: "CONNECT", severity: "INFO", subject: "GW01", detail: "" });

beforeEach(() => {
  useDashStore.setState({ socket: "OPEN", monitor: null, bridgeVersion: null, sessionTz: "UTC", snapshot: null, events: [] });
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
});

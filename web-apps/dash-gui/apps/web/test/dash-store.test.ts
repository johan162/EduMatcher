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

  it("forgets the snapshot when pm-monitor or the socket goes away", () => {
    const { apply, setSocket } = useDashStore.getState();
    apply({ type: "snapshot", data: snap(1) });
    apply({ type: "monitor_state", monitor: "DOWN" });
    expect(useDashStore.getState().snapshot).toBeNull();
    apply({ type: "snapshot", data: snap(2) });
    setSocket("CLOSED");
    expect(useDashStore.getState().snapshot).toBeNull();
  });

  it("appends events in seq order, ignores replays, and keeps the newest MAX_EVENTS", () => {
    const { apply } = useDashStore.getState();
    apply({ type: "event", data: event(1) });
    apply({ type: "event", data: event(2) });
    apply({ type: "event", data: event(2) });
    expect(useDashStore.getState().events.map((e) => e.seq)).toEqual([1, 2]);
    for (let s = 3; s < MAX_EVENTS + 10; s++) apply({ type: "event", data: event(s) });
    const events = useDashStore.getState().events;
    expect(events).toHaveLength(MAX_EVENTS);
    expect(events.at(-1)!.seq).toBe(MAX_EVENTS + 9);
  });
});

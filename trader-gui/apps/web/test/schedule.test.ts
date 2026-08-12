import { describe, it, expect } from "vitest";
import { nextScheduledTransition, parseClockTime } from "@/lib/schedule";
import { useSessionStore } from "@/store/useSessionStore";

const SCHEDULE = {
  sessions_enabled: true,
  country: "SE",
  schedule: {
    pre_open: "08:00",
    opening_auction_start: "08:45",
    continuous_start: "09:00",
    closing_auction_start: "17:20",
    closing_auction_end: "17:30:00",
  },
};

/** Local-time helper — the schedule is the venue operator's wall clock. */
function at(h: number, m: number, s = 0): number {
  const d = new Date();
  d.setHours(h, m, s, 0);
  return d.getTime();
}

describe("parseClockTime", () => {
  it("accepts HH:MM and HH:MM:SS", () => {
    expect(parseClockTime("09:00")).toBe(9 * 3600);
    expect(parseClockTime("17:30:15")).toBe(17 * 3600 + 30 * 60 + 15);
  });

  it("rejects nonsense rather than coercing it", () => {
    for (const bad of ["", null, undefined, "9", "25:00", "09:60", "nine"]) {
      expect(parseClockTime(bad)).toBeNull();
    }
  });
});

describe("nextScheduledTransition", () => {
  it("finds the next boundary later today", () => {
    const next = nextScheduledTransition(SCHEDULE, at(9, 30));
    expect(next).toEqual({ toState: "CLOSING_AUCTION", at: at(17, 20) });
  });

  it("rolls to tomorrow's first boundary after the close", () => {
    const next = nextScheduledTransition(SCHEDULE, at(18, 0))!;
    expect(next.toState).toBe("PRE_OPEN");
    expect(next.at).toBeGreaterThan(at(18, 0));
    expect(new Date(next.at).getHours()).toBe(8);
  });

  it("returns null when sessions are disabled", () => {
    expect(nextScheduledTransition({ ...SCHEDULE, sessions_enabled: false }, at(9, 30))).toBeNull();
  });

  it("tolerates a partial schedule block", () => {
    const partial = { sessions_enabled: true, schedule: { continuous_start: "09:00" } };
    expect(nextScheduledTransition(partial, at(8, 0))).toEqual({
      toState: "CONTINUOUS",
      at: at(9, 0),
    });
    expect(nextScheduledTransition({ sessions_enabled: true, schedule: {} }, at(8, 0))).toBeNull();
    expect(nextScheduledTransition(null, at(8, 0))).toBeNull();
  });
});

describe("useSessionStore.countdownTarget", () => {
  it("prefers session.next over the configured schedule", () => {
    useSessionStore.setState({ schedule: SCHEDULE });
    useSessionStore.getState().setPhase("CONTINUOUS", "OPENING_AUCTION", {
      to_state: "CLOSING_AUCTION",
      at: new Date(at(16, 0)).toISOString(),
    });
    expect(useSessionStore.getState().countdownTarget(at(9, 30))).toEqual({
      toState: "CLOSING_AUCTION",
      at: at(16, 0),
    });
  });

  it("falls back to the schedule once the announced target has passed", () => {
    // An admin-forced transition leaves the scheduler's `next` in the past;
    // pinning the countdown at 00:00 there is the bug this guards.
    useSessionStore.setState({ schedule: SCHEDULE });
    useSessionStore.getState().setPhase("CONTINUOUS", "PRE_OPEN", {
      to_state: "CLOSING_AUCTION",
      at: new Date(at(9, 0)).toISOString(),
    });
    expect(useSessionStore.getState().countdownTarget(at(9, 30))).toEqual({
      toState: "CLOSING_AUCTION",
      at: at(17, 20),
    });
  });

  it("returns null when neither source has a target", () => {
    useSessionStore.setState({ schedule: null });
    useSessionStore.getState().setPhase("CLOSED", null, null);
    expect(useSessionStore.getState().countdownTarget(at(9, 30))).toBeNull();
  });

  it("ignores an unparseable next.at", () => {
    useSessionStore.setState({ schedule: null });
    useSessionStore.getState().setPhase("CONTINUOUS", null, {
      to_state: "CLOSED",
      at: "not-a-date",
    });
    expect(useSessionStore.getState().nextTransitionAt).toBeNull();
  });
});

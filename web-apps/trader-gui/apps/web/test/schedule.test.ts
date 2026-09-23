import { describe, it, expect } from "vitest";
import { nextScheduledTransition, parseClockTime } from "@/lib/schedule";
import { useSessionStore } from "@/store/useSessionStore";

const WEEKDAY_TIMES = {
  pre_open: "08:00",
  opening_auction_start: "08:45",
  continuous_start: "09:00",
  closing_auction_start: "17:20",
  closing_auction_end: "17:30:00",
};

const WEEKEND_TIMES = {
  pre_open: "10:00",
  opening_auction_start: "10:25",
  continuous_start: "10:30",
  closing_auction_start: "14:00",
  closing_auction_end: "14:05",
};

const HOLIDAY_TIMES = {
  pre_open: "10:00",
  opening_auction_start: "10:25",
  continuous_start: "10:30",
  closing_auction_start: "13:00",
  closing_auction_end: "13:05",
};

/** A Mon-Fri exchange, weekends/holidays CLOSED, `today` resolved to a weekday. */
const SCHEDULE = {
  sessions_enabled: true,
  country: "SE",
  schedule: {
    mon: WEEKDAY_TIMES,
    tue: WEEKDAY_TIMES,
    wed: WEEKDAY_TIMES,
    thu: WEEKDAY_TIMES,
    fri: WEEKDAY_TIMES,
    sat: null,
    sun: null,
    holidays: null,
    today: WEEKDAY_TIMES,
    today_is_holiday: false,
  },
};

/** Local-time helper — the schedule is the venue operator's wall clock. */
function at(h: number, m: number, s = 0): number {
  const d = new Date();
  d.setHours(h, m, s, 0);
  return d.getTime();
}

/** The `WeeklySchedule` key for the day after `now` — used to give the
 * rollover tests a real day-of-week entry regardless of which day the suite
 * actually runs on. */
const WEEKDAY_KEYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"] as const;
function tomorrowKey(): (typeof WEEKDAY_KEYS)[number] {
  return WEEKDAY_KEYS[(new Date().getDay() + 1) % 7]!;
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
    const schedule = {
      ...SCHEDULE,
      schedule: { ...SCHEDULE.schedule, [tomorrowKey()]: WEEKDAY_TIMES },
    };
    const next = nextScheduledTransition(schedule, at(18, 0))!;
    expect(next.toState).toBe("PRE_OPEN");
    expect(next.at).toBeGreaterThan(at(18, 0));
    expect(new Date(next.at).getHours()).toBe(8);
  });

  it("returns null when sessions are disabled", () => {
    expect(nextScheduledTransition({ ...SCHEDULE, sessions_enabled: false }, at(9, 30))).toBeNull();
  });

  it("returns null when there is no schedule at all", () => {
    expect(nextScheduledTransition({ sessions_enabled: true, schedule: null }, at(8, 0))).toBeNull();
    expect(nextScheduledTransition(null, at(8, 0))).toBeNull();
  });

  it("uses `today` as given, holiday hours included, without recomputing it", () => {
    // `today`'s hours differ from what the weekday entry would say — the
    // function must trust the server-resolved `today`, not recompute it.
    // At 09:30 the holiday's first boundary (pre_open 10:00) is next, not
    // the weekday's 09:00 continuous_start.
    const holidayToday = {
      sessions_enabled: true,
      schedule: { mon: WEEKDAY_TIMES, today: HOLIDAY_TIMES, today_is_holiday: true },
    };
    const next = nextScheduledTransition(holidayToday, at(9, 30));
    expect(next).toEqual({ toState: "PRE_OPEN", at: at(10, 0) });
  });

  it("rolls straight to tomorrow when today is CLOSED but tomorrow is scheduled", () => {
    // A weekend-only exchange: today (a weekday) is CLOSED, tomorrow (say,
    // Saturday) has its own hours.
    const weekendOnly = {
      sessions_enabled: true,
      schedule: { today: null, [tomorrowKey()]: WEEKEND_TIMES },
    };
    const next = nextScheduledTransition(weekendOnly, at(8, 0))!;
    expect(next.toState).toBe("PRE_OPEN");
    expect(new Date(next.at).getHours()).toBe(10);
    expect(new Date(next.at).getMinutes()).toBe(0);
  });

  it("returns null when today and tomorrow are both CLOSED", () => {
    const closed = {
      sessions_enabled: true,
      schedule: { today: null, [tomorrowKey()]: null },
    };
    expect(nextScheduledTransition(closed, at(8, 0))).toBeNull();
  });
});

describe("useSessionStore.countdownTarget", () => {
  it("prefers session.next over the configured schedule", () => {
    useSessionStore.setState({ schedule: SCHEDULE });
    useSessionStore.getState().setPhase("CONTINUOUS", "OPENING_AUCTION", {
      state: "CLOSING_AUCTION",
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
      state: "CLOSING_AUCTION",
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
      state: "CLOSED",
      at: "not-a-date",
    });
    expect(useSessionStore.getState().nextTransitionAt).toBeNull();
  });
});

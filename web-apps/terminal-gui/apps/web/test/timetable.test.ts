import { describe, expect, it } from "vitest";
import type { WeeklySchedule } from "@edumatcher/terminal-types";
import {
  currentStep,
  daySegments,
  exchangeNow,
  nextHoliday,
  nextTradingDay,
  segmentAt,
  weekOf,
} from "../src/lib/timetable";

const DAY = {
  pre_open: "08:00",
  opening_auction_start: "08:50",
  continuous_start: "09:00:00",
  closing_auction_start: "17:25",
  closing_auction_end: "17:30",
};
const SHORT = { ...DAY, closing_auction_start: "12:55", closing_auction_end: "13:00" };
const WEEK: WeeklySchedule = {
  mon: DAY,
  tue: DAY,
  wed: DAY,
  thu: DAY,
  fri: DAY,
  sat: null,
  sun: null,
  holidays: SHORT,
  upcoming_holidays: [
    { date: "2026-12-26", name: "Annandag jul" },
    { date: "2027-01-01", name: "Nyårsdagen" },
  ],
};

describe("daySegments", () => {
  it("covers the whole day in six phases", () => {
    const segments = daySegments(DAY)!;
    expect(segments.map((s) => s.phase)).toEqual([
      "CLOSED",
      "PRE_OPEN",
      "OPENING_AUCTION",
      "CONTINUOUS",
      "CLOSING_AUCTION",
      "CLOSED",
    ]);
    expect(segments[0]!.start).toBe(0);
    expect(segments[3]!.start).toBe(9 * 3600);
    expect(segments[5]!.end).toBe(86_400);
    expect(segmentAt(segments, 12 * 3600)).toBe(3);
    expect(segmentAt(segments, 17 * 3600 + 30 * 60)).toBe(5);
  });

  it("refuses a day it cannot draw", () => {
    expect(daySegments({ ...DAY, continuous_start: null })).toBeNull();
    expect(daySegments({ ...DAY, continuous_start: "08:30" })).toBeNull();
  });
});

describe("currentStep", () => {
  it("takes the clock's step when it agrees with the feed", () => {
    expect(currentStep("CONTINUOUS", null, 3)).toBe(3);
    expect(currentStep("CLOSED", null, 0)).toBe(0);
    expect(currentStep("CLOSED", "CLOSING_AUCTION", 5)).toBe(5);
  });

  it("follows the feed when the clock disagrees", () => {
    expect(currentStep("CLOSING_AUCTION", "CONTINUOUS", 3)).toBe(4);
    expect(currentStep("CLOSED", "CONTINUOUS", 3)).toBe(5);
    expect(currentStep("CLOSED", null, 3)).toBe(0);
  });

  it("puts CLOSED before the open of a day that is not today", () => {
    expect(currentStep("CLOSED", "CLOSING_AUCTION", null)).toBe(0);
  });

  it("lights nothing for a phase it does not know", () => {
    expect(currentStep(null, null, 3)).toBeNull();
    expect(currentStep("UNKNOWN", null, 3)).toBeNull();
  });
});

describe("calendar", () => {
  it("reads the date and time in the exchange's timezone", () => {
    // 23:30 UTC on the 31st is already New Year's Day in Stockholm.
    expect(exchangeNow(Date.parse("2026-12-31T23:30:00Z"), "Europe/Stockholm")).toEqual({
      date: "2027-01-01",
      sec: 30 * 60,
    });
  });

  it("lays out Monday to Sunday with holidays resolved", () => {
    const week = weekOf(WEEK, "2026-12-23");
    expect(week.map((d) => d.date)).toEqual([
      "2026-12-21",
      "2026-12-22",
      "2026-12-23",
      "2026-12-24",
      "2026-12-25",
      "2026-12-26",
      "2026-12-27",
    ]);
    // A Saturday holiday runs on the holidays entry, even though Saturday is closed.
    expect(week[5]!.holiday?.name).toBe("Annandag jul");
    expect(week[5]!.times).toBe(SHORT);
    expect(week[6]!.times).toBeNull();
  });

  it("skips holidays on days that are closed anyway", () => {
    const next = nextHoliday(WEEK, "2026-12-21")!;
    expect(next.date).toBe("2027-01-01");
    expect(next.times).toBe(SHORT);
    expect(nextHoliday(WEEK, "2027-01-02")).toBeNull();
  });

  it("finds the next trading day over a weekend", () => {
    expect(nextTradingDay(WEEK, "2026-12-27")?.date).toBe("2026-12-28");
    expect(nextTradingDay(WEEK, "2026-12-23")?.date).toBe("2026-12-23");
  });
});

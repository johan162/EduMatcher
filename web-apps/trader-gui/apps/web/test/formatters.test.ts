import { afterEach, describe, it, expect } from "vitest";
import { useSessionStore } from "@/store/useSessionStore";
import {
  formatClock,
  formatIsoTime,
  formatNsTimestamp,
  formatSessionDate,
  formatTime,
  formatPrice,
  formatQty,
  formatChangePct,
  formatCountdown,
  shortId,
} from "@/lib/formatters";

describe("formatPrice", () => {
  it("formats with given decimals", () => {
    expect(formatPrice(150.25, 2)).toBe("150.25");
    expect(formatPrice(150.1, 3)).toBe("150.100");
  });

  it("returns — for null", () => {
    expect(formatPrice(null)).toBe("—");
  });
});

describe("formatQty", () => {
  it("formats integers with thousands separator", () => {
    expect(formatQty(1000)).toBe("1,000");
    expect(formatQty(500)).toBe("500");
  });

  it("returns — for null", () => {
    expect(formatQty(null)).toBe("—");
  });
});

describe("formatChangePct", () => {
  it("computes (last - open) / open * 100", () => {
    expect(formatChangePct(151.5, 150)).toBe("+1.00%");
    expect(formatChangePct(148.5, 150)).toBe("-1.00%");
  });

  it("returns — when either value is null or open is 0", () => {
    expect(formatChangePct(null, 150)).toBe("—");
    expect(formatChangePct(150, null)).toBe("—");
    expect(formatChangePct(150, 0)).toBe("—");
  });
});

describe("formatCountdown", () => {
  it("returns MM:SS for under an hour", () => {
    expect(formatCountdown(90_000)).toBe("01:30");
    expect(formatCountdown(0)).toBe("00:00");
  });

  it("returns HH:MM:SS for an hour or more", () => {
    expect(formatCountdown(3_661_000)).toBe("01:01:01");
  });
});

describe("shortId", () => {
  it("truncates to 8 chars", () => {
    expect(shortId("ORD-abcdef123456")).toBe("ORD-abcd");
  });
});

describe("session-timezone clocks", () => {
  afterEach(() => useSessionStore.getState().setTimezone(null));

  // 2026-07-30T09:30:02.123Z is 11:30:02.123 in Stockholm (CEST).
  const iso = "2026-07-30T09:30:02.123Z";

  it("renders in the exchange's timezone, not UTC or the browser's", () => {
    useSessionStore.getState().setTimezone("Europe/Stockholm");
    expect(formatClock(new Date(iso))).toBe("11:30:02");
    expect(formatIsoTime(iso)).toBe("11:30:02.123");
    expect(formatTime(Date.parse(iso) / 1000)).toBe("11:30:02");
    expect(formatSessionDate(new Date(iso))).toBe("2026-07-30");
    expect(formatNsTimestamp(Date.parse(iso) * 1e6)).toBe("2026-07-30 11:30:02");
  });

  it("takes the date from the session timezone too", () => {
    useSessionStore.getState().setTimezone("Asia/Tokyo");
    expect(formatSessionDate(new Date("2026-07-30T20:00:00Z"))).toBe("2026-07-31");
  });

  it("does not throw on an unknown timezone name", () => {
    useSessionStore.getState().setTimezone("Not/AZone");
    expect(formatClock(new Date(iso))).toMatch(/^\d\d:\d\d:\d\d$/);
  });
});

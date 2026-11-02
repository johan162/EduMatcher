import { describe, expect, it } from "vitest";
import { TickMarkType } from "lightweight-charts";
import { sessionDay, timeFormatters } from "@/lib/chartTime.js";

// 2026-11-02T08:30:00Z — 09:30 in Europe/Stockholm (CET), 03:30 in New York.
const T = Date.UTC(2026, 10, 2, 8, 30) / 1000;

describe("chartTime", () => {
  it("labels ticks in the session timezone, not UTC", () => {
    const { tick } = timeFormatters("Europe/Stockholm");
    expect(tick(T as never, TickMarkType.Time)).toBe("09:30");
    expect(timeFormatters("America/New_York").tick(T as never, TickMarkType.Time)).toBe("03:30");
    expect(timeFormatters("UTC").tick(T as never, TickMarkType.Time)).toBe("08:30");
  });

  it("formats the crosshair with date and time", () => {
    expect(timeFormatters("Europe/Stockholm").crosshair(T as never)).toBe("02/11/2026 09:30");
  });

  it("leaves daily (string) times to the library", () => {
    expect(timeFormatters("UTC").tick("2026-11-02" as never, TickMarkType.Time)).toBeNull();
  });

  it("resolves the trading day in the session timezone", () => {
    const late = Date.UTC(2026, 10, 2, 23, 30) / 1000; // next day in Stockholm
    expect(sessionDay(late, "UTC")).toBe("2026-11-02");
    expect(sessionDay(late, "Europe/Stockholm")).toBe("2026-11-03");
  });
});

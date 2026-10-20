/** Displayed times are on the session clock (lib/time.ts, I106). */

import { describe, expect, it } from "vitest";
import { formatDate, formatDateTime, formatTime } from "../src/lib/time.js";

describe("session clock", () => {
  const t = Date.parse("2026-10-19T08:00:05Z");

  it("shows an instant in the session timezone, whatever the browser's", () => {
    expect(formatTime(t, "Europe/Stockholm")).toBe("10:00:05");
    expect(formatTime(t, "Asia/Kolkata")).toBe("13:30:05");
    expect(formatTime(t, "America/New_York")).toBe("04:00:05");
    expect(formatTime(t, "UTC", false)).toBe("08:00");
    expect(formatDateTime("2026-10-19T08:00:05.000Z", "Europe/Stockholm")).toBe("2026-10-19 10:00:05");
  });

  it("the session date can differ from the UTC date", () => {
    const late = Date.parse("2026-10-19T23:30:00Z");
    expect(formatDate(late, "UTC")).toBe("2026-10-19");
    expect(formatDate(late, "Europe/Stockholm")).toBe("2026-10-20");
    expect(formatDate(late, "America/New_York")).toBe("2026-10-19");
  });

  it("follows daylight saving: Stockholm goes from 03:00 CEST back to 02:00 CET", () => {
    expect(formatTime(Date.parse("2026-10-25T00:59:59Z"), "Europe/Stockholm")).toBe("02:59:59");
    expect(formatTime(Date.parse("2026-10-25T01:00:00Z"), "Europe/Stockholm")).toBe("02:00:00");
  });

  it("midnight is 00, not 24", () => {
    expect(formatTime(Date.parse("2026-10-19T22:00:00Z"), "Europe/Stockholm")).toBe("00:00:00");
  });

  it("a zone the browser does not know shows UTC rather than breaking the page", () => {
    expect(formatTime(t, "Not/AZone")).toBe("08:00:05");
  });
});

describe("no other file formats time on its own", () => {
  // Read through import.meta.glob, as tailwind-tokens.test.ts does: no Node types here.
  const sources = Object.entries(
    import.meta.glob("../src/**/*.{ts,tsx}", { eager: true, query: "?raw", import: "default" }) as Record<string, string>,
  ).filter(([path]) => !path.endsWith("/lib/time.ts"));
  // Browser-local getters and formatting: all would show the browser's zone.
  const forbidden =
    /\.(toLocaleString|toLocaleTimeString|toLocaleDateString|toTimeString|toDateString|getHours|getMinutes|getSeconds|getDate|getDay|getMonth|getFullYear|getTimezoneOffset)\(|Intl\.DateTimeFormat/;

  it("sees the sources", () => {
    expect(sources.length).toBeGreaterThan(5);
  });

  it.each(sources)("%s", (_path, text) => {
    expect(text).not.toMatch(forbidden);
  });
});

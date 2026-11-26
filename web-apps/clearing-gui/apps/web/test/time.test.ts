import { describe, expect, it } from "vitest";
import { formatIso, formatNs } from "@/lib/time";

/** CG19: every time on the venue's session clock, with its date and zone. */

const ns = (iso: string) => Date.parse(iso) * 1_000_000;

describe("formatNs", () => {
  it("shows winter and summer time in the session zone, with the zone's abbreviation", () => {
    expect(formatNs(ns("2026-01-15T08:00:01Z"), "Europe/Stockholm")).toBe("2026-01-15 09:00:01 CET");
    expect(formatNs(ns("2026-07-15T08:00:01Z"), "Europe/Stockholm")).toBe("2026-07-15 10:00:01 CEST");
  });

  it("gives the session date, not the UTC date, across midnight", () => {
    expect(formatNs(ns("2026-07-01T23:30:00Z"), "Europe/Stockholm")).toBe("2026-07-02 01:30:00 CEST");
    expect(formatNs(ns("2026-07-02T05:00:00Z"), "Pacific/Honolulu")).toBe("2026-07-01 19:00:00 HST");
  });

  it("names a zone by its common abbreviation where one exists, else by its offset", () => {
    expect(formatNs(ns("2026-07-15T12:00:00Z"), "America/New_York")).toBe("2026-07-15 08:00:00 EDT");
    expect(formatNs(ns("2026-07-15T12:00:00Z"), "Asia/Tokyo")).toBe("2026-07-15 21:00:00 GMT+9");
    expect(formatNs(ns("2026-07-15T12:00:00Z"), "UTC")).toBe("2026-07-15 12:00:00 UTC");
  });

  it("falls back to labelled UTC without a zone, or with one the browser does not know", () => {
    expect(formatNs(ns("2026-07-15T12:00:00Z"), null)).toBe("2026-07-15 12:00:00 UTC");
    expect(formatNs(ns("2026-07-15T12:00:00Z"), "Not/AZone")).toBe("2026-07-15 12:00:00 UTC");
  });

  it("shows a dash for a missing time", () => {
    expect(formatNs(null, "Europe/Stockholm")).toBe("—");
    expect(formatNs(undefined, null)).toBe("—");
  });
});

describe("formatIso", () => {
  it("formats an ISO-8601 instant like an ns time", () => {
    expect(formatIso("2026-08-28T15:35:02+00:00", "Europe/Stockholm")).toBe("2026-08-28 17:35:02 CEST");
    expect(formatIso("2026-08-28T15:35:02Z", null)).toBe("2026-08-28 15:35:02 UTC");
  });

  it("shows a dash for text that is not an instant", () => {
    expect(formatIso("not a time", "Europe/Stockholm")).toBe("—");
  });
});

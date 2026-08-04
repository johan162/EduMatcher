import { describe, expect, it } from "vitest";
import { isValidWindow, windowToIsoFrom } from "../src/window.js";

describe("windowToIsoFrom", () => {
  it("subtracts the correct number of seconds for each allow-listed window", () => {
    const now = new Date("2026-07-29T12:00:00.000Z");
    expect(windowToIsoFrom("1h", now)).toBe("2026-07-29T11:00:00Z");
    expect(windowToIsoFrom("24h", now)).toBe("2026-07-28T12:00:00Z");
  });

  it("falls back to 1h for an unknown window", () => {
    const now = new Date("2026-07-29T12:00:00.000Z");
    expect(windowToIsoFrom("bogus", now)).toBe(windowToIsoFrom("1h", now));
  });
});

describe("isValidWindow", () => {
  it("accepts the documented windows and rejects everything else", () => {
    expect(isValidWindow("1h")).toBe(true);
    expect(isValidWindow("24h")).toBe(true);
    expect(isValidWindow("3d")).toBe(false);
  });

  it("rejects inherited Object.prototype keys", () => {
    // `window` comes straight from the /api/stats/* query string. With `in`
    // these were "valid", the lookup returned a function, and
    // new Date(NaN).toISOString() threw RangeError — an unauthenticated 500.
    for (const key of ["toString", "constructor", "__proto__", "valueOf", "hasOwnProperty"]) {
      expect(isValidWindow(key)).toBe(false);
    }
  });
});

describe("windowToIsoFrom hardening", () => {
  it("falls back rather than throwing on a prototype key", () => {
    const now = new Date("2026-07-29T12:00:00.000Z");
    for (const key of ["toString", "constructor", "__proto__", "valueOf"]) {
      expect(() => windowToIsoFrom(key, now)).not.toThrow();
      expect(windowToIsoFrom(key, now)).toBe(windowToIsoFrom("1h", now));
    }
  });

  it("covers every allow-listed window", () => {
    const now = new Date("2026-07-29T12:00:00.000Z");
    expect(windowToIsoFrom("5m", now)).toBe("2026-07-29T11:55:00Z");
    expect(windowToIsoFrom("15m", now)).toBe("2026-07-29T11:45:00Z");
    expect(windowToIsoFrom("6h", now)).toBe("2026-07-29T06:00:00Z");
  });
});

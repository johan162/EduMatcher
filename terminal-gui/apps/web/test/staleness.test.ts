import { describe, expect, it } from "vitest";
import { STALE_AFTER_SEC, isStale } from "../src/lib/staleness.js";

const now = Date.parse("2026-07-30T12:00:00Z");
const agoSec = (seconds: number) => new Date(now - seconds * 1000).toISOString();

describe("isStale", () => {
  it("leaves a recent print alone", () => {
    expect(isStale(agoSec(30), now)).toBe(false);
  });

  it("flags a print older than the threshold", () => {
    expect(isStale(agoSec(STALE_AFTER_SEC + 1), now)).toBe(true);
  });

  it("does not flag one exactly on the threshold", () => {
    expect(isStale(agoSec(STALE_AFTER_SEC), now)).toBe(false);
  });

  it("treats a symbol that has never printed as untraded, not stale", () => {
    // The empty price and change columns already say it has not traded.
    // Calling it stale would imply it once had a fresh price that has aged.
    expect(isStale(undefined, now)).toBe(false);
  });

  it("does not flag a timestamp it cannot read", () => {
    expect(isStale("not a date", now)).toBe(false);
  });
});

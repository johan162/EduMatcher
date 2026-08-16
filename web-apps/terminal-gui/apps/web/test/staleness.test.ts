import { describe, expect, it } from "vitest";
import { STALE_AFTER_SEC, isStale, staleLabel } from "../src/lib/staleness.js";

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

describe("configurable threshold (T-L3)", () => {
  const printed = "2026-07-30T12:00:00.000Z";
  const at = (seconds: number) => Date.parse(printed) + seconds * 1000;

  it("honours a threshold tighter than the default", () => {
    // A busy desk wants the mark to discriminate again.
    expect(isStale(printed, at(90), 60)).toBe(true);
    expect(isStale(printed, at(30), 60)).toBe(false);
  });

  it("honours one wider than the default", () => {
    // A thin classroom book, where five minutes would fade every row
    // permanently — and a mark that is always on marks nothing.
    expect(isStale(printed, at(600), 3600)).toBe(false);
    expect(isStale(printed, at(4000), 3600)).toBe(true);
  });

  it("turns the marking off entirely at Infinity", () => {
    expect(isStale(printed, at(86_400), Infinity)).toBe(false);
  });

  it("still defaults to five minutes when no threshold is given", () => {
    expect(isStale(printed, at(301))).toBe(true);
    expect(isStale(printed, at(299))).toBe(false);
  });
});

describe("staleLabel", () => {
  it("states the threshold in the units a reader thinks in", () => {
    // The number has to be on screen: a faded row is only readable if the
    // reader knows what faded means here.
    expect(staleLabel(30)).toBe("30s");
    expect(staleLabel(300)).toBe("5 min");
    expect(staleLabel(3600)).toBe("1 h");
  });

  it("says off rather than naming an infinite duration", () => {
    expect(staleLabel(Infinity)).toBe("off");
  });
});

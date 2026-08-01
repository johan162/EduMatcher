import { describe, expect, it } from "vitest";
import { PRESETS, timeframeSpec } from "../src/lib/timeframe.js";

const NOW = Date.parse("2026-07-30T12:00:00Z");

describe("granularity follows the window", () => {
  it("buckets trades by the minute for one day", () => {
    expect(timeframeSpec("1D", NOW)).toMatchObject({ source: "trades", bucketSec: 60 });
  });

  it("widens to five-minute buckets over five days", () => {
    expect(timeframeSpec("5D", NOW)).toMatchObject({ source: "trades", bucketSec: 300 });
  });

  it.each(["1M", "3M", "YTD", "All"] as const)("reads the daily rollup for %s", (preset) => {
    // Ninety days of one-minute bars would be unreadable and an enormous
    // download; pm-stats already computed these.
    const spec = timeframeSpec(preset, NOW);
    expect(spec.source).toBe("daily");
    expect(spec.bucketSec).toBeUndefined();
  });
});

describe("windows", () => {
  it("asks trades for an ISO timestamp bound", () => {
    expect(timeframeSpec("1D", NOW).from).toBe("2026-07-30T00:00:00.000Z");
  });

  it("starts 1D at today's open, not twenty-four hours back (T-H2)", () => {
    // SymbolDetail draws today's VWAP across this window as a horizontal
    // reference line, and a price line spans the whole chart — so a rolling
    // window would put a benchmark for today over most of yesterday's session
    // every morning. The window is what has to be honest.
    const lateInTheDay = Date.parse("2026-07-30T23:59:00Z");
    const earlyInTheDay = Date.parse("2026-07-30T00:30:00Z");
    expect(timeframeSpec("1D", lateInTheDay).from).toBe("2026-07-30T00:00:00.000Z");
    expect(timeframeSpec("1D", earlyInTheDay).from).toBe("2026-07-30T00:00:00.000Z");
  });

  it("keeps 5D rolling, since it spans sessions by design", () => {
    expect(timeframeSpec("5D", NOW).from).toBe("2026-07-25T12:00:00.000Z");
  });

  it("asks daily for a plain date bound, which is what that endpoint takes", () => {
    expect(timeframeSpec("1M", NOW).from).toBe("2026-06-30");
  });

  it("starts YTD at the first of January, not thirty days back", () => {
    expect(timeframeSpec("YTD", NOW).from).toBe("2026-01-01");
  });

  it("leaves All unbounded, so the endpoint returns everything retained", () => {
    expect(timeframeSpec("All", NOW).from).toBeUndefined();
  });

  it("reaches back three months for 3M", () => {
    expect(timeframeSpec("3M", NOW).from).toBe("2026-05-01");
  });
});

describe("Live", () => {
  it("pins the right edge", () => {
    expect(timeframeSpec("Live", NOW).follow).toBe(true);
  });

  it("shows the same window as 1D, since live describes tracking not span", () => {
    const live = timeframeSpec("Live", NOW);
    const oneDay = timeframeSpec("1D", NOW);
    expect(live.from).toBe(oneDay.from);
    expect(live.bucketSec).toBe(oneDay.bucketSec);
  });

  it("is the only preset that follows", () => {
    const following = PRESETS.filter((p) => timeframeSpec(p, NOW).follow);
    expect(following).toEqual(["Live"]);
  });
});

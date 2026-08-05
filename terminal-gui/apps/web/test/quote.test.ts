import { describe, expect, it } from "vitest";
import { avgTradeSize, rangePosition, spread, spreadBps, turnover } from "../src/lib/quote.js";

describe("spread", () => {
  it("is the distance between the two touch prices", () => {
    expect(spread(151.4, 151.6)).toBeCloseTo(0.2, 6);
  });

  it("goes negative on a crossed book rather than clamping", () => {
    // A crossed market is real, and it is the one state a viewer most needs
    // to see. Clamping to zero would hide it.
    expect(spread(151.6, 151.4)).toBeCloseTo(-0.2, 6);
  });

  it("is absent when a side has been withdrawn", () => {
    expect(spread(undefined, 151.6)).toBeUndefined();
    expect(spread(151.4, null)).toBeUndefined();
  });
});

describe("spreadBps", () => {
  it("expresses the spread against the midpoint", () => {
    // 0.20 on a 151.50 mid.
    expect(spreadBps(151.4, 151.6)).toBeCloseTo(13.2013, 3);
  });

  it("makes two price levels comparable", () => {
    // A penny is four times as wide on 5.00 as 0.04 is on 80.00, and the
    // absolute figures alone say the opposite.
    expect(spreadBps(4.995, 5.005)).toBeGreaterThan(spreadBps(79.98, 80.02) ?? 0);
  });

  it("is absent when the midpoint is not positive", () => {
    expect(spreadBps(-1, 1)).toBeUndefined();
  });
});

describe("turnover", () => {
  it("is shares times the session VWAP", () => {
    expect(turnover(1000, 150)).toBe(150_000);
  });

  it("is zero for a symbol that has not traded, not unknown", () => {
    // pm-stats leaves VWAP null until the first print.
    expect(turnover(0, null)).toBe(0);
  });

  it("is absent when the volume is unknown", () => {
    expect(turnover(null, 150)).toBeUndefined();
  });
});

describe("avgTradeSize", () => {
  it("is the mean shares per print", () => {
    expect(avgTradeSize(1000, 8)).toBe(125);
  });

  it("is absent rather than dividing by a zero trade count", () => {
    expect(avgTradeSize(0, 0)).toBeUndefined();
  });
});

describe("rangePosition", () => {
  it("places the last price between the session low and high", () => {
    expect(rangePosition(100, 200, 150)).toBeCloseTo(0.5, 6);
    expect(rangePosition(100, 200, 175)).toBeCloseTo(0.75, 6);
  });

  it("clamps a live tick that has outrun the recorded range", () => {
    // The rollup is recomputed on every trade, so `last` briefly sits outside
    // the high/low it will shortly become part of.
    expect(rangePosition(100, 200, 250)).toBe(1);
    expect(rangePosition(100, 200, 50)).toBe(0);
  });

  it("centres a range with no width", () => {
    expect(rangePosition(100, 100, 100)).toBe(0.5);
  });

  it("is absent when the session has no range yet", () => {
    expect(rangePosition(null, null, 150)).toBeUndefined();
  });
});

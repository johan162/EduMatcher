import { describe, expect, it } from "vitest";
import type { DepthFrame, DepthLevel } from "@edumatcher/terminal-types";
import { buildLadder } from "../src/lib/depth.js";

const frame = (bids: DepthLevel[], asks: DepthLevel[]): DepthFrame => ({
  type: "depth",
  sym: "AAPL",
  seq: 1,
  ts: "2026-07-30T10:00:00Z",
  levels: Math.max(bids.length, asks.length),
  bids,
  asks,
});

describe("buildLadder", () => {
  it("accumulates each side outward from the touch", () => {
    const ladder = buildLadder(
      frame(
        [
          [151.4, 100, 2],
          [151.3, 300, 4],
          [151.2, 600, 5],
        ],
        [[151.6, 250, 3]],
      ),
    );

    expect(ladder?.bids.map((r) => r.cumulative)).toEqual([100, 400, 1000]);
    expect(ladder?.asks.map((r) => r.cumulative)).toEqual([250]);
  });

  it("reports each side's total resting size", () => {
    const ladder = buildLadder(
      frame(
        [
          [151.4, 100, 1],
          [151.3, 300, 1],
        ],
        [[151.6, 250, 1]],
      ),
    );

    expect(ladder?.bidTotal).toBe(400);
    expect(ladder?.askTotal).toBe(250);
  });

  it("expresses the imbalance as the bid's share of resting size", () => {
    const ladder = buildLadder(frame([[151.4, 750, 1]], [[151.6, 250, 1]]));
    expect(ladder?.imbalance).toBeCloseTo(0.75, 6);
  });

  it("leaves the imbalance absent on an empty book rather than reporting balance", () => {
    // Nothing resting either side is a different state from evenly matched,
    // and 0.5 would claim a symmetry that does not exist.
    expect(buildLadder(frame([], []))?.imbalance).toBeUndefined();
  });

  it("scales both sides against the deeper one", () => {
    // Independent per-side scaling would draw a thin book as deep as a heavy
    // one sitting opposite it.
    const ladder = buildLadder(frame([[151.4, 900, 1]], [[151.6, 100, 1]]));
    expect(ladder?.peakCumulative).toBe(900);
  });

  it("renders as many rows as the deeper side has levels", () => {
    const ladder = buildLadder(
      frame(
        [
          [151.4, 100, 1],
          [151.3, 100, 1],
        ],
        [[151.6, 100, 1]],
      ),
    );

    expect(ladder?.depth).toBe(2);
  });

  it("has nothing to build before the first snapshot", () => {
    expect(buildLadder(null)).toBeNull();
  });
});

describe("price distance from the touch (T-L1)", () => {
  it("measures each level against its own side's touch", () => {
    // Evenly spaced rows cannot say how far apart the prices are. The
    // cumulative column says how much size is behind the touch; this says
    // how far away it sits, which is the other half of the same question.
    const ladder = buildLadder({
      type: "depth",
      sym: "AAPL",
      seq: 1,
      ts: "t",
      levels: 3,
      bids: [
        [100, 10, 1],
        [99, 10, 1],
        [50, 10, 1],
      ],
      asks: [],
    });

    expect(ladder?.bids[0]?.distance).toBe(0);
    expect(ladder?.bids[1]?.distance).toBeCloseTo(0.01);
    expect(ladder?.bids[2]?.distance).toBeCloseTo(0.5);
  });

  it("separates a tight ladder from a scattered one, which even spacing cannot", () => {
    const tight = buildLadder({
      type: "depth",
      sym: "AAPL",
      seq: 1,
      ts: "t",
      levels: 3,
      bids: [
        [100, 10, 1],
        [99.99, 10, 1],
        [99.98, 10, 1],
      ],
      asks: [],
    });
    const scattered = buildLadder({
      type: "depth",
      sym: "AAPL",
      seq: 1,
      ts: "t",
      levels: 3,
      bids: [
        [100, 10, 1],
        [99, 10, 1],
        [50, 10, 1],
      ],
      asks: [],
    });

    // These two render as identical grids today; only the distance tells
    // them apart.
    expect(tight?.peakDistance).toBeLessThan(0.001);
    expect(scattered?.peakDistance).toBeCloseTo(0.5);
  });

  it("is unsigned, so the two sides are comparable rather than mirrored", () => {
    const ladder = buildLadder({
      type: "depth",
      sym: "AAPL",
      seq: 1,
      ts: "t",
      levels: 2,
      bids: [
        [100, 10, 1],
        [99, 10, 1],
      ],
      asks: [
        [101, 10, 1],
        [102, 10, 1],
      ],
    });

    expect(ladder?.bids[1]?.distance).toBeCloseTo(0.01);
    expect(ladder?.asks[1]?.distance).toBeCloseTo(0.0099, 3);
  });

  it("omits the distance when the touch price is not a usable reference", () => {
    // A proportion of zero says nothing, so it says nothing rather than
    // dividing by it.
    const ladder = buildLadder({
      type: "depth",
      sym: "AAPL",
      seq: 1,
      ts: "t",
      levels: 1,
      bids: [
        [0, 10, 1],
        [0, 10, 1],
      ],
      asks: [],
    });

    expect(ladder?.bids[0]?.distance).toBeUndefined();
    expect(ladder?.peakDistance).toBe(0);
  });

  it("reports no peak distance for an empty book rather than -Infinity", () => {
    const ladder = buildLadder({
      type: "depth",
      sym: "AAPL",
      seq: 1,
      ts: "t",
      levels: 0,
      bids: [],
      asks: [],
    });

    expect(ladder?.peakDistance).toBe(0);
  });
});

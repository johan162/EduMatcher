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

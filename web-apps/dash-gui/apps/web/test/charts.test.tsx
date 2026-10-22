// @vitest-environment jsdom
/**
 * TimeSeries (D2.3), RateBars and top-N (D2.4). Recharts gets a fixed width:
 * jsdom has no layout, so a responsive container would measure zero.
 */

import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { Point } from "@edumatcher/dash-types";
import { bucketGrid, RateBars, rateRows } from "../src/components/widgets/RateBars.js";
import { mergeSeries, seriesStyle, thresholdBands, TimeSeries, yDomain } from "../src/components/widgets/TimeSeries.js";
import { formatCount } from "../src/lib/format.js";
import { OTHER, topN, topNSeries } from "../src/lib/topn.js";
import { useCrosshair } from "../src/store/useCrosshair.js";

const T0 = Date.parse("2026-10-19T08:00:00Z");
const MIN = 60_000;
const RANGE = { fromMs: T0, toMs: T0 + 60 * MIN };
const line = (base: number): Point[] => Array.from({ length: 60 }, (_, i) => [T0 + i * MIN, base + (i % 5)]);

beforeEach(() => useCrosshair.setState({ ts: null }));
afterEach(cleanup);

describe("TimeSeries", () => {
  it("draws a line per series and no event markers", () => {
    render(<TimeSeries label="CPU" series={[{ label: "pm-engine", points: line(30) }]} range={RANGE} tz="UTC" format={String} width={600} />);
    expect(document.querySelectorAll(".recharts-line")).toHaveLength(1);
    expect(document.querySelectorAll(".recharts-reference-line")).toHaveLength(0);
  });

  it("labels the time axis on the session clock, not the browser's", () => {
    // 08:00Z is 13:30 in Kolkata: its ticks are on the half hour in UTC terms.
    render(<TimeSeries label="CPU" series={[{ label: "a", points: line(1) }]} range={RANGE} tz="Asia/Kolkata" format={String} width={600} />);
    const ticks = [...document.querySelectorAll(".recharts-xAxis .recharts-cartesian-axis-tick-value")].map((t) => t.textContent);
    expect(ticks[0]).toBe("13:30");
    expect(ticks.at(-1)).toBe("14:30");
  });

  it("the crosshair is shared: hovering one chart draws the line on every chart", () => {
    render(
      <>
        <TimeSeries label="A" series={[{ label: "a", points: line(1) }]} range={RANGE} tz="UTC" format={String} width={600} />
        <TimeSeries label="B" series={[{ label: "b", points: line(2) }]} range={RANGE} tz="UTC" format={String} width={600} />
      </>,
    );
    expect(screen.queryAllByTestId("crosshair")).toHaveLength(0);
    act(() => useCrosshair.getState().setTs(T0 + 30 * MIN));
    const lines = screen.getAllByTestId("crosshair");
    expect(lines).toHaveLength(2);
    // Halfway through the range: halfway across the plot, past the y axis.
    expect(lines[0]!.style.left.replace(/\s/g, "")).toMatch(/^calc\(68px\+0\.5\*\(100%-76px\)\)$/);
    act(() => useCrosshair.getState().setTs(T0 - MIN)); // outside the range: no line
    expect(screen.queryAllByTestId("crosshair")).toHaveLength(0);
  });

  it("stacks areas, and names every series in its legend", () => {
    render(
      <TimeSeries label="Memory" stacked series={[{ label: "pm-engine", points: line(10) }, { label: "pm-stats", points: line(5) }]} range={RANGE} tz="UTC" format={String} width={600} />,
    );
    expect(document.querySelectorAll(".recharts-area")).toHaveLength(2);
    expect(screen.getByRole("figure", { name: "Memory" }).textContent).toContain("pm-stats");
  });

  it("merges series into one row per timestamp", () => {
    expect(mergeSeries([{ label: "a", points: [[1, 10], [2, 20]] }, { label: "b", points: [[2, 5], [3, 6]] }])).toEqual([
      { ts: 1, s0: 10 },
      { ts: 2, s0: 20, s1: 5 },
      { ts: 3, s1: 6 },
    ]);
  });

  it("threshold bands tint warn..crit and above crit, or below for an inverted rule", () => {
    expect(thresholdBands({ warn: 80, crit: 95 }, 0, 110)).toEqual([
      { y1: 80, y2: 95, color: "var(--warn)" },
      { y1: 95, y2: 110, color: "var(--crit)" },
    ]);
    expect(thresholdBands({ warn: 20, crit: 10, invert: true }, 0, 100)).toEqual([
      { y1: 0, y2: 10, color: "var(--crit)" },
      { y1: 10, y2: 20, color: "var(--warn)" },
    ]);
    render(<TimeSeries label="CPU" series={[{ label: "a", points: line(50) }]} range={RANGE} tz="UTC" format={String} thresholds={{ warn: 80, crit: 95 }} width={600} />);
    expect(document.querySelectorAll(".recharts-reference-area")).toHaveLength(2);
  });
});

describe("top N + other", () => {
  const items = [5, 50, 7, 30, 1, 12].map((value, i) => ({ label: `P${i}`, value }));

  it("keeps the N largest and sums the rest into other, which adds up to the total", () => {
    const out = topN(items, 3, (value, count) => ({ label: `${OTHER} (${count})`, value }));
    expect(out.map((i) => i.label)).toEqual(["P1", "P3", "P5", "other (3)"]);
    expect(out.at(-1)!.value).toBe(13);
    expect(out.reduce((s, i) => s + i.value, 0)).toBe(items.reduce((s, i) => s + i.value, 0));
  });

  it("no other when everything fits", () => {
    expect(topN(items, 6, () => ({ label: OTHER, value: 0 })).map((i) => i.label)).not.toContain(OTHER);
  });

  it("per bucket, the series' other is the rest's sum, so each bucket adds up", () => {
    const series = Array.from({ length: 11 }, (_, i) => ({
      label: `T${String(i).padStart(2, "0")}`,
      points: [0, 1, 2].map((b): [number, number] => [T0 + b * MIN, (i + 1) * (b + 1)]),
    }));
    const out = topNSeries(series, 8);
    expect(out).toHaveLength(9);
    expect(out[0]!.label).toBe("T10"); // the largest total first
    expect(out.at(-1)!.label).toBe(OTHER);
    for (const b of [0, 1, 2]) {
      const ts = T0 + b * MIN;
      const shown = out.reduce((s, x) => s + (x.points.find(([t]) => t === ts)?.[1] ?? 0), 0);
      const all = series.reduce((s, x) => s + x.points.find(([t]) => t === ts)![1], 0);
      expect(shown).toBe(all);
    }
  });

  it("RateBars stacks the top 8 and other, and names them", () => {
    const series = Array.from({ length: 10 }, (_, i) => ({ label: `P${i}`, points: line(i + 1) }));
    render(<RateBars label="Orders / min" series={series} range={RANGE} bucketMs={MIN} tz="UTC" format={formatCount} width={600} />);
    expect(document.querySelectorAll(".recharts-bar")).toHaveLength(9);
    const legend = screen.getByRole("figure", { name: "Orders / min" }).querySelector("figcaption")!.textContent;
    expect(legend).toContain("P9");
    expect(legend).toContain(OTHER);
    expect(legend).not.toContain("P0"); // the smallest two are in other
  });
});

describe("data edge cases (review)", () => {
  it("a stacked chart counts a series' missing bucket as 0, so the stack above stays whole", () => {
    const rows = mergeSeries([{ label: "late", points: [[2, 5]] }, { label: "always", points: [[1, 1], [2, 1]] }], true);
    expect(rows).toEqual([
      { ts: 1, s0: 0, s1: 1 },
      { ts: 2, s0: 5, s1: 1 },
    ]);
    // Lines keep the gap: a line breaks where its series has nothing.
    expect(mergeSeries([{ label: "late", points: [[2, 5]] }, { label: "always", points: [[1, 1]] }])[0]).toEqual({ ts: 1, s1: 1 });
  });

  it("a point that is not a number is left out, not drawn at NaN", () => {
    expect(mergeSeries([{ label: "a", points: [[1, Number.NaN], [2, 3], [Number.NaN, 4]] }])).toEqual([{ ts: 1 }, { ts: 2, s0: 3 }]);
  });

  it("past eight series the colours repeat in a new dash, so no colour stands for two series alone", () => {
    expect(seriesStyle(0)).toEqual({ color: "var(--series-1)", dash: undefined });
    expect(seriesStyle(8)).toEqual({ color: "var(--series-1)", dash: "6 3" });
    expect(seriesStyle(17)).toEqual({ color: "var(--series-2)", dash: "1 3" });
    const twelve = Array.from({ length: 12 }, (_, i) => ({ label: `p${i}`, points: line(i) }));
    render(<TimeSeries label="Twelve" series={twelve} range={RANGE} tz="UTC" format={String} width={600} />);
    const dashed = [...document.querySelectorAll(".recharts-line-curve")].map((p) => p.getAttribute("stroke-dasharray"));
    expect(dashed.filter((d) => d === "6 3")).toHaveLength(4);
  });

  it("the y axis is never empty: all zeros, or thresholds at zero, still span a range", () => {
    expect(yDomain([{ ts: 1, s0: 0 }], 1, false)).toEqual([0, 1]);
    expect(yDomain([], 1, false, { warn: 0 })).toEqual([0, 1]);
    expect(yDomain([{ ts: 1, s0: -5, s1: 3 }], 2, false)).toEqual([-5, 3]);
    expect(yDomain([{ ts: 1, s0: 2, s1: 3 }], 2, true)).toEqual([0, 5]);
  });

  it("says so when there is nothing to draw", () => {
    render(<TimeSeries label="Empty" series={[]} range={RANGE} tz="UTC" format={String} width={600} />);
    expect(screen.getByRole("figure", { name: "Empty" }).textContent).toContain("No data in this range");
  });

  it("rate bars lay every bucket of the range, empty ones at 0, so a quiet stretch is a gap in time", () => {
    const grid = bucketGrid(RANGE, MIN, T0);
    expect(grid).toHaveLength(60);
    expect(grid[0]).toBe(T0);
    const rows = rateRows([{ label: "a", points: [[T0 + 5 * MIN, 7], [T0 + 50 * MIN, 3]] }], RANGE, MIN);
    expect(rows).toHaveLength(60);
    expect(rows.filter((r) => r.s0! > 0).map((r) => [r.ts, r.s0])).toEqual([
      [T0 + 5 * MIN, 7],
      [T0 + 50 * MIN, 3],
    ]);
  });

  it("the grid follows the data's bucket starts (session-clock aligned), not the range's", () => {
    // Range starts 08:00:20; buckets start on the minute: the first is 08:00:00.
    const rows = rateRows([{ label: "a", points: [[T0 + MIN, 1]] }], { fromMs: T0 + 20_000, toMs: T0 + 3 * MIN }, MIN);
    expect(rows.map((r) => r.ts)).toEqual([T0, T0 + MIN, T0 + 2 * MIN]);
  });

  it("a point off the grid is added to its nearest bucket, never dropped", () => {
    const rows = rateRows([{ label: "a", points: [[T0, 1], [T0 + MIN + 2_000, 5]] }], { fromMs: T0, toMs: T0 + 2 * MIN }, MIN);
    expect(rows.map((r) => r.s0)).toEqual([1, 5]);
    expect(bucketGrid(RANGE, 0, T0)).toEqual([]);
    expect(bucketGrid({ fromMs: T0, toMs: T0 + 7 * 24 * 3600_000 }, 1000, T0)).toEqual([]); // too many to lay out
  });

  it("rate bars without data say so", () => {
    render(<RateBars label="Quiet" series={[]} range={RANGE} bucketMs={MIN} tz="UTC" format={formatCount} width={600} />);
    expect(screen.getByRole("figure", { name: "Quiet" }).textContent).toContain("No data in this range");
  });
});

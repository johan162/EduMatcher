// @vitest-environment jsdom
/**
 * TimeSeries (D2.3), RateBars and top-N (D2.4). Recharts gets a fixed width:
 * jsdom has no layout, so a responsive container would measure zero.
 */

import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { Point } from "@edumatcher/dash-types";
import { RateBars } from "../src/components/widgets/RateBars.js";
import { inRange, mergeSeries, thresholdBands, TimeSeries } from "../src/components/widgets/TimeSeries.js";
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
  const annotations = [
    { ts: T0 - MIN, label: "before", color: "var(--crit)" },
    { ts: T0, label: "at the start", color: "var(--crit)" },
    { ts: T0 + 20 * MIN, label: "inside", color: "var(--warn)" },
    { ts: T0 + 60 * MIN, label: "at the end", color: "var(--info)" },
    { ts: T0 + 61 * MIN, label: "after", color: "var(--info)" },
  ];

  it("draws one marker per event in range and none outside it", () => {
    render(<TimeSeries label="CPU" series={[{ label: "pm-engine", points: line(30) }]} range={RANGE} tz="UTC" format={String} annotations={annotations} width={600} />);
    const markers = document.querySelectorAll(".recharts-reference-line.annotation");
    expect(markers).toHaveLength(3);
    expect(inRange(annotations, RANGE).map((a) => a.label)).toEqual(["at the start", "inside", "at the end"]);
    expect(document.querySelectorAll(".recharts-line")).toHaveLength(1);
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
    expect(document.querySelectorAll(".crosshair")).toHaveLength(0);
    act(() => useCrosshair.getState().setTs(T0 + 30 * MIN));
    expect(document.querySelectorAll(".recharts-reference-line.crosshair")).toHaveLength(2);
    act(() => useCrosshair.getState().setTs(T0 - MIN)); // outside the range: no line
    expect(document.querySelectorAll(".crosshair")).toHaveLength(0);
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
    render(<RateBars label="Orders / min" series={series} range={RANGE} tz="UTC" format={formatCount} width={600} />);
    expect(document.querySelectorAll(".recharts-bar")).toHaveLength(9);
    const legend = screen.getByRole("figure", { name: "Orders / min" }).querySelector("figcaption")!.textContent;
    expect(legend).toContain("P9");
    expect(legend).toContain(OTHER);
    expect(legend).not.toContain("P0"); // the smallest two are in other
  });
});

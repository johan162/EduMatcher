/**
 * The Market canvas's ECharts option, built without a canvas: what each
 * series carries and how its marks render, from the contract's examples.
 */
import { describe, expect, it } from "vitest";
import type { HeatmapT, LifelinesT } from "@/api/schemas";
import { buildOption, hatchLines, type CanvasInput } from "@/components/market/chartOption";
import { END_MARKS, MASK_EFFECT } from "@/lib/marks";
import { nsToMs } from "@/lib/ns";
import type { Trade } from "@/lib/flow";
import { example } from "./helpers";

const HEATMAP = "/api/v1/audit/market/{symbol}/heatmap";
const LIFELINES = "/api/v1/audit/market/{symbol}/lifelines";

function input(overrides: Partial<CanvasInput> = {}): CanvasInput {
  const heatmap = example<HeatmapT>(HEATMAP);
  return {
    heatmap,
    lifelines: example<LifelinesT>(LIFELINES),
    trades: [],
    startMs: nsToMs(heatmap.from_ns),
    endMs: nsToMs(heatmap.to_ns),
    selected: null,
    ...overrides,
  };
}

type Series = { id: string; data: unknown[]; renderItem?: (p: unknown, api: unknown) => Graphic };
type Graphic = { type: string; children?: Graphic[]; shape?: Record<string, number>; style?: Record<string, unknown> };

function series(option: ReturnType<typeof buildOption>, id: string): Series {
  const found = (option.series as Series[]).find((s) => s.id === id);
  expect(found, id).toBeDefined();
  return found!;
}

/** A coordinate system mapping data to pixels one to one. */
const api = {
  coord: ([x, y]: [number, number]) => [x, y],
  size: ([dx, dy]: [number, number]) => [dx, dy],
};
const params = (dataIndex: number) => ({ dataIndex, coordSys: { x: 0, y: 0, width: 1e15, height: 1e6 } });

function tooltip(option: ReturnType<typeof buildOption>, seriesId: string, dataIndex: number): string {
  const formatter = (option.tooltip as { formatter: (p: unknown) => string }).formatter;
  return formatter({ seriesId, dataIndex });
}

describe("market canvas option", () => {
  it("draws every heatmap cell, opacity by displayed quantity", () => {
    const i = input();
    const cells = i.heatmap.columns.reduce((n, c) => n + c.bids.length + c.asks.length, 0);
    expect(series(buildOption(i), "cells").data).toHaveLength(cells);
  });

  it("hatches each masked interval and its tooltip gives the reason", () => {
    const i = input();
    i.heatmap.masks.push({
      kind: "gap",
      from_ns: i.heatmap.from_ns,
      to_ns: i.heatmap.columns[0]!.end_ns,
      detail: "engine eseq 120->125 - 4 message(s) missing",
    });
    const option = buildOption(i);
    const masks = series(option, "masks");
    expect(masks.data).toHaveLength(2);
    for (let index = 0; index < 2; index++) {
      const drawn = masks.renderItem!(params(index), api);
      expect(drawn.type).toBe("group");
      expect(drawn.children![0]!.type).toBe("rect");
      expect(drawn.children!.filter((c) => c.type === "line").length).toBeGreaterThan(0);
    }
    const halt = tooltip(option, "masks", 0);
    expect(halt).toContain("Halt");
    expect(halt).toContain("ADMIN_SYMBOL");
    expect(halt).toContain(MASK_EFFECT.halt);
    const gap = tooltip(option, "masks", 1);
    expect(gap).toContain("Records lost (gap)");
    expect(gap).toContain("4 message(s) missing");
    expect(gap).toContain(MASK_EFFECT.gap);
  });

  it("hatch lines stay inside their rectangle", () => {
    for (const [x1, y1, x2, y2] of hatchLines(10, 20, 30, 12, 6)) {
      for (const [x, y] of [
        [x1, y1],
        [x2, y2],
      ] as const) {
        expect(x).toBeGreaterThanOrEqual(10 - 1e-9);
        expect(x).toBeLessThanOrEqual(40 + 1e-9);
        expect(y).toBeGreaterThanOrEqual(20 - 1e-9);
        expect(y).toBeLessThanOrEqual(32 + 1e-9);
      }
    }
  });

  it("draws one bar per lifeline segment and marks each end with its glyph", () => {
    const i = input();
    const option = buildOption(i);
    const life = i.lifelines.lifelines[0]!;
    expect(series(option, "lifelines").data).toHaveLength(life.segments.length);
    const ends = series(option, "ends").data as { label: { formatter: string } }[];
    expect(ends.map((e) => e.label.formatter)).toEqual([END_MARKS[life.end].glyph]);
    expect(tooltip(option, "ends", 0)).toContain("owner cancel");
    expect(tooltip(option, "lifelines", 0)).toContain(life.order_id.slice(0, 8));
  });

  it("buyer- and seller-initiated trades differ in shape, not only in colour", () => {
    const base = { priceTicks: 10000, qty: 10, auction: false, tradeId: "t" };
    const start = input().startMs;
    const trades: Trade[] = [
      { ...base, ms: start + 1, aggressor: "BUY" },
      { ...base, ms: start + 2, aggressor: "SELL" },
      { ...base, ms: start + 3, aggressor: null, auction: true },
    ];
    const data = series(buildOption(input({ trades })), "trades").data as { symbol: string }[];
    expect(new Set(data.map((d) => d.symbol)).size).toBe(3);
  });

  it("every custom series reads its time span from [x0, x1], never y from x1", () => {
    // Without an explicit encode, ECharts reads data[1] (an end time, ~1.8e12)
    // as y, which wrecked the flow strip's axis (found in the browser).
    const custom = (buildOption(input()).series as { type: string; id: string; encode?: { x?: number[]; y?: number } }[])
      .filter((s) => s.type === "custom");
    for (const s of custom) {
      expect(s.encode?.x, s.id).toEqual([0, 1]);
      expect(s.encode?.y, s.id).not.toBe(1);
    }
    expect(custom.map((s) => s.id).sort()).toEqual(["cells", "flow", "lifelines", "masks", "phases"]);
  });

  it("a selected lifeline is drawn thicker than the others", () => {
    const i = input();
    const id = i.lifelines.lifelines[0]!.order_id;
    const plain = series(buildOption(i), "lifelines").renderItem!(params(0), api);
    const chosen = series(buildOption({ ...i, selected: id }), "lifelines").renderItem!(params(0), api);
    expect(Number(chosen.style!["lineWidth"] ?? 0)).toBeGreaterThan(Number(plain.style!["lineWidth"] ?? 0));
  });
});

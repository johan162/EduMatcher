/**
 * The Market canvas as an ECharts option (design §9.4), built from the API's
 * read models without touching a canvas, so every mark can be tested.
 *
 * Three stacked grids share one time axis (receipt clock, milliseconds):
 *
 * - phases: the session-phase band (null phase: "unknown");
 * - main: depth heatmap cells (bid and ask hues, opacity by displayed
 *   quantity), hatched masks (gap: no cells; halt: the observed book kept),
 *   order lifelines (thickness by displayed quantity, dashed while a stop is
 *   held), end-reason glyphs, and trades (shape by aggressor, diamond for an
 *   auction print);
 * - flow: signed aggressive volume per heatmap bin (up: buyer-initiated,
 *   down: seller-initiated).
 *
 * Only types are imported from ECharts: the library itself is loaded on
 * demand by EChart.tsx.
 */
import type { EChartsOption } from "echarts";
import type { HeatmapT, LifelineT, LifelinesT } from "@/api/schemas";
import { flowBins, type Trade } from "@/lib/flow";
import { END_MARKS, MASK_EFFECT, MASK_LABEL, SIDE_COLOR, endText } from "@/lib/marks";
import { clockText, nsToMs, priceText } from "@/lib/ns";

export interface CanvasInput {
  heatmap: HeatmapT;
  lifelines: LifelinesT;
  trades: Trade[];
  startMs: number;
  endMs: number;
  /** The order whose drawer is open, drawn thicker. */
  selected: string | null;
}

interface Api {
  coord: (point: [number, number]) => number[];
}
interface Params {
  dataIndex: number;
  coordSys: { x: number; y: number; width: number; height: number };
}
interface Graphic {
  type: string;
  shape?: Record<string, number>;
  style?: Record<string, unknown>;
  children?: Graphic[];
  silent?: boolean;
}

const GRID = { left: 70, right: 16 };
const HATCH_STEP = 7;

/** Diagonal hatch segments clipped to the rectangle (x, y, w, h). */
export function hatchLines(x: number, y: number, w: number, h: number, step = HATCH_STEP): [number, number, number, number][] {
  const lines: [number, number, number, number][] = [];
  // Lines x' - y' = c (going down-right), for c across the box.
  for (let c = -h; c < w; c += step) {
    const x1 = Math.max(c, 0);
    const y1 = x1 - c;
    const x2 = Math.min(c + h, w);
    const y2 = x2 - c;
    if (x2 > x1) lines.push([x + x1, y + y1, x + x2, y + y2]);
  }
  return lines;
}

interface Layout {
  cells: { x0: number; x1: number; price: number; opacity: number; side: "BUY" | "SELL" }[];
  masks: HeatmapT["masks"];
  segments: { x0: number; x1: number; price: number; displayed: number; stop: boolean; life: number }[];
  ends: { x: number; price: number; life: number }[];
  maxDisplayed: number;
}

function layout(input: CanvasInput): Layout {
  const { heatmap, lifelines } = input;
  let maxQty = 0;
  for (const c of heatmap.columns) for (const [, q] of [...c.bids, ...c.asks]) maxQty = Math.max(maxQty, q);
  const cells: Layout["cells"] = [];
  for (const c of heatmap.columns) {
    const x0 = nsToMs(c.start_ns);
    const x1 = nsToMs(c.end_ns);
    for (const [price, qty] of c.bids) cells.push({ x0, x1, price, opacity: qty / (maxQty || 1), side: "BUY" });
    for (const [price, qty] of c.asks) cells.push({ x0, x1, price, opacity: qty / (maxQty || 1), side: "SELL" });
  }
  const segments: Layout["segments"] = [];
  const ends: Layout["ends"] = [];
  let maxDisplayed = 0;
  lifelines.lifelines.forEach((life, index) => {
    for (const s of life.segments) {
      if (s.price_ticks === null) continue;
      maxDisplayed = Math.max(maxDisplayed, s.displayed_qty);
      segments.push({
        x0: nsToMs(s.start_ns),
        x1: nsToMs(s.end_ns),
        price: s.price_ticks,
        displayed: s.displayed_qty,
        stop: s.state === "stop",
        life: index,
      });
    }
    const last = life.segments[life.segments.length - 1];
    if (last && last.price_ticks !== null) {
      ends.push({ x: life.end_ns ? nsToMs(life.end_ns) : nsToMs(last.end_ns), price: last.price_ticks, life: index });
    }
  });
  return { cells, masks: heatmap.masks, segments, ends, maxDisplayed };
}

/** The lifeline a click on the canvas landed on, if any. */
export function lifelineAt(input: CanvasInput, seriesId: string, dataIndex: number): LifelineT | null {
  const l = layout(input);
  const index =
    seriesId === "lifelines" ? l.segments[dataIndex]?.life : seriesId === "ends" ? l.ends[dataIndex]?.life : undefined;
  return index === undefined ? null : (input.lifelines.lifelines[index] ?? null);
}

function sideOf(life: LifelineT | undefined): "BUY" | "SELL" {
  return life?.side === "SELL" ? "SELL" : "BUY";
}

export function maskText(mask: HeatmapT["masks"][number]): string {
  const from = clockText(nsToMs(mask.from_ns));
  const to = clockText(nsToMs(mask.to_ns));
  const detail = mask.detail ? ` (${mask.detail})` : "";
  return `${MASK_LABEL[mask.kind]}${detail}: ${from} – ${to}; ${MASK_EFFECT[mask.kind]}`;
}

export function buildOption(input: CanvasInput): EChartsOption {
  const { heatmap, lifelines, trades, startMs, endMs, selected } = input;
  const decimals = heatmap.tick_decimals ?? lifelines.tick_decimals;
  const l = layout(input);
  const lives = lifelines.lifelines;

  const prices = [
    ...heatmap.levels.map((v) => v.price_ticks),
    ...l.segments.map((s) => s.price),
    ...trades.map((t) => t.priceTicks),
  ];
  const low = prices.length ? Math.min(...prices) - 2 : 0;
  const high = prices.length ? Math.max(...prices) + 2 : 1;
  const binMs = nsToMs(heatmap.bin_ns) || (endMs - startMs) / 100;
  const flow = flowBins(trades, startMs, endMs, binMs);
  const shown = trades.filter((t) => t.ms >= startMs && t.ms < endMs);
  const maxTrade = Math.max(1, ...shown.map((t) => t.qty));

  const timeAxis = (gridIndex: number, labels: boolean) => ({
    type: "value" as const,
    gridIndex,
    min: startMs,
    max: endMs,
    axisLabel: { show: labels, formatter: (v: number) => clockText(v) },
    axisTick: { show: labels },
    splitLine: { show: false },
  });

  const rect = (api: Api, x0: number, x1: number, y0: number, y1: number) => {
    const [px0 = 0, py0 = 0] = api.coord([x0, y0]);
    const [px1 = 0, py1 = 0] = api.coord([x1, y1]);
    return { x: Math.min(px0, px1), y: Math.min(py0, py1), width: Math.abs(px1 - px0), height: Math.abs(py1 - py0) };
  };

  const tooltipText = (p: { seriesId?: string; dataIndex: number }): string => {
    switch (p.seriesId) {
      case "cells": {
        const c = l.cells[p.dataIndex];
        return c ? `${c.side === "BUY" ? "Bid" : "Ask"} ${priceText(c.price, decimals)}: displayed depth ${Math.round(c.opacity * 100)}% of the window's largest` : "";
      }
      case "masks": {
        const m = l.masks[p.dataIndex];
        return m ? maskText(m) : "";
      }
      case "lifelines":
      case "ends": {
        const life = lifelineAt(input, p.seriesId, p.dataIndex);
        if (!life) return "";
        return `${life.gateway ?? "?"} ${life.side ?? ""} ${life.order_id.slice(0, 8)}… (run ${life.run}): ${endText(life)}, filled ${life.filled_qty}`;
      }
      case "trades": {
        const t = shown[p.dataIndex];
        if (!t) return "";
        const who = t.aggressor ? `${t.aggressor === "BUY" ? "buyer" : "seller"}-initiated` : "auction print";
        return `Trade ${t.qty} @ ${priceText(t.priceTicks, decimals)}, ${who}, ${clockText(t.ms)}`;
      }
      case "phases": {
        const ph = heatmap.phases[p.dataIndex];
        return ph ? `Phase ${ph.phase ?? "unknown"}: ${clockText(nsToMs(ph.from_ns))} – ${clockText(nsToMs(ph.to_ns))}` : "";
      }
      case "flow": {
        const b = flow[p.dataIndex];
        return b ? `Signed aggressive volume ${b.signed}${b.unsigned ? `; ${b.unsigned} without an aggressor` : ""}` : "";
      }
      default:
        return "";
    }
  };

  return {
    animation: false,
    aria: { enabled: true },
    tooltip: { trigger: "item", confine: true, formatter: tooltipText as never },
    grid: [
      { ...GRID, top: 6, height: 14 },
      { ...GRID, top: 28, bottom: 92 },
      { ...GRID, bottom: 24, height: 52 },
    ],
    xAxis: [timeAxis(0, false), timeAxis(1, false), timeAxis(2, true)],
    yAxis: [
      { type: "value", gridIndex: 0, min: 0, max: 1, show: false },
      {
        type: "value",
        gridIndex: 1,
        min: low,
        max: high,
        axisLabel: { formatter: (v: number) => priceText(Math.round(v), decimals) },
        splitLine: { lineStyle: { opacity: 0.15 } },
      },
      { type: "value", gridIndex: 2, axisLabel: { fontSize: 9 }, splitLine: { show: false } },
    ],
    brush: { toolbox: [], xAxisIndex: 1, brushType: "lineX", brushMode: "single", transformable: false },
    series: [
      {
        id: "phases",
        type: "custom",
        xAxisIndex: 0,
        yAxisIndex: 0,
        encode: { x: [0, 1] },
        data: heatmap.phases.map((p) => [nsToMs(p.from_ns), nsToMs(p.to_ns)]),
        renderItem: ((params: Params, api: Api): Graphic => {
          const ph = heatmap.phases[params.dataIndex]!;
          const shape = rect(api, nsToMs(ph.from_ns), nsToMs(ph.to_ns), 0, 1);
          const label = ph.phase ?? "unknown";
          return {
            type: "rect",
            shape,
            style: {
              fill: params.dataIndex % 2 ? "rgba(148,163,184,0.25)" : "rgba(148,163,184,0.12)",
              // About 6 px per character at 9 px: a label wider than its phase is left out (the tooltip names it).
              text: shape.width > label.length * 6 + 8 ? label : "",
              textFill: "rgb(148,163,184)",
              fontSize: 9,
            },
          };
        }) as never,
      },
      {
        id: "cells",
        type: "custom",
        xAxisIndex: 1,
        yAxisIndex: 1,
        encode: { x: [0, 1], y: 2 },
        data: l.cells.map((c) => [c.x0, c.x1, c.price]),
        renderItem: ((params: Params, api: Api): Graphic => {
          const c = l.cells[params.dataIndex]!;
          return {
            type: "rect",
            shape: rect(api, c.x0, c.x1, c.price - 0.5, c.price + 0.5),
            style: { fill: SIDE_COLOR[c.side], opacity: 0.12 + 0.68 * c.opacity },
          };
        }) as never,
      },
      {
        id: "masks",
        type: "custom",
        xAxisIndex: 1,
        yAxisIndex: 1,
        encode: { x: [0, 1] },
        data: l.masks.map((m) => [nsToMs(m.from_ns), nsToMs(m.to_ns)]),
        renderItem: ((params: Params, api: Api): Graphic => {
          const m = l.masks[params.dataIndex]!;
          const [x0 = 0] = api.coord([nsToMs(m.from_ns), 0]);
          const [x1 = 0] = api.coord([nsToMs(m.to_ns), 0]);
          const box = { x: Math.min(x0, x1), y: params.coordSys.y, width: Math.max(Math.abs(x1 - x0), 1), height: params.coordSys.height };
          const stroke = m.kind === "gap" ? "rgba(239,68,68,0.6)" : "rgba(245,158,11,0.6)";
          return {
            type: "group",
            children: [
              { type: "rect", shape: box, style: { fill: m.kind === "gap" ? "rgba(239,68,68,0.10)" : "rgba(245,158,11,0.08)" } },
              ...hatchLines(box.x, box.y, box.width, box.height).map(([ax, ay, bx, by]) => ({
                type: "line",
                silent: true,
                shape: { x1: ax, y1: ay, x2: bx, y2: by },
                style: { stroke, lineWidth: 1 },
              })),
            ],
          };
        }) as never,
      },
      {
        id: "lifelines",
        type: "custom",
        xAxisIndex: 1,
        yAxisIndex: 1,
        encode: { x: [0, 1], y: 2 },
        data: l.segments.map((s) => [s.x0, s.x1, s.price]),
        renderItem: ((params: Params, api: Api): Graphic => {
          const s = l.segments[params.dataIndex]!;
          const life = lives[s.life];
          const [px0 = 0, py = 0] = api.coord([s.x0, s.price]);
          const [px1 = 0] = api.coord([s.x1, s.price]);
          const width = 2 + 6 * (s.displayed / (l.maxDisplayed || 1)) + (life?.order_id === selected ? 3 : 0);
          return {
            type: "line",
            shape: { x1: px0, y1: py, x2: Math.max(px1, px0 + 1), y2: py },
            style: {
              stroke: SIDE_COLOR[sideOf(life)],
              lineWidth: width,
              lineDash: s.stop ? [4, 3] : null,
              opacity: selected && life?.order_id !== selected ? 0.45 : 0.95,
            },
          };
        }) as never,
      },
      {
        id: "ends",
        type: "scatter",
        xAxisIndex: 1,
        yAxisIndex: 1,
        symbolSize: 14,
        // Transparent by colour, not opacity: an item's opacity hides its label (the glyph) too.
        itemStyle: { color: "rgba(0,0,0,0)" },
        data: l.ends.map((e) => {
          const life = lives[e.life]!;
          return {
            value: [e.x, e.price],
            label: {
              show: true,
              position: "inside",
              formatter: END_MARKS[life.end].glyph,
              fontSize: 14,
              fontWeight: "bold",
              color: SIDE_COLOR[sideOf(life)],
              textBorderColor: "rgb(15,23,42)",
              textBorderWidth: 2,
            },
          };
        }),
      },
      {
        id: "trades",
        type: "scatter",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: shown.map((t) => ({
          value: [t.ms, t.priceTicks],
          symbol: t.auction || !t.aggressor ? "diamond" : t.aggressor === "BUY" ? "triangle" : "path://M0,0 L10,0 L5,10 Z",
          symbolSize: 6 + 14 * Math.sqrt(t.qty / maxTrade),
          itemStyle: {
            color: t.aggressor ? SIDE_COLOR[t.aggressor] : "rgb(148,163,184)",
            borderColor: "rgb(15,23,42)",
            borderWidth: 1,
          },
        })),
      },
      {
        id: "flow",
        type: "custom",
        xAxisIndex: 2,
        yAxisIndex: 2,
        encode: { x: [0, 1], y: 2 },
        data: flow.map((b) => [b.startMs, b.endMs, b.signed]),
        renderItem: ((params: Params, api: Api): Graphic => {
          const b = flow[params.dataIndex]!;
          return {
            type: "rect",
            shape: rect(api, b.startMs, b.endMs, 0, b.signed),
            style: { fill: b.signed >= 0 ? SIDE_COLOR.BUY : SIDE_COLOR.SELL },
          };
        }) as never,
      },
    ],
  } as EChartsOption;
}

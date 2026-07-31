/**
 * Index level line chart (design §10.2).
 *
 * A deliberately plainer sibling of `PriceChart`: an index has one series, no
 * candles and no volume, so the split-series treatment there would be noise.
 * Same thin-imperative-wrapper shape — everything that decides *what* to draw
 * is a pure function in `lib/index-series.ts`.
 */

import {
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { IndexPoint } from "../lib/index-series.js";

export interface IndexChartProps {
  points: IndexPoint[];
}

function token(name: string, fallback: string): string {
  if (typeof getComputedStyle === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

export function IndexChart({ points }: IndexChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const line = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const fg = token("--fg-subtle", "#8792a6");
    const grid = token("--border", "#262d3a");

    const chart = createChart(container, {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: fg, attributionLogo: false },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      rightPriceScale: { borderColor: grid },
      timeScale: { borderColor: grid, timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
    });
    chartRef.current = chart;
    line.current = chart.addSeries(LineSeries, {
      color: token("--accent", "#ffa028"),
      lineWidth: 2,
      priceLineVisible: false,
    });

    return () => {
      chart.remove();
      chartRef.current = null;
      line.current = null;
    };
  }, []);

  useEffect(() => {
    line.current?.setData(
      points.map((p) => ({ time: p.time as Time, value: p.value })),
    );
  }, [points]);

  return (
    <div className="relative h-72 w-full rounded border border-border">
      <div ref={containerRef} className="absolute inset-0" />
      {points.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-fg-subtle">
          {/*
            An exchange with no index configured never reaches this component,
            so an empty series here means the index exists but has not been
            recorded yet — a fresh install, or a preset reaching back further
            than pm-stats has data for.
          */}
          No level history for this period yet.
        </div>
      )}
    </div>
  );
}

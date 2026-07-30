/**
 * Candlestick + midpoint + volume chart (design §9.3, §9.4).
 *
 * Kept as a thin imperative wrapper: Lightweight Charts owns its own canvas
 * and mutates series in place, so all this does is create the chart once,
 * push data when it changes, and tear down on unmount. Everything that
 * decides *what* to draw is a pure function in `lib/bars.ts`.
 */

import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { Bar, LinePoint, VolumePoint } from "../lib/bars.js";

export interface PriceChartProps {
  bars: Bar[];
  volume: VolumePoint[];
  midHistorical: LinePoint[];
  midLive: LinePoint[];
  showCandles: boolean;
  showMidpoint: boolean;
  /** Pin the right edge and scroll with incoming ticks (the `Live` preset). */
  follow: boolean;
  theme: "dark" | "light";
}

/** Read a CSS variable so the chart tracks the app's theme rather than duplicating it. */
function token(name: string, fallback: string): string {
  if (typeof getComputedStyle === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

export function PriceChart(props: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candles = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volume = useRef<ISeriesApi<"Histogram"> | null>(null);
  const midPast = useRef<ISeriesApi<"Line"> | null>(null);
  const midNow = useRef<ISeriesApi<"Line"> | null>(null);

  // Recreated on theme change: series colours are set at construction and the
  // whole chart is cheap to rebuild, which is simpler than reaching into every
  // series to repaint it.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const up = token("--up", "#26d07c");
    const down = token("--down", "#ff4d5e");
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

    candles.current = chart.addSeries(CandlestickSeries, {
      upColor: up,
      downColor: down,
      borderUpColor: up,
      borderDownColor: down,
      wickUpColor: up,
      wickDownColor: down,
    });

    // Volume sits in its own scale pinned to the bottom fifth, so it reads as
    // context under the price rather than competing with it.
    volume.current = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      color: grid,
    });
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

    // The recorded history is drawn dashed and dimmer than the live tail: its
    // 15-minute cadence is far coarser, and a viewer should see at a glance
    // which part of the line is interpolated between samples (§9.3).
    midPast.current = chart.addSeries(LineSeries, {
      color: fg,
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    midNow.current = chart.addSeries(LineSeries, {
      color: token("--accent", "#ffa028"),
      lineWidth: 2,
      priceLineVisible: false,
    });

    return () => {
      chart.remove();
      chartRef.current = null;
      candles.current = volume.current = null;
      midPast.current = midNow.current = null;
    };
  }, [props.theme]);

  useEffect(() => {
    candles.current?.setData(
      props.showCandles ? props.bars.map((b) => ({ ...b, time: b.time as Time })) : [],
    );
    volume.current?.setData(
      props.showCandles ? props.volume.map((v) => ({ ...v, time: v.time as Time })) : [],
    );
  }, [props.bars, props.volume, props.showCandles]);

  useEffect(() => {
    const past = props.showMidpoint ? props.midHistorical : [];
    const now = props.showMidpoint ? props.midLive : [];
    midPast.current?.setData(past.map((p) => ({ ...p, time: p.time as Time })));
    midNow.current?.setData(now.map((p) => ({ ...p, time: p.time as Time })));
  }, [props.midHistorical, props.midLive, props.showMidpoint]);

  useEffect(() => {
    if (props.follow) chartRef.current?.timeScale().scrollToRealTime();
    else chartRef.current?.timeScale().fitContent();
  }, [props.follow, props.bars, props.midLive]);

  return <div ref={containerRef} className="h-full w-full" data-testid="price-chart" />;
}

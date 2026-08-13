import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type SeriesType,
  type UTCTimestamp,
} from "lightweight-charts";
import { useHistoryTradesQuery, useHistoryDailyChartQuery } from "@/queries/index.js";
import { useWsEvent } from "@/hooks/useWsEvent.js";
import {
  candlesToLine,
  dailyToCandles,
  foldTick,
  isIntraday,
  tradesToCandles,
  type Candle,
  type IntradayTimeframe,
  type Timeframe,
} from "@/lib/candles.js";
import type { HistoryTrade } from "@/types/index.js";

/** How many prints to pull for the intraday timeframes (§16.2.1). */
const CHART_TRADE_LIMIT = 1000;

const TIMEFRAMES: Timeframe[] = ["1m", "5m", "1h", "1D", "All"];

const CHART_OPTIONS = {
  layout: {
    background: { type: ColorType.Solid, color: "#0a0a0f" },
    textColor: "#9090b0",
    fontFamily: "JetBrains Mono, ui-monospace, monospace",
  },
  grid: {
    vertLines: { color: "#1a1a28" },
    horzLines: { color: "#1a1a28" },
  },
  crosshair: { mode: CrosshairMode.Normal },
  rightPriceScale: { borderColor: "#2a2a45" },
  timeScale: { borderColor: "#2a2a45", timeVisible: true, secondsVisible: false },
} as const;

function toCandleData(candles: Candle[]) {
  return candles.map((c) => ({
    time: (typeof c.time === "number" ? (c.time as UTCTimestamp) : c.time) as UTCTimestamp,
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
  }));
}

function toLinePoint(c: Candle) {
  return {
    time: (typeof c.time === "number" ? (c.time as UTCTimestamp) : c.time) as UTCTimestamp,
    value: c.close,
  };
}

function normaliseTrade(row: HistoryTrade) {
  return {
    timestamp: Math.floor(Date.parse(row.ts) / 1000),
    price: row.price,
    quantity: row.quantity,
  };
}

interface SymbolChartProps {
  symbol: string;
}

/**
 * Candlestick / line chart for one symbol (§16.2), rendered with Lightweight
 * Charts v5. Intraday timeframes are built from trade prints and appended to
 * live; 1D/All render the daily rollup and do not live-append (a daily bar's
 * time is a date string, not the tick's epoch bucket).
 */
export function SymbolChart({ symbol }: SymbolChartProps) {
  const [timeframe, setTimeframe] = useState<Timeframe>("5m");
  const [chartType, setChartType] = useState<"candlestick" | "line">("candlestick");

  const intraday = isIntraday(timeframe);
  const tradesQuery = useHistoryTradesQuery(intraday ? symbol : null, CHART_TRADE_LIMIT);
  const dailyQuery = useHistoryDailyChartQuery(intraday ? null : symbol);

  const candles = useMemo<Candle[]>(() => {
    if (intraday) {
      const ticks = (tradesQuery.data?.trades ?? []).map(normaliseTrade);
      return tradesToCandles(ticks, timeframe as IntradayTimeframe);
    }
    return dailyToCandles(dailyQuery.data?.daily ?? []);
  }, [intraday, timeframe, tradesQuery.data, dailyQuery.data]);

  // Refs the (once-bound) live-trade handler reads so it always sees the
  // current symbol / timeframe / series without re-subscribing.
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<SeriesType> | null>(null);
  const lastBarRef = useRef<Candle | null>(null);
  const symbolRef = useRef(symbol);
  const timeframeRef = useRef<Timeframe>(timeframe);
  const chartTypeRef = useRef<"candlestick" | "line">(chartType);
  const candlesRef = useRef<Candle[]>(candles);

  symbolRef.current = symbol;
  timeframeRef.current = timeframe;
  chartTypeRef.current = chartType;
  candlesRef.current = candles;

  // Create the chart once; keep it sized to its container.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = createChart(el, { ...CHART_OPTIONS, width: el.clientWidth, height: 320 });
    chartRef.current = chart;

    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width) chart.applyOptions({ width });
    });
    observer.observe(el);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // (Re)build the series when the chart type flips, then seed it with the
  // current candles so the switch is instant rather than waiting for a refetch.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    if (seriesRef.current) {
      chart.removeSeries(seriesRef.current);
      seriesRef.current = null;
    }
    if (chartType === "candlestick") {
      const series = chart.addSeries(CandlestickSeries, {
        upColor: "#22c55e",
        downColor: "#ef4444",
        borderVisible: false,
        wickUpColor: "#22c55e",
        wickDownColor: "#ef4444",
      });
      // The library's data-item unions are keyed on the series type; the
      // helper already produces the matching shape, so assert at the boundary.
      series.setData(toCandleData(candlesRef.current) as never);
      seriesRef.current = series;
    } else {
      const series = chart.addSeries(LineSeries, { color: "#6ea8fe", lineWidth: 2 });
      series.setData(candlesToLine(candlesRef.current) as never);
      seriesRef.current = series;
    }
    lastBarRef.current = candlesRef.current[candlesRef.current.length - 1] ?? null;
    chart.timeScale().fitContent();
  }, [chartType]);

  // Replace the data when the candle set changes (new timeframe / refetch).
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    if (chartType === "candlestick") series.setData(toCandleData(candles) as never);
    else series.setData(candlesToLine(candles) as never);
    lastBarRef.current = candles[candles.length - 1] ?? null;
    chartRef.current?.timeScale().fitContent();
  }, [candles, chartType]);

  // Live tick append (§16.2.3). Only for intraday timeframes and the active
  // symbol; the handler is bound once, so all mutable inputs come from refs.
  useWsEvent("trade", (env) => {
    const d = env.data;
    if (d.symbol !== symbolRef.current) return;
    if (!isIntraday(timeframeRef.current)) return;
    const series = seriesRef.current;
    if (!series) return;
    const { bar } = foldTick(
      lastBarRef.current,
      { timestamp: d.timestamp, price: d.price, quantity: d.quantity },
      timeframeRef.current as IntradayTimeframe,
    );
    lastBarRef.current = bar;
    if (chartTypeRef.current === "candlestick") {
      series.update({
        time: bar.time as UTCTimestamp,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      } as never);
    } else {
      series.update(toLinePoint(bar) as never);
    }
  });

  const loading = intraday ? tradesQuery.isLoading : dailyQuery.isLoading;
  const empty = !loading && candles.length === 0;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <div className="flex rounded border border-[#2a2a45] overflow-hidden">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              type="button"
              onClick={() => setTimeframe(tf)}
              aria-pressed={timeframe === tf}
              className={`px-2 py-0.5 text-xs font-mono ${
                timeframe === tf
                  ? "bg-[#20203a] text-[#e8e8f0]"
                  : "text-[#9090b0] hover:bg-[#1a1a28]"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={() => setChartType((t) => (t === "candlestick" ? "line" : "candlestick"))}
          className="ml-auto px-2 py-0.5 text-xs rounded border border-[#2a2a45] text-[#9090b0] hover:bg-[#1a1a28]"
        >
          {chartType === "candlestick" ? "Candles" : "Line"}
        </button>
      </div>

      <div className="relative">
        <div ref={containerRef} className="w-full" data-testid="symbol-chart" />
        {loading && (
          <p className="absolute inset-0 flex items-center justify-center text-xs text-[#9090b0]">
            Loading chart…
          </p>
        )}
        {empty && (
          <p className="absolute inset-0 flex items-center justify-center text-xs text-[#505070]">
            No {intraday ? "trades" : "daily history"} yet for {symbol}.
          </p>
        )}
      </div>
    </div>
  );
}

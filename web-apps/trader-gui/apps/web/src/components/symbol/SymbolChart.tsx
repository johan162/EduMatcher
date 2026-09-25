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
import { nsToEpochSec } from "@/lib/time.js";
import { CHART_COLORS } from "@/lib/chartTheme.js";
import { useThemeStore, type ThemePreference } from "@/store/useThemeStore.js";

/** How many prints to pull for the intraday timeframes (§16.2.1). */
const CHART_TRADE_LIMIT = 1000;

const TIMEFRAMES: Timeframe[] = ["1m", "5m", "1h", "1D", "All"];

function chartOptions(theme: ThemePreference) {
  const c = CHART_COLORS[theme];
  return {
    layout: {
      background: { type: ColorType.Solid, color: c.background },
      textColor: c.text,
      fontFamily: "JetBrains Mono, ui-monospace, monospace",
    },
    grid: {
      vertLines: { color: c.grid },
      horzLines: { color: c.grid },
    },
    crosshair: { mode: CrosshairMode.Normal },
    rightPriceScale: { borderColor: c.border },
    timeScale: { borderColor: c.border, timeVisible: true, secondsVisible: false },
  } as const;
}

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
  const theme = useThemeStore((s) => s.theme);

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
  const themeRef = useRef(theme);

  themeRef.current = theme;
  symbolRef.current = symbol;
  timeframeRef.current = timeframe;
  chartTypeRef.current = chartType;
  candlesRef.current = candles;

  // Create the chart once; keep it sized to its container.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = createChart(el, {
      ...chartOptions(themeRef.current),
      width: el.clientWidth,
      height: 320,
    });
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
    const colors = CHART_COLORS[themeRef.current];
    if (chartType === "candlestick") {
      const series = chart.addSeries(CandlestickSeries, {
        upColor: colors.up,
        downColor: colors.down,
        borderVisible: false,
        wickUpColor: colors.up,
        wickDownColor: colors.down,
      });
      // The library's data-item unions are keyed on the series type; the
      // helper already produces the matching shape, so assert at the boundary.
      series.setData(toCandleData(candlesRef.current) as never);
      seriesRef.current = series;
    } else {
      const series = chart.addSeries(LineSeries, { color: colors.line, lineWidth: 2 });
      series.setData(candlesToLine(candlesRef.current) as never);
      seriesRef.current = series;
    }
    lastBarRef.current = candlesRef.current[candlesRef.current.length - 1] ?? null;
    chart.timeScale().fitContent();
  }, [chartType]);

  // Recolour the live chart and its series when the theme flips.
  useEffect(() => {
    const colors = CHART_COLORS[theme];
    chartRef.current?.applyOptions(chartOptions(theme));
    if (chartTypeRef.current === "candlestick") {
      seriesRef.current?.applyOptions({
        upColor: colors.up,
        downColor: colors.down,
        wickUpColor: colors.up,
        wickDownColor: colors.down,
      } as never);
    } else {
      seriesRef.current?.applyOptions({ color: colors.line } as never);
    }
  }, [theme]);

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
    const prevBar = lastBarRef.current;
    const { bar } = foldTick(
      prevBar,
      { timestamp: nsToEpochSec(d.ts_ns), price: d.price, quantity: d.quantity },
      timeframeRef.current as IntradayTimeframe,
    );
    // H2 (docs-design/reviews/EduMatcher-Trader-GUI-Review.md): a replayed
    // print (reconnect, gap repair) can land in an already-closed earlier
    // bucket -- lightweight-charts' series.update requires non-decreasing
    // time and throws "Cannot update oldest data" otherwise.
    if (prevBar && bar.time < prevBar.time) return;
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
        <div className="flex rounded border border-line overflow-hidden">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              type="button"
              onClick={() => setTimeframe(tf)}
              aria-pressed={timeframe === tf}
              className={`px-2 py-0.5 text-xs font-mono ${
                timeframe === tf ? "bg-elevated text-fg" : "text-fg-dim hover:bg-raised"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={() => setChartType((t) => (t === "candlestick" ? "line" : "candlestick"))}
          className="ml-auto px-2 py-0.5 text-xs rounded border border-line text-fg-dim hover:bg-raised"
        >
          {chartType === "candlestick" ? "Candles" : "Line"}
        </button>
      </div>

      <div className="relative">
        <div ref={containerRef} className="w-full" data-testid="symbol-chart" />
        {loading && (
          <p className="absolute inset-0 flex items-center justify-center text-xs text-fg-dim">
            Loading chart…
          </p>
        )}
        {empty && (
          <p className="absolute inset-0 flex items-center justify-center text-xs text-fg-faint">
            No {intraday ? "trades" : "daily history"} yet for {symbol}.
          </p>
        )}
      </div>
    </div>
  );
}

/**
 * ECharts on a canvas, loaded on first use (a separate chunk: the shell and
 * the login carry none of it), with only the parts the Market canvas draws.
 * It reports item clicks and a horizontal brush; the option is built
 * elsewhere (chartOption.ts) and tested there.
 */
import { useEffect, useRef } from "react";
import type { EChartsOption, EChartsType } from "echarts";

export interface EChartProps {
  option: EChartsOption;
  /** A click on a mark: its series id and index in that series' data. */
  onItemClick: (seriesId: string, dataIndex: number) => void;
  /** A brushed interval on the main grid's time axis, in milliseconds. */
  onBrush: (startMs: number, endMs: number) => void;
  ariaLabel: string;
  height: number;
}

async function loadECharts() {
  return (await import("./echartsSetup")).echarts;
}

export function EChart({ option, onItemClick, onBrush, ariaLabel, height }: EChartProps) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<EChartsType | null>(null);
  const handlers = useRef({ onItemClick, onBrush });
  handlers.current = { onItemClick, onBrush };
  const latest = useRef(option);
  latest.current = option;

  useEffect(() => {
    let disposed = false;
    let observer: ResizeObserver | null = null;
    void loadECharts().then((echarts) => {
      if (disposed || !el.current) return;
      const c = echarts.init(el.current, undefined, { renderer: "canvas" }) as unknown as EChartsType;
      chart.current = c;
      c.setOption(latest.current, true);
      c.dispatchAction({ type: "takeGlobalCursor", key: "brush", brushOption: { brushType: "lineX", brushMode: "single" } });
      c.on("click", (p) => {
        const params = p as { seriesId?: string; dataIndex?: number };
        if (params.seriesId !== undefined && params.dataIndex !== undefined) {
          handlers.current.onItemClick(params.seriesId, params.dataIndex);
        }
      });
      c.on("brushEnd", (p) => {
        const area = (p as { areas?: { coordRange?: [number, number] }[] }).areas?.[0];
        const range = area?.coordRange;
        c.dispatchAction({ type: "brush", areas: [] });
        if (range && range[1] > range[0]) handlers.current.onBrush(range[0], range[1]);
      });
      if (typeof ResizeObserver !== "undefined") {
        observer = new ResizeObserver(() => c.resize());
        observer.observe(el.current);
      }
    });
    return () => {
      disposed = true;
      observer?.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    const c = chart.current;
    if (!c) return;
    c.setOption(option, true);
    c.dispatchAction({ type: "takeGlobalCursor", key: "brush", brushOption: { brushType: "lineX", brushMode: "single" } });
  }, [option]);

  return <div ref={el} role="img" aria-label={ariaLabel} style={{ width: "100%", height }} />;
}

/**
 * ECharts on a canvas, loaded on first use (a separate chunk: the shell and
 * the login carry none of it), with only the parts the Market canvas draws.
 * It reports item clicks and a horizontal brush; the option is built
 * elsewhere (chartOption.ts) and tested there.
 */
import { useEffect, useRef } from "react";
import type { EChartsOption, EChartsType } from "echarts";
import { FONT_SIZE_FACTOR, useFontSizeStore } from "@/store/useFontSizeStore";

export interface EChartProps {
  option: EChartsOption;
  /**
   * A click on the main grid, in data units: time (ms) and price, with how
   * much of each a few pixels are (the hit tolerance).
   */
  onPlotClick: (ms: number, price: number, tolMs: number, tolPrice: number) => void;
  /** A brushed interval on the main grid's time axis, in milliseconds. */
  onBrush: (startMs: number, endMs: number) => void;
  ariaLabel: string;
  height: number;
}

/** How near (in pixels) a click must land to pick a lifeline. */
const HIT_PX = 6;

async function loadECharts() {
  return (await import("./echartsSetup")).echarts;
}

export function EChart({ option, onPlotClick, onBrush, ariaLabel, height }: EChartProps) {
  // The font-size setting zooms #root with CSS `zoom`, which ECharts' pointer
  // mapping does not undo (a brush landed 1.25x off, found in Chrome). The
  // canvas is counter-zoomed back to 1, so it and the browser agree on pixels.
  const unzoom = 1 / FONT_SIZE_FACTOR[useFontSizeStore((s) => s.fontSize)];
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<EChartsType | null>(null);
  const handlers = useRef({ onPlotClick, onBrush });
  handlers.current = { onPlotClick, onBrush };
  const latest = useRef(option);
  latest.current = option;

  useEffect(() => {
    let disposed = false;
    let observer: ResizeObserver | null = null;
    let onClick: ((e: MouseEvent) => void) | null = null;
    const host = el.current;
    void loadECharts().then((echarts) => {
      if (disposed || !el.current) return;
      const c = echarts.init(el.current, undefined, { renderer: "canvas" }) as unknown as EChartsType;
      chart.current = c;
      c.setOption(latest.current, true);
      c.dispatchAction({ type: "takeGlobalCursor", key: "brush", brushOption: { brushType: "lineX", brushMode: "single" } });
      // The brush holds the cursor, so neither series nor canvas (zrender)
      // click events fire (checked in Chrome): listen for the DOM click on
      // the container and convert it to data units on the main grid.
      const host = el.current;
      onClick = (e: MouseEvent) => {
        // The font-size setting zooms #root with CSS `zoom`: the client rect is
        // in zoomed pixels, ECharts works in the element's own (clientWidth).
        const box = host.getBoundingClientRect();
        const zoom = box.width / (host.clientWidth || box.width);
        const at = [(e.clientX - box.left) / zoom, (e.clientY - box.top) / zoom];
        if (!c.containPixel({ gridIndex: 1 }, at)) return;
        const [ms, price] = c.convertFromPixel({ gridIndex: 1 }, at) as number[];
        const [ms2, price2] = c.convertFromPixel({ gridIndex: 1 }, [at[0]! + HIT_PX, at[1]! + HIT_PX]) as number[];
        if (ms === undefined || price === undefined || ms2 === undefined || price2 === undefined) return;
        handlers.current.onPlotClick(ms, price, Math.abs(ms2 - ms), Math.abs(price2 - price));
      };
      host.addEventListener("click", onClick);
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
      if (onClick) host?.removeEventListener("click", onClick);
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

  // The label sits on a wrapper: ECharts rewrites attributes of the element it
  // draws in. Its canvas is hidden from assistive tech; the page's lists and
  // legend are the chart's accessible equivalent.
  return (
    <div role="img" aria-label={ariaLabel} style={{ zoom: unzoom }}>
      <div ref={el} aria-hidden="true" style={{ width: "100%", height }} />
    </div>
  );
}

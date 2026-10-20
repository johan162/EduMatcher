/**
 * History wiring for the rows (design D3.5).
 *
 * - {@link useHistory} fetches a panel's history for the time picker's
 *   range: once when the range (or what the panel asks for) changes, then
 *   every refresh interval, and not otherwise.
 * - {@link useLiveSeries} appends the live value from each snapshot between
 *   fetches -- at the chart's own resolution: a point when a new bucket
 *   begins (on the bucket starts the bridge's data is on), so a 1 Hz
 *   snapshot redraws a chart once per bucket, not every second.
 * - {@link useChartRange} is the window a chart shows, ending at the latest
 *   snapshot's time (pm-monitor's clock, not the browser's) and moving once
 *   per bucket, so a memoised chart is not redrawn every second.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { HealthSnapshot, Point, RangeName } from "@edumatcher/dash-types";
import { RANGE_MS } from "../lib/api.js";
import { REFRESH_MS } from "../lib/range.js";
import { useDashStore } from "../store/useDashStore.js";
import type { TimeSeriesLine } from "../components/widgets/TimeSeries.js";
import type { TimeRangeMs } from "../components/widgets/StateTimeline.js";

export interface History<T> {
  data: T | null;
  error: string | null;
}

/**
 * `load` for the current range; `key` names what is asked for (null: not
 * yet known, nothing is fetched). A change of key or range drops the old
 * data and fetches once; the refresh interval fetches again.
 */
export function useHistory<T>(key: string | null, load: (range: RangeName, signal: AbortSignal) => Promise<T>): History<T> {
  const range = useDashStore((s) => s.range);
  const refresh = useDashStore((s) => s.refresh);
  const [state, setState] = useState<History<T>>({ data: null, error: null });
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    setState({ data: null, error: null });
    if (key === null) return;
    let ctl = new AbortController();
    const run = () => {
      ctl.abort();
      const mine = (ctl = new AbortController());
      loadRef.current(range, mine.signal).then(
        (data) => {
          if (!mine.signal.aborted) setState({ data, error: null });
        },
        (err: unknown) => {
          if (!mine.signal.aborted) setState((s) => ({ data: s.data, error: err instanceof Error ? err.message : String(err) }));
        },
      );
    };
    run();
    const every = REFRESH_MS[refresh];
    const timer = every === null ? undefined : setInterval(run, every);
    return () => {
      ctl.abort();
      clearInterval(timer);
    };
  }, [key, range, refresh]);

  return state;
}

/** The latest snapshot's time in epoch ms (pm-monitor's clock); the browser's before the first. */
export function useNow(): number {
  const ts = useDashStore((s) => s.snapshot?.ts);
  const parsed = ts ? Date.parse(ts) : Number.NaN;
  return Number.isFinite(parsed) ? parsed : Date.now();
}

/** The picker's window ending now, moving in steps of `stepMs` (a chart's bucket). */
export function useChartRange(stepMs: number): TimeRangeMs {
  const range = useDashStore((s) => s.range);
  const now = useNow();
  const step = stepMs > 0 ? stepMs : 1000;
  const toMs = Math.ceil(now / step) * step;
  return useMemo(() => ({ fromMs: toMs - RANGE_MS[range], toMs }), [toMs, range]);
}

/**
 * `points` with the live `value` at `ts` appended when `ts` falls in a
 * bucket after the last point's (bucket starts on the data's grid, from
 * its last point; `ts`'s own when there is none). The same array when
 * nothing is appended.
 */
export function appendLive(points: readonly Point[], ts: number, value: number | null, bucketMs: number): readonly Point[] {
  if (value === null || !Number.isFinite(value) || !(bucketMs > 0) || !Number.isFinite(ts)) return points;
  const last = points.at(-1)?.[0];
  if (last === undefined) return [[Math.floor(ts / bucketMs) * bucketMs, value]];
  const start = last + Math.floor((ts - last) / bucketMs) * bucketMs;
  return start > last ? [...points, [start, value]] : points;
}

/**
 * `base` (fetched history) with each snapshot's live values appended
 * (appendLive); `values` gives one value per series of `base`, null for
 * none. Starts again from `base` whenever it is fetched anew.
 */
export function useLiveSeries(
  base: readonly TimeSeriesLine[] | null,
  bucketMs: number,
  values: (snapshot: HealthSnapshot) => readonly (number | null)[],
): readonly TimeSeriesLine[] | null {
  const snapshot = useDashStore((s) => s.snapshot);
  const [live, setLive] = useState<{ base: readonly TimeSeriesLine[] | null; series: readonly TimeSeriesLine[] | null }>({ base, series: base });
  const valuesRef = useRef(values);
  valuesRef.current = values;

  const current = live.base === base ? live.series : base;
  useEffect(() => {
    if (!current || !snapshot) return;
    const ts = Date.parse(snapshot.ts);
    const vs = valuesRef.current(snapshot);
    let changed = false;
    const next = current.map((s, i) => {
      const points = appendLive(s.points, ts, vs[i] ?? null, bucketMs);
      if (points === s.points) return s;
      changed = true;
      return { ...s, points };
    });
    if (changed || live.base !== base) setLive({ base, series: changed ? next : current });
  }, [snapshot, base, bucketMs]);

  return current;
}

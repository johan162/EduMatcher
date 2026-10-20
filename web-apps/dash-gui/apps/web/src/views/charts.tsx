/**
 * The two single-series history charts the rows and drawers share:
 *
 * - {@link CounterBars}: a counter's increments per minute (or hour) from
 *   /api/rate, refetched every refresh interval -- a bucket is complete
 *   only when its minute is, so it is not extended between fetches.
 * - {@link SeriesChart}: one stored series from /api/series (a vital of one
 *   process, a gauge of one participant or book), with each snapshot's
 *   live value appended at the series' own resolution.
 */

import { useMemo } from "react";
import type { HealthSnapshot, RateResponse, SeriesResponse } from "@edumatcher/dash-types";
import { RateBars } from "../components/widgets/RateBars.js";
import { TimeSeries } from "../components/widgets/TimeSeries.js";
import { useChartRange, useHistory, useLiveSeries } from "../hooks/history.js";
import { getJson, query, rateBucket } from "../lib/api.js";
import type { Thresholds } from "../lib/thresholds.js";
import { useDashStore } from "../store/useDashStore.js";
import { useAnnotations } from "./rows/common.js";

export interface CounterBarsProps {
  label: string;
  /** The counter in metrics.db. */
  name: string;
  /** One participant's or symbol's increments; all labels summed when absent. */
  seriesLabel?: string;
  /** The legend's name for the bars. */
  legend: string;
  format: (v: number) => string;
}

export function CounterBars({ label, name, seriesLabel, legend, format }: CounterBarsProps) {
  const tz = useDashStore((s) => s.sessionTz);
  const { bucketMs } = rateBucket(useDashStore((s) => s.range));
  const history = useHistory<RateResponse>(`rate|${name}|${seriesLabel ?? ""}`, (range, signal) =>
    getJson(`/api/rate?${query({ name, label: seriesLabel, range, bucket: rateBucket(range).bucket })}`, signal),
  );
  const range = useChartRange(bucketMs);
  const data = history.data ? [{ label: legend, points: history.data.points }] : [];
  return <RateBars label={label} series={data} range={range} bucketMs={bucketMs} tz={tz} format={format} />;
}

export interface SeriesChartProps {
  label: string;
  /** The stored series: `name` with `seriesLabel` ("" for none), from `source` when several processes record it. */
  name: string;
  seriesLabel?: string;
  source?: string;
  legend: string;
  /** The same figure from a snapshot, for the live points; null for none. */
  live: (snapshot: HealthSnapshot) => number | null;
  format: (v: number) => string;
  thresholds?: Thresholds;
  integer?: boolean;
  height?: number;
}

export function SeriesChart({ label, name, seriesLabel = "", source, legend, live, format, thresholds, integer, height }: SeriesChartProps) {
  const tz = useDashStore((s) => s.sessionTz);
  const history = useHistory<SeriesResponse>(`series|${name}|${seriesLabel}|${source ?? ""}`, (range, signal) =>
    getJson(`/api/series?${query({ name, label: seriesLabel || undefined, source, range })}`, signal),
  );
  const bucketMs = (history.data?.bucketSec ?? 10) * 1000;
  const base = useMemo(() => (history.data ? [{ label: legend, points: history.data.points }] : null), [history.data, legend]);
  const series = useLiveSeries(base, bucketMs, (snap) => [live(snap)]);
  const range = useChartRange(bucketMs);
  const annotations = useAnnotations();
  return (
    <TimeSeries
      label={label}
      series={series ?? []}
      range={range}
      tz={tz}
      format={format}
      thresholds={thresholds}
      annotations={annotations}
      integer={integer}
      height={height}
    />
  );
}

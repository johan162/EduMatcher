/**
 * One vital of every exchange process over the picked range (exchange
 * memory by process, CPU per process): one /api/series/multi call with
 * `sources=`, so every line is at one resolution on the same buckets (the
 * TimeSeries data contract), then each snapshot's live values appended at
 * that resolution.
 */

import { useMemo } from "react";
import type { HealthSnapshot, MultiSeriesResponse, ProcessHealth } from "@edumatcher/dash-types";
import { TimeSeries } from "../../components/widgets/TimeSeries.js";
import { useChartRange, useHistory, useLiveSeries } from "../../hooks/history.js";
import { getJson, query } from "../../lib/api.js";
import type { Thresholds } from "../../lib/thresholds.js";
import { useDashStore } from "../../store/useDashStore.js";
import { NO_SERIES } from "../charts.js";
import { beaconing, liveExchangeProcesses, shortKey } from "./common.js";

export interface ProcessSeriesChartProps {
  label: string;
  /** The stored series: `proc.<vital>`. */
  name: string;
  /** The same vital from a snapshot's process record, for the live points. */
  live: (p: ProcessHealth) => number;
  format: (v: number) => string;
  stacked?: boolean;
  thresholds?: Thresholds;
  height?: number;
}

/**
 * Each charted process's live figure from a snapshot, in `keys` order: null
 * for one gone from it, and for one whose beacons stopped -- its record
 * keeps the last figures, which are not current (I118).
 */
export function liveValues(snap: HealthSnapshot, keys: readonly string[], live: (p: ProcessHealth) => number): (number | null)[] {
  return keys.map((key) => {
    const p = snap.processes.find((x) => x.key === key);
    return p && beaconing(p) ? live(p) : null;
  });
}

export function ProcessSeriesChart({ label, name, live, format, stacked, thresholds, height }: ProcessSeriesChartProps) {
  const tz = useDashStore((s) => s.sessionTz);
  // Recomputed every snapshot, but the joined keys only change when a process comes or goes.
  const sources = useDashStore((s) => liveExchangeProcesses(s.snapshot?.processes ?? []).map((p) => p.key).join(","));
  const history = useHistory<MultiSeriesResponse>(sources === "" ? null : `${name}|${sources}`, (range, signal) =>
    getJson(`/api/series/multi?${query({ name, sources, range })}`, signal),
  );
  const bucketMs = (history.data?.bucketSec ?? 10) * 1000;
  const base = useMemo(
    () => history.data?.series.map((s) => ({ label: shortKey(s.source), points: s.points })) ?? null,
    [history.data],
  );
  const keys = useMemo(() => history.data?.series.map((s) => s.source) ?? [], [history.data]);
  const series = useLiveSeries(base, bucketMs, (snap: HealthSnapshot) => liveValues(snap, keys, live));
  const range = useChartRange(bucketMs);

  return (
    <TimeSeries
      label={label}
      series={series ?? NO_SERIES}
      range={range}
      tz={tz}
      format={format}
      stacked={stacked}
      thresholds={thresholds}
      height={height}
    />
  );
}

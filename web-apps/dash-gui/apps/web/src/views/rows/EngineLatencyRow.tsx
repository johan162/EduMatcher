/**
 * ENGINE LATENCY: how long the matching engine takes per message, and how
 * much of that is garbage collection.
 *
 * Every figure is the engine's own, over its last minute: order entry
 * (new, cancel, amend, quotes, combos, OCOs) timed 1 message in 16, apart
 * from everything else it handles -- heartbeats, connects, queries, admin --
 * whose cost says nothing about matching. GC pauses are timed for every
 * collection, sampled message or not, so the longest stall is never missed.
 *
 * The history is one /api/series/multi?names= call, drawn as two charts:
 * latency in microseconds, GC pauses in milliseconds, each on its own scale.
 */

import { useMemo } from "react";
import type { HealthSnapshot, MultiSeriesResponse } from "@edumatcher/dash-types";
import { Row } from "../../components/widgets/Row.js";
import { StatTile } from "../../components/widgets/StatTile.js";
import { TimeSeries } from "../../components/widgets/TimeSeries.js";
import { useChartRange, useHistory, useLiveSeries } from "../../hooks/history.js";
import { getJson, query } from "../../lib/api.js";
import { formatCount, formatMicros, formatPercent } from "../../lib/format.js";
import { LATENCY } from "../../lib/metrics.js";
import { useDashStore } from "../../store/useDashStore.js";
import { NO_SERIES } from "../charts.js";
import { useBreachLevel, useRule } from "./common.js";

/** Fewer samples than this, and nearest-rank p99 is just their maximum. */
export const MIN_P99_SAMPLES = 100;

const LATENCY_LINES = [
  { name: LATENCY.p50, label: "p50", live: (s: HealthSnapshot) => s.trading.handle_p50_us },
  { name: LATENCY.p99, label: "p99", live: (s: HealthSnapshot) => s.trading.handle_p99_us },
  { name: LATENCY.p99ExGc, label: "p99 without GC", live: (s: HealthSnapshot) => s.trading.handle_p99_ex_gc_us },
] as const;
const GC_LINE = { name: LATENCY.gcPauseMax, label: "longest GC pause", live: (s: HealthSnapshot) => s.trading.gc_pause_max_us };
const NAMES = [...LATENCY_LINES, GC_LINE].map((l) => l.name).join(",");

function useEngineHistory() {
  const source = useDashStore((s) => s.snapshot?.processes.find((p) => p.process === "pm-engine")?.key ?? null);
  return useHistory<MultiSeriesResponse>(source === null ? null : `engine-latency|${source}`, (range, signal) =>
    getJson(`/api/series/multi?${query({ names: NAMES, source: source!, range })}`, signal),
  );
}

function LatencyCharts() {
  const tz = useDashStore((s) => s.sessionTz);
  const p99Rule = useRule("engine_handle_p99_us");
  const history = useEngineHistory();
  const bucketMs = (history.data?.bucketSec ?? 10) * 1000;
  // Once per fetch, not per snapshot: a new series each render would redraw the chart every second (I118).
  const [latencyBase, gcBase] = useMemo(() => {
    const data = history.data;
    if (!data) return [null, null];
    const line = (l: { name: string; label: string }) => ({
      label: l.label,
      points: data.series.find((s) => s.name === l.name)?.points ?? [],
    });
    return [LATENCY_LINES.map(line), [line(GC_LINE)]];
  }, [history.data]);
  const latency = useLiveSeries(latencyBase, bucketMs, (snap) => LATENCY_LINES.map((l) => l.live(snap)));
  const gc = useLiveSeries(gcBase, bucketMs, (snap) => [GC_LINE.live(snap)]);
  const range = useChartRange(bucketMs);
  return (
    <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
      <TimeSeries label="Order latency" series={latency ?? NO_SERIES} range={range} tz={tz} format={formatMicros} thresholds={p99Rule} />
      <TimeSeries label="Longest GC pause" series={gc ?? NO_SERIES} range={range} tz={tz} format={formatMicros} />
    </div>
  );
}

export function EngineLatencyRow() {
  const trading = useDashStore((s) => s.snapshot?.trading ?? null);
  const p99Rule = useRule("engine_handle_p99_us");
  const p99Level = useBreachLevel("engine_handle_p99_us");
  const samples = trading?.handle_samples ?? 0;
  const few = trading !== null && samples < MIN_P99_SAMPLES;

  return (
    <Row
      id="engine-latency"
      title="Engine latency"
      badge={few ? `${formatCount(samples)} samples: p99 is the maximum` : undefined}
      badgeTone="text-fg-subtle"
    >
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile label="Order p50" value={trading?.handle_p50_us ?? null} format={formatMicros} sub="last minute" />
        <StatTile
          label="Order p99"
          value={trading?.handle_p99_us ?? null}
          format={formatMicros}
          thresholds={p99Rule}
          level={p99Level}
          sub={trading ? `${formatCount(samples)} samples` : undefined}
        />
        <StatTile label="p99 without GC" value={trading?.handle_p99_ex_gc_us ?? null} format={formatMicros} sub="GC time taken out" />
        <StatTile label="Other messages p99" value={trading?.other_p99_us ?? null} format={formatMicros} sub="queries, heartbeats, admin" />
        <StatTile label="Longest GC pause" value={trading?.gc_pause_max_us ?? null} format={formatMicros} sub="last minute" />
        <StatTile label="Time in GC" value={trading?.gc_time_pct ?? null} format={formatPercent} sub="of engine wall time" />
      </div>
      <LatencyCharts />
    </Row>
  );
}

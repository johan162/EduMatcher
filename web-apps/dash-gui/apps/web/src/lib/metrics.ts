/**
 * Every metric name the dashboard reads, in one place (design D3.1), so a
 * renamed metric is one edit here -- and fails two tests until it is made:
 * tests/test_dash_metrics_mirror.py checks each against what its process
 * emits (read from the producers' source), test/metrics.test.ts against a
 * snapshot captured from a running exchange.
 *
 * Most figures come from the snapshot's own records (trading, participants,
 * books, gateways, host); these are the ones read from a process's beacon
 * metrics, and the series pm-monitor stores in metrics.db.
 */

import type { HealthSnapshot, MetricSample, ProcessHealth } from "@edumatcher/dash-types";

export interface BeaconMetric {
  /** The process that emits it (`ProcessHealth.process`). */
  process: string;
  name: string;
  /** Emitted only once it has something to count: absent means 0. */
  lazy?: boolean;
}

/** Read from `ProcessHealth.metrics` of the process named. */
export const METRIC = {
  engineDiagnostics: { process: "pm-engine", name: "engine.diagnostics" },
  apiWsSessions: { process: "pm-api-gwy", name: "api.ws_sessions" },
  apiDroppedEvents: { process: "pm-api-gwy", name: "api.dropped_events", lazy: true },
  statsFeedGaps: { process: "pm-stats", name: "stats.feed_gaps" },
} satisfies Record<string, BeaconMetric>;

/** Counters in metrics.db, read through /api/rate. */
export const COUNTER = {
  ordersIn: "engine.orders_in",
  trades: "engine.trades",
  tradedValue: "engine.traded_value",
  rejects: "engine.rejects",
} as const;

/**
 * The requests a reject is counted against: pm-monitor's REQUEST_COUNTERS
 * (monitor/activity.py), so the chart's ratio is the one it judges.
 */
export const REQUEST_COUNTERS = ["engine.orders_in", "engine.cancels_in", "engine.amends_in", "engine.quotes_in"] as const;

/** Requests below which there is no reject ratio: monitor/thresholds.py MIN_REQUESTS_5M. */
export const MIN_REQUESTS = 20;

/** Per-process vitals pm-monitor stores (collector.py VITALS, as `proc.<vital>`). */
export const VITAL = {
  rss: "proc.rss_bytes",
  cpu: "proc.cpu_pct",
} as const;

/** Every sample of `metric` from the processes it names (all instances). */
export function samples(processes: readonly ProcessHealth[], metric: BeaconMetric): MetricSample[] {
  return processes.filter((p) => p.process === metric.process).flatMap((p) => p.metrics.filter((m) => m.name === metric.name));
}

/** The sum of `metric` over its labels and processes; null if none reports it (0 if it is lazy). */
export function total(snapshot: HealthSnapshot, metric: BeaconMetric): number | null {
  const found = samples(snapshot.processes, metric);
  if (found.length === 0) return metric.lazy ? 0 : null;
  return found.reduce((sum, m) => sum + m.value, 0);
}

/** `metric`'s value per label, summed over processes. */
export function byLabel(snapshot: HealthSnapshot, metric: BeaconMetric): { label: string; value: number }[] {
  const out = new Map<string, number>();
  for (const m of samples(snapshot.processes, metric)) out.set(m.label, (out.get(m.label) ?? 0) + m.value);
  return [...out.entries()].map(([label, value]) => ({ label, value }));
}

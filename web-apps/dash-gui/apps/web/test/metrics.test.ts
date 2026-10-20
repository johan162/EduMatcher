/**
 * D3.1: every metric name the dashboard reads is in a snapshot captured
 * from a running exchange (test/fixtures/snapshot.json), from the process
 * it is read from. tests/test_dash_metrics_mirror.py pins the same names to
 * the producers' source, so a rename fails there even before a new capture.
 */

import { describe, expect, it } from "vitest";
import { byLabel, COUNTER, GAUGE, METRIC, REQUEST_COUNTERS, samples, total, type BeaconMetric } from "../src/lib/metrics.js";
import { CAPTURED, fixtureSnapshot } from "./fixtures/snapshots.js";

const emitted = (process: string) => new Set(CAPTURED.processes.filter((p) => p.process === process).flatMap((p) => p.metrics.map((m) => m.name)));

describe("metric names", () => {
  it.each(Object.entries(METRIC).filter(([, m]) => !(m as BeaconMetric).lazy))("%s is emitted by its process", (_key, m) => {
    expect(emitted(m.process).has(m.name), `${m.process} ${m.name}`).toBe(true);
  });

  it("the engine's record carries no per-participant or per-symbol samples but diagnostics", () => {
    // pm-monitor leaves them out of the snapshot (I123): the trading,
    // participants and books blocks carry them derived, and the history API
    // serves COUNTER and GAUGE from metrics.db. tests/test_dash_metrics_mirror.py
    // pins those names to the engine and to what pm-monitor stores.
    const engine = CAPTURED.processes.find((p) => p.process === "pm-engine")!;
    const labelled = new Set(engine.metrics.filter((m) => m.label !== "").map((m) => m.name));
    expect([...labelled]).toEqual([METRIC.engineDiagnostics.name]);
    for (const name of [...Object.values(COUNTER), ...REQUEST_COUNTERS, ...Object.values(GAUGE)]) {
      expect(engine.metrics.some((m) => m.name === name && m.label !== ""), name).toBe(false);
    }
  });

  it("a lazy metric that is absent counts 0; any other absent one is no value", () => {
    expect(total(CAPTURED, METRIC.apiDroppedEvents)).toBe(0);
    const stripped = fixtureSnapshot({ processes: CAPTURED.processes.filter((p) => p.process !== "pm-stats") });
    expect(total(stripped, METRIC.statsFeedGaps)).toBeNull();
  });

  it("sums over labels and processes, or keeps the labels", () => {
    const sessions = samples(CAPTURED.processes, METRIC.apiWsSessions);
    expect(sessions.length).toBeGreaterThan(1); // one per channel
    expect(total(CAPTURED, METRIC.apiWsSessions)).toBe(sessions.reduce((s, m) => s + m.value, 0));
    expect(byLabel(CAPTURED, METRIC.engineDiagnostics).map((d) => d.label)).toContain("DISPATCH_ERROR");
  });
});

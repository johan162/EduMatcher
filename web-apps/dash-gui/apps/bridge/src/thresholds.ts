/**
 * The threshold rules pm-monitor judges by (design §9.6, I113), for the
 * widgets' bands, colours and hover texts while nothing is in breach -- the
 * snapshot carries only active breaches.
 *
 * Source: the deployed artifact's `monitor.thresholds`, which is complete
 * (the compiler writes every rule, defaults filled in) and is what
 * pm-monitor read when it started. With no artifact deployed pm-monitor
 * runs on its built-in defaults, and so does this: DEFAULT_THRESHOLDS,
 * INVERTED and FIXED_RULES mirror monitor/config.py and monitor/thresholds.py
 * and are pinned to them by tests/test_dash_thresholds_mirror.py.
 *
 * An artifact that is there but cannot be used (unreadable, not JSON, a
 * rule missing or not a number) is an error, never quietly replaced by the
 * defaults: the page would then show thresholds pm-monitor is not using.
 * The file is read again only when it changes.
 */

import { readFileSync, statSync } from "node:fs";
import type { ThresholdRule, ThresholdsResponse } from "@edumatcher/dash-types";
import { QueryError } from "./metrics-db.js";

/** monitor/config.py `MonitorThresholds()`: the configurable rules and their defaults. */
export const DEFAULT_THRESHOLDS: Record<string, { warn: number; crit: number }> = {
  host_cpu_pct: { warn: 80, crit: 95 },
  host_mem_pct: { warn: 80, crit: 92 },
  disk_free_pct: { warn: 15, crit: 5 },
  engine_handle_p99_us: { warn: 2000, crit: 10000 },
  reject_pct_5m: { warn: 10, crit: 30 },
  rss_growth_pct_1h: { warn: 50, crit: 100 },
  heap_garbage_pct: { warn: 50, crit: 80 },
};

/** monitor/config.py `INVERTED_THRESHOLDS`: low is bad. */
export const INVERTED: readonly string[] = ["disk_free_pct"];

/**
 * Rules fixed in pm-monitor's code: `loop_age_ms` (thresholds.py
 * LOOP_AGE_WARN_MS; its critical level is the HUNG state), and the
 * "any increase over 5 minutes" rules (activity.py WATCHED_INCREASES and
 * SLOW_RULE, judged with warn 0).
 */
export const FIXED_RULES: Record<string, ThresholdRule> = {
  loop_age_ms: { warn: 1000, crit: null, invert: false, configurable: false },
  api_dropped_events: { warn: 0, crit: null, invert: false, configurable: false },
  metrics_store_errors: { warn: 0, crit: null, invert: false, configurable: false },
  stats_feed_gaps: { warn: 0, crit: null, invert: false, configurable: false },
  slow_client_disconnects: { warn: 0, crit: null, invert: false, configurable: false },
};

function unavailable(message: string): QueryError {
  return new QueryError(503, "thresholds_unavailable", message);
}

/** The rules from a parsed artifact; throws when it is not usable. */
export function rulesFromArtifact(artifact: unknown, path: string): Record<string, ThresholdRule> {
  const block = (artifact as { monitor?: { thresholds?: unknown } } | null)?.monitor?.thresholds;
  if (typeof block !== "object" || block === null) throw unavailable(`${path} has no monitor.thresholds`);
  const rules: Record<string, ThresholdRule> = {};
  for (const name of Object.keys(DEFAULT_THRESHOLDS)) {
    const band = (block as Record<string, unknown>)[name] as { warn?: unknown; crit?: unknown } | undefined;
    if (!band || !Number.isFinite(band.warn) || !Number.isFinite(band.crit)) {
      throw unavailable(`${path}: monitor.thresholds.${name} is missing or not numbers`);
    }
    rules[name] = { warn: band.warn as number, crit: band.crit as number, invert: INVERTED.includes(name), configurable: true };
  }
  return { ...rules, ...FIXED_RULES };
}

export function defaultRules(): Record<string, ThresholdRule> {
  const rules: Record<string, ThresholdRule> = {};
  for (const [name, band] of Object.entries(DEFAULT_THRESHOLDS)) {
    rules[name] = { ...band, invert: INVERTED.includes(name), configurable: true };
  }
  return { ...rules, ...FIXED_RULES };
}

export class ThresholdSource {
  private cached: { stamp: string; response: ThresholdsResponse } | null = null;

  constructor(readonly path: string) {}

  read(): ThresholdsResponse {
    let stamp: string;
    try {
      const st = statSync(this.path);
      stamp = `${st.dev}:${st.ino}:${st.mtimeMs}:${st.size}`;
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code === "ENOENT") {
        return { source: "defaults", path: this.path, rules: defaultRules() };
      }
      throw unavailable(`${this.path} cannot be read: ${(err as Error).message}`);
    }
    if (this.cached?.stamp === stamp) return this.cached.response;
    let artifact: unknown;
    try {
      artifact = JSON.parse(readFileSync(this.path, "utf8"));
    } catch (err) {
      throw unavailable(`${this.path} cannot be read: ${(err as Error).message}`);
    }
    const response: ThresholdsResponse = { source: "artifact", path: this.path, rules: rulesFromArtifact(artifact, this.path) };
    this.cached = { stamp, response };
    return response;
  }
}

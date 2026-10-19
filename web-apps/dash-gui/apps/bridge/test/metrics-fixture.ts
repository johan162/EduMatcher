/**
 * The metrics.db the history tests read, built once per test file by
 * fixtures/make_metrics_db.py through pm-monitor's own MetricsStore, so it
 * can never drift from the real schema. Needs the repo's Poetry environment,
 * as `scripts/mkbld.sh` (which runs these tests) has.
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..", "..", "..", "..", "..");

export function buildMetricsFixture(): string {
  const out = join(mkdtempSync(join(tmpdir(), "dash-metrics-")), "metrics.db");
  execFileSync("poetry", ["run", "python", join(here, "fixtures", "make_metrics_db.py"), out], {
    cwd: repoRoot,
    stdio: ["ignore", "ignore", "inherit"],
  });
  return out;
}

/** Fixture timeline start, 2026-10-19T08:00:00Z, in epoch ms. */
export const T0 = Date.parse("2026-10-19T08:00:00Z");
export const MIN = 60_000;
export const HOUR = 3_600_000;

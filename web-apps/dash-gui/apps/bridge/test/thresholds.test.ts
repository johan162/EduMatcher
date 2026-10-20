/** /api/thresholds (I113): the rules pm-monitor judges by, from the artifact or its defaults. */

import { mkdtempSync, renameSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import type { ApiError, ThresholdsResponse } from "@edumatcher/dash-types";
import { DEFAULT_THRESHOLDS, FIXED_RULES, ThresholdSource } from "../src/thresholds.js";
import { startRig, type Rig } from "./harness.js";

const dir = () => mkdtempSync(join(tmpdir(), "dash-thresholds-"));

/** An artifact as pm-config-deploy writes it: every rule present. */
function artifact(overrides: Record<string, { warn: number; crit: number }> = {}): string {
  return JSON.stringify({ meta: { schema_version: 5 }, monitor: { enabled: true, thresholds: { ...DEFAULT_THRESHOLDS, ...overrides } } });
}

let rig: Rig | undefined;
afterEach(async () => {
  await rig?.stop();
  rig = undefined;
});

describe("ThresholdSource", () => {
  it("without an artifact: pm-monitor's built-in defaults, as pm-monitor then runs", () => {
    const r = new ThresholdSource(join(dir(), "engine_config.json")).read();
    expect(r.source).toBe("defaults");
    expect(r.rules["host_cpu_pct"]).toEqual({ warn: 80, crit: 95, invert: false, configurable: true });
    expect(r.rules["disk_free_pct"]).toEqual({ warn: 15, crit: 5, invert: true, configurable: true });
    expect(r.rules["loop_age_ms"]).toEqual({ warn: 1000, crit: null, invert: false, configurable: false });
    expect(Object.keys(r.rules).sort()).toEqual([...Object.keys(DEFAULT_THRESHOLDS), ...Object.keys(FIXED_RULES)].sort());
  });

  it("with an artifact: its values, and the fixed rules beside them", () => {
    const path = join(dir(), "engine_config.json");
    writeFileSync(path, artifact({ host_cpu_pct: { warn: 70, crit: 90 } }));
    const r = new ThresholdSource(path).read();
    expect(r).toMatchObject({ source: "artifact", path });
    expect(r.rules["host_cpu_pct"]).toEqual({ warn: 70, crit: 90, invert: false, configurable: true });
    expect(r.rules["stats_feed_gaps"]).toEqual({ warn: 0, crit: null, invert: false, configurable: false });
  });

  it("follows a redeployed artifact (a new file at the path)", () => {
    const d = dir();
    const path = join(d, "engine_config.json");
    writeFileSync(path, artifact());
    const source = new ThresholdSource(path);
    expect(source.read().rules["reject_pct_5m"]!.warn).toBe(10);
    writeFileSync(join(d, "new.json"), artifact({ reject_pct_5m: { warn: 3, crit: 6 } }));
    renameSync(join(d, "new.json"), path);
    expect(source.read().rules["reject_pct_5m"]!.warn).toBe(3);
  });

  it.each([
    ["not JSON", "{ nope"],
    ["no monitor section", JSON.stringify({ meta: {} })],
    ["a rule missing", JSON.stringify({ monitor: { thresholds: { host_cpu_pct: { warn: 1, crit: 2 } } } })],
    ["a rule not numbers", artifact({ host_mem_pct: { warn: "80" as unknown as number, crit: 92 } })],
  ])("an artifact that cannot be used is an error, never quietly the defaults: %s", (_why, text) => {
    const path = join(dir(), "engine_config.json");
    writeFileSync(path, text);
    expect(() => new ThresholdSource(path).read()).toThrow(expect.objectContaining({ status: 503, code: "thresholds_unavailable" }));
  });
});

describe("GET /api/thresholds", () => {
  it("serves the rules", async () => {
    const path = join(dir(), "engine_config.json");
    writeFileSync(path, artifact({ engine_handle_p99_us: { warn: 1500, crit: 9000 } }));
    rig = await startRig({ configArtifactPath: path });
    const r = (await (await fetch(`http://127.0.0.1:${rig.port}/api/thresholds`)).json()) as ThresholdsResponse;
    expect(r.source).toBe("artifact");
    expect(r.rules["engine_handle_p99_us"]).toMatchObject({ warn: 1500, crit: 9000 });
  });

  it("says why it cannot, with a 503", async () => {
    const path = join(dir(), "engine_config.json");
    writeFileSync(path, "{ nope");
    rig = await startRig({ configArtifactPath: path });
    const res = await fetch(`http://127.0.0.1:${rig.port}/api/thresholds`);
    expect(res.status).toBe(503);
    expect(((await res.json()) as ApiError).error).toBe("thresholds_unavailable");
  });
});

import { afterEach, describe, expect, it } from "vitest";
import { loadBridgeConfig } from "../src/config.js";

const saved = { ...process.env };
afterEach(() => {
  process.env = { ...saved };
});

describe("loadBridgeConfig", () => {
  it("defaults to the dev bridge port and a local pm-monitor", () => {
    for (const k of ["PORT", "MONITOR_HOST", "MONITOR_PUB_PORT", "METRICS_DB_PATH"]) delete process.env[k];
    process.env["EDUMATCHER_DATA_DIR"] = "/srv/em";
    const cfg = loadBridgeConfig();
    expect(cfg.port).toBe(5195);
    expect(cfg.monitor).toEqual({ host: "127.0.0.1", pubPort: 5611, downAfterSec: 3 });
    expect(cfg.metricsDbPath).toBe("/srv/em/metrics.db");
    expect(cfg.logServer.failoverDir).toBe("/srv/em/logs");
    expect(cfg.logServer.clientId).toBe("pm-dash-bridge");
  });

  it("reads overrides from the environment and ignores garbage numbers", () => {
    process.env["PORT"] = "8095";
    process.env["MONITOR_HOST"] = "edumatcher";
    process.env["MONITOR_PUB_PORT"] = "not-a-number";
    process.env["METRICS_DB_PATH"] = "/backend-data/metrics.db";
    process.env["LOG_SRV_ENABLED"] = "false";
    const cfg = loadBridgeConfig();
    expect(cfg.port).toBe(8095);
    expect(cfg.monitor.host).toBe("edumatcher");
    expect(cfg.monitor.pubPort).toBe(5611);
    expect(cfg.metricsDbPath).toBe("/backend-data/metrics.db");
    expect(cfg.logServer.enabled).toBe(false);
  });
});

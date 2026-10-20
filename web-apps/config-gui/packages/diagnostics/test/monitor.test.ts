/**
 * Rules for the `monitor` block, mirroring pm-cverifier M029 (threshold
 * order), M030 (hung vs beacon interval), M031 (host reaches bind) and M018
 * (ports), plus the session time-zone check.
 */

import { describe, expect, it } from "vitest";
import {
  createApiGateway,
  createBlankDraft,
  createGateway,
  type EngineConfigDraft,
} from "@edumatcher/schema";
import { evaluateDiagnostics } from "../src/index.js";

function draft(include = true): EngineConfigDraft {
  const d = createBlankDraft();
  d.symbols = { AAPL: { tickDecimals: 2 } };
  d.symbolOrder = ["AAPL"];
  d.gateways = [createGateway("TRADER01"), createGateway("OPS01", "ADMIN")];
  d.monitor.include = include;
  return d;
}

function ids(d: EngineConfigDraft): string[] {
  return evaluateDiagnostics(d).map((x) => x.id);
}

const MONITOR_IDS = [
  "monitor-threshold-order",
  "monitor-hung-vs-interval",
  "monitor-host-unreachable",
  "monitor-ports-equal",
  "session-timezone-unknown",
];

describe("monitor", () => {
  it("the defaults raise nothing", () => {
    const found = ids(draft());
    expect(found.filter((id) => MONITOR_IDS.includes(id) || id === "port-collision" || id === "schema")).toEqual([]);
  });

  it("M029: warn must be below crit", () => {
    const d = draft();
    d.monitor.thresholds.host_cpu_pct = { warn: 95, crit: 95 };
    const diag = evaluateDiagnostics(d).find((x) => x.id === "monitor-threshold-order");
    expect(diag?.severity).toBe("error");
    expect(diag?.fieldPaths).toEqual(["monitor.thresholds.host_cpu_pct"]);
    expect(diag?.tab).toBe("monitor");
  });

  it("M029: disk_free_pct is inverted", () => {
    const d = draft();
    d.monitor.thresholds.disk_free_pct = { warn: 5, crit: 15 };
    expect(ids(d)).toContain("monitor-threshold-order");
    d.monitor.thresholds.disk_free_pct = { warn: 20, crit: 10 };
    expect(ids(d)).not.toContain("monitor-threshold-order");
  });

  it("M030: hung_after_sec must exceed the beacon interval", () => {
    const d = draft();
    d.monitor.hungAfterSec = 2;
    expect(ids(d)).toContain("monitor-hung-vs-interval");
  });

  it("M031: a host that cannot reach the bind is a warning", () => {
    const d = draft();
    d.monitor.bindAddress = "10.0.0.5";
    const diag = evaluateDiagnostics(d).find((x) => x.id === "monitor-host-unreachable");
    expect(diag?.severity).toBe("warning");
    d.monitor.bindAddress = "0.0.0.0";
    expect(ids(d)).not.toContain("monitor-host-unreachable");
    d.monitor.bindAddress = "localhost"; // both loopback
    expect(ids(d)).not.toContain("monitor-host-unreachable");
  });

  it("its own two ports must differ", () => {
    const d = draft();
    d.monitor.pullPort = d.monitor.pubPort;
    expect(ids(d)).toContain("monitor-ports-equal");
    expect(ids(d)).not.toContain("port-collision");
  });

  it("the rules apply only to a written block", () => {
    const d = draft(false);
    d.monitor.hungAfterSec = 1;
    d.monitor.thresholds.host_cpu_pct = { warn: 99, crit: 1 };
    expect(ids(d).filter((id) => id.startsWith("monitor-"))).toEqual([]);
  });

  it("its default ports collide with another listener even when not written", () => {
    const d = draft(false);
    const api = createApiGateway("main");
    api.port = 5610;
    api.host = "0.0.0.0";
    d.apiGateways = [api];
    const diag = evaluateDiagnostics(d).find((x) => x.id === "port-collision");
    expect(diag?.fieldPaths).toEqual(["monitor.pullPort", "apiGateways.main.port"]);
  });

  it("no collision when monitoring is switched off", () => {
    const d = draft(true);
    d.monitor.enabled = false;
    const api = createApiGateway("main");
    api.port = 5610;
    d.apiGateways = [api];
    expect(ids(d)).not.toContain("port-collision");
  });
});

describe("session time zone", () => {
  it("accepts an IANA name and refuses anything else", () => {
    const d = draft(false);
    d.sessionTimezone = "America/New_York";
    expect(ids(d)).not.toContain("session-timezone-unknown");
    d.sessionTimezone = "Mars/Olympus_Mons";
    expect(ids(d)).toContain("session-timezone-unknown");
  });
});

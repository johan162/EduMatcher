/**
 * LALF-PS rules for the log_server section.
 *
 * Mirrors pm-cverifier's S102 (pm-log-srv binds three ports and they must be
 * distinct) and S103 (the lease ceiling cannot sit below the default lease),
 * plus the cross-section port-collision case. See
 * docs/user-guide/280-log-srv.md for what the fields do.
 */

import { describe, expect, it } from "vitest";
import {
  createBlankDraft,
  createGateway,
  type EngineConfigDraft,
} from "@edumatcher/schema";
import { evaluateDiagnostics } from "../src/index.js";

function draftWithLogServer(): EngineConfigDraft {
  const draft = createBlankDraft();
  draft.symbols = { AAPL: { tickDecimals: 2 } };
  draft.symbolOrder = ["AAPL"];
  draft.gateways = [createGateway("TRADER01"), createGateway("OPS01", "ADMIN")];
  draft.logServer.enabled = true;
  return draft;
}

function ids(draft: EngineConfigDraft): string[] {
  return evaluateDiagnostics(draft).map((d) => d.id);
}

describe("diagnostics — log_server LALF-PS", () => {
  it("is quiet on the default configuration", () => {
    const found = ids(draftWithLogServer());
    expect(found).not.toContain("log-server-port-overlap");
    expect(found).not.toContain("log-server-lease-bounds");
    expect(found).not.toContain("port-collision");
  });

  it("errors when the PUB port sits on the LALF port", () => {
    const draft = draftWithLogServer();
    draft.logServer.pubPort = draft.logServer.port;
    const diags = evaluateDiagnostics(draft);
    const overlap = diags.find((d) => d.id === "log-server-port-overlap");
    expect(overlap?.severity).toBe("error");
    expect(overlap?.fieldPaths).toContain("logServer.pubPort");
    // Reported once, as an error — not also as a generic port-collision warning.
    expect(diags.filter((d) => d.id === "port-collision")).toHaveLength(0);
  });

  it("errors when PUB and PULL share a port", () => {
    const draft = draftWithLogServer();
    draft.logServer.pullPort = draft.logServer.pubPort;
    expect(ids(draft)).toContain("log-server-port-overlap");
  });

  it("warns when a LALF-PS port collides with another gateway", () => {
    const draft = draftWithLogServer();
    draft.marketDataGateway.enabled = true;
    draft.marketDataGateway.port = draft.logServer.pubPort;
    const collision = evaluateDiagnostics(draft).find(
      (d) => d.id === "port-collision",
    );
    expect(collision).toBeDefined();
    expect(collision?.fieldPaths).toContain("logServer.pubPort");
  });

  it("ignores LALF-PS ports for collisions once the interface is off", () => {
    const draft = draftWithLogServer();
    draft.logServer.pubsubEnabled = false;
    draft.marketDataGateway.enabled = true;
    draft.marketDataGateway.port = draft.logServer.pubPort;
    expect(ids(draft)).not.toContain("port-collision");
  });

  it("errors when the lease ceiling is below the default lease", () => {
    const draft = draftWithLogServer();
    draft.logServer.leaseSec = 60;
    draft.logServer.maxLeaseSec = 30;
    const diag = evaluateDiagnostics(draft).find(
      (d) => d.id === "log-server-lease-bounds",
    );
    expect(diag?.severity).toBe("error");
  });

  it("accepts an equal lease and ceiling", () => {
    const draft = draftWithLogServer();
    draft.logServer.leaseSec = 30;
    draft.logServer.maxLeaseSec = 30;
    expect(ids(draft)).not.toContain("log-server-lease-bounds");
  });

  it("warns when the notify interval outlives the lease", () => {
    const draft = draftWithLogServer();
    draft.logServer.leaseSec = 5;
    draft.logServer.notifyIntervalMs = 30_000;
    const diag = evaluateDiagnostics(draft).find(
      (d) => d.id === "log-server-notify-exceeds-lease",
    );
    expect(diag?.severity).toBe("warning");
  });

  it("says nothing about LALF-PS while the log server itself is disabled", () => {
    const draft = draftWithLogServer();
    draft.logServer.enabled = false;
    draft.logServer.pubPort = draft.logServer.port;
    draft.logServer.maxLeaseSec = 1;
    const found = ids(draft);
    expect(found).not.toContain("log-server-port-overlap");
    expect(found).not.toContain("log-server-lease-bounds");
  });
});

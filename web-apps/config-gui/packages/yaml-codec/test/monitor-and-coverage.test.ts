/**
 * The `monitor` block and the other sections config-gui gained with it
 * (design: docs-design/EduMatcher-Config-GUI-Monitor-Extension.md):
 * auction_indicative_interval_sec, log_server.client, the optional API
 * instance keys, and the regenerated comment-defaults header.
 */

import { describe, expect, it } from "vitest";
import yaml from "js-yaml";
import {
  MONITOR_THRESHOLD_RULES,
  createApiGateway,
  createBlankDraft,
  createGateway,
  type EngineConfigDraft,
} from "@edumatcher/schema";
import { buildConfigDocument, generateYaml, parseYamlToDraft } from "../src/index.js";

function exchange(): EngineConfigDraft {
  const draft = createBlankDraft();
  draft.symbols = { AAPL: { tickDecimals: 2 } };
  draft.symbolOrder = ["AAPL"];
  draft.gateways = [createGateway("TRADER01")];
  return draft;
}

const MINIMAL = "participants:\n    - id: TRADER01\nsymbols:\n  AAPL:\n    tick_decimals: 2\n";

describe("monitor", () => {
  it("is not written until included", () => {
    expect(buildConfigDocument(exchange()).monitor).toBeUndefined();
  });

  it("is written whole, every field, as pm-config-gen --monitor writes it", () => {
    const draft = exchange();
    draft.monitor.include = true;
    const block = buildConfigDocument(draft).monitor as Record<string, any>;
    expect(Object.keys(block)).toEqual([
      "enabled",
      "bind_address",
      "host",
      "pull_port",
      "pub_port",
      "beacon_interval_sec",
      "hung_after_sec",
      "silent_after_beacons",
      "book_metrics_interval_sec",
      "retention",
      "thresholds",
    ]);
    expect(block.retention).toEqual({ raw_hours: 6, minute_days: 7 });
    expect(Object.keys(block.thresholds)).toEqual([...MONITOR_THRESHOLD_RULES]);
    expect(block.thresholds.disk_free_pct).toEqual({ warn: 15, crit: 5 });
  });

  it("round-trips every changed field", () => {
    const draft = exchange();
    const m = draft.monitor;
    m.include = true;
    m.enabled = false;
    m.bindAddress = "0.0.0.0";
    m.host = "monitor.lan";
    m.pullPort = 6610;
    m.pubPort = 6611;
    m.beaconIntervalSec = 1.5;
    m.hungAfterSec = 8;
    m.silentAfterBeacons = 4;
    m.bookMetricsIntervalSec = 30;
    m.rawHours = 2;
    m.minuteDays = 14;
    m.thresholds.host_cpu_pct = { warn: 70, crit: 90 };
    const text = generateYaml(draft);
    expect(text).toContain("# health beacons and pm-monitor (operator dashboard)\nmonitor:");
    const { draft: back, unmapped } = parseYamlToDraft(text);
    expect(unmapped).not.toContain("monitor");
    expect(back.monitor).toEqual(m);
  });

  it("imports a partial block over the defaults", () => {
    const { draft } = parseYamlToDraft(
      MINIMAL + "monitor:\n  hung_after_sec: 9\n  thresholds:\n    reject_pct_5m: {warn: 5}\n",
    );
    expect(draft.monitor.include).toBe(true);
    expect(draft.monitor.hungAfterSec).toBe(9);
    expect(draft.monitor.beaconIntervalSec).toBe(2);
    expect(draft.monitor.thresholds.reject_pct_5m).toEqual({ warn: 5, crit: 30 });
  });
});

describe("the other sections", () => {
  it("writes auction_indicative_interval_sec only when changed, and reads it back", () => {
    const draft = exchange();
    expect(buildConfigDocument(draft).auction_indicative_interval_sec).toBeUndefined();
    draft.auctionIndicativeIntervalSec = 0.5;
    const text = generateYaml(draft);
    expect((yaml.load(text) as any).auction_indicative_interval_sec).toBe(0.5);
    expect(parseYamlToDraft(text).draft.auctionIndicativeIntervalSec).toBe(0.5);
  });

  it("writes log_server.client only when a field differs from its default", () => {
    const draft = exchange();
    draft.logServer.include = true;
    expect((buildConfigDocument(draft).log_server as any).client).toBeUndefined();
    draft.logServer.client.failoverTimeoutSec = 10;
    const doc = buildConfigDocument(draft) as any;
    expect(doc.log_server.client).toEqual({
      connect_timeout_sec: 0.5,
      failover_timeout_sec: 10,
      failover_dir: "data/logs",
    });
    expect(parseYamlToDraft(generateYaml(draft)).draft.logServer.client.failoverTimeoutSec).toBe(10);
  });

  it("writes the optional API instance keys only when set, and reads them back", () => {
    const draft = exchange();
    const gw = createApiGateway("main");
    draft.apiGateways = [gw];
    const bare = (buildConfigDocument(draft).api_gateways as any).main;
    for (const key of ["clearing_db", "market_data_cache_sec", "engine_pull_addr", "index_pub_addr"]) {
      expect(bare).not.toHaveProperty(key);
    }
    gw.clearingDb = "data/other_clearing.db";
    gw.marketDataCacheSec = 120;
    gw.enginePullAddr = "tcp://10.0.0.5:5555";
    gw.enginePubAddr = "tcp://10.0.0.5:5556";
    gw.indexPullAddr = "tcp://10.0.0.5:5559";
    gw.indexPubAddr = "tcp://10.0.0.5:5558";
    const back = parseYamlToDraft(generateYaml(draft)).draft.apiGateways[0]!;
    expect(back).toMatchObject({
      clearingDb: "data/other_clearing.db",
      marketDataCacheSec: 120,
      enginePullAddr: "tcp://10.0.0.5:5555",
      enginePubAddr: "tcp://10.0.0.5:5556",
      indexPullAddr: "tcp://10.0.0.5:5559",
      indexPubAddr: "tcp://10.0.0.5:5558",
    });
  });

  it("has no unmapped section for a file using every block", () => {
    const draft = exchange();
    draft.monitor.include = true;
    draft.logServer.include = true;
    draft.country = "Norway";
    draft.auctionIndicativeIntervalSec = 2;
    expect(parseYamlToDraft(generateYaml(draft)).unmapped).toEqual([]);
  });
});

describe("comment-defaults header", () => {
  it("is written only when asked for, and documents the new sections", () => {
    const draft = exchange();
    expect(generateYaml(draft)).not.toContain("Defaultable engine_config fields");
    draft.output.commentDefaultFields = true;
    const text = generateYaml(draft);
    expect(text).toContain("# Defaultable engine_config fields and default values:");
    expect(text).toContain("#   monitor:");
    expect(text).toContain("#   locale:");
    // every line of the header is a comment: the file still loads the same
    expect(yaml.load(text)).toEqual(yaml.load(generateYaml({ ...draft, output: { ...draft.output, commentDefaultFields: false } })));
  });
});

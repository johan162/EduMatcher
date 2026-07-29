/**
 * LALF-PS coverage for the log_server section.
 *
 * The GUI, `pm-config-gen` and `pm-log-srv` itself must all agree about the
 * twelve LALF-PS fields (docs/user-guide/280-log-srv.md). These tests pin the
 * GUI's half: the YAML it emits, the YAML it can read back, and the two
 * cross-field rules that mirror pm-cverifier's S102/S103.
 */

import { describe, expect, it } from "vitest";
import yaml from "js-yaml";
import {
  DEFAULT_LOG_SERVER,
  createBlankDraft,
  createGateway,
  engineConfigDraftSchema,
  type EngineConfigDraft,
} from "@edumatcher/schema";
import {
  buildConfigDocument,
  generateYaml,
  parseYamlToDraft,
} from "../src/index.js";

/** Snake-case keys pm-log-srv's loader reads for the LALF-PS interface. */
const PUBSUB_YAML_KEYS = [
  "pubsub_enabled",
  "pub_port",
  "pull_port",
  "lease_sec",
  "max_lease_sec",
  "max_subscribers",
  "notify_interval_ms",
  "backfill_chunk_rows",
  "max_backfill_minutes",
  "max_backfill_rows",
  "max_pending_rows",
  "pub_sndhwm",
] as const;

function draftWithLogServer(): EngineConfigDraft {
  const draft = createBlankDraft();
  draft.symbols = { AAPL: { tickDecimals: 2 } };
  draft.symbolOrder = ["AAPL"];
  draft.gateways = [createGateway("TRADER01"), createGateway("OPS01", "ADMIN")];
  draft.logServer.enabled = true;
  return draft;
}

function logServerSection(draft: EngineConfigDraft): Record<string, unknown> {
  const doc = buildConfigDocument(draft) as Record<string, unknown>;
  return doc.log_server as Record<string, unknown>;
}

describe("log_server LALF-PS defaults", () => {
  it("matches the pm-config-gen defaults", () => {
    const g = createBlankDraft().logServer;
    expect({
      pubsubEnabled: g.pubsubEnabled,
      pubPort: g.pubPort,
      pullPort: g.pullPort,
      leaseSec: g.leaseSec,
      maxLeaseSec: g.maxLeaseSec,
      maxSubscribers: g.maxSubscribers,
      notifyIntervalMs: g.notifyIntervalMs,
      backfillChunkRows: g.backfillChunkRows,
      maxBackfillMinutes: g.maxBackfillMinutes,
      maxBackfillRows: g.maxBackfillRows,
      maxPendingRows: g.maxPendingRows,
      pubSndhwm: g.pubSndhwm,
    }).toEqual({
      pubsubEnabled: true,
      pubPort: 5601,
      pullPort: 5602,
      leaseSec: 30,
      maxLeaseSec: 300,
      maxSubscribers: 32,
      notifyIntervalMs: 250,
      backfillChunkRows: 500,
      maxBackfillMinutes: 1440,
      maxBackfillRows: 100_000,
      maxPendingRows: 20_000,
      pubSndhwm: 10_000,
    });
  });

  it("occupies a contiguous three-port block by default", () => {
    const g = DEFAULT_LOG_SERVER;
    expect([g.port, g.pubPort, g.pullPort]).toEqual([5600, 5601, 5602]);
  });
});

describe("buildConfigDocument — log_server LALF-PS", () => {
  it("emits every LALF-PS key", () => {
    const section = logServerSection(draftWithLogServer());
    for (const key of PUBSUB_YAML_KEYS) {
      expect(section, `missing ${key}`).toHaveProperty(key);
    }
  });

  it("emits the ports the loader expects", () => {
    const section = logServerSection(draftWithLogServer());
    expect(section.pubsub_enabled).toBe(true);
    expect(section.pub_port).toBe(5601);
    expect(section.pull_port).toBe(5602);
  });

  it("still emits the settings when the interface is switched off", () => {
    // Otherwise toggling LALF-PS off and on again would silently discard
    // whatever ports and limits the user had configured.
    const draft = draftWithLogServer();
    draft.logServer.pubsubEnabled = false;
    draft.logServer.pubPort = 7601;
    const section = logServerSection(draft);
    expect(section.pubsub_enabled).toBe(false);
    expect(section.pub_port).toBe(7601);
  });

  it("omits log_server entirely when the section is disabled", () => {
    const draft = draftWithLogServer();
    draft.logServer.enabled = false;
    expect(buildConfigDocument(draft)).not.toHaveProperty("log_server");
  });
});

describe("parseYamlToDraft — log_server LALF-PS", () => {
  it("round-trips every field through generate → parse", () => {
    const draft = draftWithLogServer();
    Object.assign(draft.logServer, {
      pubsubEnabled: false,
      pubPort: 7601,
      pullPort: 7602,
      leaseSec: 15,
      maxLeaseSec: 120,
      maxSubscribers: 8,
      notifyIntervalMs: 500,
      backfillChunkRows: 250,
      maxBackfillMinutes: 120,
      maxBackfillRows: 50_000,
      maxPendingRows: 5_000,
      pubSndhwm: 2_000,
    });

    const { draft: reparsed } = parseYamlToDraft(generateYaml(draft));
    expect(reparsed.logServer).toEqual(draft.logServer);
  });

  it("keeps defaults for LALF-PS keys a hand-written file omits", () => {
    const text = yaml.dump({
      symbols: { AAPL: { tick_decimals: 2 } },
      gateways: { alf: [{ id: "TRADER01" }] },
      log_server: { enabled: true, port: 5600 },
    });
    const { draft } = parseYamlToDraft(text);
    expect(draft.logServer.pubsubEnabled).toBe(true);
    expect(draft.logServer.pubPort).toBe(5601);
    expect(draft.logServer.leaseSec).toBe(30);
  });

  it("reads pubsub_enabled: false rather than falling back to the default", () => {
    const text = yaml.dump({
      symbols: { AAPL: { tick_decimals: 2 } },
      gateways: { alf: [{ id: "TRADER01" }] },
      log_server: { enabled: true, pubsub_enabled: false },
    });
    const { draft } = parseYamlToDraft(text);
    expect(draft.logServer.pubsubEnabled).toBe(false);
  });
});

describe("engineConfigDraftSchema — log_server LALF-PS", () => {
  it("accepts a default draft", () => {
    expect(
      engineConfigDraftSchema.safeParse(draftWithLogServer()).success,
    ).toBe(true);
  });

  it("rejects two of the three ports sharing a number", () => {
    const draft = draftWithLogServer();
    draft.logServer.pubPort = draft.logServer.port;
    expect(engineConfigDraftSchema.safeParse(draft).success).toBe(false);
  });

  it("allows a port clash while the interface is disabled", () => {
    const draft = draftWithLogServer();
    draft.logServer.pubsubEnabled = false;
    draft.logServer.pubPort = draft.logServer.port;
    expect(engineConfigDraftSchema.safeParse(draft).success).toBe(true);
  });

  it("rejects a max lease below the default lease", () => {
    const draft = draftWithLogServer();
    draft.logServer.leaseSec = 60;
    draft.logServer.maxLeaseSec = 30;
    expect(engineConfigDraftSchema.safeParse(draft).success).toBe(false);
  });

  it("rejects a non-positive limit", () => {
    const draft = draftWithLogServer();
    draft.logServer.maxSubscribers = 0;
    expect(engineConfigDraftSchema.safeParse(draft).success).toBe(false);
  });
});

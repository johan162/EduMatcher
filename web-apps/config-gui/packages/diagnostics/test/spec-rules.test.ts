/** Rules from 990-app-config-spec.md §4–§7 that the GUI previously let through. */

import { describe, expect, it } from "vitest";
import {
  createBlankDraft,
  createGateway,
  createIndex,
  type EngineConfigDraft,
} from "@edumatcher/schema";
import { evaluateDiagnostics } from "../src/index.js";

function base(): EngineConfigDraft {
  const d = createBlankDraft();
  d.symbols = {
    AAPL: {
      tickDecimals: 2,
      lastBuyPrice: 1,
      lastSellPrice: 1,
      outstandingShares: 1,
    },
    MSFT: {
      tickDecimals: 2,
      lastBuyPrice: 1,
      lastSellPrice: 1,
      outstandingShares: 1,
    },
  };
  d.symbolOrder = ["AAPL", "MSFT"];
  d.gateways = [createGateway("TRADER01"), createGateway("OPS01", "ADMIN")];
  return d;
}

const errorIds = (d: EngineConfigDraft): string[] =>
  evaluateDiagnostics(d)
    .filter((x) => x.severity === "error")
    .map((x) => x.id);

describe("spec rules", () => {
  it("a clean draft has no errors", () => {
    expect(errorIds(base())).toEqual([]);
  });

  it("CV1: at least one gateway", () => {
    const d = base();
    d.gateways = [];
    expect(errorIds(d)).toContain("no-gateways");
  });

  it("CV2: gateway ids are unique", () => {
    const d = base();
    d.gateways.push(createGateway("TRADER01"));
    expect(errorIds(d)).toContain("duplicate-gateway-id");
  });

  it("CV14: no gateway id may prefix another", () => {
    const d = base();
    d.gateways.push(createGateway("TRADER011"));
    expect(errorIds(d)).toContain("gateway-id-prefix");
  });

  it("CV7: the default level must be defined", () => {
    const d = base();
    d.riskControls.defaultLevel = "GHOST";
    expect(errorIds(d)).toContain("undefined-default-level");
  });

  it("CV10: an index needs a non-empty description and an alphanumeric id", () => {
    const d = base();
    const idx = createIndex("EDU-1");
    idx.constituents = ["AAPL"];
    d.indices = [idx];
    const errors = evaluateDiagnostics(d).filter((x) => x.id === "schema");
    expect(errors.map((e) => e.fieldPaths[0])).toEqual(
      expect.arrayContaining(["indices.0.id", "indices.0.description"]),
    );
  });

  it("CV10: an index constituent needs outstanding_shares (an error, as the loader refuses it)", () => {
    const d = base();
    delete d.symbols.AAPL!.outstandingShares;
    const idx = createIndex("EDU");
    idx.description = "Edu";
    idx.constituents = ["AAPL"];
    d.indices = [idx];
    expect(errorIds(d)).toContain(
      "outstanding-shares-missing-for-index-constituent",
    );
  });

  it("a priced combo leg needs a price", () => {
    const d = base();
    d.combos = [
      {
        comboId: "C1",
        comboType: "AON",
        tif: "DAY",
        legs: [
          {
            symbol: "AAPL",
            side: "BUY",
            orderType: "LIMIT",
            quantity: 1,
            price: null,
          },
          { symbol: "MSFT", side: "SELL", orderType: "MARKET", quantity: 1 },
        ],
      },
    ];
    expect(errorIds(d)).toEqual(["combo-leg-price-missing"]);
  });

  it("CV15: a gateway's credentials may live in only one API instance", () => {
    const d = base();
    const cred = { apiKey: "k", gatewayId: "TRADER01", description: "" };
    d.apiGateways = [
      { ...structuredCloneApi("a"), credentials: [cred] },
      { ...structuredCloneApi("b"), credentials: [{ ...cred, apiKey: "k2" }] },
    ];
    expect(errorIds(d)).toContain("api-gateway-id-overlap");
  });

  it("an explicit quote with no price is an error (the loader refuses it)", () => {
    const d = base();
    d.gateways.push(createGateway("MM01", "MARKET_MAKER"));
    for (const s of d.symbolOrder) {
      d.symbols[s]!.marketMakerQuotes = [
        {
          gatewayId: "MM01",
          bidPrice: null,
          askPrice: 2,
          bidQty: 1,
          askQty: 1,
          tif: "DAY",
          seedOnce: true,
        },
      ];
    }
    expect(errorIds(d)).toContain("mm-quote-price-missing");
  });

  it("field ranges are errors, but only in sections that are written", () => {
    const d = base();
    d.balfGateway.heartbeatIntervalSec = 0;
    expect(errorIds(d)).not.toContain("schema"); // balf_gateway not written
    d.balfGateway.include = true;
    expect(errorIds(d)).toContain("schema");
  });

  it("a symbol-only circuit-breaker level must set its shift", () => {
    const d = base();
    d.symbols.AAPL!.circuitBreaker = {
      levels: { L9: { haltDurationNs: null } },
    };
    expect(errorIds(d)).toContain("cb-level-shift-missing");
  });
});

function structuredCloneApi(name: string) {
  return {
    name,
    enabled: true,
    host: "0.0.0.0",
    port: name === "a" ? 8080 : 8081,
    swaggerEnabled: true,
    logLevel: "info" as const,
    statsDb: "data/stats.db",
    credentials: [],
    rateLimitWritesPerSecond: 10,
    rateLimitBurst: 20,
    engineAuthSec: 3,
    engineReplySec: 3,
    waitAckSec: 3,
    orderRetentionSec: 3600,
  };
}

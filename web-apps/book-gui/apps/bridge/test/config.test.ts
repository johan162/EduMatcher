import { afterEach, describe, expect, it } from "vitest";
import { loadBridgeConfig } from "../src/config.js";
import { marketDataUrl } from "../src/server.js";
import { SymbolRefcount } from "../src/upstream/symbol-refcount.js";

const saved = { ...process.env };
afterEach(() => {
  process.env = { ...saved };
});

describe("loadBridgeConfig", () => {
  it("defaults to the dev bridge port and the dashboards gateway, with no key", () => {
    delete process.env["PORT"];
    delete process.env["API_GATEWAY_URL"];
    delete process.env["PM_BOOK_API_KEY"];
    const cfg = loadBridgeConfig();
    expect(cfg.port).toBe(5194);
    expect(cfg.apiGateway).toEqual({ baseUrl: "http://127.0.0.1:8081", apiKey: "" });
    expect(cfg.tapeMax).toBe(500);
    expect(cfg.logServer.clientId).toBe("pm-book-bridge");
  });

  it("reads overrides from the environment and ignores garbage numbers", () => {
    process.env["PORT"] = "8094";
    process.env["PM_BOOK_API_KEY"] = "key-readonly-x";
    process.env["TAPE_MAX"] = "not-a-number";
    process.env["LOG_SRV_ENABLED"] = "false";
    const cfg = loadBridgeConfig();
    expect(cfg.port).toBe(8094);
    expect(cfg.apiGateway.apiKey).toBe("key-readonly-x");
    expect(cfg.tapeMax).toBe(500);
    expect(cfg.logServer.enabled).toBe(false);
  });
});

describe("marketDataUrl", () => {
  it("derives the WebSocket URL from the REST base", () => {
    expect(marketDataUrl("http://edumatcher:8081")).toBe("ws://edumatcher:8081/api/v1/market-data");
    expect(marketDataUrl("https://gw.example/")).toBe("wss://gw.example/api/v1/market-data");
  });
});

describe("SymbolRefcount", () => {
  it("signals subscribe on the first holder and unsubscribe on the last", () => {
    const refs = new SymbolRefcount();
    expect(refs.acquire("A")).toBe(true);
    expect(refs.acquire("A")).toBe(false);
    expect(refs.release("A")).toBe(false);
    expect(refs.held()).toEqual({ A: 1 });
    expect(refs.release("A")).toBe(true);
    expect(refs.release("A")).toBe(false);
    expect(refs.held()).toEqual({});
  });
});

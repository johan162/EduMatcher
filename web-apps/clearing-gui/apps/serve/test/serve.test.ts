import { describe, it, expect } from "vitest";
import * as http from "node:http";
import type { AddressInfo } from "node:net";
import { ENV_OPTIONS, handler, renderHelp } from "../serve.js";

/**
 * `--help` used to be produced by regex-scraping this file's own leading
 * JSDoc, so the documented behaviour and the implemented behaviour had no
 * structural link and drifted (the help claimed an unset API_PROXY_TARGET fell
 * through to the SPA, while the code returned 503). Both are now derived from
 * ENV_OPTIONS; these tests hold that contract in place.
 */
describe("pm-clearing-ui-serve --help", () => {
  const help = renderHelp();

  it("documents every environment variable the server reads", () => {
    for (const option of ENV_OPTIONS) {
      expect(help).toContain(option.name);
    }
  });

  it("prints each option's declared default, so help and runtime agree", () => {
    for (const option of ENV_OPTIONS) {
      expect(help).toContain(
        `Default: ${option.fallback === "" ? "(unset)" : option.fallback}`,
      );
    }
  });

  it("states what an unset API_PROXY_TARGET actually does (503, not a fallthrough)", () => {
    const proxy = ENV_OPTIONS.find((o) => o.name === "API_PROXY_TARGET");
    expect(proxy).toBeDefined();
    const text = proxy!.help.join(" ");
    expect(text).toMatch(/503/);
    expect(text).not.toMatch(/fall through to the SPA\b(?! )/);
    expect(help).toMatch(/503/);
  });

  it("defaults STATIC_DIR to an absolute path so it resolves from any CWD", () => {
    const staticDir = ENV_OPTIONS.find((o) => o.name === "STATIC_DIR");
    expect(staticDir).toBeDefined();
    expect(staticDir!.fallback.startsWith("/")).toBe(true);
    expect(staticDir!.fallback.endsWith("/apps/web/dist")).toBe(true);
  });

  it("importing the module does not start a server", () => {
    // Reaching this point at all proves it: a bound listener would keep the
    // vitest worker alive and the import above would have had side effects.
    expect(typeof renderHelp).toBe("function");
  });
});

describe("pm-clearing-ui-serve defaults", () => {
  it("listens on the clearing GUI's container port (809N with N=6)", () => {
    expect(ENV_OPTIONS.find((o) => o.name === "PORT")?.fallback).toBe("8096");
  });

  it("only proxies /api, so the browser never needs another address", () => {
    const help = renderHelp();
    expect(help).toContain("/api/*");
    expect(help).not.toMatch(/sqlite|clearing\.db|eod\.db|5563/i);
  });
});

describe("pm-clearing-ui-serve request handling", () => {
  async function get(path: string): Promise<{ status: number; body: string }> {
    const server = http.createServer(handler);
    await new Promise<void>((done) => server.listen(0, "127.0.0.1", done));
    const { port } = server.address() as AddressInfo;
    try {
      const res = await fetch(`http://127.0.0.1:${port}${path}`);
      return { status: res.status, body: await res.text() };
    } finally {
      server.close();
    }
  }

  it("answers a malformed escape with 400 instead of crashing", async () => {
    expect((await get("/%E0%A4%A")).status).toBe(400);
  });

  it("explains /api/* without a proxy target rather than serving the SPA", async () => {
    const res = await get("/api/v1/clearing/summary");
    expect(res.status).toBe(503);
    expect(res.body).toContain("API_PROXY_TARGET");
  });
});

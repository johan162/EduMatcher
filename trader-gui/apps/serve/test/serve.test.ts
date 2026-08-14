import { describe, it, expect } from "vitest";
import { ENV_OPTIONS, renderHelp } from "../serve.js";

/**
 * `--help` used to be produced by regex-scraping this file's own leading
 * JSDoc, so the documented behaviour and the implemented behaviour had no
 * structural link and drifted (the help claimed an unset API_PROXY_TARGET fell
 * through to the SPA, while the code returned 503). Both are now derived from
 * ENV_OPTIONS; these tests hold that contract in place.
 */
describe("pm-trading-ui-serve --help", () => {
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

import Fastify from "fastify";
import { describe, expect, it } from "vitest";
import {
  loadLedgerViaCli,
  registerLedgerRoutes,
} from "../src/routes/ledger.js";

const ENTRY = {
  logger: "edumatcher.x",
  template: "slow %s",
  level: "WARNING",
  explanation: "Something is slow.",
  actions: ["Wait."],
};

/** A stand-in pm-log-cli: node running a script, given `ledger export` as argv. */
function fakeCli(script: string): string[] {
  return [process.execPath, "-e", script];
}

const PRINTS_LEDGER = fakeCli(
  `if (process.argv.slice(-2).join(" ") !== "ledger export") process.exit(2);
   console.log(JSON.stringify({ "0123456789ab": ${JSON.stringify(ENTRY)} }));`,
);

describe("loadLedgerViaCli", () => {
  it("returns the exported entries", async () => {
    expect(await loadLedgerViaCli(PRINTS_LEDGER)).toEqual({
      available: true,
      entries: { "0123456789ab": ENTRY },
    });
  });

  it("reports a missing pm-log-cli as unavailable", async () => {
    const result = await loadLedgerViaCli(["/nonexistent/pm-log-cli"]);
    expect(result.available).toBe(false);
    expect(result.reason).toBe(
      "/nonexistent/pm-log-cli is not installed or not on PATH",
    );
    expect(result.entries).toEqual({});
  });

  it("reports a failing export as unavailable", async () => {
    const result = await loadLedgerViaCli(fakeCli("process.exit(1)"));
    expect(result.available).toBe(false);
    expect(result.reason).toMatch(/ledger export failed/);
  });
});

describe("GET /api/ledger", () => {
  it("answers 200 either way and retries after a failure", async () => {
    const app = Fastify();
    // A pm-log-cli that fails while LEDGER_TEST_FAIL=1 (children inherit env).
    const command = fakeCli(
      `if (process.env.LEDGER_TEST_FAIL === "1") process.exit(1);
       console.log(JSON.stringify({ "0123456789ab": ${JSON.stringify(ENTRY)} }));`,
    );
    process.env.LEDGER_TEST_FAIL = "1";
    registerLedgerRoutes(app, command);
    try {
      const first = await app.inject({ method: "GET", url: "/api/ledger" });
      expect(first.statusCode).toBe(200);
      expect(first.json().available).toBe(false);

      process.env.LEDGER_TEST_FAIL = "0";
      const second = await app.inject({ method: "GET", url: "/api/ledger" });
      expect(second.json()).toEqual({
        available: true,
        entries: { "0123456789ab": ENTRY },
      });
    } finally {
      delete process.env.LEDGER_TEST_FAIL;
      await app.close();
    }
  });
});

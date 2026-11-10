/**
 * `GET /api/ledger` (docs-design/EduMatcher-Log-Ledger.md §5).
 *
 * The ledger ships with the Python package, so the bridge reads it from
 * `pm-log-cli ledger export` rather than keeping a second copy, the same
 * coupling `/api/diagnostics` already has. It only changes with a release, so
 * a successful export is kept for the bridge's lifetime; a failed one is not,
 * so the next request tries again. Without pm-log-cli the route still answers
 * 200 with `available: false`: the drawer then says why it has no
 * explanations, and every other view is unaffected.
 */

import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { FastifyInstance } from "fastify";
import type { LedgerEntry, LedgerResponse } from "@edumatcher/log-types";

const execFileAsync = promisify(execFile);

export async function loadLedgerViaCli(
  command: string[],
): Promise<LedgerResponse> {
  try {
    const { stdout } = await execFileAsync(
      command[0]!,
      [...command.slice(1), "ledger", "export"],
      {
        timeout: 15_000,
        maxBuffer: 16 * 1024 * 1024,
      },
    );
    return {
      available: true,
      entries: JSON.parse(stdout) as Record<string, LedgerEntry>,
    };
  } catch (err) {
    const reason =
      (err as NodeJS.ErrnoException | undefined)?.code === "ENOENT"
        ? `${command[0]} is not installed or not on PATH`
        : `${command.join(" ")} ledger export failed: ${String(err)}`;
    return { available: false, reason, entries: {} };
  }
}

export function registerLedgerRoutes(
  app: FastifyInstance,
  logCliCommand: string[],
): void {
  let loaded: LedgerResponse | null = null;
  app.get("/api/ledger", async (): Promise<LedgerResponse> => {
    if (loaded) return loaded;
    const result = await loadLedgerViaCli(logCliCommand);
    if (result.available) loaded = result;
    else app.log.warn({ reason: result.reason }, "log ledger unavailable");
    return result;
  });
}

/**
 * `GET /api/diagnostics` (design §12.2, §23 open question 1).
 *
 * Chosen resolution to the open question: shell out to
 * `pm-log-cli --format json diagnose`, so there is exactly one
 * implementation of the seven heuristics (`edumatcher.log_cli.diagnose`)
 * rather than a second, TypeScript one that would drift. This couples the
 * bridge to `pm-log-cli` being installed and on `PATH`; when it is not
 * (e.g. a minimal container image with no Python toolchain), the route
 * degrades to a 503 rather than failing the whole app — matching
 * `config-gui`'s own precedent for an optional Python-backed endpoint
 * (`/api/config/verify`, `apps/server/src/verify.ts`).
 */

import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { FastifyInstance } from "fastify";
import { ALL_HEURISTICS, type DiagnosticFinding } from "@edumatcher/log-types";

const execFileAsync = promisify(execFile);

export class LogCliUnavailableError extends Error {}

export async function runDiagnosticsViaCli(
  command: string[],
  dbPath: string,
  opts: { process?: string; since?: string },
): Promise<DiagnosticFinding[]> {
  const args = [...command.slice(1), "--db", dbPath, "--format", "json", "diagnose"];
  if (opts.process) args.push("--process", opts.process);
  if (opts.since) args.push("--since", opts.since);

  let stdout: string;
  try {
    ({ stdout } = await execFileAsync(command[0]!, args, { timeout: 15_000 }));
  } catch (err) {
    if ((err as NodeJS.ErrnoException | undefined)?.code === "ENOENT") {
      throw new LogCliUnavailableError("pm-log-cli is not installed or not on PATH");
    }
    // pm-log-cli exits 3 when it found something to report, which is the
    // normal outcome, not a failure of the call. Anything else is real.
    const out = (err as { code?: unknown; stdout?: string }).stdout;
    if ((err as { code?: unknown }).code !== 3 || typeof out !== "string") throw err;
    stdout = out;
  }

  return (JSON.parse(stdout) as { findings: DiagnosticFinding[] }).findings;
}

export function registerDiagnosticsRoutes(
  app: FastifyInstance,
  dbPath: string,
  logCliCommand: string[],
): void {
  app.get("/api/diagnostics", async (request, reply) => {
    const q = request.query as Record<string, unknown>;
    const process_ = q.process ? String(q.process) : undefined;
    const since = q.since ? String(q.since) : undefined;

    try {
      const findings = await runDiagnosticsViaCli(logCliCommand, dbPath, {
        process: process_,
        since,
      });
      const flagged = new Set(findings.map((f) => f.heuristic));
      const passedHeuristics = ALL_HEURISTICS.filter((h) => !flagged.has(h));
      return { ranAt: new Date().toISOString(), findings, passedHeuristics };
    } catch (err) {
      if (err instanceof LogCliUnavailableError) {
        return reply.status(503).send({
          error: "log_cli_unavailable",
          message:
            "pm-log-cli is not available on this deployment. Diagnostics are optional; every other view still works.",
        });
      }
      return reply.status(500).send({ error: "diagnostics_failed", message: String(err) });
    }
  });
}

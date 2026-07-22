/**
 * Optional server-side verification via `pm-cverifier` (design §11, §15).
 *
 * SECURITY: the YAML content is written to a securely-created temp file and
 * passed by path. We invoke the tool with `execFile` and a fixed argv array —
 * never a shell string — so no user-controlled content is ever interpolated
 * into a command line.
 */

import { execFile } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

export interface VerifyResult {
  available: boolean;
  exitCode: number | null;
  report: unknown;
  raw: string;
}

export class CverifierUnavailableError extends Error {}

function run(
  command: string,
  args: string[],
): Promise<{ code: number | null; stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    execFile(command, args, { timeout: 15_000, maxBuffer: 4_000_000 }, (error, stdout, stderr) => {
      if (error && (error as NodeJS.ErrnoException).code === "ENOENT") {
        reject(new CverifierUnavailableError(`Command not found: ${command}`));
        return;
      }
      // pm-cverifier exits non-zero when it finds issues; that is not a failure
      // of the call itself, so resolve with whatever it produced.
      const code =
        error && typeof (error as { code?: unknown }).code === "number"
          ? ((error as { code: number }).code)
          : 0;
      resolve({ code, stdout, stderr });
    });
  });
}

/**
 * Write `yamlText` to a temp file and run the verifier against it.
 * @throws CverifierUnavailableError when the tool is not installed.
 */
export async function verifyYaml(
  yamlText: string,
  cverifierCommand: string[],
): Promise<VerifyResult> {
  const [command, ...baseArgs] = cverifierCommand;
  if (!command) throw new CverifierUnavailableError("No verifier command configured.");

  const dir = await mkdtemp(join(tmpdir(), "edu-cverify-"));
  const filePath = join(dir, "engine_config.yaml");
  try {
    await writeFile(filePath, yamlText, "utf8");
    const { code, stdout } = await run(command, [...baseArgs, "--format", "json", filePath]);
    let report: unknown = null;
    try {
      report = JSON.parse(stdout);
    } catch {
      report = null;
    }
    return { available: true, exitCode: code, report, raw: stdout };
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

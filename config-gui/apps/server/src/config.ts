/** Server configuration read from the environment with safe defaults. */

export interface ServerConfig {
  host: string;
  port: number;
  /** Max accepted import payload in bytes (design §15: cap uploads). */
  maxImportBytes: number;
  /** Command used to invoke pm-cverifier for the optional /verify endpoint. */
  cverifierCommand: string[];
  /** Allowed CORS origin(s); "*" in dev. */
  corsOrigin: string;
  /** When set, the built frontend in this directory is served by the API (single-container mode). */
  staticDir?: string;
}

function intFromEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function loadServerConfig(): ServerConfig {
  return {
    host: process.env.HOST ?? "127.0.0.1",
    port: intFromEnv("PORT", 5175),
    maxImportBytes: intFromEnv("MAX_IMPORT_BYTES", 1_000_000),
    // Overridable so deployments can point at `poetry run pm-cverifier`, etc.
    cverifierCommand: (process.env.CVERIFIER_COMMAND ?? "pm-cverifier").split(" "),
    corsOrigin: process.env.CORS_ORIGIN ?? "*",
    staticDir: process.env.STATIC_DIR || undefined,
  };
}

/**
 * The one call surface the rest of the bridge logs through (design §17.5).
 *
 * Backed by `LalfClient` when `pm-log-srv` answered the startup probe, by
 * stdout when it did not. Either way a caller never learns which — and a
 * `pm-log-srv` outage can never block, slow, or crash the CALF uplink, the WS
 * fan-out, or request handling, which is §17.5's central requirement.
 */

import { LalfClient, isoUtc, type LogLevel } from "@edumatcher/lalf-client";
import type { BridgeConfig } from "../config.js";

export interface Logger {
  debug(logger: string, message: string): void;
  info(logger: string, message: string): void;
  warn(logger: string, message: string): void;
  error(logger: string, message: string): void;
  critical(logger: string, message: string): void;
  /** Where records are going right now — surfaced on `/api/bridge/status`. */
  destination(): string;
  close(): Promise<void>;
}

function stdoutLogger(): Logger {
  const write = (level: LogLevel, logger: string, message: string) => {
    process.stdout.write(`${isoUtc()} ${level} ${logger} - ${message}\n`);
  };
  return {
    debug: (l, m) => write("DEBUG", l, m),
    info: (l, m) => write("INFO", l, m),
    warn: (l, m) => write("WARNING", l, m),
    error: (l, m) => write("ERROR", l, m),
    critical: (l, m) => write("CRITICAL", l, m),
    destination: () => "stdout",
    close: () => Promise.resolve(),
  };
}

function lalfLogger(client: LalfClient): Logger {
  const write = (level: LogLevel, logger: string, message: string) => client.log({ level, logger, message });
  return {
    debug: (l, m) => write("DEBUG", l, m),
    info: (l, m) => write("INFO", l, m),
    warn: (l, m) => write("WARNING", l, m),
    error: (l, m) => write("ERROR", l, m),
    critical: (l, m) => write("CRITICAL", l, m),
    destination: () => (client.state === "FAILED_OVER" ? client.fallbackPath : `lalf://${client.state}`),
    close: () => client.stop(),
  };
}

/**
 * Run the startup probe and return whichever logger it justifies.
 *
 * Never throws and never blocks longer than `connectTimeoutSec`: "no log
 * server running" is a normal condition, not an error, and startup must not
 * wait on it (design §17.5 step 1).
 */
export async function createLogger(config: BridgeConfig): Promise<Logger> {
  if (!config.logServer.enabled) return stdoutLogger();

  const client = new LalfClient({
    host: config.logServer.host,
    port: config.logServer.port,
    client: config.logServer.clientId,
    instance: config.logServer.instance,
    connectTimeoutSec: config.logServer.connectTimeoutSec,
    failoverTimeoutSec: config.logServer.failoverTimeoutSec,
    queueMaxSize: config.logServer.queueMaxSize,
    failoverDir: config.logServer.failoverDir,
  });

  const attached = await client.attach().catch(() => false);
  if (!attached) {
    await client.stop();
    return stdoutLogger();
  }
  return lalfLogger(client);
}

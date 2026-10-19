/**
 * Bridge configuration, read from the environment (design §14, §15).
 *
 * Same mechanism and helper semantics as book-gui's and terminal-gui's
 * bridges, so the first-party Node backends configure and containerise the
 * same way.
 */

import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { homedir } from "node:os";
import { fileURLToPath } from "node:url";

export interface BridgeConfig {
  host: string;
  port: number;
  corsOrigin: string;
  staticDir?: string;
  maxWsClients: number;
  /** Protocol-level ping to each tab, and missed pongs before it is reaped. */
  wsPingSec: number;
  wsPingMaxMissed: number;
  /** `bufferedAmount` above which a stalled tab is closed with 1013. */
  wsMaxBufferedBytes: number;

  monitor: {
    /** Where pm-monitor's PUB socket is reachable (`monitor.host`). */
    host: string;
    /** `monitor.pub_port`. */
    pubPort: number;
    /** No snapshot for this long → DOWN (pm-monitor publishes at 1 Hz). */
    downAfterSec: number;
  };

  /** pm-monitor's history, opened read-only. */
  metricsDbPath: string;
  /**
   * `monitor.retention.raw_hours`: ranges up to this read every 10 s sample,
   * longer ones the one-minute roll-up. Set it to what pm-monitor keeps.
   */
  rawHours: number;

  logServer: {
    enabled: boolean;
    host: string;
    port: number;
    clientId: string;
    instance?: string;
    connectTimeoutSec: number;
    failoverTimeoutSec: number;
    queueMaxSize: number;
    failoverDir: string;
  };
}

// Mirrors edumatcher.config._resolve_data_dir()'s priority order so the bridge
// and the Python processes agree on where metrics.db and `logs/` live. This
// file sits five levels below the repo root when run from the source tree;
// the container always sets METRICS_DB_PATH and LOG_FAILOVER_DIR explicitly.
const thisFileDir = dirname(fileURLToPath(import.meta.url));
const repoSrcDir = join(resolve(thisFileDir, "..", "..", "..", "..", ".."), "src");

function resolveDataDir(): string {
  const envDir = process.env["EDUMATCHER_DATA_DIR"];
  if (envDir) return resolve(envDir.replace(/^~/, homedir()));
  if (existsSync(repoSrcDir)) return join(repoSrcDir, "data");
  return join(homedir(), ".local", "share", "edumatcher");
}

function intFromEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function floatFromEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  const parsed = Number.parseFloat(raw);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function boolFromEnv(name: string, fallback: boolean): boolean {
  const raw = process.env[name]?.toLowerCase();
  if (raw === undefined || raw === "") return fallback;
  return raw === "1" || raw === "true" || raw === "yes";
}

export function loadBridgeConfig(): BridgeConfig {
  const dataDir = resolveDataDir();
  return {
    host: process.env["HOST"] ?? "127.0.0.1",
    port: intFromEnv("PORT", 5195),
    corsOrigin: process.env["CORS_ORIGIN"] ?? "*",
    staticDir: process.env["STATIC_DIR"] || undefined,
    maxWsClients: intFromEnv("MAX_WS_CLIENTS", 200),
    wsPingSec: intFromEnv("WS_PING_SEC", 10),
    wsPingMaxMissed: intFromEnv("WS_PING_MAX_MISSED", 2),
    wsMaxBufferedBytes: intFromEnv("WS_MAX_BUFFERED_BYTES", 5_000_000),

    monitor: {
      // monitor.host / monitor.pub_port defaults (MonitorConfig).
      host: process.env["MONITOR_HOST"] ?? "127.0.0.1",
      pubPort: intFromEnv("MONITOR_PUB_PORT", 5611),
      downAfterSec: floatFromEnv("MONITOR_DOWN_AFTER_SEC", 3),
    },

    metricsDbPath: process.env["METRICS_DB_PATH"] ?? join(dataDir, "metrics.db"),
    rawHours: intFromEnv("MONITOR_RAW_HOURS", 6),

    logServer: {
      enabled: boolFromEnv("LOG_SRV_ENABLED", true),
      host: process.env["LOG_SRV_HOST"] ?? "127.0.0.1",
      port: intFromEnv("LOG_SRV_PORT", 5600),
      clientId: process.env["LOG_SRV_CLIENT_ID"] ?? "pm-dash-bridge",
      instance: process.env["LOG_SRV_INSTANCE"] || undefined,
      connectTimeoutSec: floatFromEnv("LOG_CONNECT_TIMEOUT_SEC", 0.5),
      failoverTimeoutSec: floatFromEnv("LOG_FAILOVER_TIMEOUT_SEC", 30),
      queueMaxSize: intFromEnv("LOG_QUEUE_MAXSIZE", 2000),
      failoverDir: process.env["LOG_FAILOVER_DIR"] ?? join(dataDir, "logs"),
    },
  };
}

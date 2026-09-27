/**
 * Bridge configuration, read from the environment (design §10).
 *
 * Same mechanism and helper semantics as terminal-gui's bridge, so both
 * first-party Node backends configure and containerise the same way.
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
  /** Cadence of the `bridge_status` heartbeat to every tab. */
  wsHeartbeatSec: number;
  /** Protocol-level ping to each tab, and missed pongs before it is reaped. */
  wsPingSec: number;
  wsPingMaxMissed: number;
  /** `bufferedAmount` above which a stalled tab is closed with 1013. */
  wsMaxBufferedBytes: number;

  apiGateway: {
    /** `pm-api-gwy` base URL; the market-data WebSocket URL is derived from it. */
    baseUrl: string;
    /** Read-only (`gateway_id: null`) key. Never serialised to a browser. */
    apiKey: string;
  };

  upstream: {
    pingSec: number;
    pingMaxMissed: number;
    /** How long RECONNECTING may last before the state is reported DOWN. */
    downAfterSec: number;
  };

  /** Trades kept per watched symbol for the TRADES panel. */
  tapeMax: number;

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
// and the Python processes agree on where `logs/` lives. This file sits five
// levels below the repo root when run from the source tree; the container
// always sets LOG_FAILOVER_DIR explicitly.
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
  return {
    host: process.env["HOST"] ?? "127.0.0.1",
    port: intFromEnv("PORT", 5194),
    corsOrigin: process.env["CORS_ORIGIN"] ?? "*",
    staticDir: process.env["STATIC_DIR"] || undefined,
    maxWsClients: intFromEnv("MAX_WS_CLIENTS", 200),
    wsHeartbeatSec: intFromEnv("WS_HEARTBEAT_SEC", 5),
    wsPingSec: intFromEnv("WS_PING_SEC", 10),
    wsPingMaxMissed: intFromEnv("WS_PING_MAX_MISSED", 2),
    wsMaxBufferedBytes: intFromEnv("WS_MAX_BUFFERED_BYTES", 5_000_000),

    apiGateway: {
      // 8081 is the "dashboards" instance, where the bundled examples issue
      // the read-only credential; a key from "desk" (8080) is not accepted there.
      baseUrl: process.env["API_GATEWAY_URL"] ?? "http://127.0.0.1:8081",
      apiKey: process.env["PM_BOOK_API_KEY"] ?? "",
    },

    upstream: {
      pingSec: intFromEnv("UPSTREAM_PING_SEC", 10),
      pingMaxMissed: intFromEnv("UPSTREAM_PING_MAX_MISSED", 3),
      downAfterSec: intFromEnv("UPSTREAM_DOWN_AFTER_SEC", 30),
    },

    tapeMax: intFromEnv("TAPE_MAX", 500),

    logServer: {
      enabled: boolFromEnv("LOG_SRV_ENABLED", true),
      host: process.env["LOG_SRV_HOST"] ?? "127.0.0.1",
      port: intFromEnv("LOG_SRV_PORT", 5600),
      clientId: process.env["LOG_SRV_CLIENT_ID"] ?? "pm-book-bridge",
      instance: process.env["LOG_SRV_INSTANCE"] || undefined,
      connectTimeoutSec: floatFromEnv("LOG_CONNECT_TIMEOUT_SEC", 0.5),
      failoverTimeoutSec: floatFromEnv("LOG_FAILOVER_TIMEOUT_SEC", 30),
      queueMaxSize: intFromEnv("LOG_QUEUE_MAXSIZE", 2000),
      failoverDir: process.env["LOG_FAILOVER_DIR"] ?? join(resolveDataDir(), "logs"),
    },
  };
}

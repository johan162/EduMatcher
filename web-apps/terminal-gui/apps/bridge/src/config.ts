/**
 * Bridge configuration, read from the environment.
 *
 * Design §19 specifies a YAML file; this uses environment variables instead,
 * matching `log-gui/apps/bridge/src/config.ts` so both first-party Node
 * backends configure and containerise the same way. Field names and defaults
 * still mirror §19's block one-for-one.
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
  /**
   * Browser-facing liveness (design review H4). `bridge_status` is
   * broadcast on this cadence, in addition to on CALF state change, so a
   * silent tab can tell a healthy-but-quiet feed from a half-open socket.
   * Excluded from `MARKET_DATA_FRAMES`, so it never resets a data-age clock.
   */
  wsHeartbeatIntervalSec: number;
  /**
   * Protocol-level `ping` cadence to each browser tab, and the number of
   * consecutive missed `pong`s before the bridge terminates the socket.
   * Reaps a half-open tab that never fires TCP `close`, which would
   * otherwise hold its CALF subscriptions and count toward
   * `maxWsClients` until the OS timeout (design review H4).
   */
  wsPingIntervalSec: number;
  wsPingMaxMissed: number;
  /**
   * `bufferedAmount` (bytes) above which a tab is treated as stalled and
   * closed with 1013, rather than left to accumulate outbound frames in
   * bridge memory indefinitely (design review H4).
   */
  wsMaxBufferedBytes: number;

  calf: {
    host: string;
    port: number;
    clientId: string;
    /**
     * Keepalive cadence. The gateway's idle timer advances only on inbound
     * client bytes — its own outbound `HB` does not reset it — so a bridge
     * that merely listens is disconnected after `idle_timeout_sec`
     * (default 300). Design §17 never mentions this; without it the terminal
     * would silently drop every five minutes.
     */
    pingIntervalSec: number;
    /** Index ids to `SUB|CH=INDEX` for. CALF has no "list the indexes" request. */
    indexIds: string[];
  };

  apiGateway: {
    baseUrl: string;
    /** Read-only (`gateway_id: null`) key. Never serialised to a browser. */
    apiKey: string;
  };

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
// and the Python processes agree on where `logs/` lives without either side
// configuring the other. This file sits five levels below the repo root in
// every way the bridge is run (tsx in dev; the container always sets the paths
// explicitly and never reaches the source-tree branch).
const thisFileDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(thisFileDir, "..", "..", "..", "..", "..");
const repoSrcDir = join(repoRoot, "src");

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

function csvFromEnv(name: string): string[] {
  return (process.env[name] ?? "")
    .split(",")
    .map((token) => token.trim().toUpperCase())
    .filter((token) => token.length > 0);
}

export function loadBridgeConfig(): BridgeConfig {
  return {
    host: process.env["HOST"] ?? "127.0.0.1",
    port: intFromEnv("PORT", 5190),
    corsOrigin: process.env["CORS_ORIGIN"] ?? "*",
    staticDir: process.env["STATIC_DIR"] || undefined,
    maxWsClients: intFromEnv("MAX_WS_CLIENTS", 200),
    wsHeartbeatIntervalSec: intFromEnv("WS_HEARTBEAT_INTERVAL_SEC", 5),
    wsPingIntervalSec: intFromEnv("WS_PING_INTERVAL_SEC", 10),
    wsPingMaxMissed: intFromEnv("WS_PING_MAX_MISSED", 2),
    wsMaxBufferedBytes: intFromEnv("WS_MAX_BUFFERED_BYTES", 5_000_000),

    calf: {
      host: process.env["CALF_HOST"] ?? "127.0.0.1",
      port: intFromEnv("CALF_PORT", 5570),
      clientId: process.env["CALF_CLIENT_ID"] ?? "pm-terminal-bridge",
      pingIntervalSec: intFromEnv("CALF_PING_INTERVAL_SEC", 60),
      indexIds: csvFromEnv("INDEX_IDS"),
    },

    apiGateway: {
      // 8081 is the "dashboards" instance: the read-only credential this
      // bridge uses (gateway_id: null) is issued there, not on "desk" (8080).
      baseUrl: process.env["API_GATEWAY_URL"] ?? "http://127.0.0.1:8081",
      apiKey: process.env["PM_TERMINAL_API_KEY"] ?? "",
    },

    logServer: {
      enabled: boolFromEnv("LOG_SRV_ENABLED", true),
      host: process.env["LOG_SRV_HOST"] ?? "127.0.0.1",
      port: intFromEnv("LOG_SRV_PORT", 5600),
      clientId: process.env["LOG_SRV_CLIENT_ID"] ?? "pm-terminal-bridge",
      instance: process.env["LOG_SRV_INSTANCE"] || undefined,
      connectTimeoutSec: floatFromEnv("LOG_CONNECT_TIMEOUT_SEC", 0.5),
      failoverTimeoutSec: floatFromEnv("LOG_FAILOVER_TIMEOUT_SEC", 30),
      queueMaxSize: intFromEnv("LOG_QUEUE_MAXSIZE", 2000),
      failoverDir: process.env["LOG_FAILOVER_DIR"] ?? join(resolveDataDir(), "logs"),
    },
  };
}

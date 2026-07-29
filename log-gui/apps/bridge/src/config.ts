/** Bridge configuration read from the environment (design §20). */

import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { homedir } from "node:os";
import { LOG_LEVELS, type LogLevel } from "@edumatcher/log-types";

export interface BridgeConfig {
  host: string;
  port: number;
  corsOrigin: string;
  staticDir?: string;

  lalfPs: {
    host: string;
    pubPort: number;
    pullPort: number;
    subIdPrefix: string;
    leaseSec: number;
  };
  logDb: {
    path: string;
  };
  ackStore: {
    path: string;
  };
  issues: {
    retentionDays: number;
    minLevel: LogLevel;
    alertLevel: LogLevel;
  };
  thresholds: {
    errorRateNormalPerMin: number;
    errorRateElevatedPerMin: number;
    errorRateSeverePerMin: number;
    processSilenceSec: number;
  };
  limits: {
    queryMaxRows: number;
    exportMaxRows: number;
    liveBatchThresholdPerSec: number;
  };
}

// Mirrors edumatcher.config._resolve_data_dir()'s priority order exactly
// (EDUMATCHER_DATA_DIR env var, then source-tree <repo>/src/data, then an
// installed-package home-directory fallback) so the bridge and pm-log-srv
// agree on log.db's location without either side needing to configure the
// other — see the v1.1.0 design-doc changelog for why this matters (§20).
//
// This file lives at <repo>/log-gui/apps/bridge/src/config.ts, four levels
// below the repo root, in every way this bridge is ever run (dev via tsx,
// or the production container, which never reaches this branch at all
// since its Dockerfile always sets LOG_DB_PATH/ACK_STORE_PATH explicitly) —
// so that fixed relative distance is safe to hard-code, unlike a typical
// compiled-output path that can shift between dev and build.
//
// The Python side's "source tree?" check is structural (does <repo>/src
// exist as a directory at all), not "does src/data exist yet" — mirrored
// here by checking for <repo>/src itself, so a first-ever run before
// anything has written to src/data still resolves to the same place
// pm-log-srv would pick, rather than falling through to the home
// directory just because nothing has been created there yet.
const _thisFileDir = dirname(fileURLToPath(import.meta.url));
const _repoRoot = resolve(_thisFileDir, "..", "..", "..", "..");
const _repoSrcDir = join(_repoRoot, "src");

function resolveDataDir(): string {
  const envDir = process.env.EDUMATCHER_DATA_DIR;
  if (envDir) return resolve(envDir.replace(/^~/, homedir()));
  if (existsSync(_repoSrcDir)) return join(_repoSrcDir, "data");
  return join(homedir(), ".local", "share", "edumatcher");
}

function intFromEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

/** Validates against the real `LogLevel` enum rather than trusting the env var. */
function logLevelFromEnv(name: string, fallback: LogLevel): LogLevel {
  const raw = process.env[name]?.toUpperCase();
  return raw && (LOG_LEVELS as readonly string[]).includes(raw) ? (raw as LogLevel) : fallback;
}

export function loadBridgeConfig(): BridgeConfig {
  return {
    host: process.env.HOST ?? "127.0.0.1",
    port: intFromEnv("PORT", 8091),
    corsOrigin: process.env.CORS_ORIGIN ?? "*",
    staticDir: process.env.STATIC_DIR || undefined,

    lalfPs: {
      host: process.env.LOG_SRV_HOST ?? "127.0.0.1",
      pubPort: intFromEnv("LOG_SRV_PUB_PORT", 5601),
      pullPort: intFromEnv("LOG_SRV_PULL_PORT", 5602),
      subIdPrefix: process.env.SUB_ID_PREFIX ?? "pm-log-bridge",
      leaseSec: intFromEnv("LEASE_SEC", 30),
    },
    logDb: {
      path: process.env.LOG_DB_PATH ?? join(resolveDataDir(), "log.db"),
    },
    ackStore: {
      path: process.env.ACK_STORE_PATH ?? join(resolveDataDir(), "log-ui-acks.db"),
    },
    issues: {
      retentionDays: intFromEnv("ISSUES_RETENTION_DAYS", 7),
      minLevel: logLevelFromEnv("ISSUES_MIN_LEVEL", "WARNING"),
      alertLevel: logLevelFromEnv("ISSUES_ALERT_LEVEL", "ERROR"),
    },
    thresholds: {
      errorRateNormalPerMin: intFromEnv("ERROR_RATE_NORMAL_PER_MIN", 5),
      errorRateElevatedPerMin: intFromEnv("ERROR_RATE_ELEVATED_PER_MIN", 20),
      errorRateSeverePerMin: intFromEnv("ERROR_RATE_SEVERE_PER_MIN", 100),
      processSilenceSec: intFromEnv("PROCESS_SILENCE_SEC", 30),
    },
    limits: {
      queryMaxRows: intFromEnv("QUERY_MAX_ROWS", 5000),
      exportMaxRows: intFromEnv("EXPORT_MAX_ROWS", 1_000_000),
      liveBatchThresholdPerSec: intFromEnv("LIVE_BATCH_THRESHOLD_PER_SEC", 50),
    },
  };
}

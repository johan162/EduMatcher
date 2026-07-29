/**
 * Compiles a `LogFilter` to a parameterised SQL `WHERE` clause + params.
 *
 * Mirrors `edumatcher.log_srv.pubsub.LogFilter.sql_where()` and
 * `edumatcher.log_cli.queries.query_events()` closely enough to be reviewed
 * side by side (design §5.2, §16.2).
 *
 * The one property that matters most (design §19): **every user-supplied
 * value is a bound `?` parameter — nothing is ever interpolated into the SQL
 * string.** Column names and directions come only from fixed allow-lists
 * below, never from caller input.
 */

import type { LogFilter, LogLevel } from "@edumatcher/log-types";
import { LOG_LEVELS } from "@edumatcher/log-types";

const LEVEL_ORDER: Record<LogLevel, number> = {
  DEBUG: 10,
  INFO: 20,
  WARNING: 30,
  ERROR: 40,
  CRITICAL: 50,
};

function allowedLevels(minLevel?: LogLevel): LogLevel[] {
  if (!minLevel) return [];
  const floor = LEVEL_ORDER[minLevel];
  return LOG_LEVELS.filter((level) => LEVEL_ORDER[level] >= floor);
}

export interface CompiledWhere {
  /** e.g. "WHERE a = ? AND b = ?", or "" when the filter has no predicates. */
  whereSql: string;
  params: unknown[];
}

/**
 * Compile a `LogFilter` to a `WHERE` clause. `seqAfter` adds `seq > ?`
 * (used by the live-tail gap-fill and cursor pagination); `extraLevels`
 * lets a caller pass explicit `levels` instead of `minLevel` (Alerts view,
 * design §11.5, which filters by exact `ERROR+` rather than a floor computed
 * client-side — though in practice `minLevel` covers both).
 */
export function compileWhere(
  filter: LogFilter,
  opts: { seqAfter?: number; seqBefore?: number } = {},
): CompiledWhere {
  const clauses: string[] = [];
  const params: unknown[] = [];

  const levels = allowedLevels(filter.minLevel);
  if (levels.length > 0) {
    clauses.push(`level IN (${levels.map(() => "?").join(",")})`);
    params.push(...levels);
  }
  if (filter.processes && filter.processes.length > 0) {
    clauses.push(`process IN (${filter.processes.map(() => "?").join(",")})`);
    params.push(...filter.processes);
  }
  if (filter.sessions && filter.sessions.length > 0) {
    clauses.push(`session IN (${filter.sessions.map(() => "?").join(",")})`);
    params.push(...filter.sessions);
  }
  if (filter.loggers && filter.loggers.length > 0) {
    clauses.push(
      "(" + filter.loggers.map(() => "logger LIKE ?").join(" OR ") + ")",
    );
    for (const prefix of filter.loggers) params.push(`${prefix}%`);
  }
  if (filter.exceptionsOnly) {
    clauses.push("has_exception = 1");
  }
  if (filter.contains) {
    clauses.push("LOWER(message) LIKE ?");
    params.push(`%${filter.contains.toLowerCase()}%`);
  }
  if (filter.from) {
    clauses.push("client_ts >= ?");
    params.push(filter.from);
  }
  if (filter.to) {
    clauses.push("client_ts <= ?");
    params.push(filter.to);
  }
  if (opts.seqAfter !== undefined) {
    clauses.push("seq > ?");
    params.push(opts.seqAfter);
  }
  if (opts.seqBefore !== undefined) {
    clauses.push("seq < ?");
    params.push(opts.seqBefore);
  }

  return {
    whereSql: clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "",
    params,
  };
}

/** Fixed allow-list — sort direction must never come from request input. */
export type SortDirection = "ASC" | "DESC";

export function compileOrderLimit(
  direction: SortDirection,
  limit: number,
): { sql: string; params: unknown[] } {
  const dir: SortDirection = direction === "ASC" ? "ASC" : "DESC";
  const safeLimit = Number.isFinite(limit) && limit > 0 ? Math.floor(limit) : 200;
  return { sql: `ORDER BY seq ${dir} LIMIT ?`, params: [safeLimit] };
}

/**
 * Evaluates a `LogFilter` against an already-received row (design §6.5, §9.3).
 *
 * Mirrors `edumatcher.log_srv.pubsub.LogFilter.matches` / `_row_matches`, but
 * this is the *in-bridge, per-tab* evaluation — the upstream LALF-PS
 * subscription itself carries no filter (§6.4), so every tab's predicate is
 * applied here against the same received row.
 */

import type { LogFilter, LogLevel, LogRow } from "@edumatcher/log-types";

const LEVEL_ORDER: Record<LogLevel, number> = {
  DEBUG: 10,
  INFO: 20,
  WARNING: 30,
  ERROR: 40,
  CRITICAL: 50,
};

export function rowMatchesFilter(row: LogRow, filter: LogFilter): boolean {
  if (filter.minLevel && LEVEL_ORDER[row.level] < LEVEL_ORDER[filter.minLevel]) return false;
  if (filter.processes && filter.processes.length > 0 && !filter.processes.includes(row.process)) {
    return false;
  }
  if (filter.sessions && filter.sessions.length > 0 && !filter.sessions.includes(row.session)) {
    return false;
  }
  if (filter.loggers && filter.loggers.length > 0) {
    if (!filter.loggers.some((prefix) => row.logger.startsWith(prefix))) return false;
  }
  if (filter.exceptionsOnly && !row.has_exception) return false;
  if (filter.contains && !row.message.toLowerCase().includes(filter.contains.toLowerCase())) {
    return false;
  }
  return true;
}

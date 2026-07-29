/**
 * Shared row/filter types (design §9.3, §16.2, §16.3).
 *
 * Mirrors the `log_events` columns exactly (src/edumatcher/log_srv/schema.py)
 * and the LALF-PS JSON row shape (src/edumatcher/log_srv/pubsub.py
 * `row_to_dict`), so a `LogRow` means the same thing whether it arrived over
 * `GET /api/logs` or a WS `event` frame.
 */

export type LogLevel = "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";

export const LOG_LEVELS: readonly LogLevel[] = [
  "DEBUG",
  "INFO",
  "WARNING",
  "ERROR",
  "CRITICAL",
];

export interface LogRow {
  seq: number;
  client_ts: string;
  server_ts: string;
  process: string;
  instance: string | null;
  pid: number;
  host: string;
  session: string;
  level: LogLevel;
  logger: string;
  module: string | null;
  line: number | null;
  has_exception: boolean;
  truncated: boolean;
  message: string;
}

/**
 * One filter object drives both the historical query (compiled to SQL by
 * `@edumatcher/log-query`) and the live tail (evaluated in-bridge against the
 * same fields the LALF-PS `LogFilter` already carries) — design §9.3.
 *
 * `from`/`to` have no LALF-PS equivalent (the live path has no notion of a
 * time range beyond "now"); they only apply to the historical query.
 */
export interface LogFilter {
  minLevel?: LogLevel;
  processes?: string[];
  loggers?: string[];
  sessions?: string[];
  contains?: string;
  exceptionsOnly?: boolean;
  from?: string;
  to?: string;
}

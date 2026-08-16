/**
 * Aggregate query builders backing `/api/stats/*` (design §8.5, §16.2).
 *
 * These return SQL text + bound params for the caller (the bridge's
 * `log-db.ts`) to execute against its read-only `log.db` connection. Bucket
 * boundaries are computed as `strftime` expressions since `node:sqlite`/
 * `better-sqlite3` both expose SQLite's own `strftime`, keeping bucketing in
 * SQL rather than JS (design §17: "Bucketed in SQL, not in JS").
 */

import { compileWhere, type SqlParam } from "./filter-to-sql.js";
import type { LogFilter } from "@edumatcher/log-types";

export type BucketSize = "1m" | "5m" | "1h";

export const BUCKET_SECONDS: Record<BucketSize, number> = {
  "1m": 60,
  "5m": 300,
  "1h": 3600,
};

/**
 * Timeseries query: counts per bucket, optionally grouped by level/process.
 * `bucket` and `groupBy` are fixed allow-listed enums, never raw strings from
 * a request, so there is no injection surface even though they end up in the
 * generated SQL text.
 *
 * Bucket boundaries are computed by flooring the row's Unix epoch seconds to
 * a multiple of the bucket size, then formatting that back to an ISO minute
 * — this is what makes an arbitrary 5-minute bucket possible in pure SQL
 * (`strftime`'s format string can select a calendar unit like a minute or an
 * hour, but not an arbitrary multiple of one).
 */
export function buildTimeseriesQuery(
  filter: LogFilter,
  bucket: BucketSize,
  groupBy: "level" | "process" | null,
): { sql: string; params: SqlParam[] } {
  const { whereSql, params } = compileWhere(filter);
  const bucketSeconds = BUCKET_SECONDS[bucket];
  const groupCol = groupBy === "level" ? "level" : groupBy === "process" ? "process" : null;

  const selectGroup = groupCol ? `, ${groupCol} AS grp` : "";
  const groupByGroup = groupCol ? `, ${groupCol}` : "";
  const bucketExpr = `strftime('%Y-%m-%dT%H:%M:%SZ', (CAST(strftime('%s', client_ts) AS INTEGER) / ${bucketSeconds}) * ${bucketSeconds}, 'unixepoch')`;

  const sql = `
    SELECT ${bucketExpr} AS bucket_start${selectGroup}, COUNT(*) AS n
    FROM log_events
    ${whereSql}
    GROUP BY bucket_start${groupByGroup}
    ORDER BY bucket_start ASC
  `;
  return { sql, params };
}

export function buildByLevelQuery(filter: LogFilter): { sql: string; params: SqlParam[] } {
  const { whereSql, params } = compileWhere(filter);
  const sql = `
    SELECT level, COUNT(*) AS n
    FROM log_events
    ${whereSql}
    GROUP BY level
    ORDER BY n DESC
  `;
  return { sql, params };
}

export function buildByProcessQuery(filter: LogFilter): { sql: string; params: SqlParam[] } {
  const { whereSql, params } = compileWhere(filter);
  const sql = `
    SELECT process, COUNT(*) AS n
    FROM log_events
    ${whereSql}
    GROUP BY process
    ORDER BY n DESC
  `;
  return { sql, params };
}

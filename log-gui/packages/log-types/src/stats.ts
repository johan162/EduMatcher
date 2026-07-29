/**
 * Aggregate/summary shapes served by `GET /api/stats/*` (design §8.5, §16.2).
 * Mirror `edumatcher.log_cli.queries.query_stats` and the `processes` table.
 */

export interface StatsSummary {
  server: {
    started_at: string | null;
    total_log_events: number;
    total_connections: number;
    total_truncated: number;
    total_errors_sent: number;
  };
  totalRows: number;
  perLevel: Array<{ level: string; n: number }>;
  perProcess: Array<{ process: string; n: number }>;
  dbSizeBytes: number;
  dbPath: string;
  oldestClientTs: string | null;
}

export interface TimeseriesBucket {
  bucketStart: string;
  /** Present when `group_by` was omitted. */
  count?: number;
  /** Present when `group_by=level` or `group_by=process`. */
  groups?: Record<string, number>;
}

export interface TimeseriesResponse {
  window: string;
  bucketSeconds: number;
  groupBy: "level" | "process" | null;
  buckets: TimeseriesBucket[];
}

export interface ByLevelResponse {
  window: string;
  levels: Array<{ level: string; n: number }>;
}

export interface ByProcessResponse {
  window: string;
  level: string | null;
  processes: Array<{ process: string; n: number }>;
}

export interface ProcessRow {
  process: string;
  instance: string | null;
  pid: number;
  host: string;
  session: string;
  connected_at: string;
  last_seen_at: string;
  disconnected_at: string | null;
  log_count: number;
  errorCount: number;
}

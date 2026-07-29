/**
 * Read-only handle onto `log.db` (design §4.4, §6.4, §19).
 *
 * Opened with `readOnly: true` — node:sqlite's equivalent of
 * `edumatcher.log_srv.schema.open_db(..., read_only=True)`'s `mode=ro` URI
 * open. This is what makes "the bridge never writes to log.db" an enforced
 * property rather than a convention (§19).
 */

import { DatabaseSync } from "node:sqlite";
import {
  BUCKET_SECONDS,
  buildByLevelQuery,
  buildByProcessQuery,
  buildTimeseriesQuery,
  compileOrderLimit,
  compileWhere,
  isValidWindow,
  windowToIsoFrom,
  type BucketSize,
} from "@edumatcher/log-query";
import type {
  ByLevelResponse,
  ByProcessResponse,
  LogFilter,
  LogRow,
  ProcessRow,
  StatsSummary,
  TimeseriesBucket,
  TimeseriesResponse,
} from "@edumatcher/log-types";
import { existsSync, statSync } from "node:fs";

const QUERY_COLUMNS = [
  "seq",
  "client_ts",
  "server_ts",
  "process",
  "instance",
  "pid",
  "host",
  "session",
  "level",
  "logger",
  "module",
  "line",
  "has_exception",
  "truncated",
  "message",
] as const;

function rowToLogRow(raw: Record<string, unknown>): LogRow {
  return {
    seq: Number(raw.seq),
    client_ts: String(raw.client_ts),
    server_ts: String(raw.server_ts),
    process: String(raw.process),
    instance: raw.instance == null ? null : String(raw.instance),
    pid: Number(raw.pid),
    host: String(raw.host),
    session: String(raw.session),
    level: String(raw.level) as LogRow["level"],
    logger: String(raw.logger),
    module: raw.module == null ? null : String(raw.module),
    line: raw.line == null ? null : Number(raw.line),
    has_exception: Boolean(raw.has_exception),
    truncated: Boolean(raw.truncated),
    message: String(raw.message),
  };
}

export class LogDb {
  private db: DatabaseSync | null = null;
  private lastError: string | null = null;

  constructor(private readonly path: string) {}

  /** Attempts to (re-)open the database. Safe to call repeatedly. */
  open(): boolean {
    if (this.db) return true;
    if (!existsSync(this.path)) {
      this.lastError = `log.db not found at ${this.path}`;
      return false;
    }
    try {
      this.db = new DatabaseSync(this.path, { readOnly: true });
      this.lastError = null;
      return true;
    } catch (err) {
      this.lastError = err instanceof Error ? err.message : String(err);
      this.db = null;
      return false;
    }
  }

  get health(): { ok: boolean; detail: string } {
    if (this.db) return { ok: true, detail: "connected" };
    return { ok: false, detail: this.lastError ?? "not connected" };
  }

  private ensure(): DatabaseSync {
    if (!this.db && !this.open()) {
      throw new Error(this.lastError ?? "log.db unavailable");
    }
    return this.db!;
  }

  maxSeq(): number {
    const row = this.ensure()
      .prepare("SELECT COALESCE(MAX(seq), 0) AS m FROM log_events")
      .get() as { m: number };
    return row.m;
  }

  queryEvents(
    filter: LogFilter,
    opts: { seqAfter?: number; seqBefore?: number; limit: number; direction: "ASC" | "DESC" },
  ): LogRow[] {
    const db = this.ensure();
    const { whereSql, params } = compileWhere(filter, {
      seqAfter: opts.seqAfter,
      seqBefore: opts.seqBefore,
    });
    const { sql: orderLimit, params: olParams } = compileOrderLimit(opts.direction, opts.limit);
    const sql = `SELECT ${QUERY_COLUMNS.join(", ")} FROM log_events ${whereSql} ${orderLimit}`;
    const rows = db.prepare(sql).all(...params, ...olParams) as Record<string, unknown>[];
    return rows.map(rowToLogRow);
  }

  countEvents(filter: LogFilter): number {
    const db = this.ensure();
    const { whereSql, params } = compileWhere(filter);
    const row = db
      .prepare(`SELECT COUNT(*) AS n FROM log_events ${whereSql}`)
      .get(...params) as { n: number };
    return row.n;
  }

  eventsForFingerprintCandidates(sinceIso: string, limit: number): LogRow[] {
    // Backfill scan for the in-memory fingerprint index at startup (§11.5):
    // every WARNING+ row within the issue-retention window.
    const db = this.ensure();
    const sql = `SELECT ${QUERY_COLUMNS.join(", ")} FROM log_events
      WHERE level IN ('WARNING','ERROR','CRITICAL') AND client_ts >= ?
      ORDER BY seq ASC LIMIT ?`;
    const rows = db.prepare(sql).all(sinceIso, limit) as Record<string, unknown>[];
    return rows.map(rowToLogRow);
  }

  statsSummary(): StatsSummary {
    const db = this.ensure();
    const serverRow = db
      .prepare(
        `SELECT started_at, total_log_events, total_connections, total_truncated, total_errors_sent
         FROM server_stats WHERE id = 1`,
      )
      .get() as
      | {
          started_at: string;
          total_log_events: number;
          total_connections: number;
          total_truncated: number;
          total_errors_sent: number;
        }
      | undefined;

    const totalRows = (db.prepare("SELECT COUNT(*) AS n FROM log_events").get() as { n: number }).n;
    const perLevel = db
      .prepare("SELECT level, COUNT(*) AS n FROM log_events GROUP BY level ORDER BY n DESC")
      .all() as Array<{ level: string; n: number }>;
    const perProcess = db
      .prepare("SELECT process, COUNT(*) AS n FROM log_events GROUP BY process ORDER BY n DESC")
      .all() as Array<{ process: string; n: number }>;
    const oldest = db
      .prepare("SELECT MIN(client_ts) AS m FROM log_events")
      .get() as { m: string | null };

    let dbSizeBytes = 0;
    try {
      dbSizeBytes = statSync(this.path).size;
    } catch {
      // best-effort only
    }

    return {
      server: {
        started_at: serverRow?.started_at ?? null,
        total_log_events: serverRow?.total_log_events ?? 0,
        total_connections: serverRow?.total_connections ?? 0,
        total_truncated: serverRow?.total_truncated ?? 0,
        total_errors_sent: serverRow?.total_errors_sent ?? 0,
      },
      totalRows,
      perLevel,
      perProcess,
      dbSizeBytes,
      dbPath: this.path,
      oldestClientTs: oldest.m,
    };
  }

  timeseries(
    filter: LogFilter,
    window: string,
    bucket: BucketSize,
    groupBy: "level" | "process" | null,
  ): TimeseriesResponse {
    const db = this.ensure();
    const win = isValidWindow(window) ? window : "1h";
    const from = windowToIsoFrom(win);
    const scoped: LogFilter = { ...filter, from };
    const { sql, params } = buildTimeseriesQuery(scoped, bucket, groupBy);
    const rows = db.prepare(sql).all(...params) as Array<{
      bucket_start: string;
      grp?: string;
      n: number;
    }>;

    const byBucket = new Map<string, TimeseriesBucket>();
    for (const row of rows) {
      let bucketEntry = byBucket.get(row.bucket_start);
      if (!bucketEntry) {
        bucketEntry = { bucketStart: row.bucket_start };
        byBucket.set(row.bucket_start, bucketEntry);
      }
      if (groupBy) {
        bucketEntry.groups = bucketEntry.groups ?? {};
        bucketEntry.groups[row.grp ?? "unknown"] = row.n;
      } else {
        bucketEntry.count = row.n;
      }
    }

    return {
      window: win,
      bucketSeconds: BUCKET_SECONDS[bucket],
      groupBy,
      buckets: [...byBucket.values()].sort((a, b) => a.bucketStart.localeCompare(b.bucketStart)),
    };
  }

  byLevel(filter: LogFilter, window: string): ByLevelResponse {
    const db = this.ensure();
    const win = isValidWindow(window) ? window : "1h";
    const from = windowToIsoFrom(win);
    const { sql, params } = buildByLevelQuery({ ...filter, from });
    const rows = db.prepare(sql).all(...params) as Array<{ level: string; n: number }>;
    return { window: win, levels: rows };
  }

  byProcess(filter: LogFilter, window: string): ByProcessResponse {
    const db = this.ensure();
    const win = isValidWindow(window) ? window : "1h";
    const from = windowToIsoFrom(win);
    const { sql, params } = buildByProcessQuery({ ...filter, from });
    const rows = db.prepare(sql).all(...params) as Array<{ process: string; n: number }>;
    return { window: win, level: filter.minLevel ?? null, processes: rows };
  }

  processes(): ProcessRow[] {
    const db = this.ensure();
    const rows = db
      .prepare(
        `SELECT process, instance, pid, host, session, connected_at, last_seen_at,
                disconnected_at, log_count
         FROM processes ORDER BY connected_at DESC`,
      )
      .all() as Array<Omit<ProcessRow, "errorCount">>;

    const errorRows = db
      .prepare(
        `SELECT process, COUNT(*) AS n FROM log_events
         WHERE level IN ('ERROR','CRITICAL') GROUP BY process`,
      )
      .all() as Array<{ process: string; n: number }>;
    const errorByProcess = new Map(errorRows.map((r) => [r.process, r.n]));

    return rows.map((r) => ({ ...r, errorCount: errorByProcess.get(r.process) ?? 0 }));
  }

  /** Raw connection, for the diagnostics module which runs its own SQL (design §12.2). */
  connection(): DatabaseSync {
    return this.ensure();
  }
}

/**
 * Read-only history from pm-monitor's `metrics.db` (design §9.5, §11.2,
 * WP-C2.3).
 *
 * Opened with `readOnly: true`, as log-gui opens `log.db`, so "the bridge
 * never writes to metrics.db" is enforced by SQLite, not by convention.
 * Every query is one statement run to completion: no read transaction is
 * ever held between requests, since a long-lived reader stops pm-monitor's
 * WAL checkpoints and `metrics.db-wal` would grow without bound (I87).
 *
 * The handle follows the file at `path`, not the one it had open, so a
 * `metrics.db` replaced by `pm-opctl-cli clear --all` is picked up. In the
 * container, a clean pm-monitor stop removes `metrics.db-wal`/`-shm` and the
 * read-only mount cannot create them again, so SQLite cannot open the file
 * the usual way; with no `-wal` the file is complete, and it is read
 * `immutable` until pm-monitor starts and a `-wal` appears (I105). Any
 * other failure to read is a 503, never a bare 500.
 *
 * Samples refer to `series(id)`, so a query looks its series up first and
 * then range-scans the `(series, ts)` primary key. Bucketing is done in SQL,
 * so a request never returns more than `MAX_POINTS` points however long
 * its range; node:sqlite binds every JS number as REAL, so the bucket width
 * is CAST to INTEGER or the division would not floor. Buckets start on the
 * session clock (`offsetSec`, see session-time.ts). Metric names, labels
 * and sources are always bound parameters.
 */

import { existsSync, statSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { pathToFileURL } from "node:url";
import type { HealthEvent, Point, Resolution } from "@edumatcher/dash-types";

/** Most points one series returns; the bucket widens to fit the range. */
export const MAX_POINTS = 1000;
/** Native spacing of the two sample tables (store.py RAW_EVERY_SEC, MINUTE). */
export const RAW_SEC = 10;
export const MINUTE_SEC = 60;

/**
 * Bucket start in epoch seconds, aligned to the session clock. Parameters:
 * offset, width, width, offset.
 */
const BUCKET =
  "((unixepoch(ts) + CAST(? AS INTEGER)) / CAST(? AS INTEGER)) * CAST(? AS INTEGER) - CAST(? AS INTEGER)";

/** A request the database cannot answer as asked: becomes a 4xx or 503. */
export class QueryError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

function unavailable(detail: string): QueryError {
  return new QueryError(503, "metrics_db_unavailable", detail);
}

export interface TimeRange {
  /** Epoch milliseconds, inclusive. */
  fromMs: number;
  /** Epoch milliseconds, exclusive. */
  toMs: number;
}

/** The store's own text form, so a `ts` comparison is a key range scan. */
export function isoUtc(ms: number): string {
  return new Date(ms).toISOString();
}

/** A bucket of at least `nativeSec` that yields at most MAX_POINTS points. */
export function bucketFor(range: TimeRange, nativeSec: number): number {
  const spanSec = (range.toMs - range.fromMs) / 1000;
  const needed = Math.ceil(spanSec / MAX_POINTS);
  return Math.max(nativeSec, Math.ceil(needed / nativeSec) * nativeSec);
}

interface SeriesRow {
  id: number;
  source: string;
}

export interface SeriesResult {
  source: string;
  resolution: Resolution;
  bucketSec: number;
  points: Point[];
}

export class MetricsDb {
  private db: DatabaseSync | null = null;
  /** `dev:ino` of the file the handle has open. */
  private identity = "";
  /** Opened `immutable` (pm-monitor stopped, no `-wal`): see the module note. */
  private immutable = false;

  constructor(readonly path: string) {}

  /** Whether a query can be answered now; runs one. */
  get health(): { ok: boolean; detail: string } {
    try {
      this.run((db) => db.prepare("SELECT count(*) FROM series").get());
      return {
        ok: true,
        detail: this.immutable ? "open (read-only, immutable: pm-monitor is stopped)" : "open (read-only)",
      };
    } catch (err) {
      if (err instanceof QueryError) return { ok: false, detail: err.message };
      throw err;
    }
  }

  close(): void {
    this.db?.close();
    this.db = null;
  }

  /** The session timezone pm-monitor pinned in the file; null when unreadable. */
  sessionTimezone(): string | null {
    try {
      const row = this.run((db) =>
        db.prepare("SELECT value FROM metrics_meta WHERE key = 'session_timezone'").get(),
      ) as { value: string } | undefined;
      return row?.value ?? null;
    } catch (err) {
      if (err instanceof QueryError) return null;
      throw err;
    }
  }

  /** Whether any series of this metric exists, under any label or source. */
  knows(name: string): boolean {
    return this.run((db) => db.prepare("SELECT 1 FROM series WHERE name = ? LIMIT 1").get(name) !== undefined);
  }

  /** Every label recorded for a metric, sorted. */
  labels(name: string, limit: number): string[] {
    const rows = this.run((db) =>
      db.prepare("SELECT DISTINCT label FROM series WHERE name = ? ORDER BY label LIMIT ?").all(name, limit),
    ) as { label: string }[];
    return rows.map((r) => r.label);
  }

  /**
   * One series over a range. `source` may be left out when only one process
   * (or `host`) records this name and label; otherwise it is required, since
   * gauges from two processes cannot be merged into one line. The 10 s
   * samples answer when they reach back as far as anything recorded does;
   * otherwise (retention has thinned the start of the range) the minute
   * table answers. `only: "1m"` reads the minute table whatever the range.
   */
  series(
    name: string,
    label: string,
    source: string | undefined,
    range: TimeRange,
    offsetSec: number,
    only?: Resolution,
  ): SeriesResult {
    return this.run((db): SeriesResult => {
      const one = this.resolveSeries(db, name, label, source);
      if (only !== "1m" && this.rawCovers(db, one.id, range)) {
        const bucketSec = bucketFor(range, RAW_SEC);
        return { source: one.source, resolution: "raw", bucketSec, points: this.rawPoints(db, one.id, range, bucketSec, offsetSec) };
      }
      const bucketSec = bucketFor(range, MINUTE_SEC);
      return {
        source: one.source,
        resolution: "1m",
        bucketSec,
        points: this.minutePoints(db, one.id, range, bucketSec, offsetSec),
      };
    });
  }

  /**
   * Counter increments per bucket from the minute table's reset-corrected
   * `delta`, summed over every matching series: all sources, and all labels
   * unless one is given. Rates add up, so the sum is meaningful.
   */
  rate(
    name: string,
    label: string | undefined,
    source: string | undefined,
    range: TimeRange,
    bucketSec: number,
    offsetSec: number,
  ): Point[] {
    return this.run((db) => {
      const ids = this.matchingIds(db, name, label, source);
      if (ids.length === 0) return [];
      const marks = ids.map(() => "?").join(",");
      const rows = db
        .prepare(
          `SELECT ${BUCKET} AS bucket, sum(delta) AS total
           FROM samples_1m
           WHERE series IN (${marks}) AND ts >= ? AND ts < ? AND delta IS NOT NULL
           GROUP BY bucket ORDER BY bucket`,
        )
        .all(offsetSec, bucketSec, bucketSec, offsetSec, ...ids, isoUtc(range.fromMs), isoUtc(range.toMs)) as {
        bucket: number;
        total: number;
      }[];
      return rows.map((r): Point => [r.bucket * 1000, r.total]);
    });
  }

  /** The latest `days` trading dates' totals, oldest first, summed like {@link rate}. */
  daily(name: string, label: string | undefined, source: string | undefined, days: number): { date: string; total: number }[] {
    const where = ["name = ?"];
    const params: (string | number)[] = [name];
    if (label !== undefined) {
      where.push("label = ?");
      params.push(label);
    }
    if (source !== undefined) {
      where.push("source = ?");
      params.push(source);
    }
    const rows = this.run((db) =>
      db
        .prepare(
          `SELECT date, sum(total) AS total FROM daily_totals WHERE ${where.join(" AND ")}
           GROUP BY date ORDER BY date DESC LIMIT ?`,
        )
        .all(...params, days),
    ) as { date: string; total: number }[];
    return rows.reverse();
  }

  /**
   * Events in ascending `seq`. With `afterSeq` (a reconnecting browser
   * catching up) the oldest `limit` after it; otherwise the newest `limit`
   * in the range.
   */
  events(opts: { range?: TimeRange; afterSeq?: number; kinds?: string[]; limit: number }): HealthEvent[] {
    const where: string[] = [];
    const params: (string | number)[] = [];
    if (opts.afterSeq !== undefined) {
      where.push("seq > ?");
      params.push(opts.afterSeq);
    }
    if (opts.range) {
      where.push("ts >= ? AND ts < ?");
      params.push(isoUtc(opts.range.fromMs), isoUtc(opts.range.toMs));
    }
    if (opts.kinds && opts.kinds.length > 0) {
      where.push(`kind IN (${opts.kinds.map(() => "?").join(",")})`);
      params.push(...opts.kinds);
    }
    const order = opts.afterSeq !== undefined ? "ASC" : "DESC";
    const rows = this.run((db) =>
      db
        .prepare(
          `SELECT seq, ts, kind, severity, subject, detail FROM events
           ${where.length ? `WHERE ${where.join(" AND ")}` : ""}
           ORDER BY seq ${order} LIMIT ?`,
        )
        .all(...params, opts.limit),
    ) as unknown as HealthEvent[];
    const events = rows.map((r) => ({ ...r }));
    return order === "DESC" ? events.reverse() : events;
  }

  // ------------------------------------------------------------------

  /** One query against the current file; any SQLite failure becomes a 503. */
  private run<T>(query: (db: DatabaseSync) => T): T {
    try {
      return query(this.ensure());
    } catch (err) {
      if (err instanceof QueryError) throw err;
      const message = err instanceof Error ? err.message : String(err);
      this.close();
      // SQLite words it by version ("unable to open database file", "attempt
      // to write a readonly database"): without a -wal, any failure gets one
      // immutable try, and a file that is truly unreadable fails that too.
      if (!this.immutable && !existsSync(`${this.path}-wal`)) {
        this.immutable = true;
        return this.run(query);
      }
      throw unavailable(`metrics.db cannot be read: ${message}`);
    }
  }

  /** The handle on the file now at `path`, opened (or reopened) as needed. */
  private ensure(): DatabaseSync {
    let identity: string;
    try {
      const st = statSync(this.path);
      identity = `${st.dev}:${st.ino}`;
    } catch {
      this.close();
      throw unavailable(`metrics.db not found at ${this.path} -- is pm-monitor running with this data directory?`);
    }
    if (this.db && identity !== this.identity) this.close(); // replaced since it was opened
    if (this.immutable && existsSync(`${this.path}-wal`)) {
      this.close(); // pm-monitor has started: read its WAL again
      this.immutable = false;
    }
    if (!this.db) {
      try {
        const url = pathToFileURL(this.path);
        if (this.immutable) url.searchParams.set("immutable", "1");
        this.db = new DatabaseSync(this.immutable ? url : this.path, { readOnly: true });
      } catch (err) {
        throw unavailable(err instanceof Error ? err.message : String(err));
      }
      this.identity = identity;
    }
    return this.db;
  }

  private resolveSeries(db: DatabaseSync, name: string, label: string, source: string | undefined): SeriesRow {
    const rows = db
      .prepare(
        source === undefined
          ? "SELECT id, source FROM series WHERE name = ? AND label = ? ORDER BY source"
          : "SELECT id, source FROM series WHERE name = ? AND label = ? AND source = ?",
      )
      .all(...(source === undefined ? [name, label] : [name, label, source])) as unknown as SeriesRow[];
    if (rows.length === 0) {
      const what = `${name}${label ? `{${label}}` : ""}${source ? ` from ${source}` : ""}`;
      throw new QueryError(404, "unknown_series", `no series ${what} in metrics.db`);
    }
    if (rows.length > 1) {
      throw new QueryError(
        400,
        "ambiguous_source",
        `${name}${label ? `{${label}}` : ""} is recorded by ${rows.length} sources; pass source= one of ${rows
          .map((r) => r.source)
          .join(", ")}`,
      );
    }
    return rows[0]!;
  }

  /**
   * Whether the 10 s samples hold everything there is in the range: true
   * unless the minute table has rows in it from before the first 10 s row
   * (retention thinned the raw rows there). A gap with no data at all, or
   * a pm-monitor that has not yet closed a minute, leaves raw the answer.
   * The slack is a minute and a raw flush: a minute row is stamped with its
   * minute's start, the series' first sample may come late in that minute,
   * and the first raw row is written at the next 10 s flush after it --
   * up to 70 s after the minute row's stamp (found end to end, I110).
   */
  private rawCovers(db: DatabaseSync, id: number, range: TimeRange): boolean {
    const raw = (db.prepare("SELECT min(ts) AS t FROM samples_raw WHERE series = ?").get(id) as { t: string | null }).t;
    if (raw === null) return false;
    const before = Date.parse(raw) - (MINUTE_SEC + RAW_SEC) * 1000;
    if (before <= range.fromMs) return true;
    const older = db
      .prepare("SELECT 1 FROM samples_1m WHERE series = ? AND ts >= ? AND ts < ? LIMIT 1")
      .get(id, isoUtc(range.fromMs), isoUtc(before));
    return older === undefined;
  }

  private matchingIds(db: DatabaseSync, name: string, label: string | undefined, source: string | undefined): number[] {
    const where = ["name = ?"];
    const params: string[] = [name];
    if (label !== undefined) {
      where.push("label = ?");
      params.push(label);
    }
    if (source !== undefined) {
      where.push("source = ?");
      params.push(source);
    }
    const rows = db.prepare(`SELECT id FROM series WHERE ${where.join(" AND ")}`).all(...params) as { id: number }[];
    return rows.map((r) => r.id);
  }

  private rawPoints(db: DatabaseSync, id: number, range: TimeRange, bucketSec: number, offsetSec: number): Point[] {
    const rows = db
      .prepare(
        `SELECT ${BUCKET} AS bucket, avg(value) AS v
         FROM samples_raw WHERE series = ? AND ts >= ? AND ts < ?
         GROUP BY bucket ORDER BY bucket`,
      )
      .all(offsetSec, bucketSec, bucketSec, offsetSec, id, isoUtc(range.fromMs), isoUtc(range.toMs)) as {
      bucket: number;
      v: number;
    }[];
    return rows.map((r) => [r.bucket * 1000, r.v]);
  }

  /**
   * A gauge is the sample-weighted mean of the bucket's minutes. A counter
   * (its minutes carry a `delta`) is its highest value in the bucket, the
   * level it had reached; how much it grew is what /api/rate is for.
   */
  private minutePoints(db: DatabaseSync, id: number, range: TimeRange, bucketSec: number, offsetSec: number): Point[] {
    const rows = db
      .prepare(
        `SELECT ${BUCKET} AS bucket,
                CASE WHEN max(delta IS NOT NULL) THEN max(v_last)
                     ELSE sum(v_avg * n) / sum(n) END AS v
         FROM samples_1m WHERE series = ? AND ts >= ? AND ts < ?
         GROUP BY bucket ORDER BY bucket`,
      )
      .all(offsetSec, bucketSec, bucketSec, offsetSec, id, isoUtc(range.fromMs), isoUtc(range.toMs)) as {
      bucket: number;
      v: number;
    }[];
    return rows.map((r) => [r.bucket * 1000, r.v]);
  }
}

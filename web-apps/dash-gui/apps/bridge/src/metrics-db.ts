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
 * Samples refer to `series(id)`, so a query looks its series up first and
 * then range-scans the `(series, ts)` primary key. Bucketing is done in SQL,
 * so a request never returns more than `MAX_POINTS` points however long
 * its range; node:sqlite binds every JS number as REAL, so the bucket width
 * is CAST to INTEGER or the division would not floor. Metric names, labels
 * and sources are always bound parameters.
 */

import { existsSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import type { HealthEvent, Point, Resolution } from "@edumatcher/dash-types";

/** Most points one series returns; the bucket widens to fit the range. */
export const MAX_POINTS = 1000;
/** Native spacing of the two sample tables (store.py RAW_EVERY_SEC, MINUTE). */
export const RAW_SEC = 10;
export const MINUTE_SEC = 60;

/** A request the database cannot answer as asked: becomes a 4xx. */
export class QueryError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
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
  private lastError: string | null = null;

  constructor(
    readonly path: string,
    /** `monitor.retention.raw_hours`: ranges up to this read every sample. */
    private readonly rawHours: number,
  ) {}

  get health(): { ok: boolean; detail: string } {
    if (this.db || this.open()) return { ok: true, detail: "open (read-only)" };
    return { ok: false, detail: this.lastError ?? "not open" };
  }

  close(): void {
    this.db?.close();
    this.db = null;
  }

  /** Whether any series of this metric exists, under any label or source. */
  knows(name: string): boolean {
    return this.ensure().prepare("SELECT 1 FROM series WHERE name = ? LIMIT 1").get(name) !== undefined;
  }

  /** Every label recorded for a metric, sorted. */
  labels(name: string, limit: number): string[] {
    const rows = this.ensure()
      .prepare("SELECT DISTINCT label FROM series WHERE name = ? ORDER BY label LIMIT ?")
      .all(name, limit) as { label: string }[];
    return rows.map((r) => r.label);
  }

  /**
   * One series over a range. `source` may be left out when only one process
   * (or `host`) records this name and label; otherwise it is required, since
   * gauges from two processes cannot be merged into one line. `only: "1m"`
   * reads the minute table whatever the range.
   */
  series(
    name: string,
    label: string,
    source: string | undefined,
    range: TimeRange,
    only?: Resolution,
  ): SeriesResult {
    const one = this.resolveSeries(name, label, source);
    const useRaw = only !== "1m" && range.toMs - range.fromMs <= this.rawHours * 3600 * 1000;
    if (useRaw) {
      const bucketSec = bucketFor(range, RAW_SEC);
      const points = this.rawPoints(one.id, range, bucketSec);
      // Older than the raw window (retention deleted it): the minute table
      // still has the range.
      if (points.length > 0) return { source: one.source, resolution: "raw", bucketSec, points };
    }
    const bucketSec = bucketFor(range, MINUTE_SEC);
    return { source: one.source, resolution: "1m", bucketSec, points: this.minutePoints(one.id, range, bucketSec) };
  }

  /**
   * Counter increments per bucket from the minute table's reset-corrected
   * `delta`, summed over every matching series: all sources, and all labels
   * unless one is given. Rates add up, so the sum is meaningful.
   */
  rate(name: string, label: string | undefined, source: string | undefined, range: TimeRange, bucketSec: number): Point[] {
    const ids = this.matchingIds(name, label, source);
    if (ids.length === 0) return [];
    const marks = ids.map(() => "?").join(",");
    const rows = this.ensure()
      .prepare(
        `SELECT (unixepoch(ts) / CAST(? AS INTEGER)) * CAST(? AS INTEGER) AS bucket, sum(delta) AS total
         FROM samples_1m
         WHERE series IN (${marks}) AND ts >= ? AND ts < ? AND delta IS NOT NULL
         GROUP BY bucket ORDER BY bucket`,
      )
      .all(bucketSec, bucketSec, ...ids, isoUtc(range.fromMs), isoUtc(range.toMs)) as {
      bucket: number;
      total: number;
    }[];
    return rows.map((r) => [r.bucket * 1000, r.total]);
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
    const rows = this.ensure()
      .prepare(
        `SELECT date, sum(total) AS total FROM daily_totals WHERE ${where.join(" AND ")}
         GROUP BY date ORDER BY date DESC LIMIT ?`,
      )
      .all(...params, days) as { date: string; total: number }[];
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
    const rows = this.ensure()
      .prepare(
        `SELECT seq, ts, kind, severity, subject, detail FROM events
         ${where.length ? `WHERE ${where.join(" AND ")}` : ""}
         ORDER BY seq ${order} LIMIT ?`,
      )
      .all(...params, opts.limit) as unknown as HealthEvent[];
    const events = rows.map((r) => ({ ...r }));
    return order === "DESC" ? events.reverse() : events;
  }

  // ------------------------------------------------------------------

  private open(): boolean {
    if (this.db) return true;
    if (!existsSync(this.path)) {
      this.lastError = `metrics.db not found at ${this.path} -- is pm-monitor running with this data directory?`;
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

  private ensure(): DatabaseSync {
    if (!this.open()) throw new QueryError(503, "metrics_db_unavailable", this.lastError ?? "metrics.db unavailable");
    return this.db!;
  }

  private resolveSeries(name: string, label: string, source: string | undefined): SeriesRow {
    const rows = this.ensure()
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

  private matchingIds(name: string, label: string | undefined, source: string | undefined): number[] {
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
    const rows = this.ensure()
      .prepare(`SELECT id FROM series WHERE ${where.join(" AND ")}`)
      .all(...params) as { id: number }[];
    return rows.map((r) => r.id);
  }

  private rawPoints(id: number, range: TimeRange, bucketSec: number): Point[] {
    const rows = this.ensure()
      .prepare(
        `SELECT (unixepoch(ts) / CAST(? AS INTEGER)) * CAST(? AS INTEGER) AS bucket, avg(value) AS v
         FROM samples_raw WHERE series = ? AND ts >= ? AND ts < ?
         GROUP BY bucket ORDER BY bucket`,
      )
      .all(bucketSec, bucketSec, id, isoUtc(range.fromMs), isoUtc(range.toMs)) as { bucket: number; v: number }[];
    return rows.map((r) => [r.bucket * 1000, r.v]);
  }

  /**
   * A gauge is the sample-weighted mean of the bucket's minutes. A counter
   * (its minutes carry a `delta`) is its highest value in the bucket, the
   * level it had reached; how much it grew is what /api/rate is for.
   */
  private minutePoints(id: number, range: TimeRange, bucketSec: number): Point[] {
    const rows = this.ensure()
      .prepare(
        `SELECT (unixepoch(ts) / CAST(? AS INTEGER)) * CAST(? AS INTEGER) AS bucket,
                CASE WHEN max(delta IS NOT NULL) THEN max(v_last)
                     ELSE sum(v_avg * n) / sum(n) END AS v
         FROM samples_1m WHERE series = ? AND ts >= ? AND ts < ?
         GROUP BY bucket ORDER BY bucket`,
      )
      .all(bucketSec, bucketSec, id, isoUtc(range.fromMs), isoUtc(range.toMs)) as { bucket: number; v: number }[];
    return rows.map((r) => [r.bucket * 1000, r.v]);
  }
}

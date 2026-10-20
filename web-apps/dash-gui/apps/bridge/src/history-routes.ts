/**
 * History REST routes (design §11.2, WP-C2.4) over {@link MetricsDb}.
 *
 * Every parameter is validated here; a malformed or out-of-bounds request
 * is a 400 with `{ error, message }`, never a database error. Names,
 * labels and sources reach SQL only as bound parameters.
 *
 * Times: a request names an instant unambiguously — epoch milliseconds, or
 * ISO-8601 with `Z` or an offset (a bare local time would be read in the
 * bridge's own zone, which is neither the browser's nor the exchange's).
 * Responses are epoch ms. Buckets start on the session clock.
 */

import type { FastifyInstance, FastifyReply } from "fastify";
import type {
  ApiError,
  DailyResponse,
  EventKind,
  EventsResponse,
  MultiSeriesResponse,
  RangeName,
  RateResponse,
  SeriesResponse,
} from "@edumatcher/dash-types";
import { MAX_POINTS, MetricsDb, QueryError, type TimeRange } from "./metrics-db.js";
import { utcOffsetSec } from "./session-time.js";

/** The longest range any history request may span: the minute table's window. */
export const MAX_RANGE_MS = 7 * 24 * 3600 * 1000;
/** Labels one `/api/series/multi` request may ask for. */
export const MAX_LABELS = 50;
export const MAX_EVENTS = 1000;
export const DEFAULT_EVENTS = 500;
export const MAX_DAYS = 366;

/** A Record, so a kind added to `EventKind` (the spec) fails typecheck until listed. */
const EVENT_KINDS: Record<EventKind, true> = {
  CONNECT: true,
  AUTH_REJECT: true,
  DISCONNECT: true,
  DIAGNOSTIC: true,
  SESSION: true,
  HALT: true,
  RESUME: true,
  PROCESS_STATUS: true,
  THRESHOLD: true,
};

/** The time-picker set (§11.2); `range=` is an alternative to `from=`. */
const RANGES: Record<RangeName, number> = {
  "5m": 5 * 60_000,
  "15m": 15 * 60_000,
  "1h": 3600_000,
  "6h": 6 * 3600_000,
  "24h": 24 * 3600_000,
  "7d": 7 * 24 * 3600_000,
};

type Query = Record<string, string | undefined>;

/** ISO-8601 date and time with seconds optional, and a zone that is required. */
const ISO_INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?(Z|[+-]\d{2}:\d{2})$/;

function bad(code: string, message: string): QueryError {
  return new QueryError(400, code, message);
}

/** The query string, each parameter given at most once. */
function query(raw: unknown): Query {
  const q = (raw ?? {}) as Record<string, unknown>;
  for (const [key, value] of Object.entries(q)) {
    if (typeof value !== "string") throw bad("bad_param", `${key}= is given more than once`);
  }
  return q as Query;
}

/** Epoch milliseconds, or ISO-8601 with `Z` or an offset (as metrics.db and the snapshot write it). */
export function parseTime(raw: string, param: string): number {
  const ms = /^\d+$/.test(raw) ? Number(raw) : ISO_INSTANT.test(raw) ? Date.parse(raw) : NaN;
  if (!Number.isFinite(ms)) {
    throw bad("bad_time", `${param}=${raw} is neither epoch milliseconds nor ISO-8601 with Z or an offset`);
  }
  return ms;
}

/** `from`/`to`, or `range` ending now; at most seven days. */
export function parseRange(q: Query, now: number, required = true): TimeRange | undefined {
  if (q.range !== undefined) {
    if (q.from !== undefined) throw bad("bad_range", "give either range= or from=, not both");
    const span = Object.hasOwn(RANGES, q.range) ? RANGES[q.range as RangeName] : undefined;
    if (span === undefined) throw bad("bad_range", `range=${q.range}; use one of ${Object.keys(RANGES).join(", ")}`);
    const toMs = q.to !== undefined ? parseTime(q.to, "to") : now;
    return { fromMs: toMs - span, toMs };
  }
  if (q.from === undefined) {
    if (required) throw bad("missing_param", "from= (or range=) is required");
    return undefined;
  }
  const fromMs = parseTime(q.from, "from");
  const toMs = q.to !== undefined ? parseTime(q.to, "to") : now;
  if (toMs <= fromMs) throw bad("bad_range", "to must be after from");
  if (toMs - fromMs > MAX_RANGE_MS) throw bad("range_too_long", "a range may span at most 7 days");
  return { fromMs, toMs };
}

function requireName(q: Query): string {
  const name = q.name;
  if (!name) throw bad("missing_param", "name= is required");
  if (name.length > 64) throw bad("bad_name", "name= is at most 64 characters");
  return name;
}

function optionalText(q: Query, key: string, max: number): string | undefined {
  const value = q[key];
  if (value !== undefined && value.length > max) throw bad(`bad_${key}`, `${key}= is at most ${max} characters`);
  return value;
}

function positiveInt(raw: string | undefined, param: string, fallback: number, max: number): number {
  if (raw === undefined) return fallback;
  if (!/^\d+$/.test(raw) || Number(raw) < 1 || Number(raw) > max) {
    throw bad("bad_param", `${param}= must be an integer from 1 to ${max}`);
  }
  return Number(raw);
}

function knownMetric(db: MetricsDb, name: string): void {
  if (!db.knows(name)) throw bad("unknown_metric", `no metric named ${name} in metrics.db`);
}

function send(reply: FastifyReply, run: () => unknown): unknown {
  try {
    return run();
  } catch (err) {
    if (err instanceof QueryError) {
      const body: ApiError = { error: err.code, message: err.message };
      return reply.status(err.status).send(body);
    }
    throw err;
  }
}

/**
 * `sessionTz` is the exchange's IANA zone as the bridge knows it now: buckets
 * start on that clock.
 */
export function registerHistoryRoutes(
  app: FastifyInstance,
  db: MetricsDb,
  sessionTz: () => string,
  now: () => number = Date.now,
): void {
  const offsetFor = (range: TimeRange) => utcOffsetSec(sessionTz(), range.toMs);

  app.get("/api/series", (request, reply) =>
    send(reply, (): SeriesResponse => {
      const q = query(request.query);
      const name = requireName(q);
      const label = optionalText(q, "label", 32) ?? "";
      const source = optionalText(q, "source", 200);
      const range = parseRange(q, now())!;
      knownMetric(db, name);
      const result = db.series(name, label, source, range, offsetFor(range));
      return { name, label, ...result };
    }),
  );

  app.get("/api/series/multi", (request, reply) =>
    send(reply, (): MultiSeriesResponse => {
      const q = query(request.query);
      const name = requireName(q);
      const source = optionalText(q, "source", 200);
      const range = parseRange(q, now())!;
      const offsetSec = offsetFor(range);
      knownMetric(db, name);
      const labels =
        q.labels !== undefined && q.labels !== ""
          ? [...new Set(q.labels.split(","))]
          : db.labels(name, MAX_LABELS + 1);
      if (labels.length > MAX_LABELS) throw bad("too_many_labels", `at most ${MAX_LABELS} labels per request`);
      if (labels.some((l) => l.length > 32)) throw bad("bad_label", "a label is at most 32 characters");
      let results = labels.map((label) => ({ label, ...db.series(name, label, source, range, offsetSec) }));
      // One resolution for the whole chart: if any label had to fall back to
      // the minute table, every label is read from it.
      if (results.some((r) => r.resolution === "1m") && results.some((r) => r.resolution === "raw")) {
        results = labels.map((label) => ({ label, ...db.series(name, label, source, range, offsetSec, "1m") }));
      }
      return {
        name,
        source: source ?? [...new Set(results.map((r) => r.source))].join(","),
        resolution: results[0]?.resolution ?? "raw",
        bucketSec: Math.max(...results.map((r) => r.bucketSec), 0),
        series: results.map((r) => ({ label: r.label, points: r.points })),
      };
    }),
  );

  app.get("/api/rate", (request, reply) =>
    send(reply, (): RateResponse => {
      const q = query(request.query);
      const name = requireName(q);
      const label = optionalText(q, "label", 32);
      const source = optionalText(q, "source", 200);
      const range = parseRange(q, now())!;
      const bucket = q.bucket ?? "1m";
      if (bucket !== "1m" && bucket !== "1h") throw bad("bad_bucket", "bucket= is 1m or 1h");
      const bucketSec = bucket === "1m" ? 60 : 3600;
      if ((range.toMs - range.fromMs) / 1000 / bucketSec > MAX_POINTS) {
        throw bad("too_many_points", `this range has more than ${MAX_POINTS} ${bucket} buckets; use bucket=1h`);
      }
      knownMetric(db, name);
      return { name, label: label ?? null, bucket, points: db.rate(name, label, source, range, bucketSec, offsetFor(range)) };
    }),
  );

  app.get("/api/daily", (request, reply) =>
    send(reply, (): DailyResponse => {
      const q = query(request.query);
      const name = requireName(q);
      const label = optionalText(q, "label", 32);
      const source = optionalText(q, "source", 200);
      const days = positiveInt(q.days, "days", 30, MAX_DAYS);
      knownMetric(db, name);
      return { name, label: label ?? null, days: db.daily(name, label, source, days) };
    }),
  );

  app.get("/api/events", (request, reply) =>
    send(reply, (): EventsResponse => {
      const q = query(request.query);
      const limit = positiveInt(q.limit, "limit", DEFAULT_EVENTS, MAX_EVENTS);
      let afterSeq: number | undefined;
      if (q.after_seq !== undefined) {
        if (!/^\d+$/.test(q.after_seq)) throw bad("bad_param", "after_seq= must be a non-negative integer");
        afterSeq = Number(q.after_seq);
      }
      const range = parseRange(q, now(), afterSeq === undefined);
      const kinds = q.kind !== undefined && q.kind !== "" ? q.kind.split(",") : undefined;
      const unknown = kinds?.filter((k) => !Object.hasOwn(EVENT_KINDS, k)) ?? [];
      if (unknown.length > 0) {
        throw bad("bad_kind", `unknown kind ${unknown.join(", ")}; use ${Object.keys(EVENT_KINDS).join(", ")}`);
      }
      return { events: db.events({ range, afterSeq, kinds, limit }) };
    }),
  );
}

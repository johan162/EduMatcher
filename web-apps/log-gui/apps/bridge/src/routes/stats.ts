/** `GET /api/stats/*` (design §8.5, §16.2). */

import type { FastifyInstance } from "fastify";
import type { BucketSize } from "@edumatcher/log-query";
import type { LogFilter } from "@edumatcher/log-types";
import type { LogDb } from "../log-db.js";

function baseFilterFromQuery(q: Record<string, unknown>): LogFilter {
  return {
    minLevel: q.level ? (String(q.level).toUpperCase() as LogFilter["minLevel"]) : undefined,
    processes: q.process ? [String(q.process)] : undefined,
  };
}

export function registerStatsRoutes(app: FastifyInstance, logDb: LogDb): void {
  app.get("/api/stats/summary", async (_request, reply) => {
    try {
      return logDb.statsSummary();
    } catch (err) {
      return reply.status(503).send({ error: "log_db_unavailable", message: String(err) });
    }
  });

  app.get("/api/stats/timeseries", async (request, reply) => {
    const q = request.query as Record<string, unknown>;
    const window = String(q.window ?? "1h");
    const bucketRaw = String(q.bucket ?? "1m");
    const bucket: BucketSize = bucketRaw === "5m" || bucketRaw === "1h" ? bucketRaw : "1m";
    const groupBy = q.group_by === "level" || q.group_by === "process" ? q.group_by : null;
    try {
      return logDb.timeseries(baseFilterFromQuery(q), window, bucket, groupBy);
    } catch (err) {
      return reply.status(503).send({ error: "log_db_unavailable", message: String(err) });
    }
  });

  app.get("/api/stats/by-level", async (request, reply) => {
    const q = request.query as Record<string, unknown>;
    try {
      return logDb.byLevel(baseFilterFromQuery(q), String(q.window ?? "1h"));
    } catch (err) {
      return reply.status(503).send({ error: "log_db_unavailable", message: String(err) });
    }
  });

  app.get("/api/stats/by-process", async (request, reply) => {
    const q = request.query as Record<string, unknown>;
    try {
      return logDb.byProcess(baseFilterFromQuery(q), String(q.window ?? "1h"));
    } catch (err) {
      return reply.status(503).send({ error: "log_db_unavailable", message: String(err) });
    }
  });
}

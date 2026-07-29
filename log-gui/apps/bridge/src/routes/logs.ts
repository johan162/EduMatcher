/** `GET /api/logs`, `/api/logs/count`, `/api/logs/export` (design §9.6, §16.2). */

import type { FastifyInstance } from "fastify";
import type { LogFilter } from "@edumatcher/log-types";
import type { LogDb } from "../log-db.js";

function filterFromQuery(q: Record<string, unknown>): LogFilter {
  const asArray = (v: unknown): string[] | undefined => {
    if (v == null) return undefined;
    if (Array.isArray(v)) return v.map(String);
    return String(v).split(",").filter(Boolean);
  };
  return {
    minLevel: q.minLevel ? (String(q.minLevel).toUpperCase() as LogFilter["minLevel"]) : undefined,
    processes: asArray(q.processes),
    loggers: asArray(q.loggers),
    sessions: asArray(q.sessions),
    contains: q.contains ? String(q.contains) : undefined,
    exceptionsOnly: q.exceptionsOnly === "true" || q.exceptionsOnly === true,
    from: q.from ? String(q.from) : undefined,
    to: q.to ? String(q.to) : undefined,
  };
}

export function registerLogsRoutes(app: FastifyInstance, logDb: LogDb, queryMaxRows: number): void {
  app.get("/api/logs", async (request, reply) => {
    const q = request.query as Record<string, unknown>;
    const filter = filterFromQuery(q);
    const cursor = q.cursor ? Number(q.cursor) : undefined;
    const limit = Math.min(q.limit ? Number(q.limit) : 200, queryMaxRows);
    const direction = q.direction === "ASC" ? "ASC" : "DESC";

    try {
      const rows = logDb.queryEvents(filter, {
        seqAfter: direction === "ASC" ? cursor : undefined,
        seqBefore: direction === "DESC" ? cursor : undefined,
        limit,
        direction,
      });
      return { rows };
    } catch (err) {
      return reply.status(503).send({ error: "log_db_unavailable", message: String(err) });
    }
  });

  app.get("/api/logs/count", async (request, reply) => {
    const filter = filterFromQuery(request.query as Record<string, unknown>);
    try {
      return { count: logDb.countEvents(filter) };
    } catch (err) {
      return reply.status(503).send({ error: "log_db_unavailable", message: String(err) });
    }
  });

  app.get("/api/logs/export", async (request, reply) => {
    const q = request.query as Record<string, unknown>;
    const filter = filterFromQuery(q);
    const format = q.format === "json" ? "json" : "csv";
    const cap = 1_000_000;

    let rows;
    try {
      rows = logDb.queryEvents(filter, { limit: cap, direction: "ASC" });
    } catch (err) {
      return reply.status(503).send({ error: "log_db_unavailable", message: String(err) });
    }

    if (format === "json") {
      reply.header("Content-Type", "application/json");
      reply.header("Content-Disposition", "attachment; filename=logs-export.json");
      return rows;
    }

    reply.header("Content-Type", "text/csv");
    reply.header("Content-Disposition", "attachment; filename=logs-export.csv");
    const header = "seq,client_ts,level,process,logger,message\n";
    const body = rows
      .map((r) => [r.seq, r.client_ts, r.level, r.process, r.logger, JSON.stringify(r.message)].join(","))
      .join("\n");
    return header + body;
  });
}

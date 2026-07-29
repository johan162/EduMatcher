/** `GET /api/issues*`, ack/un-ack mutations (design §11.5, §16.2). */

import type { FastifyInstance } from "fastify";
import type { AckStore } from "../ack-store.js";
import type { IssueIndex } from "../issue-index.js";
import type { WsHub } from "../ws-hub.js";
import type { LogDb } from "../log-db.js";
import type { ServerFrame } from "@edumatcher/log-types";

export function registerIssuesRoutes(
  app: FastifyInstance,
  issueIndex: IssueIndex,
  ackStore: AckStore,
  logDb: LogDb,
  wsHub: WsHub,
): void {
  app.get("/api/issues", async (request) => {
    const q = request.query as Record<string, unknown>;
    const acked = q.acked === "true" ? true : q.acked === "false" ? false : undefined;
    const minLevel = q.min_level ? String(q.min_level).toUpperCase() : undefined;
    return { issues: issueIndex.list({ acked, minLevel }) };
  });

  app.get("/api/issues/:fingerprint/events", async (request, reply) => {
    const { fingerprint } = request.params as { fingerprint: string };
    const issue = issueIndex.get(fingerprint);
    if (!issue) return reply.status(404).send({ error: "not_found" });
    try {
      const rows = logDb.queryEvents(
        { processes: [issue.process], loggers: [issue.logger], minLevel: issue.level },
        { limit: 200, direction: "DESC" },
      );
      return { fingerprint, rows };
    } catch (err) {
      return reply.status(503).send({ error: "log_db_unavailable", message: String(err) });
    }
  });

  app.post("/api/issues/:fingerprint/ack", async (request, reply) => {
    const { fingerprint } = request.params as { fingerprint: string };
    const body = request.body as { ackedBy?: string; note?: string } | undefined;
    const issue = issueIndex.get(fingerprint);
    if (!issue) return reply.status(404).send({ error: "not_found" });
    if (!body?.ackedBy) {
      return reply.status(400).send({ error: "invalid_request", message: "ackedBy is required" });
    }

    const ack = ackStore.ack({
      fingerprint,
      ackedBy: body.ackedBy,
      note: body.note ?? null,
      ackedThroughSeq: issue.lastSeq,
      level: issue.level,
      process: issue.process,
      logger: issue.logger,
      sampleMessage: issue.sampleMessage,
    });
    const frame: ServerFrame = { t: "ack", fingerprint, ack };
    wsHub.broadcastAll(frame);
    return { ack };
  });

  app.delete("/api/issues/:fingerprint/ack", async (request) => {
    const { fingerprint } = request.params as { fingerprint: string };
    const body = request.body as { by?: string } | undefined;
    ackStore.unack(fingerprint, body?.by ?? "unknown");
    const frame: ServerFrame = { t: "ack", fingerprint, ack: null };
    wsHub.broadcastAll(frame);
    return { ok: true };
  });
}

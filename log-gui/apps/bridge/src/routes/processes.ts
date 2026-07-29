/** `GET /api/processes` (design §10.2, §16.2). */

import type { FastifyInstance } from "fastify";
import type { LogDb } from "../log-db.js";

export function registerProcessesRoutes(app: FastifyInstance, logDb: LogDb): void {
  app.get("/api/processes", async (_request, reply) => {
    try {
      return { processes: logDb.processes() };
    } catch (err) {
      return reply.status(503).send({ error: "log_db_unavailable", message: String(err) });
    }
  });
}

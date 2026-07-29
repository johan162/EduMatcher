/** `GET /api/healthz`, `GET /api/bridge/status` (design §13.2, §16.2). */

import type { FastifyInstance } from "fastify";
import type { AckStore } from "../ack-store.js";
import type { LogDb } from "../log-db.js";
import type { LalfPsUplink } from "../lalf-ps-uplink.js";
import type { WsHub } from "../ws-hub.js";

export function registerStatusRoutes(
  app: FastifyInstance,
  uplink: LalfPsUplink,
  logDb: LogDb,
  ackStore: AckStore,
  wsHub: WsHub,
  fingerprintCount: () => number,
): void {
  app.get("/api/healthz", async () => ({ ok: true }));

  app.get("/api/bridge/status", async () => ({
    lalfPs: {
      ok: uplink.currentState === "ACTIVE",
      detail: uplink.currentState,
    },
    logDb: logDb.health,
    wsClients: wsHub.clientCount,
    fingerprintsIndexed: fingerprintCount(),
    acksStored: ackStore.ackedCount,
    subId: uplink.subId,
    lastSeq: uplink.lastSeq,
  }));
}

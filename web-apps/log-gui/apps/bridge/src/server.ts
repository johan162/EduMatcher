/**
 * Fastify backend for pm-log-ui (design §6.4, §16).
 *
 * Holds exactly one LALF-PS subscription regardless of browser tab count
 * (§6.5), one read-only handle on `log.db`, and one read-write handle on its
 * own ack store. Never writes to `log.db` (§19).
 */

import cors from "@fastify/cors";
import helmet from "@fastify/helmet";
import fastifyStatic from "@fastify/static";
import websocketPlugin from "@fastify/websocket";
import Fastify from "fastify";
import { resolve } from "node:path";
import type { ServerFrame, ServerState } from "@edumatcher/log-types";
import { AckStore } from "./ack-store.js";
import { loadBridgeConfig } from "./config.js";
import { RollingCounters } from "./counters.js";
import { IssueIndex } from "./issue-index.js";
import { LalfPsUplink } from "./lalf-ps-uplink.js";
import { LiveBatcher } from "./live-batcher.js";
import { LogDb } from "./log-db.js";
import { registerDiagnosticsRoutes } from "./routes/diagnostics.js";
import { registerIssuesRoutes } from "./routes/issues.js";
import { registerLogsRoutes } from "./routes/logs.js";
import { registerProcessesRoutes } from "./routes/processes.js";
import { registerStatsRoutes } from "./routes/stats.js";
import { registerStatusRoutes } from "./routes/status.js";
import { registerUiConfigRoutes } from "./routes/ui-config.js";
import { WsHub } from "./ws-hub.js";

const config = loadBridgeConfig();

const app = Fastify({ logger: { level: process.env.LOG_LEVEL ?? "info" } });

await app.register(helmet, { contentSecurityPolicy: false });
await app.register(cors, { origin: config.corsOrigin });
await app.register(websocketPlugin);

app.log.info(
  `Resolved paths — log.db: ${resolve(config.logDb.path)}, ack store: ${resolve(config.ackStore.path)}, cwd: ${process.cwd()}`,
);

const logDb = new LogDb(config.logDb.path);
logDb.open();

const ackStore = new AckStore(config.ackStore.path);
const issueIndex = new IssueIndex(ackStore, config.issues.minLevel);
const counters = new RollingCounters();
const wsHub = new WsHub();

// Live rows go out one frame each until the ingest rate exceeds
// LIVE_BATCH_THRESHOLD_PER_SEC, then coalesced (design §6.4, §17).
const liveBatcher = new LiveBatcher({
  thresholdPerSec: config.limits.liveBatchThresholdPerSec,
  emitOne: (row) => wsHub.broadcastRow(row),
  emitMany: (rows) => wsHub.broadcastRows(rows),
});

// Backfill the fingerprint index over the issue-retention window at startup
// (design §11.5) — rebuildable, so a failure here is non-fatal.
try {
  const cutoff = new Date(Date.now() - config.issues.retentionDays * 86_400_000).toISOString();
  const rows = logDb.queryEvents(
    { minLevel: config.issues.minLevel, from: cutoff },
    { limit: 50_000, direction: "ASC" },
  );
  issueIndex.seed(rows);
  app.log.info(`Seeded issue index with ${rows.length} rows from the last ${config.issues.retentionDays}d`);
} catch (err) {
  app.log.warn(`Issue-index backfill skipped: ${String(err)}`);
}

const uplink = new LalfPsUplink({
  host: config.lalfPs.host,
  pubPort: config.lalfPs.pubPort,
  pullPort: config.lalfPs.pullPort,
  subIdPrefix: config.lalfPs.subIdPrefix,
  leaseSec: config.lalfPs.leaseSec,
});

uplink.on("event", (rows) => {
  for (const row of rows) {
    counters.ingest(row);
    liveBatcher.ingest(row);

    const issue = issueIndex.ingest(row);
    if (issue) {
      const frame: ServerFrame = { t: "issue", issue };
      wsHub.broadcastAll(frame);
    }
  }
});

uplink.on("server_state", (payload) => {
  const state: ServerState = {
    server: String(payload.server ?? ""),
    state: payload.state === "UP" ? "UP" : "DOWN",
    proto: String(payload.proto ?? ""),
    subscribers: Number(payload.subscribers ?? 0),
    activeBackfills: Number(payload.active_backfills ?? 0),
    lastSeq: Number(payload.last_seq ?? 0),
    inboxDropped: Number(payload.inbox_dropped ?? 0),
    defaultLeaseSec: Number(payload.default_lease_sec ?? 0),
    timestamp: Number(payload.timestamp ?? Date.now() / 1000),
  };
  const frame: ServerFrame = { t: "server_state", state };
  wsHub.broadcastAll(frame);
});

// Counters at ~1 Hz regardless of ingest rate (design §6.4, §17).
setInterval(() => {
  const frame: ServerFrame = { t: "counters", window: counters.snapshot() };
  wsHub.broadcastAll(frame);
}, 1000);

// Bridge/source health at 10s — mirrors the REST /api/bridge/status shape
// so a tab can show staleness without a fetch on every render (design §7.4).
setInterval(() => {
  const frame: ServerFrame = {
    t: "bridge_status",
    lalfPs: { ok: uplink.currentState === "ACTIVE", detail: uplink.currentState },
    logDb: logDb.health,
    wsClients: wsHub.clientCount,
  };
  wsHub.broadcastAll(frame);
}, 10_000);

// Age out issues with no activity beyond the retention window (design §11.4).
setInterval(
  () => {
    const cutoff = new Date(Date.now() - config.issues.retentionDays * 86_400_000).toISOString();
    issueIndex.pruneOlderThan(cutoff);
  },
  60 * 60 * 1000,
);

await uplink.start();

app.get("/ws/stream", { websocket: true }, (socket) => {
  wsHub.register(socket);
  const hello: ServerFrame = {
    t: "hello",
    subId: uplink.subId,
    serverName: null,
    lastSeq: uplink.lastSeq,
  };
  socket.send(JSON.stringify(hello));
});

registerLogsRoutes(app, logDb, config.limits.queryMaxRows, config.limits.exportMaxRows);
registerUiConfigRoutes(app, config);
registerStatsRoutes(app, logDb);
registerProcessesRoutes(app, logDb);
registerIssuesRoutes(app, issueIndex, ackStore, logDb, wsHub);
registerDiagnosticsRoutes(app, config.logDb.path, (process.env.LOG_CLI_COMMAND ?? "pm-log-cli").split(" "));
registerStatusRoutes(app, uplink, logDb, ackStore, wsHub, () => issueIndex.list().length);

// Single-container mode: serve the built frontend (design mirrors config-gui's deployment).
if (config.staticDir) {
  const { isAbsolute, resolve } = await import("node:path");
  const root = isAbsolute(config.staticDir) ? config.staticDir : resolve(process.cwd(), config.staticDir);
  await app.register(fastifyStatic, { root });
  app.setNotFoundHandler((request, reply) => {
    if (request.method === "GET" && !request.url.startsWith("/api") && !request.url.startsWith("/ws")) {
      return reply.sendFile("index.html");
    }
    return reply.status(404).send({ error: "not_found" });
  });
}

async function shutdown(): Promise<void> {
  // Flush before the sockets close, or a buffered batch is silently dropped.
  liveBatcher.stop();
  await uplink.stop();
  await app.close();
  process.exit(0);
}
process.on("SIGINT", () => void shutdown());
process.on("SIGTERM", () => void shutdown());

try {
  await app.listen({ host: config.host, port: config.port });
  app.log.info(`pm-log-bridge listening on http://${config.host}:${config.port}`);
} catch (err) {
  app.log.error(err);
  process.exit(1);
}

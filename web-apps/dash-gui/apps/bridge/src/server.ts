/**
 * `pm-dash-bridge` — Fastify backend for the operator dashboard (design §6, §11).
 *
 * Holds one ZeroMQ subscription to pm-monitor and one read-only handle on its
 * metrics.db however many tabs are open (log-gui's pattern), fans snapshots
 * and events out to every tab on `/ws`, serves history over REST and the
 * built web UI.
 */

import cors from "@fastify/cors";
import helmet from "@fastify/helmet";
import fastifyStatic from "@fastify/static";
import websocketPlugin from "@fastify/websocket";
import Fastify, { type FastifyInstance } from "fastify";
import { readFileSync } from "node:fs";
import { isAbsolute, resolve } from "node:path";
import type { BridgeStatus, HelloFrame } from "@edumatcher/dash-types";
import type { BridgeConfig } from "./config.js";
import { registerHistoryRoutes } from "./history-routes.js";
import type { Logger } from "./logging/logger.js";
import { MetricsDb } from "./metrics-db.js";
import { MonitorUplink } from "./monitor-uplink.js";
import { WsHub } from "./ws-fanout.js";

export interface Bridge {
  app: FastifyInstance;
  uplink: MonitorUplink;
  hub: WsHub;
  db: MetricsDb;
  close(): Promise<void>;
}

export const VERSION = (
  JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")) as { version: string }
).version;

/** A snapshot or event payload framed for the browser without re-serialising it. */
function frame(type: "snapshot" | "event", json: string): string {
  return `{"type":"${type}","data":${json}}`;
}

export interface BuildOptions {
  /** Start the ZeroMQ subscription (tests feed the uplink directly instead). */
  connect?: boolean;
  now?: () => number;
}

export async function buildBridge(config: BridgeConfig, log: Logger, opts: BuildOptions = {}): Promise<Bridge> {
  const app = Fastify({ logger: false });
  await app.register(helmet, { contentSecurityPolicy: false });
  await app.register(cors, { origin: config.corsOrigin });
  await app.register(websocketPlugin);

  const hub = new WsHub(config.maxWsClients, {
    pingSec: config.wsPingSec,
    pingMaxMissed: config.wsPingMaxMissed,
    maxBufferedBytes: config.wsMaxBufferedBytes,
  });
  const uplink = new MonitorUplink({
    host: config.monitor.host,
    pubPort: config.monitor.pubPort,
    downAfterSec: config.monitor.downAfterSec,
    now: opts.now,
  });
  const db = new MetricsDb(config.metricsDbPath, config.rawHours);
  const source = `${config.monitor.host}:${config.monitor.pubPort}`;

  uplink.on("snapshot", (s) => hub.broadcast(frame("snapshot", s.json)));
  uplink.on("event", (e) => hub.broadcast(frame("event", e.json)));
  uplink.on("state", (state) => {
    if (state === "UP") log.info("dash-bridge.uplink", `pm-monitor at ${source} UP`);
    else log.warn("dash-bridge.uplink", `pm-monitor at ${source} DOWN: no snapshot for ${config.monitor.downAfterSec} s`);
    hub.toAll({ type: "monitor_state", monitor: state });
  });

  app.get("/ws", { websocket: true }, (socket) => {
    const latest = uplink.latest;
    const hello: HelloFrame = {
      type: "hello",
      version: VERSION,
      monitor: uplink.state,
      sessionTz: latest?.data.exchange?.session_timezone || "UTC",
    };
    const opening = [JSON.stringify(hello)];
    if (latest) opening.push(frame("snapshot", latest.json));
    if (!hub.register(socket, opening)) {
      log.warn("dash-bridge.ws-fanout", `max_ws_clients=${config.maxWsClients} reached; refusing connection`);
      socket.close(1013, "max clients reached");
    }
  });

  app.get(
    "/api/bridge/status",
    (): BridgeStatus => ({
      version: VERSION,
      monitor: uplink.state,
      monitorSince: new Date(uplink.stateSince).toISOString(),
      source,
      snapshotsIn: uplink.snapshotsIn,
      eventsIn: uplink.eventsIn,
      lastSnapshotTs: uplink.latest?.data.ts ?? null,
      metricsDb: { path: config.metricsDbPath, ...db.health },
      wsClients: hub.clientCount,
      logging: log.destination(),
    }),
  );

  registerHistoryRoutes(app, db, opts.now);

  if (config.staticDir) {
    const root = isAbsolute(config.staticDir) ? config.staticDir : resolve(process.cwd(), config.staticDir);
    await app.register(fastifyStatic, { root });
    app.setNotFoundHandler((request, reply) => {
      if (request.method === "GET" && !request.url.startsWith("/api") && !request.url.startsWith("/ws")) {
        return reply.sendFile("index.html");
      }
      return reply.status(404).send({ error: "not_found", message: `${request.method} ${request.url}` });
    });
  }

  if (opts.connect !== false) uplink.start();

  return {
    app,
    uplink,
    hub,
    db,
    async close() {
      uplink.stop();
      hub.stop();
      await app.close();
      db.close();
    },
  };
}

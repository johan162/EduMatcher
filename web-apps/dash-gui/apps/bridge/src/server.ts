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
import type { BridgeStatus, HelloFrame, MarketSessionFrame } from "@edumatcher/dash-types";
import { CalfSessionUplink } from "./calf-session.js";
import type { BridgeConfig } from "./config.js";
import { registerHistoryRoutes } from "./history-routes.js";
import type { Logger } from "./logging/logger.js";
import { MetricsDb, QueryError } from "./metrics-db.js";
import { MonitorUplink } from "./monitor-uplink.js";
import { knownTimeZone } from "./session-time.js";
import { ThresholdSource } from "./thresholds.js";
import { WsHub } from "./ws-fanout.js";

export interface Bridge {
  app: FastifyInstance;
  uplink: MonitorUplink;
  session: CalfSessionUplink;
  hub: WsHub;
  db: MetricsDb;
  close(): Promise<void>;
}

/**
 * The release version: the web app's version.json, which scripts/mkbld.sh
 * writes for every GUI, so the top bar, `hello` and /api/bridge/status all
 * say the same (the workspace package.json versions are never bumped).
 */
export const VERSION = (
  JSON.parse(readFileSync(new URL("../../web/src/version.json", import.meta.url), "utf8")) as { version: string }
).version;

/** A snapshot or event payload framed for the browser without re-serialising it. */
function frame(type: "snapshot" | "event", json: string): string {
  return `{"type":"${type}","data":${json}}`;
}

export interface BuildOptions {
  /** Start the ZeroMQ subscription and the CALF connection (tests feed the uplinks directly instead). */
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
  let lastErrorLogMs = -Infinity;
  const uplink = new MonitorUplink({
    host: config.monitor.host,
    pubPort: config.monitor.pubPort,
    downAfterSec: config.monitor.downAfterSec,
    now: opts.now,
    // At most one line a minute: a message that fails tends to fail at 1 Hz.
    onError: (err) => {
      const t = Date.now();
      if (t - lastErrorLogMs < 60_000) return;
      lastErrorLogMs = t;
      log.error("dash-bridge.uplink", `a pm-monitor message failed in the bridge (${uplink.handlerErrors} so far): ${String(err)}`);
    },
  });
  const session = new CalfSessionUplink(config.calf);
  const db = new MetricsDb(config.metricsDbPath);
  const source = `${config.monitor.host}:${config.monitor.pubPort}`;

  // The exchange's session timezone: the latest snapshot's, else the one
  // pm-monitor pinned in metrics.db, else UTC. A snapshot's stays known
  // after DOWN, so frozen data keeps its clock.
  let snapshotTz: string | null = null;
  let warnedTz: string | null = null;
  const sessionTz = (): string => {
    const tz = snapshotTz ?? db.sessionTimezone();
    if (!tz) return "UTC";
    if (knownTimeZone(tz)) return tz;
    if (warnedTz !== tz) {
      warnedTz = tz;
      log.warn("dash-bridge.time", `session timezone ${tz} is unknown to this Node's ICU; using UTC`);
    }
    return "UTC";
  };

  const downReason = (): string =>
    uplink.connected
      ? `connected, but no snapshot for ${config.monitor.downAfterSec} s`
      : `not reachable at ${source} -- check MONITOR_HOST/MONITOR_PUB_PORT and pm-monitor's bind address`;

  uplink.on("snapshot", (s) => {
    snapshotTz = s.data.exchange?.session_timezone || snapshotTz;
    hub.broadcast(frame("snapshot", s.json));
  });
  uplink.on("event", (e) => hub.broadcast(frame("event", e.json)));
  uplink.on("state", (state) => {
    if (state === "UP") log.info("dash-bridge.uplink", `pm-monitor at ${source} UP`);
    else log.warn("dash-bridge.uplink", `pm-monitor DOWN: ${downReason()}`);
    hub.toAll({ type: "monitor_state", monitor: state });
  });

  const sessionFrame = (s = session.latest): MarketSessionFrame => ({ type: "market_session", session: s });
  session.on("session", (s) => hub.toAll(sessionFrame(s)));

  app.get("/ws", { websocket: true }, (socket) => {
    const latest = uplink.latest;
    const hello: HelloFrame = {
      type: "hello",
      version: VERSION,
      monitor: uplink.state,
      sessionTz: sessionTz(),
    };
    const opening = [JSON.stringify(hello)];
    if (latest) opening.push(frame("snapshot", latest.json));
    opening.push(JSON.stringify(sessionFrame()));
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
      monitorConnected: uplink.connected,
      snapshotsIn: uplink.snapshotsIn,
      eventsIn: uplink.eventsIn,
      invalidIn: uplink.invalidIn,
      handlerErrors: uplink.handlerErrors,
      lastSnapshotTs: uplink.latest?.data.ts ?? null,
      sessionTz: sessionTz(),
      metricsDb: { path: config.metricsDbPath, ...db.health },
      wsClients: hub.clientCount,
      logging: log.destination(),
      links: config.links,
    }),
  );

  registerHistoryRoutes(app, db, sessionTz, opts.now);

  // The rules pm-monitor judges by: the widgets' bands while nothing is in breach (I113).
  const thresholds = new ThresholdSource(config.configArtifactPath);
  app.get("/api/thresholds", (_request, reply) => {
    try {
      return thresholds.read();
    } catch (err) {
      if (err instanceof QueryError) return reply.status(err.status).send({ error: err.code, message: err.message });
      throw err;
    }
  });

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

  // DOWN from the start is not a state change: say once why nothing arrives.
  let firstCheck: ReturnType<typeof setTimeout> | undefined;
  if (opts.connect !== false) {
    uplink.start();
    session.start();
    firstCheck = setTimeout(() => {
      if (uplink.snapshotsIn === 0) log.warn("dash-bridge.uplink", `no snapshot from pm-monitor yet: ${downReason()}`);
    }, config.monitor.downAfterSec * 1000);
    firstCheck.unref();
  }

  return {
    app,
    uplink,
    session,
    hub,
    db,
    async close() {
      clearTimeout(firstCheck);
      uplink.stop();
      session.stop();
      hub.stop();
      await app.close();
      db.close();
    },
  };
}

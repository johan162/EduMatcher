/**
 * `pm-dash-bridge` — Fastify backend for the operator dashboard (design §6, §11).
 *
 * WP-C1 scaffold: serves the built web UI, the `/ws` endpoint (a `hello`
 * frame) and `/api/bridge/status`. WP-C2 adds the pm-monitor uplink, the
 * snapshot/event fan-out and the metrics.db history routes.
 */

import cors from "@fastify/cors";
import helmet from "@fastify/helmet";
import fastifyStatic from "@fastify/static";
import websocketPlugin from "@fastify/websocket";
import Fastify, { type FastifyInstance } from "fastify";
import { readFileSync } from "node:fs";
import { isAbsolute, resolve } from "node:path";
import type { BridgeStatus, MonitorState, ServerFrame } from "@edumatcher/dash-types";
import type { BridgeConfig } from "./config.js";
import type { Logger } from "./logging/logger.js";
import { WsHub } from "./ws-fanout.js";

export interface Bridge {
  app: FastifyInstance;
  hub: WsHub;
  close(): Promise<void>;
}

const VERSION = (
  JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")) as { version: string }
).version;

export async function buildBridge(config: BridgeConfig, log: Logger): Promise<Bridge> {
  const app = Fastify({ logger: false });
  await app.register(helmet, { contentSecurityPolicy: false });
  await app.register(cors, { origin: config.corsOrigin });
  await app.register(websocketPlugin);

  const hub = new WsHub(config.maxWsClients, {
    pingSec: config.wsPingSec,
    pingMaxMissed: config.wsPingMaxMissed,
    maxBufferedBytes: config.wsMaxBufferedBytes,
  });
  const source = `${config.monitor.host}:${config.monitor.pubPort}`;
  // Until WP-C2's uplink exists there is nothing to receive from.
  const monitor: MonitorState = "DOWN";

  app.get("/ws", { websocket: true }, (socket) => {
    const hello: ServerFrame = { type: "hello", version: VERSION, monitor, sessionTz: "UTC" };
    if (!hub.register(socket, hello)) {
      log.warn("dash-bridge.ws-fanout", `max_ws_clients=${config.maxWsClients} reached; refusing connection`);
      socket.close(1013, "max clients reached");
    }
  });

  app.get(
    "/api/bridge/status",
    (): BridgeStatus => ({
      version: VERSION,
      monitor,
      source,
      metricsDb: config.metricsDbPath,
      wsClients: hub.clientCount,
      logging: log.destination(),
    }),
  );

  if (config.staticDir) {
    const root = isAbsolute(config.staticDir) ? config.staticDir : resolve(process.cwd(), config.staticDir);
    await app.register(fastifyStatic, { root });
    app.setNotFoundHandler((request, reply) => {
      if (request.method === "GET" && !request.url.startsWith("/api") && !request.url.startsWith("/ws")) {
        return reply.sendFile("index.html");
      }
      return reply.status(404).send({ error: "not_found" });
    });
  }

  return {
    app,
    hub,
    async close() {
      hub.stop();
      await app.close();
    },
  };
}

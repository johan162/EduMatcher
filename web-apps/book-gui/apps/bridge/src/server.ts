/**
 * `pm-book-bridge` — Fastify backend for the order book viewer (design §5).
 *
 * Holds one upstream market-data WebSocket to `pm-api-gwy` however many tabs
 * are open, reads history over REST with the same read-only key, and serves
 * the built web UI. No credential of any kind reaches the browser.
 */

import cors from "@fastify/cors";
import helmet from "@fastify/helmet";
import fastifyStatic from "@fastify/static";
import websocketPlugin from "@fastify/websocket";
import Fastify, { type FastifyInstance } from "fastify";
import { isAbsolute, resolve } from "node:path";
import { BookService } from "./book-service.js";
import type { BridgeConfig } from "./config.js";
import type { Logger } from "./logging/logger.js";
import { HistoryClient } from "./session/history-seed.js";
import { MarketUplink } from "./upstream/market-uplink.js";
import { WsHub } from "./ws-fanout.js";

export interface Bridge {
  app: FastifyInstance;
  uplink: MarketUplink;
  service: BookService;
  hub: WsHub;
  close(): Promise<void>;
}

/** `http://host:port` → `ws://host:port/api/v1/market-data` (and https → wss). */
export function marketDataUrl(baseUrl: string): string {
  const url = new URL("/api/v1/market-data", baseUrl.replace(/\/+$/, "") + "/");
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export async function buildBridge(config: BridgeConfig, log: Logger): Promise<Bridge> {
  const app = Fastify({ logger: false });
  await app.register(helmet, { contentSecurityPolicy: false });
  await app.register(cors, { origin: config.corsOrigin });
  await app.register(websocketPlugin);

  const source = new URL(config.apiGateway.baseUrl).host;
  const uplink = new MarketUplink({
    url: marketDataUrl(config.apiGateway.baseUrl),
    apiKey: config.apiGateway.apiKey,
    pingSec: config.upstream.pingSec,
    pingMaxMissed: config.upstream.pingMaxMissed,
    downAfterSec: config.upstream.downAfterSec,
  });
  const history = new HistoryClient({ baseUrl: config.apiGateway.baseUrl, apiKey: config.apiGateway.apiKey });
  const service = new BookService(uplink, history, config.tapeMax, log);
  const hub = new WsHub(service, config.maxWsClients, {
    pingSec: config.wsPingSec,
    pingMaxMissed: config.wsPingMaxMissed,
    maxBufferedBytes: config.wsMaxBufferedBytes,
  });

  const status = () => ({
    type: "bridge_status" as const,
    upstream: uplink.state,
    since: uplink.stateSince,
    wsClients: hub.clientCount,
  });

  service.on("symbolFrame", (sym, frame) => hub.toSymbol(sym, frame));
  service.on("frame", (frame) => hub.toAll(frame));

  uplink.on("status", (state) => {
    if (state === "ACTIVE") log.info("book-bridge.upstream", `market-data connection to ${source} ACTIVE`);
    else log.warn("book-bridge.upstream", `market-data connection to ${source} ${state}`);
    hub.toAll(status());
  });
  uplink.on("authRejected", () =>
    log.critical(
      "book-bridge.upstream",
      `${source} refused PM_BOOK_API_KEY — is it a read-only key of that instance?`,
    ),
  );

  // Terminal-gui's liveness heartbeat: a silent tab can tell a quiet feed from a dead socket.
  const heartbeat = setInterval(() => hub.toAll(status()), config.wsHeartbeatSec * 1000);
  heartbeat.unref();

  app.get("/ws/stream", { websocket: true }, (socket) => {
    const hello = { type: "hello" as const, symbols: service.symbols, upstream: uplink.state, source };
    if (!hub.register(socket, hello)) {
      log.warn("book-bridge.ws-fanout", `max_ws_clients=${config.maxWsClients} reached; refusing connection`);
      socket.close(1013, "max clients reached");
    }
  });

  app.get("/api/bridge/status", () => ({
    upstream: uplink.state,
    since: uplink.stateSince,
    source,
    symbols: service.symbols.length,
    watched: service.watched(),
    wsClients: hub.clientCount,
    logging: log.destination(),
  }));

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

  if (!config.apiGateway.apiKey) {
    log.critical("book-bridge.main", "PM_BOOK_API_KEY is unset — no market data or history can be read");
  } else {
    uplink.start();
    void service.refreshSymbols();
  }

  return {
    app,
    uplink,
    service,
    hub,
    async close() {
      clearInterval(heartbeat);
      hub.stop();
      uplink.stop();
      await app.close();
    },
  };
}

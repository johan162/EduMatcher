/**
 * `pm-terminal-bridge` — Fastify backend for the market data terminal
 * (design §6, §17).
 *
 * Holds exactly one upstream live-data connection (CALF, to `pm-md-gwy`)
 * regardless of how many browser tabs are open, plus one REST client to
 * `pm-api-gwy` for `/history/*` only. No credential of any kind reaches the
 * browser (§18).
 */

import cors from "@fastify/cors";
import helmet from "@fastify/helmet";
import fastifyStatic from "@fastify/static";
import websocketPlugin from "@fastify/websocket";
import Fastify from "fastify";
import { isAbsolute, resolve } from "node:path";
import type { ServerFrame } from "@edumatcher/terminal-types";
import { CalfUplink } from "./calf/uplink.js";
import { loadBridgeConfig } from "./config.js";
import { registerHistoryRoutes } from "./history-proxy.js";
import { createLogger } from "./logging/logger.js";
import { WsHub } from "./ws-fanout.js";

const config = loadBridgeConfig();
const log = await createLogger(config);

const app = Fastify({ logger: false });

await app.register(helmet, { contentSecurityPolicy: false });
await app.register(cors, { origin: config.corsOrigin });
await app.register(websocketPlugin);

log.info(
  "terminal-bridge.main",
  `startup: bind=${config.host}:${config.port} calf=${config.calf.host}:${config.calf.port} ` +
    `api=${config.apiGateway.baseUrl} logging=${log.destination()}`,
);

if (!config.apiGateway.apiKey) {
  // The live feed still works without this; only /history/* is affected.
  log.error("terminal-bridge.history-proxy", "PM_TERMINAL_API_KEY is unset — history endpoints will fail");
}

const uplink = new CalfUplink(config.calf);
const hub = new WsHub(uplink, config.maxWsClients);

uplink.on("frame", (frame: ServerFrame) => hub.broadcast(frame));

uplink.on("welcome", (welcome) => {
  log.info(
    "terminal-bridge.calf.uplink",
    `handshake ok: gw=${welcome.gateway} channels=${[...welcome.chSupported].join(",")} ` +
      `symbols=${welcome.symbols.length} indexes=${config.calf.indexIds.length}`,
  );
});

uplink.on("status", (state) => {
  if (state === "RECONNECTING")
    log.warn("terminal-bridge.calf.uplink", "CALF connection dropped; reconnecting");
  else log.info("terminal-bridge.calf.uplink", `CALF connection ${state}`);

  hub.broadcast({ type: "bridge_status", calf: state, since: uplink.stateSince, wsClients: hub.clientCount });
});

// A tab's `hello` is a point-in-time snapshot of the universe; this keeps
// already-open tabs current as the gateway learns of more instruments.
uplink.on("symbol", () => hub.broadcast({ type: "symbols", symbols: uplink.symbols() }));

uplink.on("subscription", ({ action, ch, sym, held }) => {
  log.info("terminal-bridge.calf.symbol-refcount", `${action} CH=${ch} SYM=${sym} (${held} held)`);
});

uplink.on("gatewayError", ({ code, detail }) => {
  log.warn("terminal-bridge.calf.uplink", `gateway ERR ${code}: ${JSON.stringify(detail)}`);
});

uplink.on("gap", ({ ch, sym, ts }) => {
  log.warn("terminal-bridge.calf.uplink", `unrepaired gap CH=${ch} SYM=${sym}`);
  hub.broadcast({ type: "gap", ch, sym, ts });
});

uplink.start();

app.get("/ws/stream", { websocket: true }, (socket) => {
  if (!hub.register(socket)) {
    log.warn(
      "terminal-bridge.ws-fanout",
      `max_ws_clients=${config.maxWsClients} reached; refusing connection`,
    );
    socket.close(1013, "max clients reached");
    return;
  }

  log.info("terminal-bridge.ws-fanout", `browser connected (${hub.clientCount} open)`);
  hub.sendTo(socket, {
    type: "hello",
    symbols: uplink.symbols(),
    tickDecimals: uplink.tickDecimals(),
    indexes: config.calf.indexIds,
    calf: uplink.state,
    gateway: uplink.gateway,
  });
  socket.on("close", () =>
    log.info("terminal-bridge.ws-fanout", `browser disconnected (${hub.clientCount} open)`),
  );
});

registerHistoryRoutes(app, { baseUrl: config.apiGateway.baseUrl, apiKey: config.apiGateway.apiKey });

app.get("/api/bridge/status", () => ({
  calf: uplink.state,
  since: uplink.stateSince,
  gateway: uplink.gateway,
  symbols: uplink.symbols().length,
  indexes: config.calf.indexIds,
  wsClients: hub.clientCount,
  logging: log.destination(),
}));

// Single-container mode: serve the built frontend, same as log-gui's bridge.
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

async function shutdown(signal: string): Promise<void> {
  log.info("terminal-bridge.main", `${signal} received; shutting down`);
  await uplink.stop();
  await app.close();
  await log.close();
  process.exit(0);
}
process.on("SIGINT", () => void shutdown("SIGINT"));
process.on("SIGTERM", () => void shutdown("SIGTERM"));

try {
  await app.listen({ host: config.host, port: config.port });
  log.info("terminal-bridge.main", `listening on http://${config.host}:${config.port}`);
} catch (err) {
  log.critical("terminal-bridge.main", `failed to bind ${config.host}:${config.port}: ${String(err)}`);
  process.exit(1);
}

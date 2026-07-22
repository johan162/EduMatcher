/**
 * Fastify backend for config-gui (design §14).
 *
 * Stateless: every request carries a complete draft. No server-side persistence
 * of drafts or secrets (design §15). The only subprocess-spawning route is
 * /api/config/verify, which uses execFile with a fixed argv.
 */

import cors from "@fastify/cors";
import helmet from "@fastify/helmet";
import fastifyStatic from "@fastify/static";
import Fastify from "fastify";
import { z } from "zod";
import {
  DEFAULT_API_GATEWAY,
  DEFAULT_BALF_GATEWAY,
  DEFAULT_CB_LADDER,
  DEFAULT_CB_WINDOW_NS,
  DEFAULT_DEPTH_SNAPSHOT_TOLERANCE_TICKS,
  DEFAULT_DROP_COPY_BUFFER_SIZE,
  DEFAULT_DYNAMIC_BAND_PCT,
  DEFAULT_MARKET_DATA_GATEWAY,
  DEFAULT_MM_MIN_QTY,
  DEFAULT_MM_SPREAD_TICKS,
  DEFAULT_POST_TRADE_GATEWAY,
  DEFAULT_QUOTE_HISTORY_MAXLEN,
  DEFAULT_RECENT_TRADES_MAXLEN,
  DEFAULT_SCHEDULE,
  DEFAULT_SNAPSHOT_INTERVAL_SEC,
  DEFAULT_STATIC_BAND_PCT,
  DEFAULT_TICK_DECIMALS,
  engineConfigDraftSchema,
} from "@edumatcher/schema";
import { evaluateDiagnostics } from "@edumatcher/diagnostics";
import { generateYaml, parseYamlToDraft } from "@edumatcher/yaml-codec";
import { loadServerConfig } from "./config.js";
import { CverifierUnavailableError, verifyYaml } from "./verify.js";

const serverConfig = loadServerConfig();

const app = Fastify({
  logger: { level: process.env.LOG_LEVEL ?? "info" },
  // Guard against oversized import payloads (design §15).
  bodyLimit: serverConfig.maxImportBytes + 64_000,
});

await app.register(helmet, { contentSecurityPolicy: false });
await app.register(cors, { origin: serverConfig.corsOrigin });

const importBody = z.object({ yaml: z.string().max(serverConfig.maxImportBytes) });
const validateBody = z.object({ draft: engineConfigDraftSchema });
const generateBody = z.object({
  draft: engineConfigDraftSchema,
  filename: z.string().min(1).optional(),
  command: z.string().optional(),
});
const verifyBody = z.object({ yaml: z.string().max(serverConfig.maxImportBytes) });

function badRequest(reply: import("fastify").FastifyReply, error: z.ZodError) {
  return reply.status(400).send({
    error: "invalid_request",
    issues: error.issues.map((i) => ({ path: i.path.join("."), message: i.message })),
  });
}

app.get("/api/healthz", async () => ({ ok: true }));

app.get("/api/defaults", async () => ({
  defaults: {
    snapshotIntervalSec: DEFAULT_SNAPSHOT_INTERVAL_SEC,
    quoteHistoryMaxlen: DEFAULT_QUOTE_HISTORY_MAXLEN,
    dropCopyBufferSize: DEFAULT_DROP_COPY_BUFFER_SIZE,
    recentTradesMaxlen: DEFAULT_RECENT_TRADES_MAXLEN,
    depthSnapshotToleranceTicks: DEFAULT_DEPTH_SNAPSHOT_TOLERANCE_TICKS,
    tickDecimals: DEFAULT_TICK_DECIMALS,
    staticBandPct: DEFAULT_STATIC_BAND_PCT,
    dynamicBandPct: DEFAULT_DYNAMIC_BAND_PCT,
    cbWindowNs: DEFAULT_CB_WINDOW_NS,
    cbLadder: DEFAULT_CB_LADDER,
    mmSpreadTicks: DEFAULT_MM_SPREAD_TICKS,
    mmMinQty: DEFAULT_MM_MIN_QTY,
    schedule: DEFAULT_SCHEDULE,
    postTradeGateway: DEFAULT_POST_TRADE_GATEWAY,
    marketDataGateway: DEFAULT_MARKET_DATA_GATEWAY,
    balfGateway: DEFAULT_BALF_GATEWAY,
    apiGateway: DEFAULT_API_GATEWAY,
  },
}));

app.post("/api/config/import", async (request, reply) => {
  const parsed = importBody.safeParse(request.body);
  if (!parsed.success) return badRequest(reply, parsed.error);
  try {
    const { draft, unmapped } = parseYamlToDraft(parsed.data.yaml);
    return { draft, unmapped };
  } catch (err) {
    return reply.status(422).send({
      error: "parse_failed",
      message: err instanceof Error ? err.message : "Could not parse YAML.",
    });
  }
});

app.post("/api/config/validate", async (request, reply) => {
  const parsed = validateBody.safeParse(request.body);
  if (!parsed.success) return badRequest(reply, parsed.error);
  return { diagnostics: evaluateDiagnostics(parsed.data.draft) };
});

app.post("/api/config/generate", async (request, reply) => {
  const parsed = generateBody.safeParse(request.body);
  if (!parsed.success) return badRequest(reply, parsed.error);
  const { draft, filename, command } = parsed.data;
  const yaml = generateYaml(draft, command ? { command } : {});
  return { yaml, filename: filename ?? draft.output.filename };
});

app.post("/api/config/verify", async (request, reply) => {
  const parsed = verifyBody.safeParse(request.body);
  if (!parsed.success) return badRequest(reply, parsed.error);
  try {
    const result = await verifyYaml(parsed.data.yaml, serverConfig.cverifierCommand);
    return result;
  } catch (err) {
    if (err instanceof CverifierUnavailableError) {
      return reply.status(503).send({
        error: "cverifier_unavailable",
        message:
          "pm-cverifier is not available on this deployment. This check is optional; the GUI's own diagnostics still apply.",
      });
    }
    throw err;
  }
});

// Single-container mode: serve the built frontend and fall back to index.html
// for client-side routes (design §12 deployment). Optional — the API is fully
// functional without it (dev uses the Vite server + proxy instead).
if (serverConfig.staticDir) {
  const { isAbsolute, resolve } = await import("node:path");
  const root = isAbsolute(serverConfig.staticDir)
    ? serverConfig.staticDir
    : resolve(process.cwd(), serverConfig.staticDir);
  await app.register(fastifyStatic, { root });
  app.setNotFoundHandler((request, reply) => {
    if (request.method === "GET" && !request.url.startsWith("/api")) {
      return reply.sendFile("index.html");
    }
    return reply.status(404).send({ error: "not_found" });
  });
}

try {
  await app.listen({ host: serverConfig.host, port: serverConfig.port });
  app.log.info(`config-gui API listening on http://${serverConfig.host}:${serverConfig.port}`);
} catch (err) {
  app.log.error(err);
  process.exit(1);
}

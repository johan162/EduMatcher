#!/usr/bin/env tsx
/**
 * pm-trading-ui-serve
 *
 * Zero-extra-dependency static file server for the EduMatcher Trading GUI
 * production build.  Serves `apps/web/dist/` (or the directory set by
 * $STATIC_DIR) over HTTP with:
 *
 *  - Correct MIME types for JS/CSS/WASM/SVG/fonts.
 *  - `Cache-Control: public, max-age=31536000, immutable` for hashed assets
 *    (any file under `assets/` or whose name contains a content hash).
 *  - `Cache-Control: no-cache` for `index.html` so browsers always revalidate
 *    the entry point and pick up new hashed bundles after a redeploy.
 *  - SPA fallback: every GET that doesn't resolve to a real file is served
 *    `index.html` so React Router handles the path client-side.
 *
 * Environment variables (all optional):
 *
 *   HOST          Bind address.        Default: 0.0.0.0
 *   PORT          Listen port.         Default: 4173
 *   STATIC_DIR    Absolute or CWD-relative path to the built SPA.
 *                 Default: <script-dir>/../../apps/web/dist
 *   API_PROXY_TARGET  Forward /api/* requests to this URL instead of 404-ing
 *                 them. Example: http://localhost:8080
 *                 When omitted, /api/* requests fall through to the SPA
 *                 (which will fail in the browser — always set this in prod).
 *
 * Usage:
 *   npm run serve              # from trader-gui/
 *   node --import tsx/esm apps/serve/serve.ts
 *   PORT=8088 STATIC_DIR=/opt/trader-dist npm run serve
 *
 * Pass --help to see these instructions at runtime.
 */

import * as fs from "node:fs";
import * as http from "node:http";
import * as path from "node:path";
import * as url from "node:url";

// ── --help ────────────────────────────────────────────────────────────────────
if (process.argv.includes("--help") || process.argv.includes("-h")) {
  // Print the JSDoc block above as inline help.
  const src = fs.readFileSync(url.fileURLToPath(import.meta.url), "utf8");
  const match = /\/\*\*([\s\S]+?)\*\//.exec(src);
  if (match?.[1]) console.log(match[1].replace(/^ \* ?/gm, "").trim());
  process.exit(0);
}

// ── Configuration ─────────────────────────────────────────────────────────────
const HOST = process.env["HOST"] ?? "0.0.0.0";
const PORT = parseInt(process.env["PORT"] ?? "4173", 10);
const API_PROXY_TARGET = process.env["API_PROXY_TARGET"] ?? "";

// Default: resolve relative to this file's location so `npm run serve` works
// from any CWD.
const __dirname = path.dirname(url.fileURLToPath(import.meta.url));
const STATIC_DIR = path.resolve(
  process.env["STATIC_DIR"] ?? path.join(__dirname, "..", "web", "dist"),
);

// ── MIME types ────────────────────────────────────────────────────────────────
const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".ico": "image/x-icon",
  ".webp": "image/webp",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".wasm": "application/wasm",
  ".map": "application/json; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".xml": "application/xml; charset=utf-8",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

/** True for the Vite-style hashed asset filenames, e.g. `index-CL2gZ16f.js`. */
function isHashedAsset(filePath: string): boolean {
  return filePath.startsWith(path.join(STATIC_DIR, "assets")) ||
    /\.[a-f0-9]{8,}\.\w+$/.test(filePath);
}

function sendFile(
  res: http.ServerResponse,
  filePath: string,
  statusCode = 200,
): void {
  const ext = path.extname(filePath).toLowerCase();
  const mime = MIME[ext] ?? "application/octet-stream";
  const cache = path.basename(filePath) === "index.html"
    ? "no-cache"
    : isHashedAsset(filePath)
      ? "public, max-age=31536000, immutable"
      : "public, max-age=3600";
  res.writeHead(statusCode, {
    "Content-Type": mime,
    "Cache-Control": cache,
    "X-Content-Type-Options": "nosniff",
  });
  fs.createReadStream(filePath).pipe(res);
}

function sendError(res: http.ServerResponse, code: number, msg: string): void {
  res.writeHead(code, { "Content-Type": "text/plain; charset=utf-8" });
  res.end(`${code} ${msg}\n`);
}

// ── Optional /api proxy ───────────────────────────────────────────────────────
function proxyApiRequest(
  req: http.IncomingMessage,
  res: http.ServerResponse,
): void {
  if (!API_PROXY_TARGET) {
    sendError(res, 502, "API_PROXY_TARGET not configured");
    return;
  }
  const target = new URL(API_PROXY_TARGET);
  const options: http.RequestOptions = {
    hostname: target.hostname,
    port: target.port || (target.protocol === "https:" ? 443 : 80),
    path: req.url,
    method: req.method,
    headers: { ...req.headers, host: target.host },
  };
  const proxy = http.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode ?? 502, proxyRes.headers);
    proxyRes.pipe(res, { end: true });
  });
  proxy.on("error", (err) => {
    console.error("[proxy]", err.message);
    if (!res.headersSent) sendError(res, 502, "Bad Gateway");
  });
  req.pipe(proxy, { end: true });
}

// ── Request handler ───────────────────────────────────────────────────────────
const INDEX = path.join(STATIC_DIR, "index.html");

function handler(req: http.IncomingMessage, res: http.ServerResponse): void {
  const method = req.method ?? "GET";
  const rawUrl = req.url ?? "/";

  // Strip query string for file resolution; keep only the pathname.
  const pathname = decodeURIComponent(rawUrl.split("?")[0] ?? "/");

  // Proxy /api/* to pm-api-gwy when target is configured.
  if (pathname.startsWith("/api/")) {
    if (API_PROXY_TARGET) {
      proxyApiRequest(req, res);
    } else {
      // Respond with a helpful 503 so the browser console is clear about
      // why API calls fail when serving locally without a proxy target.
      sendError(
        res,
        503,
        "No API_PROXY_TARGET configured — set API_PROXY_TARGET=http://localhost:8080 to forward /api/* to pm-api-gwy",
      );
    }
    return;
  }

  // Only serve GET/HEAD.
  if (method !== "GET" && method !== "HEAD") {
    sendError(res, 405, "Method Not Allowed");
    return;
  }

  // Normalise and sandbox: prevent path traversal.
  const rel = pathname === "/" ? "/index.html" : pathname;
  const abs = path.normalize(path.join(STATIC_DIR, rel));
  if (!abs.startsWith(STATIC_DIR + path.sep) && abs !== STATIC_DIR) {
    sendError(res, 403, "Forbidden");
    return;
  }

  // Try the exact path, then a directory index, then the SPA fallback.
  for (const candidate of [abs, path.join(abs, "index.html"), INDEX]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
      sendFile(res, candidate, candidate === INDEX && abs !== INDEX ? 200 : 200);
      return;
    }
  }

  sendError(res, 404, "Not Found");
}

// ── Start ─────────────────────────────────────────────────────────────────────
if (!fs.existsSync(STATIC_DIR)) {
  console.error(
    `[pm-trading-ui-serve] STATIC_DIR not found: ${STATIC_DIR}\n` +
    `  Run "npm run build" from trader-gui/ first, or set STATIC_DIR to the ` +
    `built dist/ directory.`,
  );
  process.exit(1);
}

const server = http.createServer(handler);

server.listen(PORT, HOST, () => {
  const addr = `http://${HOST === "0.0.0.0" ? "localhost" : HOST}:${PORT}`;
  console.log(`[pm-trading-ui-serve] Serving ${STATIC_DIR}`);
  console.log(`[pm-trading-ui-serve] Listening on ${addr}`);
  if (API_PROXY_TARGET) {
    console.log(`[pm-trading-ui-serve] /api/* → ${API_PROXY_TARGET}`);
  } else {
    console.log(
      `[pm-trading-ui-serve] /api/* → 503 (set API_PROXY_TARGET=http://localhost:8080 to proxy)`,
    );
  }
});

server.on("error", (err) => {
  console.error("[pm-trading-ui-serve] Server error:", err.message);
  process.exit(1);
});

// Graceful shutdown on SIGTERM / SIGINT (systemd and Ctrl-C).
function shutdown(sig: string): void {
  console.log(`\n[pm-trading-ui-serve] ${sig} — shutting down…`);
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 5000).unref();
}
process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));

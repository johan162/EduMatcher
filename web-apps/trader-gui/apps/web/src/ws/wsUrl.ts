import { env } from "@/lib/env.js";

/**
 * Absolute WebSocket URL for a gateway path.
 *
 * `VITE_WS_BASE` is empty in development so the Vite proxy handles the
 * upgrade — but the browser `WebSocket` constructor rejects a relative URL,
 * so an empty base is resolved against the page origin (http→ws, https→wss)
 * rather than passed through.
 */
export function wsUrl(path: string): string {
  const base = env("VITE_WS_BASE").replace(/\/+$/, "");
  if (base) return `${base}${path}`;

  const loc = typeof location === "undefined" ? undefined : location;
  if (!loc) return path; // non-browser (tests) — the factory is injected there
  const scheme = loc.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${loc.host}${path}`;
}

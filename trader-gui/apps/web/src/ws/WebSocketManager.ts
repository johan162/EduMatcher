/**
 * WebSocketManager — orchestrates all WebSocket connections (§17.1).
 *
 * Sockets:
 *  /api/v1/events          — private order/fill/quote events  (TRADER, MM)
 *  /api/v1/market-data     — book/trades/depth/auction        (all roles)
 *  /api/v1/admin/monitor   — cross-gateway admin feed         (ADMIN only)
 *
 * One singleton is stored in module scope and shared via the
 * useWebSocketManager() React hook (call once at app root).
 */
import { useEffect } from "react";
import { ManagedSocket, type SocketStatus } from "./ManagedSocket.js";
import { useAuthStore } from "@/store/useAuthStore.js";
import { useSessionStore } from "@/store/useSessionStore.js";
import { useBookStore } from "@/store/useBookStore.js";
import { useHaltStore } from "@/store/useHaltStore.js";
import { useNotificationStore } from "@/store/useNotificationStore.js";
import { env } from "@/lib/env.js";
import type {
  WsEnvelope,
  MarketDataSubscriptionItem,
  GatewayRole,
  BookData,
  DepthData,
  TradeData,
  AuctionResult,
  AuctionIndicative,
  SessionEvent,
  CircuitBreakerHalt,
  CircuitBreakerResume,
} from "@/types/index.js";

const WS_BASE = env("VITE_WS_BASE");

// ── Internal event bus ────────────────────────────────────────────────────────
type AnyHandler = (msg: WsEnvelope<unknown>) => void;
const bus = new Map<string, Set<AnyHandler>>();

export function wsOn(type: string, handler: AnyHandler): () => void {
  if (!bus.has(type)) bus.set(type, new Set());
  bus.get(type)!.add(handler);
  return () => bus.get(type)?.delete(handler);
}

function emit(env: WsEnvelope<unknown>): void {
  bus.get(env.type)?.forEach((h) => h(env));
}

// ── Module-scoped sockets ─────────────────────────────────────────────────────
let eventsWs: ManagedSocket | null = null;
let marketDataWs: ManagedSocket | null = null;
let adminWs: ManagedSocket | null = null;

/** Active market-data subscription items; replayed on reconnect. */
let mdItems: MarketDataSubscriptionItem[] = [];

function getApiKey(): string {
  return useAuthStore.getState().apiKey ?? "";
}

// ── Connection health (observable) ───────────────────────────────────────────
export type HealthStatus = "connected" | "reconnecting" | "disconnected";

const healthListeners = new Set<() => void>();

function notifyHealth(): void {
  healthListeners.forEach((l) => l());
}

export function onHealthChange(cb: () => void): () => void {
  healthListeners.add(cb);
  return () => healthListeners.delete(cb);
}

function socketToHealth(s: SocketStatus): HealthStatus {
  if (s === "OPEN") return "connected";
  if (s === "CONNECTING") return "reconnecting";
  return "disconnected";
}

export function getConnectionHealth(): {
  events: HealthStatus;
  marketData: HealthStatus;
  adminMonitor: HealthStatus | null;
  overall: HealthStatus;
} {
  const ev = socketToHealth(eventsWs?.status ?? "CLOSED");
  const md = socketToHealth(marketDataWs?.status ?? "CLOSED");
  const am = adminWs ? socketToHealth(adminWs.status) : null;

  const states = [ev, md, ...(am ? [am] : [])];
  let overall: HealthStatus = "connected";
  if (states.some((s) => s === "disconnected")) overall = "disconnected";
  else if (states.some((s) => s === "reconnecting")) overall = "reconnecting";

  return { events: ev, marketData: md, adminMonitor: am, overall };
}

// ── Routing helpers ───────────────────────────────────────────────────────────
function handleMarketDataMessage(raw: unknown): void {
  const env = raw as WsEnvelope<unknown>;
  if (!env?.type) return;
  emit(env);

  switch (env.type) {
    case "book": {
      const d = env.data as BookData;
      useBookStore.getState().updateBook(d.symbol, d);
      break;
    }
    case "depth": {
      const d = env.data as DepthData;
      useBookStore.getState().updateDepth(d.symbol, d);
      break;
    }
    case "trade": {
      const d = env.data as TradeData;
      useBookStore.getState().updateLastPrice(d.symbol, d.price, d.quantity);
      break;
    }
    case "auction": {
      const d = env.data as AuctionResult;
      useBookStore.getState().updateAuction(d.symbol, d, { indicative: false });
      break;
    }
    case "auction.indicative": {
      const d = env.data as AuctionIndicative;
      useBookStore.getState().updateAuction(d.symbol, d, { indicative: true });
      break;
    }
    case "session": {
      const d = env.data as SessionEvent;
      const nextAt = d.next?.at ? new Date(d.next.at).getTime() : null;
      useSessionStore.getState().setPhase(d.state, d.prev_state ?? null, nextAt);
      useNotificationStore.getState().push({
        ts: Date.now(),
        kind: "SESSION",
        title: `Session → ${d.state}`,
        detail: d.prev_state ? `was ${d.prev_state}` : "",
      });
      break;
    }
    case "circuit_breaker": {
      const topic = env.topic ?? "";
      if (topic.startsWith("circuit_breaker.halt")) {
        const d = env.data as CircuitBreakerHalt;
        useHaltStore.getState().setHalt(d.symbol, {
          symbol: d.symbol,
          level: d.level,
          resume_at_ns: d.resume_at_ns,
          halt_source: d.halt_source,
          trigger_price: d.trigger_price,
          reference_price: d.reference_price,
        });
        useNotificationStore.getState().push({
          ts: Date.now(),
          kind: "CB",
          title: `CB Halt: ${d.symbol}`,
          detail: d.level ? `Level ${d.level}` : "Admin halt",
        });
      } else if (topic.startsWith("circuit_breaker.resume")) {
        const d = env.data as CircuitBreakerResume;
        useHaltStore.getState().clearHalt(d.symbol);
        useNotificationStore.getState().push({
          ts: Date.now(),
          kind: "CB",
          title: `CB Resume: ${d.symbol}`,
          detail: d.reason ?? "",
        });
      }
      break;
    }
  }
}

function handlePrivateMessage(raw: unknown): void {
  const env = raw as WsEnvelope<unknown>;
  if (!env?.type) return;
  emit(env);
  // Individual order/fill/quote handlers attach via wsOn() from hooks/queries.
}

function handleAdminMonitorMessage(raw: unknown): void {
  const env = raw as WsEnvelope<unknown>;
  if (!env?.type) return;
  emit(env);
}

// ── Public API ────────────────────────────────────────────────────────────────
export function connectAll(role: GatewayRole): void {
  const key = getApiKey();

  // Events socket (TRADER + MM only; ADMIN uses admin monitor)
  if (role !== "ADMIN") {
    eventsWs = new ManagedSocket(`${WS_BASE}/api/v1/events`, {
      authFrame: () => ({ api_key: useAuthStore.getState().apiKey }),
      onReconnect: () => notifyHealth(),
    });
    eventsWs.on(handlePrivateMessage);
    eventsWs.onStatus(() => notifyHealth());
    eventsWs.connect();
  }

  // Market data socket (all roles)
  marketDataWs = new ManagedSocket(`${WS_BASE}/api/v1/market-data`, {
    authFrame: () => ({ api_key: useAuthStore.getState().apiKey }),
    onReconnect: (ws) => {
      // Replay the active subscription set on reconnect.
      if (mdItems.length > 0) {
        ws.send({ action: "subscribe", items: mdItems });
      }
      notifyHealth();
    },
  });
  marketDataWs.on(handleMarketDataMessage);
  marketDataWs.onStatus(() => notifyHealth());
  marketDataWs.connect();

  // Admin monitor socket (ADMIN only)
  if (role === "ADMIN") {
    adminWs = new ManagedSocket(`${WS_BASE}/api/v1/admin/monitor`, {
      authFrame: () => ({ api_key: useAuthStore.getState().apiKey }),
      onReconnect: () => notifyHealth(),
    });
    adminWs.on(handleAdminMonitorMessage);
    adminWs.onStatus(() => notifyHealth());
    adminWs.connect();
  }
}

export function disconnectAll(): void {
  eventsWs?.close();
  marketDataWs?.close();
  adminWs?.close();
  eventsWs = null;
  marketDataWs = null;
  adminWs = null;
  mdItems = [];
}

export function subscribeMarketData(items: MarketDataSubscriptionItem[]): void {
  // Merge new items into the active set.
  mdItems = [...mdItems, ...items];
  marketDataWs?.send({ action: "subscribe", items });
}

export function unsubscribeMarketData(items: MarketDataSubscriptionItem[]): void {
  // Remove matching entries from the replay list.
  mdItems = mdItems.filter(
    (existing) =>
      !items.some(
        (rm) =>
          JSON.stringify(rm.symbols.sort()) === JSON.stringify(existing.symbols.sort()) &&
          JSON.stringify(rm.channels.sort()) === JSON.stringify(existing.channels.sort()),
      ),
  );
  marketDataWs?.send({ action: "unsubscribe", items });
}

// ── React hook ────────────────────────────────────────────────────────────────
/**
 * Mount once at app root (inside <App>).
 * Connects sockets when the user is authenticated; tears down on logout.
 */
export function useWebSocketManager(): void {
  const apiKey = useAuthStore((s) => s.apiKey);
  const role = useAuthStore((s) => s.role);

  useEffect(() => {
    if (!apiKey || !role) {
      disconnectAll();
      return;
    }
    connectAll(role);
    return () => {
      disconnectAll();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey, role]);
}

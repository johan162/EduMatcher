/**
 * WebSocketManager — orchestrates all WebSocket connections (§17.1).
 *
 * Sockets:
 *  /api/v1/events          — private order/fill/quote events  (TRADER, MM)
 *  /api/v1/market-data     — book/trades/depth/auction        (all roles)
 *  /api/v1/admin/monitor   — cross-gateway admin feed         (ADMIN only)
 *
 * One singleton lives in module scope (not React state) and is mounted once
 * at the app root via `useWebSocketManager()`. Components subscribe to typed
 * events through `useWsEvent`.
 *
 * Market data runs on a **single** socket carrying two subscription items —
 * a broad `*` item for the overview grid and a bounded focus item for the
 * heavy `depth`/`auction` channels (§17.3.1). Subscription state is held as a
 * desired pair set and diffed, so re-focusing a symbol sends one small
 * subscribe/unsubscribe rather than re-declaring the world.
 */
import { useEffect } from "react";
import { ManagedSocket, type SocketStatus } from "./ManagedSocket.js";
import { wsUrl } from "./wsUrl.js";
import { SeqTracker } from "./seqTracker.js";
import { channelForTopic, symbolForTopic } from "./topics.js";
import {
  capSymbols,
  diffPairs,
  planPairs,
  replayItems,
  type MarketDataChannel,
  type PairKey,
  type SubscriptionItem,
  type SubscriptionPlan,
} from "./subscriptions.js";
import { useAuthStore } from "@/store/useAuthStore.js";
import { useSessionStore } from "@/store/useSessionStore.js";
import { useBookStore } from "@/store/useBookStore.js";
import { useHaltStore } from "@/store/useHaltStore.js";
import { useNotificationStore } from "@/store/useNotificationStore.js";
import { envInt } from "@/lib/env.js";
import type {
  WsEnvelope,
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

const MAX_FOCUS_SYMBOLS = envInt("VITE_MAX_FOCUS_SYMBOLS", 25);

// ── Internal event bus ────────────────────────────────────────────────────────
type AnyHandler = (envelope: WsEnvelope<unknown>) => void;
const bus = new Map<string, Set<AnyHandler>>();

export function wsOn(type: string, handler: AnyHandler): () => void {
  let set = bus.get(type);
  if (!set) {
    set = new Set();
    bus.set(type, set);
  }
  set.add(handler);
  return () => {
    bus.get(type)?.delete(handler);
  };
}

function emit(envelope: WsEnvelope<unknown>): void {
  bus.get(envelope.type)?.forEach((h) => h(envelope));
}

// ── Module-scoped sockets ─────────────────────────────────────────────────────
let eventsWs: ManagedSocket | null = null;
let marketDataWs: ManagedSocket | null = null;
let adminWs: ManagedSocket | null = null;

// ── Market-data subscription state ───────────────────────────────────────────
let plan: SubscriptionPlan = { overview: true, focus: [] };
/** Pairs the server has been told about. Cleared on disconnect. */
let applied = new Set<PairKey>();
const seqTracker = new SeqTracker();
/** Topics with a resume in flight, so one gap does not fan out into many. */
const pendingResume = new Set<string>();
let lastMarketDataAt: number | null = null;

function authFrame(): object {
  return { api_key: useAuthStore.getState().apiKey ?? "" };
}

// ── Connection health (observable) ───────────────────────────────────────────
export type HealthStatus = "connected" | "reconnecting" | "disconnected";

const healthListeners = new Set<() => void>();

function notifyHealth(): void {
  healthListeners.forEach((l) => l());
}

export function onHealthChange(cb: () => void): () => void {
  healthListeners.add(cb);
  return () => {
    healthListeners.delete(cb);
  };
}

function socketToHealth(s: SocketStatus): HealthStatus {
  if (s === "OPEN") return "connected";
  if (s === "CONNECTING") return "reconnecting";
  return "disconnected";
}

export interface ConnectionHealthSnapshot {
  events: HealthStatus;
  marketData: HealthStatus;
  adminMonitor: HealthStatus | null;
  overall: HealthStatus;
  /** Unix ms of the last market-data frame — the top bar's "Updated" clock. */
  lastMarketDataAt: number | null;
}

export function getConnectionHealth(): ConnectionHealthSnapshot {
  // A socket that was never created for this role is not "disconnected" — it
  // is not part of this role's health at all, which is why `events` collapses
  // to `connected` for ADMIN rather than dragging `overall` red.
  const ev = eventsWs ? socketToHealth(eventsWs.status) : null;
  const md = marketDataWs ? socketToHealth(marketDataWs.status) : null;
  const am = adminWs ? socketToHealth(adminWs.status) : null;

  const active = [ev, md, am].filter((s): s is HealthStatus => s !== null);
  let overall: HealthStatus = active.length === 0 ? "disconnected" : "connected";
  if (active.some((s) => s === "disconnected")) overall = "disconnected";
  else if (active.some((s) => s === "reconnecting")) overall = "reconnecting";

  return {
    events: ev ?? "connected",
    marketData: md ?? "disconnected",
    adminMonitor: am,
    overall,
    lastMarketDataAt,
  };
}

// ── Subscription control ─────────────────────────────────────────────────────

/** The plan currently in force (read-only view, for tests and diagnostics). */
export function getSubscriptionPlan(): SubscriptionPlan {
  return { overview: plan.overview, focus: [...plan.focus] };
}

/** Pairs the server has been told about (read-only view). */
export function getAppliedPairs(): PairKey[] {
  return [...applied];
}

function sendItems(action: "subscribe" | "unsubscribe", items: SubscriptionItem[]): void {
  if (items.length === 0 || !marketDataWs) return;
  marketDataWs.send({ action, items });
}

/** Reconcile the server's subscription with the current plan. */
function syncSubscriptions(): void {
  const desired = planPairs(plan);
  const { subscribe, unsubscribe } = diffPairs(applied, desired);
  // Unsubscribe first: dropping the stale focus symbol before adding the new
  // one keeps the gateway's heavy-channel fan-out at the cap, never 2× it.
  sendItems("unsubscribe", unsubscribe);
  sendItems("subscribe", subscribe);
  applied = desired;
}

/** Enable/disable the broad `*` book+trades item (Market Overview). */
export function setOverviewSubscription(enabled: boolean): void {
  if (plan.overview === enabled) return;
  plan = { ...plan, overview: enabled };
  syncSubscriptions();
}

/**
 * Replace the focus set — active symbol plus watchlist. Capped by
 * `VITE_MAX_FOCUS_SYMBOLS`, because `depth` and `auction` are full snapshots
 * with no delta form (§17.3.4).
 */
export function setFocusSymbols(symbols: readonly string[]): void {
  const next = capSymbols(symbols, MAX_FOCUS_SYMBOLS);
  if (next.length === plan.focus.length && next.every((s, i) => s === plan.focus[i])) {
    return;
  }
  if (symbols.length > next.length) {
    console.warn(`[ws] focus set truncated to ${next.length} symbols (VITE_MAX_FOCUS_SYMBOLS)`);
  }
  plan = { ...plan, focus: next };
  syncSubscriptions();
}

/** Ask for an authoritative snapshot of one symbol/channel set (§26.3.2). */
export function requestSnapshot(symbol: string, channels: MarketDataChannel[]): void {
  marketDataWs?.send({ action: "snapshot", symbols: [symbol], channels });
}

// ── Gap repair ───────────────────────────────────────────────────────────────

/**
 * Repair a detected `seq` gap with a targeted resume (§26.3.2) rather than a
 * full re-subscribe + REST refresh storm.
 */
function repairGap(topic: string, fromSeq: number): void {
  if (pendingResume.has(topic)) return;
  const channel = channelForTopic(topic);
  if (channel === null || !marketDataWs) return;
  pendingResume.add(topic);
  const symbol = symbolForTopic(topic);
  marketDataWs.send({
    action: "resume",
    topic,
    from_seq: fromSeq,
    // `trade.executed` does not name its symbol in the topic, so the server
    // takes it from `symbols`; harmless for the symbol-qualified topics.
    ...(symbol ? { symbols: [symbol] } : {}),
  });
}

interface ResumeRejectedData {
  topic: string;
  from_seq: number | null;
  reason: string;
}

function handleResumeRejected(data: ResumeRejectedData): void {
  const topic = data.topic ?? "";
  pendingResume.delete(topic);
  seqTracker.reset(topic);
  const channel = channelForTopic(topic);
  const symbol = symbolForTopic(topic);
  console.warn(`[ws] resume rejected for ${topic}: ${data.reason}`);
  if (channel === null) return;
  if (symbol) {
    requestSnapshot(symbol, [channel]);
  } else {
    // A venue-wide topic (trade.executed) resumes per focus symbol.
    for (const sym of plan.focus) requestSnapshot(sym, [channel]);
  }
}

// ── Routing: market data ─────────────────────────────────────────────────────
function handleMarketDataMessage(raw: unknown): void {
  const envelope = raw as WsEnvelope<unknown>;
  if (!envelope?.type) return;
  lastMarketDataAt = Date.now();

  // Control frames are not market data and carry no `seq`.
  switch (envelope.type) {
    case "authenticated":
      return;
    case "subscription": {
      const data = envelope.data as { rejected?: unknown[] } | undefined;
      if (data?.rejected?.length) {
        console.warn("[ws] subscription items rejected", data.rejected);
      }
      emit(envelope);
      return;
    }
    case "resume.rejected":
      handleResumeRejected(envelope.data as ResumeRejectedData);
      emit(envelope);
      return;
    case "trades.reset": {
      const data = envelope.data as { symbol?: string };
      if (data?.symbol) useBookStore.getState().clearRecentTrades(data.symbol);
      seqTracker.reset(envelope.topic);
      emit(envelope);
      return;
    }
    case "error":
      console.warn("[ws] market-data error frame", envelope.data);
      emit(envelope);
      return;
  }

  const gap = seqTracker.observe(envelope.topic, envelope.seq);
  if (gap !== null) {
    console.warn(`[ws] seq gap on ${gap.topic}: expected ${gap.expected}, got ${gap.received}`);
    repairGap(gap.topic, gap.expected - 1);
  } else if (envelope.topic) {
    pendingResume.delete(envelope.topic);
  }

  emit(envelope);

  switch (envelope.type) {
    case "book": {
      const d = envelope.data as BookData;
      useBookStore.getState().updateBook(d.symbol, d);
      break;
    }
    case "depth": {
      const d = envelope.data as DepthData;
      useBookStore.getState().updateDepth(d.symbol, d);
      break;
    }
    case "trade": {
      const d = envelope.data as TradeData;
      useBookStore.getState().recordTrade(d);
      break;
    }
    case "auction": {
      const d = envelope.data as AuctionResult;
      useBookStore.getState().updateAuction(d.symbol, d, { indicative: false });
      break;
    }
    case "auction.indicative": {
      const d = envelope.data as AuctionIndicative;
      useBookStore.getState().updateAuction(d.symbol, d, { indicative: true });
      break;
    }
    case "session": {
      applySessionEvent(envelope.data as SessionEvent);
      break;
    }
    case "circuit_breaker": {
      applyCircuitBreakerEvent(envelope);
      break;
    }
  }
}

export function applySessionEvent(d: SessionEvent): void {
  const store = useSessionStore.getState();
  if (d.state === store.phase && d.prev_state === undefined) {
    // A repeated state with no transition information carries no news.
    return;
  }
  store.setPhase(d.state, d.prev_state ?? null, d.next ?? null);
  useNotificationStore.getState().push({
    ts: Date.now(),
    kind: "SESSION",
    title: `Session → ${d.state}`,
    detail: d.prev_state ? `was ${d.prev_state}` : "",
  });
}

function applyCircuitBreakerEvent(envelope: WsEnvelope<unknown>): void {
  const topic = envelope.topic ?? "";
  if (topic.startsWith("circuit_breaker.resume")) {
    const d = envelope.data as CircuitBreakerResume;
    useHaltStore.getState().clearHalt(d.symbol);
    useNotificationStore.getState().push({
      ts: Date.now(),
      kind: "CB",
      title: `CB Resume: ${d.symbol}`,
      detail: d.reason ?? "",
    });
    return;
  }
  // Anything that is not an explicit resume is a halt — `circuit_breaker.halt`
  // today, and an unrecognised sub-topic is safer treated as "halted".
  const d = envelope.data as CircuitBreakerHalt;
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
}

// ── Routing: private + admin ─────────────────────────────────────────────────
function handlePrivateMessage(raw: unknown): void {
  const envelope = raw as WsEnvelope<unknown>;
  if (!envelope?.type) return;
  emit(envelope);
  // Order/fill/quote consumers attach via wsOn() from hooks/queries (phase 6+).
}

function handleAdminMonitorMessage(raw: unknown): void {
  const envelope = raw as WsEnvelope<unknown>;
  if (!envelope?.type) return;
  emit(envelope);
}

// ── Public API ────────────────────────────────────────────────────────────────
export function connectAll(role: GatewayRole): void {
  disconnectAll();

  // Events socket (TRADER + MM only; ADMIN uses the admin monitor feed).
  if (role !== "ADMIN") {
    eventsWs = new ManagedSocket(wsUrl("/api/v1/events"), {
      authFrame,
      onReconnect: () => notifyHealth(),
    });
    eventsWs.on(handlePrivateMessage);
    eventsWs.onStatus(notifyHealth);
    eventsWs.connect();
  }

  // Market-data socket (all roles).
  marketDataWs = new ManagedSocket(wsUrl("/api/v1/market-data"), {
    authFrame,
    onReconnect: (ws) => {
      // The server holds no subscription state across a reconnect, so the
      // full item list is re-declared — with the per-topic resume points so
      // the append-only `trades` channel picks up where it left off instead
      // of replaying its whole tail (§26.3.2).
      applied = planPairs(plan);
      pendingResume.clear();
      const items = replayItems(applied, (symbol, channel) => resumePointFor(symbol, channel));
      if (items.length > 0) ws.send({ action: "subscribe", items });
      notifyHealth();
    },
  });
  marketDataWs.on(handleMarketDataMessage);
  marketDataWs.onStatus(notifyHealth);
  marketDataWs.connect();

  // Admin monitor socket (ADMIN only).
  if (role === "ADMIN") {
    adminWs = new ManagedSocket(wsUrl("/api/v1/admin/monitor"), {
      authFrame,
      onReconnect: () => notifyHealth(),
    });
    adminWs.on(handleAdminMonitorMessage);
    adminWs.onStatus(notifyHealth);
    adminWs.connect();
  }
  notifyHealth();
}

/** Last `seq` seen for a (symbol, channel), for `resume_from` annotation. */
function resumePointFor(symbol: string, channel: MarketDataChannel): number | undefined {
  if (channel === "trades") return seqTracker.lastSeq("trade.executed");
  if (channel === "book") return seqTracker.lastSeq(`book.${symbol}`);
  if (channel === "depth") return seqTracker.lastSeq(`depth.${symbol}`);
  return seqTracker.lastSeq(`auction.result.${symbol}`);
}

export function disconnectAll(): void {
  eventsWs?.close();
  marketDataWs?.close();
  adminWs?.close();
  eventsWs = null;
  marketDataWs = null;
  adminWs = null;
  applied = new Set();
  pendingResume.clear();
  seqTracker.reset();
  lastMarketDataAt = null;
  notifyHealth();
}

/**
 * Test seam: install fake sockets and reset module state.
 * Not used by the app; exported so the routing/subscription logic can be
 * exercised without a browser WebSocket.
 */
export function __setMarketDataSocketForTest(socket: ManagedSocket | null): void {
  marketDataWs = socket;
  applied = new Set();
  plan = { overview: true, focus: [] };
  pendingResume.clear();
  seqTracker.reset();
  lastMarketDataAt = null;
}

export const __marketDataMessageForTest = handleMarketDataMessage;

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
  }, [apiKey, role]);
}

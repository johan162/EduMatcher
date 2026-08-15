/**
 * ManagedSocket — bespoke WebSocket wrapper (§17.1).
 *
 * NOT the `reconnecting-websocket` npm package. This class exists because
 * reconnect MUST re-send a custom JSON authentication frame, and for
 * /market-data must also replay the active subscription set.
 *
 * Features:
 *  - Exponential-backoff reconnect on the §7.4 schedule (1s, 2s, 4s, 8s, 30s cap)
 *  - Sends `opts.authFrame()` on every (re)connect and waits for the server's
 *    `{ "type": "authenticated" }` reply before declaring OPEN
 *  - Fails the attempt if that reply does not arrive within `authTimeoutMs`
 *    (the gateway itself gives the client 5s to send the frame, so a silent
 *    server is a failed attempt, not a socket to sit on forever)
 *  - Calls `opts.onReconnect` after every successful authentication so the
 *    caller can replay subscriptions or refresh REST snapshots
 */

import { env, envInt } from "@/lib/env.js";

export type SocketStatus = "CONNECTING" | "OPEN" | "CLOSED";
type MessageHandler = (msg: unknown) => void;

/**
 * The slice of the DOM `WebSocket` this class uses. Declared structurally so
 * tests can inject a fake without a DOM, and so the module imports cleanly in
 * Vitest's default `node` environment.
 */
export interface WebSocketLike {
  readyState: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: string }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  onclose: ((ev: { code?: number; reason?: string }) => void) | null;
}

export type SocketFactory = (url: string) => WebSocketLike;

/** `WebSocket.OPEN` without depending on the global existing at import time. */
const READY_STATE_OPEN = 1;

const DEFAULT_MAX_DELAY_MS = envInt("VITE_WS_RECONNECT_MAX_DELAY", 30_000);
const DEFAULT_AUTH_TIMEOUT_MS = 5_000;

/** §7.4 reconnect schedule, before the cap is applied. */
export const BACKOFF_STEPS_MS = [1_000, 2_000, 4_000, 8_000] as const;

/**
 * Delay before reconnect attempt number `attempt` (1-based).
 * Attempts past the table hold at the cap — the previous implementation
 * indexed the table with `min(attempt, len-1)` and therefore never left 8s.
 */
export function backoffDelay(attempt: number, maxDelayMs = DEFAULT_MAX_DELAY_MS): number {
  const idx = Math.max(1, Math.floor(attempt)) - 1;
  const step = idx < BACKOFF_STEPS_MS.length ? BACKOFF_STEPS_MS[idx]! : maxDelayMs;
  return Math.min(step, maxDelayMs);
}

export interface ManagedSocketOptions {
  /** Frame sent immediately on open; must authenticate the connection. */
  authFrame: () => object;
  /** Invoked after every successful authentication, including the first. */
  onReconnect?: (socket: ManagedSocket) => void;
  /** Invoked when the server closes with a policy-violation / auth code. */
  onAuthFailure?: (code: number, reason: string) => void;
  /** Milliseconds to wait for `{type:"authenticated"}`. Default 5000. */
  authTimeoutMs?: number;
  /** Cap for the reconnect backoff. Default VITE_WS_RECONNECT_MAX_DELAY. */
  maxDelayMs?: number;
  /** Injectable socket constructor — tests supply a fake. */
  factory?: SocketFactory;
}

/** Close codes the gateway uses to reject a connection outright. */
const POLICY_VIOLATION = 1008;
const ADMIN_REQUIRED = 4003;

export class ManagedSocket {
  private ws: WebSocketLike | null = null;
  private handlers = new Set<MessageHandler>();
  private statusHandlers = new Set<(s: SocketStatus) => void>();
  private attempt = 0;
  private _status: SocketStatus = "CLOSED";
  private _lastMessageAt: number | null = null;
  private _lastCloseCode: number | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private authTimer: ReturnType<typeof setTimeout> | null = null;
  private destroyed = false;
  private readonly authTimeoutMs: number;
  private readonly maxDelayMs: number;
  private readonly factory: SocketFactory;

  constructor(
    private readonly url: string,
    private readonly opts: ManagedSocketOptions,
  ) {
    this.authTimeoutMs = opts.authTimeoutMs ?? DEFAULT_AUTH_TIMEOUT_MS;
    this.maxDelayMs = opts.maxDelayMs ?? DEFAULT_MAX_DELAY_MS;
    this.factory = opts.factory ?? ((u: string) => new WebSocket(u) as unknown as WebSocketLike);
  }

  get status(): SocketStatus {
    return this._status;
  }

  /** Unix ms of the last frame received, or null if none yet. */
  get lastMessageAt(): number | null {
    return this._lastMessageAt;
  }

  /** Close code of the most recent disconnect, for diagnostics. */
  get lastCloseCode(): number | null {
    return this._lastCloseCode;
  }

  /** Number of consecutive failed attempts since the last authentication. */
  get reconnectAttempt(): number {
    return this.attempt;
  }

  connect(): void {
    if (this.destroyed) return;
    this._setStatus("CONNECTING");

    let ws: WebSocketLike;
    try {
      ws = this.factory(this.url);
    } catch {
      // A constructor throw (bad URL, no global WebSocket) is a failed attempt,
      // not a crash of the caller's render.
      this._setStatus("CLOSED");
      this._scheduleReconnect();
      return;
    }
    this.ws = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify(this.opts.authFrame()));
      // The server has not confirmed anything yet: status stays CONNECTING
      // until the `authenticated` frame arrives, so the health indicator
      // never shows green for a socket that is open but unauthenticated.
      this._armAuthTimeout(ws);
    };

    ws.onmessage = (ev: { data: string }) => {
      this._lastMessageAt = Date.now();
      let msg: unknown;
      try {
        msg = JSON.parse(ev.data) as unknown;
      } catch {
        return;
      }

      const type =
        typeof msg === "object" && msg !== null
          ? (msg as Record<string, unknown>)["type"]
          : undefined;

      if (this._status !== "OPEN" && type === "authenticated") {
        this._clearAuthTimeout();
        this.attempt = 0;
        this._setStatus("OPEN");
        this.opts.onReconnect?.(this);
      }

      for (const h of this.handlers) h(msg);
    };

    ws.onerror = () => {
      // onerror is always followed by onclose; reconnect is scheduled there.
    };

    ws.onclose = (ev) => {
      this._clearAuthTimeout();
      this._lastCloseCode = ev?.code ?? null;
      if (this.destroyed) return;
      this._setStatus("CLOSED");
      if (ev?.code === POLICY_VIOLATION || ev?.code === ADMIN_REQUIRED) {
        this.opts.onAuthFailure?.(ev.code, ev.reason ?? "");
      }
      this._scheduleReconnect();
    };
  }

  send(obj: object): void {
    if (this.ws?.readyState === READY_STATE_OPEN) {
      this.ws.send(JSON.stringify(obj));
    }
  }

  /** Subscribe to parsed messages. Returns an unsubscribe function. */
  on(handler: MessageHandler): () => void {
    this.handlers.add(handler);
    return () => {
      this.handlers.delete(handler);
    };
  }

  /** Subscribe to status changes. Returns an unsubscribe function. */
  onStatus(handler: (s: SocketStatus) => void): () => void {
    this.statusHandlers.add(handler);
    return () => {
      this.statusHandlers.delete(handler);
    };
  }

  /** Permanently close — will NOT reconnect. */
  close(): void {
    this.destroyed = true;
    this._clearAuthTimeout();
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    const ws = this.ws;
    this.ws = null;
    ws?.close();
    this._setStatus("CLOSED");
  }

  private _armAuthTimeout(ws: WebSocketLike): void {
    this._clearAuthTimeout();
    this.authTimer = setTimeout(() => {
      this.authTimer = null;
      if (this._status === "OPEN" || this.destroyed) return;
      // Silent server: drop the socket so onclose drives the backoff.
      ws.close();
    }, this.authTimeoutMs);
  }

  private _clearAuthTimeout(): void {
    if (this.authTimer !== null) {
      clearTimeout(this.authTimer);
      this.authTimer = null;
    }
  }

  private _setStatus(s: SocketStatus): void {
    if (this._status === s) return;
    this._status = s;
    for (const h of this.statusHandlers) h(s);
  }

  private _scheduleReconnect(): void {
    if (this.destroyed || this.reconnectTimer !== null) return;
    this.attempt++;
    const delay = backoffDelay(this.attempt, this.maxDelayMs);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }
}

/** Base URL for all sockets; empty in dev so the Vite proxy handles the upgrade. */
export const WS_BASE = env("VITE_WS_BASE");

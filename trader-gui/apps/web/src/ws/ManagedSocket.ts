/**
 * ManagedSocket — bespoke WebSocket wrapper (§17.1).
 *
 * NOT the `reconnecting-websocket` npm package. This class exists because
 * reconnect MUST re-send a custom JSON authentication frame, and for
 * /market-data must also replay the active subscription set.
 *
 * Features:
 *  - Exponential-backoff reconnect (1s → 2s → 4s → 8s → 30s cap)
 *  - Calls `opts.authFrame()` on every (re)connect attempt
 *  - Calls `opts.onReconnect` after re-authentication so the caller can
 *    replay subscriptions or fetch REST snapshots
 */

import { env } from "@/lib/env.js";

export type SocketStatus = "CONNECTING" | "OPEN" | "CLOSED";
type MessageHandler = (msg: unknown) => void;

const MAX_DELAY_MS = parseInt(env("VITE_WS_RECONNECT_MAX_DELAY", "30000"), 10) || 30_000;

const BACKOFF_STEPS = [1_000, 2_000, 4_000, 8_000];

export class ManagedSocket {
  private ws: WebSocket | null = null;
  private handlers = new Set<MessageHandler>();
  private statusHandlers = new Set<(s: SocketStatus) => void>();
  private attempt = 0;
  private _status: SocketStatus = "CLOSED";
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private destroyed = false;

  constructor(
    private readonly url: string,
    private readonly opts: {
      authFrame: () => object;
      onReconnect?: (socket: ManagedSocket) => void;
    },
  ) {}

  get status(): SocketStatus {
    return this._status;
  }

  connect(): void {
    if (this.destroyed) return;
    this._setStatus("CONNECTING");
    const ws = new WebSocket(this.url);
    this.ws = ws;

    ws.onopen = () => {
      this.attempt = 0;
      // Send auth frame — server must confirm before we declare OPEN.
      ws.send(JSON.stringify(this.opts.authFrame()));
    };

    ws.onmessage = (ev: MessageEvent<string>) => {
      let msg: unknown;
      try {
        msg = JSON.parse(ev.data) as unknown;
      } catch {
        return;
      }

      // The first message should be `{ "type": "authenticated" }`.
      if (
        this._status === "CONNECTING" &&
        typeof msg === "object" &&
        msg !== null &&
        (msg as Record<string, unknown>)["type"] === "authenticated"
      ) {
        this._setStatus("OPEN");
        this.opts.onReconnect?.(this);
      }

      for (const h of this.handlers) h(msg);
    };

    ws.onerror = () => {
      // onerror is always followed by onclose; schedule reconnect there.
    };

    ws.onclose = () => {
      if (this.destroyed) return;
      this._setStatus("CLOSED");
      this._scheduleReconnect();
    };
  }

  send(obj: object): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(obj));
    }
  }

  /** Subscribe to parsed messages. Returns an unsubscribe function. */
  on(handler: MessageHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  /** Subscribe to status changes. Returns an unsubscribe function. */
  onStatus(handler: (s: SocketStatus) => void): () => void {
    this.statusHandlers.add(handler);
    return () => this.statusHandlers.delete(handler);
  }

  /** Permanently close — will NOT reconnect. */
  close(): void {
    this.destroyed = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
    this._setStatus("CLOSED");
  }

  private _setStatus(s: SocketStatus): void {
    if (this._status === s) return;
    this._status = s;
    for (const h of this.statusHandlers) h(s);
  }

  private _scheduleReconnect(): void {
    if (this.destroyed) return;
    const delay = BACKOFF_STEPS[Math.min(this.attempt, BACKOFF_STEPS.length - 1)] ?? MAX_DELAY_MS;
    const capped = Math.min(delay, MAX_DELAY_MS);
    this.attempt++;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, capped);
  }
}

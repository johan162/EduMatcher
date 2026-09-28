/**
 * The bridge's one upstream connection: `pm-api-gwy`'s `WS /api/v1/market-data`
 * (design §6, WP3).
 *
 * Responsibilities: authenticate with the read-only key, hold the `book` +
 * `trades` subscription for every symbol some tab watches, and keep that
 * subscription whole across drops.
 *
 * Loss handling, and why it looks the way it does. The gateway's per-socket
 * queue receives *every* market-data event on the venue and filters after
 * dequeue, so overflow depends on venue-wide traffic. `trade.executed` is
 * venue-wide and its `seq` has gaps for any symbol-filtered subscriber as a
 * matter of course, so it cannot reveal a loss; `book.<SYM>` is per symbol
 * and can. A `book` seq gap therefore triggers a trade `resume` from the last
 * trade seq seen for that symbol. A reconnect re-subscribes with the same hint.
 * When the gap is older than the gateway's trade tail it answers
 * `trades.reset`, and the symbol is re-seeded from history instead.
 */

import { EventEmitter } from "node:events";
import WebSocket from "ws";
import type { BookFrame, TapeTrade, UpstreamState } from "@edumatcher/book-types";
import {
  authFrame,
  parseEnvelope,
  resumeTradesFrame,
  subscribeFrame,
  toBookFrame,
  toLiveTrade,
  unsubscribeFrame,
} from "./envelope.js";

export interface UplinkOptions {
  /** `ws://host:port/api/v1/market-data`. */
  url: string;
  apiKey: string;
  pingSec: number;
  pingMaxMissed: number;
  downAfterSec: number;
  backoffMinMs?: number;
  backoffMaxMs?: number;
}

export interface UplinkEvents {
  status: [UpstreamState];
  book: [BookFrame];
  trade: [string, TapeTrade];
  /** The symbol's trades could not be replayed; rebuild it from history. */
  reseed: [string];
  /** The gateway refused the key. */
  authRejected: [];
}

/** Display precision for a `book` that carries no `tick_decimals` (the exchange's own default). */
const DEFAULT_TICK_DECIMALS = 2;

export class MarketUplink extends EventEmitter<UplinkEvents> {
  state: UpstreamState = "DOWN";
  stateSince = new Date().toISOString();

  private socket?: WebSocket;
  private authenticated = false;
  private stopped = false;
  private readonly held = new Set<string>();
  private readonly lastBookSeq = new Map<string, number>();
  private readonly lastTradeSeq = new Map<string, number>();
  private backoffMs: number;
  private missedPongs = 0;
  private pingTimer?: ReturnType<typeof setInterval>;
  private reconnectTimer?: ReturnType<typeof setTimeout>;
  private downTimer?: ReturnType<typeof setTimeout>;

  constructor(private readonly opts: UplinkOptions) {
    super();
    this.backoffMs = opts.backoffMinMs ?? 500;
  }

  start(): void {
    this.setState("RECONNECTING");
    this.armDownTimer();
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    clearInterval(this.pingTimer);
    clearTimeout(this.reconnectTimer);
    clearTimeout(this.downTimer);
    this.socket?.terminate();
  }

  subscribe(sym: string): void {
    this.held.add(sym);
    if (this.authenticated) this.send(subscribeFrame(sym));
  }

  unsubscribe(sym: string): void {
    this.held.delete(sym);
    // A later subscribe starts a new stream: its first `book` seq is not a gap.
    this.lastBookSeq.delete(sym);
    this.lastTradeSeq.delete(sym);
    if (this.authenticated) this.send(unsubscribeFrame(sym));
  }

  private connect(): void {
    const socket = new WebSocket(this.opts.url);
    this.socket = socket;
    socket.on("open", () => socket.send(authFrame(this.opts.apiKey)));
    socket.on("message", (raw: Buffer) => this.onMessage(raw.toString("utf8")));
    socket.on("pong", () => {
      this.missedPongs = 0;
    });
    socket.on("close", (code: number) => this.onClose(code));
    // `close` always follows `error`; reconnecting is handled there.
    socket.on("error", () => undefined);
  }

  private onMessage(raw: string): void {
    const env = parseEnvelope(raw);
    if (!env) return;
    switch (env.type) {
      case "authenticated":
        return this.onAuthenticated();
      case "book": {
        const frame = toBookFrame(env, DEFAULT_TICK_DECIMALS);
        if (!frame || !this.held.has(frame.sym)) return;
        const prev = this.lastBookSeq.get(frame.sym);
        if (prev !== undefined && frame.seq > prev + 1) this.recoverTrades(frame.sym);
        this.lastBookSeq.set(frame.sym, Math.max(prev ?? 0, frame.seq));
        this.emit("book", frame);
        return;
      }
      case "trade": {
        const parsed = toLiveTrade(env.data);
        if (!parsed || !this.held.has(parsed.sym)) return;
        if (env.seq !== undefined) {
          this.lastTradeSeq.set(parsed.sym, Math.max(this.lastTradeSeq.get(parsed.sym) ?? 0, env.seq));
        }
        this.emit("trade", parsed.sym, parsed.trade);
        return;
      }
      case "trades.reset": {
        const sym = env.data["symbol"];
        if (typeof sym === "string" && this.held.has(sym.toUpperCase()))
          this.emit("reseed", sym.toUpperCase());
        return;
      }
    }
  }

  private onAuthenticated(): void {
    this.authenticated = true;
    this.backoffMs = this.opts.backoffMinMs ?? 500;
    clearTimeout(this.downTimer);
    this.setState("ACTIVE");
    for (const sym of this.held) this.send(subscribeFrame(sym, this.lastTradeSeq.get(sym)));

    this.missedPongs = 0;
    clearInterval(this.pingTimer);
    this.pingTimer = setInterval(() => {
      if (this.missedPongs >= this.opts.pingMaxMissed) {
        this.socket?.terminate();
        return;
      }
      this.missedPongs += 1;
      this.socket?.ping();
    }, this.opts.pingSec * 1000);
  }

  private recoverTrades(sym: string): void {
    const from = this.lastTradeSeq.get(sym);
    if (from === undefined) this.emit("reseed", sym);
    else this.send(resumeTradesFrame(sym, from));
  }

  private onClose(code: number): void {
    const wasAuthenticated = this.authenticated;
    this.authenticated = false;
    clearInterval(this.pingTimer);
    if (this.stopped) return;

    const maxMs = this.opts.backoffMaxMs ?? 15_000;
    if (!wasAuthenticated && code === 1008) {
      // A refused key does not fix itself by retrying quickly.
      clearTimeout(this.downTimer);
      this.setState("DOWN");
      this.emit("authRejected");
      this.backoffMs = maxMs;
    } else if (this.state === "ACTIVE") {
      this.setState("RECONNECTING");
      this.armDownTimer();
    }

    const jitter = 0.8 + Math.random() * 0.4;
    this.reconnectTimer = setTimeout(() => this.connect(), this.backoffMs * jitter);
    this.backoffMs = Math.min(this.backoffMs * 2, maxMs);
  }

  private armDownTimer(): void {
    clearTimeout(this.downTimer);
    this.downTimer = setTimeout(() => this.setState("DOWN"), this.opts.downAfterSec * 1000);
  }

  private setState(state: UpstreamState): void {
    if (state === this.state) return;
    this.state = state;
    this.stateSince = new Date().toISOString();
    this.emit("status", state);
  }

  private send(frame: string): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(frame);
  }
}

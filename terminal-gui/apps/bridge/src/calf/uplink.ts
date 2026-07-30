/**
 * `CalfUplink` — the bridge's single upstream live-data connection (design
 * §6.4, §17.1).
 *
 * One TCP session to `pm-md-gwy` serves every browser tab. Inbound CALF lines
 * are decoded once here and handed out as ready-to-send JSON frames; no tab
 * ever sees the wire format.
 *
 * Three places this departs from design §17.1, each verified against the
 * shipped gateway rather than inferred:
 *
 *   1. **Reconnect does not use `HELLO|RESUME=1`.** §17.1 step 3 has the
 *      bridge issue "a separate HELLO...RESUME=1 per stream" after a drop.
 *      That cannot work: `_handle_client_line` only dispatches `HELLO` while a
 *      session is unauthenticated, so the second one on a connection is
 *      answered with `ERR|CODE=BAD_MESSAGE` — a connection can resume at most
 *      one `(CH, SYM)` stream, ever. Instead the bridge reconnects with a
 *      plain `HELLO` and re-subscribes; the gateway's automatic `SNAP` on
 *      `SUB` restores correct state for `TOP`/`STATE`/`INDEX`/`DEPTH`/`CB`.
 *      `TRADE` and `AUCTION` have no snapshot baseline, so prints during the
 *      gap are lost — which §17.1 already accepts as the right trade-off for
 *      a display-only viewer.
 *   2. **There is no `ERR|CODE=SLOW_CLIENT` to react to.** The gateway drops
 *      an over-queued client silently (`_queue_raw` clears the queue and marks
 *      the session closing; `_flush_client_writes` then disconnects). It looks
 *      like any other close, and is handled as one.
 *   3. **A keepalive `PING` is required.** See `config.calf.pingIntervalSec`.
 */

import { EventEmitter } from "node:events";
import { Socket } from "node:net";
import {
  CalfProtocolError,
  LineBuffer,
  buildExit,
  buildHello,
  buildPing,
  buildSub,
  buildUnsub,
  decodeAuction,
  decodeCb,
  decodeDepth,
  decodeIndex,
  decodeState,
  decodeTop,
  decodeTrade,
  parseLine,
  parseWelcome,
  readEnvelope,
  type Channel,
  type WelcomeInfo,
} from "@edumatcher/calf-protocol";
import type { CalfState, ServerFrame, TradeSide, WatchChannel } from "@edumatcher/terminal-types";
import { SymbolRefCount } from "./symbol-refcount.js";
import { TopCache } from "./top-cache.js";

/** Held for the bridge's whole lifetime, regardless of tab count (§6.4). */
const WILDCARD_CHANNELS: Channel[] = ["STATE", "TOP", "TRADE", "AUCTION"];

const RECONNECT_MIN_MS = 500;
const RECONNECT_MAX_MS = 10_000;

export interface CalfUplinkOptions {
  host: string;
  port: number;
  clientId: string;
  indexIds: string[];
  pingIntervalSec: number;
}

export interface CalfUplinkEvents {
  frame: [ServerFrame];
  status: [CalfState];
  welcome: [WelcomeInfo];
  /** A symbol seen on the wire that was not in `WELCOME|SYMBOLS=`. */
  symbol: [string];
  /** `ERR` from the gateway — a real problem worth an operator's attention. */
  gatewayError: [{ code: string; detail: Record<string, string> }];
}

export class CalfUplink extends EventEmitter<CalfUplinkEvents> {
  private socket: Socket | null = null;
  private readonly lines = new LineBuffer();
  private readonly topCache = new TopCache();
  private readonly refCount: SymbolRefCount;
  private readonly knownSymbols = new Set<string>();

  private reconnectDelayMs = RECONNECT_MIN_MS;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private pingTimer: NodeJS.Timeout | null = null;
  private stopped = false;
  private handshaken = false;
  private supportedChannels = new Set<string>();

  state: CalfState = "DOWN";
  stateSince = new Date().toISOString();
  gateway: string | null = null;

  constructor(private readonly opts: CalfUplinkOptions) {
    super();
    this.refCount = new SymbolRefCount({
      onFirst: (ch, sym) => this.sendSub(ch, sym),
      onLast: (ch, sym) => this.send(buildUnsub([ch], [sym])),
    });
  }

  /** Symbols this bridge knows about — `WELCOME|SYMBOLS=` plus any seen live. */
  symbols(): string[] {
    return [...this.knownSymbols].sort();
  }

  start(): void {
    this.stopped = false;
    this.open();
  }

  async stop(): Promise<void> {
    this.stopped = true;
    this.clearTimers();
    if (this.socket) {
      try {
        this.socket.write(buildExit());
      } catch {
        // Best effort — the peer may already be gone.
      }
      this.socket.removeAllListeners();
      this.socket.destroy();
      this.socket = null;
    }
    this.setState("DOWN");
  }

  /**
   * Register interest in a per-symbol channel on behalf of one browser tab.
   * The `SUB` only reaches the gateway if this is the first interested party.
   */
  watch(ch: WatchChannel, sym: string): void {
    this.refCount.acquire(ch, sym);
  }

  unwatch(ch: WatchChannel, sym: string): void {
    this.refCount.release(ch, sym);
  }

  // -- connection ------------------------------------------------------------

  private open(): void {
    if (this.stopped) return;

    this.handshaken = false;
    this.lines.reset();

    const socket = new Socket();
    this.socket = socket;

    socket.on("connect", () => socket.write(buildHello(this.opts.clientId)));
    socket.on("data", (chunk: Buffer) => this.onData(chunk));
    socket.on("error", () => this.onClosed());
    socket.on("close", () => this.onClosed());

    socket.connect(this.opts.port, this.opts.host);
  }

  private onClosed(): void {
    if (this.stopped) return;
    if (this.socket) {
      this.socket.removeAllListeners();
      this.socket.destroy();
      this.socket = null;
    }
    this.clearTimers();
    this.setState("RECONNECTING");

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.open();
    }, this.reconnectDelayMs);
    this.reconnectTimer.unref?.();
    this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 2, RECONNECT_MAX_MS);
  }

  private onData(chunk: Buffer): void {
    let lines: string[];
    try {
      lines = this.lines.push(chunk);
    } catch (err) {
      // An oversized unterminated line means the stream is no longer framed
      // the way CALF promises. Reconnecting is the only clean recovery.
      this.emit("gatewayError", { code: "BAD_FRAMING", detail: { message: String(err) } });
      this.socket?.destroy();
      return;
    }

    for (const line of lines) {
      try {
        this.handleLine(line);
      } catch (err) {
        if (err instanceof CalfProtocolError) {
          this.emit("gatewayError", { code: "PARSE_ERROR", detail: { line, message: err.message } });
          continue;
        }
        throw err;
      }
    }
  }

  private handleLine(line: string): void {
    const { msgType, fields } = parseLine(line);

    switch (msgType) {
      case "WELCOME":
        return this.onWelcome(fields);
      case "HB":
      case "PONG":
        return;
      case "ERR":
        this.emit("gatewayError", { code: fields["CODE"] ?? "UNKNOWN", detail: fields });
        return;
      default:
        return this.onStreamMessage(msgType, fields);
    }
  }

  private onWelcome(fields: Record<string, string>): void {
    const welcome = parseWelcome(fields);
    this.handshaken = true;
    this.gateway = welcome.gateway;
    this.supportedChannels = welcome.chSupported;
    this.reconnectDelayMs = RECONNECT_MIN_MS;

    for (const sym of welcome.symbols) this.learnSymbol(sym);

    this.emit("welcome", welcome);
    this.subscribeAll();
    this.armPing();
    this.setState("ACTIVE");
  }

  /**
   * Issue every subscription this bridge should hold, from scratch.
   *
   * Called on first connect and again after every reconnect — the gateway
   * keeps no subscription state across connections, and the automatic `SNAP`
   * each `SUB` triggers is what makes a plain re-subscribe an adequate
   * substitute for the per-stream `RESUME` the design assumed.
   */
  private subscribeAll(): void {
    const wildcards = WILDCARD_CHANNELS.filter((ch) => this.supports(ch));
    if (wildcards.length > 0) this.send(buildSub(wildcards, ["*"]));

    if (this.opts.indexIds.length > 0 && this.supports("INDEX")) {
      this.send(buildSub(["INDEX"], this.opts.indexIds));
    }

    for (const { ch, sym } of this.refCount.active()) this.sendSub(ch, sym);
  }

  /**
   * Whether the gateway advertised this channel.
   *
   * A gateway predating `CH_SUPPORTED` sends no such field at all; treating an
   * empty set as "supports everything" keeps the bridge working against one
   * rather than refusing to subscribe to anything.
   */
  private supports(ch: Channel): boolean {
    return this.supportedChannels.size === 0 || this.supportedChannels.has(ch);
  }

  private sendSub(ch: WatchChannel, sym: string): void {
    if (!this.supports(ch)) return;
    this.send(buildSub([ch], [sym]));
  }

  // -- stream dispatch --------------------------------------------------------

  private onStreamMessage(msgType: string, fields: Record<string, string>): void {
    const { ch, sym, seq, ts } = readEnvelope(fields);
    if (sym !== "*") this.learnSymbol(sym);

    switch (ch) {
      case "TOP":
        // Both SNAP and MD are partial; only the merged view is meaningful.
        this.emit("frame", { type: "top", sym, seq, ts, ...this.topCache.merge(sym, decodeTop(fields)) });
        return;

      case "TRADE": {
        const trade = decodeTrade(fields);
        this.emit("frame", { type: "trade", sym, seq, ts, ...trade, side: trade.side as TradeSide });
        return;
      }

      case "STATE":
        this.emit("frame", { type: "state", sym, seq, ts, ...decodeState(fields) });
        return;

      case "INDEX":
        this.emit("frame", { type: "index", sym, seq, ts, ...decodeIndex(fields) });
        return;

      case "DEPTH":
        this.emit("frame", { type: "depth", sym, seq, ts, ...decodeDepth(fields) });
        return;

      case "AUCTION":
        this.emit("frame", { type: "auction_result", sym, seq, ts, ...decodeAuction(fields) });
        return;

      case "CB":
        this.emit("frame", { type: "halt_context", sym, seq, ts, ...decodeCb(fields) });
        return;

      default:
        this.emit("gatewayError", { code: "UNKNOWN_CHANNEL", detail: { ch, msgType } });
    }
  }

  private learnSymbol(sym: string): void {
    if (this.knownSymbols.has(sym)) return;
    this.knownSymbols.add(sym);
    this.emit("symbol", sym);
  }

  // -- plumbing ----------------------------------------------------------------

  private send(line: string): void {
    if (!this.handshaken || !this.socket) return;
    this.socket.write(line);
  }

  private armPing(): void {
    if (this.pingTimer) clearInterval(this.pingTimer);
    this.pingTimer = setInterval(() => this.send(buildPing()), this.opts.pingIntervalSec * 1000);
    this.pingTimer.unref?.();
  }

  private clearTimers(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private setState(state: CalfState): void {
    if (this.state === state) return;
    this.state = state;
    this.stateSince = new Date().toISOString();
    this.emit("status", state);
  }
}

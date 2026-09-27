/**
 * Per-tab WebSocket fan-out (design §5.2, WP5).
 *
 * Each tab watches exactly one symbol, as pm-viewer does. Symbol-scoped frames
 * go only to the tabs watching that symbol; venue-wide ones go to every tab.
 *
 * The liveness handling is terminal-gui's: a protocol-level ping reaps a
 * half-open tab, and a tab whose outbound buffer backs up is closed with 1013
 * rather than left to grow bridge memory — either way its watch is released.
 */

import type { WebSocket } from "ws";
import type { ClientFrame, ServerFrame } from "@edumatcher/book-types";

/** What the hub needs from the book service — narrowed for testability. */
export interface Watcher {
  knows(sym: string): boolean;
  acquire(sym: string): void;
  release(sym: string): void;
  initialFrames(sym: string): ServerFrame[];
}

export interface ReapingConfig {
  pingSec: number;
  pingMaxMissed: number;
  maxBufferedBytes: number;
}

interface Tab {
  socket: WebSocket;
  sym?: string;
  missedPongs: number;
}

export class WsHub {
  private readonly tabs = new Set<Tab>();
  private readonly reapTimer: ReturnType<typeof setInterval>;

  constructor(
    private readonly watcher: Watcher,
    private readonly maxClients: number,
    private readonly reaping: ReapingConfig,
  ) {
    this.reapTimer = setInterval(() => this.reap(), reaping.pingSec * 1000);
    this.reapTimer.unref();
  }

  get clientCount(): number {
    return this.tabs.size;
  }

  /** Adopt a tab and greet it. False when at capacity: the caller closes the socket. */
  register(socket: WebSocket, hello: ServerFrame): boolean {
    if (this.tabs.size >= this.maxClients) return false;
    const tab: Tab = { socket, missedPongs: 0 };
    this.tabs.add(tab);

    socket.on("message", (raw: Buffer) => {
      let frame: ClientFrame;
      try {
        frame = JSON.parse(raw.toString("utf8")) as ClientFrame;
      } catch {
        return;
      }
      if (frame.t === "watch" && typeof frame.sym === "string") this.watch(tab, frame.sym.toUpperCase());
    });
    socket.on("pong", () => {
      tab.missedPongs = 0;
    });
    socket.on("close", () => this.unregister(tab));
    socket.on("error", () => this.unregister(tab));

    this.send(tab, JSON.stringify(hello));
    return true;
  }

  toSymbol(sym: string, frame: ServerFrame): void {
    const encoded = JSON.stringify(frame);
    for (const tab of this.tabs) if (tab.sym === sym) this.send(tab, encoded);
  }

  toAll(frame: ServerFrame): void {
    const encoded = JSON.stringify(frame);
    for (const tab of this.tabs) this.send(tab, encoded);
  }

  stop(): void {
    clearInterval(this.reapTimer);
  }

  private watch(tab: Tab, sym: string): void {
    if (!this.watcher.knows(sym)) {
      this.send(
        tab,
        JSON.stringify({
          type: "error",
          code: "UNKNOWN_SYMBOL",
          sym,
          message: `${sym} is not a listed symbol`,
        }),
      );
      return;
    }
    if (tab.sym === sym) return;
    const previous = tab.sym;
    tab.sym = sym;
    this.watcher.acquire(sym);
    if (previous) this.watcher.release(previous);
    for (const frame of this.watcher.initialFrames(sym)) this.send(tab, JSON.stringify(frame));
  }

  private reap(): void {
    for (const tab of this.tabs) {
      if (tab.socket.readyState !== tab.socket.OPEN) continue;
      if (tab.socket.bufferedAmount > this.reaping.maxBufferedBytes) {
        tab.socket.close(1013, "buffer exceeded");
        continue;
      }
      tab.missedPongs += 1;
      if (tab.missedPongs > this.reaping.pingMaxMissed) {
        tab.socket.terminate();
        continue;
      }
      tab.socket.ping();
    }
  }

  private unregister(tab: Tab): void {
    if (!this.tabs.delete(tab)) return;
    if (tab.sym) this.watcher.release(tab.sym);
  }

  private send(tab: Tab, encoded: string): void {
    if (tab.socket.readyState === tab.socket.OPEN) tab.socket.send(encoded);
  }
}

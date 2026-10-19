/**
 * Per-tab WebSocket fan-out (design §11.1).
 *
 * Every tab receives the same frames: there is one dashboard, not one view
 * per tab. The liveness handling is book-gui's: a protocol-level ping reaps
 * a half-open tab, and a tab whose outbound buffer backs up is closed with
 * 1013 rather than left to grow bridge memory.
 */

import type { WebSocket } from "ws";
import type { ServerFrame } from "@edumatcher/dash-types";

export interface ReapingConfig {
  pingSec: number;
  pingMaxMissed: number;
  maxBufferedBytes: number;
}

interface Tab {
  socket: WebSocket;
  missedPongs: number;
}

export class WsHub {
  private readonly tabs = new Set<Tab>();
  private readonly reapTimer: ReturnType<typeof setInterval>;

  constructor(
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
    socket.on("pong", () => {
      tab.missedPongs = 0;
    });
    socket.on("close", () => this.tabs.delete(tab));
    socket.on("error", () => this.tabs.delete(tab));
    this.send(tab, JSON.stringify(hello));
    return true;
  }

  toAll(frame: ServerFrame): void {
    const encoded = JSON.stringify(frame);
    for (const tab of this.tabs) this.send(tab, encoded);
  }

  stop(): void {
    clearInterval(this.reapTimer);
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

  private send(tab: Tab, encoded: string): void {
    if (tab.socket.readyState === tab.socket.OPEN) tab.socket.send(encoded);
  }
}

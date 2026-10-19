/**
 * Per-tab WebSocket fan-out (design §11.1, WP-C2.2).
 *
 * Every tab receives the same frames: there is one dashboard, not one view
 * per tab. A frame is encoded once and the same text goes to every tab.
 *
 * Liveness is book-gui's: a protocol-level ping reaps a half-open tab. A tab
 * that does not read is cut off as soon as its outbound buffer passes the
 * limit — checked on every send, not only at the ping interval,
 * since a 60 KB snapshot a second would otherwise pile up for ten seconds
 * before anyone looked. A closed tab simply reconnects and starts from the
 * latest snapshot; nothing is buffered on its behalf.
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
  /** Tabs closed for not reading, since start. */
  slowClosed = 0;

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

  /**
   * Adopt a tab and send it its opening frames (already encoded). False when
   * at capacity: the caller closes the socket.
   */
  register(socket: WebSocket, opening: string[]): boolean {
    if (this.tabs.size >= this.maxClients) return false;
    const tab: Tab = { socket, missedPongs: 0 };
    this.tabs.add(tab);
    socket.on("pong", () => {
      tab.missedPongs = 0;
    });
    socket.on("close", () => this.tabs.delete(tab));
    socket.on("error", () => this.tabs.delete(tab));
    for (const text of opening) this.send(tab, text);
    return true;
  }

  /** Send one encoded frame to every tab. */
  broadcast(encoded: string): void {
    for (const tab of this.tabs) this.send(tab, encoded);
  }

  toAll(frame: ServerFrame): void {
    this.broadcast(JSON.stringify(frame));
  }

  stop(): void {
    clearInterval(this.reapTimer);
    for (const tab of this.tabs) tab.socket.terminate();
    this.tabs.clear();
  }

  private reap(): void {
    for (const tab of this.tabs) {
      if (tab.socket.readyState !== tab.socket.OPEN) continue;
      tab.missedPongs += 1;
      if (tab.missedPongs > this.reaping.pingMaxMissed) {
        tab.socket.terminate();
        continue;
      }
      tab.socket.ping();
    }
  }

  private send(tab: Tab, encoded: string): void {
    const socket = tab.socket;
    if (socket.readyState !== socket.OPEN) return;
    if (socket.bufferedAmount > this.reaping.maxBufferedBytes) {
      this.slowClosed += 1;
      this.tabs.delete(tab);
      // terminate, not close: a close handshake would queue behind the very
      // backlog that got the tab cut off.
      socket.terminate();
      return;
    }
    socket.send(encoded);
  }
}

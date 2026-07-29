/**
 * Per-tab WS fan-out (design §6.5, §16.3).
 *
 * The bridge holds one upstream LALF-PS subscription; each browser tab gets
 * its own filter, applied here against already-received rows. A tab can only
 * change what *it* receives — nothing here reaches `pm-log-srv` (§16.3).
 */

import type { WebSocket } from "ws";
import type { ClientFrame, LogFilter, LogRow, ServerFrame } from "@edumatcher/log-types";
import { rowMatchesFilter } from "./row-filter.js";

interface Tab {
  socket: WebSocket;
  filter: LogFilter;
  live: boolean;
}

export class WsHub {
  private readonly tabs = new Set<Tab>();

  register(socket: WebSocket): void {
    const tab: Tab = { socket, filter: {}, live: true };
    this.tabs.add(tab);

    socket.on("message", (raw: Buffer) => {
      let frame: ClientFrame;
      try {
        frame = JSON.parse(raw.toString("utf8")) as ClientFrame;
      } catch {
        return;
      }
      if (frame.t === "set_filter") tab.filter = frame.filter;
      else if (frame.t === "set_live") tab.live = frame.live;
      // "ping" needs no response beyond the WS-level pong.
    });

    socket.on("close", () => {
      this.tabs.delete(tab);
    });
  }

  get clientCount(): number {
    return this.tabs.size;
  }

  /** Send one row to every tab whose live filter matches it (design §6.5, §9.4). */
  broadcastRow(row: LogRow): void {
    const frame: ServerFrame = { t: "event", row };
    const encoded = JSON.stringify(frame);
    for (const tab of this.tabs) {
      if (!tab.live) continue;
      if (!rowMatchesFilter(row, tab.filter)) continue;
      this.sendRaw(tab.socket, encoded);
    }
  }

  /** Broadcast a frame that every tab receives unconditionally (counters, issues, acks, server/bridge state). */
  broadcastAll(frame: ServerFrame): void {
    const encoded = JSON.stringify(frame);
    for (const tab of this.tabs) this.sendRaw(tab.socket, encoded);
  }

  private sendRaw(socket: WebSocket, encoded: string): void {
    if (socket.readyState === socket.OPEN) {
      socket.send(encoded);
    }
  }
}

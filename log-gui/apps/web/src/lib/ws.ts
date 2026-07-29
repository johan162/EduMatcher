/** WS client with a thin reconnect wrapper (design §6.1, §6.6). */

import type { ClientFrame, ServerFrame } from "@edumatcher/log-types";

export type WsStatus = "connecting" | "open" | "reconnecting" | "closed";

export class LogStreamClient {
  private socket: WebSocket | null = null;
  private retryDelayMs = 500;
  private stopped = false;

  constructor(
    private readonly onFrame: (frame: ServerFrame) => void,
    private readonly onStatus: (status: WsStatus) => void,
  ) {}

  connect(): void {
    this.stopped = false;
    this.open();
  }

  private open(): void {
    if (this.stopped) return;
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${window.location.host}/ws/stream`;
    this.onStatus("connecting");
    const socket = new WebSocket(url);
    this.socket = socket;

    socket.addEventListener("open", () => {
      this.retryDelayMs = 500;
      this.onStatus("open");
    });

    socket.addEventListener("message", (event) => {
      try {
        const frame = JSON.parse(event.data as string) as ServerFrame;
        this.onFrame(frame);
      } catch {
        // ignore malformed frame
      }
    });

    socket.addEventListener("close", () => {
      if (this.stopped) {
        this.onStatus("closed");
        return;
      }
      this.onStatus("reconnecting");
      setTimeout(() => this.open(), this.retryDelayMs);
      this.retryDelayMs = Math.min(this.retryDelayMs * 2, 10_000);
    });

    socket.addEventListener("error", () => {
      socket.close();
    });
  }

  send(frame: ClientFrame): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(frame));
    }
  }

  close(): void {
    this.stopped = true;
    this.socket?.close();
  }
}

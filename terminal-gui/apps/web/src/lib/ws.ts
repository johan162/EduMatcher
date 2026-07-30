/**
 * Browser WebSocket client with a thin reconnect wrapper (design §5.1, §6.6).
 *
 * There is no auth frame to negotiate, so this needs none of a trading
 * client's session complexity — connect, read JSON frames, retry with capped
 * backoff. The bridge re-sends `hello` and fresh snapshots on every new
 * connection, so a reconnected tab needs no catch-up logic of its own.
 */

import type { ClientFrame, ServerFrame } from "@edumatcher/terminal-types";

export type WsStatus = "connecting" | "open" | "reconnecting" | "closed";

const RETRY_INITIAL_MS = 500;
const RETRY_MAX_MS = 10_000;

export class TerminalStreamClient {
  private socket: WebSocket | null = null;
  private retryDelayMs = RETRY_INITIAL_MS;
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
    this.onStatus("connecting");
    const socket = new WebSocket(`${proto}//${window.location.host}/ws/stream`);
    this.socket = socket;

    socket.addEventListener("open", () => {
      this.retryDelayMs = RETRY_INITIAL_MS;
      this.onStatus("open");
    });

    socket.addEventListener("message", (event) => {
      try {
        this.onFrame(JSON.parse(event.data as string) as ServerFrame);
      } catch {
        // A malformed frame is not worth tearing the session down for.
      }
    });

    socket.addEventListener("close", () => {
      if (this.stopped) {
        this.onStatus("closed");
        return;
      }
      this.onStatus("reconnecting");
      setTimeout(() => this.open(), this.retryDelayMs);
      this.retryDelayMs = Math.min(this.retryDelayMs * 2, RETRY_MAX_MS);
    });

    socket.addEventListener("error", () => socket.close());
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

/**
 * Browser WebSocket client with a thin reconnect wrapper (design §5.1, §6.6).
 *
 * There is no auth frame to negotiate, so this needs none of a trading
 * client's session complexity — connect, read JSON frames, retry with capped
 * backoff.
 *
 * **Standing interest is replayed on every reconnect, and must be.** The
 * bridge reference-counts per-symbol channels across tabs and releases a
 * tab's holds the moment its socket closes, which is correct — but it means
 * a reconnected tab is subscribed to nothing beyond the wildcards, while its
 * components still believe they asked. `DEPTH` and `CB` would simply stop
 * arriving, and a depth ladder frozen on its last pre-outage frame is a book
 * that is wrong rather than absent. The views cannot notice this themselves:
 * their effects are keyed on the symbol, not on the connection.
 *
 * An earlier revision of this comment claimed the bridge sent "fresh
 * snapshots on every new connection", which was never true and is what let
 * both halves of the problem go unnoticed.
 */

import type { ClientFrame, ServerFrame } from "@edumatcher/terminal-types";

export type WsStatus = "connecting" | "open" | "reconnecting" | "closed";

const RETRY_INITIAL_MS = 500;
const RETRY_MAX_MS = 10_000;

export class TerminalStreamClient {
  private socket: WebSocket | null = null;
  private retryDelayMs = RETRY_INITIAL_MS;
  private stopped = false;
  /**
   * Control frames that describe standing interest, keyed so a matching
   * release removes the right one.
   *
   * Held rather than merely forwarded, because the bridge forgets them when
   * the socket closes and the views will never say them again.
   */
  private readonly standing = new Map<string, ClientFrame>();

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
      // Before the status change, so anything reacting to "open" finds the
      // subscriptions already re-declared rather than racing them.
      for (const frame of this.standing.values()) this.transmit(frame);
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
    this.remember(frame);
    this.transmit(frame);
  }

  /**
   * Record or forget standing interest, so it can be replayed on reconnect.
   *
   * `ping` carries no state. Everything else here is a declaration that
   * stays true until withdrawn, which is exactly what a new connection has
   * to be told again.
   */
  private remember(frame: ClientFrame): void {
    switch (frame.t) {
      case "subscribe":
        this.standing.set(`${frame.ch}|${frame.sym}`, frame);
        return;
      case "unsubscribe":
        this.standing.delete(`${frame.ch}|${frame.sym}`);
        return;
      case "halt_board":
        if (frame.open) this.standing.set("halt_board", frame);
        else this.standing.delete("halt_board");
        return;
      case "ping":
        return;
    }
  }

  private transmit(frame: ClientFrame): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(frame));
    }
  }

  close(): void {
    this.stopped = true;
    this.socket?.close();
  }
}

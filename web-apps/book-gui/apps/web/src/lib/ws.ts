/**
 * The tab's WebSocket to the bridge, reconnecting with backoff (design §5.3).
 *
 * The WebSocket constructor is injectable so tests can drive a fake one.
 */

import type { ClientFrame, ServerFrame } from "@edumatcher/book-types";

export interface SocketHandlers {
  onFrame: (frame: ServerFrame) => void;
  onOpen: () => void;
  onClose: () => void;
}

export class BookSocket {
  private socket?: WebSocket;
  private stopped = false;
  private backoffMs = 500;
  private timer?: ReturnType<typeof setTimeout>;

  constructor(
    private readonly url: string,
    private readonly handlers: SocketHandlers,
    private readonly Impl: typeof WebSocket = WebSocket,
  ) {}

  start(): void {
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    clearTimeout(this.timer);
    this.socket?.close();
  }

  send(frame: ClientFrame): void {
    if (this.socket?.readyState === this.Impl.OPEN) this.socket.send(JSON.stringify(frame));
  }

  private connect(): void {
    const socket = new this.Impl(this.url);
    this.socket = socket;
    socket.onopen = () => {
      this.backoffMs = 500;
      this.handlers.onOpen();
    };
    socket.onmessage = (event: MessageEvent<string>) => {
      try {
        this.handlers.onFrame(JSON.parse(event.data) as ServerFrame);
      } catch {
        // A frame that is not JSON is not ours to render.
      }
    };
    socket.onclose = () => {
      this.handlers.onClose();
      if (this.stopped) return;
      this.timer = setTimeout(() => this.connect(), this.backoffMs);
      this.backoffMs = Math.min(this.backoffMs * 2, 10_000);
    };
  }
}

export function streamUrl(loc: Location = window.location): string {
  return `${loc.protocol === "https:" ? "wss" : "ws"}://${loc.host}/ws/stream`;
}

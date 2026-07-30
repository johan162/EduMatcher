/**
 * A `pm-md-gwy` stand-in for tests.
 *
 * Deliberately mirrors the shipped gateway's observable behaviour rather than
 * an idealised one — in particular it answers a post-handshake `HELLO` with
 * `ERR|CODE=BAD_MESSAGE` exactly as `_handle_client_line` does, so a test can
 * prove the bridge never tries to resume that way.
 */

import { createServer, type Server, type Socket } from "node:net";

export interface FakeGatewayOptions {
  /** Advertised in `WELCOME|CH_SUPPORTED=`. Omit the field entirely with `null`. */
  chSupported?: string[] | null;
  /** Advertised in `WELCOME|SYMBOLS=`. Omitted when empty, as the real one does. */
  symbols?: string[];
  /** Accept the connection but send no `WELCOME`. */
  silent?: boolean;
}

export class FakeCalfGateway {
  private server: Server | null = null;
  private readonly sockets = new Set<Socket>();

  /** Every complete line received, across all connections. */
  readonly received: string[] = [];
  connectionCount = 0;
  port = 0;

  constructor(private readonly opts: FakeGatewayOptions = {}) {}

  async start(): Promise<number> {
    const server = createServer((socket) => this.handle(socket));
    this.server = server;
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    if (typeof address === "string" || address === null) throw new Error("no port assigned");
    this.port = address.port;
    return this.port;
  }

  private handle(socket: Socket): void {
    this.connectionCount += 1;
    this.sockets.add(socket);
    socket.on("error", () => undefined);
    socket.on("close", () => this.sockets.delete(socket));

    let authenticated = false;
    let buf = "";

    socket.on("data", (chunk) => {
      buf += chunk.toString("utf8");
      for (;;) {
        const idx = buf.indexOf("\n");
        if (idx < 0) return;
        const line = buf.slice(0, idx);
        buf = buf.slice(idx + 1);
        this.received.push(line);

        if (line.startsWith("HELLO")) {
          if (authenticated) {
            // The real gateway rejects a second HELLO on the same session.
            socket.write("ERR|CODE=BAD_MESSAGE|MSG=unsupported HELLO\n");
            continue;
          }
          authenticated = true;
          if (!this.opts.silent) socket.write(this.welcomeLine());
          continue;
        }
        if (line.startsWith("PING")) socket.write("PONG\n");
      }
    });
  }

  private welcomeLine(): string {
    const channels = this.opts.chSupported ?? ["AUCTION", "CB", "DEPTH", "INDEX", "STATE", "TOP", "TRADE"];
    const parts = ["WELCOME", "PROTO=CALF1", "GW=fake-gwy01", "HBINT=1", "REPLAY=30"];
    if (channels !== null) parts.push(`CH_SUPPORTED=${channels.join(",")}`);
    const symbols = this.opts.symbols ?? [];
    if (symbols.length > 0) parts.push(`SYMBOLS=${symbols.join(",")}`);
    return `${parts.join("|")}\n`;
  }

  /** Push a market-data line to every connected client. */
  emit(line: string): void {
    for (const socket of this.sockets) socket.write(`${line}\n`);
  }

  /** Push raw bytes, so a test can split a line across TCP chunks. */
  emitRaw(text: string): void {
    for (const socket of this.sockets) socket.write(text);
  }

  dropConnections(): void {
    for (const socket of this.sockets) socket.destroy();
    this.sockets.clear();
  }

  /** Lines received on this connection matching a message type. */
  linesStartingWith(prefix: string): string[] {
    return this.received.filter((line) => line.startsWith(prefix));
  }

  async stop(): Promise<void> {
    this.dropConnections();
    const server = this.server;
    this.server = null;
    if (!server) return;
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
}

export async function waitFor(
  predicate: () => boolean,
  timeoutMs = 2000,
  label = "condition",
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error(`timed out after ${timeoutMs}ms waiting for ${label}`);
}

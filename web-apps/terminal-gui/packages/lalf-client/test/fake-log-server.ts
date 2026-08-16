/**
 * A minimal `pm-log-srv` stand-in for tests: speaks enough LALF to complete a
 * handshake and to reassemble the LEN-prefixed frames a client sends, so tests
 * can assert on what actually went over the wire rather than on the client's
 * own internal state.
 */

import { createServer, type Server, type Socket } from "node:net";

export interface ReceivedFrame {
  msgType: string;
  fields: Record<string, string>;
  payload: string | null;
}

export interface FakeLogServerOptions {
  /** `WELCOME.HBINT` in seconds. */
  hbint?: number;
  /** Accept the connection but never answer, to exercise the probe timeout. */
  silent?: boolean;
}

export class FakeLogServer {
  private server: Server | null = null;
  private readonly sockets = new Set<Socket>();

  readonly frames: ReceivedFrame[] = [];
  connectionCount = 0;
  port = 0;

  constructor(private readonly opts: FakeLogServerOptions = {}) {}

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

    let buf = Buffer.alloc(0);
    let pending: { msgType: string; fields: Record<string, string>; len: number } | null = null;

    socket.on("data", (chunk) => {
      buf = Buffer.concat([buf, chunk]);
      for (;;) {
        if (pending) {
          if (buf.length < pending.len) return;
          this.frames.push({
            msgType: pending.msgType,
            fields: pending.fields,
            payload: buf.subarray(0, pending.len).toString("utf8"),
          });
          buf = buf.subarray(pending.len);
          pending = null;
          continue;
        }

        const idx = buf.indexOf(0x0a);
        if (idx < 0) return;
        const line = buf.subarray(0, idx).toString("utf8");
        buf = buf.subarray(idx + 1);

        const parts = line.split("|");
        const msgType = parts[0] ?? "";
        const fields: Record<string, string> = {};
        for (const token of parts.slice(1)) {
          const eq = token.indexOf("=");
          if (eq > 0) fields[token.slice(0, eq)] = token.slice(eq + 1);
        }

        if (msgType === "HELLO" && !this.opts.silent) {
          const hbint = this.opts.hbint ?? 5;
          socket.write(`WELCOME|PROTO=LALF1|SRV=fake-log-srv|HBINT=${hbint}|SESSION=s1\n`);
        }

        const len = fields["LEN"];
        if (len !== undefined) {
          pending = { msgType, fields, len: Number(len) };
          continue;
        }
        this.frames.push({ msgType, fields, payload: null });
      }
    });
  }

  /** Drop every live connection without closing the listener. */
  dropConnections(): void {
    for (const socket of this.sockets) socket.destroy();
    this.sockets.clear();
  }

  framesOfType(msgType: string): ReceivedFrame[] {
    return this.frames.filter((frame) => frame.msgType === msgType);
  }

  async stop(): Promise<void> {
    this.dropConnections();
    const server = this.server;
    this.server = null;
    if (!server) return;
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
}

/** Poll until `predicate` holds, or fail the calling test after `timeoutMs`. */
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

/** A port with nothing listening on it, for probe-failure tests. */
export async function unusedPort(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (typeof address === "string" || address === null) throw new Error("no port assigned");
  const { port } = address;
  await new Promise<void>((resolve) => server.close(() => resolve()));
  return port;
}

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
  /**
   * Advertised in `REF=` alongside `SYMBOLS=`. Omit entirely to model a
   * gateway predating the field; symbols missing from the map are advertised
   * at the default of 2, as the real gateway does.
   */
  tickDecimals?: Record<string, number>;
  /**
   * Answered to a `SYMBOLS` request. Defaults to `symbols`; set separately to
   * model a gateway that started without an engine config (so `WELCOME`
   * carries none) but has since learned instruments from the wire.
   */
  symbolsOnRequest?: string[];
  /** Accept the connection but send no `WELCOME`. */
  silent?: boolean;
}

export class FakeCalfGateway {
  private server: Server | null = null;
  private readonly sockets = new Set<Socket>();
  /**
   * Streams scripted to answer `RESUME` with `ERR|CODE=REPLAY_MISS`, keyed by
   * `${ch}|${sym}` — the real gateway's response once the requested `LASTSEQ`
   * has aged out of its replay window.
   */
  private readonly replayMisses = new Set<string>();

  /**
   * The replay buffer, per `${ch}|${sym}`, mirroring `ReplayBuffer`.
   *
   * Everything `emit` sends is retained here as well as delivered, because
   * that is what the real gateway does — `_emit_stream_event` appends to the
   * buffer and fans out from the same line. It matters: `replay_since` returns
   * every entry *past* `LASTSEQ`, and a client asking to repair a gap asks
   * from its position before the gap, so the reply necessarily re-sends
   * messages already delivered. A fake that only ever replayed the genuinely
   * missing lines would hide whether a client de-duplicates.
   *
   * `seedReplay` adds lines that were never delivered, standing in for events
   * that occurred while a client was disconnected.
   */
  private readonly replayBuffer = new Map<string, Array<{ seq: number; line: string }>>();

  /** Every complete line received, across all connections. */
  readonly received: string[] = [];
  connectionCount = 0;
  port = 0;

  constructor(private readonly opts: FakeGatewayOptions = {}) {}

  /** Answer every `RESUME` for this stream with `REPLAY_MISS`. */
  setReplayMiss(ch: string, sym: string): void {
    this.replayMisses.add(`${ch}|${sym}`);
  }

  /**
   * Put lines in the replay buffer without delivering them — events that
   * happened while the client was not listening, and which only a `RESUME`
   * will surface.
   */
  seedReplay(lines: string[]): void {
    for (const line of lines) this.buffer(line);
  }

  /** Retain one line for replay, exactly as `_emit_stream_event` does. */
  private buffer(line: string): void {
    const fields = parseFields(line);
    const ch = fields["CH"];
    const sym = fields["SYM"];
    const seq = Number(fields["SEQ"]);
    if (!ch || !sym || !Number.isFinite(seq)) return;
    const key = `${ch}|${sym}`;
    const entries = this.replayBuffer.get(key) ?? [];
    entries.push({ seq, line });
    entries.sort((a, b) => a.seq - b.seq);
    this.replayBuffer.set(key, entries);
  }

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

        if (line.startsWith("SYMBOLS")) {
          const known = this.opts.symbolsOnRequest ?? this.opts.symbols ?? [];
          const parts = ["SYMBOLS", `COUNT=${known.length}`];
          // The real gateway omits the field entirely rather than sending it
          // empty, so COUNT is the only reliable indicator of an empty set.
          if (known.length > 0) parts.push(`SYMBOLS=${known.join(",")}`);
          socket.write(`${parts.join("|")}\n`);
        }

        if (line.startsWith("RESUME")) this.handleResume(socket, line);
      }
    });
  }

  private handleResume(socket: Socket, line: string): void {
    const fields = parseFields(line);
    const ch = fields["CH"] ?? "";
    const sym = fields["SYM"] ?? "";
    const lastSeq = Number(fields["LASTSEQ"]);
    const key = `${ch}|${sym}`;

    if (this.replayMisses.has(key)) {
      socket.write(`ERR|CODE=REPLAY_MISS|CH=${ch}|SYM=${sym}\n`);
      // Older gateways followed the ERR with a snapshot on every channel, and
      // `_send_snapshot_for_stream` has no branch for TRADE or AUCTION — so
      // what a client sees is an envelope with no payload, which decoded by CH
      // alone reads as a print of zero shares at zero price. Reproduced here
      // because a client has to survive it whatever this gateway does.
      socket.write(`SNAP|CH=${ch}|SYM=${sym}|SEQ=9001|TS=2026-07-30T14:40:00.000Z\n`);
      return;
    }

    // Everything past LASTSEQ, which is what `replay_since` returns — not
    // "the lines the client is missing". The two differ by exactly the
    // duplicates a client must drop for itself.
    for (const entry of this.replayBuffer.get(key) ?? []) {
      if (entry.seq > lastSeq) socket.write(`${entry.line}\n`);
    }
  }

  private welcomeLine(): string {
    const channels = this.opts.chSupported ?? ["AUCTION", "CB", "DEPTH", "INDEX", "STATE", "TOP", "TRADE"];
    const parts = ["WELCOME", "PROTO=CALF1", "GW=fake-gwy01", "HBINT=1", "REPLAY=30"];
    if (channels !== null) parts.push(`CH_SUPPORTED=${channels.join(",")}`);
    const symbols = this.opts.symbols ?? [];
    if (symbols.length > 0) {
      parts.push(`SYMBOLS=${symbols.join(",")}`);
      const ref = this.opts.tickDecimals;
      if (ref) parts.push(`REF=${symbols.map((s) => `${s}:${ref[s] ?? 2}`).join(",")}`);
    }
    return `${parts.join("|")}\n`;
  }

  /** Push a market-data line to every connected client, and retain it. */
  emit(line: string): void {
    this.buffer(line);
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

/** `MSGTYPE|K=V|K=V` to a field map, ignoring the message type. */
function parseFields(line: string): Record<string, string> {
  return Object.fromEntries(
    line
      .split("|")
      .slice(1)
      .map((pair) => pair.split("=") as [string, string]),
  );
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

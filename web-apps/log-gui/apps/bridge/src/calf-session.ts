/**
 * The exchange session phase, read from `pm-md-gwy` over CALF
 * (EduMatcher-GUI-Apps-Improvements WP-UI01).
 *
 * One TCP connection subscribed to the exchange-wide `STATE` stream only:
 * `SUB|CH=STATE|SYM=*` is answered at once with a `SNAP` of the current phase
 * and, when md-gwy knows one, the next scheduled transition; every later
 * transition arrives as a `STATE` line. CALF needs no credentials, so this
 * works without an API key.
 *
 * md-gwy starts at `SESSION=UNKNOWN` and resolves it by asking the engine,
 * and this uplink reports `UNKNOWN` too whenever md-gwy is unreachable or
 * silent: a remembered `CONTINUOUS` would be a claim nobody is making any
 * more. md-gwy sends `HB` every second, so silence means a dead connection.
 */

import { EventEmitter } from "node:events";
import { Socket } from "node:net";
import type { MarketSession } from "@edumatcher/log-types";

export const UNKNOWN_SESSION: MarketSession = {
  state: "UNKNOWN",
  nextState: null,
  nextAt: null,
};

export interface CalfSessionOptions {
  host: string;
  port: number;
  /** `HELLO|CLIENT=`, at most 32 characters. */
  clientId: string;
  /** No line for this long → the connection is treated as dead. */
  silenceSec?: number;
  backoffMinMs?: number;
  backoffMaxMs?: number;
}

/** `KEY=VALUE` fields of one CALF line, after its message type. */
function parseFields(line: string): {
  msgType: string;
  fields: Record<string, string>;
} {
  const [msgType = "", ...tokens] = line.replace(/\r$/, "").split("|");
  const fields: Record<string, string> = {};
  for (const token of tokens) {
    const eq = token.indexOf("=");
    if (eq > 0) fields[token.slice(0, eq)] = token.slice(eq + 1);
  }
  return { msgType, fields };
}

/** The session a `SNAP`/`STATE` line on the exchange-wide stream describes, else null. */
export function sessionFromLine(line: string): MarketSession | null {
  const { msgType, fields } = parseFields(line);
  if (
    (msgType !== "SNAP" && msgType !== "STATE") ||
    fields["CH"] !== "STATE" ||
    fields["SYM"] !== "*"
  )
    return null;
  const state = fields["SESSION"];
  if (!state) return null;
  // Both or neither, as md-gwy sends them: a phase with no time cannot be
  // counted down to.
  const nextState = fields["NEXTPHASE"];
  const nextAt = fields["NEXTAT"];
  return nextState && nextAt
    ? { state, nextState, nextAt }
    : { state, nextState: null, nextAt: null };
}

export class CalfSessionUplink extends EventEmitter<{
  session: [MarketSession];
}> {
  private socket: Socket | null = null;
  private retry: ReturnType<typeof setTimeout> | null = null;
  private silence: ReturnType<typeof setTimeout> | null = null;
  private backoffMs: number;
  private stopped = true;
  private current: MarketSession = UNKNOWN_SESSION;

  constructor(private readonly opts: CalfSessionOptions) {
    super();
    this.backoffMs = opts.backoffMinMs ?? 500;
  }

  get latest(): MarketSession {
    return this.current;
  }

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.retry) clearTimeout(this.retry);
    if (this.silence) clearTimeout(this.silence);
    this.retry = this.silence = null;
    this.socket?.destroy();
    this.socket = null;
  }

  private connect(): void {
    const socket = new Socket();
    this.socket = socket;
    let buf = "";

    socket.on("connect", () => {
      this.backoffMs = this.opts.backoffMinMs ?? 500;
      socket.write(
        `HELLO|CLIENT=${this.opts.clientId}|PROTO=CALF1\nSUB|CH=STATE|SYM=*\n`,
      );
      this.armSilence(socket);
    });
    socket.on("data", (chunk) => {
      this.armSilence(socket);
      buf += chunk.toString("utf8");
      for (let idx = buf.indexOf("\n"); idx >= 0; idx = buf.indexOf("\n")) {
        const session = sessionFromLine(buf.slice(0, idx));
        buf = buf.slice(idx + 1);
        if (session) this.publish(session);
      }
    });
    socket.on("error", () => undefined);
    socket.on("close", () => {
      if (this.socket !== socket) return;
      this.socket = null;
      if (this.silence) clearTimeout(this.silence);
      this.publish(UNKNOWN_SESSION);
      if (this.stopped) return;
      this.retry = setTimeout(() => this.connect(), this.backoffMs);
      this.retry.unref();
      this.backoffMs = Math.min(
        this.backoffMs * 2,
        this.opts.backoffMaxMs ?? 10_000,
      );
    });
    socket.connect(this.opts.port, this.opts.host);
  }

  private armSilence(socket: Socket): void {
    if (this.silence) clearTimeout(this.silence);
    this.silence = setTimeout(
      () => socket.destroy(),
      (this.opts.silenceSec ?? 10) * 1000,
    );
    this.silence.unref();
  }

  private publish(session: MarketSession): void {
    const prev = this.current;
    if (
      prev.state === session.state &&
      prev.nextState === session.nextState &&
      prev.nextAt === session.nextAt
    )
      return;
    this.current = session;
    this.emit("session", session);
  }
}

/**
 * `LalfClient` — ships this process's operational log records to `pm-log-srv`
 * over LALF (design §17.5), porting the behaviour of
 * `edumatcher.logclient.handler.TcpLogHandler` and `.discovery.resolve_handler`.
 *
 * Three phases, exactly as EduMatcher-log-srv.md §8.3/§8.6 specify:
 *
 *   1. A one-shot startup probe. If the server answers `WELCOME` within
 *      `connectTimeoutSec`, attach; otherwise report failure and let the
 *      caller log to stdout. "No log server running" is a normal condition,
 *      not an error, and must never slow startup.
 *   2. Steady state: every record goes out as a `LOG` frame, with an `HB` sent
 *      whenever the connection has been otherwise idle for `HBINT` seconds.
 *   3. If an attached connection drops, reconnect with capped backoff for
 *      `failoverTimeoutSec`, queueing records meanwhile. Once that window is
 *      exhausted, make a *one-way* switch to a local file and never re-probe —
 *      splitting one run's records across two destinations is worse for an
 *      operator than committing to the second one.
 *
 * Two deliberate differences from the Python original:
 *
 *   - The queue holds records, not pre-encoded frames. The Python client
 *     queues bytes and therefore has to discard its backlog at failover
 *     (`_drain_queue_to_fallback`); holding records lets that backlog be
 *     written to the fallback file instead, which is what §17.5's
 *     "no log call is ever silently dropped" actually asks for.
 *   - The probe reuses its own connection rather than opening a second one.
 *     A successful probe *is* an attached session, so there is nothing to gain
 *     from closing it and immediately reconnecting.
 */

import { createWriteStream, mkdirSync, type WriteStream } from "node:fs";
import { hostname } from "node:os";
import { dirname, join } from "node:path";
import { Socket } from "node:net";
import {
  buildExit,
  buildHb,
  buildHello,
  buildLogFrame,
  isoUtc,
  parseHeaderLine,
  parseWelcome,
  type LogLevel,
  type LogRecord,
} from "./protocol.js";

const BACKOFF_INITIAL_MS = 250;
const BACKOFF_MAX_MS = 5000;
const DEFAULT_HBINT_SEC = 5;

export type LalfState = "IDLE" | "CONNECTED" | "RECONNECTING" | "FAILED_OVER" | "STOPPED";

export interface LalfClientOptions {
  host: string;
  port: number;
  /** `HELLO.CLIENT` — this process's name, e.g. `pm-terminal-bridge`. */
  client: string;
  /** Disambiguates concurrently-running instances of the same process. */
  instance?: string;
  /** Bounded backlog held while reconnecting. Oldest is preserved. */
  queueMaxSize?: number;
  connectTimeoutSec?: number;
  failoverTimeoutSec?: number;
  /** Directory for the post-failover log file. Created on demand. */
  failoverDir?: string;
}

/** A log call from the application, before the client assigns it a sequence. */
export type LogInput = Omit<LogRecord, "seq" | "ts"> & { ts?: string };

export class LalfClient {
  private readonly opts: Required<Omit<LalfClientOptions, "instance">> & { instance?: string };
  private socket: Socket | null = null;
  private queue: LogRecord[] = [];
  private seq = 0;
  private hbintSec = DEFAULT_HBINT_SEC;
  private idleTimer: NodeJS.Timeout | null = null;
  private retryTimer: NodeJS.Timeout | null = null;
  private backoffMs = BACKOFF_INITIAL_MS;
  private downSince: number | null = null;
  private fallback: WriteStream | null = null;

  state: LalfState = "IDLE";
  /** Records discarded because the reconnect backlog was full. */
  droppedCount = 0;

  constructor(options: LalfClientOptions) {
    this.opts = {
      queueMaxSize: 2000,
      connectTimeoutSec: 0.5,
      failoverTimeoutSec: 30,
      failoverDir: "logs",
      ...options,
    };
  }

  /**
   * One-shot startup probe (§17.5 step 1).
   *
   * Resolves `true` once a `WELCOME` has been received and this client is
   * live; `false` if the server did not answer in time, in which case nothing
   * is attached and the caller should log to stdout instead.
   */
  async attach(): Promise<boolean> {
    if (this.state === "STOPPED") return false;
    const socket = await this.tryConnect();
    if (!socket) return false;
    this.adopt(socket);
    return true;
  }

  /** Queue one record for delivery. Never throws, never blocks the caller. */
  log(input: LogInput): void {
    if (this.state === "STOPPED") return;

    this.seq += 1;
    const record: LogRecord = { ...input, seq: this.seq, ts: input.ts ?? isoUtc() };

    if (this.state === "FAILED_OVER") {
      this.writeFallback(record);
      return;
    }

    if (this.queue.length >= this.opts.queueMaxSize) {
      // Oldest-preserved: a burst of new records must not evict the
      // already-queued context that explains why the burst happened.
      this.droppedCount += 1;
      return;
    }
    this.queue.push(record);
    this.flush();
  }

  /** Records waiting to be sent — non-zero only while reconnecting. */
  get queueDepth(): number {
    return this.queue.length;
  }

  async stop(): Promise<void> {
    this.state = "STOPPED";
    this.clearTimers();
    if (this.socket) {
      this.flush();
      try {
        this.socket.write(buildExit());
      } catch {
        // Best effort: the socket may already be gone.
      }
      this.socket.destroy();
      this.socket = null;
    }
    await this.closeFallback();
  }

  // -- connection lifecycle --------------------------------------------------

  /** One connect + handshake attempt. Resolves the socket, or null on failure. */
  private tryConnect(): Promise<Socket | null> {
    return new Promise((resolve) => {
      const socket = new Socket();
      let settled = false;

      const fail = () => {
        if (settled) return;
        settled = true;
        socket.destroy();
        resolve(null);
      };

      const timer = setTimeout(fail, this.opts.connectTimeoutSec * 1000);
      timer.unref?.();

      socket.once("error", fail);
      socket.once("close", fail);

      socket.connect(this.opts.port, this.opts.host, () => {
        socket.write(buildHello(this.opts.client, process.pid, hostname(), this.opts.instance));
      });

      socket.once("data", (chunk: Buffer) => {
        if (settled) return;
        try {
          const line = chunk.toString("utf8").split("\n", 1)[0] ?? "";
          const { msgType, fields } = parseHeaderLine(line);
          if (msgType !== "WELCOME") return fail();
          this.hbintSec = parseWelcome(fields).hbint || DEFAULT_HBINT_SEC;
        } catch {
          return fail();
        }
        settled = true;
        clearTimeout(timer);
        socket.removeListener("error", fail);
        socket.removeListener("close", fail);
        resolve(socket);
      });
    });
  }

  /** Take ownership of a freshly handshaken socket. */
  private adopt(socket: Socket): void {
    this.socket = socket;
    this.state = "CONNECTED";
    this.downSince = null;
    this.backoffMs = BACKOFF_INITIAL_MS;

    socket.on("error", () => this.onDisconnected());
    socket.on("close", () => this.onDisconnected());
    // The server sends HB and may send ERR; neither changes client behaviour,
    // but the stream must be drained or the socket stalls.
    socket.resume();

    this.flush();
    this.armIdleTimer();
  }

  private onDisconnected(): void {
    if (this.state === "STOPPED" || this.state === "FAILED_OVER") return;
    if (this.socket) {
      this.socket.removeAllListeners();
      this.socket.destroy();
      this.socket = null;
    }
    this.state = "RECONNECTING";
    if (this.downSince === null) this.downSince = Date.now();
    this.clearTimers();
    this.scheduleRetry();
  }

  private scheduleRetry(): void {
    if (this.retryTimer) return;
    const delay = this.backoffMs;
    this.backoffMs = Math.min(this.backoffMs * 2, BACKOFF_MAX_MS);

    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      void this.retry();
    }, delay);
    this.retryTimer.unref?.();
  }

  private async retry(): Promise<void> {
    if (this.state !== "RECONNECTING") return;

    const socket = await this.tryConnect();
    if (this.state !== "RECONNECTING") {
      socket?.destroy();
      return;
    }
    if (socket) {
      this.adopt(socket);
      return;
    }

    const downMs = Date.now() - (this.downSince ?? Date.now());
    if (downMs >= this.opts.failoverTimeoutSec * 1000) {
      this.triggerFailover();
      return;
    }
    this.scheduleRetry();
  }

  // -- sending ----------------------------------------------------------------

  private flush(): void {
    if (this.state !== "CONNECTED" || !this.socket) return;
    if (this.queue.length === 0) return;

    const pending = this.queue;
    this.queue = [];
    for (const record of pending) this.socket.write(buildLogFrame(record));
    this.armIdleTimer();
  }

  /**
   * (Re)arm the heartbeat.
   *
   * The server treats a connection as dead if nothing arrives within 2x HBINT,
   * and any message resets that clock — so an `HB` is only needed when the
   * connection has been genuinely idle, not on a fixed wall-clock cadence.
   */
  private armIdleTimer(): void {
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.idleTimer = setTimeout(() => {
      if (this.state !== "CONNECTED" || !this.socket) return;
      this.socket.write(buildHb(isoUtc()));
      this.armIdleTimer();
    }, this.hbintSec * 1000);
    this.idleTimer.unref?.();
  }

  private clearTimers(): void {
    if (this.idleTimer) {
      clearTimeout(this.idleTimer);
      this.idleTimer = null;
    }
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
  }

  // -- failover ----------------------------------------------------------------

  /** Path this run's records go to once the grace window is exhausted. */
  get fallbackPath(): string {
    const name = this.opts.instance ? `${this.opts.client}-${this.opts.instance}` : this.opts.client;
    return join(this.opts.failoverDir, `${name}.log`);
  }

  private triggerFailover(): void {
    if (this.state === "FAILED_OVER") return;
    this.state = "FAILED_OVER";
    this.clearTimers();

    const message =
      `pm-log-srv unreachable for ${Math.round(this.opts.failoverTimeoutSec)}s, ` +
      `falling back to ${this.fallbackPath}`;
    // Written to both stderr and the head of the file, so the switch is
    // visible wherever an operator happens to be looking.
    process.stderr.write(`${message}\n`);
    this.writeFallback({
      seq: 0,
      ts: isoUtc(),
      level: "WARNING" as LogLevel,
      logger: "edumatcher.lalfclient",
      message,
    });

    const backlog = this.queue;
    this.queue = [];
    for (const record of backlog) this.writeFallback(record);
  }

  private writeFallback(record: LogRecord): void {
    if (!this.fallback) {
      mkdirSync(dirname(this.fallbackPath), { recursive: true });
      this.fallback = createWriteStream(this.fallbackPath, { flags: "a", encoding: "utf8" });
      // A broken fallback file must not crash the process it exists to serve.
      this.fallback.on("error", () => undefined);
    }
    this.fallback.write(`${record.ts} ${record.level} ${record.logger} - ${record.message}\n`);
  }

  private closeFallback(): Promise<void> {
    const stream = this.fallback;
    this.fallback = null;
    if (!stream) return Promise.resolve();
    return new Promise((resolve) => stream.end(() => resolve()));
  }
}

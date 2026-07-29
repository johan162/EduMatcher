/**
 * LALF-PS subscription management (design §16.1, §6.5, §6.6).
 *
 * Speaks the wire format `edumatcher.log_srv.pubsub`/`edumatcher.models.message`
 * define: two-frame ZeroMQ multipart messages, frame 0 the UTF-8 topic
 * string, frame 1 a JSON payload. The bridge holds exactly one subscription
 * (`sub_id`) regardless of browser tab count (§6.5) and never sends
 * `log.backfill_request` — history comes from `log.db` (§4.7).
 */

import * as zmq from "zeromq";
import { EventEmitter } from "node:events";
import type { LogRow } from "@edumatcher/log-types";

export type UplinkState = "CONNECTING" | "ACTIVE" | "RECONNECTING" | "SERVER_DOWN";

interface UplinkEvents {
  event: [LogRow[]];
  server_state: [Record<string, unknown>];
  state_change: [UplinkState];
  lease_expired: [];
}

function decodeFrames(frames: Buffer[]): [string, Record<string, unknown>] {
  const topic = frames[0]!.toString("utf8");
  const payload = JSON.parse(frames[1]!.toString("utf8")) as Record<string, unknown>;
  return [topic, payload];
}

function encodeFrames(topic: string, payload: Record<string, unknown>): Buffer[] {
  return [Buffer.from(topic, "utf8"), Buffer.from(JSON.stringify(payload), "utf8")];
}

function rowFromWire(raw: Record<string, unknown>): LogRow {
  return {
    seq: Number(raw.seq),
    client_ts: String(raw.client_ts),
    server_ts: String(raw.server_ts),
    process: String(raw.process),
    instance: raw.instance == null ? null : String(raw.instance),
    pid: Number(raw.pid),
    host: String(raw.host),
    session: String(raw.session),
    level: String(raw.level) as LogRow["level"],
    logger: String(raw.logger),
    module: raw.module == null ? null : String(raw.module),
    line: raw.line == null ? null : Number(raw.line),
    has_exception: Boolean(raw.has_exception),
    truncated: Boolean(raw.truncated),
    message: String(raw.message),
  };
}

export interface LalfPsUplinkOptions {
  host: string;
  pubPort: number;
  pullPort: number;
  subIdPrefix: string;
  leaseSec: number;
  /** How often to check whether the lease needs renewing. */
  renewCheckIntervalMs?: number;
  /** No `server_state` beyond this many heartbeats => SERVER_DOWN (design §6.6). */
  serverDownAfterMissedHeartbeats?: number;
}

export class LalfPsUplink extends EventEmitter<UplinkEvents> {
  readonly subId: string;
  private sub: zmq.Subscriber | null = null;
  private push: zmq.Push | null = null;
  private state: UplinkState = "CONNECTING";
  private renewBeforeSec = this.opts.leaseSec / 2;
  private lastSeqDelivered = 0;
  private lastServerStateAtMs = 0;
  private lastSubscribeSentAtMs = 0;
  private renewTimer: NodeJS.Timeout | null = null;
  private stopped = false;

  constructor(private readonly opts: LalfPsUplinkOptions) {
    super();
    this.subId = `${opts.subIdPrefix}-${process.pid}`;
  }

  private setState(next: UplinkState): void {
    if (this.state === next) return;
    this.state = next;
    this.emit("state_change", next);
  }

  get currentState(): UplinkState {
    return this.state;
  }

  get lastSeq(): number {
    return this.lastSeqDelivered;
  }

  async start(): Promise<void> {
    this.stopped = false;
    const pubAddr = `tcp://${this.opts.host}:${this.opts.pubPort}`;
    const pullAddr = `tcp://${this.opts.host}:${this.opts.pullPort}`;

    this.sub = new zmq.Subscriber();
    this.sub.connect(pubAddr);
    this.sub.subscribe(`log.${this.subId}`);
    this.sub.subscribe("log.server_state");

    this.push = new zmq.Push();
    this.push.connect(pullAddr);

    void this.receiveLoop();

    // Slow-joiner settle (design §16.1 step 3): a message published before
    // the SUB connection finishes establishing is dropped silently.
    await new Promise((resolve) => setTimeout(resolve, 200));
    this.sendSubscribe();

    this.renewTimer = setInterval(
      () => this.tick(),
      this.opts.renewCheckIntervalMs ?? 1000,
    );
  }

  async stop(): Promise<void> {
    this.stopped = true;
    if (this.renewTimer) clearInterval(this.renewTimer);
    if (this.push) {
      // Best-effort courtesy unsubscribe (design §16.1) — awaited so the
      // frame is actually flushed before the socket closes on the next line.
      await this.push.send(encodeFrames("log.unsubscribe", { sub_id: this.subId })).catch(() => {});
    }
    this.sub?.close();
    this.push?.close();
    this.sub = null;
    this.push = null;
  }

  private sendSubscribe(): void {
    if (!this.push) return;
    this.lastSubscribeSentAtMs = Date.now();
    this.push
      .send(
        encodeFrames("log.subscribe", {
          sub_id: this.subId,
          mode: "STREAM",
          lease_sec: this.opts.leaseSec,
        }),
      )
      .catch(() => {
        // transient send failure; the next tick() will retry via the
        // "no ack within 1s" path
      });
  }

  private sendRenew(): void {
    if (!this.push) return;
    this.push
      .send(encodeFrames("log.renew", { sub_id: this.subId, timestamp: Date.now() / 1000 }))
      .catch(() => {
        /* retried on next tick if still unrenewed */
      });
  }

  private tick(): void {
    if (this.stopped) return;
    const now = Date.now();

    if (this.state === "CONNECTING" && now - this.lastSubscribeSentAtMs > 1000) {
      // No subscribe_ack within 1s => retry (idempotent by sub_id, design §16.1 step 6).
      this.sendSubscribe();
    }

    if (this.state === "ACTIVE") {
      const renewAtMs = this.lastSubscribeSentAtMs + this.renewBeforeSec * 1000;
      if (now >= renewAtMs) {
        this.sendRenew();
        this.lastSubscribeSentAtMs = now;
      }
    }

    const missedHeartbeats = this.opts.serverDownAfterMissedHeartbeats ?? 3;
    const heartbeatBudgetMs = missedHeartbeats * 5000; // conservative default heartbeat_interval_sec=5
    if (this.lastServerStateAtMs > 0 && now - this.lastServerStateAtMs > heartbeatBudgetMs) {
      this.setState("SERVER_DOWN");
    }
  }

  private async receiveLoop(): Promise<void> {
    if (!this.sub) return;
    try {
      for await (const frames of this.sub) {
        if (this.stopped) return;
        let decoded: [string, Record<string, unknown>];
        try {
          decoded = decodeFrames(frames as Buffer[]);
        } catch {
          continue;
        }
        const [topic, payload] = decoded;
        this.handleMessage(topic, payload);
      }
    } catch {
      // socket closed during stop(); nothing to do
    }
  }

  private handleMessage(topic: string, payload: Record<string, unknown>): void {
    if (topic === `log.subscribe_ack.${this.subId}`) {
      const renewBefore = Number(payload.renew_before_sec);
      if (Number.isFinite(renewBefore) && renewBefore > 0) this.renewBeforeSec = renewBefore;
      const lastSeq = Number(payload.last_seq);
      if (Number.isFinite(lastSeq)) this.lastSeqDelivered = Math.max(this.lastSeqDelivered, lastSeq);
      this.setState("ACTIVE");
      return;
    }
    if (topic === `log.renew_ack.${this.subId}`) {
      this.setState("ACTIVE");
      return;
    }
    if (topic === `log.event.${this.subId}`) {
      const rawRows = Array.isArray(payload.rows) ? (payload.rows as Record<string, unknown>[]) : [];
      const rows = rawRows.map(rowFromWire);
      for (const row of rows) this.lastSeqDelivered = Math.max(this.lastSeqDelivered, row.seq);
      if (rows.length > 0) this.emit("event", rows);
      return;
    }
    if (topic === `log.lease_expired.${this.subId}`) {
      this.setState("RECONNECTING");
      this.emit("lease_expired");
      this.sendSubscribe();
      return;
    }
    if (topic === `log.error.${this.subId}`) {
      if (payload.code === "UNKNOWN_SUB") {
        this.setState("RECONNECTING");
        this.emit("lease_expired");
        this.sendSubscribe();
      }
      return;
    }
    if (topic === "log.server_state") {
      this.lastServerStateAtMs = Date.now();
      const state = String(payload.state ?? "");
      if (state === "UP" && this.state !== "ACTIVE") {
        // Server came back; re-subscribe rather than assume the old lease survived.
        this.sendSubscribe();
      } else if (state === "DOWN") {
        this.setState("SERVER_DOWN");
      }
      this.emit("server_state", payload);
      return;
    }
  }
}

/**
 * The bridge's one subscription to pm-monitor (design §11, WP-C2.1).
 *
 * A ZeroMQ SUB on pm-monitor's PUB socket (`monitor.pub_port`), filtered to
 * the `health.` family. Every message is two frames, the UTF-8 topic and a
 * JSON payload (`edumatcher.models.message.encode`), as log-gui's LALF-PS
 * uplink decodes them. ZeroMQ reconnects a SUB by itself, so there is no
 * reconnect logic here: the state is simply UP while snapshots arrive and
 * DOWN once none has for `downAfterSec` (pm-monitor publishes at 1 Hz).
 *
 * The payload is kept as received — its parsed object for the bridge's own
 * use (`exchange.session_timezone`) and its raw text, so the fan-out can
 * frame it for every tab without serialising it again.
 */

import { EventEmitter } from "node:events";
import * as zmq from "zeromq";
import type { HealthEvent, HealthSnapshot, MonitorState } from "@edumatcher/dash-types";

export const TOPIC_SNAPSHOT = "health.snapshot";
export const TOPIC_EVENT = "health.event";

/** A payload as parsed, with the exact JSON text it arrived as. */
export interface Received<T> {
  data: T;
  json: string;
}

interface UplinkEvents {
  snapshot: [Received<HealthSnapshot>];
  event: [Received<HealthEvent>];
  state: [MonitorState];
}

export interface MonitorUplinkOptions {
  host: string;
  pubPort: number;
  downAfterSec: number;
  /** How often silence is checked; a tenth of a second keeps DOWN prompt. */
  checkIntervalMs?: number;
  now?: () => number;
}

export class MonitorUplink extends EventEmitter<UplinkEvents> {
  private sub: zmq.Subscriber | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private stateValue: MonitorState = "DOWN";
  private stateSinceMs: number;
  private lastSnapshotAtMs = -Infinity;
  private latestSnapshot: Received<HealthSnapshot> | null = null;
  private readonly now: () => number;
  snapshotsIn = 0;
  eventsIn = 0;
  /** Messages that were not two frames of topic + JSON object. */
  invalidIn = 0;

  constructor(private readonly opts: MonitorUplinkOptions) {
    super();
    this.now = opts.now ?? Date.now;
    this.stateSinceMs = this.now();
  }

  get address(): string {
    return `tcp://${this.opts.host}:${this.opts.pubPort}`;
  }

  get state(): MonitorState {
    return this.stateValue;
  }

  get stateSince(): number {
    return this.stateSinceMs;
  }

  /** The latest snapshot, while UP; a stale one is never handed out. */
  get latest(): Received<HealthSnapshot> | null {
    return this.stateValue === "UP" ? this.latestSnapshot : null;
  }

  start(): void {
    this.sub = new zmq.Subscriber();
    this.sub.connect(this.address);
    this.sub.subscribe("health.");
    void this.receiveLoop(this.sub);
    this.timer = setInterval(() => this.checkSilence(), this.opts.checkIntervalMs ?? 100);
    this.timer.unref();
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.sub?.close();
    this.sub = null;
  }

  /** One received message; public so tests can feed frames without a socket. */
  handle(frames: Buffer[]): void {
    if (frames.length < 2) {
      this.invalidIn += 1;
      return;
    }
    const topic = frames[0]!.toString("utf8");
    if (topic !== TOPIC_SNAPSHOT && topic !== TOPIC_EVENT) return;
    const json = frames[1]!.toString("utf8");
    let data: unknown;
    try {
      data = JSON.parse(json);
    } catch {
      this.invalidIn += 1;
      return;
    }
    if (typeof data !== "object" || data === null || Array.isArray(data)) {
      this.invalidIn += 1;
      return;
    }
    if (topic === TOPIC_SNAPSHOT) {
      this.snapshotsIn += 1;
      this.lastSnapshotAtMs = this.now();
      this.latestSnapshot = { data: data as HealthSnapshot, json };
      this.setState("UP");
      this.emit("snapshot", this.latestSnapshot);
    } else {
      this.eventsIn += 1;
      this.emit("event", { data: data as HealthEvent, json });
    }
  }

  /** Flip to DOWN after the silence limit; public so tests can drive the clock. */
  checkSilence(): void {
    if (this.stateValue === "UP" && this.now() - this.lastSnapshotAtMs >= this.opts.downAfterSec * 1000) {
      this.setState("DOWN");
    }
  }

  private setState(next: MonitorState): void {
    if (this.stateValue === next) return;
    this.stateValue = next;
    this.stateSinceMs = this.now();
    this.emit("state", next);
  }

  private async receiveLoop(sub: zmq.Subscriber): Promise<void> {
    try {
      for await (const frames of sub) this.handle(frames as Buffer[]);
    } catch {
      // the socket was closed by stop()
    }
  }
}

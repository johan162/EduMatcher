/**
 * Rate-aware live delivery (`LIVE_BATCH_THRESHOLD_PER_SEC`).
 *
 * A quiet venue and a storm want opposite things from the WebSocket. At a few
 * rows a second, one frame per row is what makes the tail feel immediate. At
 * thousands, one frame per row is thousands of `JSON.stringify` calls, socket
 * writes and React state updates per second per tab — the browser stops
 * rendering long before the bridge stops sending.
 *
 * So: below the threshold, forward each row as it arrives. Above it, coalesce
 * into the `events` frame the protocol already defines. The rate is measured
 * over a trailing one-second window, so the switch is automatic in both
 * directions and needs no operator intervention.
 *
 * Ordering is preserved unconditionally: once anything is buffered, later rows
 * queue behind it even if the rate falls back below the threshold. Emitting a
 * fresh row directly while older rows waited in the buffer would deliver them
 * out of sequence, and `seq` order is the one thing a log tail must not break.
 */

import type { LogRow } from "@edumatcher/log-types";

const RATE_WINDOW_MS = 1000;

export interface LiveBatcherOptions {
  /** Rows/sec strictly above which batching engages. */
  thresholdPerSec: number;
  /** How often a non-empty buffer is flushed while batching. */
  flushIntervalMs?: number;
  emitOne: (row: LogRow) => void;
  emitMany: (rows: LogRow[]) => void;
  /** Injectable for tests. */
  now?: () => number;
}

export class LiveBatcher {
  private readonly recent: number[] = [];
  private buffer: LogRow[] = [];
  private timer: NodeJS.Timeout | null = null;
  private readonly flushIntervalMs: number;
  private readonly now: () => number;

  constructor(private readonly opts: LiveBatcherOptions) {
    this.flushIntervalMs = opts.flushIntervalMs ?? 100;
    this.now = opts.now ?? Date.now;
  }

  /** Rows seen in the trailing second — the value compared to the threshold. */
  get currentRatePerSec(): number {
    this.pruneRateWindow(this.now());
    return this.recent.length;
  }

  get batching(): boolean {
    return this.buffer.length > 0;
  }

  ingest(row: LogRow): void {
    const now = this.now();
    this.recent.push(now);
    this.pruneRateWindow(now);

    // Buffer non-empty => keep buffering, whatever the rate says (ordering).
    if (this.buffer.length === 0 && this.recent.length <= this.opts.thresholdPerSec) {
      this.opts.emitOne(row);
      return;
    }

    this.buffer.push(row);
    if (this.timer === null) {
      this.timer = setTimeout(() => this.flush(), this.flushIntervalMs);
    }
  }

  /** Emits whatever is buffered. Safe to call when empty. */
  flush(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    if (this.buffer.length === 0) return;
    const rows = this.buffer;
    this.buffer = [];
    this.opts.emitMany(rows);
  }

  /** Flushes and stops. Called at shutdown so buffered rows are not dropped. */
  stop(): void {
    this.flush();
  }

  private pruneRateWindow(nowMs: number): void {
    const cutoff = nowMs - RATE_WINDOW_MS;
    while (this.recent.length > 0 && this.recent[0]! <= cutoff) {
      this.recent.shift();
    }
  }
}

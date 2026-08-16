/**
 * Rolling in-memory counters emitted as a WS `counters` frame at ~1 Hz
 * (design §6.4, §8.4, §17) — a storm produces one frame per second
 * regardless of ingest rate.
 */

import type { CounterWindow, LogRow } from "@edumatcher/log-types";

const WINDOW_SEC = 60;

interface TimestampedEvent {
  atMs: number;
  level: string;
  process: string;
}

export class RollingCounters {
  private events: TimestampedEvent[] = [];
  private serverLastSeq = 0;

  ingest(row: LogRow): void {
    this.events.push({ atMs: Date.now(), level: row.level, process: row.process });
    this.serverLastSeq = Math.max(this.serverLastSeq, row.seq);
  }

  private prune(nowMs: number): void {
    const cutoff = nowMs - WINDOW_SEC * 1000;
    while (this.events.length > 0 && this.events[0]!.atMs < cutoff) {
      this.events.shift();
    }
  }

  snapshot(): CounterWindow {
    const now = Date.now();
    this.prune(now);

    const perLevel: Record<string, number> = {};
    const perProcess: Record<string, number> = {};
    let errorCount = 0;
    for (const evt of this.events) {
      perLevel[evt.level] = (perLevel[evt.level] ?? 0) + 1;
      perProcess[evt.process] = (perProcess[evt.process] ?? 0) + 1;
      if (evt.level === "ERROR" || evt.level === "CRITICAL") errorCount += 1;
    }

    const minutes = WINDOW_SEC / 60;
    return {
      eventsPerMin: this.events.length / minutes,
      errorsPerMin: errorCount / minutes,
      perLevel,
      perProcess,
      windowSec: WINDOW_SEC,
      serverLastSeq: this.serverLastSeq,
    };
  }
}

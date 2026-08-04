/**
 * LIVE_BATCH_THRESHOLD_PER_SEC.
 *
 * Before this existed the variable was parsed and ignored, so every row got
 * its own WS frame at any rate. These tests pin the two properties that make
 * batching safe to switch on automatically: it engages only above the
 * threshold, and it never reorders rows.
 */

import { describe, expect, it, vi } from "vitest";
import { LiveBatcher } from "../src/live-batcher.js";
import type { LogRow } from "@edumatcher/log-types";

function row(seq: number): LogRow {
  return {
    seq,
    client_ts: "2026-08-04T10:00:00.000000+00:00",
    server_ts: "2026-08-04T10:00:00.000000+00:00",
    process: "pm-engine",
    instance: null,
    pid: 1,
    host: "h",
    session: "s",
    level: "INFO",
    logger: "l",
    module: null,
    line: null,
    has_exception: false,
    truncated: false,
    message: `m${seq}`,
  };
}

interface Harness {
  batcher: LiveBatcher;
  singles: LogRow[];
  batches: LogRow[][];
  advance: (ms: number) => void;
}

function harness(thresholdPerSec: number): Harness {
  const singles: LogRow[] = [];
  const batches: LogRow[][] = [];
  let clock = 0;
  const batcher = new LiveBatcher({
    thresholdPerSec,
    flushIntervalMs: 100,
    emitOne: (r) => singles.push(r),
    emitMany: (rs) => batches.push(rs),
    now: () => clock,
  });
  return {
    batcher,
    singles,
    batches,
    advance: (ms) => {
      clock += ms;
      vi.advanceTimersByTime(ms);
    },
  };
}

describe("LiveBatcher", () => {
  it("sends one frame per row while the rate is at or below the threshold", () => {
    const h = harness(5);
    for (let i = 1; i <= 5; i++) h.batcher.ingest(row(i));

    expect(h.singles.map((r) => r.seq)).toEqual([1, 2, 3, 4, 5]);
    expect(h.batches).toEqual([]);
  });

  it("coalesces once the rate exceeds the threshold", () => {
    vi.useFakeTimers();
    try {
      const h = harness(5);
      for (let i = 1; i <= 8; i++) h.batcher.ingest(row(i));

      // The first 5 fit under the threshold and go out individually; the
      // rest are held.
      expect(h.singles.map((r) => r.seq)).toEqual([1, 2, 3, 4, 5]);
      expect(h.batches).toEqual([]);

      h.advance(100);
      expect(h.batches).toHaveLength(1);
      expect(h.batches[0]!.map((r) => r.seq)).toEqual([6, 7, 8]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("never reorders: a row arriving while the buffer is occupied queues behind it", () => {
    vi.useFakeTimers();
    try {
      const h = harness(2);
      // Push past the threshold so rows 3+ buffer.
      for (let i = 1; i <= 4; i++) h.batcher.ingest(row(i));
      expect(h.batcher.batching).toBe(true);

      // Let the rate window age out so the measured rate drops back to zero,
      // but do NOT let the flush timer fire.
      h.advance(50);
      expect(h.batcher.currentRatePerSec).toBeGreaterThan(0);

      h.batcher.ingest(row(5));
      // 5 must not overtake 3 and 4 by being emitted directly.
      expect(h.singles.map((r) => r.seq)).toEqual([1, 2]);

      h.advance(100);
      expect(h.batches[0]!.map((r) => r.seq)).toEqual([3, 4, 5]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("returns to per-row delivery once the burst is fully drained", () => {
    vi.useFakeTimers();
    try {
      const h = harness(2);
      for (let i = 1; i <= 4; i++) h.batcher.ingest(row(i));
      h.advance(100);
      expect(h.batches).toHaveLength(1);

      // Well past the rate window: the burst is gone from the measurement.
      h.advance(1500);
      h.batcher.ingest(row(9));
      expect(h.singles.map((r) => r.seq)).toEqual([1, 2, 9]);
      expect(h.batches).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("flushes buffered rows on stop rather than dropping them", () => {
    vi.useFakeTimers();
    try {
      const h = harness(1);
      for (let i = 1; i <= 3; i++) h.batcher.ingest(row(i));
      expect(h.batcher.batching).toBe(true);

      h.batcher.stop();
      expect(h.batches[0]!.map((r) => r.seq)).toEqual([2, 3]);
      expect(h.batcher.batching).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("a threshold of zero batches everything", () => {
    vi.useFakeTimers();
    try {
      const h = harness(0);
      h.batcher.ingest(row(1));
      expect(h.singles).toEqual([]);
      h.advance(100);
      expect(h.batches[0]!.map((r) => r.seq)).toEqual([1]);
    } finally {
      vi.useRealTimers();
    }
  });
});

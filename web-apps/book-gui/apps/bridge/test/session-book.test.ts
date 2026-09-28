import { describe, expect, it } from "vitest";
import type { TapeTrade } from "@edumatcher/book-types";
import { SessionBook } from "../src/session/session-book.js";

const t = (n: number, px: number, qty = 10, tsMs = n * 1000): TapeTrade => ({
  id: `000001-${String(n).padStart(9, "0")}`,
  tsMs,
  px,
  qty,
  side: "BUY",
});
const META = { sessionDate: "2026-09-27", timezone: "Europe/Stockholm" };

describe("SessionBook", () => {
  it("buffers live prints until the history seed, then counts each trade once", () => {
    const s = new SessionBook(100);
    expect(s.addLive(t(3, 12))).toBeUndefined(); // buffered
    expect(s.addLive(t(4, 13))).toBeUndefined();
    s.seed([t(2, 11), t(1, 10), t(3, 12)], { ...META, prevClose: 9 });

    const { stats, tape } = s.snapshot();
    expect(tape.map((x) => x.px)).toEqual([10, 11, 12, 13]);
    expect(stats).toEqual({
      open: 10,
      high: 13,
      low: 10,
      close: 13,
      prevClose: 9,
      volume: 40,
      tradeCount: 4,
      partial: false,
      sessionDate: "2026-09-27",
      timezone: "Europe/Stockholm",
    });
    expect(s.addLive(t(4, 13))).toBeUndefined(); // duplicate
    expect(s.addLive(t(5, 8))).toEqual(t(5, 8));
    expect(s.snapshot().stats).toMatchObject({ low: 8, close: 8, volume: 50 });
  });

  it("orders open, close and the tape by trade id, not arrival", () => {
    const s = new SessionBook(100);
    s.seed([], META);
    s.addLive(t(7, 70));
    s.addLive(t(5, 50));
    s.addLive(t(6, 60));
    const { stats, tape } = s.snapshot();
    expect([stats.open, stats.close]).toEqual([50, 70]);
    expect(tape.map((x) => x.px)).toEqual([50, 60, 70]);
  });

  it("keeps only the newest tapeMax prints but counts them all", () => {
    const s = new SessionBook(3);
    s.seed(
      [1, 2, 3, 4, 5].map((n) => t(n, n)),
      META,
    );
    const { stats, tape } = s.snapshot();
    expect(tape.map((x) => x.px)).toEqual([3, 4, 5]);
    expect(stats.tradeCount).toBe(5);
  });

  it("marks a history-less session partial, since its first live print", () => {
    const s = new SessionBook(10);
    s.addLive(t(1, 5, 1, 1234));
    s.seedPartial(9999);
    expect(s.snapshot().stats).toMatchObject({ partial: true, since: 1234, volume: 1, timezone: "UTC" });

    const empty = new SessionBook(10);
    empty.seedPartial(9999);
    expect(empty.snapshot().stats.since).toBe(9999);
  });

  it("reset returns to seeding and bumps the generation", () => {
    const s = new SessionBook(10);
    s.seed([t(1, 1)], META);
    s.reset();
    expect(s.seeding).toBe(true);
    expect(s.generation).toBe(1);
    expect(s.snapshot().stats.volume).toBe(0);
    s.seed([t(1, 1), t(2, 2)], META);
    expect(s.snapshot().stats.volume).toBe(20);
  });

  it("returns copies, so a sent frame cannot be mutated by a later print", () => {
    const s = new SessionBook(10);
    s.seed([t(1, 1)], META);
    const before = s.snapshot();
    s.addLive(t(2, 2));
    expect(before.stats.volume).toBe(10);
    expect(before.tape).toHaveLength(1);
  });
});

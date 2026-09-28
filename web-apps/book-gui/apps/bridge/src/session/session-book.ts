/**
 * One watched symbol's session: its latest book, trade tape and OHLCV
 * (design §7.2, WP4).
 *
 * Every trade reaches the statistics through `add`, whichever path delivered
 * it — the history seed, the gateway's cached tail on subscribe, a resume
 * replay, or a live print — and is counted once, by trade id. Trade ids are
 * fixed-width `<run_seq>-<counter>` strings, so they sort in print order;
 * that is what orders open, close and the tape even when an older print
 * arrives after a newer one. Same rules as pm-viewer's `_SessionStats`.
 *
 * Seeding is race-free because live trades are buffered until the history
 * has been applied: a print from before the subscription is in history, one
 * during the paging is in the buffer (and in history too if pm-stats
 * committed it in time — the id de-duplicates it), one after is live.
 */

import type { BookFrame, SessionStats, TapeTrade } from "@edumatcher/book-types";

export interface SeedMeta {
  sessionDate: string;
  timezone: string;
  prevClose?: number;
}

export class SessionBook {
  book?: BookFrame;
  seeding = true;
  /** Bumped by `reset`, so a seed that was overtaken by a newer one can tell. */
  generation = 0;

  private stats: SessionStats = { volume: 0, tradeCount: 0, partial: false, timezone: "UTC" };
  private tape: TapeTrade[] = [];
  private readonly seen = new Set<string>();
  private buffer: TapeTrade[] = [];
  private firstId?: string;
  private lastId?: string;

  constructor(private readonly tapeMax: number) {}

  /** Buffered while seeding. Returns the trade when it was applied, undefined for a duplicate. */
  addLive(trade: TapeTrade): TapeTrade | undefined {
    if (this.seeding) {
      this.buffer.push(trade);
      return undefined;
    }
    return this.add(trade) ? trade : undefined;
  }

  /** Apply today's history (any order), then everything that arrived meanwhile. */
  seed(history: TapeTrade[], meta: SeedMeta): void {
    this.stats.sessionDate = meta.sessionDate;
    this.stats.timezone = meta.timezone;
    if (meta.prevClose !== undefined) this.stats.prevClose = meta.prevClose;
    for (const trade of [...history].sort(byId)) this.add(trade);
    this.goLive();
  }

  /** History is unavailable: count only what is seen from now on, and say so. */
  seedPartial(now: number): void {
    this.stats.partial = true;
    this.stats.since = this.buffer[0]?.tsMs ?? now;
    this.goLive();
  }

  /** Forget everything but the book, ready for a fresh `seed`. */
  reset(): void {
    this.stats = { volume: 0, tradeCount: 0, partial: false, timezone: "UTC" };
    this.tape = [];
    this.seen.clear();
    this.buffer = [];
    this.firstId = undefined;
    this.lastId = undefined;
    this.seeding = true;
    this.generation += 1;
  }

  snapshot(): { stats: SessionStats; tape: TapeTrade[] } {
    return { stats: { ...this.stats }, tape: [...this.tape] };
  }

  private goLive(): void {
    const buffered = this.buffer;
    this.buffer = [];
    this.seeding = false;
    for (const trade of buffered) this.add(trade);
  }

  private add(trade: TapeTrade): boolean {
    if (this.seen.has(trade.id)) return false;
    this.seen.add(trade.id);

    const s = this.stats;
    if (this.firstId === undefined || trade.id < this.firstId) {
      s.open = trade.px;
      this.firstId = trade.id;
    }
    if (this.lastId === undefined || trade.id > this.lastId) {
      s.close = trade.px;
      this.lastId = trade.id;
    }
    s.high = s.high === undefined ? trade.px : Math.max(s.high, trade.px);
    s.low = s.low === undefined ? trade.px : Math.min(s.low, trade.px);
    s.volume += trade.qty;
    s.tradeCount += 1;

    this.tape.push(trade);
    const prev = this.tape[this.tape.length - 2];
    if (prev && prev.id > trade.id) this.tape.sort(byId);
    if (this.tape.length > this.tapeMax) this.tape.splice(0, this.tape.length - this.tapeMax);
    return true;
  }
}

function byId(a: TapeTrade, b: TapeTrade): number {
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

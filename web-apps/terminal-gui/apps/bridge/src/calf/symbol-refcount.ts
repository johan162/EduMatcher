/**
 * Shared per-symbol subscription reference counting (design §6.5, §13.2).
 *
 * `DEPTH` and `CB` are the two CALF channels that refuse `SYM=*`, so the
 * bridge has to hold them per symbol and know when nobody is looking anymore.
 * Several independent parties can want the same one at once — two tabs on the
 * same Symbol Detail view, plus the Session board once that symbol halts — so
 * a plain "subscribe on open, unsubscribe on close" would tear down a
 * subscription another tab is still reading.
 *
 * This class owns only the counting and the 0↔1 edges. Who holds what is the
 * WS hub's business; issuing the actual `SUB`/`UNSUB` is the uplink's.
 */

import type { WatchChannel } from "@edumatcher/terminal-types";

type Key = `${WatchChannel}|${string}`;

const keyOf = (ch: WatchChannel, sym: string): Key => `${ch}|${sym}`;

export interface RefCountHandlers {
  /** Called on the 0→1 edge only. */
  onFirst: (ch: WatchChannel, sym: string) => void;
  /** Called on the →0 edge only. */
  onLast: (ch: WatchChannel, sym: string) => void;
}

export class SymbolRefCount {
  private readonly counts = new Map<Key, number>();

  constructor(private readonly handlers: RefCountHandlers) {}

  /** Register one interested party. Fires `onFirst` if this is the first. */
  acquire(ch: WatchChannel, sym: string): void {
    const key = keyOf(ch, sym);
    const next = (this.counts.get(key) ?? 0) + 1;
    this.counts.set(key, next);
    if (next === 1) this.handlers.onFirst(ch, sym);
  }

  /**
   * Drop one interested party. Fires `onLast` when the last one goes.
   *
   * Releasing something never acquired is a no-op rather than an error: a tab
   * can disconnect mid-handshake, and a spurious `UNSUB` for a subscription
   * the bridge does not hold is worse than doing nothing.
   */
  release(ch: WatchChannel, sym: string): void {
    const key = keyOf(ch, sym);
    const current = this.counts.get(key);
    if (current === undefined) return;

    if (current <= 1) {
      this.counts.delete(key);
      this.handlers.onLast(ch, sym);
      return;
    }
    this.counts.set(key, current - 1);
  }

  count(ch: WatchChannel, sym: string): number {
    return this.counts.get(keyOf(ch, sym)) ?? 0;
  }

  /**
   * Every currently-held `(channel, symbol)` pair.
   *
   * Used on reconnect: these are exactly the per-symbol subscriptions the
   * bridge must re-issue, since there is no wildcard form to fall back on.
   */
  active(): Array<{ ch: WatchChannel; sym: string }> {
    return [...this.counts.keys()].map((key) => {
      const [ch, sym] = key.split("|") as [WatchChannel, string];
      return { ch, sym };
    });
  }
}

/**
 * Per-topic sequence tracking and gap detection (§17.3.1, §26.3.2).
 *
 * Every market-data envelope carries a `seq` monotonic **within its topic**.
 * A skip means the client missed events on that topic; the repair is a
 * targeted `resume`, not a full re-subscribe.
 *
 * Deliberately tolerant of two shapes that are not gaps:
 *  - the first `seq` seen for a topic (there is nothing to compare against —
 *    the client may well have connected mid-stream)
 *  - a replayed or duplicated `seq` at or below the high-water mark, which a
 *    resume/snapshot answer produces by construction and which must not be
 *    allowed to walk the counter backwards
 */

export interface SeqGap {
  topic: string;
  /** The seq that was expected next. */
  expected: number;
  /** The seq that actually arrived. */
  received: number;
  /** How many events were missed. */
  missed: number;
}

export class SeqTracker {
  private last = new Map<string, number>();

  /** Record `seq` for `topic`; returns the gap it revealed, or null. */
  observe(topic: string, seq: number | undefined): SeqGap | null {
    if (topic === "" || seq === undefined || !Number.isFinite(seq)) return null;
    const prev = this.last.get(topic);
    if (prev === undefined) {
      this.last.set(topic, seq);
      return null;
    }
    if (seq <= prev) return null; // duplicate or replay — not a gap
    this.last.set(topic, seq);
    if (seq === prev + 1) return null;
    return { topic, expected: prev + 1, received: seq, missed: seq - prev - 1 };
  }

  /** High-water mark for a topic, or undefined if none seen. */
  lastSeq(topic: string): number | undefined {
    return this.last.get(topic);
  }

  /** Forget one topic (after a `*.reset`) or all of them (on disconnect). */
  reset(topic?: string): void {
    if (topic === undefined) this.last.clear();
    else this.last.delete(topic);
  }

  /** Snapshot of the tracked high-water marks, for replay annotation. */
  entries(): [string, number][] {
    return [...this.last.entries()];
  }
}

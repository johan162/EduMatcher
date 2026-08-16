/**
 * Per-symbol top-of-book cache (design §17.3, corrected).
 *
 * CALF `MD` messages are deltas: the gateway's `normalise_book` diffs against
 * its own cache and emits only the fields that changed. A browser tab that
 * joined mid-session, or one rendering a symbol whose ask has not moved in an
 * hour, would otherwise see holes in a frame it is entitled to read as
 * complete. Merging once here — server-side, shared across every tab — is
 * both cheaper and simpler than making each tab do it.
 *
 * Absent stays absent: a symbol with no trades yet has no `last`, and that is
 * information the UI should render as a dash rather than as zero.
 */

import type { TopDelta } from "@edumatcher/calf-protocol";
import type { TopOfBook } from "@edumatcher/terminal-types";

export class TopCache {
  private readonly bySymbol = new Map<string, TopOfBook>();

  /**
   * Apply a `SNAP`/`MD` delta and return the symbol's full merged state.
   *
   * A `null` in the delta means the gateway withdrew that side — the book has
   * no bid or no ask — so the field is *removed* rather than overwritten. That
   * keeps a merged view identical to the `SNAP` a reconnecting client would
   * get, which is exactly what diverged before CALF gained an explicit
   * withdrawal marker.
   *
   * The returned object is detached from the cache: it is about to be spread
   * into a frame and handed to every connected tab, and a shared reference
   * would let any of them corrupt what the next delta merges onto.
   */
  merge(symbol: string, delta: TopDelta): TopOfBook {
    const merged: TopOfBook = { ...this.bySymbol.get(symbol) };

    for (const [key, value] of Object.entries(delta) as Array<[keyof TopOfBook, number | null]>) {
      if (value === null) delete merged[key];
      else merged[key] = value;
    }

    this.bySymbol.set(symbol, merged);
    return { ...merged };
  }

  get(symbol: string): TopOfBook | undefined {
    return this.bySymbol.get(symbol);
  }

  /**
   * Every symbol's current merged book, for replay to a newly-connected tab.
   *
   * Detached copies, for the same reason `merge` returns one: these are
   * about to be handed to a browser and must not alias what the next delta
   * merges onto.
   */
  entries(): Array<[string, TopOfBook]> {
    return [...this.bySymbol.entries()].map(([sym, book]) => [sym, { ...book }]);
  }

  get size(): number {
    return this.bySymbol.size;
  }
}

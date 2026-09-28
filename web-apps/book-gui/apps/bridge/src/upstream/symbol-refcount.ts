/**
 * Which symbols any tab is watching (design §5.2).
 *
 * The upstream subscription follows the count: subscribe on 0→1, unsubscribe
 * on 1→0, so two tabs on one symbol share a single upstream subscription.
 */
export class SymbolRefcount {
  private readonly counts = new Map<string, number>();

  /** True when this is the first holder, i.e. the caller must subscribe. */
  acquire(sym: string): boolean {
    const n = this.counts.get(sym) ?? 0;
    this.counts.set(sym, n + 1);
    return n === 0;
  }

  /** True when this was the last holder, i.e. the caller must unsubscribe. */
  release(sym: string): boolean {
    const n = this.counts.get(sym);
    if (n === undefined) return false;
    if (n > 1) {
      this.counts.set(sym, n - 1);
      return false;
    }
    this.counts.delete(sym);
    return true;
  }

  held(): Record<string, number> {
    return Object.fromEntries(this.counts);
  }
}

/**
 * Paging arithmetic for the Overview grid (design §8.3).
 *
 * Paging is purely a rendering concern: every symbol is already flowing into
 * the tab from the bridge's always-on wildcard subscriptions, so rows on pages
 * nobody is looking at stay just as live as the visible ones. Nothing here
 * subscribes or unsubscribes to anything.
 */

/** Pages needed for `total` items, never fewer than one. */
export function pageCount(total: number, perPage: number): number {
  if (perPage <= 0) return 1;
  return Math.max(1, Math.ceil(total / perPage));
}

/** Keep a page index inside the current bounds, wrapping at both ends. */
export function wrapPage(page: number, total: number, perPage: number): number {
  const count = pageCount(total, perPage);
  return ((page % count) + count) % count;
}

/**
 * Clamp rather than wrap — used when the row count shrinks under a viewer
 * (a watchlist filter, a smaller window) and the current page falls off the
 * end. Wrapping there would jump them to page 1 mid-read; clamping holds them
 * at the last real page.
 */
export function clampPage(page: number, total: number, perPage: number): number {
  return Math.min(Math.max(0, page), pageCount(total, perPage) - 1);
}

export function pageSlice<T>(items: T[], page: number, perPage: number): T[] {
  if (perPage <= 0) return items;
  const start = clampPage(page, items.length, perPage) * perPage;
  return items.slice(start, start + perPage);
}

/**
 * Whether auto-advance should run at all.
 *
 * A single page has nowhere to advance to, and design §8.6 additionally
 * disables it for a small watchlist — cycling a five-row grid against itself
 * is motion without information.
 */
export function shouldAutoPage(total: number, perPage: number): boolean {
  return pageCount(total, perPage) > 1;
}

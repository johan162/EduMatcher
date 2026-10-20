/**
 * Every URL the dashboard makes (design §12.4, D4): its own drawer routes,
 * and the cross-links into log-gui and book-gui. Their paths are kept here
 * only, so a sibling app that changes its URL scheme is one edit.
 *
 * Each id is one path segment, encoded: process keys hold `/` and `@`
 * (`pm-api-gwy/desk@host`).
 */

export type DrawerKind = "process" | "participant" | "book";

/** The drawer route for a process key, participant id or symbol. */
export function drawerPath(kind: DrawerKind, id: string): string {
  return `/${kind}/${encodeURIComponent(id)}`;
}

/** log-gui's explorer filtered to one process's records (`process` is the log client name). */
export function logGuiUrl(base: string, process: string): string {
  return `${base}/logs?${new URLSearchParams({ processes: process }).toString()}`;
}

/** book-gui's view of one book. */
export function bookGuiUrl(base: string, symbol: string): string {
  return `${base}/book/${encodeURIComponent(symbol)}`;
}

/**
 * Footer (design §9.8): upstream health, how much of each ladder is on
 * screen — a truncated ladder is never silent — the age of the last book,
 * and the keyboard hint pm-viewer puts in its subtitle.
 */

import clsx from "clsx";
import { useBookStore } from "../../store/useBookStore.js";
import { useNow } from "../../lib/hooks.js";

export function StatusStrip() {
  const upstream = useBookStore((s) => s.upstream);
  const book = useBookStore((s) => s.book);
  const capacity = useBookStore((s) => s.capacity);
  const lastBookAt = useBookStore((s) => s.lastBookAt);
  const now = useNow(1000);

  const shown = (n: number) => `${Math.min(n, capacity)}/${n}`;
  const age = lastBookAt === null ? null : Math.max(0, Math.round((now - lastBookAt) / 1000));

  return (
    <footer className="flex h-7 shrink-0 items-center gap-4 border-t border-border bg-bg-subtle px-4 text-xs text-fg-subtle">
      <span className={clsx(upstream !== "ACTIVE" && "font-semibold text-halt")}>
        upstream {upstream ?? "unknown"}
      </span>
      {book && (
        <span className="tabular" data-testid="levels-shown">
          bids {shown(book.bids.length)} · asks {shown(book.asks.length)} levels shown
        </span>
      )}
      <span className="tabular" data-testid="book-age">
        {age === null ? "no book yet" : `last book ${age}s ago`}
      </span>
      <span className="ml-auto">s / F1 change symbol</span>
    </footer>
  );
}

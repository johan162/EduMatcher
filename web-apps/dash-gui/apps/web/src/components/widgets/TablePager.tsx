/**
 * The pager of a long table, as in terminal-gui's Overview: "Page N/M",
 * previous and next, and the rows-per-page choice (`PAGE_SIZES`; 0 is all).
 * `pageCount` and `pageIndex` come from `pagination()`.
 */

import { ChevronLeft, ChevronRight } from "lucide-react";
import { PAGE_SIZES } from "../../store/usePrefsStore.js";

/** The page count for `total` rows, and `requested` held inside it: rows come and go under a viewer. */
export function pagination(total: number, pageSize: number, requested: number): { pageCount: number; pageIndex: number } {
  const pageCount = pageSize ? Math.max(1, Math.ceil(total / pageSize)) : 1;
  return { pageCount, pageIndex: Math.min(requested, pageCount - 1) };
}

export interface TablePagerProps {
  pageIndex: number;
  pageCount: number;
  pageSize: number;
  onPage: (index: number) => void;
  onPageSize: (size: number) => void;
}

export function TablePager({ pageIndex, pageCount, pageSize, onPage, onPageSize }: TablePagerProps) {
  return (
    <div className="flex items-center gap-3">
      <span className="tabular text-fg-subtle">
        Page {pageIndex + 1}/{pageCount}
      </span>
      <button
        type="button"
        disabled={pageIndex === 0}
        onClick={() => onPage(pageIndex - 1)}
        aria-label="Previous page"
        className="rounded p-1 text-fg-subtle hover:bg-bg-inset hover:text-fg disabled:opacity-40"
      >
        <ChevronLeft size={14} />
      </button>
      <button
        type="button"
        disabled={pageIndex >= pageCount - 1}
        onClick={() => onPage(pageIndex + 1)}
        aria-label="Next page"
        className="rounded p-1 text-fg-subtle hover:bg-bg-inset hover:text-fg disabled:opacity-40"
      >
        <ChevronRight size={14} />
      </button>
      <select
        value={pageSize}
        onChange={(e) => onPageSize(Number(e.target.value))}
        aria-label="Rows per page"
        className="rounded border border-border bg-bg-inset px-1 py-0.5 text-xs text-fg-subtle"
      >
        {PAGE_SIZES.map((n) => (
          <option key={n} value={n}>
            {n ? `${n} rows` : "All rows"}
          </option>
        ))}
      </select>
    </div>
  );
}

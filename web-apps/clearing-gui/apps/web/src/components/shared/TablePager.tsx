/**
 * The pager under a long table, as dash-gui's: the rows shown, "Page N/M",
 * previous and next, and the rows-per-page choice (`PAGE_SIZES`; 0 is all).
 */
import { ChevronLeft, ChevronRight } from "lucide-react";
import { PAGE_SIZES } from "@/store/usePageSizeStore";

/** The page count for `total` rows, and `requested` held inside it: rows come and go under a viewer. */
export function pagination(total: number, pageSize: number, requested: number): { pageCount: number; pageIndex: number } {
  const pageCount = pageSize ? Math.max(1, Math.ceil(total / pageSize)) : 1;
  return { pageCount, pageIndex: Math.min(requested, pageCount - 1) };
}

export interface TablePagerProps {
  /** Names the pager landmark, e.g. "Positions pages". */
  label: string;
  total: number;
  pageIndex: number;
  pageCount: number;
  pageSize: number;
  onPage: (index: number) => void;
  onPageSize: (size: number) => void;
}

export function TablePager({ label, total, pageIndex, pageCount, pageSize, onPage, onPageSize }: TablePagerProps) {
  const first = pageSize ? pageIndex * pageSize + 1 : 1;
  const last = pageSize ? Math.min(total, first + pageSize - 1) : total;
  return (
    <nav aria-label={label} className="mt-1.5 flex items-center justify-between gap-3 text-xs text-fg-dim">
      <span className="num">{`Rows ${first}–${last} of ${total}`}</span>
      <div className="flex items-center gap-3">
        <span className="num">
          Page {pageIndex + 1}/{pageCount}
        </span>
        <button
          type="button"
          disabled={pageIndex === 0}
          onClick={() => onPage(pageIndex - 1)}
          aria-label="Previous page"
          className="rounded p-1 hover:bg-raised hover:text-fg disabled:opacity-40"
        >
          <ChevronLeft size={14} aria-hidden="true" />
        </button>
        <button
          type="button"
          disabled={pageIndex >= pageCount - 1}
          onClick={() => onPage(pageIndex + 1)}
          aria-label="Next page"
          className="rounded p-1 hover:bg-raised hover:text-fg disabled:opacity-40"
        >
          <ChevronRight size={14} aria-hidden="true" />
        </button>
        <select
          value={pageSize}
          onChange={(e) => onPageSize(Number(e.target.value))}
          aria-label="Rows per page"
          className="rounded border border-line bg-raised px-1 py-0.5 text-xs"
        >
          {PAGE_SIZES.map((n) => (
            <option key={n} value={n}>
              {n ? `${n} rows` : "All rows"}
            </option>
          ))}
        </select>
      </div>
    </nav>
  );
}

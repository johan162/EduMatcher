import { useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { PAGE_SIZES, usePageSizeStore } from "@/store/usePageSizeStore";
import { pagination, TablePager } from "./TablePager";

/** Up to this many rows a table fits every page size, so it gets no pager. */
const SMALLEST_PAGE = Math.min(...PAGE_SIZES.filter((n) => n > 0));

export interface Column<R> {
  id: string;
  header: string;
  /** Longer explanation, shown as the header's tooltip. */
  title?: string;
  cell: (row: R) => ReactNode;
  /** The value sorting compares; a column without one is not sortable. */
  sortValue?: (row: R) => number | string | null;
  align?: "left" | "right";
}

export interface SortState {
  id: string;
  dir: "asc" | "desc";
}

interface DataTableProps<R> {
  /** Names the table for screen readers (rendered as its caption). */
  caption: string;
  columns: Column<R>[];
  rows: R[];
  rowKey: (row: R) => string;
  initialSort?: SortState;
  /** False keeps the rows in the API's order: no header sorts. */
  sortable?: boolean;
}

/**
 * A plain, accessible data table with client-side sorting and paging.
 *
 * Sortable headers are buttons with a sort icon, and the active one carries
 * `aria-sort`, so the order is announced, not only drawn. Sorting is stable
 * and puts missing (`null`) values last in either direction. Rows are sorted
 * here only: the API's own order (e.g. newest first) is the starting point.
 *
 * Paging uses the one remembered rows-per-page choice. The requested page is
 * kept while polled rows come and go (shown clamped to the last page), and
 * goes back to the first on a new sort or page size. A new filter is a new
 * query, which `QueryState` shows as a skeleton first, so the table remounts
 * on page 1. A table that fits the smallest page has no pager.
 */
export function DataTable<R>({ caption, columns, rows, rowKey, initialSort, sortable = true }: DataTableProps<R>) {
  const [sort, setSort] = useState<SortState | null>(sortable ? (initialSort ?? null) : null);
  const [requestedPage, setRequestedPage] = useState(0);
  const pageSize = usePageSizeStore((s) => s.pageSize);
  const setPageSize = usePageSizeStore((s) => s.setPageSize);

  const sorted = useMemo(() => {
    const column = sort ? columns.find((c) => c.id === sort.id) : undefined;
    if (!sort || !column?.sortValue) return rows;
    const value = column.sortValue;
    const factor = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const x = value(a);
      const y = value(b);
      if (x === y) return 0;
      if (x === null) return 1;
      if (y === null) return -1;
      return (x < y ? -1 : 1) * factor;
    });
  }, [rows, columns, sort]);

  const paged = sorted.length > SMALLEST_PAGE;
  const { pageCount, pageIndex } = pagination(sorted.length, paged ? pageSize : 0, requestedPage);
  const shown = paged && pageSize ? sorted.slice(pageIndex * pageSize, (pageIndex + 1) * pageSize) : sorted;

  function toggle(id: string) {
    setSort((prev) =>
      prev?.id === id ? { id, dir: prev.dir === "asc" ? "desc" : "asc" } : { id, dir: "desc" },
    );
    setRequestedPage(0);
  }

  function changePageSize(size: number) {
    setPageSize(size);
    setRequestedPage(0);
  }

  return (
    <div>
      <div className="overflow-x-auto rounded border border-line">
        <table className="w-full border-collapse text-xs">
          <caption className="sr-only">{caption}</caption>
          <thead className="bg-panel text-fg-dim">
            <tr>
              {columns.map((c) => {
                const active = sort?.id === c.id;
                const ariaSort = active ? (sort.dir === "asc" ? "ascending" : "descending") : undefined;
                const align = c.align === "right" ? "text-right" : "text-left";
                const label = c.title ? (
                  <span data-has-tooltip className="cursor-help underline decoration-dotted underline-offset-2">
                    {c.header}
                  </span>
                ) : (
                  c.header
                );
                return (
                  <th key={c.id} scope="col" aria-sort={ariaSort} title={c.title} className={`px-2 py-1.5 font-medium ${align}`}>
                    {sortable && c.sortValue ? (
                      <button
                        type="button"
                        onClick={() => toggle(c.id)}
                        className="group inline-flex items-center gap-1 hover:text-fg"
                      >
                        {label}
                        <SortIcon dir={active ? sort.dir : null} />
                      </button>
                    ) : (
                      label
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => (
              <tr key={rowKey(row)} className="border-t border-line hover:bg-raised">
                {columns.map((c) => (
                  <td key={c.id} className={`px-2 py-1 ${c.align === "right" ? "num text-right" : ""}`}>
                    {c.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {paged && (
        <TablePager
          label={`${caption} pages`}
          total={sorted.length}
          pageIndex={pageIndex}
          pageCount={pageCount}
          pageSize={pageSize}
          onPage={setRequestedPage}
          onPageSize={changePageSize}
        />
      )}
    </div>
  );
}

/** ↑/↓ on the sorted column; a faint ↕ on the others, so sortable headers read as such. */
function SortIcon({ dir }: { dir: "asc" | "desc" | null }) {
  if (dir === "asc") return <ArrowUp data-sort-icon size={10} aria-hidden="true" />;
  if (dir === "desc") return <ArrowDown data-sort-icon size={10} aria-hidden="true" />;
  return <ArrowUpDown data-sort-icon size={10} aria-hidden="true" className="opacity-40 group-hover:opacity-80" />;
}

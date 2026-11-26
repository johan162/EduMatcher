import { Fragment, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronDown, ChevronRight } from "lucide-react";
import { PAGE_SIZES, usePageSizeStore } from "@/store/usePageSizeStore";
import { pagination, TablePager } from "./TablePager";

/** Up to this many rows a table fits every page size, so it gets no pager. */
const SMALLEST_PAGE = Math.min(...PAGE_SIZES.filter((n) => n > 0));

export interface Column<R> {
  id: string;
  header: string;
  /** What the column shows and where it comes from: the header's tooltip. */
  title: string;
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
  /** The server holds rows beyond `rows` (a cursor-paged list, e.g. Trades). */
  more?: MoreRowsSource;
  /** Makes each row open something: clickable, and Enter/Space when focused. */
  onRowClick?: (row: R) => void;
  /** The `rowKey` of the row whose item is open (marked `aria-selected`). */
  selectedKey?: string;
  /** A disclosure button per row that opens `render(row)` under it (CG25). */
  detail?: RowDetail<R>;
}

/** What a row's disclosure button is called and what it opens. */
export interface RowDetail<R> {
  /** The button's accessible name, e.g. "Explain AAPL". */
  name: (row: R) => string;
  render: (row: R) => ReactNode;
}

/** The next server page of a cursor-paged list, fetched when paging needs it. */
export interface MoreRowsSource {
  available: boolean;
  loading: boolean;
  load: () => void;
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
 *
 * With `more`, the rows are the loaded part of a server-paged list: Next past
 * the loaded rows asks for the next server page, and the page shows once it
 * has arrived. "All" means all loaded rows.
 *
 * With `detail`, each row has a disclosure button at the start of its first
 * cell that opens a full-width row under it; open rows are remembered by `rowKey`, so
 * a poll or a page change does not close them.
 */
export function DataTable<R>({
  caption,
  columns,
  rows,
  rowKey,
  initialSort,
  sortable = true,
  more,
  onRowClick,
  selectedKey,
  detail,
}: DataTableProps<R>) {
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());
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

  const moreAvailable = more?.available ?? false;
  const paged = sorted.length > SMALLEST_PAGE || moreAvailable;
  const { pageCount, pageIndex } = pagination(sorted.length, paged ? pageSize : 0, requestedPage);
  const shown = paged && pageSize ? sorted.slice(pageIndex * pageSize, (pageIndex + 1) * pageSize) : sorted;

  // A requested page beyond the loaded rows: fetch the next server page.
  // Keyed on the flag alone: one request each time it turns true, whatever
  // object the caller passes on each render.
  const needMore = moreAvailable && !more!.loading && pageSize > 0 && requestedPage * pageSize >= rows.length;
  const load = useRef(more?.load);
  load.current = more?.load;
  useEffect(() => {
    if (needMore) load.current?.();
  }, [needMore]);

  function toggle(id: string) {
    setSort((prev) =>
      prev?.id === id ? { id, dir: prev.dir === "asc" ? "desc" : "asc" } : { id, dir: "desc" },
    );
    setRequestedPage(0);
  }

  // With "All" there is one page of everything loaded, so Next past it is a
  // request for the next server page rather than a page number.
  function changePage(index: number) {
    if (pageSize === 0 && moreAvailable && index > pageIndex) load.current?.();
    else setRequestedPage(index);
  }

  function toggleDetail(key: string) {
    setOpened((prev) => {
      const next = new Set(prev);
      if (!next.delete(key)) next.add(key);
      return next;
    });
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
            {shown.map((row) => {
              const key = rowKey(row);
              const open = detail !== undefined && opened.has(key);
              const detailId = `detail-${caption}-${key}`.replace(/[^\w-]/g, "_");
              return (
                <Fragment key={key}>
                  <tr
                    className={`border-t border-line hover:bg-raised ${onRowClick ? "cursor-pointer" : ""} ${
                      onRowClick && key === selectedKey ? "bg-accent/15" : ""
                    }`}
                    {...(onRowClick && {
                      "data-row-key": key,
                      tabIndex: 0,
                      "aria-selected": key === selectedKey,
                      onClick: () => onRowClick(row),
                      onKeyDown: (e: KeyboardEvent<HTMLTableRowElement>) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onRowClick(row);
                        }
                      },
                    })}
                  >
                    {columns.map((c, i) => (
                      <td key={c.id} className={`px-2 py-1 ${c.align === "right" ? "num text-right" : ""}`}>
                        {detail && i === 0 && (
                          <button
                            type="button"
                            aria-expanded={open}
                            aria-controls={open ? detailId : undefined}
                            aria-label={detail.name(row)}
                            onClick={(e) => {
                              e.stopPropagation();
                              toggleDetail(key);
                            }}
                            className="mr-1 align-middle text-fg-dim hover:text-fg"
                          >
                            {open ? <ChevronDown size={12} aria-hidden="true" /> : <ChevronRight size={12} aria-hidden="true" />}
                          </button>
                        )}
                        {c.cell(row)}
                      </td>
                    ))}
                  </tr>
                  {open && (
                    <tr id={detailId}>
                      <td colSpan={columns.length} className="border-t border-line bg-raised/40 px-3 py-2">
                        {detail.render(row)}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
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
          more={moreAvailable}
          loading={more?.loading ?? false}
          onPage={changePage}
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

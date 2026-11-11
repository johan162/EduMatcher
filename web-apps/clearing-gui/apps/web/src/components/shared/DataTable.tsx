import { useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";

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
}

/**
 * A plain, accessible data table with client-side sorting.
 *
 * Sortable headers are buttons and the active one carries `aria-sort`, so the
 * order is announced, not only drawn. Sorting is stable and puts missing
 * (`null`) values last in either direction. Rows are sorted here only: the
 * API's own order (e.g. newest first) is the starting point.
 */
export function DataTable<R>({ caption, columns, rows, rowKey, initialSort }: DataTableProps<R>) {
  const [sort, setSort] = useState<SortState | null>(initialSort ?? null);

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

  function toggle(id: string) {
    setSort((prev) =>
      prev?.id === id ? { id, dir: prev.dir === "asc" ? "desc" : "asc" } : { id, dir: "desc" },
    );
  }

  return (
    <div className="overflow-x-auto rounded border border-line">
      <table className="w-full border-collapse text-xs">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-panel text-fg-dim">
          <tr>
            {columns.map((c) => {
              const active = sort?.id === c.id;
              const ariaSort = active ? (sort.dir === "asc" ? "ascending" : "descending") : undefined;
              const align = c.align === "right" ? "text-right" : "text-left";
              return (
                <th key={c.id} scope="col" aria-sort={ariaSort} title={c.title} className={`px-2 py-1.5 font-medium ${align}`}>
                  {c.sortValue ? (
                    <button
                      type="button"
                      onClick={() => toggle(c.id)}
                      className="inline-flex items-center gap-1 hover:text-fg"
                    >
                      {c.header}
                      {active && (sort.dir === "asc" ? <ArrowUp size={10} aria-hidden="true" /> : <ArrowDown size={10} aria-hidden="true" />)}
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
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
  );
}

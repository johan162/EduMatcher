/**
 * The process and participant tables (design §13, rows 2 and 4): plain
 * rows with state glyphs and inline sparklines, sortable by any column with
 * a sort key, optionally in groups (the processes' "Participant bots" come
 * after the exchange's own), each group sorted on its own.
 *
 * A row without a sort value (null, or not a finite number) sorts last in
 * either direction. The table scrolls sideways inside its panel rather than
 * spilling out of it. Clickable rows are reachable and work by keyboard.
 */

import clsx from "clsx";
import { memo, useState, type ReactNode } from "react";
import { PROCESS_STATE, type StatusLook } from "../../lib/status.js";
import type { ProcessState } from "@edumatcher/dash-types";

export interface Column<T> {
  id: string;
  header: string;
  render: (row: T) => ReactNode;
  /** Present: the column sorts by it; null (or NaN) for "no value". */
  sortKey?: (row: T) => number | string | null;
  align?: "left" | "right";
}

export type SortDir = "asc" | "desc";

export interface HealthTableProps<T> {
  label: string;
  columns: readonly Column<T>[];
  rows: readonly T[];
  rowKey: (row: T) => string;
  initialSort?: { id: string; dir: SortDir };
  /** Rows are shown in these groups, in the order they first appear. */
  group?: (row: T) => string;
  onRowClick?: (row: T) => void;
}

/** No sort value: sorted last whatever the direction. */
function missing(k: number | string | null): boolean {
  return k === null || (typeof k === "number" && !Number.isFinite(k));
}

/** Rows by `key`, stably; rows without a value last in either direction. */
export function sortRows<T>(rows: readonly T[], key: (row: T) => number | string | null, dir: SortDir): T[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const ka = key(a);
    const kb = key(b);
    if (missing(ka) || missing(kb)) return Number(missing(ka)) - Number(missing(kb));
    return sign * (typeof ka === "number" && typeof kb === "number" ? ka - kb : String(ka).localeCompare(String(kb)));
  });
}

export function HealthTable<T>({ label, columns, rows, rowKey, initialSort, group, onRowClick }: HealthTableProps<T>) {
  const [sort, setSort] = useState(initialSort);
  const column = columns.find((c) => c.id === sort?.id);
  const sorted = column?.sortKey && sort ? (r: readonly T[]) => sortRows(r, column.sortKey!, sort.dir) : (r: readonly T[]) => [...r];

  const groups = new Map<string, T[]>();
  for (const row of rows) {
    const g = group ? group(row) : "";
    groups.set(g, [...(groups.get(g) ?? []), row]);
  }

  const toggle = (id: string) =>
    setSort((s) => (s?.id === id ? { id, dir: s.dir === "asc" ? "desc" : "asc" } : { id, dir: "asc" }));

  return (
    <div data-widget="health-table" className="min-w-0 overflow-x-auto">
    <table aria-label={label} className="w-full border-collapse text-xs">
      <thead>
        <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-fg-faint">
          {columns.map((c) => (
            <th
              key={c.id}
              scope="col"
              aria-sort={sort?.id === c.id ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}
              className={clsx("px-2 py-1 font-semibold", c.align === "right" && "text-right")}
            >
              {c.sortKey ? (
                <button type="button" onClick={() => toggle(c.id)} className="uppercase hover:text-fg">
                  {c.header}
                  {sort?.id === c.id && (sort.dir === "asc" ? " ▲" : " ▼")}
                </button>
              ) : (
                c.header
              )}
            </th>
          ))}
        </tr>
      </thead>
      {[...groups.entries()].map(([name, groupRows], gi) => (
        <tbody key={name || gi}>
          {name && gi > 0 && (
            <tr>
              <th colSpan={columns.length} scope="rowgroup" className="px-2 pb-1 pt-3 text-left text-[11px] font-semibold uppercase tracking-wide text-fg-faint">
                {name}
              </th>
            </tr>
          )}
          {sorted(groupRows).map((row) => (
            <TableRow key={rowKey(row)} id={rowKey(row)} row={row} signature={JSON.stringify(row)} columns={columns} onRowClick={onRowClick} />
          ))}
        </tbody>
      ))}
    </table>
    </div>
  );
}

interface TableRowProps<T> {
  id: string;
  row: T;
  /** The row's data as text: the row is drawn again only when it changes. */
  signature: string;
  columns: readonly Column<T>[];
  onRowClick?: (row: T) => void;
}

function TableRowImpl<T>({ id, row, columns, onRowClick }: TableRowProps<T>) {
  return (
    <tr
      data-row={id}
      onClick={onRowClick ? () => onRowClick(row) : undefined}
      onKeyDown={
        onRowClick
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onRowClick(row);
              }
            }
          : undefined
      }
      tabIndex={onRowClick ? 0 : undefined}
      className={clsx("border-b border-border-subtle", onRowClick && "cursor-pointer hover:bg-bg-inset focus:bg-bg-inset focus:outline-none")}
    >
      {columns.map((c) => (
        <td key={c.id} className={clsx("whitespace-nowrap px-2 py-1 tabular", c.align === "right" && "text-right")}>
          {c.render(row)}
        </td>
      ))}
    </tr>
  );
}

/**
 * A row redrawn only when its data, its columns or its click handler
 * change: the snapshot is new every second, but at 300 books most rows are
 * not (I123). Callers pass stable ``columns`` and ``onRowClick``.
 */
const TableRow = memo(
  TableRowImpl,
  (a, b) => a.signature === b.signature && a.columns === b.columns && a.onRowClick === b.onRowClick && a.id === b.id,
) as typeof TableRowImpl;

/** A state as glyph and word in its colour. */
export function StateBadge({ look }: { look: StatusLook }) {
  return (
    <span className={clsx("whitespace-nowrap font-semibold", look.text)}>
      <span aria-hidden="true">{look.glyph}</span> {look.label}
    </span>
  );
}

export function ProcessStateBadge({ state }: { state: ProcessState }) {
  return <StateBadge look={PROCESS_STATE[state]} />;
}

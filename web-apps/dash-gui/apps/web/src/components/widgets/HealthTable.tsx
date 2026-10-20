/**
 * The process and participant tables (design §13, rows 2 and 4): plain
 * rows with state glyphs and inline sparklines, sortable by any column with
 * a sort key, optionally in groups (the processes' "Participant bots" come
 * after the exchange's own), each group sorted on its own.
 */

import clsx from "clsx";
import { useState, type ReactNode } from "react";
import { PROCESS_STATE, type StatusLook } from "../../lib/status.js";
import type { ProcessState } from "@edumatcher/dash-types";

export interface Column<T> {
  id: string;
  header: string;
  render: (row: T) => ReactNode;
  /** Present: the column sorts by it. */
  sortKey?: (row: T) => number | string;
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

export function sortRows<T>(rows: readonly T[], key: (row: T) => number | string, dir: SortDir): T[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const ka = key(a);
    const kb = key(b);
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
            <tr
              key={rowKey(row)}
              data-row={rowKey(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={clsx("border-b border-border-subtle", onRowClick && "cursor-pointer hover:bg-bg-inset")}
            >
              {columns.map((c) => (
                <td key={c.id} className={clsx("px-2 py-1 tabular", c.align === "right" && "text-right")}>
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      ))}
    </table>
  );
}

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

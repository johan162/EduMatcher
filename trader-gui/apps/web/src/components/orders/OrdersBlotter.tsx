import { useMemo, useState } from "react";
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type RowSelectionState,
  type SortingState,
} from "@tanstack/react-table";
import { ChevronDown, ChevronUp, Pencil, Repeat, X } from "lucide-react";
import { FlashCell } from "@/components/shared/FlashCell.js";
import { StatusPill } from "./StatusPill.js";
import { isTerminal } from "@/store/useOrderStore.js";
import { formatPrice, formatQty } from "@/lib/formatters.js";
import type { Order } from "@/types/index.js";

/** HH:MM:SS.mmm from an ISO timestamp (§13.1.1 Updated column). */
function formatTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
}

export interface OrdersBlotterProps {
  orders: Order[];
  tickDecimalsFor: (symbol: string) => number;
  onOpenDetail: (orderId: string) => void;
  onAmend: (order: Order) => void;
  onReplace: (order: Order) => void;
  onCancel: (order: Order) => void;
  onBulkCancel: (orderIds: string[]) => void;
}

/**
 * Active Orders Blotter (§13.1) — a live table of this gateway's orders driven
 * by {@link useOrderStore} (seeded from `orders.snapshot`, kept current by
 * `order.*`). Sortable columns, per-row Amend/Replace/Cancel, row-click opens
 * the Order Detail drawer, and multi-select drives a bulk cancel.
 */
export function OrdersBlotter({
  orders,
  tickDecimalsFor,
  onOpenDetail,
  onAmend,
  onReplace,
  onCancel,
  onBulkCancel,
}: OrdersBlotterProps) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});

  const columns = useMemo<ColumnDef<Order>[]>(() => {
    const stop = (e: React.MouseEvent) => e.stopPropagation();
    return [
      {
        id: "select",
        enableSorting: false,
        size: 28,
        header: ({ table }) => (
          <input
            type="checkbox"
            aria-label="Select all orders"
            checked={table.getIsAllRowsSelected()}
            onChange={table.getToggleAllRowsSelectedHandler()}
            onClick={stop}
          />
        ),
        cell: ({ row }) => (
          <input
            type="checkbox"
            aria-label={`Select order ${row.original.order_id}`}
            checked={row.getIsSelected()}
            disabled={!row.getCanSelect()}
            onChange={row.getToggleSelectedHandler()}
            onClick={stop}
          />
        ),
      },
      { accessorKey: "symbol", header: "Symbol", cell: (c) => <span className="font-mono font-medium">{c.row.original.symbol}</span> },
      {
        accessorKey: "side",
        header: "Side",
        cell: (c) => (
          <span className={c.row.original.side === "BUY" ? "text-bid" : "text-ask"}>
            {c.row.original.side}
          </span>
        ),
      },
      { accessorKey: "order_type", header: "Type", cell: (c) => <span className="text-[#9090b0]">{c.row.original.order_type}</span> },
      { accessorKey: "tif", header: "TIF", cell: (c) => <span className="text-[#9090b0]">{c.row.original.tif}</span> },
      { accessorKey: "quantity", header: "Qty", cell: (c) => <span className="price-cell">{formatQty(c.row.original.quantity)}</span> },
      {
        accessorKey: "remaining_qty",
        header: "Remaining",
        cell: (c) => (
          <FlashCell value={c.row.original.remaining_qty} formatter={(v) => formatQty(v)} />
        ),
      },
      {
        accessorKey: "price",
        header: "Price",
        cell: (c) => (
          <span className="price-cell">
            {c.row.original.price === null
              ? "—"
              : formatPrice(c.row.original.price, tickDecimalsFor(c.row.original.symbol))}
          </span>
        ),
      },
      {
        id: "group",
        header: "Group",
        enableSorting: false,
        cell: (c) => {
          const g = c.row.original.oco_group_id ?? c.row.original.combo_parent_id;
          return g ? (
            <span className="rounded bg-[#20203a] px-1 text-[10px] text-[#9090b0]">{g}</span>
          ) : (
            <span className="text-[#505070]">—</span>
          );
        },
      },
      { id: "status", accessorKey: "status", header: "Status", cell: (c) => <StatusPill status={c.row.original.status} /> },
      { id: "updated", accessorKey: "updated_at", header: "Updated", cell: (c) => <span className="text-[#9090b0] text-[10px]">{formatTime(c.row.original.updated_at)}</span> },
      {
        id: "actions",
        header: "",
        enableSorting: false,
        cell: (c) => {
          const o = c.row.original;
          const done = isTerminal(o.status);
          return (
            <div className="flex items-center justify-end gap-1.5" onClick={stop}>
              <button
                type="button"
                onClick={() => onAmend(o)}
                disabled={done}
                aria-label={`Amend order ${o.order_id}`}
                title="Amend (same-price size reduction keeps priority)"
                className="text-[#9090b0] hover:text-[#e8e8f0] disabled:opacity-30"
              >
                <Pencil size={12} />
              </button>
              <button
                type="button"
                onClick={() => onReplace(o)}
                disabled={done}
                aria-label={`Replace order ${o.order_id}`}
                title="Cancel-replace"
                className="text-[#9090b0] hover:text-[#e8e8f0] disabled:opacity-30"
              >
                <Repeat size={12} />
              </button>
              <button
                type="button"
                onClick={() => onCancel(o)}
                disabled={done}
                aria-label={`Cancel order ${o.order_id}`}
                title="Cancel"
                className="text-[#9090b0] hover:text-ask disabled:opacity-30"
              >
                <X size={13} />
              </button>
            </div>
          );
        },
      },
    ];
  }, [tickDecimalsFor, onAmend, onReplace, onCancel]);

  const table = useReactTable({
    data: orders,
    columns,
    state: { sorting, rowSelection },
    onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection,
    enableRowSelection: (row) => !isTerminal(row.original.status),
    getRowId: (row) => row.order_id,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const selectedIds = table.getSelectedRowModel().rows.map((r) => r.original.order_id);

  if (orders.length === 0) {
    return (
      <div className="border border-[#2a2a45] rounded p-8 text-center text-sm text-[#9090b0]">
        No active orders — press <kbd className="rounded bg-[#1a1a28] px-1">F1</kbd> to enter an order
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="overflow-auto border border-[#2a2a45] rounded">
        <table className="w-full text-xs border-collapse">
          <thead className="sticky top-0 z-10 bg-[#12121a]">
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => {
                  const sortable = header.column.getCanSort();
                  const dir = header.column.getIsSorted();
                  return (
                    <th
                      key={header.id}
                      scope="col"
                      aria-sort={
                        dir === "asc"
                          ? "ascending"
                          : dir === "desc"
                            ? "descending"
                            : sortable
                              ? "none"
                              : undefined
                      }
                      className="text-left font-medium text-[#9090b0] px-2 py-1.5 border-b border-[#2a2a45] whitespace-nowrap"
                    >
                      {header.isPlaceholder ? null : sortable ? (
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          className="flex items-center gap-1 hover:text-[#e8e8f0]"
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {dir === "asc" && <ChevronUp size={11} />}
                          {dir === "desc" && <ChevronDown size={11} />}
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                onClick={() => onOpenDetail(row.original.order_id)}
                className={`cursor-pointer border-b border-[#1a1a28] hover:bg-[#1a1a28] ${
                  row.getIsSelected() ? "bg-[#20203a]" : ""
                }`}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-2 py-1 whitespace-nowrap">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selectedIds.length > 0 && (
        <div className="flex items-center gap-3 rounded border border-[#2a2a45] bg-[#12121a] px-3 py-2 text-xs">
          <span className="text-[#e8e8f0]">
            {selectedIds.length} {selectedIds.length === 1 ? "order" : "orders"} selected
          </span>
          <button
            type="button"
            onClick={() => {
              onBulkCancel(selectedIds);
              setRowSelection({});
            }}
            className="ml-auto rounded bg-ask px-3 py-1 font-semibold text-white hover:brightness-110"
          >
            Cancel all selected
          </button>
        </div>
      )}
    </div>
  );
}

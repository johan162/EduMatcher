import { useMemo, useRef } from "react";
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronDown, ChevronUp } from "lucide-react";
import { FlashCell } from "@/components/shared/FlashCell.js";
import { AuctionBadge, ChangeCell, HaltBadge, WatchStar } from "./Badges.js";
import { formatPrice, formatQty } from "@/lib/formatters.js";
import type { MarketRow } from "@/lib/marketRows.js";

/** Estimated row height in px; the virtualizer measures the real ones. */
const ROW_HEIGHT = 28;

export interface MarketTableProps {
  rows: MarketRow[];
  sorting: SortingState;
  onSortingChange: (updater: SortingState | ((old: SortingState) => SortingState)) => void;
  activeSymbol: string | null;
  showAuction: boolean;
  onSelect: (symbol: string) => void;
  onToggleWatch: (symbol: string) => void;
}

export function MarketTable({
  rows,
  sorting,
  onSortingChange,
  activeSymbol,
  showAuction,
  onSelect,
  onToggleWatch,
}: MarketTableProps) {
  const columns = useMemo<ColumnDef<MarketRow>[]>(
    () => [
      {
        id: "watch",
        header: "",
        enableSorting: false,
        size: 28,
        cell: ({ row }) => (
          <WatchStar
            symbol={row.original.symbol}
            watched={row.original.watched}
            onToggle={onToggleWatch}
          />
        ),
      },
      {
        accessorKey: "symbol",
        header: "Symbol",
        cell: ({ row }) => <span className="font-mono font-medium">{row.original.symbol}</span>,
      },
      {
        accessorKey: "bid",
        header: "Bid",
        cell: ({ row }) => (
          <FlashCell
            value={row.original.bid}
            formatter={(v) => formatPrice(v, row.original.tickDecimals)}
            className="text-bid"
          />
        ),
      },
      {
        accessorKey: "ask",
        header: "Ask",
        cell: ({ row }) => (
          <FlashCell
            value={row.original.ask}
            formatter={(v) => formatPrice(v, row.original.tickDecimals)}
            className="text-ask"
          />
        ),
      },
      {
        accessorKey: "last",
        header: "Last",
        cell: ({ row }) => (
          <FlashCell
            value={row.original.last}
            formatter={(v) => formatPrice(v, row.original.tickDecimals)}
          />
        ),
      },
      {
        accessorKey: "changePct",
        header: "Chg %",
        // Nulls sort last in both directions: a symbol with no open price is
        // "unknown", not "worst", and should not head the ascending sort.
        sortUndefined: "last",
        cell: ({ row }) => <ChangeCell pct={row.original.changePct} />,
      },
      {
        accessorKey: "volume",
        header: "Volume",
        sortUndefined: "last",
        cell: ({ row }) => (
          <span className="price-cell text-[#9090b0]">
            {row.original.volume === null ? "—" : formatQty(row.original.volume)}
          </span>
        ),
      },
      {
        id: "status",
        header: "Status",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="flex items-center gap-1">
            {row.original.halted && <HaltBadge level={row.original.haltLevel} />}
            {showAuction && !row.original.halted && (
              <AuctionBadge
                eqPrice={row.original.auctionPrice}
                indicative={row.original.auctionIndicative}
                tickDecimals={row.original.tickDecimals}
              />
            )}
          </span>
        ),
      },
    ],
    [onToggleWatch, showAuction],
  );

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: (row) => row.symbol,
  });

  const scrollRef = useRef<HTMLDivElement>(null);
  const tableRows = table.getRowModel().rows;
  const virtualizer = useVirtualizer({
    count: tableRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  });

  const virtualRows = virtualizer.getVirtualItems();
  // Spacer rows rather than absolute positioning, so the <table> keeps its
  // native column sizing and the sticky header stays aligned with the body.
  const paddingTop = virtualRows.length > 0 ? (virtualRows[0]?.start ?? 0) : 0;
  const paddingBottom =
    virtualRows.length > 0
      ? virtualizer.getTotalSize() - (virtualRows[virtualRows.length - 1]?.end ?? 0)
      : 0;

  return (
    <div ref={scrollRef} className="flex-1 overflow-auto border border-[#2a2a45] rounded">
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
                    {sortable ? (
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
          {paddingTop > 0 && (
            <tr aria-hidden="true">
              <td colSpan={columns.length} style={{ height: paddingTop }} />
            </tr>
          )}
          {virtualRows.map((virtualRow) => {
            const row = tableRows[virtualRow.index];
            if (!row) return null;
            const isActive = row.original.symbol === activeSymbol;
            return (
              <tr
                key={row.id}
                data-index={virtualRow.index}
                ref={virtualizer.measureElement}
                onClick={() => onSelect(row.original.symbol)}
                aria-selected={isActive}
                className={`cursor-pointer border-b border-[#1a1a28] ${
                  isActive ? "bg-[#20203a]" : "hover:bg-[#1a1a28]"
                }`}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-2 py-1 whitespace-nowrap">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            );
          })}
          {paddingBottom > 0 && (
            <tr aria-hidden="true">
              <td colSpan={columns.length} style={{ height: paddingBottom }} />
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

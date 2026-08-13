import { useMemo } from "react";
import { X } from "lucide-react";
import { useOrdersQuery, useCancelOrderMutation } from "@/queries/index.js";
import { formatPrice, formatQty } from "@/lib/formatters.js";
import type { Order } from "@/types/index.js";

/** Orders that are still working and can be cancelled. */
const RESTING = new Set(["NEW", "PARTIAL", "PENDING"]);

interface CompactBlotterProps {
  symbol: string;
  tickDecimals: number;
}

/**
 * Compact blotter for the Workspace bottom strip (§11.2): the active symbol's
 * resting orders with an inline cancel. A filtered slice of the full Active
 * Orders Blotter (phase 7); it reads `GET /orders` and reflects cancels
 * optimistically via query invalidation. Live `/events` wiring lands in
 * phase 6/7.
 */
export function CompactBlotter({ symbol, tickDecimals }: CompactBlotterProps) {
  const ordersQuery = useOrdersQuery();
  const cancel = useCancelOrderMutation();

  const rows = useMemo<Order[]>(
    () =>
      (ordersQuery.data ?? []).filter(
        (o) => o.symbol === symbol && RESTING.has(o.status),
      ),
    [ordersQuery.data, symbol],
  );

  return (
    <div className="flex flex-col gap-1 h-full">
      <div className="flex items-center gap-2">
        <span className="text-xs text-[#9090b0]">Working orders</span>
        <span className="text-[10px] text-[#505070]">{symbol}</span>
        <span className="ml-auto text-[10px] text-[#505070]">
          {rows.length} {rows.length === 1 ? "order" : "orders"}
        </span>
      </div>

      {rows.length === 0 ? (
        <p className="text-[11px] text-[#505070] py-2">
          {ordersQuery.isLoading ? "Loading orders…" : `No working orders for ${symbol}.`}
        </p>
      ) : (
        <div className="overflow-auto">
          <table className="w-full text-xs font-mono border-collapse">
            <thead className="text-[10px] text-[#505070]">
              <tr>
                <th scope="col" className="text-left font-medium px-2 py-1">Side</th>
                <th scope="col" className="text-left font-medium px-2 py-1">Type</th>
                <th scope="col" className="text-right font-medium px-2 py-1">Qty</th>
                <th scope="col" className="text-right font-medium px-2 py-1">Rem</th>
                <th scope="col" className="text-right font-medium px-2 py-1">Price</th>
                <th scope="col" className="text-left font-medium px-2 py-1">Status</th>
                <th scope="col" className="px-2 py-1" />
              </tr>
            </thead>
            <tbody>
              {rows.map((o) => (
                <tr key={o.order_id} className="border-b border-[#1a1a28]">
                  <td className={`px-2 py-0.5 ${o.side === "BUY" ? "text-bid" : "text-ask"}`}>
                    {o.side}
                  </td>
                  <td className="px-2 py-0.5 text-[#9090b0]">{o.order_type}</td>
                  <td className="px-2 py-0.5 text-right text-[#9090b0]">{formatQty(o.quantity)}</td>
                  <td className="px-2 py-0.5 text-right text-[#9090b0]">
                    {formatQty(o.remaining_qty)}
                  </td>
                  <td className="px-2 py-0.5 text-right text-[#e8e8f0]">
                    {o.price === null ? "MKT" : formatPrice(o.price, tickDecimals)}
                  </td>
                  <td className="px-2 py-0.5 text-[#9090b0]">{o.status}</td>
                  <td className="px-2 py-0.5 text-right">
                    <button
                      type="button"
                      onClick={() => cancel.mutate(o.order_id)}
                      disabled={cancel.isPending}
                      aria-label={`Cancel order ${o.order_id}`}
                      className="text-[#9090b0] hover:text-ask disabled:opacity-50"
                    >
                      <X size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

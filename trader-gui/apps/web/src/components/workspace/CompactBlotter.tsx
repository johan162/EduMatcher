import { useMemo } from "react";
import { X } from "lucide-react";
import { useOrderStore, isTerminal } from "@/store/useOrderStore.js";
import { useOrderCancel } from "@/hooks/useOrderCancel.js";
import { CancelConfirm } from "@/components/orders/CancelConfirm.js";
import { formatPrice, formatQty } from "@/lib/formatters.js";
import type { Order } from "@/types/index.js";

interface CompactBlotterProps {
  symbol: string;
  tickDecimals: number;
}

/**
 * Compact blotter for the Workspace bottom strip (§11.2): the active symbol's
 * working orders with an inline cancel. A filtered slice of the full Active
 * Orders Blotter, reading the same live {@link useOrderStore} (seeded from
 * `orders.snapshot`, kept current by `order.*`) so it needs no polling.
 */
export function CompactBlotter({ symbol, tickDecimals }: CompactBlotterProps) {
  const ordersMap = useOrderStore((s) => s.orders);
  // Same cancel behaviour as the full blotter: confirm by default, undo-toast
  // in power-user mode (§20.3).
  const { requestCancel, confirmTarget, setConfirmTarget, confirmCancel, busy } = useOrderCancel();

  const rows = useMemo<Order[]>(
    () =>
      Object.values(ordersMap).filter((o) => o.symbol === symbol && !isTerminal(o.status)),
    [ordersMap, symbol],
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
        <p className="text-[11px] text-[#505070] py-2">No working orders for {symbol}.</p>
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
                      onClick={() => requestCancel(o)}
                      disabled={busy}
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

      {confirmTarget && (
        <CancelConfirm
          title="Cancel order?"
          message={`Cancel ${confirmTarget.side} ${confirmTarget.quantity} ${confirmTarget.symbol} (${confirmTarget.order_id.slice(0, 8)})?`}
          confirmLabel="Cancel order"
          busy={busy}
          onConfirm={confirmCancel}
          onClose={() => setConfirmTarget(null)}
        />
      )}
    </div>
  );
}

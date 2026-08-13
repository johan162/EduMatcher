import { useEffect } from "react";
import { OrderTicket } from "@/components/orders/OrderTicket.js";
import { useActiveSymbolStore } from "@/store/useActiveSymbolStore.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";

/**
 * Standalone Order Entry screen (§12) — the full single-leg ticket with the
 * symbol picker unlocked, so choosing a symbol here also sets the active symbol
 * for the rest of the app. The Workspace embeds the same ticket in compact mode
 * with its symbol locked.
 */
export function OrderEntryPage() {
  const activeSymbol = useActiveSymbolStore((s) => s.activeSymbol);
  const setActiveSymbol = useActiveSymbolStore((s) => s.setActiveSymbol);
  const symbols = useSymbolStore((s) => s.symbols);
  const meta = useSymbolStore((s) => s.symbols.find((m) => m.symbol === activeSymbol));

  // Land on a usable symbol so the ref-price hint has something to show.
  useEffect(() => {
    if (!activeSymbol && symbols.length > 0) setActiveSymbol(symbols[0]!.symbol);
  }, [activeSymbol, symbols, setActiveSymbol]);

  return (
    <div className="p-4 max-w-md">
      <h1 className="text-lg font-semibold text-[#e8e8f0] mb-3">Order Entry</h1>
      <section
        aria-label="Order ticket"
        className="border border-[#2a2a45] rounded bg-[#0d0d14] p-3"
      >
        <OrderTicket tickDecimals={meta?.tick_decimals ?? 2} />
      </section>
    </div>
  );
}

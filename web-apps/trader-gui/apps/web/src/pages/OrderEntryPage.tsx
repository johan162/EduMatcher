import { useEffect, useState } from "react";
import { OrderTicket } from "@/components/orders/OrderTicket.js";
import { OcoForm } from "@/components/orders/OcoForm.js";
import { ComboForm } from "@/components/orders/ComboForm.js";
import { useActiveSymbolStore } from "@/store/useActiveSymbolStore.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";

type Advanced = "none" | "oco" | "combo";

/**
 * Standalone Order Entry screen (§12) — the full single-leg ticket with the
 * symbol picker unlocked, so choosing a symbol here also sets the active symbol
 * for the rest of the app. The Workspace embeds the same ticket in compact mode
 * with its symbol locked.
 *
 * The OCO (§12.7) and Combo (§12.8) sub-panels sit behind an "Advanced"
 * disclosure so a first classroom session stays small (§12.2).
 */
export function OrderEntryPage() {
  const activeSymbol = useActiveSymbolStore((s) => s.activeSymbol);
  const setActiveSymbol = useActiveSymbolStore((s) => s.setActiveSymbol);
  const symbols = useSymbolStore((s) => s.symbols);
  const meta = useSymbolStore((s) => s.symbols.find((m) => m.symbol === activeSymbol));
  const [advanced, setAdvanced] = useState<Advanced>("none");

  // Land on a usable symbol so the ref-price hint has something to show.
  useEffect(() => {
    if (!activeSymbol && symbols.length > 0) setActiveSymbol(symbols[0]!.symbol);
  }, [activeSymbol, symbols, setActiveSymbol]);

  const tab = (id: Advanced, label: string) => (
    <button
      type="button"
      onClick={() => setAdvanced((cur) => (cur === id ? "none" : id))}
      aria-pressed={advanced === id}
      className={`rounded px-2 py-1 text-[11px] font-medium ${
        advanced === id ? "bg-[#3a3a60] text-white" : "bg-[#1a1a28] text-[#9090b0] hover:bg-[#22223a]"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="p-4 max-w-3xl">
      <h1 className="text-lg font-semibold text-[#e8e8f0] mb-3">Order Entry</h1>
      <section
        aria-label="Order ticket"
        className="max-w-md border border-[#2a2a45] rounded bg-[#0d0d14] p-3"
      >
        <OrderTicket tickDecimals={meta?.tick_decimals ?? 2} />
      </section>

      <div className="mt-3">
        <div className="flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-wide text-[#505070]">Advanced</span>
          {tab("oco", "OCO")}
          {tab("combo", "Combo")}
        </div>

        {advanced === "oco" && (
          <section
            aria-label="OCO order entry"
            className="mt-2 border border-[#2a2a45] rounded bg-[#0d0d14] p-3"
          >
            <h2 className="mb-2 text-xs font-semibold text-[#e8e8f0]">OCO — One-Cancels-Other</h2>
            <OcoForm />
          </section>
        )}

        {advanced === "combo" && (
          <section
            aria-label="Combo order entry"
            className="mt-2 border border-[#2a2a45] rounded bg-[#0d0d14] p-3"
          >
            <h2 className="mb-2 text-xs font-semibold text-[#e8e8f0]">Combo — Multi-Leg (AON)</h2>
            <ComboForm />
          </section>
        )}
      </div>
    </div>
  );
}

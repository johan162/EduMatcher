import { useEffect } from "react";
import { useActiveSymbolStore } from "@/store/useActiveSymbolStore.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";
import { useBookStore } from "@/store/useBookStore.js";
import { SymbolChart } from "@/components/symbol/SymbolChart.js";
import { DepthLadder } from "@/components/symbol/DepthLadder.js";
import { WorkspaceTicket } from "@/components/workspace/WorkspaceTicket.js";
import { CompactBlotter } from "@/components/workspace/CompactBlotter.js";

const PANEL = "border border-[#2a2a45] rounded bg-[#0d0d14] p-3 overflow-auto";

/**
 * Trading Workspace (§11) — the default TRADER cockpit. Four panels (chart,
 * DOM ladder, order ticket, compact blotter) all bound to one active symbol.
 * Changing the symbol re-binds every panel atomically; clicking a DOM level
 * pre-fills the ticket price via the shared prefill store (§11.4).
 */
export function TradingWorkspacePage() {
  const activeSymbol = useActiveSymbolStore((s) => s.activeSymbol);
  const setActiveSymbol = useActiveSymbolStore((s) => s.setActiveSymbol);
  const symbols = useSymbolStore((s) => s.symbols);
  const meta = useSymbolStore((s) => s.symbols.find((m) => m.symbol === activeSymbol));
  const bookTick = useBookStore((s) =>
    activeSymbol ? s.books[activeSymbol]?.tickDecimals : undefined,
  );

  // Land on a usable symbol: if nothing is active yet, adopt the first known
  // one so all four quadrants have something to bind to.
  useEffect(() => {
    if (!activeSymbol && symbols.length > 0) {
      setActiveSymbol(symbols[0]!.symbol);
    }
  }, [activeSymbol, symbols, setActiveSymbol]);

  if (!activeSymbol) {
    return (
      <div className="flex flex-col items-start gap-2 border border-[#2a2a45] rounded p-6">
        <h1 className="text-sm font-semibold text-[#e8e8f0]">Trading Workspace</h1>
        <p className="text-xs text-[#9090b0]">
          No symbols available yet — is pm-api-gwy running?
        </p>
      </div>
    );
  }

  const tickDecimals = bookTick ?? meta?.tick_decimals ?? 2;

  return (
    <div className="flex flex-col h-full gap-3">
      {/* Header: symbol picker */}
      <div className="flex items-center gap-2">
        <h1 className="text-sm font-semibold text-[#e8e8f0]">Workspace</h1>
        <label className="flex items-center gap-1 ml-2">
          <span className="text-[10px] text-[#505070]">Symbol</span>
          <select
            value={activeSymbol}
            onChange={(e) => setActiveSymbol(e.target.value)}
            aria-label="Active symbol"
            className="bg-[#1a1a28] border border-[#2a2a45] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[#3a3a60]"
          >
            {symbols.map((s) => (
              <option key={s.symbol} value={s.symbol}>
                {s.symbol}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* Quadrants: left column (chart over ticket) + right column (DOM) */}
      <div className="grid grid-cols-3 gap-3 flex-1 min-h-0">
        <section className={`col-span-2 ${PANEL}`} aria-label="Price chart">
          <SymbolChart symbol={activeSymbol} />
        </section>

        <section className={`row-span-2 ${PANEL}`} aria-label="Depth of market">
          <DepthLadder symbol={activeSymbol} tickDecimals={tickDecimals} />
        </section>

        <section className={`col-span-2 ${PANEL}`} aria-label="Order ticket">
          <WorkspaceTicket symbol={activeSymbol} tickDecimals={tickDecimals} />
        </section>
      </div>

      {/* Bottom strip: compact blotter for the active symbol */}
      <section className={`${PANEL} max-h-56`} aria-label="Working orders">
        <CompactBlotter symbol={activeSymbol} tickDecimals={tickDecimals} />
      </section>
    </div>
  );
}

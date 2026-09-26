import { useEffect } from "react";
import { useActiveSymbolStore } from "@/store/useActiveSymbolStore.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";
import { useBookStore } from "@/store/useBookStore.js";
import { SymbolChart } from "@/components/symbol/SymbolChart.js";
import { DepthLadder } from "@/components/symbol/DepthLadder.js";
import { OrderTicket } from "@/components/orders/OrderTicket.js";
import { CompactBlotter } from "@/components/workspace/CompactBlotter.js";
import { SymbolPicker } from "@/components/shared/SymbolPicker.js";

const PANEL = "border border-line rounded bg-deep p-3 overflow-auto";

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
      <div className="flex flex-col items-start gap-2 border border-line rounded p-6">
        <h1 className="text-sm font-semibold text-fg">Trading Workspace</h1>
        <p className="text-xs text-fg-dim">
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
        <h1 className="text-sm font-semibold text-fg">Workspace</h1>
        <div className="flex items-center gap-1 ml-2">
          <span className="text-[10px] text-fg-faint">Symbol</span>
          <SymbolPicker
            symbols={symbols.map((s) => s.symbol)}
            value={activeSymbol}
            onChange={setActiveSymbol}
            label="Active symbol"
          />
        </div>
      </div>

      {/* Quadrants: left column (chart over ticket) + right column (DOM).
          Rows are content-sized (content-start) rather than the grid default
          of stretching "auto" rows to fill the flex-1 parent -- that default
          was inflating both the chart and ticket cells with dead space below
          their actual content. */}
      <div className="grid grid-cols-3 gap-3 content-start">
        <section className={`col-span-2 ${PANEL}`} aria-label="Price chart">
          <SymbolChart symbol={activeSymbol} />
        </section>

        <section className={`row-span-2 ${PANEL}`} aria-label="Depth of market">
          <DepthLadder symbol={activeSymbol} tickDecimals={tickDecimals} />
        </section>

        <section className={`col-span-2 ${PANEL}`} aria-label="Order ticket">
          {/* The ticket's field grid and BUY/SELL row are sized for the
              standalone Order Entry screen; at 25% narrower here they no
              longer eat width the chart/DOM quadrants could use. */}
          <div className="w-3/4">
            <OrderTicket compact lockedSymbol={activeSymbol} tickDecimals={tickDecimals} />
          </div>
        </section>
      </div>

      {/* Bottom strip: compact blotter for the active symbol. Sized to its
          own content (not flex-1) so an empty/short blotter doesn't claim
          all the leftover page height -- capped at max-h-56 like before, but
          now free to sit right under the quadrants instead of being pushed
          down by their old dead space. */}
      <section className={`${PANEL} max-h-56`} aria-label="Working orders">
        <CompactBlotter symbol={activeSymbol} tickDecimals={tickDecimals} />
      </section>
    </div>
  );
}

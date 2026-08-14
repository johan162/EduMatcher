import { useEffect, useMemo } from "react";
import { useQuoteBootstrapQuery } from "@/queries/index.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";
import { useActiveSymbolStore } from "@/store/useActiveSymbolStore.js";
import { useQuotePrefillStore } from "@/store/useQuotePrefillStore.js";
import { QuoteCard } from "@/components/quotes/QuoteCard.js";
import { quotesBySymbol } from "@/lib/quotes.js";

/**
 * Quote Management Panel (§14.1) — a card grid, one per configured symbol,
 * showing the active two-sided quote (from `GET /quotes/bootstrap`) with per-leg
 * fill bars. New quotes and cancels happen inline on each card; fill alerts and
 * cache reconciliation are handled app-wide by `useQuoteEvents`.
 *
 * F2 (§14.2) opens the New Quote form for the active symbol and focuses its
 * Quote ID field (implemented by seeding the prefill store, which the matching
 * card observes to open its form).
 */
export function QuoteMgmtPage() {
  const symbols = useSymbolStore((s) => s.symbols);
  const activeSymbol = useActiveSymbolStore((s) => s.activeSymbol);
  const setPrefill = useQuotePrefillStore((s) => s.setPrefill);
  const bootstrap = useQuoteBootstrapQuery();

  const bySymbol = useMemo(() => quotesBySymbol(bootstrap.data ?? []), [bootstrap.data]);

  // F2 → open + focus the New Quote form for the active symbol (§14.2).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "F2") return;
      const target = activeSymbol ?? symbols[0]?.symbol;
      if (!target) return;
      e.preventDefault();
      const q = bySymbol[target];
      setPrefill({
        symbol: target,
        bid_price: q?.bid_price ?? null,
        bid_qty: q?.bid_qty ?? null,
        ask_price: q?.ask_price ?? null,
        ask_qty: q?.ask_qty ?? null,
        quote_id: q?.quote_id ?? "",
      });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [activeSymbol, symbols, bySymbol, setPrefill]);

  const activeCount = bootstrap.data?.length ?? 0;

  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-[#e8e8f0]">Quote Management</h1>
        <span className="text-[11px] text-[#505070]">
          {activeCount} active {activeCount === 1 ? "quote" : "quotes"}
          {bootstrap.isFetching ? " · syncing…" : ""}
        </span>
        <span className="ml-auto text-[10px] text-[#505070]">Press F2 to quote the active symbol</span>
      </div>

      {bootstrap.isError && (
        <p className="text-xs text-ask">Could not load active quotes from the engine.</p>
      )}

      {symbols.length === 0 ? (
        <div className="rounded border border-[#2a2a45] p-8 text-center text-sm text-[#9090b0]">
          No configured symbols.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {symbols.map((s) => (
            <QuoteCard
              key={s.symbol}
              symbol={s.symbol}
              tickDecimals={s.tick_decimals ?? 2}
              quote={bySymbol[s.symbol]}
            />
          ))}
        </div>
      )}
    </div>
  );
}

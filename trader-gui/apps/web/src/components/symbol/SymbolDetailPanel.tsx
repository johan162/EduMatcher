import { useState } from "react";
import { X } from "lucide-react";
import { useActiveSymbolStore } from "@/store/useActiveSymbolStore.js";
import { useSymbolDetailStore } from "@/store/useSymbolDetailStore.js";
import { useBookStore } from "@/store/useBookStore.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";
import { useSessionStore } from "@/store/useSessionStore.js";
import { useHistoryDailyQuery, todayIso } from "@/queries/index.js";
import { isAuctionPhase } from "@/lib/marketRows.js";
import { changePct } from "@/lib/marketRows.js";
import { formatPrice, formatQty } from "@/lib/formatters.js";
import { SymbolChart } from "./SymbolChart.js";
import { DepthLadder } from "./DepthLadder.js";
import { TradesTape } from "./TradesTape.js";
import { StatsPanel } from "./StatsPanel.js";
import { AuctionPanel } from "./AuctionPanel.js";

type TabId = "chart" | "depth" | "trades" | "stats" | "auction";

const TABS: { id: TabId; label: string }[] = [
  { id: "chart", label: "Chart" },
  { id: "depth", label: "Depth" },
  { id: "trades", label: "Trades" },
  { id: "stats", label: "Stats" },
  { id: "auction", label: "Auction" },
];

/**
 * Symbol Detail right-panel overlay (§16). Opens when a Market Overview row is
 * clicked (which sets the active symbol) and slides in from the right. The
 * header cells update live from the book store; the AUCTION tab shows an amber
 * dot during a call phase.
 */
export function SymbolDetailPanel() {
  const isOpen = useSymbolDetailStore((s) => s.isOpen);
  const close = useSymbolDetailStore((s) => s.close);
  const symbol = useActiveSymbolStore((s) => s.activeSymbol);
  const [tab, setTab] = useState<TabId>("chart");

  const entry = useBookStore((s) => (symbol ? s.books[symbol] : undefined));
  const meta = useSymbolStore((s) => s.symbols.find((m) => m.symbol === symbol));
  const phase = useSessionStore((s) => s.phase);
  const dailyQuery = useHistoryDailyQuery(symbol ?? undefined, todayIso());

  if (!isOpen || !symbol) return null;

  const tickDecimals = entry?.tickDecimals ?? meta?.tick_decimals ?? 2;
  const last = entry?.lastPrice ?? null;
  const open = dailyQuery.data?.daily?.[0]?.open_price ?? null;
  const pct = changePct(last, open);
  const volume = dailyQuery.data?.daily?.[0]?.volume ?? null;
  const auctionActive = isAuctionPhase(phase);

  return (
    <aside
      role="dialog"
      aria-label={`${symbol} detail`}
      className="fixed right-0 top-10 bottom-0 w-[640px] max-w-[90vw] bg-[#0d0d14] border-l border-[#2a2a45] shadow-2xl z-40 flex flex-col animate-fade-in"
    >
      {/* Header */}
      <div className="flex items-start justify-between px-4 pt-3 pb-2 border-b border-[#2a2a45]">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-mono font-semibold text-[#e8e8f0]">{symbol}</h2>
            <span className="text-sm font-mono text-[#e8e8f0]">
              {last === null ? "—" : formatPrice(last, tickDecimals)}
            </span>
            <span
              className={`text-xs font-mono ${
                pct === null ? "text-[#505070]" : pct > 0 ? "text-up" : pct < 0 ? "text-down" : "text-[#9090b0]"
              }`}
            >
              {pct === null ? "—" : `${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`}
            </span>
          </div>
          <div className="text-xs text-[#505070] mt-0.5">
            Vol: {volume === null ? "—" : formatQty(volume)}
          </div>
        </div>
        <button
          type="button"
          onClick={close}
          aria-label="Close symbol detail"
          className="text-[#9090b0] hover:text-[#e8e8f0]"
        >
          <X size={18} />
        </button>
      </div>

      {/* Tabs */}
      <div role="tablist" aria-label="Symbol detail views" className="flex border-b border-[#2a2a45] px-2">
        {TABS.map((t) => {
          const active = tab === t.id;
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={active}
              type="button"
              onClick={() => setTab(t.id)}
              className={`relative px-3 py-2 text-xs font-medium ${
                active ? "text-[#e8e8f0]" : "text-[#9090b0] hover:text-[#e8e8f0]"
              }`}
            >
              <span className="flex items-center gap-1">
                {t.label}
                {t.id === "auction" && auctionActive && (
                  <span
                    className="w-1.5 h-1.5 rounded-full bg-auction"
                    aria-label="auction in progress"
                  />
                )}
              </span>
              {active && <span className="absolute left-2 right-2 -bottom-px h-0.5 bg-[#6ea8fe]" />}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-auto p-4">
        {tab === "chart" && <SymbolChart symbol={symbol} />}
        {tab === "depth" && <DepthLadder symbol={symbol} tickDecimals={tickDecimals} />}
        {tab === "trades" && <TradesTape symbol={symbol} tickDecimals={tickDecimals} />}
        {tab === "stats" && <StatsPanel symbol={symbol} tickDecimals={tickDecimals} />}
        {tab === "auction" && <AuctionPanel symbol={symbol} tickDecimals={tickDecimals} />}
      </div>
    </aside>
  );
}

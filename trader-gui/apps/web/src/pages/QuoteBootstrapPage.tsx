import { useMemo } from "react";
import { useQuoteBootstrapQuery, useQuoteLegsQuery } from "@/queries/index.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";
import { formatPrice, formatQty } from "@/lib/formatters.js";

function clock(ms: number | undefined): string {
  if (!ms) return "—";
  return new Date(ms).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

/**
 * Quote Bootstrap and Legs View (§14.3). Two complementary read sources:
 *  - `GET /quotes/bootstrap` (ActiveQuote) — the higher-level active-quote
 *    snapshot, and the reliable per-side price/qty source.
 *  - `GET /quotes/legs` — the granular legs. This endpoint is dual-shaped: full
 *    QuoteLeg records on the engine round-trip, or degraded per-quote ack/status
 *    dicts on the warm-cache fast path (normalized in `lib/quotes.ts`). Rows of
 *    the degraded shape show quote-level fields only, flagged below.
 *
 * Both queries are reconciled to engine truth by `useQuoteEvents` (on connect,
 * reconnect, and every quote.ack/status). The "reconciled at" stamp is the last
 * successful fetch; Resync forces a re-fetch of both.
 */
export function QuoteBootstrapPage() {
  const symbols = useSymbolStore((s) => s.symbols);
  const bootstrap = useQuoteBootstrapQuery();
  const legs = useQuoteLegsQuery();

  const tickFor = useMemo(() => {
    const map = new Map(symbols.map((s) => [s.symbol, s.tick_decimals ?? 2]));
    return (sym: string | null) => (sym ? (map.get(sym) ?? 2) : 2);
  }, [symbols]);

  const reconciledAt = clock(Math.max(bootstrap.dataUpdatedAt ?? 0, legs.dataUpdatedAt ?? 0) || undefined);
  const hasDegradedLegs = (legs.data ?? []).some((r) => r.shape === "quote");

  const th = "px-2 py-1.5 text-left font-medium";
  const thr = "px-2 py-1.5 text-right font-medium";

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-[#e8e8f0]">Quote Bootstrap &amp; Legs</h1>
        <span className="text-[11px] text-[#505070]">Reconciled at {reconciledAt}</span>
        <button
          type="button"
          onClick={() => {
            void bootstrap.refetch();
            void legs.refetch();
          }}
          className="ml-auto rounded border border-[#2a2a45] px-2 py-1 text-[11px] text-[#9090b0] hover:text-[#e8e8f0]"
        >
          Resync
        </button>
      </div>

      {/* Active quotes (bootstrap) */}
      <section aria-label="Active quotes" className="flex flex-col gap-1">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-[#9090b0]">
          Active Quotes ({bootstrap.data?.length ?? 0})
        </h2>
        <div className="overflow-auto rounded border border-[#2a2a45]">
          <table className="w-full border-collapse text-xs">
            <thead className="bg-[#12121a] text-[#9090b0]">
              <tr>
                <th className={th}>Symbol</th>
                <th className={th}>Quote ID</th>
                <th className={th}>State</th>
                <th className={thr}>Bid</th>
                <th className={thr}>Ask</th>
                <th className={th}>Bid status</th>
                <th className={th}>Ask status</th>
              </tr>
            </thead>
            <tbody>
              {(bootstrap.data ?? []).map((q) => (
                <tr key={q.quote_id} className="border-b border-[#1a1a28]">
                  <td className="px-2 py-1 font-mono font-medium">{q.symbol}</td>
                  <td className="px-2 py-1 font-mono text-[#9090b0]">{q.quote_id}</td>
                  <td className="px-2 py-1">{q.state}</td>
                  <td className="px-2 py-1 text-right font-mono text-bid">
                    {formatPrice(q.bid_price, tickFor(q.symbol))} × {formatQty(q.bid_qty)}{" "}
                    <span className="text-[#505070]">({formatQty(q.bid_remaining_qty)} rem)</span>
                  </td>
                  <td className="px-2 py-1 text-right font-mono text-ask">
                    {formatPrice(q.ask_price, tickFor(q.symbol))} × {formatQty(q.ask_qty)}{" "}
                    <span className="text-[#505070]">({formatQty(q.ask_remaining_qty)} rem)</span>
                  </td>
                  <td className="px-2 py-1 text-[#9090b0]">{q.bid_status}</td>
                  <td className="px-2 py-1 text-[#9090b0]">{q.ask_status}</td>
                </tr>
              ))}
              {(bootstrap.data?.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={7} className="px-2 py-6 text-center text-[#505070]">
                    No active quotes.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Legs */}
      <section aria-label="Quote legs" className="flex flex-col gap-1">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-[#9090b0]">
          Legs ({legs.data?.length ?? 0})
        </h2>
        <div className="overflow-auto rounded border border-[#2a2a45]">
          <table className="w-full border-collapse text-xs">
            <thead className="bg-[#12121a] text-[#9090b0]">
              <tr>
                <th className={th}>Symbol</th>
                <th className={th}>Quote ID</th>
                <th className={th}>Order ID</th>
                <th className={th}>Side</th>
                <th className={thr}>Price</th>
                <th className={thr}>Qty</th>
                <th className={thr}>Remaining</th>
                <th className={thr}>Filled</th>
                <th className={th}>Leg status</th>
                <th className={th}>Quote status</th>
              </tr>
            </thead>
            <tbody>
              {(legs.data ?? []).map((r) => (
                <tr key={r.key} className="border-b border-[#1a1a28]">
                  <td className="px-2 py-1 font-mono">{r.symbol ?? "—"}</td>
                  <td className="px-2 py-1 font-mono text-[#9090b0]">{r.quote_id || "—"}</td>
                  <td className="px-2 py-1 font-mono text-[#9090b0]">{r.order_id ?? "—"}</td>
                  <td
                    className={`px-2 py-1 ${r.leg_side === "BUY" ? "text-bid" : r.leg_side === "SELL" ? "text-ask" : "text-[#505070]"}`}
                  >
                    {r.leg_side ?? "—"}
                  </td>
                  <td className="px-2 py-1 text-right font-mono">
                    {r.price == null ? "—" : formatPrice(r.price, tickFor(r.symbol))}
                  </td>
                  <td className="px-2 py-1 text-right font-mono">{r.qty == null ? "—" : formatQty(r.qty)}</td>
                  <td className="px-2 py-1 text-right font-mono text-[#9090b0]">
                    {r.remaining == null ? "—" : formatQty(r.remaining)}
                  </td>
                  <td className="px-2 py-1 text-right font-mono">{r.filled == null ? "—" : formatQty(r.filled)}</td>
                  <td className="px-2 py-1 text-[#9090b0]">{r.status ?? "—"}</td>
                  <td className="px-2 py-1 text-[#9090b0]">{r.quote_status ?? "—"}</td>
                </tr>
              ))}
              {(legs.data?.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={10} className="px-2 py-6 text-center text-[#505070]">
                    No quote legs.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {hasDegradedLegs && (
          <p className="text-[10px] text-[#505070]">
            Some rows show quote-level status only: after a quote event lands, the gateway serves
            `/quotes/legs` from its live cache, which carries quote-level ack/status rather than
            per-leg detail. Per-side price/qty above is authoritative from the bootstrap snapshot.
          </p>
        )}
      </section>
    </div>
  );
}

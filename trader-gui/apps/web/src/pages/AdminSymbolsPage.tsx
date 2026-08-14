import { useReferenceQuery } from "@/queries/index.js";
import { useThrottledBooks } from "@/hooks/useThrottledBooks.js";
import { formatPrice, formatPct } from "@/lib/formatters.js";

const th = "px-2 py-1.5 text-left font-medium";
const thr = "px-2 py-1.5 text-right font-medium";

const WRITE_PREREQ =
  "Live symbol add/edit requires a backend extension (§6.7). The engine loads symbols from " +
  "engine_config.yaml at startup — edit the config and restart pm-engine.";

/**
 * Symbol Management (§15.2). Read-only: the configured symbols from
 * `GET /reference` with their tick size, risk level, collar and CB ladder size,
 * plus live top-of-book from the book store. Add/Edit are genuinely
 * unsupported — `POST/PATCH /admin/symbols` do not exist — so they render
 * disabled with a prerequisite tooltip rather than as broken controls.
 */
export function AdminSymbolsPage() {
  const referenceQuery = useReferenceQuery();
  const books = useThrottledBooks();
  const symbols = referenceQuery.data?.symbols ?? [];

  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-[#e8e8f0]">Symbol Management</h1>
        <span className="rounded bg-[#20203a] px-1.5 py-0.5 text-[10px] text-[#9090b0]">Read-only</span>
        <button
          type="button"
          disabled
          title={WRITE_PREREQ}
          aria-label="Add symbol (unsupported)"
          className="ml-auto cursor-not-allowed rounded border border-[#2a2a45] px-2 py-1 text-[11px] text-[#505070] opacity-60"
        >
          Add symbol
        </button>
      </div>

      <p className="rounded border border-[#2a2a45] bg-[#12121a] px-2 py-1.5 text-[11px] text-[#9090b0]">
        {WRITE_PREREQ}
      </p>

      {referenceQuery.isError && (
        <p className="text-xs text-ask">Could not load symbols from the engine.</p>
      )}

      <div className="overflow-auto rounded border border-[#2a2a45]">
        <table className="w-full border-collapse text-xs">
          <thead className="bg-[#12121a] text-[#9090b0]">
            <tr>
              <th className={th}>Symbol</th>
              <th className={thr}>Tick Dec.</th>
              <th className={th}>Risk Level</th>
              <th className={thr}>Static Band</th>
              <th className={thr}>Dynamic Band</th>
              <th className={thr}>CB Levels</th>
              <th className={thr}>Last Bid</th>
              <th className={thr}>Last Ask</th>
              <th className={thr}>Action</th>
            </tr>
          </thead>
          <tbody>
            {symbols.map((s) => {
              const book = books[s.symbol];
              const bid = book?.bids[0]?.price ?? null;
              const ask = book?.asks[0]?.price ?? null;
              const cbCount = s.circuit_breaker?.levels?.length ?? 0;
              return (
                <tr key={s.symbol} className="border-b border-[#1a1a28]">
                  <td className="px-2 py-1 font-mono font-medium">{s.symbol}</td>
                  <td className="px-2 py-1 text-right font-mono">{s.tick_decimals}</td>
                  <td className="px-2 py-1 text-[#9090b0]">{s.level ?? "(default)"}</td>
                  <td className="px-2 py-1 text-right font-mono">{formatPct(s.collar?.static_band_pct)}</td>
                  <td className="px-2 py-1 text-right font-mono">{formatPct(s.collar?.dynamic_band_pct)}</td>
                  <td className="px-2 py-1 text-right font-mono text-[#9090b0]">{cbCount || "—"}</td>
                  <td className="px-2 py-1 text-right font-mono text-bid">
                    {formatPrice(bid, s.tick_decimals)}
                  </td>
                  <td className="px-2 py-1 text-right font-mono text-ask">
                    {formatPrice(ask, s.tick_decimals)}
                  </td>
                  <td className="px-2 py-1 text-right">
                    <button
                      type="button"
                      disabled
                      title={WRITE_PREREQ}
                      aria-label={`Edit ${s.symbol} (unsupported)`}
                      className="cursor-not-allowed rounded border border-[#2a2a45] px-2 py-0.5 text-[11px] text-[#505070] opacity-60"
                    >
                      Edit
                    </button>
                  </td>
                </tr>
              );
            })}
            {symbols.length === 0 && !referenceQuery.isLoading && (
              <tr>
                <td colSpan={9} className="px-2 py-6 text-center text-[#505070]">No symbols.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

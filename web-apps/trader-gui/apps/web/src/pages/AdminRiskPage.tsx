import { useState } from "react";
import { useThrottledBooks } from "@/hooks/useThrottledBooks.js";
import { useReferenceQuery, useReferenceRiskQuery } from "@/queries/index.js";
import { TableSkeleton } from "@/components/shared/Skeleton.js";
import { formatNsDuration, formatPct, formatPrice } from "@/lib/formatters.js";
import type { Collar, ReferenceSymbol, RiskLevel } from "@/types/index.js";
import { HeaderTip } from "@/components/shared/HeaderTip.js";

const PAGE_SIZES = [15, 30, 50] as const;

const inputCls =
  "bg-raised border border-line rounded px-2 py-1 text-xs focus:outline-none focus:border-[#3a3a60]";
const pageBtnCls =
  "rounded border border-line px-2 py-1 text-[11px] text-fg-dim hover:text-fg disabled:opacity-40";

const th = "px-2 py-1.5 text-left font-medium";
const thr = "px-2 py-1.5 text-right font-medium";

/** Resolve a symbol's effective collar: its own, else its risk level's. */
function effectiveCollar(sym: ReferenceSymbol, levels: RiskLevel[], defaultLevel: string | null): {
  collar: Collar | null;
  source: string;
} {
  if (sym.collar) return { collar: sym.collar, source: "symbol" };
  const levelName = sym.level ?? defaultLevel;
  const lvl = levels.find((l) => l.name === levelName);
  if (lvl?.collar) return { collar: lvl.collar, source: levelName ?? "level" };
  return { collar: null, source: levelName ?? "—" };
}

/**
 * Risk Control Panel (§15.5) — read-only views of the resolved static
 * configuration from `GET /reference` (+ `/reference/risk`). Collar settings per
 * symbol (own collar, else inherited from its risk level) and the per-symbol
 * circuit-breaker ladder. Nothing here is editable — risk config is loaded from
 * `engine_config.yaml`.
 */
export function AdminRiskPage() {
  const referenceQuery = useReferenceQuery();
  const riskQuery = useReferenceRiskQuery();
  const books = useThrottledBooks();

  const allSymbols = referenceQuery.data?.symbols ?? [];

  const [filter, setFilter] = useState("");
  const [pageSize, setPageSize] = useState<number>(PAGE_SIZES[0]);
  const [pageIndex, setPageIndex] = useState(0);

  // Both per-symbol tables show the same page of symbols.
  const needle = filter.trim().toUpperCase();
  const matching = needle ? allSymbols.filter((s) => s.symbol.toUpperCase().includes(needle)) : allSymbols;
  const pageCount = Math.max(1, Math.ceil(matching.length / pageSize));
  const page = Math.min(pageIndex, pageCount - 1);
  const symbols = matching.slice(page * pageSize, (page + 1) * pageSize);
  const levels = riskQuery.data?.levels ?? referenceQuery.data?.risk.levels ?? [];
  const defaultLevel = riskQuery.data?.default_level ?? referenceQuery.data?.risk.default_level ?? null;

  const loading = referenceQuery.isLoading || riskQuery.isLoading;
  const error = referenceQuery.isError || riskQuery.isError;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-fg">Risk Controls</h1>
        <span className="rounded bg-elevated px-1.5 py-0.5 text-[10px] text-fg-dim">Read-only</span>
        {defaultLevel && (
          <span className="text-[11px] text-fg-faint">Default level: {defaultLevel}</span>
        )}
      </div>

      {loading && <TableSkeleton rows={8} columns={4} />}
      {error && <p className="text-xs text-ask">Could not load risk configuration from the engine.</p>}

      {/* Named risk levels */}
      {levels.length > 0 && (
        <section aria-label="Risk levels" className="flex flex-col gap-1">
          <h2 className="text-[11px] font-semibold uppercase tracking-wide text-fg-dim">Risk Levels</h2>
          <div className="overflow-auto rounded border border-line">
            <table className="w-full border-collapse text-xs">
              <thead className="bg-panel text-fg-dim">
                <tr>
                  <th className={th}>Level <HeaderTip table="admin-risk" col="Level" /></th>
                  <th className={thr}>Static Band <HeaderTip table="admin-risk" col="Static Band" /></th>
                  <th className={thr}>Dynamic Band <HeaderTip table="admin-risk" col="Dynamic Band" /></th>
                </tr>
              </thead>
              <tbody>
                {levels.map((l) => (
                  <tr key={l.name} className="border-b border-raised">
                    <td className="px-2 py-1 font-mono font-medium">
                      {l.name}
                      {l.name === defaultLevel && (
                        <span className="ml-1 rounded bg-elevated px-1 text-[9px] text-fg-dim">default</span>
                      )}
                    </td>
                    <td className="px-2 py-1 text-right font-mono">{formatPct(l.collar?.static_band_pct)}</td>
                    <td className="px-2 py-1 text-right font-mono">{formatPct(l.collar?.dynamic_band_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Filter + pager shared by the two per-symbol tables */}
      {!loading && allSymbols.length > 0 && (
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-fg-faint">Symbol</span>
            <input
              value={filter}
              onChange={(e) => {
                setFilter(e.target.value.toUpperCase());
                setPageIndex(0);
              }}
              aria-label="Filter symbol"
              placeholder="All"
              className={`${inputCls} font-mono w-28`}
            />
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-fg-faint">Symbols per page</span>
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPageIndex(0);
              }}
              aria-label="Symbols per page"
              className={inputCls}
            >
              {PAGE_SIZES.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPageIndex(page - 1)}
              disabled={page === 0}
              className={pageBtnCls}
            >
              Prev
            </button>
            <span className="text-[11px] text-fg-faint">
              {matching.length === 0
                ? "0 symbols"
                : `${page * pageSize + 1}–${page * pageSize + symbols.length} of ${matching.length}`}
              {" · "}page {page + 1} / {pageCount}
            </span>
            <button
              type="button"
              onClick={() => setPageIndex(page + 1)}
              disabled={page >= pageCount - 1}
              className={pageBtnCls}
            >
              Next
            </button>
          </div>
        </div>
      )}

      {/* Per-symbol collar settings (§15.5.1) */}
      {!loading && (
      <section aria-label="Collar settings" className="flex flex-col gap-1">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-fg-dim">
          Collar Settings (per symbol)
        </h2>
        <div className="overflow-auto rounded border border-line">
          <table className="w-full border-collapse text-xs">
            <thead className="bg-panel text-fg-dim">
              <tr>
                <th className={th}>Symbol <HeaderTip table="admin-risk" col="Symbol" /></th>
                <th className={thr}>Static Band <HeaderTip table="admin-risk" col="Static Band" /></th>
                <th className={thr}>Dynamic Band <HeaderTip table="admin-risk" col="Dynamic Band" /></th>
                <th className={th}>Profile <HeaderTip table="admin-risk" col="Profile" /></th>
                <th className={thr}>Tick Dec. <HeaderTip table="admin-risk" col="Tick Dec." /></th>
                <th className={thr}>CB Levels <HeaderTip table="admin-risk" col="CB Levels" /></th>
                <th className={thr}>Last Bid <HeaderTip table="admin-risk" col="Last Bid" /></th>
                <th className={thr}>Last Ask <HeaderTip table="admin-risk" col="Last Ask" /></th>
              </tr>
            </thead>
            <tbody>
              {symbols.map((s) => {
                const { collar, source } = effectiveCollar(s, levels, defaultLevel);
                return (
                  <tr key={s.symbol} className="border-b border-raised">
                    <td className="px-2 py-1 font-mono font-medium">{s.symbol}</td>
                    <td className="px-2 py-1 text-right font-mono">{formatPct(collar?.static_band_pct)}</td>
                    <td className="px-2 py-1 text-right font-mono">{formatPct(collar?.dynamic_band_pct)}</td>
                    <td className="px-2 py-1 text-fg-dim">{source}</td>
                    <td className="px-2 py-1 text-right font-mono">{s.tick_decimals}</td>
                    <td className="px-2 py-1 text-right font-mono text-fg-dim">
                      {s.circuit_breaker?.levels?.length || "—"}
                    </td>
                    <td className="px-2 py-1 text-right font-mono text-bid">
                      {formatPrice(books[s.symbol]?.bids[0]?.price ?? null, s.tick_decimals)}
                    </td>
                    <td className="px-2 py-1 text-right font-mono text-ask">
                      {formatPrice(books[s.symbol]?.asks[0]?.price ?? null, s.tick_decimals)}
                    </td>
                  </tr>
                );
              })}
              {symbols.length === 0 && !loading && (
                <tr>
                  <td colSpan={8} className="px-2 py-6 text-center text-fg-faint">
                    {allSymbols.length === 0 ? "No symbols." : "No symbols match the filter."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      )}

      {/* Per-symbol circuit-breaker ladder (§15.5.2) */}
      {!loading && (
      <section aria-label="Circuit breaker ladder" className="flex flex-col gap-1">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-fg-dim">
          Circuit Breaker Ladder (per symbol)
        </h2>
        <p className="text-[10px] text-fg-faint">
          The ladder is configured per symbol. Every halt reopens via a call auction — there is no
          per-level resumption mode.
        </p>
        <div className="overflow-auto rounded border border-line">
          <table className="w-full border-collapse text-xs">
            <thead className="bg-panel text-fg-dim">
              <tr>
                <th className={th}>Symbol <HeaderTip table="admin-risk" col="Symbol" /></th>
                <th className={th}>Level <HeaderTip table="admin-risk" col="Level" /></th>
                <th className={thr}>Price Shift <HeaderTip table="admin-risk" col="Price Shift" /></th>
                <th className={thr}>Halt Duration <HeaderTip table="admin-risk" col="Halt Duration" /></th>
              </tr>
            </thead>
            {/* One <tbody> per symbol so its levels stripe as a group. */}
            {symbols
              .filter((s) => s.circuit_breaker?.levels?.length)
              .map((s, n) => (
                <tbody key={s.symbol} data-testid="cb-group" className={n % 2 === 1 ? "bg-raised" : ""}>
                  {(s.circuit_breaker?.levels ?? []).map((lvl, i, all) => (
                    <tr
                      key={`${lvl.name}-${i}`}
                      className={i === all.length - 1 ? "border-b border-line" : ""}
                    >
                      <td className="px-2 py-1 font-mono font-medium">{i === 0 ? s.symbol : ""}</td>
                      <td className="px-2 py-1 font-mono">{lvl.name}</td>
                      <td className="px-2 py-1 text-right font-mono">{formatPct(lvl.price_shift_pct)}</td>
                      <td className="px-2 py-1 text-right font-mono">{formatNsDuration(lvl.halt_duration_ns)}</td>
                    </tr>
                  ))}
                </tbody>
              ))}
            {symbols.every((s) => !s.circuit_breaker?.levels?.length) && (
              <tbody>
                <tr>
                  <td colSpan={4} className="px-2 py-6 text-center text-fg-faint">
                    {allSymbols.length > 0 && symbols.length === 0
                      ? "No symbols match the filter."
                      : "No circuit breakers configured."}
                  </td>
                </tr>
              </tbody>
            )}
          </table>
        </div>
      </section>
      )}
    </div>
  );
}

import { useReferenceQuery, useReferenceRiskQuery } from "@/queries/index.js";
import { formatNsDuration, formatPct } from "@/lib/formatters.js";
import type { Collar, ReferenceSymbol, RiskLevel } from "@/types/index.js";

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

  const symbols = referenceQuery.data?.symbols ?? [];
  const levels = riskQuery.data?.levels ?? referenceQuery.data?.risk.levels ?? [];
  const defaultLevel = riskQuery.data?.default_level ?? referenceQuery.data?.risk.default_level ?? null;

  const loading = referenceQuery.isLoading || riskQuery.isLoading;
  const error = referenceQuery.isError || riskQuery.isError;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-[#e8e8f0]">Risk Controls</h1>
        <span className="rounded bg-[#20203a] px-1.5 py-0.5 text-[10px] text-[#9090b0]">Read-only</span>
        {defaultLevel && (
          <span className="text-[11px] text-[#505070]">Default level: {defaultLevel}</span>
        )}
      </div>

      {loading && <p className="text-xs text-[#9090b0]">Loading reference data…</p>}
      {error && <p className="text-xs text-ask">Could not load risk configuration from the engine.</p>}

      {/* Named risk levels */}
      {levels.length > 0 && (
        <section aria-label="Risk levels" className="flex flex-col gap-1">
          <h2 className="text-[11px] font-semibold uppercase tracking-wide text-[#9090b0]">Risk Levels</h2>
          <div className="overflow-auto rounded border border-[#2a2a45]">
            <table className="w-full border-collapse text-xs">
              <thead className="bg-[#12121a] text-[#9090b0]">
                <tr>
                  <th className={th}>Level</th>
                  <th className={thr}>Static Band</th>
                  <th className={thr}>Dynamic Band</th>
                </tr>
              </thead>
              <tbody>
                {levels.map((l) => (
                  <tr key={l.name} className="border-b border-[#1a1a28]">
                    <td className="px-2 py-1 font-mono font-medium">
                      {l.name}
                      {l.name === defaultLevel && (
                        <span className="ml-1 rounded bg-[#20203a] px-1 text-[9px] text-[#9090b0]">default</span>
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

      {/* Per-symbol collar settings (§15.5.1) */}
      <section aria-label="Collar settings" className="flex flex-col gap-1">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-[#9090b0]">
          Collar Settings (per symbol)
        </h2>
        <div className="overflow-auto rounded border border-[#2a2a45]">
          <table className="w-full border-collapse text-xs">
            <thead className="bg-[#12121a] text-[#9090b0]">
              <tr>
                <th className={th}>Symbol</th>
                <th className={thr}>Static Band</th>
                <th className={thr}>Dynamic Band</th>
                <th className={th}>Profile</th>
              </tr>
            </thead>
            <tbody>
              {symbols.map((s) => {
                const { collar, source } = effectiveCollar(s, levels, defaultLevel);
                return (
                  <tr key={s.symbol} className="border-b border-[#1a1a28]">
                    <td className="px-2 py-1 font-mono font-medium">{s.symbol}</td>
                    <td className="px-2 py-1 text-right font-mono">{formatPct(collar?.static_band_pct)}</td>
                    <td className="px-2 py-1 text-right font-mono">{formatPct(collar?.dynamic_band_pct)}</td>
                    <td className="px-2 py-1 text-[#9090b0]">{source}</td>
                  </tr>
                );
              })}
              {symbols.length === 0 && !loading && (
                <tr>
                  <td colSpan={4} className="px-2 py-6 text-center text-[#505070]">No symbols.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Per-symbol circuit-breaker ladder (§15.5.2) */}
      <section aria-label="Circuit breaker ladder" className="flex flex-col gap-1">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-[#9090b0]">
          Circuit Breaker Ladder (per symbol)
        </h2>
        <p className="text-[10px] text-[#505070]">
          The ladder is configured per symbol. Every halt reopens via a call auction — there is no
          per-level resumption mode.
        </p>
        <div className="overflow-auto rounded border border-[#2a2a45]">
          <table className="w-full border-collapse text-xs">
            <thead className="bg-[#12121a] text-[#9090b0]">
              <tr>
                <th className={th}>Symbol</th>
                <th className={th}>Level</th>
                <th className={thr}>Price Shift</th>
                <th className={thr}>Halt Duration</th>
              </tr>
            </thead>
            <tbody>
              {symbols.flatMap((s) =>
                (s.circuit_breaker?.levels ?? []).map((lvl, i) => (
                  <tr key={`${s.symbol}-${lvl.name}-${i}`} className="border-b border-[#1a1a28]">
                    <td className="px-2 py-1 font-mono font-medium">{i === 0 ? s.symbol : ""}</td>
                    <td className="px-2 py-1 font-mono">{lvl.name}</td>
                    <td className="px-2 py-1 text-right font-mono">{formatPct(lvl.price_shift_pct)}</td>
                    <td className="px-2 py-1 text-right font-mono">{formatNsDuration(lvl.halt_duration_ns)}</td>
                  </tr>
                )),
              )}
              {symbols.every((s) => !s.circuit_breaker?.levels?.length) && !loading && (
                <tr>
                  <td colSpan={4} className="px-2 py-6 text-center text-[#505070]">
                    No circuit breakers configured.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

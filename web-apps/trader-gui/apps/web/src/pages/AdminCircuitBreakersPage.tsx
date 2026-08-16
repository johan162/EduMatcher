import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  useReferenceQuery,
  useAdminHaltsQuery,
  useTriggerCircuitBreakerMutation,
  useResumeCircuitBreakerMutation,
} from "@/queries/index.js";
import { useHaltStore } from "@/store/useHaltStore.js";
import { CancelConfirm } from "@/components/orders/CancelConfirm.js";
import { formatNsTimestamp } from "@/lib/formatters.js";
import { ApiError } from "@/api/apiFetch.js";

const th = "px-2 py-1.5 text-left font-medium";
const fieldCls =
  "bg-[#1a1a28] border border-[#2a2a45] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[#3a3a60]";

/**
 * Circuit Breaker Management (§15.6) — the live operational view: active halts
 * (from `haltStore`, bootstrapped by `GET /admin/halts` and kept current by the
 * `circuit_breaker` channel) plus manual trigger and clear.
 *
 * The Level selector IS functional (an earlier design revision disabled it):
 * `POST /admin/circuit-breaker/trigger` honours `level` end-to-end, so the
 * selector is populated from the chosen symbol's own configured CB ladder
 * (`/reference`). Selecting no level halts indefinitely until an explicit clear.
 */
export function AdminCircuitBreakersPage() {
  const referenceQuery = useReferenceQuery();
  const haltsQuery = useAdminHaltsQuery();
  const setHalts = useHaltStore((s) => s.setHalts);
  const halts = useHaltStore((s) => s.halts);
  const trigger = useTriggerCircuitBreakerMutation();
  const resume = useResumeCircuitBreakerMutation();

  const symbols = referenceQuery.data?.symbols ?? [];
  const [symbol, setSymbol] = useState("");
  const [level, setLevel] = useState("");
  const [confirmTrigger, setConfirmTrigger] = useState(false);
  const [resumeTarget, setResumeTarget] = useState<string | null>(null);

  // Bootstrap/reconcile the halt store from the authoritative snapshot.
  const haltsData = haltsQuery.data?.halted;
  useEffect(() => {
    if (haltsData) setHalts(haltsData);
  }, [haltsData, setHalts]);

  const activeHalts = useMemo(() => Object.values(halts), [halts]);
  const selectedSymbolLevels = useMemo(
    () => symbols.find((s) => s.symbol === symbol)?.circuit_breaker?.levels ?? [],
    [symbols, symbol],
  );

  const doTrigger = () => {
    trigger.mutate(
      { symbol, level: level || undefined },
      {
        onSuccess: () => toast.success(`Halt submitted for ${symbol}${level ? ` (${level})` : ""}`),
        onError: (err) => {
          if (err instanceof ApiError && err.code === "ROLE_DENIED") {
            toast.error(`Rejected: ${err.message}`);
            return;
          }
          if (err instanceof ApiError && (err.status === 503 || err.code === "ENGINE_TIMEOUT")) {
            toast(`Halt submitted for ${symbol} — awaiting confirmation`);
            return;
          }
          toast.error(err instanceof ApiError ? `${err.code}: ${err.message}` : "Trigger failed");
        },
      },
    );
    setConfirmTrigger(false);
  };

  const doResume = (sym: string) => {
    resume.mutate(sym, {
      onSuccess: () => toast.success(`Resume submitted for ${sym}`),
      onError: (err) => {
        if (err instanceof ApiError && (err.status === 503 || err.code === "ENGINE_TIMEOUT")) {
          toast(`Resume submitted for ${sym} — awaiting confirmation`);
          return;
        }
        toast.error(err instanceof ApiError ? `${err.code}: ${err.message}` : "Resume failed");
      },
    });
    setResumeTarget(null);
  };

  return (
    <div className="flex flex-col gap-4 p-4">
      <h1 className="text-lg font-semibold text-[#e8e8f0]">Circuit Breakers</h1>

      {/* Manual trigger (§15.6.2) */}
      <section aria-label="Manual trigger" className="flex flex-col gap-2 rounded border border-[#2a2a45] bg-[#0d0d14] p-3">
        <h2 className="text-xs font-semibold text-[#e8e8f0]">Manual halt</h2>
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-[#505070]">Symbol</span>
            <input
              list="cb-symbols"
              value={symbol}
              onChange={(e) => {
                setSymbol(e.target.value.toUpperCase());
                setLevel("");
              }}
              aria-label="Halt symbol"
              placeholder="AAPL"
              className={`${fieldCls} w-28`}
            />
            <datalist id="cb-symbols">
              {symbols.map((s) => (
                <option key={s.symbol} value={s.symbol} />
              ))}
            </datalist>
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-[#505070]">Level</span>
            <select
              value={level}
              onChange={(e) => setLevel(e.target.value)}
              aria-label="Halt level"
              disabled={selectedSymbolLevels.length === 0}
              className={`${fieldCls} w-44 disabled:opacity-40`}
            >
              <option value="">Indefinite (no level)</option>
              {selectedSymbolLevels.map((l) => (
                <option key={l.name} value={l.name}>
                  {l.name}
                  {l.price_shift_pct != null ? ` (${l.price_shift_pct}%)` : ""}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={() => setConfirmTrigger(true)}
            disabled={!symbol.trim() || trigger.isPending}
            className="rounded bg-halt px-3 py-1.5 text-xs font-semibold text-black hover:brightness-110 disabled:opacity-40"
          >
            Halt symbol
          </button>
        </div>
        <p className="text-[10px] text-[#505070]">
          A level (from the symbol's ladder) runs the real breaker with auto-resume; no level halts
          indefinitely until cleared.
        </p>
      </section>

      {/* Active halts (§15.6.1) */}
      <section aria-label="Active halts" className="flex flex-col gap-1">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-[#9090b0]">
          Active Halts ({activeHalts.length})
        </h2>
        <div className="overflow-auto rounded border border-[#2a2a45]">
          <table className="w-full border-collapse text-xs">
            <thead className="bg-[#12121a] text-[#9090b0]">
              <tr>
                <th className={th}>Symbol</th>
                <th className={th}>Level</th>
                <th className="px-2 py-1.5 text-right font-medium">Trigger Price</th>
                <th className="px-2 py-1.5 text-right font-medium">Reference Price</th>
                <th className={th}>Est. Resume</th>
                <th className={th}>Source</th>
                <th className="px-2 py-1.5 text-right font-medium">Action</th>
              </tr>
            </thead>
            <tbody>
              {activeHalts.map((h) => (
                <tr key={h.symbol} className="border-b border-[#1a1a28]">
                  <td className="px-2 py-1 font-mono font-medium">{h.symbol}</td>
                  <td className="px-2 py-1 font-mono">{h.level ?? "—"}</td>
                  <td className="px-2 py-1 text-right font-mono text-[#9090b0]">
                    {h.trigger_price ?? "—"}
                  </td>
                  <td className="px-2 py-1 text-right font-mono text-[#9090b0]">
                    {h.reference_price ?? "—"}
                  </td>
                  <td className="px-2 py-1 font-mono text-[#9090b0]">
                    {h.resume_at_ns ? formatNsTimestamp(h.resume_at_ns) : "indefinite"}
                  </td>
                  <td className="px-2 py-1 text-[#9090b0]">{h.halt_source ?? "—"}</td>
                  <td className="px-2 py-1 text-right">
                    <button
                      type="button"
                      onClick={() => setResumeTarget(h.symbol)}
                      disabled={resume.isPending}
                      aria-label={`Clear halt ${h.symbol}`}
                      className="rounded border border-[#2a2a45] px-2 py-0.5 text-[11px] text-[#9090b0] hover:text-emerald-400 disabled:opacity-40"
                    >
                      Clear
                    </button>
                  </td>
                </tr>
              ))}
              {activeHalts.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-2 py-6 text-center text-[#505070]">
                    No active halts.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <p className="text-[10px] text-[#505070]">
          Trigger/Reference price populate only for halts seen live on the circuit_breaker channel;
          rows restored from the bootstrap leave them blank until the symbol re-halts.
        </p>
      </section>

      {confirmTrigger && (
        <CancelConfirm
          title="Halt symbol?"
          message={
            level
              ? `Trigger the ${level} circuit breaker for ${symbol}? It will run the real breaker and auto-resume.`
              : `Halt ${symbol} indefinitely (no level)? It stays halted until an explicit clear.`
          }
          confirmLabel="Halt symbol"
          busy={trigger.isPending}
          onConfirm={doTrigger}
          onClose={() => setConfirmTrigger(false)}
        />
      )}

      {resumeTarget && (
        <CancelConfirm
          title="Clear halt?"
          message={`Resume trading on ${resumeTarget}?`}
          confirmLabel="Clear halt"
          busy={resume.isPending}
          onConfirm={() => doResume(resumeTarget)}
          onClose={() => setResumeTarget(null)}
        />
      )}
    </div>
  );
}

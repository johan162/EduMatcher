import { useState } from "react";
import { toast } from "sonner";
import {
  useSymbolKillSwitchMutation,
  useGatewayKillSwitchMutation,
  useGlobalKillSwitchMutation,
} from "@/queries/index.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";
import { CancelConfirm } from "@/components/orders/CancelConfirm.js";
import { ConfirmTypedDialog } from "@/components/shared/ConfirmTypedDialog.js";
import { ApiError } from "@/api/apiFetch.js";
import type { AdminGateway } from "@/types/index.js";

interface KillSwitchPanelProps {
  gateways: AdminGateway[];
}

const fieldCls =
  "bg-[#1a1a28] border border-[#2a2a45] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[#3a3a60]";

/** Shared error handling for the three kill-switch scopes. */
function killSwitchError(err: unknown): void {
  if (err instanceof ApiError && err.code === "ROLE_DENIED") {
    toast.error(`Rejected: ${err.message}`);
    return;
  }
  if (err instanceof ApiError && (err.status === 503 || err.code === "ENGINE_TIMEOUT")) {
    toast("Kill switch submitted — awaiting engine confirmation");
    return;
  }
  toast.error(err instanceof ApiError ? `${err.code}: ${err.message}` : "Kill switch failed");
}

/**
 * Admin Kill Switch (§15.8) — cancels resting orders/quotes at three scopes, all
 * verified against the current gateway. Each scope always confirms regardless of
 * power-user mode; the market-wide Global scope requires typing CONFIRM (§20.3).
 *
 * NOTE: an earlier design revision treated By Gateway / Global as disabled
 * placeholders pending a backend endpoint. Those endpoints
 * (`/admin/kill-switch/gateway`, `/admin/kill-switch/global`) now exist, so they
 * are implemented and working here.
 */
export function KillSwitchPanel({ gateways }: KillSwitchPanelProps) {
  const symbols = useSymbolStore((s) => s.symbols);
  const symbolKs = useSymbolKillSwitchMutation();
  const gatewayKs = useGatewayKillSwitchMutation();
  const globalKs = useGlobalKillSwitchMutation();

  const [symbol, setSymbol] = useState("");
  const [gatewayId, setGatewayId] = useState("");
  const [confirmSymbol, setConfirmSymbol] = useState(false);
  const [confirmGateway, setConfirmGateway] = useState(false);
  const [confirmGlobal, setConfirmGlobal] = useState(false);

  const runSymbol = () => {
    const sym = symbol.trim().toUpperCase();
    symbolKs.mutate(
      { symbol: sym },
      {
        onSuccess: (r) =>
          toast.success(
            `Kill switch ${r.symbol}: ${r.cancelled_orders} orders, ${r.cancelled_quotes} quotes cancelled`,
          ),
        onError: killSwitchError,
      },
    );
    setConfirmSymbol(false);
  };

  const runGateway = () => {
    gatewayKs.mutate(
      { targetGatewayId: gatewayId },
      {
        onSuccess: (r) =>
          toast.success(
            `Kill switch ${r.target_gateway_id}: ${r.cancelled_orders} orders, ${r.cancelled_quotes} quotes cancelled`,
          ),
        onError: killSwitchError,
      },
    );
    setConfirmGateway(false);
  };

  const runGlobal = () => {
    globalKs.mutate(undefined, {
      onSuccess: (r) =>
        toast.success(
          `Global kill switch: ${r.cancelled_orders} orders, ${r.cancelled_quotes} quotes across ${r.affected_gateways} gateways`,
        ),
      onError: killSwitchError,
    });
    setConfirmGlobal(false);
  };

  return (
    <section aria-label="Kill switch" className="flex flex-col gap-3 rounded border border-[#2a2a45] bg-[#0d0d14] p-3">
      <div>
        <h2 className="text-xs font-semibold text-[#e8e8f0]">Kill Switch</h2>
        <p className="text-[10px] text-[#505070]">
          Cancel resting orders and quotes. Does not halt trading — participants may re-submit.
        </p>
      </div>

      {/* By Symbol */}
      <div className="flex items-end gap-2">
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-[#505070]">By Symbol</span>
          <input
            list="ks-symbols"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            aria-label="Kill switch symbol"
            placeholder="AAPL"
            className={`${fieldCls} w-28`}
          />
          <datalist id="ks-symbols">
            {symbols.map((s) => (
              <option key={s.symbol} value={s.symbol} />
            ))}
          </datalist>
        </label>
        <button
          type="button"
          onClick={() => setConfirmSymbol(true)}
          disabled={!symbol.trim() || symbolKs.isPending}
          className="rounded border border-[#2a2a45] px-2 py-1 text-[11px] text-[#9090b0] hover:text-ask disabled:opacity-40"
        >
          Cancel symbol
        </button>
      </div>

      {/* By Gateway */}
      <div className="flex items-end gap-2">
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-[#505070]">By Gateway</span>
          <select
            value={gatewayId}
            onChange={(e) => setGatewayId(e.target.value)}
            aria-label="Kill switch gateway"
            className={`${fieldCls} w-40`}
          >
            <option value="">Select gateway…</option>
            {gateways.map((g) => (
              <option key={g.id} value={g.id}>
                {g.id} ({g.role})
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={() => setConfirmGateway(true)}
          disabled={!gatewayId || gatewayKs.isPending}
          className="rounded border border-[#2a2a45] px-2 py-1 text-[11px] text-[#9090b0] hover:text-ask disabled:opacity-40"
        >
          Cancel gateway
        </button>
      </div>

      {/* Global */}
      <div className="flex items-end gap-2 border-t border-[#2a2a45] pt-3">
        <div className="flex flex-col">
          <span className="text-[10px] text-ask">Global (all gateways)</span>
          <span className="text-[10px] text-[#505070]">Full-market emergency stop.</span>
        </div>
        <button
          type="button"
          onClick={() => setConfirmGlobal(true)}
          disabled={globalKs.isPending}
          className="ml-auto rounded bg-ask px-3 py-1 text-[11px] font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          Kill all
        </button>
      </div>

      {confirmSymbol && (
        <CancelConfirm
          title="Kill switch — symbol?"
          message={`Cancel all resting orders and quotes for ${symbol.trim().toUpperCase()} across every gateway?`}
          confirmLabel="Cancel symbol"
          busy={symbolKs.isPending}
          onConfirm={runSymbol}
          onClose={() => setConfirmSymbol(false)}
        />
      )}

      {confirmGateway && (
        <CancelConfirm
          title="Kill switch — gateway?"
          message={`Cancel all resting orders and quotes belonging to ${gatewayId}? The gateway stays connected and may re-submit.`}
          confirmLabel="Cancel gateway"
          busy={gatewayKs.isPending}
          onConfirm={runGateway}
          onClose={() => setConfirmGateway(false)}
        />
      )}

      {confirmGlobal && (
        <ConfirmTypedDialog
          title="Global kill switch?"
          message="Cancel every resting order and quote for every gateway. This is a full-market emergency stop and affects all participants."
          confirmLabel="Execute global kill"
          busy={globalKs.isPending}
          onConfirm={runGlobal}
          onClose={() => setConfirmGlobal(false)}
        />
      )}
    </section>
  );
}

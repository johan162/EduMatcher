import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { useAdminGatewaysQuery, useDisconnectGatewayMutation } from "@/queries/index.js";
import { CancelConfirm } from "@/components/orders/CancelConfirm.js";
import { KillSwitchPanel } from "@/components/admin/KillSwitchPanel.js";
import { ApiError } from "@/api/apiFetch.js";
import type { AdminGateway } from "@/types/index.js";

/**
 * Gateway Management (§15.7) — the roster from `GET /admin/gateways` with a
 * live connection dot and a Kick action, plus the admin Kill Switch panel
 * (§15.8). Kick disconnects a gateway (the engine cancels its orders/quotes as
 * a side effect, FR-MMQ-006) and always confirms.
 */
export function AdminGatewaysPage() {
  const gatewaysQuery = useAdminGatewaysQuery();
  const disconnect = useDisconnectGatewayMutation();
  const [kickTarget, setKickTarget] = useState<AdminGateway | null>(null);

  const gateways = gatewaysQuery.data?.gateways ?? [];

  const doKick = (id: string) => {
    disconnect.mutate(
      { id },
      {
        onSuccess: () => toast.success(`Gateway ${id} disconnected`),
        onError: (err) =>
          toast.error(err instanceof ApiError ? `${err.code}: ${err.message}` : "Disconnect failed"),
      },
    );
    setKickTarget(null);
  };

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-[#e8e8f0]">Gateway Management</h1>
        <span className="text-[11px] text-[#505070]">
          {gateways.filter((g) => g.connected).length} / {gateways.length} connected
        </span>
        <button
          type="button"
          onClick={() => void gatewaysQuery.refetch()}
          className="ml-auto flex items-center gap-1 rounded border border-[#2a2a45] px-2 py-1 text-xs text-[#9090b0] hover:text-[#e8e8f0]"
        >
          <RefreshCw size={12} className={gatewaysQuery.isFetching ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {gatewaysQuery.isError && (
        <p className="text-xs text-ask">Could not load the gateway roster.</p>
      )}

      <div className="overflow-auto rounded border border-[#2a2a45]">
        <table className="w-full border-collapse text-xs">
          <thead className="bg-[#12121a] text-[#9090b0]">
            <tr>
              <th className="px-2 py-1.5 text-left font-medium">Gateway ID</th>
              <th className="px-2 py-1.5 text-left font-medium">Role</th>
              <th className="px-2 py-1.5 text-left font-medium">Description</th>
              <th className="px-2 py-1.5 text-left font-medium">Connected</th>
              <th className="px-2 py-1.5 text-right font-medium">Action</th>
            </tr>
          </thead>
          <tbody>
            {gateways.map((g) => (
              <tr key={g.id} className="border-b border-[#1a1a28]">
                <td className="px-2 py-1 font-mono font-medium">{g.id}</td>
                <td className="px-2 py-1 text-[#9090b0]">{g.role}</td>
                <td className="px-2 py-1 text-[#9090b0]">{g.description || "—"}</td>
                <td className="px-2 py-1">
                  <span className={`inline-flex items-center gap-1 ${g.connected ? "text-emerald-400" : "text-[#505070]"}`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${g.connected ? "bg-emerald-400" : "bg-[#505070]"}`} />
                    {g.connected ? "Connected" : "Offline"}
                  </span>
                </td>
                <td className="px-2 py-1 text-right">
                  <button
                    type="button"
                    onClick={() => setKickTarget(g)}
                    disabled={!g.connected || disconnect.isPending}
                    aria-label={`Kick gateway ${g.id}`}
                    className="rounded border border-[#2a2a45] px-2 py-0.5 text-[11px] text-[#9090b0] hover:text-ask disabled:opacity-30"
                  >
                    Kick
                  </button>
                </td>
              </tr>
            ))}
            {gateways.length === 0 && !gatewaysQuery.isLoading && (
              <tr>
                <td colSpan={5} className="px-2 py-6 text-center text-[#505070]">
                  No gateways configured.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <KillSwitchPanel gateways={gateways} />

      {kickTarget && (
        <CancelConfirm
          title="Disconnect gateway?"
          message={`Disconnect gateway ${kickTarget.id}? This will cancel all their active orders and quotes.`}
          confirmLabel="Disconnect"
          busy={disconnect.isPending}
          onConfirm={() => doKick(kickTarget.id)}
          onClose={() => setKickTarget(null)}
        />
      )}
    </div>
  );
}

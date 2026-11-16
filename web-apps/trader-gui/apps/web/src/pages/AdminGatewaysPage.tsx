import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { useAdminGatewaysQuery, useDisconnectGatewayMutation } from "@/queries/index.js";
import { CancelConfirm } from "@/components/orders/CancelConfirm.js";
import { KillSwitchPanel } from "@/components/admin/KillSwitchPanel.js";
import { ApiError } from "@/api/apiFetch.js";
import type { AdminGateway } from "@/types/index.js";
import { GatewayDrawer } from "@/components/admin/GatewayDrawer.js";
import { HeaderTip } from "@/components/shared/HeaderTip.js";
import { formatNsTimestamp } from "@/lib/formatters.js";
import { PAGE_SIZES, usePrefsStore } from "@/store/usePrefsStore.js";

const fieldCls = "rounded border border-line bg-raised px-2 py-0.5 text-xs";
const pageBtnCls = "rounded p-1 text-fg-dim hover:bg-raised hover:text-fg disabled:opacity-40";

/**
 * Gateway Management (§15.7) — the roster from `GET /admin/gateways` with a
 * live connection dot and a Kill action, with the admin Mass Cancel panel
 * (§15.8) above it. Kill disconnects a gateway (the engine cancels its orders/quotes as
 * a side effect, FR-MMQ-006) and always confirms.
 */
export function AdminGatewaysPage() {
  const gatewaysQuery = useAdminGatewaysQuery();
  const disconnect = useDisconnectGatewayMutation();
  const [kickTarget, setKickTarget] = useState<AdminGateway | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const gateways = gatewaysQuery.data?.gateways ?? [];
  const selected = gateways.find((g) => g.id === selectedId) ?? null;

  const [role, setRole] = useState("");
  const [search, setSearch] = useState("");
  const pageSize = usePrefsStore((s) => s.participantsPageSize);
  const setPageSize = usePrefsStore((s) => s.setParticipantsPageSize);
  const [requestedPage, setRequestedPage] = useState(0);
  const roles = useMemo<string[]>(() => [...new Set(gateways.map((g) => g.role))].sort(), [gateways]);
  // A role nobody holds any more filters nothing rather than everything out.
  const activeRole = roles.includes(role) ? role : "";
  // The search and the role cover every participant, not just the page on show.
  const shown = useMemo(() => {
    const needle = search.trim().toUpperCase();
    return gateways.filter((g) => (!activeRole || g.role === activeRole) && (!needle || g.id.toUpperCase().includes(needle)));
  }, [gateways, activeRole, search]);
  // The requested page is held inside the page count: rows come and go under a viewer.
  const pageCount = pageSize ? Math.max(1, Math.ceil(shown.length / pageSize)) : 1;
  const pageIndex = Math.min(requestedPage, pageCount - 1);
  const pageRows = pageSize ? shown.slice(pageIndex * pageSize, (pageIndex + 1) * pageSize) : shown;

  const doKick = (id: string) => {
    disconnect.mutate(
      { id },
      {
        onSuccess: () => toast.success(`Participant ${id} disconnected`),
        onError: (err) =>
          toast.error(err instanceof ApiError ? `${err.code}: ${err.message}` : "Disconnect failed"),
      },
    );
    setKickTarget(null);
  };

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-fg">Participants</h1>
        <span className="text-[11px] text-fg-faint">
          {gateways.filter((g) => g.connected).length} / {gateways.length} connected
        </span>
        <button
          type="button"
          onClick={() => void gatewaysQuery.refetch()}
          className="ml-auto flex items-center gap-1 rounded border border-line px-2 py-1 text-xs text-fg-dim hover:text-fg"
        >
          <RefreshCw size={12} className={gatewaysQuery.isFetching ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {gatewaysQuery.isError && (
        <p className="text-xs text-ask">Could not load the participant roster.</p>
      )}

      <KillSwitchPanel gateways={gateways} />

      <div className="flex flex-wrap items-center gap-3 text-xs">
        <input
          type="search"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setRequestedPage(0);
          }}
          placeholder="Find ID"
          aria-label="Find ID"
          className={`${fieldCls} w-28 placeholder:text-fg-faint`}
        />
        <select
          value={activeRole}
          onChange={(e) => {
            setRole(e.target.value);
            setRequestedPage(0);
          }}
          aria-label="Filter by role"
          className={`${fieldCls} text-fg-dim`}
        >
          <option value="">All roles</option>
          {roles.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <span className="tabular-nums text-fg-dim">
          {shown.length} participant{shown.length === 1 ? "" : "s"}
          {shown.length !== gateways.length && ` of ${gateways.length}`}
        </span>
        <div className="ml-auto flex items-center gap-3">
          <span className="tabular-nums text-fg-dim">
            Page {pageIndex + 1}/{pageCount}
          </span>
          <button
            type="button"
            disabled={pageIndex === 0}
            onClick={() => setRequestedPage(pageIndex - 1)}
            aria-label="Previous page"
            className={pageBtnCls}
          >
            <ChevronLeft size={14} />
          </button>
          <button
            type="button"
            disabled={pageIndex >= pageCount - 1}
            onClick={() => setRequestedPage(pageIndex + 1)}
            aria-label="Next page"
            className={pageBtnCls}
          >
            <ChevronRight size={14} />
          </button>
          <select
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value));
              setRequestedPage(0);
            }}
            aria-label="Rows per page"
            className={`${fieldCls} text-fg-dim`}
          >
            {PAGE_SIZES.map((n) => (
              <option key={n} value={n}>
                {n ? `${n} rows` : "All rows"}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="overflow-auto rounded border border-line">
        <table className="w-full border-collapse text-xs">
          <thead className="bg-panel text-fg-dim">
            <tr>
              <th className="px-2 py-1.5 text-left font-medium">Participant ID <HeaderTip table="admin-gateways" col="Participant ID" /></th>
              <th className="px-2 py-1.5 text-left font-medium">Role <HeaderTip table="admin-gateways" col="Role" /></th>
              <th className="px-2 py-1.5 text-left font-medium">Description <HeaderTip table="admin-gateways" col="Description" /></th>
              <th className="px-2 py-1.5 text-left font-medium">Connected <HeaderTip table="admin-gateways" col="Connected" /></th>
              <th className="px-2 py-1.5 text-left font-medium">Connected since <HeaderTip table="admin-gateways" col="Connected since" /></th>
              <th className="px-2 py-1.5 text-right font-medium">Action <HeaderTip table="admin-gateways" col="Action" /></th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((g) => (
              <tr
                key={g.id}
                onClick={() => setSelectedId(g.id)}
                aria-selected={g.id === selectedId}
                className={`cursor-pointer border-b border-raised hover:bg-raised ${g.id === selectedId ? "bg-raised" : ""}`}
              >
                <td className="px-2 py-1 font-mono font-medium">{g.id}</td>
                <td className="px-2 py-1 text-fg-dim">{g.role}</td>
                <td className="px-2 py-1 text-fg-dim">{g.description || "—"}</td>
                <td className="px-2 py-1">
                  <span className={`inline-flex items-center gap-1 ${g.connected ? "text-emerald-400" : "text-fg-faint"}`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${g.connected ? "bg-emerald-400" : "bg-fg-faint"}`} />
                    {g.connected ? "Connected" : "Offline"}
                  </span>
                </td>
                <td className="px-2 py-1 font-mono tabular-nums text-fg-dim">{formatNsTimestamp(g.connected_since_ns)}</td>
                <td className="px-2 py-1 text-right">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setKickTarget(g);
                    }}
                    disabled={!g.connected || disconnect.isPending}
                    aria-label={`Kill participant ${g.id}`}
                    className="rounded border-2 border-ask px-2 py-0.5 text-[11px] font-bold text-ask hover:bg-ask hover:text-white disabled:opacity-30"
                  >
                    Kill
                  </button>
                </td>
              </tr>
            ))}
            {gateways.length === 0 && !gatewaysQuery.isLoading && (
              <tr>
                <td colSpan={6} className="px-2 py-6 text-center text-fg-faint">
                  No participants configured.
                </td>
              </tr>
            )}
            {gateways.length > 0 && shown.length === 0 && (
              <tr>
                <td colSpan={6} className="px-2 py-6 text-center text-fg-faint">
                  No participants match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {selected && (
        <GatewayDrawer gateway={selected} onKick={setKickTarget} onClose={() => setSelectedId(null)} />
      )}

      {kickTarget && (
        <CancelConfirm
          title="Disconnect participant?"
          message={`Disconnect participant ${kickTarget.id}? This will cancel all their active orders and quotes.`}
          confirmLabel="Disconnect"
          busy={disconnect.isPending}
          onConfirm={() => doKick(kickTarget.id)}
          onClose={() => setKickTarget(null)}
        />
      )}
    </div>
  );
}

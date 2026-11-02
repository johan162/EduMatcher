import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { useShallow } from "zustand/react/shallow";
import { useMonitorStore } from "@/store/useMonitorStore.js";
import { isTerminalStatus } from "@/lib/monitorEvents.js";
import { MonitorKindBadge } from "@/components/admin/MonitorKindBadge.js";
import { AdminOrderDetailModal } from "@/components/admin/AdminOrderDetailModal.js";
import type { AdminGateway } from "@/types/index.js";

const LIST_ROWS = 50;

interface GatewayDrawerProps {
  gateway: AdminGateway;
  onKick: (g: AdminGateway) => void;
  onClose: () => void;
}

/**
 * Right-side detail drawer for one gateway (counterpart of pm-dash's
 * participant drawer). Not modal: the roster behind it stays clickable, which
 * swaps the drawer's subject. Figures come from the admin monitor stream
 * (useMonitorStore), so they are live without any extra request. Escape or the
 * close button closes it.
 */
export function GatewayDrawer({ gateway, onKick, onClose }: GatewayDrawerProps) {
  const id = gateway.id;
  const heading = useRef<HTMLHeadingElement>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const orders = useMonitorStore(
    useShallow((s) => Object.values(s.orders).filter((o) => o.gateway_id === id)),
  );
  const events = useMonitorStore(
    useShallow((s) => s.events.filter((e) => e.gateway_id === id).slice(0, LIST_ROWS)),
  );
  useEffect(() => heading.current?.focus(), [id]);

  const working = orders.filter((o) => !isTerminalStatus(o.status));
  const fills = orders.filter((o) => (o.fill_qty ?? 0) > 0).length;
  const rejected = orders.filter((o) => o.status.toUpperCase() === "REJECTED").length;

  const facts: [string, string][] = [
    ["Role", gateway.role],
    ["Description", gateway.description || "—"],
    ["Working orders", String(working.length)],
    ["Tracked orders", String(orders.length)],
    ["With fills", String(fills)],
    ["Rejected", String(rejected)],
  ];

  return (
    <aside
      role="dialog"
      aria-modal="false"
      aria-label={`Participant ${id}`}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
      className="fixed bottom-0 right-0 top-10 z-30 flex w-full max-w-[32rem] flex-col border-l border-line bg-panel shadow-2xl"
    >
      <header className="flex items-start gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-fg-faint">Participant</p>
          <h2 ref={heading} tabIndex={-1} className="truncate font-mono text-base font-semibold text-fg focus:outline-none">
            {id}
          </h2>
          <span className={`inline-flex items-center gap-1 text-xs ${gateway.connected ? "text-emerald-400" : "text-fg-faint"}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${gateway.connected ? "bg-emerald-400" : "bg-fg-faint"}`} />
            {gateway.connected ? "Connected" : "Offline"}
          </span>
        </div>
        <button
          type="button"
          onClick={() => onKick(gateway)}
          disabled={!gateway.connected}
          aria-label={`Kick participant ${id} from drawer`}
          className="rounded border border-line px-2 py-0.5 text-[11px] text-fg-dim hover:text-ask disabled:opacity-30"
        >
          Kick
        </button>
        <button type="button" aria-label="Close" onClick={onClose} className="rounded p-1 text-fg-dim hover:text-fg">
          <X size={16} aria-hidden="true" />
        </button>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-4">
        <dl aria-label="Participant figures" className="m-0 grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-3">
          {facts.map(([name, value]) => (
            <div key={name} className="min-w-0">
              <dt className="truncate text-[11px] uppercase tracking-wide text-fg-faint">{name}</dt>
              <dd className="m-0 truncate text-fg">{value}</dd>
            </div>
          ))}
        </dl>

        <section aria-label="Working orders" className="flex flex-col gap-1">
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-fg-dim">Working orders</h3>
          <div className="max-h-60 overflow-auto rounded border border-line">
            {working.length === 0 ? (
              <p className="p-4 text-center text-xs text-fg-faint">No working orders.</p>
            ) : (
              <table className="w-full border-collapse text-xs">
                <tbody>
                  {working.slice(0, LIST_ROWS).map((o) => (
                    <tr
                      key={o.order_id}
                      onClick={() => setDetailId(o.order_id)}
                      className="cursor-pointer border-b border-raised hover:bg-raised"
                    >
                      <td className="px-2 py-1 font-mono">{o.symbol ?? "—"}</td>
                      <td className="px-2 py-1 text-fg-dim">{o.side ?? "—"}</td>
                      <td className="px-2 py-1 text-right tabular-nums">{o.price ?? "—"}</td>
                      <td className="px-2 py-1 text-right tabular-nums">{o.remaining_qty ?? o.quantity ?? "—"}</td>
                      <td className="px-2 py-1 text-fg-dim">{o.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>

        <section aria-label="Participant events" className="flex flex-col gap-1">
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-fg-dim">Recent events</h3>
          <div className="max-h-72 overflow-auto rounded border border-line">
            {events.length === 0 ? (
              <p className="p-4 text-center text-xs text-fg-faint">No activity yet.</p>
            ) : (
              <ol className="flex flex-col">
                {events.map((e) => (
                  <li
                    key={e.id}
                    onClick={e.order_id ? () => setDetailId(e.order_id) : undefined}
                    className={`flex items-center gap-2 border-b border-raised px-2 py-1 ${e.order_id ? "cursor-pointer hover:bg-raised" : ""}`}
                  >
                    <MonitorKindBadge kind={e.kind} />
                    {e.symbol && <span className="font-mono text-[11px]">{e.symbol}</span>}
                    <span className="flex-1 truncate text-[11px] text-fg-dim">{e.detail}</span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </section>
      </div>

      {detailId && <AdminOrderDetailModal orderId={detailId} onClose={() => setDetailId(null)} />}
    </aside>
  );
}

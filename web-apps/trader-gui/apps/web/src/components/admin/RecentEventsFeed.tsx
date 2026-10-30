import { useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { useMonitorStore } from "@/store/useMonitorStore.js";
import { MonitorKindBadge } from "@/components/admin/MonitorKindBadge.js";
import { AdminOrderDetailModal } from "@/components/admin/AdminOrderDetailModal.js";

const FEED_ROWS = 15;

/**
 * Recent events feed (§15.1.3). Its own component so the live event stream
 * re-renders only these rows, not the whole System Dashboard.
 */
export function RecentEventsFeed() {
  const events = useMonitorStore(useShallow((s) => s.events.slice(0, FEED_ROWS)));
  const [detailId, setDetailId] = useState<string | null>(null);

  return (
    <section aria-label="Recent events" className="flex flex-col gap-1">
      <h2 className="text-[11px] font-semibold uppercase tracking-wide text-fg-dim">
        Recent Events
      </h2>
      <div className="overflow-auto rounded border border-line">
        {events.length === 0 ? (
          <p className="p-6 text-center text-xs text-fg-faint">No cross-gateway activity yet.</p>
        ) : (
          <ol className="flex flex-col">
            {events.map((e) => {
              const linkable = Boolean(e.order_id);
              return (
                <li
                  key={e.id}
                  onClick={linkable ? () => setDetailId(e.order_id!) : undefined}
                  className={`flex items-center gap-2 border-b border-raised px-2 py-1 ${
                    linkable ? "cursor-pointer hover:bg-raised" : ""
                  }`}
                >
                  <MonitorKindBadge kind={e.kind} />
                  {e.symbol && <span className="font-mono text-[11px]">{e.symbol}</span>}
                  <span className="flex-1 truncate text-[11px] text-fg-dim">{e.detail}</span>
                </li>
              );
            })}
          </ol>
        )}
      </div>

      {detailId && <AdminOrderDetailModal orderId={detailId} onClose={() => setDetailId(null)} />}
    </section>
  );
}

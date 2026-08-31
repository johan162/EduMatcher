import { useState } from "react";
import { X } from "lucide-react";
import { useWsEvent } from "@/hooks/useWsEvent.js";
import { useOrderHistoryQuery } from "@/queries/index.js";
import { useOrderStore } from "@/store/useOrderStore.js";
import { ApiError } from "@/api/apiFetch.js";
import { StatusPill } from "./StatusPill.js";
import type { OrderHistoryEvent } from "@/types/index.js";

interface OrderDetailDrawerProps {
  /** The drawer is remounted per id by the parent (key), so WS closures are fresh. */
  orderId: string;
  onClose: () => void;
}

/** The subset of an order_events row the timeline renders, plus a live flag. */
type TimelineEntry = Partial<OrderHistoryEvent> & {
  event_type: string;
  ts: string;
  live?: boolean;
};

const EVENT_COLOR: Record<string, string> = {
  ACK: "bg-blue-600",
  REJECT: "bg-red-600",
  FILL: "bg-emerald-600",
  AMEND: "bg-amber-500 text-black",
  CANCEL: "bg-slate-500",
  EXPIRE: "bg-slate-400 text-black",
};

function timeLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
}

/** One human-readable detail line for a timeline entry. */
function detailLine(e: TimelineEntry): string {
  const parts: string[] = [];
  if (e.event_type === "FILL") {
    if (e.fill_qty != null) parts.push(`${e.fill_qty} @ ${e.fill_price ?? "—"}`);
    if (e.remaining_qty != null) parts.push(`${e.remaining_qty} left`);
  } else if (e.event_type === "AMEND") {
    if (e.price != null) parts.push(`price ${e.price}`);
    if (e.quantity != null) parts.push(`qty ${e.quantity}`);
    if (e.remaining_qty != null) parts.push(`${e.remaining_qty} left`);
    if (e.priority_reset) parts.push("priority reset");
  } else {
    if (e.price != null) parts.push(`price ${e.price}`);
    if (e.quantity != null) parts.push(`qty ${e.quantity}`);
  }
  if (e.reason) parts.push(e.reason);
  return parts.join(" · ");
}

/**
 * Order Detail drawer (§13.4) — the full chronological lifecycle of one order.
 * Seeded from `GET /history/orders/{id}` (durable stats.db events) and kept
 * current by appending live `order.*` events for this id, so it stays accurate
 * even when the history endpoint lags the live stream.
 */
export function OrderDetailDrawer({ orderId, onClose }: OrderDetailDrawerProps) {
  const historyQuery = useOrderHistoryQuery(orderId);
  const order = useOrderStore((s) => s.orders[orderId]);
  const [liveEntries, setLiveEntries] = useState<TimelineEntry[]>([]);

  const append = (e: TimelineEntry) => setLiveEntries((prev) => [...prev, e]);
  const nowIso = () => new Date().toISOString();

  useWsEvent("order.ack", (env) => {
    if (env.data.order_id !== orderId) return;
    append({
      event_type: env.data.accepted ? "ACK" : "REJECT",
      ts: nowIso(),
      reason: env.data.reason || null,
      price: env.data.price ?? null,
      quantity: env.data.qty ?? null,
      live: true,
    });
  });
  useWsEvent("order.fill", (env) => {
    if (env.data.order_id !== orderId) return;
    append({
      event_type: "FILL",
      ts: nowIso(),
      fill_qty: env.data.fill_qty,
      fill_price: env.data.fill_price,
      remaining_qty: env.data.remaining_qty,
      live: true,
    });
  });
  useWsEvent("order.amended", (env) => {
    if (env.data.order_id !== orderId) return;
    append({
      event_type: "AMEND",
      ts: nowIso(),
      price: env.data.price ?? null,
      quantity: env.data.qty,
      remaining_qty: env.data.remaining_qty,
      priority_reset: env.data.priority_reset ? 1 : 0,
      live: true,
    });
  });
  useWsEvent("order.cancelled", (env) => {
    if (env.data.order_id === orderId) append({ event_type: "CANCEL", ts: nowIso(), live: true });
  });
  useWsEvent("order.expired", (env) => {
    if (env.data.order_id === orderId) append({ event_type: "EXPIRE", ts: nowIso(), live: true });
  });

  const historyEntries: TimelineEntry[] = (historyQuery.data?.events ?? []).map((e) => ({ ...e }));
  const entries = [...historyEntries, ...liveEntries];

  const is503 = historyQuery.error instanceof ApiError && historyQuery.error.status === 503;

  return (
    <aside
      role="dialog"
      aria-label={`Order ${orderId} detail`}
      className="fixed right-0 top-10 bottom-0 w-[520px] max-w-[92vw] bg-[#0d0d14] border-l border-[#2a2a45] shadow-2xl z-40 flex flex-col animate-fade-in"
    >
      <div className="flex items-start justify-between px-4 pt-3 pb-2 border-b border-[#2a2a45]">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-mono font-semibold text-[#e8e8f0]">
              {order?.symbol ?? "Order"} · {orderId.slice(0, 8)}
            </h2>
            {order && <StatusPill status={order.status} />}
          </div>
          {order && (
            <div className="mt-1 text-[11px] text-[#9090b0]">
              <span className={order.side === "BUY" ? "text-bid" : "text-ask"}>{order.side}</span>{" "}
              {order.order_type} · {order.tif} · qty {order.quantity}
              {order.client_tag ? ` · tag ${order.client_tag}` : ""}
              {order.oco_group_id ? ` · OCO ${order.oco_group_id}` : ""}
              {order.combo_parent_id ? ` · combo ${order.combo_parent_id}` : ""}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close order detail"
          className="text-[#9090b0] hover:text-[#e8e8f0]"
        >
          <X size={18} />
        </button>
      </div>

      <div className="flex-1 overflow-auto p-4">
        <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[#707090]">
          Lifecycle
        </h3>

        {historyQuery.isLoading && <p className="text-xs text-[#9090b0]">Loading history…</p>}

        {is503 && (
          <p className="text-xs text-[#9090b0]">
            History unavailable — the stats database is not running. Live events below still update.
          </p>
        )}

        {!historyQuery.isLoading && !is503 && entries.length === 0 && (
          <p className="text-xs text-[#9090b0]">No recorded events yet.</p>
        )}

        <ol className="flex flex-col gap-2">
          {entries.map((e, i) => (
            <li key={`${e.seq ?? "live"}-${i}`} className="flex items-start gap-2">
              <span
                className={`mt-0.5 inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold text-white ${
                  EVENT_COLOR[e.event_type] ?? "bg-slate-600"
                }`}
              >
                {e.event_type}
              </span>
              <div className="flex flex-col">
                <span className="font-mono text-[11px] text-[#e8e8f0]">
                  {timeLabel(e.ts)}
                  {e.live && <span className="ml-1 text-[9px] text-[#6ea8fe]">live</span>}
                </span>
                {detailLine(e) && (
                  <span className="text-[11px] text-[#9090b0]">{detailLine(e)}</span>
                )}
              </div>
            </li>
          ))}
        </ol>
      </div>
    </aside>
  );
}

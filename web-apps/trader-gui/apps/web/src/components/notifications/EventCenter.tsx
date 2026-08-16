import { useEffect, useMemo, useState } from "react";
import { X, ArrowUpRight } from "lucide-react";
import { useNotificationStore, type NotificationKind } from "@/store/useNotificationStore.js";
import { useUiStore } from "@/store/useUiStore.js";

/** Kind → badge colour + short label (§20.2). */
const KIND_META: Record<NotificationKind, { cls: string; label: string }> = {
  ACK: { cls: "bg-blue-600", label: "ACK" },
  FILL: { cls: "bg-emerald-600", label: "FILL" },
  REJECT: { cls: "bg-red-600", label: "REJECT" },
  CANCEL: { cls: "bg-slate-500", label: "CANCEL" },
  CB: { cls: "bg-amber-500 text-black", label: "CB" },
  SESSION: { cls: "bg-violet-600", label: "SESSION" },
  SYSTEM: { cls: "bg-slate-600", label: "SYSTEM" },
};

const ALL_KINDS = Object.keys(KIND_META) as NotificationKind[];

function timeLabel(ms: number): string {
  return new Date(ms).toLocaleTimeString("en-GB", { hour12: false });
}

/**
 * Notification / Event Center (§20.2) — a right-edge sheet listing the durable
 * session history of acks, fills, rejects, cancels, CB and session events.
 * Opening it marks everything read; fill/reject entries deep-link to the Order
 * Detail drawer. Rendered once in the AppShell, gated on `useUiStore`.
 */
export function EventCenter() {
  const entries = useNotificationStore((s) => s.entries);
  const markAllRead = useNotificationStore((s) => s.markAllRead);
  const clear = useNotificationStore((s) => s.clear);
  const close = useUiStore((s) => s.closeEventCenter);
  const openOrderDetail = useUiStore((s) => s.openOrderDetail);

  const [filter, setFilter] = useState<NotificationKind | "ALL">("ALL");

  // Opening the panel clears the unread badge (§20.2).
  useEffect(() => {
    markAllRead();
  }, [markAllRead]);

  // Escape closes the sheet.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  // Only offer filters for kinds actually present, plus the active one.
  const availableKinds = useMemo(() => {
    const present = new Set(entries.map((e) => e.kind));
    return ALL_KINDS.filter((k) => present.has(k) || k === filter);
  }, [entries, filter]);

  const shown = filter === "ALL" ? entries : entries.filter((e) => e.kind === filter);

  const filterBtn = (value: NotificationKind | "ALL", label: string) => (
    <button
      key={value}
      type="button"
      onClick={() => setFilter(value)}
      aria-pressed={filter === value}
      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
        filter === value ? "bg-[#3a3a60] text-white" : "bg-[#1a1a28] text-[#9090b0] hover:text-[#e8e8f0]"
      }`}
    >
      {label}
    </button>
  );

  return (
    <aside
      role="dialog"
      aria-label="Notification and Event Center"
      className="fixed right-0 top-10 bottom-0 w-[420px] max-w-[92vw] bg-[#0d0d14] border-l border-[#2a2a45] shadow-2xl z-40 flex flex-col animate-fade-in"
    >
      <div className="flex items-center justify-between px-4 pt-3 pb-2 border-b border-[#2a2a45]">
        <h2 className="text-sm font-semibold text-[#e8e8f0]">Event Center</h2>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={clear}
            disabled={entries.length === 0}
            className="rounded border border-[#2a2a45] px-2 py-0.5 text-[11px] text-[#9090b0] hover:text-[#e8e8f0] disabled:opacity-40"
          >
            Clear
          </button>
          <button
            type="button"
            onClick={close}
            aria-label="Close Event Center"
            className="text-[#9090b0] hover:text-[#e8e8f0]"
          >
            <X size={18} />
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-1 border-b border-[#2a2a45] px-3 py-2">
        {filterBtn("ALL", "All")}
        {availableKinds.map((k) => filterBtn(k, KIND_META[k].label))}
      </div>

      <div className="flex-1 overflow-auto p-2">
        {shown.length === 0 ? (
          <p className="p-6 text-center text-xs text-[#505070]">
            {entries.length === 0 ? "No events yet this session." : "No events match this filter."}
          </p>
        ) : (
          <ol className="flex flex-col gap-1">
            {shown.map((e) => {
              const meta = KIND_META[e.kind];
              const linkable = Boolean(e.orderId);
              return (
                <li
                  key={e.id}
                  className={`rounded border border-[#1a1a28] p-2 ${
                    linkable ? "cursor-pointer hover:bg-[#1a1a28]" : ""
                  }`}
                  onClick={linkable ? () => openOrderDetail(e.orderId!) : undefined}
                >
                  <div className="flex items-center gap-2">
                    <span className={`rounded px-1.5 py-0.5 text-[9px] font-semibold text-white ${meta.cls}`}>
                      {meta.label}
                    </span>
                    <span className="font-mono text-[10px] text-[#505070]">{timeLabel(e.ts)}</span>
                    <span className="flex-1 truncate text-[11px] font-medium text-[#e8e8f0]">
                      {e.title}
                    </span>
                    {linkable && <ArrowUpRight size={12} className="text-[#6ea8fe]" />}
                  </div>
                  {e.detail && <div className="mt-0.5 text-[11px] text-[#9090b0]">{e.detail}</div>}
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </aside>
  );
}

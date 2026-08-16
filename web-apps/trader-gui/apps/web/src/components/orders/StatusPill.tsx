import type { OrderStatus } from "@/types/index.js";

/** Status → pill colour (§13.1.2). PENDING is a local, not-yet-acked state. */
const PILL: Record<OrderStatus, string> = {
  NEW: "bg-blue-600",
  PARTIAL: "bg-amber-500 text-black",
  FILLED: "bg-emerald-600",
  CANCELLED: "bg-slate-500",
  REJECTED: "bg-red-600",
  EXPIRED: "bg-slate-400 text-black",
  PENDING: "bg-slate-600",
};

export function StatusPill({ status }: { status: OrderStatus }) {
  return (
    <span
      className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold text-white ${PILL[status]}`}
    >
      {status}
    </span>
  );
}

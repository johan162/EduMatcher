import type { MonitorEventKind } from "@/types/index.js";

const KIND_CLS: Record<MonitorEventKind, string> = {
  ACK: "bg-blue-600 text-white",
  FILL: "bg-emerald-600 text-white",
  REJECT: "bg-red-600 text-white",
  CANCEL: "bg-slate-500 text-white",
  AMEND: "bg-amber-500 text-black",
  EXPIRE: "bg-slate-400 text-black",
  SESSION: "bg-violet-600 text-white",
  CB: "bg-amber-500 text-black",
  ADMIN: "bg-fuchsia-700 text-white",
  GAP: "bg-red-900 text-red-200",
};

/** Small coloured badge for a monitor event kind (§15.1.3, §15.9). */
export function MonitorKindBadge({ kind }: { kind: MonitorEventKind }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-[9px] font-semibold ${KIND_CLS[kind]}`}>{kind}</span>
  );
}

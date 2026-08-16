import { computeOrderGroups, type OrderGroup } from "@/lib/orderGroups.js";
import type { Order } from "@/types/index.js";

interface OrderGroupsPanelProps {
  orders: Order[];
  onCancelGroup: (group: OrderGroup) => void;
}

/**
 * Group rows for OCO/combo memberships (§13.3): one row per group with the
 * kind badge, id, member symbols, an aggregate status (e.g. "1 live / 1
 * cancelled"), and a one-click "Cancel group" for the live members. The blotter
 * itself keeps the per-row Group badge; this panel is the parent group view.
 */
export function OrderGroupsPanel({ orders, onCancelGroup }: OrderGroupsPanelProps) {
  const groups = computeOrderGroups(orders);
  if (groups.length === 0) return null;

  return (
    <section aria-label="Order groups" className="flex flex-col gap-1">
      <h2 className="text-[11px] font-semibold uppercase tracking-wide text-[#9090b0]">Groups</h2>
      <div className="overflow-hidden rounded border border-[#2a2a45]">
        <table className="w-full text-xs border-collapse">
          <thead className="bg-[#12121a] text-[#9090b0]">
            <tr>
              <th scope="col" className="px-2 py-1.5 text-left font-medium">Kind</th>
              <th scope="col" className="px-2 py-1.5 text-left font-medium">Group ID</th>
              <th scope="col" className="px-2 py-1.5 text-left font-medium">Symbols</th>
              <th scope="col" className="px-2 py-1.5 text-left font-medium">Status</th>
              <th scope="col" className="px-2 py-1.5" />
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => {
              const symbols = [...new Set(g.members.map((m) => m.symbol))].join(", ");
              const accent = g.kind === "OCO" ? "border-l-2 border-amber-500" : "border-l-2 border-sky-500";
              return (
                <tr key={`${g.kind}:${g.id}`} className={`border-b border-[#1a1a28] ${accent}`}>
                  <td className="px-2 py-1">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-semibold text-white ${
                        g.kind === "OCO" ? "bg-amber-600" : "bg-sky-700"
                      }`}
                    >
                      {g.kind}
                    </span>
                  </td>
                  <td className="px-2 py-1 font-mono text-[#e8e8f0]">{g.id}</td>
                  <td className="px-2 py-1 font-mono text-[#9090b0]">{symbols}</td>
                  <td className="px-2 py-1 text-[#9090b0]">
                    {g.statusLabel}{" "}
                    <span className="text-[#505070]">
                      ({g.live}/{g.total})
                    </span>
                  </td>
                  <td className="px-2 py-1 text-right">
                    <button
                      type="button"
                      onClick={() => onCancelGroup(g)}
                      disabled={g.live === 0}
                      aria-label={`Cancel ${g.kind} group ${g.id}`}
                      title={g.live === 0 ? "No live members to cancel" : "Cancel all live members of this group"}
                      className="rounded border border-[#2a2a45] px-2 py-0.5 text-[11px] text-[#9090b0] hover:text-ask disabled:opacity-30"
                    >
                      Cancel group
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

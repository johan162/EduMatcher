import { isTerminal } from "@/store/useOrderStore.js";
import type { Order, OrderStatus } from "@/types/index.js";

export type OrderGroupKind = "OCO" | "COMBO";

export interface OrderGroup {
  kind: OrderGroupKind;
  /** oco_group_id or combo_parent_id. */
  id: string;
  members: Order[];
  /** Count of non-terminal members. */
  live: number;
  total: number;
  /** Human summary, e.g. "1 live / 1 cancelled" or "PARTIAL". */
  statusLabel: string;
}

/** Order statuses in the order we surface them in a group summary. */
const STATUS_ORDER: OrderStatus[] = [
  "NEW",
  "PARTIAL",
  "PENDING",
  "FILLED",
  "CANCELLED",
  "REJECTED",
  "EXPIRED",
];

function summariseStatuses(members: Order[]): string {
  const counts = new Map<OrderStatus, number>();
  for (const m of members) counts.set(m.status, (counts.get(m.status) ?? 0) + 1);
  const live = members.filter((m) => !isTerminal(m.status)).length;
  const done = members.length - live;
  // A mixed group reads best as "live / done"; a uniform group shows its status.
  if (counts.size === 1) {
    const only = [...counts.keys()][0]!;
    return only.toLowerCase();
  }
  const parts: string[] = [];
  if (live > 0) parts.push(`${live} live`);
  // Break down the terminal members by their status for a precise picture.
  for (const s of STATUS_ORDER) {
    if (!isTerminal(s)) continue;
    const n = counts.get(s);
    if (n) parts.push(`${n} ${s.toLowerCase()}`);
  }
  if (parts.length === 0 && done > 0) parts.push(`${done} done`);
  return parts.join(" / ");
}

/**
 * Group the flat order list into OCO/combo groups for the blotter's group
 * rows/badges (§13.3). Orders with neither an `oco_group_id` nor a
 * `combo_parent_id` are not grouped. OCO takes precedence when an order somehow
 * carries both ids (OCO legs are the tighter relationship).
 */
export function computeOrderGroups(orders: Order[]): OrderGroup[] {
  const groups = new Map<string, OrderGroup>();
  for (const o of orders) {
    let kind: OrderGroupKind | null = null;
    let id: string | null = null;
    if (o.oco_group_id) {
      kind = "OCO";
      id = o.oco_group_id;
    } else if (o.combo_parent_id) {
      kind = "COMBO";
      id = o.combo_parent_id;
    }
    if (!kind || !id) continue;
    const key = `${kind}:${id}`;
    const existing = groups.get(key);
    if (existing) existing.members.push(o);
    else groups.set(key, { kind, id, members: [o], live: 0, total: 0, statusLabel: "" });
  }
  const result: OrderGroup[] = [];
  for (const g of groups.values()) {
    g.total = g.members.length;
    g.live = g.members.filter((m) => !isTerminal(m.status)).length;
    g.statusLabel = summariseStatuses(g.members);
    result.push(g);
  }
  // Stable, readable order: OCO first, then by id.
  result.sort((a, b) => (a.kind === b.kind ? a.id.localeCompare(b.id) : a.kind === "OCO" ? -1 : 1));
  return result;
}

import type { MonitorEvent, MonitorEventKind, WsEnvelope } from "@/types/index.js";

/** Order statuses that mean the order is done (mirrors the gateway cache). */
const TERMINAL = new Set(["FILLED", "CANCELLED", "EXPIRED", "REJECTED"]);

export function isTerminalStatus(status: string | undefined | null): boolean {
  return status != null && TERMINAL.has(status.toUpperCase());
}

function str(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 ? v : null;
}
function numOrDash(v: unknown): string {
  return typeof v === "number" ? String(v) : "—";
}

/** The classification of one admin-monitor envelope for the log/orders view. */
export interface MonitorClassification {
  kind: MonitorEventKind;
  order_id: string | null;
  gateway_id: string | null;
  symbol: string | null;
  detail: string;
  /** New order status to fold into the cross-gateway orders map, or null. */
  orderStatus: string | null;
}

/**
 * Classify one admin-monitor envelope (§6.9). The admin feed forwards the SAME
 * uniform envelopes as the other sockets, so the kind is derived from the
 * envelope `type` (and `topic` for the circuit-breaker halt/resume split), NOT
 * from any `data.event_type`. Returns null for envelopes that are not worth a
 * log row (book/depth/trade/auction/quote/mass_cancel/control frames).
 */
export function classifyMonitorEnvelope(env: WsEnvelope<unknown>): MonitorClassification | null {
  const d = (env.data ?? {}) as Record<string, unknown>;
  const envGateway = str(env.gateway_id);

  switch (env.type) {
    case "order.ack": {
      const accepted = Boolean(d.accepted);
      const symbol = str(d.symbol);
      const rejectCode = str(d.reject_code);
      const reason = str(d.reason);
      const detail = accepted
        ? [str(d.side), numOrDash(d.qty ?? d.quantity), symbol]
            .filter((p) => p && p !== "—")
            .join(" ") + (typeof d.price === "number" ? ` @ ${d.price}` : "")
        : [rejectCode, reason].filter(Boolean).join(" — ") || "rejected";
      return {
        kind: accepted ? "ACK" : "REJECT",
        order_id: str(d.order_id),
        gateway_id: envGateway,
        symbol,
        detail: detail || (accepted ? "accepted" : "rejected"),
        orderStatus: accepted ? "NEW" : "REJECTED",
      };
    }
    case "order.fill": {
      const detail =
        `${numOrDash(d.fill_qty)} @ ${numOrDash(d.fill_price)}` +
        (typeof d.remaining_qty === "number" ? ` · ${d.remaining_qty} left` : "");
      return {
        kind: "FILL",
        order_id: str(d.order_id),
        gateway_id: envGateway,
        symbol: str(d.symbol),
        detail,
        orderStatus: str(d.status) ?? "PARTIAL",
      };
    }
    case "order.amended": {
      const parts: string[] = [];
      if (typeof d.price === "number") parts.push(`price ${d.price}`);
      if (typeof d.qty === "number") parts.push(`qty ${d.qty}`);
      if (d.priority_reset) parts.push("priority reset");
      return {
        kind: "AMEND",
        order_id: str(d.order_id),
        gateway_id: envGateway,
        symbol: str(d.symbol),
        detail: parts.join(" · "),
        orderStatus: "AMENDED",
      };
    }
    case "order.cancelled":
      return {
        kind: "CANCEL",
        order_id: str(d.order_id),
        gateway_id: envGateway,
        symbol: str(d.symbol),
        detail: str(d.reason) ?? "",
        orderStatus: "CANCELLED",
      };
    case "order.expired":
      return {
        kind: "EXPIRE",
        order_id: str(d.order_id),
        gateway_id: envGateway,
        symbol: str(d.symbol),
        detail: "",
        orderStatus: "EXPIRED",
      };
    case "session": {
      const state = str(d.state) ?? "?";
      const prev = str(d.prev_state);
      return {
        kind: "SESSION",
        order_id: null,
        gateway_id: envGateway,
        symbol: null,
        detail: `→ ${state}${prev ? ` (was ${prev})` : ""}`,
        orderStatus: null,
      };
    }
    case "circuit_breaker": {
      const resume = (env.topic ?? "").startsWith("circuit_breaker.resume");
      const symbol = str(d.symbol);
      const level = str(d.level);
      return {
        kind: "CB",
        order_id: null,
        gateway_id: envGateway,
        symbol,
        detail: resume ? `Resume ${symbol ?? ""}`.trim() : `Halt ${symbol ?? ""}${level ? ` · L${level}` : ""}`.trim(),
        orderStatus: null,
      };
    }
    case "admin.action": {
      const scope = (d.scope ?? {}) as Record<string, unknown>;
      const bits = [
        str(d.action),
        str(scope.symbol),
        str(scope.target_gateway_id),
        d.accepted ? "accepted" : "rejected",
      ].filter(Boolean);
      return {
        kind: "ADMIN",
        order_id: null,
        gateway_id: str(d.initiator_gateway_id) ?? envGateway,
        symbol: str(scope.symbol),
        detail: bits.join(" · "),
        orderStatus: null,
      };
    }
    default:
      return null; // book/depth/trade/auction/quote/mass_cancel/control frames
  }
}

const CSV_COLUMNS = ["Time", "Seq", "Kind", "Gateway", "Symbol", "Order ID", "Details"] as const;

function csvCell(value: string): string {
  // Quote when the value contains a comma, quote, or newline; double inner quotes.
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

/** Serialize monitor log rows to CSV (§15.9 export). */
export function monitorEventsToCsv(rows: MonitorEvent[]): string {
  const lines = [CSV_COLUMNS.join(",")];
  for (const r of rows) {
    lines.push(
      [
        r.ts,
        r.seq == null ? "" : String(r.seq),
        r.kind,
        r.gateway_id ?? "",
        r.symbol ?? "",
        r.order_id ?? "",
        r.detail,
      ]
        .map(csvCell)
        .join(","),
    );
  }
  return lines.join("\n");
}

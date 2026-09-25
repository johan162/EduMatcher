import { Modal } from "@/components/shared/Modal.js";
import { useAdminOrderDetailQuery } from "@/queries/index.js";
import { ApiError } from "@/api/apiFetch.js";

interface AdminOrderDetailModalProps {
  orderId: string;
  onClose: () => void;
}

function timeLabel(ts: string): string {
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleTimeString("en-GB", { hour12: false });
}

/** Compact one-line rendering of an audited event's stored payload. */
function payloadSummary(payload: unknown): string {
  if (payload == null) return "";
  let obj: unknown = payload;
  if (typeof payload === "string") {
    try {
      obj = JSON.parse(payload);
    } catch {
      return payload;
    }
  }
  if (obj && typeof obj === "object") {
    const p = obj as Record<string, unknown>;
    const bits: string[] = [];
    for (const k of ["status", "side", "price", "quantity", "fill_qty", "fill_price", "remaining_qty", "reason"]) {
      if (p[k] !== undefined && p[k] !== null && p[k] !== "") bits.push(`${k} ${String(p[k])}`);
    }
    return bits.join(" · ");
  }
  return String(obj);
}

/**
 * Cross-gateway order lifecycle drill-down (§15.9) using the audit trail
 * `GET /api/v1/admin/orders/{id}` — NOT the gateway-scoped `/history/orders`,
 * which cannot see other gateways' orders. Degrades gracefully when pm-audit is
 * absent (503) or the id is unknown (404).
 */
export function AdminOrderDetailModal({ orderId, onClose }: AdminOrderDetailModalProps) {
  const query = useAdminOrderDetailQuery(orderId);
  const err = query.error;
  const is503 = err instanceof ApiError && err.status === 503;
  const is404 = err instanceof ApiError && err.status === 404;

  return (
    <Modal title={`Order ${orderId}`} onClose={onClose}>
      {query.isLoading && <p className="text-xs text-fg-dim">Loading audit trail…</p>}

      {is503 && (
        <p className="text-xs text-fg-dim">
          Audit trail unavailable — pm-audit is not running or its index has not been built.
        </p>
      )}
      {is404 && <p className="text-xs text-fg-dim">No audited events for this order.</p>}
      {err && !is503 && !is404 && (
        <p className="text-xs text-ask">
          {err instanceof ApiError ? `${err.code}: ${err.message}` : "Failed to load lifecycle"}
        </p>
      )}

      {query.data && (
        <ol className="flex max-h-[60vh] flex-col gap-1 overflow-auto">
          {query.data.events.map((e, i) => (
            <li key={`${e.timestamp}-${i}`} className="flex items-start gap-2 text-[11px]">
              <span className="font-mono text-fg-faint whitespace-nowrap">{timeLabel(e.timestamp)}</span>
              <span className="rounded bg-elevated px-1.5 py-0.5 font-mono text-fg-dim">
                {e.topic}
              </span>
              <div className="flex flex-col">
                <span className="font-mono text-fg-dim">{e.gateway_id}</span>
                {payloadSummary(e.payload) && (
                  <span className="text-fg-dim">{payloadSummary(e.payload)}</span>
                )}
              </div>
            </li>
          ))}
          {query.data.events.length === 0 && (
            <li className="text-xs text-fg-dim">No events.</li>
          )}
        </ol>
      )}
    </Modal>
  );
}

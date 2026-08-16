import { useState } from "react";
import { toast } from "sonner";
import { Modal } from "@/components/shared/Modal.js";
import { useReplaceOrderMutation } from "@/queries/index.js";
import { useOrderFields } from "@/hooks/useOrderFields.js";
import { orderSchema } from "@/lib/validators.js";
import { ApiError } from "@/api/apiFetch.js";
import type { Order } from "@/types/index.js";

interface ReplaceDialogProps {
  order: Order;
  onClose: () => void;
}

const field =
  "bg-[#1a1a28] border border-[#2a2a45] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[#3a3a60] disabled:opacity-40";

/**
 * Cancel-Replace (atomic) dialog (§13.2). Use when a price change or size
 * increase resets priority anyway: the gateway cancels the resting order,
 * waits for the confirmation, then submits the replacement — so priority is
 * lost by design and no stale order is left live. Symbol/side/type/TIF are
 * inherited; price/stop and quantity are editable. Submits
 * `POST /orders/{id}/replace`; the row swaps via the live cancel + new-order acks.
 */
export function ReplaceDialog({ order, onClose }: ReplaceDialogProps) {
  const fields = useOrderFields(order.order_type);
  const [price, setPrice] = useState(order.price !== null ? String(order.price) : "");
  const [stopPrice, setStopPrice] = useState(order.stop_price !== null ? String(order.stop_price) : "");
  const [qty, setQty] = useState(String(order.quantity));
  const [error, setError] = useState<string | null>(null);
  const replace = useReplaceOrderMutation();

  const submit = () => {
    setError(null);
    // Build a full OrderRequest from the resting order + edits, including only
    // the fields this order type is allowed to carry (mirrors the ticket).
    const candidate: Record<string, unknown> = {
      symbol: order.symbol,
      side: order.side,
      order_type: order.order_type,
      quantity: qty,
      tif: order.tif,
    };
    if (fields.price && price !== "") candidate.price = price;
    if (fields.stop_price && stopPrice !== "") candidate.stop_price = stopPrice;
    if (fields.visible_qty && order.visible_qty !== null) candidate.visible_qty = order.visible_qty;
    if (fields.trail_offset && order.trail_offset !== null) candidate.trail_offset = order.trail_offset;
    if (order.smp_action !== null) candidate.smp_action = order.smp_action;

    const parsed = orderSchema.safeParse(candidate);
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Invalid replacement");
      return;
    }

    const d = parsed.data;
    const body: Record<string, unknown> = {
      symbol: d.symbol.toUpperCase(),
      side: d.side,
      order_type: d.order_type,
      quantity: d.quantity,
      tif: d.tif,
    };
    if (fields.price && d.price !== undefined) body.price = d.price;
    if (fields.stop_price && d.stop_price !== undefined) body.stop_price = d.stop_price;
    if (fields.visible_qty && d.visible_qty !== undefined) body.visible_qty = d.visible_qty;
    if (fields.trail_offset && d.trail_offset !== undefined) body.trail_offset = d.trail_offset;
    if (d.smp_action !== undefined) body.smp_action = d.smp_action;

    replace.mutate(
      { orderId: order.order_id, body },
      {
        onSuccess: (res) => {
          toast.success(
            `Replaced ${res.cancelled_order_id.slice(0, 8)} → ${res.replacement_order_id.slice(0, 8)}`,
          );
          onClose();
        },
        onError: (err) => {
          if (err instanceof ApiError && (err.status === 503 || err.code === "ENGINE_TIMEOUT")) {
            // The cancel leg's ack never arrived — typically because the order
            // already filled, so no replacement was sent. Nothing was left live.
            setError("Replace could not complete — the order may have already filled.");
            return;
          }
          setError(err instanceof ApiError ? `${err.code}: ${err.message}` : "Replace failed");
        },
      },
    );
  };

  return (
    <Modal title={`Replace ${order.symbol} · ${order.order_id.slice(0, 8)}`} onClose={onClose}>
      <div className="grid grid-cols-3 gap-2">
        <div className="flex flex-col gap-0.5">
          <span className="text-[10px] text-[#505070]">Symbol</span>
          <span className="font-mono text-xs text-[#9090b0]">{order.symbol}</span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-[10px] text-[#505070]">Side</span>
          <span className={`font-mono text-xs ${order.side === "BUY" ? "text-bid" : "text-ask"}`}>
            {order.side}
          </span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-[10px] text-[#505070]">Type · TIF</span>
          <span className="font-mono text-xs text-[#9090b0]">
            {order.order_type} · {order.tif}
          </span>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        {fields.price && (
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-[#505070]">Price</span>
            <input
              type="number"
              step="any"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              aria-label="Replace price"
              className={field}
            />
          </label>
        )}
        {fields.stop_price && (
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-[#505070]">Stop price</span>
            <input
              type="number"
              step="any"
              value={stopPrice}
              onChange={(e) => setStopPrice(e.target.value)}
              aria-label="Replace stop price"
              className={field}
            />
          </label>
        )}
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-[#505070]">Quantity</span>
          <input
            type="number"
            min={1}
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            aria-label="Replace quantity"
            className={field}
          />
        </label>
      </div>

      <p className="mt-3 text-[10px] leading-snug text-[#707090]">
        Replace cancels the resting order and submits a new one atomically. Priority resets — use
        Amend for a same-price size reduction if you want to keep your place in the queue.
      </p>

      {error && <p className="mt-2 text-[11px] text-ask">{error}</p>}

      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded border border-[#2a2a45] px-3 py-1.5 text-xs text-[#9090b0] hover:text-[#e8e8f0]"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={replace.isPending}
          className="rounded bg-[#3a3a60] px-3 py-1.5 text-xs font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          Replace order
        </button>
      </div>
    </Modal>
  );
}

import { useState } from "react";
import { toast } from "sonner";
import { Modal } from "@/components/shared/Modal.js";
import { useAmendOrderMutation } from "@/queries/index.js";
import { validateAmend } from "@/lib/validators.js";
import { ApiError } from "@/api/apiFetch.js";
import type { Order } from "@/types/index.js";

interface AmendDialogProps {
  order: Order;
  onClose: () => void;
}

const field =
  "bg-[#1a1a28] border border-[#2a2a45] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[#3a3a60] disabled:opacity-40";

/**
 * Amend (in-place) dialog (§13.2) — a same-price size reduction preserves queue
 * priority. Editable: price (when the type has one) and quantity; everything
 * else is read-only. Submits `PATCH /orders/{id}`; the blotter row updates from
 * the live `order.amended` event, so on success the dialog just closes.
 */
export function AmendDialog({ order, onClose }: AmendDialogProps) {
  const hasPrice = order.price !== null;
  const [price, setPrice] = useState(hasPrice ? String(order.price) : "");
  const [qty, setQty] = useState(String(order.quantity));
  const [error, setError] = useState<string | null>(null);
  const amend = useAmendOrderMutation();

  const filled = order.quantity - order.remaining_qty;

  const submit = () => {
    setError(null);
    // Engine-mirroring rules live in lib/validators so the dialog and the
    // engine cannot drift apart (§13.2).
    const result = validateAmend(
      { quantity: order.quantity, filled, price: order.price },
      { price, quantity: qty },
    );
    if (!result.ok) {
      setError(result.error);
      return;
    }

    amend.mutate(
      { orderId: order.order_id, body: result.body },
      {
        onSuccess: () => {
          toast.success(`Amend submitted for ${order.symbol} ${order.order_id.slice(0, 8)}`);
          onClose();
        },
        onError: (err) => {
          if (err instanceof ApiError && (err.status === 503 || err.code === "ENGINE_TIMEOUT")) {
            toast(`Amend submitted — awaiting confirmation (check blotter)`);
            onClose();
            return;
          }
          const msg =
            err instanceof ApiError ? `${err.code}: ${err.message}` : "Amend failed";
          setError(msg);
        },
      },
    );
  };

  const ro = (label: string, value: string) => (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] text-[#505070]">{label}</span>
      <span className="font-mono text-xs text-[#9090b0]">{value}</span>
    </div>
  );

  return (
    <Modal title={`Amend ${order.symbol} · ${order.order_id.slice(0, 8)}`} onClose={onClose}>
      <div className="grid grid-cols-3 gap-2">
        {ro("Symbol", order.symbol)}
        {ro("Side", order.side)}
        {ro("Type", order.order_type)}
        {ro("TIF", order.tif)}
        {ro("Original Qty", String(order.quantity))}
        {ro("Filled", String(filled))}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        {hasPrice && (
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-[#505070]">Price</span>
            <input
              type="number"
              step="any"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              aria-label="Amend price"
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
            aria-label="Amend quantity"
            className={field}
          />
        </label>
      </div>

      <p className="mt-3 text-[10px] leading-snug text-[#707090]">
        Reducing quantity at the same price keeps your queue priority. A price change or a
        quantity increase resets priority — consider Replace instead.
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
          disabled={amend.isPending}
          className="rounded bg-[#3a3a60] px-3 py-1.5 text-xs font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          Amend order
        </button>
      </div>
    </Modal>
  );
}

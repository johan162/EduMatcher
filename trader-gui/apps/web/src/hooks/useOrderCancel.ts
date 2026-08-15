import { useState } from "react";
import { toast } from "sonner";
import { useCancelOrderMutation, useSubmitOrderMutation } from "@/queries/index.js";
import { useSettingsStore } from "@/store/useSettingsStore.js";
import { buildResubmitOrder } from "@/lib/resubmit.js";
import { ApiError } from "@/api/apiFetch.js";
import type { Order } from "@/types/index.js";

/**
 * Shared single-order cancel behaviour (§20.3), used by the full Active Orders
 * blotter and the Workspace compact blotter so both honour power-user mode
 * identically:
 *  - confirmations ON (default): `requestCancel` opens a confirm dialog; the
 *    consumer renders it from `confirmTarget`/`confirmCancel`.
 *  - confirmations OFF (power-user): the cancel fires immediately and an
 *    undo-toast offers to re-submit an equivalent order (priority not
 *    preserved — the toast says so).
 *
 * `cancelById` is the plain, dialog-less cancel used for each id in a bulk
 * cancel (which has its own always-confirm dialog at the call site).
 */
export function useOrderCancel() {
  const cancel = useCancelOrderMutation();
  const submit = useSubmitOrderMutation();
  const confirmCancellations = useSettingsStore((s) => s.confirmCancellations);
  const [confirmTarget, setConfirmTarget] = useState<Order | null>(null);

  const onCancelError = (id8: string) => (err: unknown) => {
    if (err instanceof ApiError && (err.status === 503 || err.code === "ENGINE_TIMEOUT")) {
      toast(`Cancel submitted — awaiting confirmation for ${id8}`);
      return;
    }
    toast.error(err instanceof ApiError ? `${err.code}: ${err.message}` : "Cancel failed");
  };

  const cancelById = (orderId: string) => {
    const id8 = orderId.slice(0, 8);
    cancel.mutate(orderId, {
      onSuccess: () => toast.success(`Cancel submitted for ${id8}`),
      onError: onCancelError(id8),
    });
  };

  const resubmit = (order: Order) => {
    const body = buildResubmitOrder(order);
    if (!body) {
      toast("Nothing to undo — the order had no remaining quantity");
      return;
    }
    submit.mutate(
      { body },
      {
        onSuccess: () => toast.success(`Re-submitted ${order.symbol} (new priority)`),
        onError: (err) =>
          toast.error(err instanceof ApiError ? `${err.code}: ${err.message}` : "Re-submit failed"),
      },
    );
  };

  const cancelWithUndo = (order: Order) => {
    const id8 = order.order_id.slice(0, 8);
    cancel.mutate(order.order_id, {
      onSuccess: () =>
        toast(`Order ${id8} cancelled`, {
          description: "Undo re-submits an equivalent order (priority not preserved).",
          action: { label: "Undo", onClick: () => resubmit(order) },
          duration: 6000,
        }),
      onError: onCancelError(id8),
    });
  };

  /** Per-row cancel entry point: confirm dialog by default, undo-toast in power-user mode. */
  const requestCancel = (order: Order) => {
    if (confirmCancellations) setConfirmTarget(order);
    else cancelWithUndo(order);
  };

  /** Confirm the pending single-order cancel (called by the consumer's dialog). */
  const confirmCancel = () => {
    if (!confirmTarget) return;
    cancelById(confirmTarget.order_id);
    setConfirmTarget(null);
  };

  return {
    requestCancel,
    cancelById,
    confirmTarget,
    setConfirmTarget,
    confirmCancel,
    busy: cancel.isPending,
  };
}

import { useCallback, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { OrdersBlotter } from "@/components/orders/OrdersBlotter.js";
import { OrderGroupsPanel } from "@/components/orders/OrderGroupsPanel.js";
import { OrderDetailDrawer } from "@/components/orders/OrderDetailDrawer.js";
import { AmendDialog } from "@/components/orders/AmendDialog.js";
import { ReplaceDialog } from "@/components/orders/ReplaceDialog.js";
import { CancelConfirm } from "@/components/orders/CancelConfirm.js";
import { useOrderStore } from "@/store/useOrderStore.js";
import { useBookStore } from "@/store/useBookStore.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";
import {
  useCancelOrderMutation,
  useCancelOcoMutation,
  useCancelComboMutation,
} from "@/queries/index.js";
import { getOrders } from "@/api/endpoints.js";
import { ApiError } from "@/api/apiFetch.js";
import type { OrderGroup } from "@/lib/orderGroups.js";
import type { Order } from "@/types/index.js";

/**
 * Active Orders screen (§13.1) — the full live blotter plus Amend, Cancel-Replace,
 * cancel (with confirmation), bulk cancel, and the Order Detail drawer. The
 * blotter is driven by {@link useOrderStore} (seeded from `orders.snapshot`,
 * kept current by `order.*`); the Refresh button reconciles against `GET /orders`.
 */
export function ActiveOrdersPage() {
  const ordersMap = useOrderStore((s) => s.orders);
  const syncedAt = useOrderStore((s) => s.syncedAt);
  const orders = useMemo(() => Object.values(ordersMap), [ordersMap]);
  const cancel = useCancelOrderMutation();
  const cancelOco = useCancelOcoMutation();
  const cancelCombo = useCancelComboMutation();

  const [detailId, setDetailId] = useState<string | null>(null);
  const [amendTarget, setAmendTarget] = useState<Order | null>(null);
  const [replaceTarget, setReplaceTarget] = useState<Order | null>(null);
  const [cancelTarget, setCancelTarget] = useState<Order | null>(null);
  const [bulkTarget, setBulkTarget] = useState<string[] | null>(null);
  const [groupTarget, setGroupTarget] = useState<OrderGroup | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const tickDecimalsFor = useCallback((symbol: string) => {
    return (
      useBookStore.getState().books[symbol]?.tickDecimals ??
      useSymbolStore.getState().symbols.find((m) => m.symbol === symbol)?.tick_decimals ??
      2
    );
  }, []);

  const refresh = async () => {
    setRefreshing(true);
    try {
      const res = await getOrders();
      useOrderStore.getState().hydrate(res.orders);
    } catch (err) {
      toast.error(err instanceof ApiError ? `${err.code}: ${err.message}` : "Refresh failed");
    } finally {
      setRefreshing(false);
    }
  };

  const doCancel = (orderId: string) => {
    cancel.mutate(orderId, {
      onSuccess: () => toast.success(`Cancel submitted for ${orderId.slice(0, 8)}`),
      onError: (err) => {
        if (err instanceof ApiError && (err.status === 503 || err.code === "ENGINE_TIMEOUT")) {
          toast(`Cancel submitted — awaiting confirmation for ${orderId.slice(0, 8)}`);
          return;
        }
        toast.error(err instanceof ApiError ? `${err.code}: ${err.message}` : "Cancel failed");
      },
    });
  };

  // Cancel a whole OCO/combo group with one call: DELETE /oco/{id} cancels both
  // legs; DELETE /combos/{id} cancels the combo and all its legs (§13.3). The
  // blotter rows then update from the live order.cancelled / oco.cancelled /
  // combo.status events.
  const doCancelGroup = (group: OrderGroup) => {
    const onError = (err: unknown) => {
      if (err instanceof ApiError && (err.status === 503 || err.code === "ENGINE_TIMEOUT")) {
        toast(`Cancel ${group.kind} ${group.id} submitted — awaiting confirmation`);
        return;
      }
      toast.error(err instanceof ApiError ? `${err.code}: ${err.message}` : "Group cancel failed");
    };
    const onSuccess = () => toast.success(`${group.kind} group ${group.id} cancel submitted`);
    if (group.kind === "OCO") cancelOco.mutate(group.id, { onSuccess, onError });
    else cancelCombo.mutate(group.id, { onSuccess, onError });
  };

  return (
    <div className="flex flex-col gap-3 p-4 h-full">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-[#e8e8f0]">Active Orders</h1>
        <span className="text-[11px] text-[#505070]">
          {orders.length} {orders.length === 1 ? "order" : "orders"}
          {syncedAt ? ` · reconciled ${new Date(syncedAt).toLocaleTimeString()}` : ""}
        </span>
        <button
          type="button"
          onClick={refresh}
          disabled={refreshing}
          className="ml-auto flex items-center gap-1 rounded border border-[#2a2a45] px-2 py-1 text-xs text-[#9090b0] hover:text-[#e8e8f0] disabled:opacity-50"
        >
          <RefreshCw size={12} className={refreshing ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      <OrderGroupsPanel orders={orders} onCancelGroup={setGroupTarget} />

      <OrdersBlotter
        orders={orders}
        tickDecimalsFor={tickDecimalsFor}
        onOpenDetail={setDetailId}
        onAmend={setAmendTarget}
        onReplace={setReplaceTarget}
        onCancel={setCancelTarget}
        onBulkCancel={setBulkTarget}
      />

      {detailId && (
        <OrderDetailDrawer key={detailId} orderId={detailId} onClose={() => setDetailId(null)} />
      )}

      {amendTarget && <AmendDialog order={amendTarget} onClose={() => setAmendTarget(null)} />}

      {replaceTarget && (
        <ReplaceDialog order={replaceTarget} onClose={() => setReplaceTarget(null)} />
      )}

      {cancelTarget && (
        <CancelConfirm
          title="Cancel order?"
          message={`Cancel ${cancelTarget.side} ${cancelTarget.quantity} ${cancelTarget.symbol} (${cancelTarget.order_id.slice(0, 8)})?`}
          confirmLabel="Cancel order"
          busy={cancel.isPending}
          onConfirm={() => {
            doCancel(cancelTarget.order_id);
            setCancelTarget(null);
          }}
          onClose={() => setCancelTarget(null)}
        />
      )}

      {bulkTarget && (
        <CancelConfirm
          title="Cancel selected orders?"
          message={`Cancel ${bulkTarget.length} selected ${bulkTarget.length === 1 ? "order" : "orders"}? This cannot be undone.`}
          confirmLabel={`Cancel ${bulkTarget.length}`}
          onConfirm={() => {
            bulkTarget.forEach(doCancel);
            toast(`Cancelling ${bulkTarget.length} orders`);
            setBulkTarget(null);
          }}
          onClose={() => setBulkTarget(null)}
        />
      )}

      {groupTarget && (
        <CancelConfirm
          title={`Cancel ${groupTarget.kind} group?`}
          message={
            groupTarget.kind === "OCO"
              ? `Cancel OCO group ${groupTarget.id}? This cancels both legs.`
              : `Cancel combo group ${groupTarget.id}? This cancels the combo and all its legs. Already-filled legs are not reversed.`
          }
          confirmLabel="Cancel group"
          busy={cancelOco.isPending || cancelCombo.isPending}
          onConfirm={() => {
            doCancelGroup(groupTarget);
            setGroupTarget(null);
          }}
          onClose={() => setGroupTarget(null)}
        />
      )}
    </div>
  );
}

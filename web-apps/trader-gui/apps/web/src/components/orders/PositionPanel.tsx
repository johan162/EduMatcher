import { useMemo, useState } from "react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { usePositionsQuery, useSubmitOrderMutation } from "@/queries/index.js";
import { cancelOrder } from "@/api/endpoints.js";
import { useWsEvent } from "@/hooks/useWsEvent.js";
import { useSessionStore } from "@/store/useSessionStore.js";
import { useBookStore } from "@/store/useBookStore.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";
import { useSettingsStore } from "@/store/useSettingsStore.js";
import { CancelConfirm } from "@/components/orders/CancelConfirm.js";
import { buildFlattenOrder } from "@/lib/flatten.js";
import { formatPrice, formatQty } from "@/lib/formatters.js";
import { ApiError } from "@/api/apiFetch.js";
import type { Position } from "@/types/index.js";

/**
 * Position Summary Panel with Flatten (§13.6), shared by the TRADER and
 * MARKET_MAKER Positions screens (§14.4). Net position per symbol from
 * `GET /positions`, refreshed live by invalidating on `order.fill`. Flatten
 * submits a MARKET close (opposite side, abs(qty)); Flatten All closes every
 * non-zero position. MARKET orders are rejected outside CONTINUOUS
 * (FR-ENG-030), so the actions are disabled in other phases.
 */
export function PositionPanel() {
  const positionsQuery = usePositionsQuery();
  const submit = useSubmitOrderMutation();
  const qc = useQueryClient();
  const phase = useSessionStore((s) => s.phase);
  const books = useBookStore((s) => s.books);
  const symbols = useSymbolStore((s) => s.symbols);
  const confirmCancellations = useSettingsStore((s) => s.confirmCancellations);

  const [flattenTarget, setFlattenTarget] = useState<Position | null>(null);
  const [flattenAll, setFlattenAll] = useState(false);

  // A fill changes the net position — refresh the cache when one arrives.
  useWsEvent("order.fill", () => {
    void qc.invalidateQueries({ queryKey: ["positions"] });
  });

  const positions = useMemo(
    () => (positionsQuery.data ?? []).slice().sort((a, b) => a.symbol.localeCompare(b.symbol)),
    [positionsQuery.data],
  );
  const nonZero = positions.filter((p) => p.net_qty !== 0);
  const isContinuous = phase === "CONTINUOUS";

  const tickFor = (sym: string) =>
    books[sym]?.tickDecimals ?? symbols.find((m) => m.symbol === sym)?.tick_decimals ?? 2;

  // Prefer the live last trade price; fall back to the cache's last_price.
  const lastPriceFor = (p: Position) => books[p.symbol]?.lastPrice ?? p.last_price;

  const submitFlatten = (p: Position, opts: { undo?: boolean } = {}) => {
    const body = buildFlattenOrder(p);
    if (!body) return;
    submit.mutate(
      { body: body as unknown as Record<string, unknown> },
      {
        onSuccess: (res) => {
          if (opts.undo) {
            // Power-user path: fire immediately, offer a brief undo window that
            // cancels the just-submitted MARKET order if it has not yet filled
            // (best-effort — priority/fill are not guaranteed reversible).
            toast(`Flatten ${p.symbol}: ${body.side} ${body.quantity} MARKET`, {
              action: {
                label: "Undo",
                onClick: () => {
                  cancelOrder(res.order_id).catch(() => {
                    /* already filled/cancelled — nothing to undo */
                  });
                },
              },
            });
          } else {
            toast.success(`Flatten ${p.symbol}: ${body.side} ${body.quantity} MARKET submitted`);
          }
          void qc.invalidateQueries({ queryKey: ["positions"] });
        },
        onError: (err) => {
          if (err instanceof ApiError && (err.status === 503 || err.code === "ENGINE_TIMEOUT")) {
            toast(`Flatten ${p.symbol} submitted — awaiting confirmation`);
            return;
          }
          toast.error(err instanceof ApiError ? `${err.code}: ${err.message}` : "Flatten failed");
        },
      },
    );
  };

  const onFlattenClick = (p: Position) => {
    if (!isContinuous) return;
    if (confirmCancellations) setFlattenTarget(p);
    else submitFlatten(p, { undo: true }); // undo-toast in power-user mode
  };

  const doFlattenAll = () => {
    for (const p of nonZero) submitFlatten(p);
    toast(`Flattening ${nonZero.length} ${nonZero.length === 1 ? "position" : "positions"}`);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <span className="text-[11px] text-[#505070]">
          {positions.length} {positions.length === 1 ? "symbol" : "symbols"}
          {positionsQuery.isFetching ? " · loading…" : ""}
        </span>
        <button
          type="button"
          onClick={() => setFlattenAll(true)}
          disabled={!isContinuous || nonZero.length === 0}
          title={
            !isContinuous
              ? "Market orders are only accepted during continuous trading"
              : nonZero.length === 0
                ? "No open positions"
                : "Flatten every non-zero position"
          }
          className="ml-auto rounded bg-ask px-3 py-1.5 text-xs font-semibold text-white hover:brightness-110 disabled:opacity-40"
        >
          Flatten All
        </button>
      </div>

      {!isContinuous && (
        <p className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-[11px] text-amber-300">
          Flatten submits MARKET orders, which are only accepted during continuous trading. The
          actions are disabled in the current phase ({phase}).
        </p>
      )}

      {positions.length === 0 ? (
        <div className="border border-[#2a2a45] rounded p-8 text-center text-sm text-[#9090b0]">
          No open positions.
        </div>
      ) : (
        <div className="overflow-auto border border-[#2a2a45] rounded">
          <table className="w-full text-xs border-collapse">
            <thead className="bg-[#12121a] text-[#9090b0]">
              <tr>
                <th scope="col" className="px-2 py-1.5 text-left font-medium">Symbol</th>
                <th scope="col" className="px-2 py-1.5 text-right font-medium">Position</th>
                <th scope="col" className="px-2 py-1.5 text-right font-medium">Last Price</th>
                <th scope="col" className="px-2 py-1.5 text-right font-medium">Action</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => {
                const last = lastPriceFor(p);
                const flat = p.net_qty === 0;
                return (
                  <tr key={p.symbol} className="border-b border-[#1a1a28] hover:bg-[#1a1a28]">
                    <td className="px-2 py-1 font-mono font-medium">{p.symbol}</td>
                    <td
                      className={`px-2 py-1 text-right font-mono ${
                        p.net_qty > 0 ? "text-bid" : p.net_qty < 0 ? "text-ask" : "text-[#9090b0]"
                      }`}
                    >
                      {p.net_qty > 0 ? "+" : ""}
                      {formatQty(p.net_qty)}
                    </td>
                    <td className="px-2 py-1 text-right font-mono text-[#e8e8f0]">
                      {formatPrice(last, tickFor(p.symbol))}
                    </td>
                    <td className="px-2 py-1 text-right">
                      <button
                        type="button"
                        onClick={() => onFlattenClick(p)}
                        disabled={flat || !isContinuous || submit.isPending}
                        aria-label={`Flatten ${p.symbol}`}
                        className="rounded border border-[#2a2a45] px-2 py-0.5 text-[11px] text-[#9090b0] hover:text-[#e8e8f0] disabled:opacity-30"
                      >
                        Flatten
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Per-row confirm (default mode) */}
      {flattenTarget && (
        <FlattenConfirm
          position={flattenTarget}
          onConfirm={() => {
            submitFlatten(flattenTarget);
            setFlattenTarget(null);
          }}
          onClose={() => setFlattenTarget(null)}
        />
      )}

      {/* Flatten All ALWAYS confirms, regardless of power-user mode (§13.6) */}
      {flattenAll && (
        <CancelConfirm
          title="Flatten all positions?"
          message={`Submit MARKET closing orders for ${nonZero.length} ${nonZero.length === 1 ? "position" : "positions"}? This is high-impact and affects multiple symbols.`}
          confirmLabel="Flatten All"
          onConfirm={() => {
            doFlattenAll();
            setFlattenAll(false);
          }}
          onClose={() => setFlattenAll(false)}
        />
      )}
    </div>
  );
}

/** Single-position flatten confirmation with the resolved side/qty spelled out. */
function FlattenConfirm({
  position,
  onConfirm,
  onClose,
}: {
  position: Position;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const order = buildFlattenOrder(position);
  return (
    <CancelConfirm
      title="Flatten position?"
      message={
        order
          ? `Flatten ${position.symbol}: ${order.side} ${order.quantity} MARKET?`
          : `${position.symbol} is already flat.`
      }
      confirmLabel="Flatten"
      onConfirm={onConfirm}
      onClose={onClose}
    />
  );
}

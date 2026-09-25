import { useMemo, useState } from "react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { usePositionsQuery, useSubmitOrderMutation } from "@/queries/index.js";
import { useWsEvent } from "@/hooks/useWsEvent.js";
import { useSessionStore } from "@/store/useSessionStore.js";
import { useBookStore } from "@/store/useBookStore.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";
import { useSettingsStore } from "@/store/useSettingsStore.js";
import { useOrderStore, isTerminal } from "@/store/useOrderStore.js";
import { useHaltStore } from "@/store/useHaltStore.js";
import { CancelConfirm } from "@/components/orders/CancelConfirm.js";
import { buildFlattenOrder } from "@/lib/flatten.js";
import { isOrderTypeBlocked } from "@/lib/sessionState.js";
import { summarizeSettled, describeBulkOutcome } from "@/lib/bulkOutcome.js";
import { formatPrice, formatQty } from "@/lib/formatters.js";
import { ApiError } from "@/api/apiFetch.js";
import type { Order, Position, Side } from "@/types/index.js";

/**
 * M4: count of this symbol's working (non-terminal) orders on `side` -- the
 * side a flatten for this symbol would itself submit. If one of these later
 * fills too, combined with the flatten's own fill the position can overshoot
 * past flat (e.g. a long 100 with a working SELL 100 flattens to short 100).
 * Warn about it; do not block the flatten.
 */
function workingOrdersOnSide(orders: Record<string, Order>, symbol: string, side: Side): number {
  return Object.values(orders).filter(
    (o) => o.symbol === symbol && o.side === side && !isTerminal(o.status),
  ).length;
}

function overshootWarning(count: number, side: Side): string {
  if (!count) return "";
  return ` Warning: ${count} working ${side} ${count === 1 ? "order" : "orders"} on this symbol could add to this once filled.`;
}

/**
 * Position Summary Panel with Flatten (§13.6), shared by the TRADER and
 * MARKET_MAKER Positions screens (§14.4). Net position per symbol from
 * `GET /positions`, refreshed live by invalidating on `order.fill`. Flatten
 * submits a MARKET close (opposite side, abs(qty)); Flatten All closes every
 * flattenable non-zero position. Whether a MARKET order can be submitted
 * right now is decided by `lib/sessionState.ts::isOrderTypeBlocked` (M7) --
 * the single source shared with OrderTicket -- rather than a local re-
 * statement of the phase/halt rule, so this panel and the ticket cannot
 * drift apart on when MARKET orders are accepted.
 */
export function PositionPanel() {
  const positionsQuery = usePositionsQuery();
  const submit = useSubmitOrderMutation();
  const qc = useQueryClient();
  const phase = useSessionStore((s) => s.phase);
  const books = useBookStore((s) => s.books);
  const symbols = useSymbolStore((s) => s.symbols);
  const confirmCancellations = useSettingsStore((s) => s.confirmCancellations);
  const ordersMap = useOrderStore((s) => s.orders);
  const halts = useHaltStore((s) => s.halts);

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
  // M7: a halted symbol also rejects MARKET (isOrderTypeBlocked, FR-ENG-030)
  // even in CONTINUOUS -- PositionPanel used to only check phase, so Flatten
  // was offered on a halted symbol and the engine would reject it.
  const flattenBlocked = (symbol: string) =>
    isOrderTypeBlocked("MARKET", phase, halts[symbol] !== undefined);
  const flattenablePositions = nonZero.filter((p) => !flattenBlocked(p.symbol));

  const tickFor = (sym: string) =>
    books[sym]?.tickDecimals ?? symbols.find((m) => m.symbol === sym)?.tick_decimals ?? 2;

  // Prefer the live last trade price; fall back to the cache's last_price.
  const lastPriceFor = (p: Position) => books[p.symbol]?.lastPrice ?? p.last_price;

  // M4: the power-user "Undo" used to cancel the just-submitted MARKET
  // order, which never rests and so can never undo anything -- dropped.
  const submitFlatten = (p: Position) => {
    const body = buildFlattenOrder(p);
    if (!body) return;
    submit.mutate(
      { body: body as unknown as Record<string, unknown> },
      {
        onSuccess: () => {
          toast.success(`Flatten ${p.symbol}: ${body.side} ${body.quantity} MARKET submitted`);
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
    if (flattenBlocked(p.symbol)) return;
    if (confirmCancellations) setFlattenTarget(p);
    else submitFlatten(p);
  };

  // M4: how many of the non-zero positions also have a working order on
  // their own flatten side, surfaced in the Flatten All confirm message.
  const flattenAllOverlapCount = flattenablePositions.filter((p) => {
    const order = buildFlattenOrder(p);
    return order ? workingOrdersOnSide(ordersMap, p.symbol, order.side) > 0 : false;
  }).length;
  const haltedSkipped = nonZero.length - flattenablePositions.length;
  const flattenAllMessage =
    `Submit MARKET closing orders for ${flattenablePositions.length} ` +
    `${flattenablePositions.length === 1 ? "position" : "positions"}? This is high-impact and ` +
    `affects multiple symbols.` +
    (flattenAllOverlapCount
      ? ` Warning: ${flattenAllOverlapCount} of these also ` +
        `${flattenAllOverlapCount === 1 ? "has" : "have"} a working order on the flatten side, ` +
        `which could push the position past flat once filled.`
      : "") +
    (haltedSkipped
      ? ` ${haltedSkipped} ${haltedSkipped === 1 ? "position is" : "positions are"} halted and ` +
        `will be skipped.`
      : "");

  // M3: fire every close concurrently via mutateAsync and report one summary
  // toast once all settle, instead of looping submitFlatten (whose
  // onSuccess/onError only ever fired for the last position in the batch).
  const doFlattenAll = async () => {
    const bodies = flattenablePositions
      .map((p) => buildFlattenOrder(p))
      .filter((b): b is NonNullable<typeof b> => b !== null);
    toast(`Flattening ${bodies.length} ${bodies.length === 1 ? "position" : "positions"}`);
    const results = await Promise.allSettled(
      bodies.map((body) =>
        submit.mutateAsync({ body: body as unknown as Record<string, unknown> }),
      ),
    );
    void qc.invalidateQueries({ queryKey: ["positions"] });
    const outcome = summarizeSettled(results);
    const message = describeBulkOutcome("Flattened", "position", outcome);
    if (outcome.failed) toast.error(message);
    else if (outcome.pending) toast(message);
    else toast.success(message);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <span className="text-[11px] text-fg-faint">
          {positions.length} {positions.length === 1 ? "symbol" : "symbols"}
          {positionsQuery.isFetching ? " · loading…" : ""}
        </span>
        <button
          type="button"
          onClick={() => setFlattenAll(true)}
          disabled={flattenablePositions.length === 0}
          title={
            !isContinuous
              ? "Market orders are only accepted during continuous trading"
              : nonZero.length === 0
                ? "No open positions"
                : flattenablePositions.length === 0
                  ? "All open positions are halted"
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
        <div className="border border-line rounded p-8 text-center text-sm text-fg-dim">
          No open positions.
        </div>
      ) : (
        <div className="overflow-auto border border-line rounded">
          <table className="w-full text-xs border-collapse">
            <thead className="bg-panel text-fg-dim">
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
                  <tr key={p.symbol} className="border-b border-raised hover:bg-raised">
                    <td className="px-2 py-1 font-mono font-medium">{p.symbol}</td>
                    <td
                      className={`px-2 py-1 text-right font-mono ${
                        p.net_qty > 0 ? "text-bid" : p.net_qty < 0 ? "text-ask" : "text-fg-dim"
                      }`}
                    >
                      {p.net_qty > 0 ? "+" : ""}
                      {formatQty(p.net_qty)}
                    </td>
                    <td className="px-2 py-1 text-right font-mono text-fg">
                      {formatPrice(last, tickFor(p.symbol))}
                    </td>
                    <td className="px-2 py-1 text-right">
                      <button
                        type="button"
                        onClick={() => onFlattenClick(p)}
                        disabled={flat || flattenBlocked(p.symbol) || submit.isPending}
                        aria-label={`Flatten ${p.symbol}`}
                        title={halts[p.symbol] !== undefined ? `${p.symbol} is halted` : undefined}
                        className="rounded border border-line px-2 py-0.5 text-[11px] text-fg-dim hover:text-fg disabled:opacity-30"
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
          orders={ordersMap}
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
          message={flattenAllMessage}
          confirmLabel="Flatten All"
          onConfirm={() => {
            void doFlattenAll();
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
  orders,
  onConfirm,
  onClose,
}: {
  position: Position;
  orders: Record<string, Order>;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const order = buildFlattenOrder(position);
  return (
    <CancelConfirm
      title="Flatten position?"
      message={
        order
          ? `Flatten ${position.symbol}: ${order.side} ${order.quantity} MARKET?` +
            overshootWarning(workingOrdersOnSide(orders, position.symbol, order.side), order.side)
          : `${position.symbol} is already flat.`
      }
      confirmLabel="Flatten"
      onConfirm={onConfirm}
      onClose={onClose}
    />
  );
}

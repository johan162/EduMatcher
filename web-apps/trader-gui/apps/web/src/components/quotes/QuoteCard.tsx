import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { useCancelQuoteMutation } from "@/queries/index.js";
import { useQuotePrefillStore } from "@/store/useQuotePrefillStore.js";
import { CancelConfirm } from "@/components/orders/CancelConfirm.js";
import { NewQuoteForm, type QuoteFormInitial } from "@/components/quotes/NewQuoteForm.js";
import { legFill } from "@/lib/quotes.js";
import { formatPrice, formatQty } from "@/lib/formatters.js";
import { ApiError } from "@/api/apiFetch.js";
import type { ActiveQuote } from "@/types/index.js";

interface QuoteCardProps {
  symbol: string;
  tickDecimals: number;
  quote?: ActiveQuote;
}

function stateClasses(state: string): string {
  if (state === "ACTIVE") return "bg-emerald-700 text-white";
  if (state.startsWith("INACTIVE")) return "bg-amber-600 text-white";
  if (state === "PENDING") return "bg-slate-600 text-white";
  return "bg-slate-700 text-[#c8c8e0]"; // CANCELLED / MISSING / unknown
}

/**
 * One quote card (§14.1.1). Reads the reliable per-side data from the
 * ActiveQuote (bootstrap): bid/ask price × qty with a `filled = qty - remaining`
 * progress bar, quote state badge, and per-leg status. New Quote toggles the
 * inline form; a fill-alert "Re-quote" (§14.1.2) opens it prefilled via the
 * quote prefill store. Cancel calls `DELETE /quotes/{symbol}` with confirmation.
 */
export function QuoteCard({ symbol, tickDecimals, quote }: QuoteCardProps) {
  const qc = useQueryClient();
  const cancel = useCancelQuoteMutation();
  const prefill = useQuotePrefillStore((s) => s.prefill);

  const [formOpen, setFormOpen] = useState(false);
  const [initial, setInitial] = useState<QuoteFormInitial | undefined>(undefined);
  const [confirmOpen, setConfirmOpen] = useState(false);

  // A "Re-quote" fill alert (or any prefill for this symbol) opens the form
  // prefilled with the previous quote's prices/qtys and a fresh quote id.
  useEffect(() => {
    if (prefill && prefill.symbol === symbol) {
      setInitial({
        bid_price: prefill.bid_price,
        bid_qty: prefill.bid_qty,
        ask_price: prefill.ask_price,
        ask_qty: prefill.ask_qty,
      });
      setFormOpen(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill?.nonce]);

  const openNewQuote = () => {
    // Seed from the current quote's values (fresh id) when one exists.
    setInitial(
      quote
        ? {
            bid_price: quote.bid_price,
            bid_qty: quote.bid_qty,
            ask_price: quote.ask_price,
            ask_qty: quote.ask_qty,
          }
        : undefined,
    );
    setFormOpen(true);
  };

  const doCancel = () => {
    cancel.mutate(symbol, {
      onSuccess: () => {
        toast.success(`Cancel submitted for ${symbol} quote`);
        void qc.invalidateQueries({ queryKey: ["quotes/bootstrap"] });
        void qc.invalidateQueries({ queryKey: ["quotes/legs"] });
      },
      onError: (err) => {
        if (err instanceof ApiError && (err.status === 503 || err.code === "ENGINE_TIMEOUT")) {
          toast(`Cancel submitted for ${symbol} — awaiting confirmation`);
          return;
        }
        toast.error(err instanceof ApiError ? `${err.code}: ${err.message}` : "Quote cancel failed");
      },
    });
    setConfirmOpen(false);
  };

  const legRow = (
    side: "BID" | "ASK",
    price: number | null,
    qty: number,
    remaining: number,
    status: string,
  ) => {
    const { filled, pct } = legFill(qty, remaining);
    const priceColor = side === "BID" ? "text-bid" : "text-ask";
    return (
      <div className="flex flex-col gap-0.5">
        <div className="flex items-baseline justify-between">
          <span className={`text-[11px] font-semibold ${priceColor}`}>{side}</span>
          <span className="font-mono text-xs">
            {formatPrice(price, tickDecimals)} × {formatQty(qty)}
          </span>
          <span className="text-[10px] text-[#9090b0]">
            Fill: {formatQty(filled)} / {formatQty(qty)}
          </span>
        </div>
        <div className="h-1 overflow-hidden rounded bg-[#1a1a28]">
          <div
            className={side === "BID" ? "h-full bg-bid" : "h-full bg-ask"}
            style={{ width: `${Math.min(100, pct)}%` }}
            aria-label={`${side} fill ${pct.toFixed(0)}%`}
          />
        </div>
        <span className="text-[9px] text-[#505070]">{status}</span>
      </div>
    );
  };

  return (
    <div className="flex flex-col gap-2 rounded border border-[#2a2a45] bg-[#0d0d14] p-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-semibold text-[#e8e8f0]">{symbol}</span>
          {quote && (
            <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${stateClasses(quote.state)}`}>
              {quote.state}
            </span>
          )}
        </div>
        <div className="flex gap-1.5">
          <button
            type="button"
            onClick={openNewQuote}
            className="rounded bg-[#3a3a60] px-2 py-0.5 text-[11px] font-medium text-white hover:brightness-110"
          >
            New Quote
          </button>
          {quote && (
            <button
              type="button"
              onClick={() => setConfirmOpen(true)}
              aria-label={`Cancel ${symbol} quote`}
              className="rounded border border-[#2a2a45] px-2 py-0.5 text-[11px] text-[#9090b0] hover:text-ask"
            >
              Cancel
            </button>
          )}
        </div>
      </div>

      {quote ? (
        <>
          {legRow("BID", quote.bid_price, quote.bid_qty, quote.bid_remaining_qty, quote.bid_status)}
          {legRow("ASK", quote.ask_price, quote.ask_qty, quote.ask_remaining_qty, quote.ask_status)}
          <div className="text-[10px] text-[#505070]">Quote ID: {quote.quote_id}</div>
        </>
      ) : (
        !formOpen && <p className="text-[11px] text-[#505070]">No active quote.</p>
      )}

      {formOpen && (
        <NewQuoteForm
          symbol={symbol}
          tickDecimals={tickDecimals}
          initial={initial}
          onDone={() => setFormOpen(false)}
        />
      )}

      {confirmOpen && (
        <CancelConfirm
          title="Cancel quote?"
          message={`Cancel the active ${symbol} quote? This removes both resting legs.`}
          confirmLabel="Cancel quote"
          busy={cancel.isPending}
          onConfirm={doCancel}
          onClose={() => setConfirmOpen(false)}
        />
      )}
    </div>
  );
}

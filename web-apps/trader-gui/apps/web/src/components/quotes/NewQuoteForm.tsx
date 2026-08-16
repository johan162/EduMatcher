import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { useSubmitQuoteMutation } from "@/queries/index.js";
import { useActiveSymbolStore } from "@/store/useActiveSymbolStore.js";
import { useNotificationStore } from "@/store/useNotificationStore.js";
import { quoteSchema } from "@/lib/validators.js";
import { spreadInfo } from "@/lib/quotes.js";
import { formatPrice } from "@/lib/formatters.js";
import { ApiError } from "@/api/apiFetch.js";

const fieldCls =
  "bg-[#1a1a28] border border-[#2a2a45] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[#3a3a60]";

export interface QuoteFormInitial {
  quote_id?: string;
  bid_price?: number | null;
  bid_qty?: number | null;
  ask_price?: number | null;
  ask_qty?: number | null;
  tif?: "DAY" | "GTC";
}

interface NewQuoteFormProps {
  symbol: string;
  tickDecimals: number;
  initial?: QuoteFormInitial;
  onDone: () => void;
}

const numStr = (v: number | null | undefined) => (v == null ? "" : String(v));

/**
 * New Quote form (§14.2), rendered inline inside a quote card. Two-sided quote
 * with a live spread indicator; submits to `POST /api/v1/quotes`. Selecting this
 * card's symbol also sets the active symbol so the MM's chart/DOM follow it.
 * The Quote ID field is auto-focused on open (the F2 target, §14.2).
 */
export function NewQuoteForm({ symbol, tickDecimals, initial, onDone }: NewQuoteFormProps) {
  const submit = useSubmitQuoteMutation();
  const setActiveSymbol = useActiveSymbolStore((s) => s.setActiveSymbol);
  const pushNotification = useNotificationStore((s) => s.push);
  const quoteIdRef = useRef<HTMLInputElement>(null);

  const [quoteId, setQuoteId] = useState(
    initial?.quote_id || `mm-${symbol.toLowerCase()}-${Date.now().toString(36)}`,
  );
  const [bidPrice, setBidPrice] = useState(numStr(initial?.bid_price));
  const [bidQty, setBidQty] = useState(numStr(initial?.bid_qty) || "500");
  const [askPrice, setAskPrice] = useState(numStr(initial?.ask_price));
  const [askQty, setAskQty] = useState(numStr(initial?.ask_qty) || "500");
  const [tif, setTif] = useState<"DAY" | "GTC">(initial?.tif ?? "DAY");
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Editing a quote implies focusing this symbol across the app (§14.2).
  useEffect(() => {
    setActiveSymbol(symbol);
    quoteIdRef.current?.focus();
    quoteIdRef.current?.select();
  }, [symbol, setActiveSymbol]);

  const spread = useMemo(() => {
    const b = parseFloat(bidPrice);
    const a = parseFloat(askPrice);
    return spreadInfo(Number.isFinite(b) ? b : null, Number.isFinite(a) ? a : null, tickDecimals);
  }, [bidPrice, askPrice, tickDecimals]);

  const doSubmit = () => {
    setErrors({});
    const parsed = quoteSchema.safeParse({
      symbol,
      bid_price: bidPrice,
      bid_qty: bidQty,
      ask_price: askPrice,
      ask_qty: askQty,
      tif,
      quote_id: quoteId.trim(),
    });
    if (!parsed.success) {
      const next: Record<string, string> = {};
      for (const issue of parsed.error.issues) next[issue.path.join(".")] ??= issue.message;
      setErrors(next);
      return;
    }
    const d = parsed.data;
    submit.mutate(
      {
        symbol: d.symbol.toUpperCase(),
        bid_price: d.bid_price,
        bid_qty: d.bid_qty,
        ask_price: d.ask_price,
        ask_qty: d.ask_qty,
        tif: d.tif,
        quote_id: d.quote_id,
      },
      {
        onSuccess: (res) => {
          // PendingIdResponse.id echoes the quote_id (key is `id`, not quote_id).
          toast(`Quote ${res.id} submitted`);
          pushNotification({
            ts: Date.now(),
            kind: "ACK",
            title: `Quote ${res.id} submitted`,
            detail: `${d.symbol} · ${d.bid_price} × ${d.bid_qty} / ${d.ask_price} × ${d.ask_qty}`,
          });
          onDone();
        },
        onError: (err) => {
          const msg = err instanceof ApiError ? `${err.code}: ${err.message}` : "Quote submission failed";
          setErrors({ _form: msg });
          toast.error(msg);
        },
      },
    );
  };

  return (
    <div className="mt-2 flex flex-col gap-2 border-t border-[#2a2a45] pt-2">
      <label className="flex flex-col gap-0.5">
        <span className="text-[10px] text-[#505070]">Quote ID</span>
        <input
          ref={quoteIdRef}
          value={quoteId}
          onChange={(e) => setQuoteId(e.target.value)}
          aria-label="Quote ID"
          className={fieldCls}
        />
        {errors.quote_id && <span className="text-[10px] text-ask">{errors.quote_id}</span>}
      </label>

      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-bid">Bid price</span>
          <input
            type="number"
            step="any"
            value={bidPrice}
            onChange={(e) => setBidPrice(e.target.value)}
            aria-label="Bid price"
            className={fieldCls}
          />
          {errors.bid_price && <span className="text-[10px] text-ask">{errors.bid_price}</span>}
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-bid">Bid qty</span>
          <input
            type="number"
            min={1}
            value={bidQty}
            onChange={(e) => setBidQty(e.target.value)}
            aria-label="Bid qty"
            className={fieldCls}
          />
          {errors.bid_qty && <span className="text-[10px] text-ask">{errors.bid_qty}</span>}
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-ask">Ask price</span>
          <input
            type="number"
            step="any"
            value={askPrice}
            onChange={(e) => setAskPrice(e.target.value)}
            aria-label="Ask price"
            className={fieldCls}
          />
          {errors.ask_price && <span className="text-[10px] text-ask">{errors.ask_price}</span>}
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-ask">Ask qty</span>
          <input
            type="number"
            min={1}
            value={askQty}
            onChange={(e) => setAskQty(e.target.value)}
            aria-label="Ask qty"
            className={fieldCls}
          />
          {errors.ask_qty && <span className="text-[10px] text-ask">{errors.ask_qty}</span>}
        </label>
      </div>

      <div className="flex items-center justify-between">
        <label className="flex items-center gap-1">
          <span className="text-[10px] text-[#505070]">TIF</span>
          <select
            value={tif}
            onChange={(e) => setTif(e.target.value as "DAY" | "GTC")}
            aria-label="Quote TIF"
            className={fieldCls}
          >
            <option value="DAY">DAY</option>
            <option value="GTC">GTC</option>
          </select>
        </label>
        <span className="text-[10px] text-[#9090b0]" aria-label="spread indicator">
          {spread
            ? `Spread: ${formatPrice(spread.currency, tickDecimals)} (${spread.ticks} ticks)`
            : "Spread: —"}
        </span>
      </div>

      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onDone}
          className="rounded border border-[#2a2a45] px-2 py-1 text-[11px] text-[#9090b0] hover:text-[#e8e8f0]"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={doSubmit}
          disabled={submit.isPending}
          className="rounded bg-[#3a3a60] px-3 py-1 text-[11px] font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          Submit Quote
        </button>
      </div>

      {errors._form && <p className="text-[11px] text-ask">{errors._form}</p>}
    </div>
  );
}

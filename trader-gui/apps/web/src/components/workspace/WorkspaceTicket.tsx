import { useEffect, useState } from "react";
import { useSubmitOrderMutation } from "@/queries/index.js";
import { useTicketPrefillStore } from "@/store/useTicketPrefillStore.js";
import { useNotificationStore } from "@/store/useNotificationStore.js";
import { orderSchema } from "@/lib/validators.js";
import { ApiError } from "@/api/apiFetch.js";
import type { Side } from "@/types/index.js";

type CompactOrderType = "LIMIT" | "MARKET";

interface WorkspaceTicketProps {
  symbol: string;
  tickDecimals: number;
}

/**
 * Compact order ticket for the Trading Workspace bottom-left quadrant (§11.2).
 *
 * Its symbol is locked to the active symbol. Clicking a DOM level pre-fills
 * the price (and suggests a side) via the shared ticket-prefill store (§11.4).
 * This is the compact subset — LIMIT/MARKET with dual BUY/SELL buttons; the
 * full 8-type ticket with TIF-phase restrictions and the auction banner is
 * phase 6.
 */
export function WorkspaceTicket({ symbol, tickDecimals }: WorkspaceTicketProps) {
  const [orderType, setOrderType] = useState<CompactOrderType>("LIMIT");
  const [qty, setQty] = useState("100");
  const [price, setPrice] = useState("");
  const [tif, setTif] = useState<"DAY" | "GTC">("DAY");
  const [suggestedSide, setSuggestedSide] = useState<Side | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [okMsg, setOkMsg] = useState<string | null>(null);

  const prefill = useTicketPrefillStore((s) => s.prefill);
  const submit = useSubmitOrderMutation();
  const pushNotification = useNotificationStore((s) => s.push);

  // Apply a click-to-trade prefill for this symbol. Keyed on the prefill nonce
  // so re-clicking the same level still refreshes the ticket.
  useEffect(() => {
    if (!prefill || prefill.symbol !== symbol) return;
    setOrderType("LIMIT");
    setPrice(prefill.price.toFixed(tickDecimals));
    setSuggestedSide(prefill.side);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill?.nonce]);

  const doSubmit = (side: Side) => {
    setError(null);
    setOkMsg(null);
    const candidate = {
      symbol,
      side,
      order_type: orderType,
      quantity: qty,
      tif,
      ...(orderType === "LIMIT" ? { price } : {}),
    };
    const parsed = orderSchema.safeParse(candidate);
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? "Invalid order");
      return;
    }
    // MARKET must not carry a price (engine rejects it); LIMIT keeps it.
    const body: Record<string, unknown> = {
      symbol: parsed.data.symbol,
      side: parsed.data.side,
      order_type: parsed.data.order_type,
      quantity: parsed.data.quantity,
      tif: parsed.data.tif,
    };
    if (parsed.data.order_type === "LIMIT") body.price = parsed.data.price;

    submit.mutate(body, {
      onSuccess: (res) => {
        setOkMsg(`${side} ${parsed.data.quantity} ${symbol} submitted`);
        pushNotification({
          ts: Date.now(),
          kind: "ACK",
          title: `${side} ${symbol} submitted`,
          detail: `${orderType} · order ${res.order_id.slice(0, 8)}`,
          orderId: res.order_id,
        });
      },
      onError: (err) => {
        setError(
          err instanceof ApiError ? `${err.code}: ${err.message}` : "Order submission failed",
        );
      },
    });
  };

  const sideBtn = (side: Side) => {
    const isBuy = side === "BUY";
    const suggested = suggestedSide === side;
    return (
      <button
        type="button"
        onClick={() => doSubmit(side)}
        disabled={submit.isPending}
        aria-keyshortcuts={isBuy ? "b" : "s"}
        className={`flex-1 py-2 rounded text-sm font-semibold text-white disabled:opacity-50 ${
          isBuy ? "bg-bid hover:brightness-110" : "bg-ask hover:brightness-110"
        } ${suggested ? "ring-2 ring-offset-1 ring-offset-[#0d0d14] ring-white/70" : ""}`}
      >
        {side}
      </button>
    );
  };

  const field = "bg-[#1a1a28] border border-[#2a2a45] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[#3a3a60]";

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-xs text-[#9090b0]">Order Ticket</span>
        <span className="font-mono text-xs text-[#e8e8f0]">{symbol}</span>
        <span className="ml-auto text-[10px] text-[#505070]">compact</span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-[#505070]">Type</span>
          <select
            value={orderType}
            onChange={(e) => setOrderType(e.target.value as CompactOrderType)}
            aria-label="Order type"
            className={field}
          >
            <option value="LIMIT">LIMIT</option>
            <option value="MARKET">MARKET</option>
          </select>
        </label>

        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-[#505070]">TIF</span>
          <select
            value={tif}
            onChange={(e) => setTif(e.target.value as "DAY" | "GTC")}
            aria-label="Time in force"
            className={field}
          >
            <option value="DAY">DAY</option>
            <option value="GTC">GTC</option>
          </select>
        </label>

        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-[#505070]">Quantity</span>
          <input
            type="number"
            min={1}
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            aria-label="Quantity"
            className={field}
          />
        </label>

        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-[#505070]">Price</span>
          <input
            type="number"
            step="any"
            value={price}
            disabled={orderType === "MARKET"}
            onChange={(e) => setPrice(e.target.value)}
            aria-label="Price"
            placeholder={orderType === "MARKET" ? "—" : "0.00"}
            className={`${field} disabled:opacity-40`}
          />
        </label>
      </div>

      <div className="flex gap-2">
        {sideBtn("BUY")}
        {sideBtn("SELL")}
      </div>

      {error && <p className="text-[11px] text-ask">{error}</p>}
      {okMsg && !error && <p className="text-[11px] text-bid">{okMsg}</p>}
    </div>
  );
}

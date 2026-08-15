import { useEffect, useId, useRef, useState } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import { toast } from "sonner";
import { useSubmitOrderMutation } from "@/queries/index.js";
import { useOrderFields } from "@/hooks/useOrderFields.js";
import { useEventCallback } from "@/hooks/useEventCallback.js";
import { usePriceHint } from "@/hooks/usePriceHint.js";
import { useSessionStore } from "@/store/useSessionStore.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";
import { useActiveSymbolStore } from "@/store/useActiveSymbolStore.js";
import { useTicketPrefillStore } from "@/store/useTicketPrefillStore.js";
import { useNotificationStore } from "@/store/useNotificationStore.js";
import { orderSchema } from "@/lib/validators.js";
import { ALLOWED_TIF } from "@/lib/sessionState.js";
import { ApiError } from "@/api/apiFetch.js";
import { FieldInfo } from "@/components/shared/FieldInfo.js";
import type { OrderType, Side, Tif, SmpAction } from "@/types/index.js";

interface OrderTicketProps {
  /** Compact quadrant styling for the Trading Workspace (§11.2). */
  compact?: boolean;
  /** When set, the symbol is fixed (Workspace mode) and the picker is hidden. */
  lockedSymbol?: string;
  /** Decimals for formatting a click-to-trade prefill price. */
  tickDecimals?: number;
}

const TABS: { type: OrderType; label: string }[] = [
  { type: "MARKET", label: "Market" },
  { type: "LIMIT", label: "Limit" },
  { type: "STOP", label: "Stop" },
  { type: "STOP_LIMIT", label: "Stop-Limit" },
  { type: "FOK", label: "FOK" },
  { type: "ICEBERG", label: "Iceberg" },
  { type: "IOC", label: "IOC" },
  { type: "TRAILING_STOP", label: "Trailing Stop" },
];

/** Order types the engine rejects during a call auction (FR-ENG-030, §12.10). */
const AUCTION_DISABLED: OrderType[] = ["MARKET", "FOK", "IOC"];

const ALL_TIF: Tif[] = ["DAY", "GTC", "ATO", "ATC"];
const SMP_OPTIONS: SmpAction[] = ["NONE", "CANCEL_AGGRESSOR", "CANCEL_RESTING", "CANCEL_BOTH"];

const fieldCls =
  "bg-[#1a1a28] border border-[#2a2a45] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[#3a3a60] disabled:opacity-40";

/**
 * The single-leg Order Ticket (§12) — the one shared ticket used both by the
 * standalone Order Entry screen (full) and the Trading Workspace bottom-left
 * quadrant (`compact`, symbol locked to the active symbol).
 *
 * All 8 single-leg order types, side-agnostic Zod validation with the `side`
 * injected by the BUY/SELL button pressed, TIF options gated by session phase
 * (§12.5), an auction banner that disables continuous-only types (§12.10), a
 * reference-price hint, click-to-trade prefill, and `B`/`S` hotkeys (§12.11).
 *
 * Submits with `?wait=ack` so the first `order.ack` folds into the HTTP
 * response, giving a synchronous accepted/rejected verdict (§12.9) surfaced as
 * a toast and an Event Center entry. OCO/Combo (§12.7–8) and the blotter (§13)
 * are later phases.
 */
export function OrderTicket({ compact = false, lockedSymbol, tickDecimals = 2 }: OrderTicketProps) {
  const [orderType, setOrderType] = useState<OrderType>("LIMIT");
  const [typedSymbol, setTypedSymbol] = useState("");
  const [qty, setQty] = useState("100");
  const [price, setPrice] = useState("");
  const [stopPrice, setStopPrice] = useState("");
  const [visibleQty, setVisibleQty] = useState("");
  const [trailOffset, setTrailOffset] = useState("");
  const [tif, setTif] = useState<Tif>("DAY");
  const [smp, setSmp] = useState<SmpAction | "">("");
  const [clientOrderId, setClientOrderId] = useState("");
  const [suggestedSide, setSuggestedSide] = useState<Side | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const fields = useOrderFields(orderType);
  const phase = useSessionStore((s) => s.phase);
  const symbols = useSymbolStore((s) => s.symbols);
  const setActiveSymbol = useActiveSymbolStore((s) => s.setActiveSymbol);
  const prefill = useTicketPrefillStore((s) => s.prefill);
  const pushNotification = useNotificationStore((s) => s.push);
  const submit = useSubmitOrderMutation();

  const symbol = (lockedSymbol ?? typedSymbol).toUpperCase();
  // Live anchor for the "Ref:" hint (last trade → mid → prev_close); traders
  // have no per-symbol reference price over REST (see usePriceHint / §12.6).
  const refPrice = usePriceHint(symbol || null);

  const allowedTif = ALLOWED_TIF[phase];
  const isAuction = phase === "OPENING_AUCTION" || phase === "CLOSING_AUCTION";
  const isClosed = phase === "CLOSED";
  const typeBlockedByAuction = isAuction && AUCTION_DISABLED.includes(orderType);
  const symbolInputId = useId();
  const symbolFieldRef = useRef<HTMLInputElement>(null);
  const qtyFieldRef = useRef<HTMLInputElement>(null);

  // Keep the selected TIF valid for the current phase: if the phase change made
  // it illegal (e.g. leaving OPENING_AUCTION drops ATO), fall back to the first
  // allowed value so we never submit a TIF the engine will reject.
  useEffect(() => {
    if (allowedTif.length > 0 && !allowedTif.includes(tif)) {
      setTif(allowedTif[0]!);
    }
  }, [allowedTif, tif]);

  // A continuous-only type selected as we enter an auction: fall back to LIMIT
  // (always valid) so the ticket stays submittable instead of dead-ended.
  useEffect(() => {
    if (isAuction && AUCTION_DISABLED.includes(orderType)) {
      setOrderType("LIMIT");
    }
  }, [isAuction, orderType]);

  // Click-to-trade prefill (§11.4): a DOM level click records price + side.
  // Keyed on the nonce so re-clicking the same level still refreshes.
  useEffect(() => {
    if (!prefill || prefill.symbol !== symbol) return;
    setOrderType("LIMIT");
    setPrice(prefill.price.toFixed(tickDecimals));
    setSuggestedSide(prefill.side);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill?.nonce]);

  const canSubmit = !submit.isPending && !isClosed && !typeBlockedByAuction;

  const doSubmit = (side: Side) => {
    setErrors({});
    if (isClosed) {
      setErrors({ _form: "Market is closed — no orders accepted" });
      return;
    }
    if (typeBlockedByAuction) {
      setErrors({ _form: `${orderType} orders are not accepted during an auction` });
      return;
    }

    const candidate: Record<string, unknown> = {
      symbol,
      side,
      order_type: orderType,
      quantity: qty,
      tif,
    };
    if (fields.price && price !== "") candidate.price = price;
    if (fields.stop_price && stopPrice !== "") candidate.stop_price = stopPrice;
    if (fields.visible_qty && visibleQty !== "") candidate.visible_qty = visibleQty;
    if (fields.trail_offset && trailOffset !== "") candidate.trail_offset = trailOffset;
    // Omit smp_action unless actively chosen — an absent field lets the gateway
    // apply its configured SMP default, distinct from an explicit "NONE" (§12.4).
    if (smp !== "") candidate.smp_action = smp;
    if (clientOrderId.trim() !== "") candidate.client_order_id = clientOrderId.trim();

    const parsed = orderSchema.safeParse(candidate);
    if (!parsed.success) {
      const next: Record<string, string> = {};
      for (const issue of parsed.error.issues) {
        const key = String(issue.path[0] ?? "_form");
        next[key] ??= issue.message;
      }
      setErrors(next);
      return;
    }

    const d = parsed.data;
    // Mirror the gateway's strict model: uppercased symbol, only the fields the
    // type actually uses, and smp/client_order_id only when present.
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
    if (d.client_order_id) body.client_order_id = d.client_order_id;

    submit.mutate(
      { body, wait: "ack" },
      {
        onSuccess: (res) => {
          const id8 = res.order_id.slice(0, 8);
          // Transient fields are cleared; symbol/qty/price stay so the trader
          // can immediately act on the other side (§12.9 step 7).
          setClientOrderId("");
          if (res.accepted === false) {
            const reason = res.event?.reason || "order rejected";
            toast.error(`REJECTED: ${reason}`);
            pushNotification({
              ts: Date.now(),
              kind: "REJECT",
              title: `${side} ${symbol} rejected`,
              detail: `${orderType} · ${reason}`,
              orderId: res.order_id,
            });
            return;
          }
          if (res.accepted === true) {
            toast.success(`${side} ${d.quantity} ${symbol} accepted`);
            pushNotification({
              ts: Date.now(),
              kind: "ACK",
              title: `${side} ${symbol} accepted`,
              detail: `${orderType} · order ${id8}`,
              orderId: res.order_id,
            });
            return;
          }
          // accepted == null → gateway returned status PENDING without waiting
          // (only happens if wait=ack was omitted). Defensive; the ticket always
          // waits, so a genuine ack timeout arrives on the onError path as a 503.
          toast(`${side} ${symbol} submitted — pending ACK`);
          pushNotification({
            ts: Date.now(),
            kind: "ACK",
            title: `${side} ${symbol} submitted`,
            detail: `${orderType} · order ${id8} · pending ACK`,
            orderId: res.order_id,
          });
        },
        onError: (err) => {
          // A wait=ack timeout is 503 ENGINE_TIMEOUT — NOT a rejection. The order
          // was already sent to the engine (send_new_order fired) and may be
          // working; only the ack didn't return in time (§12.9 step 6). Surface
          // "awaiting confirmation" so the trader reconciles via the blotter
          // rather than resubmitting a possibly-live order.
          if (err instanceof ApiError && (err.status === 503 || err.code === "ENGINE_TIMEOUT")) {
            toast(`${side} ${symbol} submitted — awaiting confirmation (check blotter)`);
            pushNotification({
              ts: Date.now(),
              kind: "ACK",
              title: `${side} ${symbol} — awaiting ACK`,
              detail: `${orderType} · no ack yet; reconcile via the blotter`,
            });
            return;
          }
          const msg =
            err instanceof ApiError ? `${err.code}: ${err.message}` : "Order submission failed";
          setErrors({ _form: msg });
          toast.error(msg);
          pushNotification({
            ts: Date.now(),
            kind: "REJECT",
            title: `${side} ${symbol} failed`,
            detail: msg,
          });
        },
      },
    );
  };

  // Route the B/S handlers through a latest-ref stable callback so they always
  // run the current closure (order type / fields / phase). react-hotkeys-hook
  // freezes a stale callback when given a deps array; useEventCallback makes
  // that irrelevant. enableOnFormTags:false gives the §12.11 "ignore
  // input/textarea/select" behaviour so the explicit buttons stay unambiguous.
  const submitBuy = useEventCallback(() => canSubmit && doSubmit("BUY"));
  const submitSell = useEventCallback(() => canSubmit && doSubmit("SELL"));
  useHotkeys("b", submitBuy, { enableOnFormTags: false });
  useHotkeys("s", submitSell, { enableOnFormTags: false });
  // F1 focuses the ticket's first field from anywhere; Escape clears errors.
  useHotkeys("f1", () => (lockedSymbol ? qtyFieldRef : symbolFieldRef).current?.focus(), {
    enableOnFormTags: true,
    preventDefault: true,
  });
  useHotkeys(
    "escape",
    () => {
      setErrors({});
      (document.activeElement as HTMLElement | null)?.blur();
    },
    { enableOnFormTags: true },
  );

  const tabDisabled = (t: OrderType) => isAuction && AUCTION_DISABLED.includes(t);

  const sideBtn = (side: Side) => {
    const isBuy = side === "BUY";
    const suggested = suggestedSide === side;
    const disabledReason = isClosed
      ? "Market is closed"
      : typeBlockedByAuction
        ? `${orderType} not accepted during an auction`
        : undefined;
    return (
      <button
        type="button"
        onClick={() => doSubmit(side)}
        disabled={!canSubmit}
        title={disabledReason}
        aria-keyshortcuts={isBuy ? "b" : "s"}
        className={`flex-1 py-2 rounded text-sm font-semibold text-white disabled:opacity-40 disabled:cursor-not-allowed ${
          isBuy ? "bg-bid hover:brightness-110" : "bg-ask hover:brightness-110"
        } ${suggested ? "ring-2 ring-offset-1 ring-offset-[#0d0d14] ring-white/70" : ""}`}
      >
        {side}
      </button>
    );
  };

  const labelledField = (
    label: string,
    input: React.ReactNode,
    errorKey?: string,
    info?: React.ReactNode,
  ) => (
    // A <div> (not <label>): each input already carries its own aria-label, and
    // wrapping a <label> around both the input and the FieldInfo button would
    // make the label associate with the button instead of the input.
    <div className="flex flex-col gap-0.5">
      <span className="flex items-center gap-1 text-[10px] text-[#505070]">
        {label}
        {info}
      </span>
      {input}
      {errorKey && errors[errorKey] && (
        <span className="text-[10px] text-ask">{errors[errorKey]}</span>
      )}
    </div>
  );

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold text-[#e8e8f0]">Order Ticket</span>
        {lockedSymbol && <span className="font-mono text-xs text-[#9090b0]">{lockedSymbol}</span>}
        <span className="ml-auto text-[10px] text-[#505070]">{compact ? "compact" : "F1 to focus"}</span>
      </div>

      {/* Order-type tabs (§12.3) */}
      <div className="flex flex-wrap gap-1" role="tablist" aria-label="Order type">
        {TABS.map(({ type, label }) => {
          const active = orderType === type;
          const disabled = tabDisabled(type);
          return (
            <button
              key={type}
              type="button"
              role="tab"
              aria-selected={active}
              disabled={disabled}
              title={disabled ? "Not available during an auction" : undefined}
              onClick={() => setOrderType(type)}
              className={`px-2 py-1 rounded text-[11px] font-medium disabled:opacity-30 disabled:cursor-not-allowed ${
                active
                  ? "bg-[#3a3a60] text-white"
                  : "bg-[#1a1a28] text-[#9090b0] hover:bg-[#22223a]"
              }`}
            >
              {label}
            </button>
          );
        })}
      </div>

      {/* Auction banner (§12.10) */}
      {isAuction && (
        <div className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-[11px] text-amber-300">
          <strong>Auction phase</strong> — orders rest and match at the uncross. No continuous
          matching now; market/FOK/IOC are disabled.
        </div>
      )}
      {isClosed && (
        <div className="rounded border border-red-500/40 bg-red-500/10 px-2 py-1.5 text-[11px] text-red-300">
          <strong>Market closed</strong> — orders are not accepted in this phase.
        </div>
      )}

      <div className="grid grid-cols-2 gap-2">
        {/* Symbol — combobox (full) or locked label (workspace) */}
        {lockedSymbol
          ? labelledField(
              "Symbol",
              <input
                value={lockedSymbol}
                readOnly
                aria-label="Symbol"
                className={`${fieldCls} opacity-70`}
              />,
              undefined,
              <FieldInfo label="Symbol" lines={["Locked to the workspace's active symbol."]} />,
            )
          : labelledField(
              "Symbol",
              <>
                <input
                  ref={symbolFieldRef}
                  list={symbolInputId}
                  value={typedSymbol}
                  onChange={(e) => {
                    const v = e.target.value.toUpperCase();
                    setTypedSymbol(v);
                    if (symbols.some((s) => s.symbol === v)) setActiveSymbol(v);
                  }}
                  aria-label="Symbol"
                  placeholder="AAPL"
                  className={fieldCls}
                />
                <datalist id={symbolInputId}>
                  {symbols.map((s) => (
                    <option key={s.symbol} value={s.symbol} />
                  ))}
                </datalist>
              </>,
              "symbol",
              <FieldInfo
                label="Symbol"
                lines={["Required. The instrument to trade.", "Pick from the list, e.g. AAPL."]}
              />,
            )}

        {labelledField(
          "Quantity",
          <input
            ref={qtyFieldRef}
            type="number"
            min={1}
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            aria-label="Quantity"
            className={fieldCls}
          />,
          "quantity",
          <FieldInfo
            label="Quantity"
            lines={["Required. Whole number of shares.", "Must be a positive integer, e.g. 100."]}
          />,
        )}

        {fields.price &&
          labelledField(
            "Price",
            <input
              type="number"
              step="any"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              aria-label="Price"
              placeholder={refPrice !== null ? `Ref: ${refPrice.toFixed(tickDecimals)}` : "0.00"}
              className={fieldCls}
            />,
            "price",
            <FieldInfo
              label="Price"
              lines={[
                `Required for ${orderType} orders.`,
                "The limit: max buy / min sell price.",
                "Enter as a decimal, e.g. 150.25.",
                refPrice !== null ? `Reference: ${refPrice.toFixed(tickDecimals)}` : "Reference: —",
              ]}
            />,
          )}

        {fields.stop_price &&
          labelledField(
            "Stop price",
            <input
              type="number"
              step="any"
              value={stopPrice}
              onChange={(e) => setStopPrice(e.target.value)}
              aria-label="Stop price"
              className={fieldCls}
            />,
            "stop_price",
            <FieldInfo
              label="Stop price"
              lines={["Required for STOP / STOP_LIMIT.", "The trigger price; the order activates once reached."]}
            />,
          )}

        {fields.visible_qty &&
          labelledField(
            "Visible qty",
            <input
              type="number"
              min={1}
              value={visibleQty}
              onChange={(e) => setVisibleQty(e.target.value)}
              aria-label="Visible quantity"
              className={fieldCls}
            />,
            "visible_qty",
            <FieldInfo
              label="Visible qty"
              lines={["Required for ICEBERG.", "The slice shown on the book; must be less than the total quantity."]}
            />,
          )}

        {fields.trail_offset &&
          labelledField(
            "Trail offset",
            <input
              type="number"
              step="any"
              value={trailOffset}
              onChange={(e) => setTrailOffset(e.target.value)}
              aria-label="Trail offset"
              className={fieldCls}
            />,
            "trail_offset",
            <FieldInfo
              label="Trail offset"
              lines={["Required for TRAILING_STOP.", "Distance the stop trails behind the price."]}
            />,
          )}

        {fields.tif &&
          labelledField(
            "TIF",
            <select
              value={tif}
              onChange={(e) => setTif(e.target.value as Tif)}
              aria-label="Time in force"
              className={fieldCls}
            >
              {ALL_TIF.map((t) => (
                <option key={t} value={t} disabled={!allowedTif.includes(t)}>
                  {t}
                  {allowedTif.includes(t) ? "" : " (n/a this phase)"}
                </option>
              ))}
            </select>,
            undefined,
            <FieldInfo
              label="Time in force"
              lines={[
                "How long the order stays live.",
                "DAY / GTC always; ATO opening auction; ATC closing auction.",
                "Only values valid this phase are selectable.",
              ]}
            />,
          )}

        {labelledField(
          "SMP",
          <select
            value={smp}
            onChange={(e) => setSmp(e.target.value as SmpAction | "")}
            aria-label="SMP action"
            className={fieldCls}
          >
            <option value="">Gateway default</option>
            {SMP_OPTIONS.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>,
          undefined,
          <FieldInfo
            label="SMP action"
            lines={[
              "Optional self-match prevention.",
              "Leave as Gateway default unless you need a specific policy.",
            ]}
          />,
        )}
      </div>

      {!compact &&
        labelledField(
          "Client Order ID (optional)",
          <input
            value={clientOrderId}
            onChange={(e) => setClientOrderId(e.target.value)}
            aria-label="Client order ID"
            maxLength={64}
            placeholder="optional idempotency key"
            className={fieldCls}
          />,
          "client_order_id",
        )}

      <div className="flex gap-2">
        {sideBtn("BUY")}
        {sideBtn("SELL")}
      </div>

      {errors._form && <p className="text-[11px] text-ask">{errors._form}</p>}
    </div>
  );
}

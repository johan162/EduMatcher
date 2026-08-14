import { useState } from "react";
import { toast } from "sonner";
import { useSubmitOcoMutation } from "@/queries/index.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";
import { useActiveSymbolStore } from "@/store/useActiveSymbolStore.js";
import { useNotificationStore } from "@/store/useNotificationStore.js";
import { ocoSchema } from "@/lib/validators.js";
import { ApiError } from "@/api/apiFetch.js";
import type { Side } from "@/types/index.js";

const fieldCls =
  "bg-[#1a1a28] border border-[#2a2a45] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[#3a3a60]";

type LegType = "LIMIT" | "STOP";

interface LegState {
  side: Side;
  order_type: LegType;
  price: string;
  stop_price: string;
}

const emptyLeg = (side: Side): LegState => ({ side, order_type: "LIMIT", price: "", stop_price: "" });

/**
 * OCO Order Entry sub-panel (§12.7). Two legs (LIMIT/STOP each), one shared
 * symbol/quantity/TIF, submitted to `POST /api/v1/oco`. The resulting pair is
 * shown as a group in the blotter (§13.3). A default OCO id is generated so a
 * classroom user is not forced to invent one, but it stays editable.
 */
export function OcoForm() {
  const symbols = useSymbolStore((s) => s.symbols);
  const activeSymbol = useActiveSymbolStore((s) => s.activeSymbol);
  const setActiveSymbol = useActiveSymbolStore((s) => s.setActiveSymbol);
  const pushNotification = useNotificationStore((s) => s.push);
  const submit = useSubmitOcoMutation();

  const [ocoId, setOcoId] = useState(() => `oco-${Date.now().toString(36)}`);
  const [symbol, setSymbol] = useState(activeSymbol ?? "");
  const [qty, setQty] = useState("100");
  const [tif, setTif] = useState<"DAY" | "GTC">("DAY");
  const [leg1, setLeg1] = useState<LegState>(emptyLeg("SELL"));
  const [leg2, setLeg2] = useState<LegState>(emptyLeg("SELL"));
  const [errors, setErrors] = useState<Record<string, string>>({});

  const legPatch = (raw: LegState) => ({
    side: raw.side,
    order_type: raw.order_type,
    ...(raw.order_type === "LIMIT" && raw.price !== "" ? { price: raw.price } : {}),
    ...(raw.order_type === "STOP" && raw.stop_price !== "" ? { stop_price: raw.stop_price } : {}),
  });

  const doSubmit = () => {
    setErrors({});
    const candidate = {
      oco_id: ocoId.trim(),
      symbol: symbol.toUpperCase(),
      quantity: qty,
      tif,
      leg1: legPatch(leg1),
      leg2: legPatch(leg2),
    };
    const parsed = ocoSchema.safeParse(candidate);
    if (!parsed.success) {
      const next: Record<string, string> = {};
      for (const issue of parsed.error.issues) {
        next[issue.path.join(".")] ??= issue.message;
      }
      setErrors(next);
      return;
    }
    const d = parsed.data;
    const body: Record<string, unknown> = {
      oco_id: d.oco_id,
      symbol: d.symbol.toUpperCase(),
      quantity: d.quantity,
      tif: d.tif,
      leg1: d.leg1,
      leg2: d.leg2,
    };
    submit.mutate(body, {
      onSuccess: (res) => {
        // PendingIdResponse.id echoes the submitted oco_id (the key is `id`).
        toast.success(`OCO ${res.id} submitted`);
        pushNotification({
          ts: Date.now(),
          kind: "ACK",
          title: `OCO ${res.id} submitted`,
          detail: `${d.symbol} · ${d.quantity} · ${d.leg1.order_type}/${d.leg2.order_type}`,
        });
        // Fresh id for the next pair.
        setOcoId(`oco-${Date.now().toString(36)}`);
      },
      onError: (err) => {
        const msg = err instanceof ApiError ? `${err.code}: ${err.message}` : "OCO submission failed";
        setErrors({ _form: msg });
        toast.error(msg);
      },
    });
  };

  const legEditor = (
    label: string,
    leg: LegState,
    setLeg: (l: LegState) => void,
    keyPrefix: string,
  ) => (
    <fieldset className="rounded border border-[#2a2a45] p-2">
      <legend className="px-1 text-[10px] text-[#9090b0]">{label}</legend>
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-[#505070]">Side</span>
          <select
            value={leg.side}
            onChange={(e) => setLeg({ ...leg, side: e.target.value as Side })}
            aria-label={`${label} side`}
            className={fieldCls}
          >
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-[#505070]">Type</span>
          <select
            value={leg.order_type}
            onChange={(e) => setLeg({ ...leg, order_type: e.target.value as LegType })}
            aria-label={`${label} type`}
            className={fieldCls}
          >
            <option value="LIMIT">LIMIT</option>
            <option value="STOP">STOP</option>
          </select>
        </label>
        {leg.order_type === "LIMIT" && (
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-[#505070]">Price</span>
            <input
              type="number"
              step="any"
              value={leg.price}
              onChange={(e) => setLeg({ ...leg, price: e.target.value })}
              aria-label={`${label} price`}
              className={fieldCls}
            />
            {errors[`${keyPrefix}.price`] && (
              <span className="text-[10px] text-ask">{errors[`${keyPrefix}.price`]}</span>
            )}
          </label>
        )}
        {leg.order_type === "STOP" && (
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-[#505070]">Stop price</span>
            <input
              type="number"
              step="any"
              value={leg.stop_price}
              onChange={(e) => setLeg({ ...leg, stop_price: e.target.value })}
              aria-label={`${label} stop price`}
              className={fieldCls}
            />
            {errors[`${keyPrefix}.stop_price`] && (
              <span className="text-[10px] text-ask">{errors[`${keyPrefix}.stop_price`]}</span>
            )}
          </label>
        )}
      </div>
    </fieldset>
  );

  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-[#505070]">OCO ID</span>
          <input
            value={ocoId}
            onChange={(e) => setOcoId(e.target.value)}
            aria-label="OCO ID"
            className={fieldCls}
          />
          {errors.oco_id && <span className="text-[10px] text-ask">{errors.oco_id}</span>}
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-[#505070]">Symbol</span>
          <input
            list="oco-symbols"
            value={symbol}
            onChange={(e) => {
              const v = e.target.value.toUpperCase();
              setSymbol(v);
              if (symbols.some((s) => s.symbol === v)) setActiveSymbol(v);
            }}
            aria-label="OCO symbol"
            placeholder="AAPL"
            className={fieldCls}
          />
          <datalist id="oco-symbols">
            {symbols.map((s) => (
              <option key={s.symbol} value={s.symbol} />
            ))}
          </datalist>
          {errors.symbol && <span className="text-[10px] text-ask">{errors.symbol}</span>}
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-[#505070]">Quantity</span>
          <input
            type="number"
            min={1}
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            aria-label="OCO quantity"
            className={fieldCls}
          />
          {errors.quantity && <span className="text-[10px] text-ask">{errors.quantity}</span>}
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-[#505070]">TIF</span>
          <select
            value={tif}
            onChange={(e) => setTif(e.target.value as "DAY" | "GTC")}
            aria-label="OCO TIF"
            className={fieldCls}
          >
            <option value="DAY">DAY</option>
            <option value="GTC">GTC</option>
          </select>
        </label>
      </div>

      {legEditor("Leg 1", leg1, setLeg1, "leg1")}
      {legEditor("Leg 2", leg2, setLeg2, "leg2")}

      <button
        type="button"
        onClick={doSubmit}
        disabled={submit.isPending}
        className="rounded bg-[#3a3a60] px-3 py-1.5 text-xs font-semibold text-white hover:brightness-110 disabled:opacity-50"
      >
        Submit OCO
      </button>

      {errors._form && <p className="text-[11px] text-ask">{errors._form}</p>}
    </div>
  );
}

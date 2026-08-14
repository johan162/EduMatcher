import { useState } from "react";
import { Plus, X } from "lucide-react";
import { toast } from "sonner";
import { useSubmitComboMutation } from "@/queries/index.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";
import { useNotificationStore } from "@/store/useNotificationStore.js";
import { comboSchema } from "@/lib/validators.js";
import { ApiError } from "@/api/apiFetch.js";
import type { Side } from "@/types/index.js";

const fieldCls =
  "bg-[#1a1a28] border border-[#2a2a45] rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[#3a3a60]";

type LegType = "LIMIT" | "MARKET";

interface LegState {
  symbol: string;
  side: Side;
  order_type: LegType;
  quantity: string;
  price: string;
}

const emptyLeg = (symbol = ""): LegState => ({
  symbol,
  side: "BUY",
  order_type: "LIMIT",
  quantity: "100",
  price: "",
});

const MAX_LEGS = 10;
const MIN_LEGS = 2;

/**
 * Combo Order Entry sub-panel (§12.8). A dynamic leg builder (2–10 legs), each
 * with symbol/side/type/qty/price, sharing a combo id, TIF and SMP; submitted
 * to `POST /api/v1/combos`. The resulting combo is shown as a group in the
 * blotter (§13.3).
 */
export function ComboForm() {
  const symbols = useSymbolStore((s) => s.symbols);
  const pushNotification = useNotificationStore((s) => s.push);
  const submit = useSubmitComboMutation();

  const [comboId, setComboId] = useState(() => `combo-${Date.now().toString(36)}`);
  const [tif, setTif] = useState<"DAY" | "GTC">("DAY");
  const [legs, setLegs] = useState<LegState[]>(() => [
    emptyLeg(symbols[0]?.symbol ?? ""),
    emptyLeg(symbols[0]?.symbol ?? ""),
  ]);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const setLeg = (i: number, patch: Partial<LegState>) =>
    setLegs((prev) => prev.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));

  const addLeg = () => setLegs((prev) => (prev.length < MAX_LEGS ? [...prev, emptyLeg(symbols[0]?.symbol ?? "")] : prev));
  const removeLeg = (i: number) =>
    setLegs((prev) => (prev.length > MIN_LEGS ? prev.filter((_, idx) => idx !== i) : prev));

  const doSubmit = () => {
    setErrors({});
    const candidate = {
      combo_id: comboId.trim(),
      combo_type: "AON" as const,
      tif,
      smp_action: "NONE" as const,
      legs: legs.map((l) => ({
        symbol: l.symbol.toUpperCase(),
        side: l.side,
        order_type: l.order_type,
        quantity: l.quantity,
        ...(l.order_type === "LIMIT" && l.price !== "" ? { price: l.price } : {}),
      })),
    };
    const parsed = comboSchema.safeParse(candidate);
    if (!parsed.success) {
      const next: Record<string, string> = {};
      for (const issue of parsed.error.issues) {
        next[issue.path.join(".")] ??= issue.message;
      }
      setErrors(next);
      return;
    }
    const d = parsed.data;
    submit.mutate(d as unknown as Record<string, unknown>, {
      onSuccess: (res) => {
        // PendingIdResponse.id echoes the submitted combo_id (the key is `id`).
        toast.success(`Combo ${res.id} submitted`);
        pushNotification({
          ts: Date.now(),
          kind: "ACK",
          title: `Combo ${res.id} submitted`,
          detail: `${d.legs.length} legs · ${d.tif}`,
        });
        setComboId(`combo-${Date.now().toString(36)}`);
      },
      onError: (err) => {
        const msg = err instanceof ApiError ? `${err.code}: ${err.message}` : "Combo submission failed";
        setErrors({ _form: msg });
        toast.error(msg);
      },
    });
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-[#505070]">Combo ID</span>
          <input
            value={comboId}
            onChange={(e) => setComboId(e.target.value)}
            aria-label="Combo ID"
            className={fieldCls}
          />
          {errors.combo_id && <span className="text-[10px] text-ask">{errors.combo_id}</span>}
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-[#505070]">TIF (all legs)</span>
          <select
            value={tif}
            onChange={(e) => setTif(e.target.value as "DAY" | "GTC")}
            aria-label="Combo TIF"
            className={fieldCls}
          >
            <option value="DAY">DAY</option>
            <option value="GTC">GTC</option>
          </select>
        </label>
      </div>

      <datalist id="combo-symbols">
        {symbols.map((s) => (
          <option key={s.symbol} value={s.symbol} />
        ))}
      </datalist>

      <div className="flex flex-col gap-1.5">
        {legs.map((leg, i) => (
          <div key={i} className="flex items-end gap-1.5 rounded border border-[#2a2a45] p-1.5">
            <label className="flex flex-1 flex-col gap-0.5">
              <span className="text-[10px] text-[#505070]">Symbol</span>
              <input
                list="combo-symbols"
                value={leg.symbol}
                onChange={(e) => setLeg(i, { symbol: e.target.value.toUpperCase() })}
                aria-label={`Leg ${i + 1} symbol`}
                placeholder="AAPL"
                className={fieldCls}
              />
              {errors[`legs.${i}.symbol`] && (
                <span className="text-[10px] text-ask">{errors[`legs.${i}.symbol`]}</span>
              )}
            </label>
            <label className="flex flex-col gap-0.5">
              <span className="text-[10px] text-[#505070]">Side</span>
              <select
                value={leg.side}
                onChange={(e) => setLeg(i, { side: e.target.value as Side })}
                aria-label={`Leg ${i + 1} side`}
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
                onChange={(e) => setLeg(i, { order_type: e.target.value as LegType })}
                aria-label={`Leg ${i + 1} type`}
                className={fieldCls}
              >
                <option value="LIMIT">LIMIT</option>
                <option value="MARKET">MARKET</option>
              </select>
            </label>
            <label className="flex w-16 flex-col gap-0.5">
              <span className="text-[10px] text-[#505070]">Qty</span>
              <input
                type="number"
                min={1}
                value={leg.quantity}
                onChange={(e) => setLeg(i, { quantity: e.target.value })}
                aria-label={`Leg ${i + 1} quantity`}
                className={fieldCls}
              />
              {errors[`legs.${i}.quantity`] && (
                <span className="text-[10px] text-ask">{errors[`legs.${i}.quantity`]}</span>
              )}
            </label>
            <label className="flex w-20 flex-col gap-0.5">
              <span className="text-[10px] text-[#505070]">Price</span>
              <input
                type="number"
                step="any"
                value={leg.price}
                disabled={leg.order_type === "MARKET"}
                onChange={(e) => setLeg(i, { price: e.target.value })}
                aria-label={`Leg ${i + 1} price`}
                className={`${fieldCls} disabled:opacity-40`}
              />
              {errors[`legs.${i}.price`] && (
                <span className="text-[10px] text-ask">{errors[`legs.${i}.price`]}</span>
              )}
            </label>
            <button
              type="button"
              onClick={() => removeLeg(i)}
              disabled={legs.length <= MIN_LEGS}
              aria-label={`Remove leg ${i + 1}`}
              title={legs.length <= MIN_LEGS ? "A combo needs at least two legs" : "Remove leg"}
              className="mb-1 text-[#9090b0] hover:text-ask disabled:opacity-30"
            >
              <X size={13} />
            </button>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={addLeg}
          disabled={legs.length >= MAX_LEGS}
          className="flex items-center gap-1 rounded border border-[#2a2a45] px-2 py-1 text-[11px] text-[#9090b0] hover:text-[#e8e8f0] disabled:opacity-40"
        >
          <Plus size={12} /> Add leg
        </button>
        <span className="text-[10px] text-[#505070]">
          {legs.length}/{MAX_LEGS} legs
        </span>
        <button
          type="button"
          onClick={doSubmit}
          disabled={submit.isPending}
          className="ml-auto rounded bg-[#3a3a60] px-3 py-1.5 text-xs font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          Submit Combo
        </button>
      </div>

      {errors.legs && <p className="text-[11px] text-ask">{errors.legs}</p>}
      {errors._form && <p className="text-[11px] text-ask">{errors._form}</p>}
    </div>
  );
}

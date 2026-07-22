import {
  COMBO_TYPES,
  ORDER_TYPES,
  SIDES,
  SMP_ACTIONS,
  TIF_VALUES,
  createCombo,
  type OrderType,
  type Side,
  type SmpAction,
  type Tif,
} from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import { uppercaseId } from "@/lib/format";
import { Panel } from "@/components/layout/Panel";
import { FieldRow } from "@/components/fields/FieldRow";
import { NumberInput, TextInput } from "@/components/fields/inputs";
import { Select } from "@/components/ui/Select";

export function CombosTab() {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);
  const symbolOptions = draft.symbolOrder.map((s) => ({ value: s, label: s }));

  return (
    <Panel
      tabId="combos"
      title="Combos (Seed Orders)"
      intro="Multi-leg startup seed orders. Each combo needs 2–10 legs across distinct symbols. Prices are entered as decimal display values and converted to ticks on export using each symbol's precision."
      actions={
        <button
          type="button"
          disabled={draft.symbolOrder.length < 2}
          onClick={() =>
            update((d) => {
              let i = d.combos.length + 1;
              let id = `COMBO${i}`;
              while (d.combos.some((c) => c.comboId === id)) id = `COMBO${++i}`;
              d.combos.push(createCombo(id));
            })
          }
          className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50"
          title={draft.symbolOrder.length < 2 ? "Add at least two symbols first" : undefined}
        >
          + Add combo
        </button>
      }
    >
      {draft.combos.length === 0 && (
        <p className="text-sm text-fg-subtle">No combos defined. Combos are optional startup seed strategies.</p>
      )}

      {draft.combos.map((combo, ci) => (
        <div key={ci} className="mt-4 rounded-md border border-border bg-surface p-4">
          <div className="mb-3 flex flex-wrap items-end gap-3">
            <label className="text-sm">
              <span className="mb-1 block font-medium">Combo ID</span>
              <TextInput
                aria-label="Combo ID"
                value={combo.comboId}
                onChange={(v) => update((d) => (d.combos[ci]!.comboId = v))}
                onBlur={() => update((d) => (d.combos[ci]!.comboId = uppercaseId(d.combos[ci]!.comboId)))}
                className="w-44"
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-medium">Type</span>
              <Select
                aria-label="Combo type"
                value={combo.comboType}
                onValueChange={(v) => update((d) => (d.combos[ci]!.comboType = v as (typeof COMBO_TYPES)[number]))}
                options={COMBO_TYPES.map((t) => ({ value: t, label: t }))}
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-medium">TIF</span>
              <Select
                aria-label="Combo TIF"
                value={combo.tif}
                onValueChange={(v) => update((d) => (d.combos[ci]!.tif = v as Tif))}
                options={TIF_VALUES.map((t) => ({ value: t, label: t }))}
              />
            </label>
            <button
              type="button"
              onClick={() => update((d) => d.combos.splice(ci, 1))}
              className="ml-auto rounded-md border border-border px-2 py-1 text-sm text-fg-subtle hover:text-error"
            >
              Remove combo
            </button>
          </div>

          <FieldRow label="Legs" path={`combos.${combo.comboId}.legs`} required>
            <div className="w-full overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase text-fg-subtle">
                  <tr>
                    <th className="px-2 py-1">Symbol</th>
                    <th className="px-2 py-1">Side</th>
                    <th className="px-2 py-1">Type</th>
                    <th className="px-2 py-1">Qty</th>
                    <th className="px-2 py-1">Price</th>
                    <th className="px-2 py-1">Stop</th>
                    <th className="px-2 py-1">SMP</th>
                    <th className="px-2 py-1" />
                  </tr>
                </thead>
                <tbody>
                  {combo.legs.map((leg, li) => (
                    <tr key={li}>
                      <td className="px-2 py-1">
                        <Select
                          aria-label={`Leg ${li + 1} symbol`}
                          value={leg.symbol}
                          onValueChange={(v) => update((d) => (d.combos[ci]!.legs[li]!.symbol = v))}
                          options={symbolOptions}
                        />
                      </td>
                      <td className="px-2 py-1">
                        <Select
                          aria-label={`Leg ${li + 1} side`}
                          value={leg.side}
                          onValueChange={(v) => update((d) => (d.combos[ci]!.legs[li]!.side = v as Side))}
                          options={SIDES.map((x) => ({ value: x, label: x }))}
                        />
                      </td>
                      <td className="px-2 py-1">
                        <Select
                          aria-label={`Leg ${li + 1} order type`}
                          value={leg.orderType}
                          onValueChange={(v) => update((d) => (d.combos[ci]!.legs[li]!.orderType = v as OrderType))}
                          options={ORDER_TYPES.map((x) => ({ value: x, label: x }))}
                        />
                      </td>
                      <td className="px-2 py-1">
                        <NumberInput
                          aria-label={`Leg ${li + 1} quantity`}
                          value={leg.quantity}
                          min={1}
                          onChange={(v) => update((d) => (d.combos[ci]!.legs[li]!.quantity = v ?? 0))}
                          className="w-20"
                        />
                      </td>
                      <td className="px-2 py-1">
                        <NumberInput
                          aria-label={`Leg ${li + 1} price`}
                          value={leg.price ?? undefined}
                          step={0.01}
                          onChange={(v) => update((d) => (d.combos[ci]!.legs[li]!.price = v ?? null))}
                          className="w-24"
                        />
                      </td>
                      <td className="px-2 py-1">
                        <NumberInput
                          aria-label={`Leg ${li + 1} stop price`}
                          value={leg.stopPrice ?? undefined}
                          step={0.01}
                          onChange={(v) => update((d) => (d.combos[ci]!.legs[li]!.stopPrice = v ?? null))}
                          className="w-24"
                        />
                      </td>
                      <td className="px-2 py-1">
                        <Select
                          aria-label={`Leg ${li + 1} SMP action`}
                          value={leg.smpAction}
                          onValueChange={(v) => update((d) => (d.combos[ci]!.legs[li]!.smpAction = v as SmpAction))}
                          options={SMP_ACTIONS.map((x) => ({ value: x, label: x }))}
                        />
                      </td>
                      <td className="px-2 py-1 text-right">
                        <button
                          type="button"
                          aria-label={`Remove leg ${li + 1}`}
                          onClick={() => update((d) => d.combos[ci]!.legs.splice(li, 1))}
                          className="text-fg-subtle hover:text-error"
                        >
                          ×
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button
                type="button"
                disabled={combo.legs.length >= 10}
                onClick={() =>
                  update((d) =>
                    d.combos[ci]!.legs.push({
                      symbol: draft.symbolOrder[0] ?? "",
                      side: "BUY",
                      orderType: "LIMIT",
                      quantity: 100,
                      price: null,
                      stopPrice: null,
                      smpAction: "NONE",
                    }),
                  )
                }
                className="mt-2 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50"
              >
                + Add leg
              </button>
            </div>
          </FieldRow>
        </div>
      ))}
    </Panel>
  );
}

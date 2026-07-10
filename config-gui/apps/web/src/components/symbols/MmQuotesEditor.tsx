import { TIF_VALUES, createMmQuoteSeed, type MmQuoteSeed, type Tif } from "@edumatcher/schema";
import { NumberInput, TextInput } from "@/components/fields/inputs";
import { Select } from "@/components/ui/Select";

interface Props {
  quotes: MmQuoteSeed[];
  /** Configured MARKET_MAKER gateway ids; used to populate the gateway select. */
  mmGatewayIds: string[];
  onChange: (next: MmQuoteSeed[]) => void;
  /** Show the optional quote_id column (expert). */
  showQuoteId?: boolean;
}

/**
 * Editor for a symbol's explicit market-maker quote seeds. Supports multiple
 * market makers per symbol. Each row's gateway must be a configured
 * MARKET_MAKER gateway (enforced by diagnostics on the draft).
 */
export function MmQuotesEditor({ quotes, mmGatewayIds, onChange, showQuoteId }: Props) {
  const patch = (index: number, next: Partial<MmQuoteSeed>) => {
    onChange(quotes.map((q, i) => (i === index ? { ...q, ...next } : q)));
  };
  const remove = (index: number) => onChange(quotes.filter((_, i) => i !== index));
  const add = () => {
    const seed = createMmQuoteSeed(mmGatewayIds[0] ?? "");
    onChange([...quotes, seed]);
  };

  if (mmGatewayIds.length === 0) {
    return (
      <p className="text-sm text-fg-subtle">
        Add a gateway with role <span className="font-medium">MARKET_MAKER</span> before defining
        market-maker quotes for this symbol.
      </p>
    );
  }

  const gatewayOptions = mmGatewayIds.map((id) => ({ value: id, label: id }));
  const tifOptions = TIF_VALUES.map((t) => ({ value: t, label: t }));

  return (
    <div className="w-full">
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted text-left text-xs uppercase text-fg-subtle">
            <tr>
              <th className="px-2 py-2">Gateway *</th>
              {showQuoteId && <th className="px-2 py-2">Quote id</th>}
              <th className="px-2 py-2">Bid *</th>
              <th className="px-2 py-2">Ask *</th>
              <th className="px-2 py-2">Bid qty</th>
              <th className="px-2 py-2">Ask qty</th>
              <th className="px-2 py-2">TIF</th>
              <th className="px-2 py-2">Seed once</th>
              <th className="px-2 py-2" />
            </tr>
          </thead>
          <tbody>
            {quotes.map((q, i) => {
              const invalidGateway = !q.gatewayId || !mmGatewayIds.includes(q.gatewayId);
              const invalidSpread =
                q.bidPrice !== null && q.askPrice !== null && q.bidPrice >= q.askPrice;
              return (
                <tr key={i} className="border-t border-border">
                  <td className="px-2 py-1.5">
                    <Select
                      aria-label={`Quote ${i + 1} gateway`}
                      value={q.gatewayId}
                      onValueChange={(v) => patch(i, { gatewayId: v })}
                      options={
                        invalidGateway && q.gatewayId
                          ? [{ value: q.gatewayId, label: `${q.gatewayId} (unknown)` }, ...gatewayOptions]
                          : gatewayOptions
                      }
                    />
                  </td>
                  {showQuoteId && (
                    <td className="px-2 py-1.5">
                      <TextInput
                        aria-label={`Quote ${i + 1} id`}
                        value={q.quoteId ?? ""}
                        onChange={(v) => patch(i, { quoteId: v || undefined })}
                        className="w-32"
                      />
                    </td>
                  )}
                  <td className="px-2 py-1.5">
                    <NumberInput
                      aria-label={`Quote ${i + 1} bid price`}
                      value={q.bidPrice}
                      step={0.01}
                      min={0}
                      onChange={(v) => patch(i, { bidPrice: v ?? null })}
                      className={invalidSpread ? "w-24 border-error" : "w-24"}
                    />
                  </td>
                  <td className="px-2 py-1.5">
                    <NumberInput
                      aria-label={`Quote ${i + 1} ask price`}
                      value={q.askPrice}
                      step={0.01}
                      min={0}
                      onChange={(v) => patch(i, { askPrice: v ?? null })}
                      className={invalidSpread ? "w-24 border-error" : "w-24"}
                    />
                  </td>
                  <td className="px-2 py-1.5">
                    <NumberInput
                      aria-label={`Quote ${i + 1} bid quantity`}
                      value={q.bidQty}
                      min={1}
                      onChange={(v) => patch(i, { bidQty: v ?? 0 })}
                      className="w-20"
                    />
                  </td>
                  <td className="px-2 py-1.5">
                    <NumberInput
                      aria-label={`Quote ${i + 1} ask quantity`}
                      value={q.askQty}
                      min={1}
                      onChange={(v) => patch(i, { askQty: v ?? 0 })}
                      className="w-20"
                    />
                  </td>
                  <td className="px-2 py-1.5">
                    <Select
                      aria-label={`Quote ${i + 1} time in force`}
                      value={q.tif}
                      onValueChange={(v) => patch(i, { tif: v as Tif })}
                      options={tifOptions}
                    />
                  </td>
                  <td className="px-2 py-1.5 text-center">
                    <input
                      type="checkbox"
                      aria-label={`Quote ${i + 1} seed once`}
                      checked={q.seedOnce}
                      onChange={(e) => patch(i, { seedOnce: e.target.checked })}
                    />
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <button
                      type="button"
                      aria-label={`Remove quote ${i + 1}`}
                      onClick={() => remove(i)}
                      className="text-fg-subtle hover:text-error"
                    >
                      ×
                    </button>
                  </td>
                </tr>
              );
            })}
            {quotes.length === 0 && (
              <tr>
                <td colSpan={showQuoteId ? 9 : 8} className="px-3 py-3 text-center text-fg-subtle">
                  No quotes yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <button
        type="button"
        onClick={add}
        className="mt-2 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
      >
        + Add quote
      </button>
    </div>
  );
}

import { useDraftStore } from "@/store/draftStore";
import { usePersona } from "@/lib/usePersona";
import { Panel, Section } from "@/components/layout/Panel";
import { FieldRow } from "@/components/fields/FieldRow";
import { NumberInput } from "@/components/fields/inputs";
import { Switch } from "@/components/ui/Switch";

export function MarketMakerTab() {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);
  const { canSee } = usePersona();

  const mm = draft.mmObligationDefaults;
  const seeding = draft.seeding;
  const mmGateways = draft.gateways.filter((g) => g.role === "MARKET_MAKER");
  const midRangeSet = seeding.mmMidRange !== undefined;

  return (
    <Panel
      tabId="market-maker"
      title="Market Maker"
      intro="Market-maker gateways supply two-sided quotes. Obligations enforce a maximum spread and minimum size. Seeding pre-fills opening quotes so the book is not empty at startup."
    >
      <Section title="Obligations">
        <FieldRow
          label="Enforce MM obligations"
          path="mmObligationDefaults.enforceMmObligation"
          htmlFor="enforce-mm"
          help={{
            text: "Enforce quote-width and size compliance for market-maker gateways.",
            cliFlag: "--enforce-mm-obligations",
          }}
        >
          <Switch
            id="enforce-mm"
            aria-label="Enforce MM obligations"
            checked={mm.enforceMmObligation}
            onCheckedChange={(checked) => update((d) => (d.mmObligationDefaults.enforceMmObligation = checked))}
          />
        </FieldRow>

        <FieldRow
          label="Max spread (ticks)"
          path="mmObligationDefaults.mmMaxSpreadTicks"
          help={{ text: "Maximum allowed bid-ask spread in ticks for obligated quotes.", cliFlag: "--mm-spread-ticks" }}
          defaultHint="Default: 20"
        >
          <NumberInput
            aria-label="Max spread ticks"
            value={mm.mmMaxSpreadTicks}
            min={1}
            onChange={(v) => update((d) => (d.mmObligationDefaults.mmMaxSpreadTicks = v ?? 20))}
          />
        </FieldRow>

        <FieldRow
          label="Min quantity"
          path="mmObligationDefaults.mmMinQty"
          help={{ text: "Minimum displayed quantity required on each side of an obligated quote.", cliFlag: "--mm-min-qty" }}
          defaultHint="Default: 100"
        >
          <NumberInput
            aria-label="Min quantity"
            value={mm.mmMinQty}
            min={1}
            onChange={(v) => update((d) => (d.mmObligationDefaults.mmMinQty = v ?? 100))}
          />
        </FieldRow>
      </Section>

      <Section
        title="Quote seeding"
        description="Set a mid-range and the builder seeds a bid/ask one tick around a midpoint for every symbol × MM gateway. Without it, quote stubs are emitted with null prices that must be filled in before starting the engine."
      >
        <FieldRow
          label="Seed MM mid-range"
          path="seeding.mmMidRange"
          help={{
            text: "Minimum and maximum midpoint price used to seed opening quotes. Prices snap to the symbol's tick grid.",
            cliFlag: "--seed-mm-mid-range",
          }}
          defaultHint="Default: none (null quote stubs)"
          isSet={midRangeSet}
          onReset={() => update((d) => (d.seeding.mmMidRange = undefined))}
        >
          <NumberInput
            aria-label="Mid-range minimum"
            value={seeding.mmMidRange?.min}
            min={0}
            step={0.01}
            onChange={(v) =>
              update((d) => {
                const max = d.seeding.mmMidRange?.max ?? v ?? 0;
                d.seeding.mmMidRange = v === undefined ? undefined : { min: v, max };
              })
            }
            className="w-28"
          />
          <span className="text-sm text-fg-subtle">to</span>
          <NumberInput
            aria-label="Mid-range maximum"
            value={seeding.mmMidRange?.max}
            min={0}
            step={0.01}
            onChange={(v) =>
              update((d) => {
                const min = d.seeding.mmMidRange?.min ?? v ?? 0;
                d.seeding.mmMidRange = v === undefined ? undefined : { min, max: v };
              })
            }
            className="w-28"
          />
        </FieldRow>

        {canSee("I") && (
          <>
            <FieldRow
              label="Seed last prices from MM"
              path="seeding.seedLastPricesFromMm"
              htmlFor="seed-from-mm"
              help={{
                text: "Emit consistent last_buy_price/last_sell_price references derived from the seeded midpoint. Requires a mid-range.",
                cliFlag: "--seed-last-prices-from-mm",
              }}
            >
              <Switch
                id="seed-from-mm"
                aria-label="Seed last prices from MM"
                disabled={!midRangeSet}
                checked={seeding.seedLastPricesFromMm}
                onCheckedChange={(checked) => update((d) => (d.seeding.seedLastPricesFromMm = checked))}
              />
              {!midRangeSet && <span className="text-xs text-fg-subtle">Set a mid-range first</span>}
            </FieldRow>

            <FieldRow
              label="Seed placeholder last prices"
              path="seeding.seedLastPrices"
              htmlFor="seed-last"
              help={{
                text: "Emit null last_buy_price/last_sell_price placeholders for viewer reference (required for collar initialization).",
                cliFlag: "--seed-last-prices",
              }}
            >
              <Switch
                id="seed-last"
                aria-label="Seed placeholder last prices"
                checked={seeding.seedLastPrices}
                onCheckedChange={(checked) => update((d) => (d.seeding.seedLastPrices = checked))}
              />
            </FieldRow>
          </>
        )}

        {canSee("E") && (
          <FieldRow
            label="Deterministic seed"
            path="seeding.randomSeed"
            help={{ text: "Fix the RNG seed for reproducible classroom runs.", cliFlag: "--seed" }}
            defaultHint="Default: random"
            isSet={seeding.randomSeed !== undefined}
            onReset={() => update((d) => (d.seeding.randomSeed = undefined))}
          >
            <NumberInput
              aria-label="Deterministic seed"
              value={seeding.randomSeed}
              onChange={(v) => update((d) => (d.seeding.randomSeed = v))}
            />
          </FieldRow>
        )}
      </Section>

      <Section
        title="Quote stub review"
        description="One seed quote per symbol × market-maker gateway. Rows without a seeded price must be filled in before starting the engine."
      >
        {mmGateways.length === 0 || draft.symbolOrder.length === 0 ? (
          <p className="text-sm text-fg-subtle">Add a MARKET_MAKER gateway and at least one symbol to see quote stubs.</p>
        ) : (
          <div className="overflow-hidden rounded-md border border-border">
            <table className="w-full text-sm">
              <thead className="bg-muted text-left text-xs uppercase text-fg-subtle">
                <tr>
                  <th className="px-3 py-2">Symbol</th>
                  <th className="px-3 py-2">Gateway</th>
                  <th className="px-3 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {draft.symbolOrder.flatMap((symbol) =>
                  mmGateways.map((gw) => (
                    <tr key={`${symbol}-${gw.id}`} className="border-t border-border">
                      <td className="px-3 py-1.5 font-medium">{symbol}</td>
                      <td className="px-3 py-1.5">{gw.id}</td>
                      <td className="px-3 py-1.5">
                        {midRangeSet ? (
                          <span className="text-success">✓ seeded from mid-range</span>
                        ) : (
                          <span className="text-warning">! fill in before starting the engine</span>
                        )}
                      </td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </Panel>
  );
}

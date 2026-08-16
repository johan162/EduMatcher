import * as RadixDialog from "@radix-ui/react-dialog";
import {
  QUOTE_REFRESH_POLICIES,
  type GatewayMmObligationOverride,
  type QuoteRefreshPolicy,
} from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import { NumberInput } from "@/components/fields/inputs";
import { Select } from "@/components/ui/Select";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Id of the MARKET_MAKER gateway being edited. */
  gatewayId: string;
}

const INHERIT = "__inherit__";

const triStateOptions = [
  { value: INHERIT, label: "(inherit)" },
  { value: "true", label: "Enabled" },
  { value: "false", label: "Disabled" },
];

function triStateValue(v: boolean | undefined): string {
  return v === undefined ? INHERIT : v ? "true" : "false";
}

function parseTriState(v: string): boolean | undefined {
  return v === INHERIT ? undefined : v === "true";
}

/**
 * Expert-only, MARKET_MAKER-only advanced settings for a single ALF gateway:
 * quote-refresh policy and per-gateway market-maker obligation overrides
 * (flat + per-symbol). Edits are applied live to the draft. Fields left at
 * their defaults / "inherit" are omitted from the exported config.
 */
export function GatewayAdvancedDialog({ open, onOpenChange, gatewayId }: Props) {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);

  const gateway = draft.gateways.find((g) => g.id === gatewayId);
  const globals = draft.mmObligationDefaults;

  const setGateway = (fn: (g: NonNullable<typeof gateway>) => void) =>
    update((d) => {
      const g = d.gateways.find((x) => x.id === gatewayId);
      if (g) fn(g);
    });

  const obligations = gateway?.mmObligations ?? {};
  const overriddenSymbols = Object.keys(obligations);
  const availableSymbols = draft.symbolOrder.filter((s) => !overriddenSymbols.includes(s));

  const setObligation = (symbol: string, next: Partial<GatewayMmObligationOverride>) =>
    setGateway((g) => {
      g.mmObligations = g.mmObligations ?? {};
      g.mmObligations[symbol] = { ...g.mmObligations[symbol], ...next };
    });

  const renameObligation = (from: string, to: string) =>
    setGateway((g) => {
      if (!g.mmObligations || from === to || g.mmObligations[to]) return;
      g.mmObligations[to] = g.mmObligations[from]!;
      delete g.mmObligations[from];
    });

  const removeObligation = (symbol: string) =>
    setGateway((g) => {
      if (g.mmObligations) {
        delete g.mmObligations[symbol];
        if (Object.keys(g.mmObligations).length === 0) g.mmObligations = undefined;
      }
    });

  const addObligation = () => {
    const symbol = availableSymbols[0];
    if (symbol) setObligation(symbol, {});
  };

  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-black/50" />
        <RadixDialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[min(760px,94vw)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-border bg-surface-raised p-5 shadow-xl">
          <RadixDialog.Title className="text-base font-semibold">
            Advanced market-maker settings — {gatewayId}
          </RadixDialog.Title>
          <RadixDialog.Description className="mt-1 text-sm text-fg-subtle">
            Per-gateway overrides for this market maker. Leave anything at "inherit" / blank to use
            the global defaults from the Market Maker tab.
          </RadixDialog.Description>

          {gateway ? (
            <div className="mt-4 space-y-6">
              {/* Quote lifecycle */}
              <section>
                <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-fg-subtle">
                  Quote lifecycle
                </h3>
                <label className="block text-sm">
                  <span className="mb-1 block font-medium">Quote refresh policy</span>
                  <Select
                    aria-label="Quote refresh policy"
                    value={gateway.quoteRefreshPolicy ?? "INACTIVATE_ON_ANY_FILL"}
                    onValueChange={(v) =>
                      setGateway((g) => (g.quoteRefreshPolicy = v as QuoteRefreshPolicy))
                    }
                    options={QUOTE_REFRESH_POLICIES.map((p) => ({ value: p, label: p }))}
                  />
                  <span className="mt-1 block text-xs text-fg-subtle">
                    When seeded quotes are inactivated after executions. Default:
                    INACTIVATE_ON_ANY_FILL.
                  </span>
                </label>
              </section>

              {/* Per-gateway flat obligation overrides */}
              <section>
                <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-fg-subtle">
                  Obligation overrides (this gateway)
                </h3>
                <div className="grid grid-cols-3 gap-3">
                  <label className="text-sm">
                    <span className="mb-1 block font-medium">Enforce</span>
                    <Select
                      aria-label="Enforce MM obligation (gateway)"
                      value={triStateValue(gateway.enforceMmObligation)}
                      onValueChange={(v) =>
                        setGateway((g) => (g.enforceMmObligation = parseTriState(v)))
                      }
                      options={triStateOptions}
                    />
                    <span className="mt-1 block text-xs text-fg-subtle">
                      Global: {globals.enforceMmObligation ? "Enabled" : "Disabled"}
                    </span>
                  </label>
                  <label className="text-sm">
                    <span className="mb-1 block font-medium">Max spread (ticks)</span>
                    <NumberInput
                      aria-label="Gateway max spread ticks"
                      value={gateway.mmMaxSpreadTicks}
                      min={1}
                      onChange={(v) => setGateway((g) => (g.mmMaxSpreadTicks = v))}
                      className="w-full"
                    />
                    <span className="mt-1 block text-xs text-fg-subtle">
                      Global: {globals.mmMaxSpreadTicks}
                    </span>
                  </label>
                  <label className="text-sm">
                    <span className="mb-1 block font-medium">Min quantity</span>
                    <NumberInput
                      aria-label="Gateway min quantity"
                      value={gateway.mmMinQty}
                      min={1}
                      onChange={(v) => setGateway((g) => (g.mmMinQty = v))}
                      className="w-full"
                    />
                    <span className="mt-1 block text-xs text-fg-subtle">
                      Global: {globals.mmMinQty}
                    </span>
                  </label>
                </div>
              </section>

              {/* Per-symbol obligation overrides */}
              <section>
                <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-fg-subtle">
                  Per-symbol overrides (this gateway)
                </h3>
                {draft.symbolOrder.length === 0 ? (
                  <p className="text-sm text-fg-subtle">Add symbols first (Basics tab).</p>
                ) : (
                  <>
                    <div className="overflow-hidden rounded-md border border-border">
                      <table className="w-full text-sm">
                        <thead className="bg-muted text-left text-xs uppercase text-fg-subtle">
                          <tr>
                            <th className="px-2 py-2">Symbol</th>
                            <th className="px-2 py-2">Enforce</th>
                            <th className="px-2 py-2">Max spread</th>
                            <th className="px-2 py-2">Min qty</th>
                            <th className="px-2 py-2" />
                          </tr>
                        </thead>
                        <tbody>
                          {overriddenSymbols.map((symbol) => {
                            const o = obligations[symbol]!;
                            const symbolOptions = [
                              { value: symbol, label: symbol },
                              ...availableSymbols.map((s) => ({ value: s, label: s })),
                            ];
                            return (
                              <tr key={symbol} className="border-t border-border">
                                <td className="px-2 py-1.5">
                                  <Select
                                    aria-label={`Override symbol for ${symbol}`}
                                    value={symbol}
                                    onValueChange={(v) => renameObligation(symbol, v)}
                                    options={symbolOptions}
                                  />
                                </td>
                                <td className="px-2 py-1.5">
                                  <Select
                                    aria-label={`${symbol} enforce`}
                                    value={triStateValue(o.enforceMmObligation)}
                                    onValueChange={(v) =>
                                      setObligation(symbol, { enforceMmObligation: parseTriState(v) })
                                    }
                                    options={triStateOptions}
                                  />
                                </td>
                                <td className="px-2 py-1.5">
                                  <NumberInput
                                    aria-label={`${symbol} max spread ticks`}
                                    value={o.maxSpreadTicks}
                                    min={1}
                                    onChange={(v) => setObligation(symbol, { maxSpreadTicks: v })}
                                    className="w-24"
                                  />
                                </td>
                                <td className="px-2 py-1.5">
                                  <NumberInput
                                    aria-label={`${symbol} min qty`}
                                    value={o.minQty}
                                    min={1}
                                    onChange={(v) => setObligation(symbol, { minQty: v })}
                                    className="w-24"
                                  />
                                </td>
                                <td className="px-2 py-1.5 text-right">
                                  <button
                                    type="button"
                                    aria-label={`Remove override for ${symbol}`}
                                    onClick={() => removeObligation(symbol)}
                                    className="text-fg-subtle hover:text-error"
                                  >
                                    ×
                                  </button>
                                </td>
                              </tr>
                            );
                          })}
                          {overriddenSymbols.length === 0 && (
                            <tr>
                              <td colSpan={5} className="px-3 py-3 text-center text-fg-subtle">
                                No per-symbol overrides.
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                    <button
                      type="button"
                      disabled={availableSymbols.length === 0}
                      onClick={addObligation}
                      className="mt-2 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50"
                    >
                      + Add symbol override
                    </button>
                  </>
                )}
              </section>
            </div>
          ) : (
            <p className="mt-4 text-sm text-fg-subtle">Gateway not found.</p>
          )}

          <div className="mt-5 flex justify-end">
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg"
            >
              Done
            </button>
          </div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

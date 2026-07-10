import { useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import clsx from "clsx";
import { effectiveDefaultCollar, type MmQuoteSeed } from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import { usePersona } from "@/lib/usePersona";
import { fractionToPercent, percentToFraction } from "@/lib/format";
import { Panel, Section } from "@/components/layout/Panel";
import { FieldRow } from "@/components/fields/FieldRow";
import { NumberInput } from "@/components/fields/inputs";
import { Select } from "@/components/ui/Select";
import { MmQuotesEditor } from "@/components/symbols/MmQuotesEditor";
import { SymbolEditorDialog } from "@/components/symbols/SymbolEditorDialog";

export function SymbolsTab() {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);
  const { canSee } = usePersona();
  const [selected, setSelected] = useState<string | null>(draft.symbolOrder[0] ?? null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingSymbol, setEditingSymbol] = useState<string | undefined>(undefined);

  const symbol = selected && draft.symbols[selected] ? selected : draft.symbolOrder[0] ?? null;
  const config = symbol ? draft.symbols[symbol] : undefined;

  const mmGatewayIds = draft.gateways
    .filter((g) => g.role === "MARKET_MAKER")
    .map((g) => g.id);

  const levelOptions = [
    { value: "", label: "(inherit default)" },
    ...(effectiveDefaultCollar(draft) ? [{ value: "DEFAULT", label: "DEFAULT" }] : []),
    ...Object.keys(draft.riskControls.levels).map((name) => ({ value: name, label: name })),
  ];

  return (
    <Panel
      tabId="symbols"
      title="Symbols"
      intro="Per-symbol overrides layered on top of the global defaults. Anything left blank inherits the global value."
    >
      <Section title="Global default">
        <FieldRow
          label="Tick decimals (global)"
          path="tickDecimals"
          help={{
            text: "Display precision and tick-size conversion applied to symbols without an override. 0..8.",
            cliFlag: "--tick-decimals",
          }}
          defaultHint="Default: 2"
        >
          <NumberInput
            aria-label="Global tick decimals"
            value={draft.tickDecimals}
            min={0}
            max={8}
            onChange={(v) => update((d) => (d.tickDecimals = v ?? 2))}
          />
        </FieldRow>
        <FieldRow
          label="Symbol universe"
          path="symbols"
          help={{
            text: "Add a symbol as a structured instrument (name + required reference prices, plus optional precision, shares, and MM quotes).",
            cliFlag: "--symbols",
          }}
        >
          <div className="w-full">
            <div className="flex flex-wrap gap-1.5">
              {draft.symbolOrder.map((s) => (
                <span
                  key={s}
                  className="inline-flex items-center gap-1 rounded-md border border-border bg-surface px-2 py-1 text-sm"
                >
                  {s}
                  <button
                    type="button"
                    aria-label={`Remove ${s}`}
                    onClick={() =>
                      update((d) => {
                        delete d.symbols[s];
                        d.symbolOrder = d.symbolOrder.filter((x) => x !== s);
                        for (const index of d.indices) {
                          index.constituents = index.constituents.filter((c) => c !== s);
                        }
                        for (const combo of d.combos) {
                          combo.legs = combo.legs.filter((leg) => leg.symbol !== s);
                        }
                      })
                    }
                    className="text-fg-subtle hover:text-error"
                  >
                    ×
                  </button>
                </span>
              ))}
              {draft.symbolOrder.length === 0 && (
                <span className="text-sm text-fg-subtle">No symbols yet.</span>
              )}
            </div>
            <button
              type="button"
              onClick={() => {
                setEditingSymbol(undefined);
                setDialogOpen(true);
              }}
              className="mt-2 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
            >
              + Add symbol
            </button>
          </div>
        </FieldRow>
      </Section>

      {symbol && config ? (
        <div className="mt-6 grid grid-cols-[10rem_1fr] gap-4">
          <ul className="rounded-md border border-border bg-surface p-1">
            {draft.symbolOrder.map((s) => (
              <li key={s}>
                <button
                  type="button"
                  onClick={() => setSelected(s)}
                  className={clsx(
                    "w-full rounded px-3 py-1.5 text-left text-sm",
                    s === symbol ? "bg-accent text-accent-fg" : "hover:bg-muted",
                  )}
                >
                  {s}
                </button>
              </li>
            ))}
          </ul>

          <div className="rounded-md border border-border bg-surface p-4">
            <Tabs.Root defaultValue="general">
              <Tabs.List className="mb-3 flex gap-1 border-b border-border">
                {[
                  { v: "general", label: "General", show: true },
                  { v: "collar", label: "Collar", show: true },
                  { v: "cb", label: "Circuit Breaker", show: canSee("E") },
                  { v: "mm", label: "Market Maker", show: true },
                  { v: "mmq", label: "MM Quotes", show: canSee("I") },
                ]
                  .filter((t) => t.show)
                  .map((t) => (
                    <Tabs.Trigger
                      key={t.v}
                      value={t.v}
                      className="rounded-t px-3 py-1.5 text-sm data-[state=active]:border-b-2 data-[state=active]:border-accent data-[state=active]:font-medium"
                    >
                      {t.label}
                    </Tabs.Trigger>
                  ))}
              </Tabs.List>

              <Tabs.Content value="general">
                <FieldRow
                  label="Tick decimals"
                  path={`symbols.${symbol}.tickDecimals`}
                  help={{ text: "Per-symbol price precision override.", cliFlag: "--symbol-opts tick_decimals" }}
                  defaultHint={`Inherits global: ${draft.tickDecimals}`}
                >
                  <NumberInput
                    aria-label="Tick decimals"
                    value={config.tickDecimals}
                    min={0}
                    max={8}
                    onChange={(v) => update((d) => (d.symbols[symbol]!.tickDecimals = v ?? draft.tickDecimals))}
                  />
                </FieldRow>
                <FieldRow
                  label="Last buy price"
                  path={`symbols.${symbol}.lastBuyPrice`}
                  required
                  help={{ text: "Opening reference used to seed the book and the collar static reference. Required.", cliFlag: "--seed-last-prices" }}
                >
                  <NumberInput
                    aria-label="Last buy price"
                    value={config.lastBuyPrice ?? undefined}
                    min={0}
                    step={0.01}
                    onChange={(v) => update((d) => (d.symbols[symbol]!.lastBuyPrice = v ?? null))}
                  />
                </FieldRow>
                <FieldRow
                  label="Last sell price"
                  path={`symbols.${symbol}.lastSellPrice`}
                  required
                  help={{ text: "Opening reference used to seed the book. Required.", cliFlag: "--seed-last-prices" }}
                >
                  <NumberInput
                    aria-label="Last sell price"
                    value={config.lastSellPrice ?? undefined}
                    min={0}
                    step={0.01}
                    onChange={(v) => update((d) => (d.symbols[symbol]!.lastSellPrice = v ?? null))}
                  />
                </FieldRow>
                <FieldRow
                  label="Outstanding shares"
                  path={`symbols.${symbol}.outstandingShares`}
                  help={{ text: "Issued share count, used for index weighting. Required for index constituents.", cliFlag: "--outstanding-shares" }}
                  defaultHint="Default: none"
                  isSet={config.outstandingShares !== undefined}
                  onReset={() => update((d) => (d.symbols[symbol]!.outstandingShares = undefined))}
                >
                  <NumberInput
                    aria-label="Outstanding shares"
                    value={config.outstandingShares}
                    min={0}
                    onChange={(v) => update((d) => (d.symbols[symbol]!.outstandingShares = v))}
                  />
                </FieldRow>
              </Tabs.Content>

              <Tabs.Content value="collar">
                <FieldRow
                  label="Risk level"
                  path={`symbols.${symbol}.level`}
                  help={{ text: "Assign a named risk level (defined in Risk & Collars). Cross-checked against the level catalogue.", cliFlag: "--symbol-opts level" }}
                >
                  <Select
                    aria-label="Risk level"
                    value={config.level ?? ""}
                    onValueChange={(v) => update((d) => (d.symbols[symbol]!.level = v || undefined))}
                    options={levelOptions}
                  />
                </FieldRow>
                <FieldRow
                  label="Static band override"
                  path={`symbols.${symbol}.collar.staticBandPct`}
                  defaultHint="Inherits global/level"
                  isSet={config.collar?.staticBandPct !== undefined}
                  onReset={() => update((d) => { if (d.symbols[symbol]!.collar) d.symbols[symbol]!.collar!.staticBandPct = undefined; })}
                >
                  <NumberInput
                    aria-label="Static band override percent"
                    value={config.collar?.staticBandPct !== undefined ? fractionToPercent(config.collar.staticBandPct) : undefined}
                    min={0}
                    max={100}
                    step={0.5}
                    onChange={(v) =>
                      update((d) => {
                        const s = d.symbols[symbol]!;
                        s.collar = s.collar ?? {};
                        s.collar.staticBandPct = v === undefined ? undefined : percentToFraction(v);
                      })
                    }
                  />
                  <span className="text-sm text-fg-subtle">%</span>
                </FieldRow>
                <FieldRow
                  label="Dynamic band override"
                  path={`symbols.${symbol}.collar.dynamicBandPct`}
                  defaultHint="Inherits global/level"
                  isSet={config.collar?.dynamicBandPct !== undefined}
                  onReset={() => update((d) => { if (d.symbols[symbol]!.collar) d.symbols[symbol]!.collar!.dynamicBandPct = undefined; })}
                >
                  <NumberInput
                    aria-label="Dynamic band override percent"
                    value={config.collar?.dynamicBandPct !== undefined ? fractionToPercent(config.collar.dynamicBandPct) : undefined}
                    min={0}
                    max={100}
                    step={0.5}
                    onChange={(v) =>
                      update((d) => {
                        const s = d.symbols[symbol]!;
                        s.collar = s.collar ?? {};
                        s.collar.dynamicBandPct = v === undefined ? undefined : percentToFraction(v);
                      })
                    }
                  />
                  <span className="text-sm text-fg-subtle">%</span>
                </FieldRow>
              </Tabs.Content>

              {canSee("E") && (
                <Tabs.Content value="cb">
                  <p className="mb-2 text-sm text-fg-subtle">
                    Override individual ladder levels for this symbol. Blank fields inherit the global ladder.
                  </p>
                  {draft.circuitBreakerDefaults.levelOrder.map((name) => {
                    const override = config.circuitBreaker?.levels[name];
                    return (
                      <FieldRow key={name} label={`${name} shift %`} path={`symbols.${symbol}.circuitBreaker.${name}`}>
                        <NumberInput
                          aria-label={`${name} shift override`}
                          value={override?.priceShiftPct !== undefined ? fractionToPercent(override.priceShiftPct) : undefined}
                          min={0}
                          max={100}
                          step={0.5}
                          onChange={(v) =>
                            update((d) => {
                              const s = d.symbols[symbol]!;
                              s.circuitBreaker = s.circuitBreaker ?? { levels: {} };
                              s.circuitBreaker.levels[name] = s.circuitBreaker.levels[name] ?? {};
                              s.circuitBreaker.levels[name]!.priceShiftPct =
                                v === undefined ? undefined : percentToFraction(v);
                            })
                          }
                        />
                        <span className="text-sm text-fg-subtle">%</span>
                      </FieldRow>
                    );
                  })}
                </Tabs.Content>
              )}

              <Tabs.Content value="mm">
                <FieldRow
                  label="Enforce MM obligation"
                  path={`symbols.${symbol}.marketMaker.enforceMmObligation`}
                  defaultHint="Inherits global"
                >
                  <Select
                    aria-label="Enforce MM obligation override"
                    value={config.marketMaker?.enforceMmObligation === undefined ? "" : config.marketMaker.enforceMmObligation ? "true" : "false"}
                    onValueChange={(v) =>
                      update((d) => {
                        const s = d.symbols[symbol]!;
                        s.marketMaker = s.marketMaker ?? {};
                        s.marketMaker.enforceMmObligation = v === "" ? undefined : v === "true";
                      })
                    }
                    options={[
                      { value: "", label: "(inherit)" },
                      { value: "true", label: "Enabled" },
                      { value: "false", label: "Disabled" },
                    ]}
                  />
                </FieldRow>
                <FieldRow
                  label="Max spread (ticks)"
                  path={`symbols.${symbol}.marketMaker.mmMaxSpreadTicks`}
                  defaultHint={`Inherits global: ${draft.mmObligationDefaults.mmMaxSpreadTicks}`}
                  isSet={config.marketMaker?.mmMaxSpreadTicks !== undefined}
                  onReset={() => update((d) => { if (d.symbols[symbol]!.marketMaker) d.symbols[symbol]!.marketMaker!.mmMaxSpreadTicks = undefined; })}
                >
                  <NumberInput
                    aria-label="Max spread ticks override"
                    value={config.marketMaker?.mmMaxSpreadTicks}
                    min={1}
                    onChange={(v) =>
                      update((d) => {
                        const s = d.symbols[symbol]!;
                        s.marketMaker = s.marketMaker ?? {};
                        s.marketMaker.mmMaxSpreadTicks = v;
                      })
                    }
                  />
                </FieldRow>
                <FieldRow
                  label="Min quantity"
                  path={`symbols.${symbol}.marketMaker.mmMinQty`}
                  defaultHint={`Inherits global: ${draft.mmObligationDefaults.mmMinQty}`}
                  isSet={config.marketMaker?.mmMinQty !== undefined}
                  onReset={() => update((d) => { if (d.symbols[symbol]!.marketMaker) d.symbols[symbol]!.marketMaker!.mmMinQty = undefined; })}
                >
                  <NumberInput
                    aria-label="Min quantity override"
                    value={config.marketMaker?.mmMinQty}
                    min={1}
                    onChange={(v) =>
                      update((d) => {
                        const s = d.symbols[symbol]!;
                        s.marketMaker = s.marketMaker ?? {};
                        s.marketMaker.mmMinQty = v;
                      })
                    }
                  />
                </FieldRow>
              </Tabs.Content>

              {canSee("I") && (
                <Tabs.Content value="mmq">
                  <p className="mb-3 text-sm text-fg-subtle">
                    Explicit market-maker quote seeds for this symbol. Multiple market makers are
                    supported; each gateway must have role MARKET_MAKER. When left empty, the
                    builder auto-generates one stub per MM gateway.
                  </p>
                  <MmQuotesEditor
                    quotes={config.marketMakerQuotes ?? []}
                    mmGatewayIds={mmGatewayIds}
                    showQuoteId={canSee("E")}
                    onChange={(next: MmQuoteSeed[]) =>
                      update((d) => {
                        d.symbols[symbol]!.marketMakerQuotes =
                          next.length > 0 ? next : undefined;
                      })
                    }
                  />
                </Tabs.Content>
              )}
            </Tabs.Root>
          </div>
        </div>
      ) : (
        <p className="mt-6 text-sm text-fg-subtle">Add symbols in Basics (or above) to configure per-symbol overrides.</p>
      )}

      <SymbolEditorDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        mode={editingSymbol ? "edit" : "create"}
        symbolName={editingSymbol}
      />
    </Panel>
  );
}

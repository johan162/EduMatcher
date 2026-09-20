import { useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import clsx from "clsx";
import {
  effectiveDefaultCollar,
  writtenLastPrices,
  type CbLevel,
  type MmQuoteSeed,
} from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import { usePersona } from "@/lib/usePersona";
import {
  fractionToPercent,
  minutesToNs,
  nsToMinutes,
  percentToFraction,
  tickStep,
  uppercaseId,
} from "@/lib/format";
import { removeSymbol } from "@/lib/symbols";
import { Panel, Section } from "@/components/layout/Panel";
import { FieldRow } from "@/components/fields/FieldRow";
import { NumberInput, TextInput } from "@/components/fields/inputs";
import { Select } from "@/components/ui/Select";
import { Switch } from "@/components/ui/Switch";
import { ColumnHead } from "@/components/ui/ColumnHead";
import { MmQuotesEditor } from "@/components/symbols/MmQuotesEditor";
import { SymbolEditorDialog } from "@/components/symbols/SymbolEditorDialog";
import { SymbolOverviewDialog } from "@/components/symbols/SymbolOverviewDialog";
import { SymbolOverridesTable } from "@/components/symbols/SymbolOverridesTable";

/**
 * Sentinel for "inherit" in per-symbol dropdowns. Radix Select reserves the
 * empty string for "no selection" (it renders the placeholder, i.e. a blank
 * trigger), so "" cannot be used as an option value.
 */
const INHERIT = "__inherit__";

/**
 * Hint under a last-price field whose own value is unset, saying what the
 * file gets instead — mid-range seeding can fill it without the field
 * holding a value.
 */
function seededHint(
  written: number | null | undefined,
  own: number | null | undefined,
): string | undefined {
  if (own !== undefined) return undefined;
  if (written === undefined) return "Not set — the key is omitted from the file";
  if (written === null) return "Written as null (placeholder)";
  return `Written as ${written} (seeded from the MM mid-range)`;
}

export function SymbolsTab() {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);
  const { canSee } = usePersona();
  const [selected, setSelected] = useState<string | null>(draft.symbolOrder[0] ?? null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingSymbol, setEditingSymbol] = useState<string | undefined>(undefined);
  /** Symbol whose read-only overview is open (independent of selection). */
  const [overviewSymbol, setOverviewSymbol] = useState<string | null>(null);
  const [newCbLevel, setNewCbLevel] = useState("");

  const symbol = selected && draft.symbols[selected] ? selected : draft.symbolOrder[0] ?? null;
  const config = symbol ? draft.symbols[symbol] : undefined;

  const mmGatewayIds = draft.gateways
    .filter((g) => g.role === "MARKET_MAKER")
    .map((g) => g.id);

  const levelOptions = [
    { value: INHERIT, label: "(inherit default)" },
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
            text: "Tick decimals given to newly created symbols. Not written to the file: every symbol writes its own tick_decimals, and changing this does not change existing symbols. 0..8.",
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
                    onClick={() => update((d) => removeSymbol(d, s))}
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

      {draft.symbolOrder.length > 0 && (
        <Section
          title="Per-symbol overrides"
          description="Every symbol appears here. Greyed cells inherit the exchange default; type a value to override just that symbol. Select rows to change many at once."
        >
          <SymbolOverridesTable />
        </Section>
      )}

      {symbol && config ? (
        <div className="mt-6 grid grid-cols-[10rem_1fr] gap-4">
          <ul className="rounded-md border border-border bg-surface p-1">
            {draft.symbolOrder.map((s) => (
              <li key={s} className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setSelected(s)}
                  className={clsx(
                    "flex-1 rounded px-3 py-1.5 text-left text-sm",
                    s === symbol ? "bg-accent text-accent-fg" : "hover:bg-muted",
                  )}
                >
                  {s}
                </button>
                <button
                  type="button"
                  aria-label={`Overview for ${s}`}
                  title={`Overview for ${s} (peek without selecting)`}
                  onClick={() => setOverviewSymbol(s)}
                  className="shrink-0 rounded p-1 text-fg-subtle hover:bg-muted hover:text-fg"
                >
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={2}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7Z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                </button>
              </li>
            ))}
          </ul>

          <div className="rounded-md border border-border bg-surface p-4">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-base font-semibold">{symbol}</h3>
              <button
                type="button"
                onClick={() => setOverviewSymbol(symbol)}
                className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
                title="Read-only summary of all effective values for this symbol"
              >
                Overview
              </button>
            </div>
            <Tabs.Root defaultValue="general">
              <Tabs.List className="mb-3 flex gap-1 border-b border-border">
                {[
                  { v: "general", label: "General", show: true },
                  { v: "collar", label: "Collar & Limits", show: true },
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
                  help={{ text: "This symbol's price precision; always written.", cliFlag: "--symbol-opts tick_decimals" }}
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
                  defaultHint={seededHint(writtenLastPrices(draft, config).lastBuyPrice, config.lastBuyPrice)}
                >
                  <NumberInput
                    aria-label="Last buy price"
                    value={config.lastBuyPrice ?? undefined}
                    min={0}
                    step={tickStep(config.tickDecimals)}
                    onChange={(v) => update((d) => (d.symbols[symbol]!.lastBuyPrice = v ?? null))}
                  />
                </FieldRow>
                <FieldRow
                  label="Last sell price"
                  path={`symbols.${symbol}.lastSellPrice`}
                  required
                  help={{ text: "Opening reference used to seed the book. Required.", cliFlag: "--seed-last-prices" }}
                  defaultHint={seededHint(writtenLastPrices(draft, config).lastSellPrice, config.lastSellPrice)}
                >
                  <NumberInput
                    aria-label="Last sell price"
                    value={config.lastSellPrice ?? undefined}
                    min={0}
                    step={tickStep(config.tickDecimals)}
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
                    value={config.level ?? INHERIT}
                    onValueChange={(v) => update((d) => (d.symbols[symbol]!.level = v === INHERIT ? undefined : v))}
                    options={
                      config.level && !levelOptions.some((o) => o.value === config.level)
                        ? [...levelOptions, { value: config.level, label: `${config.level} (undefined)` }]
                        : levelOptions
                    }
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
                <FieldRow
                  label="Max order quantity"
                  path={`symbols.${symbol}.orderLimits.maxOrderQty`}
                  help={{ text: "Largest quantity a single order in this symbol may carry. Leave empty for no cap — there is no level or global default.", cliFlag: "--symbol-opts max_order_qty" }}
                  defaultHint="Default: no cap"
                  isSet={config.orderLimits?.maxOrderQty !== undefined}
                  onReset={() => update((d) => { if (d.symbols[symbol]!.orderLimits) d.symbols[symbol]!.orderLimits!.maxOrderQty = undefined; })}
                >
                  <NumberInput
                    aria-label="Max order quantity override"
                    value={config.orderLimits?.maxOrderQty}
                    min={1}
                    step={1}
                    onChange={(v) =>
                      update((d) => {
                        const s = d.symbols[symbol]!;
                        s.orderLimits = s.orderLimits ?? {};
                        s.orderLimits.maxOrderQty = v;
                      })
                    }
                  />
                  <span className="text-sm text-fg-subtle">shares</span>
                </FieldRow>
                <FieldRow
                  label="Max order value"
                  path={`symbols.${symbol}.orderLimits.maxOrderValue`}
                  help={{ text: "Largest notional a single priced order in this symbol may carry. Not applied to MARKET or IOC orders, which carry no price. Leave empty for no cap.", cliFlag: "--symbol-opts max_order_value" }}
                  defaultHint="Default: no cap"
                  isSet={config.orderLimits?.maxOrderValue !== undefined}
                  onReset={() => update((d) => { if (d.symbols[symbol]!.orderLimits) d.symbols[symbol]!.orderLimits!.maxOrderValue = undefined; })}
                >
                  <NumberInput
                    aria-label="Max order value override"
                    value={config.orderLimits?.maxOrderValue}
                    min={0}
                    step={1000}
                    onChange={(v) =>
                      update((d) => {
                        const s = d.symbols[symbol]!;
                        s.orderLimits = s.orderLimits ?? {};
                        s.orderLimits.maxOrderValue = v;
                      })
                    }
                  />
                </FieldRow>
              </Tabs.Content>

              {canSee("E") && (
                <Tabs.Content value="cb">
                  <p className="mb-2 text-sm text-fg-subtle">
                    Override the reference window and individual ladder levels for this symbol.
                    Blank fields inherit the global circuit-breaker defaults.
                    {!draft.circuitBreakerDefaults.include &&
                      " No exchange ladder is written (Circuit Breakers tab), so the engine's built-in L1/L2/L3 applies when this symbol sets no level of its own."}
                  </p>
                  <FieldRow
                    label="Reference window override (minutes)"
                    path={`symbols.${symbol}.circuitBreaker.referenceWindowNs`}
                    help={{
                      text: "Per-symbol rolling reference window for halt detection. Blank inherits the global window.",
                      cliFlag: "circuit_breaker.reference_window_ns",
                    }}
                    defaultHint={`Inherits global: ${nsToMinutes(draft.circuitBreakerDefaults.windowNs)} min`}
                    isSet={config.circuitBreaker?.referenceWindowNs !== undefined}
                    onReset={() =>
                      update((d) => {
                        if (d.symbols[symbol]!.circuitBreaker) {
                          d.symbols[symbol]!.circuitBreaker!.referenceWindowNs = undefined;
                        }
                      })
                    }
                  >
                    <NumberInput
                      aria-label="Reference window override minutes"
                      value={
                        config.circuitBreaker?.referenceWindowNs !== undefined
                          ? (nsToMinutes(config.circuitBreaker.referenceWindowNs) ?? undefined)
                          : undefined
                      }
                      min={1}
                      onChange={(v) =>
                        update((d) => {
                          const s = d.symbols[symbol]!;
                          s.circuitBreaker = s.circuitBreaker ?? { levels: {} };
                          s.circuitBreaker.referenceWindowNs =
                            v === undefined ? undefined : (minutesToNs(v) ?? undefined);
                        })
                      }
                    />
                    <span className="text-sm text-fg-subtle">min</span>
                  </FieldRow>
                  <div className="mt-3 overflow-x-auto rounded-md border border-border">
                    <table className="w-full text-sm">
                      <thead className="bg-muted text-left text-xs uppercase text-fg-subtle">
                        <tr>
                          <th className="px-3 py-2">Level</th>
                          <th className="px-3 py-2">
                            <ColumnHead
                              label="Shift %"
                              help="How far the price must move from the rolling reference (percent) to trigger this level. Higher levels use larger moves. Blank inherits the global ladder value."
                            />
                          </th>
                          <th className="px-3 py-2">
                            <ColumnHead
                              label="Halt (min)"
                              help="Cool-off: how long trading is halted after this level triggers, before it can resume. Blank inherits the global ladder value."
                            />
                          </th>
                          <th className="px-3 py-2">
                            <ColumnHead
                              label="Rest of day"
                              help="Halt until the close instead of a fixed duration. Leave off with a blank halt to inherit the global ladder value."
                            />
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {[
                          // The exchange ladder (when written), then any
                          // levels only this symbol defines — the engine
                          // merges both by name.
                          ...(draft.circuitBreakerDefaults.include
                            ? draft.circuitBreakerDefaults.levelOrder
                            : []),
                          ...Object.keys(config.circuitBreaker?.levels ?? {}).filter(
                            (n) =>
                              !(
                                draft.circuitBreakerDefaults.include &&
                                draft.circuitBreakerDefaults.levelOrder.includes(n)
                              ),
                          ),
                        ].map((name) => {
                          const globalLevel = draft.circuitBreakerDefaults.include
                            ? draft.circuitBreakerDefaults.levels[name]
                            : undefined;
                          const override = config.circuitBreaker?.levels[name];
                          const restOfDay = override?.haltDurationNs === null;
                          const globalShift = globalLevel
                            ? fractionToPercent(globalLevel.priceShiftPct)
                            : undefined;
                          const globalHaltMin =
                            globalLevel && globalLevel.haltDurationNs !== null
                              ? nsToMinutes(globalLevel.haltDurationNs)
                              : null;

                          // Mutate this symbol's override for `name`, pruning the
                          // level entry when it carries no override fields.
                          const mutateLevel = (fn: (lvl: Partial<CbLevel>) => void) =>
                            update((d) => {
                              const s = d.symbols[symbol]!;
                              s.circuitBreaker = s.circuitBreaker ?? { levels: {} };
                              const lvl: Partial<CbLevel> = { ...s.circuitBreaker.levels[name] };
                              fn(lvl);
                              if (Object.keys(lvl).length === 0) delete s.circuitBreaker.levels[name];
                              else s.circuitBreaker.levels[name] = lvl;
                            });

                          return (
                            <tr key={name} className="border-t border-border">
                              <td className="px-3 py-1.5 font-medium">
                                {name}
                                {!globalLevel && (
                                  <span className="ml-1 text-xs text-fg-subtle">(this symbol only)</span>
                                )}
                              </td>
                              <td className="px-3 py-1.5">
                                <NumberInput
                                  aria-label={`${name} shift override percent`}
                                  value={
                                    override?.priceShiftPct !== undefined
                                      ? fractionToPercent(override.priceShiftPct)
                                      : undefined
                                  }
                                  placeholder={globalShift !== undefined ? String(globalShift) : undefined}
                                  min={0}
                                  max={100}
                                  step={0.5}
                                  onChange={(v) =>
                                    mutateLevel((lvl) => {
                                      if (v === undefined) delete lvl.priceShiftPct;
                                      else lvl.priceShiftPct = percentToFraction(v);
                                    })
                                  }
                                  className="w-24"
                                />
                              </td>
                              <td className="px-3 py-1.5">
                                <NumberInput
                                  aria-label={`${name} halt minutes override`}
                                  value={
                                    typeof override?.haltDurationNs === "number"
                                      ? (nsToMinutes(override.haltDurationNs) ?? undefined)
                                      : undefined
                                  }
                                  placeholder={globalHaltMin !== null ? String(globalHaltMin) : undefined}
                                  min={1}
                                  disabled={restOfDay}
                                  onChange={(v) =>
                                    mutateLevel((lvl) => {
                                      // Rest of day is its own switch; a zero
                                      // here must not turn it on silently.
                                      if (v === undefined) delete lvl.haltDurationNs;
                                      else if (v > 0) lvl.haltDurationNs = minutesToNs(v);
                                    })
                                  }
                                  className="w-24"
                                />
                              </td>
                              <td className="px-3 py-1.5">
                                <Switch
                                  aria-label={`${name} rest of day override`}
                                  checked={restOfDay}
                                  onCheckedChange={(c) =>
                                    mutateLevel((lvl) => {
                                      if (c) lvl.haltDurationNs = null;
                                      else delete lvl.haltDurationNs;
                                    })
                                  }
                                />
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <TextInput
                      aria-label="New symbol-only level name"
                      value={newCbLevel}
                      onChange={setNewCbLevel}
                      placeholder="e.g. L4"
                      className="w-28"
                    />
                    <button
                      type="button"
                      disabled={
                        uppercaseId(newCbLevel) === "" ||
                        uppercaseId(newCbLevel) in (config.circuitBreaker?.levels ?? {}) ||
                        (draft.circuitBreakerDefaults.include &&
                          uppercaseId(newCbLevel) in draft.circuitBreakerDefaults.levels)
                      }
                      onClick={() => {
                        const name = uppercaseId(newCbLevel);
                        update((d) => {
                          const s = d.symbols[symbol]!;
                          s.circuitBreaker = s.circuitBreaker ?? { levels: {} };
                          s.circuitBreaker.levels[name] = { priceShiftPct: 0.25, haltDurationNs: null };
                        });
                        setNewCbLevel("");
                      }}
                      className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50"
                    >
                      + Add level for this symbol
                    </button>
                  </div>
                  <p className="mt-2 text-xs text-fg-subtle">
                    Blank cells inherit the global ladder value (shown as the greyed placeholder).
                    A level only this symbol defines must set its own shift; clearing all of its
                    cells removes it.
                  </p>
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
                    value={config.marketMaker?.enforceMmObligation === undefined ? INHERIT : config.marketMaker.enforceMmObligation ? "true" : "false"}
                    onValueChange={(v) =>
                      update((d) => {
                        const s = d.symbols[symbol]!;
                        s.marketMaker = s.marketMaker ?? {};
                        s.marketMaker.enforceMmObligation = v === INHERIT ? undefined : v === "true";
                      })
                    }
                    options={[
                      { value: INHERIT, label: "(inherit)" },
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
                    tickDecimals={config.tickDecimals}
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

      {overviewSymbol && (
        <SymbolOverviewDialog
          open={overviewSymbol !== null}
          onOpenChange={(o) => {
            if (!o) setOverviewSymbol(null);
          }}
          symbol={overviewSymbol}
        />
      )}
    </Panel>
  );
}

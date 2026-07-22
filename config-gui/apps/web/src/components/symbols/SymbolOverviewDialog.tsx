import * as RadixDialog from "@radix-ui/react-dialog";
import clsx from "clsx";
import {
  resolveEffectiveSymbol,
  type EffectiveCollar,
  type EffectiveMmQuote,
} from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import { fractionToPercent, nsToMinutes } from "@/lib/format";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  symbol: string;
}

function collarSourceLabel(source: EffectiveCollar["staticSource"], levelName?: string): string {
  if (source === "override") return "symbol override";
  if (source === "level") return `level ${levelName ?? ""}`.trim();
  return "engine default";
}

function haltLabel(ns: number | null): string {
  return ns === null ? "rest of day" : `${nsToMinutes(ns)} min`;
}

function originBadge(origin: EffectiveMmQuote["origin"]) {
  const map = {
    explicit: { text: "explicit", cls: "text-success" },
    seeded: { text: "seeded", cls: "text-success" },
    stub: { text: "fill in", cls: "text-warning" },
  } as const;
  const m = map[origin];
  return <span className={clsx("text-xs", m.cls)}>{m.text}</span>;
}

/** Section wrapper. */
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-fg-subtle">{title}</h3>
      <div className="rounded-md border border-border bg-surface p-3">{children}</div>
    </section>
  );
}

function DefRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-0.5 text-sm">
      <span className="text-fg-subtle">{label}</span>
      <span className="text-right">{children}</span>
    </div>
  );
}

function Src({ children }: { children: React.ReactNode }) {
  return <span className="ml-2 text-xs text-fg-subtle">· {children}</span>;
}

/**
 * Read-only overview of a symbol's *effective* configuration — the values the
 * engine will use after all inheritance/merge rules, with each value annotated
 * by its source. Consolidates what is otherwise spread across the symbol
 * sub-tabs.
 */
export function SymbolOverviewDialog({ open, onOpenChange, symbol }: Props) {
  const draft = useDraftStore((s) => s.draft);
  const eff = resolveEffectiveSymbol(draft, symbol);

  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-black/50" />
        <RadixDialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[min(720px,94vw)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-border bg-surface-raised p-5 shadow-xl">
          <div className="mb-3 flex items-center justify-between">
            <RadixDialog.Title className="text-base font-semibold">
              Overview — {symbol}
            </RadixDialog.Title>
            {eff?.level && (
              <span className="rounded bg-muted px-2 py-0.5 text-xs">
                Risk level: {eff.level}
                <span className="ml-1 text-fg-subtle">
                  ({eff.levelSource === "symbol" ? "assigned" : "default"})
                </span>
              </span>
            )}
          </div>
          <RadixDialog.Description className="sr-only">
            Read-only effective configuration for symbol {symbol}.
          </RadixDialog.Description>

          {!eff ? (
            <p className="text-sm text-fg-subtle">Symbol not found.</p>
          ) : (
            <div className="space-y-4">
              {/* General */}
              <Section title="General">
                <DefRow label="Tick decimals">
                  {eff.tickDecimals}
                  <Src>{eff.tickOverridden ? "per-symbol override" : "global default"}</Src>
                </DefRow>
                <DefRow label="Last buy price">{eff.lastBuyPrice ?? "—"}</DefRow>
                <DefRow label="Last sell price">{eff.lastSellPrice ?? "—"}</DefRow>
                <DefRow label="Outstanding shares">
                  {eff.outstandingShares !== undefined ? eff.outstandingShares.toLocaleString() : "—"}
                </DefRow>
                <DefRow label="Risk level">
                  {eff.level ?? "none"}
                  {eff.level && (
                    <Src>{eff.levelSource === "symbol" ? "assigned" : "inherited default"}</Src>
                  )}
                </DefRow>
              </Section>

              {/* Collar */}
              <Section title="Collar (effective)">
                {!eff.collar.applies ? (
                  <p className="text-sm text-fg-subtle">
                    No collar — orders for this symbol are not price-collar checked.
                  </p>
                ) : (
                  <>
                    <DefRow label="Static band">
                      {fractionToPercent(eff.collar.staticBandPct!)}%
                      <Src>{collarSourceLabel(eff.collar.staticSource, eff.collar.levelName)}</Src>
                    </DefRow>
                    <DefRow label="Dynamic band">
                      {fractionToPercent(eff.collar.dynamicBandPct!)}%
                      <Src>{collarSourceLabel(eff.collar.dynamicSource, eff.collar.levelName)}</Src>
                    </DefRow>
                  </>
                )}
                {!eff.collar.enforcedGlobally && (
                  <p className="mt-2 text-xs text-warning">
                    ! Collar enforcement is disabled globally (Risk &amp; Collars).
                  </p>
                )}
              </Section>

              {/* Circuit breaker */}
              <Section title="Circuit breaker (effective)">
                {!eff.circuitBreaker.enforcedGlobally && (
                  <p className="mb-2 text-xs text-warning">
                    ! Circuit breakers are disabled globally — this ladder will not be enforced.
                  </p>
                )}
                <DefRow label="Reference window">
                  {nsToMinutes(eff.circuitBreaker.referenceWindowNs)} min
                  <Src>{eff.circuitBreaker.windowOverridden ? "per-symbol override" : "global default"}</Src>
                </DefRow>
                <table className="mt-2 w-full text-sm">
                  <thead className="text-left text-xs uppercase text-fg-subtle">
                    <tr>
                      <th className="py-1">Level</th>
                      <th className="py-1">Shift %</th>
                      <th className="py-1">Halt</th>
                      <th className="py-1">Resumption</th>
                    </tr>
                  </thead>
                  <tbody>
                    {eff.circuitBreaker.levels.map((l) => (
                      <tr key={l.name} className="border-t border-border">
                        <td className="py-1 font-medium">{l.name}</td>
                        <td className={clsx("py-1", l.shiftOverridden && "text-accent font-medium")} title={l.shiftOverridden ? "per-symbol override" : "inherited"}>
                          {fractionToPercent(l.priceShiftPct)}%
                        </td>
                        <td className={clsx("py-1", l.haltOverridden && "text-accent font-medium")} title={l.haltOverridden ? "per-symbol override" : "inherited"}>
                          {haltLabel(l.haltDurationNs)}
                        </td>
                        <td className={clsx("py-1", l.resumptionOverridden && "text-accent font-medium")} title={l.resumptionOverridden ? "per-symbol override" : "inherited"}>
                          {l.resumptionMode}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-1 text-xs text-fg-subtle">
                  Values in accent are per-symbol overrides; the rest inherit the global ladder.
                </p>
              </Section>

              {/* Market maker */}
              {eff.marketMakerRelevant && (
                <Section title="Market maker (effective)">
                  <DefRow label="Enforce obligation">
                    {eff.mmObligation.enforce ? "Yes" : "No"}
                    <Src>{eff.mmObligation.enforceOverridden ? "symbol override" : "global default"}</Src>
                  </DefRow>
                  <DefRow label="Max spread (ticks)">
                    {eff.mmObligation.maxSpreadTicks}
                    <Src>{eff.mmObligation.maxSpreadOverridden ? "symbol override" : "global default"}</Src>
                  </DefRow>
                  <DefRow label="Min quantity">
                    {eff.mmObligation.minQty}
                    <Src>{eff.mmObligation.minQtyOverridden ? "symbol override" : "global default"}</Src>
                  </DefRow>

                  {eff.mmObligation.perGatewayOverrides.length > 0 && (
                    <div className="mt-2 text-xs text-fg-subtle">
                      <div className="font-medium">Per-gateway overrides:</div>
                      <ul className="mt-0.5 list-inside list-disc">
                        {eff.mmObligation.perGatewayOverrides.map((o) => (
                          <li key={o.gatewayId}>
                            {o.gatewayId}:{" "}
                            {[
                              o.enforceMmObligation !== undefined
                                ? `enforce ${o.enforceMmObligation ? "on" : "off"}`
                                : null,
                              o.maxSpreadTicks !== undefined ? `max spread ${o.maxSpreadTicks}` : null,
                              o.minQty !== undefined ? `min qty ${o.minQty}` : null,
                            ]
                              .filter(Boolean)
                              .join(", ")}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <div className="mt-3 overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="text-left text-xs uppercase text-fg-subtle">
                        <tr>
                          <th className="py-1">Gateway</th>
                          <th className="py-1">Bid</th>
                          <th className="py-1">Ask</th>
                          <th className="py-1">Bid qty</th>
                          <th className="py-1">Ask qty</th>
                          <th className="py-1">TIF</th>
                          <th className="py-1">Seed once</th>
                          <th className="py-1">Source</th>
                        </tr>
                      </thead>
                      <tbody>
                        {eff.mmQuotes.map((q, i) => (
                          <tr key={`${q.gatewayId}-${i}`} className="border-t border-border">
                            <td className="py-1 font-medium">{q.gatewayId}</td>
                            <td className="py-1">{q.bidPrice ?? "—"}</td>
                            <td className="py-1">{q.askPrice ?? "—"}</td>
                            <td className="py-1">{q.bidQty}</td>
                            <td className="py-1">{q.askQty}</td>
                            <td className="py-1">{q.tif}</td>
                            <td className="py-1">{q.seedOnce ? "yes" : "no"}</td>
                            <td className="py-1">{originBadge(q.origin)}</td>
                          </tr>
                        ))}
                        {eff.mmQuotes.length === 0 && (
                          <tr>
                            <td colSpan={8} className="py-2 text-center text-fg-subtle">
                              No market-maker quotes.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </Section>
              )}

              {/* Memberships */}
              <Section title="Memberships">
                <DefRow label="Indices">
                  {eff.indices.length > 0 ? eff.indices.join(", ") : "none"}
                </DefRow>
                <DefRow label="Combos">
                  {eff.combos.length > 0 ? eff.combos.join(", ") : "none"}
                </DefRow>
              </Section>
            </div>
          )}

          <div className="mt-5 flex justify-end">
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg"
            >
              Close
            </button>
          </div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

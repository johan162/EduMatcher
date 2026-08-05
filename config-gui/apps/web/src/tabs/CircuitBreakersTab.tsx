import { bandPctAt } from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import { usePersona } from "@/lib/usePersona";
import { fractionToPercent, minutesToNs, nsToMinutes, percentToFraction } from "@/lib/format";
import { Panel, Section } from "@/components/layout/Panel";
import { FieldRow } from "@/components/fields/FieldRow";
import { NumberInput } from "@/components/fields/inputs";
import { Switch } from "@/components/ui/Switch";

export function CircuitBreakersTab() {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);
  const { canSee } = usePersona();
  const cb = draft.circuitBreakerDefaults;
  const ace = cb.reopening;
  const editable = canSee("I");

  return (
    <Panel
      tabId="circuit-breakers"
      title="Circuit Breakers"
      intro="Circuit breakers halt trading when a symbol moves too far from its rolling reference price. Each ladder level has a shift % (how far) and a halt duration (how long the reopening auction collects orders for)."
    >
      <Section title="Enforcement">
        <FieldRow
          label="Enforce circuit breakers"
          path="enforceCircuitBreakers"
          htmlFor="enforce-cb"
          help={{
            text: "Global switch for halt detection and enforcement. Turning it off is for tests only.",
            cliFlag: "--no-circuit-breakers (inverted)",
          }}
        >
          <Switch
            id="enforce-cb"
            aria-label="Enforce circuit breakers"
            checked={draft.enforceCircuitBreakers}
            onCheckedChange={(checked) => update((d) => (d.enforceCircuitBreakers = checked))}
          />
        </FieldRow>
        {!draft.enforceCircuitBreakers && (
          <div className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning">
            Circuit breakers are disabled — suitable for tests only. The ladder below will not be emitted.
          </div>
        )}
      </Section>

      {canSee("I") && (
        <Section title="Reference window">
          <FieldRow
            label="Reference window (minutes)"
            path="circuitBreakerDefaults.windowNs"
            help={{
              text: "Lookback window used to compute the rolling reference price for halt triggers.",
              cliFlag: "--cb-window-ns",
            }}
          >
            <NumberInput
              aria-label="Reference window minutes"
              value={nsToMinutes(cb.windowNs) ?? undefined}
              min={1}
              onChange={(v) => update((d) => (d.circuitBreakerDefaults.windowNs = minutesToNs(v ?? 5)!))}
            />
            <span className="text-sm text-fg-subtle">min</span>
          </FieldRow>
        </Section>
      )}

      <Section
        title="Ladder"
        description={
          editable
            ? "Each level triggers at its shift % from the reference price."
            : "Built-in three-level ladder. Switch to Intermediate to customize it."
        }
      >
        <div className="overflow-hidden rounded-md border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted text-left text-xs uppercase text-fg-subtle">
              <tr>
                <th className="px-3 py-2">Level</th>
                <th className="px-3 py-2">Shift %</th>
                <th className="px-3 py-2">Call phase min (min)</th>
                <th className="px-3 py-2">Rest of day</th>
                {canSee("E") && <th className="px-3 py-2" />}
              </tr>
            </thead>
            <tbody>
              {cb.levelOrder.map((name) => {
                const level = cb.levels[name]!;
                const restOfDay = level.haltDurationNs === null;
                return (
                  <tr key={name} className="border-t border-border">
                    <td className="px-3 py-1.5 font-medium">{name}</td>
                    <td className="px-3 py-1.5">
                      <NumberInput
                        aria-label={`${name} shift percent`}
                        value={fractionToPercent(level.priceShiftPct)}
                        disabled={!editable}
                        min={0}
                        max={100}
                        step={0.5}
                        onChange={(v) =>
                          update((d) => {
                            d.circuitBreakerDefaults.levels[name]!.priceShiftPct = percentToFraction(v ?? 0);
                          })
                        }
                        className="w-24"
                      />
                    </td>
                    <td className="px-3 py-1.5">
                      <NumberInput
                        aria-label={`${name} halt minutes`}
                        value={restOfDay ? undefined : (nsToMinutes(level.haltDurationNs) ?? undefined)}
                        disabled={!editable || restOfDay}
                        min={1}
                        onChange={(v) =>
                          update((d) => {
                            d.circuitBreakerDefaults.levels[name]!.haltDurationNs = minutesToNs(v ?? 0);
                          })
                        }
                        className="w-24"
                      />
                    </td>
                    <td className="px-3 py-1.5">
                      <Switch
                        aria-label={`${name} rest of day`}
                        disabled={!editable}
                        checked={restOfDay}
                        onCheckedChange={(checked) =>
                          update((d) => {
                            d.circuitBreakerDefaults.levels[name]!.haltDurationNs = checked
                              ? null
                              : minutesToNs(5);
                          })
                        }
                      />
                    </td>
                    {canSee("E") && (
                      <td className="px-3 py-1.5 text-right">
                        <button
                          type="button"
                          aria-label={`Remove ${name}`}
                          onClick={() =>
                            update((d) => {
                              delete d.circuitBreakerDefaults.levels[name];
                              d.circuitBreakerDefaults.levelOrder = d.circuitBreakerDefaults.levelOrder.filter(
                                (n) => n !== name,
                              );
                            })
                          }
                          className="text-fg-subtle hover:text-error"
                        >
                          ×
                        </button>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {canSee("E") && (
          <button
            type="button"
            onClick={() =>
              update((d) => {
                let i = d.circuitBreakerDefaults.levelOrder.length + 1;
                let name = `L${i}`;
                while (d.circuitBreakerDefaults.levels[name]) name = `L${++i}`;
                d.circuitBreakerDefaults.levels[name] = {
                  priceShiftPct: 0.25,
                  haltDurationNs: null,
                };
                d.circuitBreakerDefaults.levelOrder.push(name);
              })
            }
            className="mt-2 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
          >
            + Add level
          </button>
        )}
        {!canSee("E") && editable && (
          <p className="mt-2 text-xs text-linked">Switch to Expert to add or remove ladder levels.</p>
        )}
      </Section>

      <Section
        title="Reopening auction (ACE)"
        description="A halt is the call phase of a reopening auction. Automated Corridor Expansion decides whether it may end: the symbol reopens only if the indicative uncross price falls inside a corridor centred on the reference price. Otherwise the corridor widens and another call phase begins."
      >
        <FieldRow
          label="Enable ACE"
          path="circuitBreakerDefaults.reopening.enabled"
          htmlFor="ace-enabled"
          help={{
            text: "When off, a halt reopens at whatever equilibrium price the resting orders imply, with no corridor and no extensions.",
            cliFlag: "--no-ace (inverted)",
          }}
        >
          <Switch
            id="ace-enabled"
            aria-label="Enable ACE"
            checked={ace.enabled}
            disabled={!editable}
            onCheckedChange={(checked) =>
              update((d) => (d.circuitBreakerDefaults.reopening.enabled = checked))
            }
          />
        </FieldRow>

        {ace.enabled && (
          <>
            <FieldRow
              label="Initial corridor (±%)"
              path="circuitBreakerDefaults.reopening.initialBandPct"
              help={{
                text: "Corridor half-width at the start of the first call phase, as a percentage of the circuit breaker's rolling reference price.",
                cliFlag: "--ace-initial-band",
              }}
            >
              <NumberInput
                aria-label="Initial corridor percent"
                value={fractionToPercent(ace.initialBandPct)}
                disabled={!editable}
                min={0}
                max={100}
                step={0.5}
                onChange={(v) =>
                  update((d) => {
                    d.circuitBreakerDefaults.reopening.initialBandPct = percentToFraction(v ?? 10);
                  })
                }
                className="w-24"
              />
              <span className="text-sm text-fg-subtle">%</span>
            </FieldRow>

            <FieldRow
              label="Random end (seconds)"
              path="circuitBreakerDefaults.reopening.randomEndMaxNs"
              help={{
                text: "Every call phase ends at a uniformly random point within this many seconds after its minimum duration, so the uncross instant cannot be targeted. 0 makes reopen times exactly predictable — useful in a classroom, wrong in production.",
                cliFlag: "--ace-random-end-ns",
              }}
            >
              <NumberInput
                aria-label="Random end seconds"
                value={ace.randomEndMaxNs / 1_000_000_000}
                disabled={!editable}
                min={0}
                onChange={(v) =>
                  update((d) => {
                    d.circuitBreakerDefaults.reopening.randomEndMaxNs = Math.round((v ?? 0) * 1_000_000_000);
                  })
                }
                className="w-24"
              />
              <span className="text-sm text-fg-subtle">s</span>
            </FieldRow>

            {ace.randomEndMaxNs === 0 && (
              <div className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning">
                Random end disabled — every reopen happens at an exactly predictable
                instant, which the last order in can target with full sight of the book.
              </div>
            )}

            {canSee("E") && (
              <FieldRow
                label="Random seed"
                path="circuitBreakerDefaults.reopening.randomSeed"
                help={{
                  text: "Engine-wide, and only valid here — pm-cverifier rejects a per-symbol seed (S110). Leave empty for OS entropy; set an integer for reproducible demos.",
                  cliFlag: "--ace-random-seed",
                }}
              >
                <NumberInput
                  aria-label="ACE random seed"
                  value={ace.randomSeed}
                  disabled={!editable}
                  onChange={(v) =>
                    update((d) => {
                      if (v === undefined || v === null) delete d.circuitBreakerDefaults.reopening.randomSeed;
                      else d.circuitBreakerDefaults.reopening.randomSeed = Math.round(v);
                    })
                  }
                  className="w-32"
                />
                <span className="text-sm text-fg-subtle">empty = OS entropy</span>
              </FieldRow>
            )}

            <div className="mt-4">
              <div className="mb-1 text-xs uppercase text-fg-subtle">
                Expansion ladder
              </div>
              <p className="mb-2 text-xs text-fg-subtle">
                Applied in order when a call phase ends with the price outside the
                corridor. Widening is additive on the reference price, not compounding.
                The last rung repeats indefinitely — which is why there is no
                maximum-extensions setting: the corridor eventually contains any price,
                so every halt resolves on its own.
              </p>
              <div className="overflow-hidden rounded-md border border-border">
                <table className="w-full text-sm">
                  <thead className="bg-muted text-left text-xs uppercase text-fg-subtle">
                    <tr>
                      <th className="px-3 py-2">#</th>
                      <th className="px-3 py-2">Widen by %</th>
                      <th className="px-3 py-2">Call phase min (min)</th>
                      <th className="px-3 py-2">Corridor after</th>
                      {canSee("E") && <th className="px-3 py-2" />}
                    </tr>
                  </thead>
                  <tbody>
                    {ace.expansions.map((rung, i) => (
                      <tr key={i} className="border-t border-border">
                        <td className="px-3 py-1.5 font-medium">
                          {i + 1}
                          {i === ace.expansions.length - 1 && (
                            <span className="ml-1 text-xs text-fg-subtle">(repeats)</span>
                          )}
                        </td>
                        <td className="px-3 py-1.5">
                          <NumberInput
                            aria-label={`Expansion ${i + 1} widen percent`}
                            value={fractionToPercent(rung.widenPct)}
                            disabled={!editable}
                            min={0}
                            max={100}
                            step={0.5}
                            onChange={(v) =>
                              update((d) => {
                                d.circuitBreakerDefaults.reopening.expansions[i]!.widenPct =
                                  percentToFraction(v ?? 10);
                              })
                            }
                            className="w-24"
                          />
                        </td>
                        <td className="px-3 py-1.5">
                          <NumberInput
                            aria-label={`Expansion ${i + 1} minimum minutes`}
                            value={nsToMinutes(rung.minDurationNs) ?? undefined}
                            disabled={!editable}
                            min={1}
                            onChange={(v) =>
                              update((d) => {
                                d.circuitBreakerDefaults.reopening.expansions[i]!.minDurationNs =
                                  minutesToNs(v ?? 2)!;
                              })
                            }
                            className="w-24"
                          />
                        </td>
                        <td className="px-3 py-1.5 tabular-nums text-fg-subtle">
                          ±{fractionToPercent(bandPctAt(ace, i + 1)).toFixed(1)}%
                        </td>
                        {canSee("E") && (
                          <td className="px-3 py-1.5 text-right">
                            <button
                              type="button"
                              aria-label={`Remove expansion ${i + 1}`}
                              disabled={ace.expansions.length <= 1}
                              onClick={() =>
                                update((d) => {
                                  d.circuitBreakerDefaults.reopening.expansions.splice(i, 1);
                                })
                              }
                              className="text-fg-subtle hover:text-error disabled:opacity-30"
                            >
                              ×
                            </button>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {canSee("E") && (
                <button
                  type="button"
                  onClick={() =>
                    update((d) => {
                      const last =
                        d.circuitBreakerDefaults.reopening.expansions[
                          d.circuitBreakerDefaults.reopening.expansions.length - 1
                        ];
                      d.circuitBreakerDefaults.reopening.expansions.push({
                        widenPct: last?.widenPct ?? 0.2,
                        minDurationNs: last?.minDurationNs ?? minutesToNs(5)!,
                      });
                    })
                  }
                  className="mt-2 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
                >
                  + Add expansion
                </button>
              )}

              <p className="mt-3 text-xs text-fg-subtle">
                A symbol at a reference price of 100.00 would reopen inside{" "}
                {ace.expansions.slice(0, 3).map((_, i) => {
                  const pct = bandPctAt(ace, i);
                  return (
                    <span key={i} className="tabular-nums">
                      {i > 0 && " → "}
                      {(100 * (1 - pct)).toFixed(2)}–{(100 * (1 + pct)).toFixed(2)}
                    </span>
                  );
                })}
                {" → …"} widening until it fits. Still halted at the close? It prints at
                the corridor boundary.
              </p>
            </div>
          </>
        )}
      </Section>
    </Panel>
  );
}

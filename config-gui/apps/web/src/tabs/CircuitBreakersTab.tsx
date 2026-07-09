import { RESUMPTION_MODES, type ResumptionMode } from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import { usePersona } from "@/lib/usePersona";
import { fractionToPercent, minutesToNs, nsToMinutes, percentToFraction } from "@/lib/format";
import { Panel, Section } from "@/components/layout/Panel";
import { FieldRow } from "@/components/fields/FieldRow";
import { NumberInput } from "@/components/fields/inputs";
import { Select } from "@/components/ui/Select";
import { Switch } from "@/components/ui/Switch";

export function CircuitBreakersTab() {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);
  const { canSee } = usePersona();
  const cb = draft.circuitBreakerDefaults;
  const editable = canSee("I");

  return (
    <Panel
      tabId="circuit-breakers"
      title="Circuit Breakers"
      intro="Circuit breakers halt trading when a symbol moves too far from its rolling reference price. Each ladder level has a shift % (how far), a halt duration, and a resumption mode (AUCTION runs an uncross, CONTINUOUS reopens immediately)."
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
                <th className="px-3 py-2">Halt (min)</th>
                <th className="px-3 py-2">Rest of day</th>
                <th className="px-3 py-2">Resumption</th>
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
                    <td className="px-3 py-1.5">
                      <Select
                        aria-label={`${name} resumption mode`}
                        disabled={!editable}
                        value={level.resumptionMode}
                        onValueChange={(v) =>
                          update((d) => {
                            d.circuitBreakerDefaults.levels[name]!.resumptionMode = v as ResumptionMode;
                          })
                        }
                        options={RESUMPTION_MODES.map((m) => ({ value: m, label: m }))}
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
                  resumptionMode: "AUCTION",
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
    </Panel>
  );
}

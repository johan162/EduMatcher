import { DEFAULT_DYNAMIC_BAND_PCT } from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import { usePersona } from "@/lib/usePersona";
import { fractionToPercent, percentToFraction, uppercaseId } from "@/lib/format";
import { Panel, Section } from "@/components/layout/Panel";
import { FieldRow } from "@/components/fields/FieldRow";
import { NumberInput, TextInput } from "@/components/fields/inputs";

export function RiskTab() {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);
  const { canSee } = usePersona();

  const rc = draft.riskControls;

  return (
    <Panel
      tabId="risk"
      title="Risk & Collars"
      intro="A collar rejects orders priced too far from a reference. The static band anchors to a session reference price; the dynamic band tracks near-live prices. Setting a global band creates a DEFAULT risk level applied to all symbols."
    >
      <Section title="Global collar (DEFAULT level)">
        <FieldRow
          label="Static band"
          path="riskControls.globalStaticBandPct"
          help={{
            text: "Wider guardrail around the reference price, as a percent. Leaving this empty means no collar unless a symbol has its own.",
            cliFlag: "--static-band",
          }}
          defaultHint="Default: no collar"
          isSet={rc.globalStaticBandPct !== undefined}
          onReset={() => update((d) => (d.riskControls.globalStaticBandPct = undefined))}
        >
          <NumberInput
            aria-label="Global static band percent"
            value={rc.globalStaticBandPct !== undefined ? fractionToPercent(rc.globalStaticBandPct) : undefined}
            min={0}
            max={100}
            step={0.5}
            onChange={(v) =>
              update((d) => {
                d.riskControls.globalStaticBandPct = v === undefined ? undefined : percentToFraction(v);
              })
            }
          />
          <span className="text-sm text-fg-subtle">%</span>
        </FieldRow>

        <FieldRow
          label="Dynamic band"
          path="riskControls.globalDynamicBandPct"
          help={{
            text: "Tighter guardrail tracking near-live prices, as a percent.",
            cliFlag: "--dynamic-band",
          }}
          defaultHint={`Default: ${fractionToPercent(DEFAULT_DYNAMIC_BAND_PCT)}% (when static band is set)`}
          isSet={rc.globalDynamicBandPct !== undefined}
          onReset={() => update((d) => (d.riskControls.globalDynamicBandPct = undefined))}
        >
          <NumberInput
            aria-label="Global dynamic band percent"
            value={rc.globalDynamicBandPct !== undefined ? fractionToPercent(rc.globalDynamicBandPct) : undefined}
            min={0}
            max={100}
            step={0.5}
            onChange={(v) =>
              update((d) => {
                d.riskControls.globalDynamicBandPct = v === undefined ? undefined : percentToFraction(v);
              })
            }
          />
          <span className="text-sm text-fg-subtle">%</span>
        </FieldRow>
      </Section>

      {canSee("I") ? (
        <Section
          title="Named risk levels"
          description="Reusable collar profiles that symbols can reference by name (in the Symbols tab). Names are uppercased and must be unique."
        >
          {Object.entries(rc.levels).map(([name, level]) => (
            <div key={name} className="rounded-md border border-border bg-surface-raised p-3">
              <div className="flex flex-wrap items-end gap-3">
                <label className="text-sm">
                  <span className="mb-1 block font-medium">Name</span>
                  <TextInput
                    aria-label={`Risk level ${name} name`}
                    value={name}
                    onChange={(v) =>
                      update((d) => {
                        const newName = uppercaseId(v);
                        if (newName && newName !== name && !d.riskControls.levels[newName]) {
                          d.riskControls.levels[newName] = d.riskControls.levels[name]!;
                          delete d.riskControls.levels[name];
                        }
                      })
                    }
                    className="w-40"
                  />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block font-medium">Static %</span>
                  <NumberInput
                    aria-label={`Risk level ${name} static percent`}
                    value={fractionToPercent(level.staticBandPct)}
                    min={0}
                    max={100}
                    step={0.5}
                    onChange={(v) =>
                      update((d) => {
                        d.riskControls.levels[name]!.staticBandPct = percentToFraction(v ?? 0);
                      })
                    }
                    className="w-28"
                  />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block font-medium">Dynamic %</span>
                  <NumberInput
                    aria-label={`Risk level ${name} dynamic percent`}
                    value={fractionToPercent(level.dynamicBandPct)}
                    min={0}
                    max={100}
                    step={0.5}
                    onChange={(v) =>
                      update((d) => {
                        d.riskControls.levels[name]!.dynamicBandPct = percentToFraction(v ?? 0);
                      })
                    }
                    className="w-28"
                  />
                </label>
                <button
                  type="button"
                  onClick={() =>
                    update((d) => {
                      delete d.riskControls.levels[name];
                    })
                  }
                  className="ml-auto rounded-md border border-border px-2 py-1 text-sm text-fg-subtle hover:text-error"
                >
                  Remove
                </button>
              </div>
            </div>
          ))}
          <button
            type="button"
            onClick={() =>
              update((d) => {
                let i = d.riskControls.levels ? Object.keys(d.riskControls.levels).length + 1 : 1;
                let name = `LEVEL${i}`;
                while (d.riskControls.levels[name]) name = `LEVEL${++i}`;
                d.riskControls.levels[name] = { staticBandPct: 0.2, dynamicBandPct: 0.02 };
              })
            }
            className="mt-2 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
          >
            + Add risk level
          </button>
        </Section>
      ) : (
        <p className="mt-4 text-sm text-linked">
          Switch to Intermediate to define named risk levels and per-symbol collar overrides.
        </p>
      )}
    </Panel>
  );
}

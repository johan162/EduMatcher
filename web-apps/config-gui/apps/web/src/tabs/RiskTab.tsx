import { useState } from "react";
import {
  DEFAULT_DYNAMIC_BAND_PCT,
  DEFAULT_STATIC_BAND_PCT,
  effectiveDefaultCollar,
  type EngineConfigDraft,
} from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import { usePersona } from "@/lib/usePersona";
import { fractionToPercent, percentToFraction, uppercaseId } from "@/lib/format";
import { Panel, Section } from "@/components/layout/Panel";
import { FieldRow } from "@/components/fields/FieldRow";
import { NumberInput, TextInput } from "@/components/fields/inputs";
import { Select } from "@/components/ui/Select";
import { Switch } from "@/components/ui/Switch";

/** Radix Select cannot use "" as an option value (see SymbolsTab). */
const NO_DEFAULT = "__none__";

/** Rename a risk level and every reference to it (symbol levels, default level). */
function renameLevel(d: EngineConfigDraft, from: string, to: string): void {
  d.riskControls.levels[to] = d.riskControls.levels[from]!;
  delete d.riskControls.levels[from];
  if (d.riskControls.defaultLevel === from) d.riskControls.defaultLevel = to;
  for (const symbol of d.symbolOrder) {
    const cfg = d.symbols[symbol];
    if (cfg?.level === from) cfg.level = to;
  }
}

/**
 * Level name field. Edits are staged locally and committed on blur: the name
 * is the row's React key, so renaming per keystroke would remount the row and
 * drop focus after every character.
 */
function LevelNameInput({ name, disabled }: { name: string; disabled: boolean }) {
  const update = useDraftStore((s) => s.update);
  const taken = useDraftStore((s) => s.draft.riskControls.levels);
  const [text, setText] = useState(name);
  const commit = () => {
    const next = uppercaseId(text);
    if (next && next !== name && taken[next] === undefined) {
      update((d) => renameLevel(d, name, next));
    } else {
      setText(name);
    }
  };
  return (
    <TextInput
      aria-label={`Risk level ${name} name`}
      value={text}
      disabled={disabled}
      onChange={setText}
      onBlur={commit}
      className="w-40"
    />
  );
}

export function RiskTab() {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);
  const { canSee } = usePersona();

  const rc = draft.riskControls;
  const collarsEnabled = draft.enforceCollars;

  return (
    <Panel
      tabId="risk"
      title="Risk & Collars"
      intro="A collar rejects orders priced too far from a reference. The static band anchors to a session reference price; the dynamic band tracks near-live prices. Setting a global band creates a DEFAULT risk level applied to all symbols."
    >
      <Section title="Enforcement">
        <FieldRow
          label="Enforce collars"
          path="enforceCollars"
          htmlFor="enforce-collars"
          help={{
            text: "Global switch for price collar enforcement. Turning it off is for tests only.",
            cliFlag: "--no-collars",
          }}
        >
          <Switch
            id="enforce-collars"
            aria-label="Enforce collars"
            checked={draft.enforceCollars}
            onCheckedChange={(checked) => update((d) => (d.enforceCollars = checked))}
          />
        </FieldRow>
        {!collarsEnabled && (
          <div className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning">
            Collars are disabled — suitable for tests only. Bands and risk levels below will not be enforced.
          </div>
        )}
      </Section>

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
            disabled={!collarsEnabled}
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
            disabled={!collarsEnabled}
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
          description="Reusable collar profiles that symbols can reference by name (in the Symbols tab). Names are uppercased and must be unique. A blank band is left out of the file and the engine applies its default; with both blank the level has no collar."
        >
          <FieldRow
            label="Default level"
            path="riskControls.defaultLevel"
            help={{
              text: "Level applied to every symbol that does not name its own (risk_controls.default_level). With a global collar set, DEFAULT is the default level unless another is chosen.",
            }}
          >
            <Select
              aria-label="Default risk level"
              value={rc.defaultLevel ?? (effectiveDefaultCollar(draft) ? "DEFAULT" : NO_DEFAULT)}
              onValueChange={(v) =>
                update((d) => {
                  d.riskControls.defaultLevel =
                    v === NO_DEFAULT || (v === "DEFAULT" && effectiveDefaultCollar(d)) ? undefined : v;
                })
              }
              options={[
                ...(effectiveDefaultCollar(draft)
                  ? [{ value: "DEFAULT", label: "DEFAULT (global collar)" }]
                  : [{ value: NO_DEFAULT, label: "(none)" }]),
                ...Object.keys(rc.levels).map((n) => ({ value: n, label: n })),
                ...(rc.defaultLevel &&
                rc.levels[rc.defaultLevel] === undefined &&
                !(rc.defaultLevel === "DEFAULT" && effectiveDefaultCollar(draft))
                  ? [{ value: rc.defaultLevel, label: `${rc.defaultLevel} (undefined)` }]
                  : []),
              ]}
            />
          </FieldRow>
          {Object.entries(rc.levels).map(([name, level]) => (
            <div key={name} className="rounded-md border border-border bg-surface-raised p-3">
              <div className="flex flex-wrap items-end gap-3">
                <label className="text-sm">
                  <span className="mb-1 block font-medium">Name</span>
                  <LevelNameInput name={name} disabled={!collarsEnabled} />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block font-medium">Static %</span>
                  <NumberInput
                    aria-label={`Risk level ${name} static percent`}
                    value={level.staticBandPct !== undefined ? fractionToPercent(level.staticBandPct) : undefined}
                    placeholder={`${fractionToPercent(DEFAULT_STATIC_BAND_PCT)} (default)`}
                    disabled={!collarsEnabled}
                    min={0}
                    max={100}
                    step={0.5}
                    onChange={(v) =>
                      update((d) => {
                        d.riskControls.levels[name]!.staticBandPct =
                          v === undefined ? undefined : percentToFraction(v);
                      })
                    }
                    className="w-28"
                  />
                </label>
                <label className="text-sm">
                  <span className="mb-1 block font-medium">Dynamic %</span>
                  <NumberInput
                    aria-label={`Risk level ${name} dynamic percent`}
                    value={level.dynamicBandPct !== undefined ? fractionToPercent(level.dynamicBandPct) : undefined}
                    placeholder={`${fractionToPercent(DEFAULT_DYNAMIC_BAND_PCT)} (default)`}
                    disabled={!collarsEnabled}
                    min={0}
                    max={100}
                    step={0.5}
                    onChange={(v) =>
                      update((d) => {
                        d.riskControls.levels[name]!.dynamicBandPct =
                          v === undefined ? undefined : percentToFraction(v);
                      })
                    }
                    className="w-28"
                  />
                </label>
                {level.staticBandPct === undefined && level.dynamicBandPct === undefined && (
                  <span className="text-xs text-fg-subtle">No collar</span>
                )}
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
            disabled={!collarsEnabled}
            onClick={() =>
              update((d) => {
                let i = d.riskControls.levels ? Object.keys(d.riskControls.levels).length + 1 : 1;
                let name = `LEVEL${i}`;
                while (d.riskControls.levels[name]) name = `LEVEL${++i}`;
                d.riskControls.levels[name] = { staticBandPct: 0.2, dynamicBandPct: 0.02 };
              })
            }
            className="mt-2 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
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

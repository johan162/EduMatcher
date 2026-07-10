import { DEFAULT_SNAPSHOT_INTERVAL_SEC } from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import { Panel, Section } from "@/components/layout/Panel";
import { FieldRow } from "@/components/fields/FieldRow";
import { NumberInput } from "@/components/fields/inputs";

export function EngineTuningTab() {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);

  return (
    <Panel
      tabId="engine-tuning"
      title="Engine Tuning"
      intro="Low-level engine performance knobs. These rarely need to change from their defaults; adjust only if you understand the operational impact."
    >
      <Section title="Market data">
        <FieldRow
          label="Snapshot interval"
          path="snapshotIntervalSec"
          help={{
            text: "Per-symbol book snapshot throttle: the engine emits at most one book update per this many seconds for a given symbol.",
            cliFlag: "--snapshot-interval",
          }}
          defaultHint={`Default: ${DEFAULT_SNAPSHOT_INTERVAL_SEC}`}
          isSet={draft.snapshotIntervalSec !== DEFAULT_SNAPSHOT_INTERVAL_SEC}
          onReset={() => update((d) => (d.snapshotIntervalSec = DEFAULT_SNAPSHOT_INTERVAL_SEC))}
        >
          <NumberInput
            aria-label="Snapshot interval seconds"
            value={draft.snapshotIntervalSec}
            min={0.01}
            step={0.1}
            onChange={(v) => update((d) => (d.snapshotIntervalSec = v ?? DEFAULT_SNAPSHOT_INTERVAL_SEC))}
          />
          <span className="text-sm text-fg-subtle">sec</span>
        </FieldRow>
      </Section>
    </Panel>
  );
}

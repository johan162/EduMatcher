import {
  DEFAULT_DEPTH_SNAPSHOT_TOLERANCE_TICKS,
  DEFAULT_DROP_COPY_BUFFER_SIZE,
  DEFAULT_QUOTE_HISTORY_MAXLEN,
  DEFAULT_RECENT_TRADES_MAXLEN,
  DEFAULT_SNAPSHOT_INTERVAL_SEC,
} from "@edumatcher/schema";
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

        <FieldRow
          label="Depth snapshot tolerance"
          path="depthSnapshotToleranceTicks"
          help={{
            text: "Depth publish window around the last trade, measured in ticks. Larger values include more price levels and increase snapshot work and payload size.",
          }}
          defaultHint={`Default: ${DEFAULT_DEPTH_SNAPSHOT_TOLERANCE_TICKS}`}
          isSet={draft.depthSnapshotToleranceTicks !== DEFAULT_DEPTH_SNAPSHOT_TOLERANCE_TICKS}
          onReset={() =>
            update(
              (d) =>
                (d.depthSnapshotToleranceTicks =
                  DEFAULT_DEPTH_SNAPSHOT_TOLERANCE_TICKS),
            )
          }
        >
          <NumberInput
            aria-label="Depth snapshot tolerance ticks"
            value={draft.depthSnapshotToleranceTicks}
            min={1}
            step={1}
            onChange={(v) =>
              update(
                (d) =>
                  (d.depthSnapshotToleranceTicks =
                    v ?? DEFAULT_DEPTH_SNAPSHOT_TOLERANCE_TICKS),
              )
            }
          />
          <span className="text-sm text-fg-subtle">ticks</span>
        </FieldRow>
      </Section>

      <Section title="Retention">
        <FieldRow
          label="Quote history"
          path="quoteHistoryMaxlen"
          help={{
            text: "Maximum number of recently inactivated quotes retained per gateway for QLEGS RECENT/ALL.",
          }}
          defaultHint={`Default: ${DEFAULT_QUOTE_HISTORY_MAXLEN}`}
          isSet={draft.quoteHistoryMaxlen !== DEFAULT_QUOTE_HISTORY_MAXLEN}
          onReset={() =>
            update((d) => (d.quoteHistoryMaxlen = DEFAULT_QUOTE_HISTORY_MAXLEN))
          }
        >
          <NumberInput
            aria-label="Quote history max entries"
            value={draft.quoteHistoryMaxlen}
            min={1}
            step={1}
            onChange={(v) =>
              update((d) => (d.quoteHistoryMaxlen = v ?? DEFAULT_QUOTE_HISTORY_MAXLEN))
            }
          />
          <span className="text-sm text-fg-subtle">entries</span>
        </FieldRow>

        <FieldRow
          label="Drop copy buffer"
          path="dropCopyBufferSize"
          help={{
            text: "Number of drop-copy events kept in memory for replay after reconnect.",
          }}
          defaultHint={`Default: ${DEFAULT_DROP_COPY_BUFFER_SIZE}`}
          isSet={draft.dropCopyBufferSize !== DEFAULT_DROP_COPY_BUFFER_SIZE}
          onReset={() =>
            update((d) => (d.dropCopyBufferSize = DEFAULT_DROP_COPY_BUFFER_SIZE))
          }
        >
          <NumberInput
            aria-label="Drop copy buffer size"
            value={draft.dropCopyBufferSize}
            min={1}
            step={100}
            onChange={(v) =>
              update((d) => (d.dropCopyBufferSize = v ?? DEFAULT_DROP_COPY_BUFFER_SIZE))
            }
          />
          <span className="text-sm text-fg-subtle">messages</span>
        </FieldRow>

        <FieldRow
          label="Recent trades"
          path="recentTradesMaxlen"
          help={{
            text: "Number of recent trade rows retained per symbol for snapshots and diagnostics.",
          }}
          defaultHint={`Default: ${DEFAULT_RECENT_TRADES_MAXLEN}`}
          isSet={draft.recentTradesMaxlen !== DEFAULT_RECENT_TRADES_MAXLEN}
          onReset={() =>
            update((d) => (d.recentTradesMaxlen = DEFAULT_RECENT_TRADES_MAXLEN))
          }
        >
          <NumberInput
            aria-label="Recent trades max entries"
            value={draft.recentTradesMaxlen}
            min={1}
            step={1}
            onChange={(v) =>
              update((d) => (d.recentTradesMaxlen = v ?? DEFAULT_RECENT_TRADES_MAXLEN))
            }
          />
          <span className="text-sm text-fg-subtle">trades</span>
        </FieldRow>
      </Section>
    </Panel>
  );
}

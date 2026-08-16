import clsx from "clsx";
import { MAX_INDICES, createIndex } from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import { usePersona } from "@/lib/usePersona";
import { uppercaseId } from "@/lib/format";
import { Panel } from "@/components/layout/Panel";
import { FieldRow } from "@/components/fields/FieldRow";
import { NumberInput, TextInput } from "@/components/fields/inputs";

export function IndicesTab() {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);
  const { canSee } = usePersona();

  return (
    <Panel
      tabId="indices"
      title="Indices"
      intro="Indices publish a weighted level from their constituent symbols. Each constituent must be a configured symbol with outstanding_shares set. Up to 5 indices."
      actions={
        <button
          type="button"
          disabled={draft.indices.length >= MAX_INDICES}
          onClick={() =>
            update((d) => {
              let i = d.indices.length + 1;
              let id = `EDU${i}`;
              while (d.indices.some((x) => x.id === id)) id = `EDU${++i}`;
              d.indices.push(createIndex(id));
            })
          }
          className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50"
        >
          + Add index
        </button>
      }
    >
      {draft.indices.length === 0 && (
        <p className="text-sm text-fg-subtle">No indices defined. Add one to publish a benchmark level.</p>
      )}

      {draft.indices.map((index, i) => (
        <div key={i} className="mt-4 rounded-md border border-border bg-surface p-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-medium">{index.id || "(unnamed index)"}</h3>
            <button
              type="button"
              onClick={() => update((d) => d.indices.splice(i, 1))}
              className="text-sm text-fg-subtle hover:text-error"
            >
              Remove
            </button>
          </div>

          <FieldRow label="Index ID" path={`indices.${index.id}.id`} required>
            <TextInput
              aria-label="Index ID"
              value={index.id}
              onChange={(v) => update((d) => (d.indices[i]!.id = v))}
              onBlur={() => update((d) => (d.indices[i]!.id = uppercaseId(d.indices[i]!.id)))}
              className="w-48"
            />
          </FieldRow>

          <FieldRow label="Description" path={`indices.${index.id}.description`} defaultHint={`Default: Index ${index.id}`}>
            <TextInput
              aria-label="Index description"
              value={index.description ?? ""}
              onChange={(v) => update((d) => (d.indices[i]!.description = v))}
              className="w-full"
            />
          </FieldRow>

          <FieldRow label="Constituents" path={`indices.${index.id}.constituents`} required>
            <div className="flex flex-wrap gap-1.5">
              {draft.symbolOrder.length === 0 && <span className="text-sm text-fg-subtle">Add symbols first.</span>}
              {draft.symbolOrder.map((symbol) => {
                const on = index.constituents.includes(symbol);
                return (
                  <button
                    key={symbol}
                    type="button"
                    onClick={() =>
                      update((d) => {
                        const c = d.indices[i]!.constituents;
                        d.indices[i]!.constituents = on ? c.filter((x) => x !== symbol) : [...c, symbol];
                      })
                    }
                    className={clsx(
                      "rounded-full border px-2.5 py-0.5 text-sm",
                      on ? "border-accent bg-accent text-accent-fg" : "border-border hover:bg-muted",
                    )}
                  >
                    {symbol}
                  </button>
                );
              })}
            </div>
          </FieldRow>

          <div className="flex flex-wrap gap-4">
            <FieldRow label="Base value" path={`indices.${index.id}.baseValue`} defaultHint="Default: 1000">
              <NumberInput
                aria-label="Base value"
                value={index.baseValue}
                min={0}
                step={0.1}
                onChange={(v) => update((d) => (d.indices[i]!.baseValue = v ?? 1000))}
              />
            </FieldRow>
            <FieldRow label="Publish interval (sec)" path={`indices.${index.id}.publishIntervalSec`} defaultHint="Default: 1.0">
              <NumberInput
                aria-label="Publish interval"
                value={index.publishIntervalSec}
                min={0.1}
                step={0.1}
                onChange={(v) => update((d) => (d.indices[i]!.publishIntervalSec = v ?? 1))}
              />
            </FieldRow>
          </div>

          {canSee("E") && (
            <>
              <FieldRow label="History file" path={`indices.${index.id}.historyFile`} defaultHint={`Default: data/indexes/${index.id}_history.jsonl`}>
                <TextInput
                  aria-label="History file"
                  value={index.historyFile ?? ""}
                  onChange={(v) => update((d) => (d.indices[i]!.historyFile = v || undefined))}
                  className="w-full"
                />
              </FieldRow>
              <FieldRow label="State file" path={`indices.${index.id}.stateFile`} defaultHint={`Default: data/indexes/${index.id}_state.json`}>
                <TextInput
                  aria-label="State file"
                  value={index.stateFile ?? ""}
                  onChange={(v) => update((d) => (d.indices[i]!.stateFile = v || undefined))}
                  className="w-full"
                />
              </FieldRow>
            </>
          )}
        </div>
      ))}
    </Panel>
  );
}

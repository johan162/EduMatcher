import { useState } from "react";
import * as RadixDialog from "@radix-ui/react-dialog";
import { useDraftStore } from "@/store/draftStore";
import {
  MAX_KEY_TOKEN_LENGTH,
  MIN_KEY_TOKEN_LENGTH,
  addGeneratedKeys,
  keyCandidates,
  randomApiKey,
} from "@/lib/apiKeys";
import { NumberInput } from "@/components/fields/inputs";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Index of the API instance the keys are added to. */
  index: number;
}

/**
 * Pick participants and give each a generated API key in one instance, like
 * pm-config-gen --api-keys-for. Radix unmounts the content while closed, so
 * the selection starts afresh each time it opens.
 */
export function GenerateApiKeysDialog({ open, onOpenChange, index }: Props) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-black/50" />
        <RadixDialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[min(560px,94vw)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-border bg-surface-raised p-5 shadow-xl">
          <GenerateForm index={index} onDone={() => onOpenChange(false)} />
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

function GenerateForm({ index, onDone }: { index: number; onDone: () => void }) {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);
  const instance = draft.apiGateways[index]!.name;
  const candidates = keyCandidates(draft);
  const eligible = candidates.filter((c) => c.holder === undefined).map((c) => c.id);
  const [selected, setSelected] = useState<Set<string>>(() => new Set(eligible));
  const savedLength = useDraftStore((s) => s.keyTokenLength);
  const setKeyTokenLength = useDraftStore((s) => s.setKeyTokenLength);
  const [tokenLength, setTokenLength] = useState<number | undefined>(savedLength);
  const lengthValid =
    tokenLength !== undefined &&
    Number.isInteger(tokenLength) &&
    tokenLength >= MIN_KEY_TOKEN_LENGTH &&
    tokenLength <= MAX_KEY_TOKEN_LENGTH;

  const toggle = (id: string, on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const generate = () => {
    // Remembered for next time and for the per-row Generate buttons.
    setKeyTokenLength(tokenLength!);
    // In participant order, not click order.
    update((d) =>
      addGeneratedKeys(d, index, eligible.filter((id) => selected.has(id)), (id) => randomApiKey(id, tokenLength)),
    );
    onDone();
  };

  return (
    <>
      <RadixDialog.Title className="text-base font-semibold">Generate API keys for {instance}</RadixDialog.Title>
      <RadixDialog.Description className="mt-1 text-sm text-fg-subtle">
        Each selected participant gets one random key that trades as that participant. A participant
        that already has a key, here or in another instance, is not given another.
      </RadixDialog.Description>

      {candidates.length === 0 ? (
        <p className="mt-4 text-sm text-fg-subtle">No participants are defined (Basics tab).</p>
      ) : (
        <>
          <div className="mt-4 flex gap-2 text-sm">
            <button type="button" onClick={() => setSelected(new Set(eligible))} className="rounded-md border border-border px-2 py-1 hover:bg-muted">
              Select all
            </button>
            <button type="button" onClick={() => setSelected(new Set())} className="rounded-md border border-border px-2 py-1 hover:bg-muted">
              Select none
            </button>
          </div>
          <ul className="mt-2 max-h-80 overflow-y-auto rounded-md border border-border">
            {candidates.map((c) => (
              <li key={c.id} className="border-b border-border px-3 py-1.5 last:border-b-0">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    aria-label={`Generate a key for ${c.id}`}
                    checked={c.holder === undefined && selected.has(c.id)}
                    disabled={c.holder !== undefined}
                    onChange={(e) => toggle(c.id, e.target.checked)}
                    className="accent-accent"
                  />
                  <span className="font-medium">{c.id}</span>
                  <span className="text-xs text-fg-subtle">{c.role}</span>
                  {c.holder !== undefined && (
                    <span className="ml-auto text-xs text-fg-subtle">
                      has a key{c.holder === instance ? "" : ` in ${c.holder}`}
                    </span>
                  )}
                </label>
              </li>
            ))}
          </ul>
        </>
      )}

      <label className="mt-4 flex items-center gap-2 text-sm">
        <span className="font-medium">Key length</span>
        <NumberInput
          aria-label="Key length"
          value={tokenLength}
          min={MIN_KEY_TOKEN_LENGTH}
          max={MAX_KEY_TOKEN_LENGTH}
          onChange={setTokenLength}
          className="w-20"
        />
        <span className="text-xs text-fg-subtle">
          random characters after key-&lt;id&gt;-, {MIN_KEY_TOKEN_LENGTH}–{MAX_KEY_TOKEN_LENGTH}. Short keys are
          easy to type in class; use 24 or more for anything exposed.
        </span>
      </label>

      <div className="mt-5 flex justify-end gap-2">
        <button type="button" onClick={onDone} className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted">
          Cancel
        </button>
        <button
          type="button"
          disabled={selected.size === 0 || !lengthValid}
          onClick={generate}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg disabled:cursor-not-allowed disabled:opacity-50"
        >
          Generate {selected.size} key{selected.size === 1 ? "" : "s"}
        </button>
      </div>
    </>
  );
}

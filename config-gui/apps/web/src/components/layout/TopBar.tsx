import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PERSONAS, type Persona } from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import { importYaml } from "@/api/client";
import { Select } from "@/components/ui/Select";
import { ConfirmDialog } from "@/components/ui/Dialog";

const PERSONA_LABELS: Record<Persona, string> = {
  BEGINNER: "Beginner",
  INTERMEDIATE: "Intermediate",
  EXPERT: "Expert",
};

export function TopBar() {
  const persona = useDraftStore((s) => s.persona);
  const setPersona = useDraftStore((s) => s.setPersona);
  const theme = useDraftStore((s) => s.theme);
  const toggleTheme = useDraftStore((s) => s.toggleTheme);
  const replaceDraft = useDraftStore((s) => s.replaceDraft);
  const newDraft = useDraftStore((s) => s.newDraft);

  const fileRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const [toast, setToast] = useState<string | null>(null);
  const [confirmNew, setConfirmNew] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);

  const showToast = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(null), 2500);
  };

  const onImportFile = async (file: File) => {
    setImportError(null);
    try {
      const text = await file.text();
      const { draft, unmapped } = await importYaml(text);
      replaceDraft(draft, unmapped);
      navigate("/review");
      showToast(
        unmapped.length > 0
          ? `Imported. ${unmapped.length} unmapped section(s) preserved.`
          : "Imported successfully.",
      );
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "Import failed.");
    }
  };

  return (
    <header className="flex h-14 items-center justify-between gap-4 border-b border-border bg-surface px-4">
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold">EduMatcher Config Builder</span>
      </div>

      <div className="flex items-center gap-2">
        <label className="sr-only" htmlFor="persona-select">
          Experience level
        </label>
        <Select
          id="persona-select"
          aria-label="Experience level"
          value={persona}
          onValueChange={(v) => setPersona(v as Persona)}
          options={PERSONAS.map((p) => ({ value: p, label: PERSONA_LABELS[p] }))}
        />

        <input
          ref={fileRef}
          type="file"
          accept=".yaml,.yml"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void onImportFile(file);
            e.target.value = "";
          }}
        />
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
        >
          Import
        </button>
        <button
          type="button"
          onClick={() => setConfirmNew(true)}
          className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
        >
          New
        </button>
        <button
          type="button"
          onClick={toggleTheme}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
        >
          {theme === "dark" ? "☀" : "☾"}
        </button>
        <button
          type="button"
          onClick={() => showToast("Draft saved to this browser.")}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg"
        >
          Save
        </button>
      </div>

      {toast && (
        <div className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-md bg-fg px-4 py-2 text-sm text-bg shadow-lg">
          {toast}
        </div>
      )}

      <ConfirmDialog
        open={confirmNew}
        onOpenChange={setConfirmNew}
        title="Start a new draft?"
        description="This discards the current draft (a copy remains autosaved in this browser until you edit the new one). Continue?"
        confirmLabel="New draft"
        onConfirm={() => {
          newDraft();
          navigate("/basics");
          showToast("Started a new draft.");
        }}
      />

      <ConfirmDialog
        open={importError !== null}
        onOpenChange={(o) => !o && setImportError(null)}
        title="Import failed"
        description={importError}
        confirmLabel="OK"
        cancelLabel="Close"
        onConfirm={() => setImportError(null)}
      />
    </header>
  );
}

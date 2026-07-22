import { useMemo, useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { yaml as yamlLang } from "@codemirror/lang-yaml";
import { githubLight, githubDark } from "@uiw/codemirror-theme-github";
import { generateYaml } from "@edumatcher/yaml-codec";
import { useDraftStore } from "@/store/draftStore";
import { verify as verifyApi } from "@/api/client";
import { Panel, Section } from "@/components/layout/Panel";
import { FieldRow } from "@/components/fields/FieldRow";
import { TextInput } from "@/components/fields/inputs";
import { Switch } from "@/components/ui/Switch";
import { tabById } from "@/lib/tabs";

export function ReviewTab() {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);
  const diagnostics = useDraftStore((s) => s.diagnostics);
  const theme = useDraftStore((s) => s.theme);
  const warningsAcknowledged = useDraftStore((s) => s.warningsAcknowledged);
  const acknowledgeWarnings = useDraftStore((s) => s.acknowledgeWarnings);

  const [verifyState, setVerifyState] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const yamlText = useMemo(() => generateYaml(draft), [draft]);

  const errors = diagnostics.filter((d) => d.severity === "error");
  const warnings = diagnostics.filter((d) => d.severity === "warning");
  const canDownload = errors.length === 0 && (warnings.length === 0 || warningsAcknowledged);

  const grouped = useMemo(() => {
    const map = new Map<string, typeof diagnostics>();
    for (const d of diagnostics) {
      const list = map.get(d.tab) ?? [];
      list.push(d);
      map.set(d.tab, list);
    }
    return [...map.entries()];
  }, [diagnostics]);

  const download = () => {
    const blob = new Blob([yamlText], { type: "text/yaml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = draft.output.filename || "engine_config.yaml";
    a.click();
    URL.revokeObjectURL(url);
  };

  const runVerify = async () => {
    setVerifyState("Running pm-cverifier…");
    const result = await verifyApi(yamlText);
    if (!result.ok) {
      setVerifyState(result.message);
      return;
    }
    const { exitCode } = result.result;
    setVerifyState(
      exitCode === 0
        ? "pm-cverifier: no issues found."
        : `pm-cverifier reported issues (exit ${exitCode}). See server-side report.`,
    );
  };

  return (
    <Panel
      tabId="review"
      title="Review & Export"
      intro="A final read-only pass. The YAML preview below is exactly what will be downloaded. Download is blocked while any error exists."
    >
      <Section title="Diagnostics summary">
        {diagnostics.length === 0 ? (
          <p className="text-sm text-success">✓ No issues. Configuration is valid.</p>
        ) : (
          grouped.map(([tab, list]) => (
            <div key={tab} className="mb-2">
              <h3 className="text-xs font-semibold uppercase text-fg-subtle">{tabById(tab)?.label ?? tab}</h3>
              <ul className="mt-1 space-y-1">
                {list.map((d, i) => (
                  <li
                    key={i}
                    className={
                      d.severity === "error"
                        ? "text-sm text-error"
                        : d.severity === "warning"
                          ? "text-sm text-warning"
                          : "text-sm text-fg-subtle"
                    }
                  >
                    {d.severity === "error" ? "✗" : d.severity === "warning" ? "!" : "i"} {d.message}
                  </li>
                ))}
              </ul>
            </div>
          ))
        )}
      </Section>

      <Section title="Output options">
        <FieldRow label="Download filename" path="output.filename">
          <TextInput
            aria-label="Download filename"
            value={draft.output.filename}
            onChange={(v) => update((d) => (d.output.filename = v))}
            className="w-72"
          />
        </FieldRow>
        <FieldRow
          label="Comment default fields"
          help={{ text: "Include the full commented reference block of all recognized fields and defaults.", cliFlag: "--comment-default-config-fields" }}
        >
          <Switch
            aria-label="Comment default fields"
            checked={draft.output.commentDefaultFields}
            onCheckedChange={(v) => update((d) => (d.output.commentDefaultFields = v))}
          />
        </FieldRow>
      </Section>

      <Section title="YAML preview" description="Comments in an imported file are not preserved on export; the GUI is a structural editor.">
        <div className="overflow-hidden rounded-md border border-border">
          <CodeMirror
            value={yamlText}
            height="380px"
            readOnly
            theme={theme === "dark" ? githubDark : githubLight}
            extensions={[yamlLang()]}
          />
        </div>
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard.writeText(yamlText);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          }}
          className="mt-2 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
        >
          {copied ? "Copied ✓" : "Copy to clipboard"}
        </button>
      </Section>

      <Section title="Export">
        {errors.length > 0 && (
          <p className="text-sm text-error">
            Resolve {errors.length} error{errors.length > 1 ? "s" : ""} before downloading.
          </p>
        )}
        {errors.length === 0 && warnings.length > 0 && !warningsAcknowledged && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" onChange={(e) => e.target.checked && acknowledgeWarnings()} />
            I understand {warnings.length} warning{warnings.length > 1 ? "s" : ""} will be included.
          </label>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={!canDownload}
            onClick={download}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-40"
          >
            Download {draft.output.filename}
          </button>
          <button
            type="button"
            onClick={() => void runVerify()}
            className="rounded-md border border-border px-4 py-2 text-sm hover:bg-muted"
          >
            Verify with pm-cverifier
          </button>
          {verifyState && <span className="text-sm text-fg-subtle">{verifyState}</span>}
        </div>
      </Section>
    </Panel>
  );
}

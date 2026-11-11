/**
 * Filter forms. A filter applies when the form is submitted (Apply / Enter),
 * not on every keystroke, so typing a symbol does not send a request per
 * letter. Each control has a visible label.
 */
import { useId, useState, type FormEvent, type ReactNode } from "react";

export type FilterValues = Record<string, string>;

export interface FilterField {
  name: string;
  label: string;
  type?: "text" | "date" | "select" | "checkbox";
  /** For `select`: value/label pairs; the first is the default. */
  options?: { value: string; label: string }[];
  placeholder?: string;
  required?: boolean;
}

interface FilterFormProps {
  /** Names the form landmark; must differ when a screen has two forms. */
  label?: string;
  fields: FilterField[];
  initial?: FilterValues;
  submitLabel?: string;
  onApply: (values: FilterValues) => void;
  children?: ReactNode;
}

export function FilterForm({
  label = "Filters",
  fields,
  initial = {},
  submitLabel = "Apply",
  onApply,
  children,
}: FilterFormProps) {
  const [values, setValues] = useState<FilterValues>(initial);
  const id = useId();

  function submit(e: FormEvent) {
    e.preventDefault();
    onApply(values);
  }

  const set = (name: string, value: string) => setValues((v) => ({ ...v, [name]: value }));

  return (
    <form onSubmit={submit} className="mb-3 flex flex-wrap items-end gap-3" aria-label={label}>
      {fields.map((f) => {
        const inputId = `${id}-${f.name}`;
        const value = values[f.name] ?? "";
        if (f.type === "checkbox") {
          return (
            <label key={f.name} htmlFor={inputId} className="flex items-center gap-1.5 text-xs text-fg-dim">
              <input
                id={inputId}
                type="checkbox"
                checked={value === "true"}
                onChange={(e) => set(f.name, e.target.checked ? "true" : "")}
              />
              {f.label}
            </label>
          );
        }
        return (
          <div key={f.name} className="flex flex-col gap-1">
            <label htmlFor={inputId} className="text-[11px] text-fg-dim">
              {f.label}
            </label>
            {f.type === "select" ? (
              <select
                id={inputId}
                value={value}
                onChange={(e) => set(f.name, e.target.value)}
                className="rounded border border-line bg-raised px-2 py-1 text-xs"
              >
                {(f.options ?? []).map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            ) : (
              <input
                id={inputId}
                type={f.type ?? "text"}
                value={value}
                required={f.required}
                placeholder={f.placeholder}
                onChange={(e) => set(f.name, e.target.value)}
                className="w-40 rounded border border-line bg-raised px-2 py-1 text-xs"
              />
            )}
          </div>
        );
      })}
      <button type="submit" className="rounded bg-accent px-3 py-1 text-xs font-semibold text-accent-fg hover:brightness-110">
        {submitLabel}
      </button>
      {children}
    </form>
  );
}

/** Upper-cased trimmed text, or undefined when blank (no filter). */
export function filterText(value: string | undefined): string | undefined {
  const trimmed = (value ?? "").trim().toUpperCase();
  return trimmed === "" ? undefined : trimmed;
}

/** A date input's value, or undefined when blank. */
export function filterDate(value: string | undefined): string | undefined {
  return value ? value : undefined;
}

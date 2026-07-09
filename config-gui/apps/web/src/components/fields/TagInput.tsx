import { useState } from "react";
import clsx from "clsx";

interface Props {
  values: string[];
  onAdd: (value: string) => void;
  onRemove: (value: string) => void;
  placeholder?: string;
  /** Transform each entry on commit (e.g. uppercase). */
  transform?: (value: string) => string;
  "aria-label"?: string;
}

export function TagInput({ values, onAdd, onRemove, placeholder, transform, ...rest }: Props) {
  const [text, setText] = useState("");

  const commit = () => {
    const parts = text
      .split(/[\s,]+/)
      .map((p) => (transform ? transform(p) : p.trim()))
      .filter(Boolean);
    for (const part of parts) {
      if (!values.includes(part)) onAdd(part);
    }
    setText("");
  };

  return (
    <div className="flex w-full flex-wrap items-center gap-1.5 rounded-md border border-border bg-surface p-1.5">
      {values.map((value) => (
        <span
          key={value}
          className="inline-flex items-center gap-1 rounded bg-muted px-2 py-0.5 text-sm"
        >
          {value}
          <button
            type="button"
            aria-label={`Remove ${value}`}
            onClick={() => onRemove(value)}
            className="text-fg-subtle hover:text-error"
          >
            ×
          </button>
        </span>
      ))}
      <input
        aria-label={rest["aria-label"]}
        value={text}
        placeholder={values.length === 0 ? placeholder : ""}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            commit();
          } else if (e.key === "Backspace" && text === "" && values.length > 0) {
            onRemove(values[values.length - 1]!);
          }
        }}
        onBlur={commit}
        className={clsx(
          "min-w-[8rem] flex-1 bg-transparent px-1 py-0.5 text-sm outline-none placeholder:text-optional-default",
        )}
      />
    </div>
  );
}

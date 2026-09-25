import { useId, useState } from "react";
import { Info } from "lucide-react";

interface FieldInfoProps {
  /** Field name (also used in the accessible label). */
  label: string;
  /** Lines of help text: requirement, valid range, example, live constraint. */
  lines: string[];
}

/**
 * A field help tooltip (§19.3): an info icon that reveals field help on hover
 * or keyboard focus. Dependency-free and accessible — the trigger is a real
 * button labelled "{field} help", and the tooltip is a `role="tooltip"` element
 * linked by `aria-describedby` while shown.
 */
export function FieldInfo({ label, lines }: FieldInfoProps) {
  const [open, setOpen] = useState(false);
  const id = useId();

  return (
    <span className="relative inline-flex align-middle">
      <button
        type="button"
        aria-label={`${label} help`}
        aria-describedby={open ? id : undefined}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className="text-fg-faint hover:text-fg-dim focus:text-fg-dim focus:outline-none"
      >
        <Info size={12} />
      </button>
      {open && (
        <span
          role="tooltip"
          id={id}
          className="absolute left-4 top-0 z-50 w-56 rounded border border-line bg-panel p-2 text-[10px] leading-snug text-fg-soft shadow-xl"
        >
          <span className="mb-0.5 block font-semibold text-fg">{label}</span>
          {lines.map((l, i) => (
            <span key={i} className="block">
              {l}
            </span>
          ))}
        </span>
      )}
    </span>
  );
}

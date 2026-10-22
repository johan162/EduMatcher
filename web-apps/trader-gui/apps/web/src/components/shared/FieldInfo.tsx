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
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const id = useId();
  const open = pos !== null;

  // `fixed` from the trigger's rectangle: a table or panel that scrolls
  // would clip an absolutely positioned tip.
  const show = (el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    setPos({ x: Math.max(8, Math.min(r.right + 4, window.innerWidth - 232)), y: r.top });
  };

  return (
    <span className="relative inline-flex align-middle">
      <button
        type="button"
        aria-label={`${label} help`}
        aria-describedby={open ? id : undefined}
        onMouseEnter={(e) => show(e.currentTarget)}
        onMouseLeave={() => setPos(null)}
        onFocus={(e) => show(e.currentTarget)}
        onBlur={() => setPos(null)}
        className="text-fg-faint hover:text-fg-dim focus:text-fg-dim focus:outline-none"
      >
        <Info size={12} />
      </button>
      {pos && (
        <span
          role="tooltip"
          id={id}
          style={{ left: pos.x, top: pos.y }}
          className="fixed z-50 w-56 rounded border border-line bg-panel p-2 text-[10px] leading-snug text-fg-soft shadow-xl"
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

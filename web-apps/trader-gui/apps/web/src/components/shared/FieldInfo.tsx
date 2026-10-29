import { useId, useState } from "react";
import { Info } from "lucide-react";

/** The tooltip's width in CSS pixels (`w-56`). */
const TIP_WIDTH = 224;

interface FieldInfoProps {
  /** Field name (also used in the accessible label). */
  label: string;
  /** Lines of help text: requirement, valid range, example, live constraint. */
  lines: string[];
  /** Open under the icon instead of to its right, so the tip never covers the icon (table headings). */
  below?: boolean;
}

/**
 * A field help tooltip (§19.3): an info icon that reveals field help on hover
 * or keyboard focus. Dependency-free and accessible — the trigger is a real
 * button labelled "{field} help", and the tooltip is a `role="tooltip"` element
 * linked by `aria-describedby` while shown.
 */
export function FieldInfo({ label, lines, below = false }: FieldInfoProps) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const id = useId();
  const open = pos !== null;

  // `fixed` from the trigger's rectangle: a table or panel that scrolls
  // would clip an absolutely positioned tip. `#root` is scaled with CSS
  // `zoom`, and a `fixed` box inside it is placed in zoomed units, while the
  // rectangle and the window are in screen pixels.
  const show = (el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    const zoom = el.offsetWidth > 0 ? r.width / el.offsetWidth : 1;
    const x = Math.min((below ? r.left : r.right + 4) / zoom, window.innerWidth / zoom - TIP_WIDTH - 8);
    setPos({ x: Math.max(8, x), y: below ? r.bottom / zoom + 4 : r.top / zoom });
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
          className="fixed z-50 w-56 whitespace-normal rounded border border-line bg-panel p-2 text-left text-[10px] font-normal normal-case leading-snug tracking-normal text-fg-soft shadow-xl"
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

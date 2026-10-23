import { useId, useState } from "react";
import { Info } from "lucide-react";

/** The tooltip's width in CSS pixels (`w-72`). */
const TIP_WIDTH = 288;

/**
 * An "i" that explains a field, column or tile (WP-UI02) on hover or keyboard
 * focus. `fixed` from the trigger's rectangle, so neither a table that
 * scrolls sideways nor a truncated tile clips it.
 */
export function InfoTip({ label, help }: { label: string; help: string }) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const id = useId();

  // `#root` is scaled with CSS `zoom`, and a `fixed` box inside it is placed in
  // zoomed units, while the rectangle and the window are in screen pixels.
  const show = (el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    const zoom = el.offsetWidth > 0 ? r.width / el.offsetWidth : 1;
    const x = Math.min(r.left / zoom, window.innerWidth / zoom - TIP_WIDTH - 8);
    setPos({ x: Math.max(8, x), y: r.bottom / zoom + 4 });
  };

  return (
    <span className="inline-flex shrink-0 align-middle normal-case tracking-normal">
      <button
        type="button"
        aria-label={`${label} help`}
        aria-describedby={pos ? id : undefined}
        onMouseEnter={(e) => show(e.currentTarget)}
        onMouseLeave={() => setPos(null)}
        onFocus={(e) => show(e.currentTarget)}
        onBlur={() => setPos(null)}
        onClick={(e) => e.stopPropagation()}
        className="text-fg-faint hover:text-fg focus:text-fg focus:outline-none"
      >
        <Info size={12} aria-hidden="true" />
      </button>
      {pos && (
        <span
          role="tooltip"
          id={id}
          style={{ left: pos.x, top: pos.y }}
          className="fixed z-50 w-72 whitespace-normal rounded border border-border-strong bg-bg-raised p-2 text-left text-xs font-normal leading-snug text-fg shadow-xl"
        >
          <span className="mb-0.5 block font-semibold">{label}</span>
          {help}
        </span>
      )}
    </span>
  );
}

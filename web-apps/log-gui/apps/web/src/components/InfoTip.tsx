import { useId, useState } from "react";
import { Info } from "lucide-react";

/** The tooltip's width in CSS pixels (`w-72`). */
const TIP_WIDTH = 288;

/**
 * A help tooltip (WP-UI02): an "i" that explains a field or column on hover
 * or keyboard focus. Positioned `fixed` from the trigger's rectangle so a
 * scrolling table or panel cannot clip it.
 */
export function InfoTip({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
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
    <span className="inline-flex align-middle normal-case tracking-normal">
      <button
        type="button"
        aria-label={`${label} help`}
        aria-describedby={pos ? id : undefined}
        onMouseEnter={(e) => show(e.currentTarget)}
        onMouseLeave={() => setPos(null)}
        onFocus={(e) => show(e.currentTarget)}
        onBlur={() => setPos(null)}
        className="text-fg-subtle hover:text-fg focus:text-fg focus:outline-none"
      >
        <Info size={12} />
      </button>
      {pos && (
        <span
          role="tooltip"
          id={id}
          style={{ left: pos.x, top: pos.y }}
          className="fixed z-50 w-72 rounded border border-border bg-bg-subtle p-2 text-xs font-normal leading-snug text-fg shadow-xl"
        >
          <span className="mb-0.5 block font-semibold">{label}</span>
          {children}
        </span>
      )}
    </span>
  );
}

import { useId, useState } from "react";
import { Info } from "lucide-react";

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

  const show = (el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    setPos({ x: Math.min(r.left, window.innerWidth - 300), y: r.bottom + 4 });
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

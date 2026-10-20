/**
 * A chart's or gauge's visible title (design §12.3: every panel is named).
 * The panel already names itself to assistive technology by its
 * aria-label, so the title is hidden from it rather than read twice.
 */

export function PanelTitle({ children }: { children: string }) {
  return (
    <div aria-hidden="true" title={children} className="mb-1 truncate text-[11px] font-semibold uppercase tracking-wide text-fg-subtle">
      {children}
    </div>
  );
}

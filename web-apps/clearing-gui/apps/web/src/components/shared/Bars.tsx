/**
 * Plain bar pictures for the teaching panels (CG27). Each picture is
 * `aria-hidden`: its numbers are in a table beside it (D12), which is what a
 * screen reader reads. Bars are drawn only for non-zero values, scaled to
 * the largest value in the picture.
 */

function share(value: number, max: number): string {
  return `${max > 0 ? (Math.abs(value) / max) * 100 : 0}%`;
}

export interface DivergingRow {
  key: string;
  label: string;
  /** Drawn leftwards from the centre line; a magnitude. */
  left: number;
  /** Drawn rightwards from the centre line; a magnitude. */
  right: number;
}

/** One row per item, a left and a right bar from a shared centre line. */
export function DivergingBars({
  rows,
  leftLabel,
  rightLabel,
  leftTone = "bg-ask/70",
  rightTone = "bg-bid/70",
}: {
  rows: DivergingRow[];
  leftLabel: string;
  rightLabel: string;
  leftTone?: string;
  rightTone?: string;
}) {
  const max = Math.max(0, ...rows.flatMap((r) => [Math.abs(r.left), Math.abs(r.right)]));
  return (
    <div aria-hidden="true" className="my-2 flex max-w-2xl flex-col gap-1 text-[11px]">
      <div className="grid grid-cols-[8rem_1fr_1fr] text-fg-dim">
        <span />
        <span className="pr-1 text-right">{leftLabel}</span>
        <span className="pl-1">{rightLabel}</span>
      </div>
      {rows.map((r) => (
        <div key={r.key} className="grid grid-cols-[8rem_1fr_1fr] items-center">
          <span className="truncate font-mono">{r.label}</span>
          <div className="flex h-3 justify-end border-r border-fg-dim">
            {r.left !== 0 && <div data-bar="left" className={leftTone} style={{ width: share(r.left, max) }} />}
          </div>
          <div className="flex h-3">
            {r.right !== 0 && <div data-bar="right" className={rightTone} style={{ width: share(r.right, max) }} />}
          </div>
        </div>
      ))}
    </div>
  );
}

/** One bar per labelled value, all from the same left edge. */
export function ValueBars({ rows }: { rows: { key: string; label: string; value: number; tone: string }[] }) {
  const max = Math.max(0, ...rows.map((r) => Math.abs(r.value)));
  return (
    <div aria-hidden="true" className="my-2 flex max-w-2xl flex-col gap-1 text-[11px]">
      {rows.map((r) => (
        <div key={r.key} className="grid grid-cols-[10rem_1fr] items-center">
          <span className="text-fg-dim">{r.label}</span>
          <div className="flex h-3">
            {r.value !== 0 && <div data-bar="value" className={r.tone} style={{ width: share(r.value, max) }} />}
          </div>
        </div>
      ))}
    </div>
  );
}

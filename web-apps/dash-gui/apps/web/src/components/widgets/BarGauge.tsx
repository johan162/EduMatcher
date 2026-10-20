/**
 * Horizontal bars, largest first (design §13): memory per process, data
 * files. Beyond `limit` items the rest are one "other" bar, so the bars
 * still add up to the whole. A bar over a threshold takes its level's
 * colour, and says so with a glyph too.
 *
 * The label column fits its labels up to a third of the width and cuts longer
 * ones with an ellipsis (full text on hover), so one long name cannot squeeze
 * every bar. A value that is not a finite number shows "—" with no bar;
 * a negative value draws no bar.
 */

import { LEVEL } from "../../lib/status.js";
import { NO_VALUE } from "../../lib/format.js";
import { describeThresholds, levelOf, type Thresholds } from "../../lib/thresholds.js";
import { OTHER, topN } from "../../lib/topn.js";

export interface BarItem {
  label: string;
  value: number;
}

export interface BarGaugeProps {
  label: string;
  items: readonly BarItem[];
  format: (v: number) => string;
  /** The full-scale value; the largest item's by default. */
  max?: number;
  thresholds?: Thresholds;
  /** Bars before the rest become "other". */
  limit?: number;
}

/** A bar's length in percent of `scale`, 0..100. */
export function barPercent(value: number, scale: number): number {
  if (!Number.isFinite(value) || !(scale > 0)) return 0;
  return Math.min(100, Math.max(0, (value / scale) * 100));
}

export function BarGauge({ label, items, format, max, thresholds, limit = 10 }: BarGaugeProps) {
  const finite = items.filter((i) => Number.isFinite(i.value));
  const rows = [...topN(finite, limit, (value, count) => ({ label: `${OTHER} (${count})`, value })), ...items.filter((i) => !Number.isFinite(i.value))];
  const scale = max ?? rows.reduce((m, r) => (Number.isFinite(r.value) ? Math.max(m, r.value) : m), 0);

  return (
    <section aria-label={label} data-widget="bar-gauge" title={thresholds ? describeThresholds(thresholds, format) : undefined} className="min-w-0">
      {rows.length === 0 ? (
        <p className="text-xs text-fg-faint">No data</p>
      ) : (
        <ul className="m-0 grid list-none grid-cols-[fit-content(33%)_minmax(3rem,1fr)_max-content] items-center gap-x-3 gap-y-1 p-0 text-xs">
          {rows.map((row, i) => {
            const level = thresholds ? levelOf(row.value, thresholds) : null;
            const look = level ? LEVEL[level] : null;
            const alarm = look !== null && level !== "OK";
            return (
              <li key={`${i}-${row.label}`} className="contents" data-label={row.label} data-level={level ?? "NONE"}>
                <span className="truncate text-fg-subtle" title={row.label}>
                  {row.label}
                </span>
                <span className="h-2.5 min-w-0 rounded-sm bg-bg-inset">
                  <span
                    className="block h-full rounded-sm"
                    style={{ width: `${barPercent(row.value, scale).toFixed(1)}%`, background: look ? look.color : "var(--series-1)" }}
                  />
                </span>
                <span className={`whitespace-nowrap text-right tabular ${alarm ? look.text : "text-fg"}`}>
                  {Number.isFinite(row.value) ? format(row.value) : NO_VALUE}
                  {alarm && ` ${look.glyph}`}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

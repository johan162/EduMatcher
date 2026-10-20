/**
 * Horizontal bars, largest first (design §13): memory per process, data
 * files. Beyond `limit` items the rest are one "other" bar, so the bars
 * still add up to the whole. A bar over a threshold takes its level's
 * colour, and says so in text too.
 */

import { LEVEL } from "../../lib/status.js";
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

export function BarGauge({ label, items, format, max, thresholds, limit = 10 }: BarGaugeProps) {
  const rows = topN(items, limit, (value, count) => ({ label: `${OTHER} (${count})`, value }));
  const scale = max ?? Math.max(0, ...rows.map((r) => r.value));

  return (
    <section aria-label={label} title={thresholds ? describeThresholds(thresholds, format) : undefined}>
      <ul className="grid grid-cols-[minmax(6rem,max-content)_1fr_max-content] items-center gap-x-3 gap-y-1 text-xs">
        {rows.map((row) => {
          const level = thresholds ? levelOf(row.value, thresholds) : "OK";
          const look = LEVEL[level];
          const pct = scale > 0 ? Math.min(100, (row.value / scale) * 100) : 0;
          return (
            <li key={row.label} className="contents" data-label={row.label} data-level={level}>
              <span className="truncate text-fg-subtle">{row.label}</span>
              <span className="h-2.5 rounded-sm bg-bg-inset">
                <span
                  className="block h-full rounded-sm"
                  style={{ width: `${pct.toFixed(1)}%`, background: thresholds ? look.color : "var(--series-1)" }}
                />
              </span>
              <span className={`tabular ${level === "OK" ? "text-fg" : look.text}`}>
                {format(row.value)}
                {level !== "OK" && ` ${look.glyph}`}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

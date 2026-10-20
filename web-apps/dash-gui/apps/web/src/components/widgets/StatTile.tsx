/**
 * A single figure with its context (design §13, row 1): label, value and
 * unit, an optional sparkline and sub-text, coloured by its threshold level
 * in one of Grafana's two stat modes -- the value's colour, or the tile's
 * background (the settings choice, D1.5). The level is also in words and a
 * glyph beside the value, and hovering names the thresholds.
 *
 * Background mode writes the text in `--bg` on the status colour: every
 * status token is >= 4.5:1 against `--bg` (contrast.test.ts), so the same
 * pair is readable the other way round.
 */

import clsx from "clsx";
import { Sparkline } from "./Sparkline.js";
import { LEVEL } from "../../lib/status.js";
import { describeThresholds, levelOf, type Thresholds } from "../../lib/thresholds.js";
import { usePrefsStore, type StatColorMode } from "../../store/usePrefsStore.js";

export interface StatTileProps {
  label: string;
  /** null: no figure yet. */
  value: number | null;
  format: (v: number) => string;
  spark?: readonly number[];
  sub?: string;
  thresholds?: Thresholds;
  /** The settings choice unless given. */
  colorMode?: StatColorMode;
}

export function StatTile({ label, value, format, spark, sub, thresholds, colorMode }: StatTileProps) {
  const preferred = usePrefsStore((s) => s.statColorMode);
  const mode = colorMode ?? preferred;
  const level = value !== null && thresholds ? levelOf(value, thresholds) : null;
  const look = level ? LEVEL[level] : null;
  const filled = mode === "background" && look !== null;

  return (
    <section
      aria-label={label}
      data-level={level ?? "NONE"}
      title={thresholds ? describeThresholds(thresholds, format) : undefined}
      className={clsx(
        "flex min-w-0 flex-col gap-1 rounded border px-3 py-2",
        filled ? [look.bg, look.border, "text-bg"] : "border-border bg-bg-subtle",
      )}
    >
      <h3 className={clsx("truncate text-[11px] font-semibold uppercase tracking-wide", filled ? "text-bg" : "text-fg-subtle")}>
        {label}
      </h3>
      <div className="flex items-baseline gap-2">
        <span
          data-testid="stat-value"
          className={clsx("tabular text-2xl font-semibold", filled ? "text-bg" : look ? look.text : value === null ? "text-stopped" : "text-fg")}
        >
          {value === null ? "—" : format(value)}
        </span>
        {look && level !== "OK" && (
          <span className={clsx("text-xs font-semibold", filled ? "text-bg" : look.text)}>
            {look.glyph} {look.label}
          </span>
        )}
      </div>
      {(spark || sub) && (
        <div className={clsx("flex items-center justify-between gap-2 text-xs", filled ? "text-bg" : "text-fg-subtle")}>
          <span className="truncate tabular">{sub}</span>
          {spark && spark.length > 1 && <Sparkline values={spark} />}
        </div>
      )}
    </section>
  );
}

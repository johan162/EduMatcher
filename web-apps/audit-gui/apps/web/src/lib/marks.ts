/**
 * The visual vocabulary of the Market canvas (design §9.4, §9.10), with a
 * text equivalent for every mark: a lifeline's end is a glyph on the chart
 * and the same glyph plus words in the marks list and the legend. Sides
 * differ in hue *and* shape, never by red/green alone.
 */
import type { LifelineT } from "@/api/schemas";

export type EndKind = LifelineT["end"];

export const END_MARKS: Record<EndKind, { glyph: string; text: string }> = {
  filled: { glyph: "●", text: "filled" },
  "cancel.owner": { glyph: "×", text: "owner cancel" },
  "cancel.system": { glyph: "⊗", text: "system cancel" },
  expired: { glyph: "◌", text: "expired" },
  open: { glyph: "▸", text: "still resting" },
  censored: { glyph: "…", text: "cut by the window" },
};

/** "system cancel: QUOTE_REPLACED", "owner cancel", ... */
export function endText(lifeline: Pick<LifelineT, "end" | "end_reason">): string {
  const base = END_MARKS[lifeline.end].text;
  return lifeline.end_reason ? `${base}: ${lifeline.end_reason}` : base;
}

/** Bid and ask hues (index.css tokens), shared by the heatmap and lifelines. */
export const SIDE_COLOR = { BUY: "rgb(56 132 255)", SELL: "rgb(245 158 11)" } as const;

export const MASK_LABEL = { gap: "Records lost (gap)", halt: "Halt" } as const;

/** What a mask means for the cells under it. */
export const MASK_EFFECT = {
  gap: "no observation is valid here, nothing is interpolated",
  halt: "the book observed while halted is kept",
} as const;

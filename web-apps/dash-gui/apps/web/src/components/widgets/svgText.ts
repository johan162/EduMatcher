/**
 * SVG text cannot wrap or truncate itself, so widgets size or cut it to fit
 * their geometry. Widths are estimated, not measured (jsdom has no layout):
 * an average glyph is about 0.6 em, a little generous for the proportional
 * UI font and exact for the tabular/mono digits most of these texts are.
 */

export const EM_PER_CHAR = 0.6;

/** The largest font size up to `max` at which `text` fits in `width`. */
export function fitFontSize(text: string, width: number, max: number, min = 6): number {
  const needed = text.length * EM_PER_CHAR;
  return Math.max(min, Math.min(max, needed > 0 ? width / needed : max));
}

/** `text` cut with an ellipsis so it fits in `width` at `fontSize`. */
export function clipText(text: string, width: number, fontSize: number): string {
  const room = Math.floor(width / (fontSize * EM_PER_CHAR));
  if (text.length <= room) return text;
  return room <= 1 ? "…" : `${text.slice(0, room - 1)}…`;
}

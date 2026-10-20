/**
 * Every status token is text, so >= 4.5:1 against `--bg` and `--bg-subtle`;
 * every series token is a line or an area, so >= 3:1 (WCAG 1.4.11) -- in
 * both themes (design §12.5, D1.1). Read from index.css itself, so a retuned
 * value is checked where it is written.
 */

import { describe, expect, it } from "vitest";

const CSS = Object.values(
  import.meta.glob("../src/index.css", { eager: true, query: "?raw", import: "default" }) as Record<string, string>,
)[0] as string;

function block(selector: string): Record<string, string> {
  const start = CSS.indexOf(`${selector} {`);
  expect(start, `no ${selector} block in index.css`).toBeGreaterThanOrEqual(0);
  const body = CSS.slice(start, CSS.indexOf("}", start));
  return Object.fromEntries([...body.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-f]{6});/gi)].map((m) => [m[1]!, m[2]!]));
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
}

const THEMES = { dark: block(":root,\nhtml.dark"), light: block("html:not(.dark)") };
const STATUS = ["ok", "warn", "crit", "hung", "missing", "stopped", "info"];
const SERIES = Array.from({ length: 8 }, (_, i) => `series-${i + 1}`);

describe.each(Object.entries(THEMES))("%s theme", (_name, tokens) => {
  it("declares every status and series token", () => {
    for (const t of [...STATUS, ...SERIES, "bg", "bg-subtle"]) expect(tokens[t], t).toMatch(/^#/);
  });

  it.each(STATUS)("--%s is readable as text (>= 4.5:1)", (token) => {
    for (const bg of ["bg", "bg-subtle"]) {
      expect(contrast(tokens[token]!, tokens[bg]!), `--${token} on --${bg}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it.each(SERIES)("--%s stands out as a line (>= 3:1)", (token) => {
    for (const bg of ["bg", "bg-subtle"]) {
      expect(contrast(tokens[token]!, tokens[bg]!), `--${token} on --${bg}`).toBeGreaterThanOrEqual(3);
    }
  });
});

describe("the measure itself", () => {
  it("matches WCAG's reference values", () => {
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrast("#777777", "#ffffff")).toBeCloseTo(4.48, 2);
  });
});

describe("no price tokens (design §12.5: this app shows no prices)", () => {
  it.each(["--up", "--down", "--flash-up", "--halt", "--auction"])("%s is gone", (token) => {
    expect(CSS).not.toMatch(new RegExp(`${token}[-:]`));
  });
});

/**
 * Guards against colour classes that compile to nothing.
 *
 * This failure mode has been found twice by human review and never once by a
 * machine, which is the argument for the file: an undeclared colour token
 * produces no CSS and no error, so the element renders unstyled and looks
 * like a design choice. `bg-surface` sat undeclared in three places (T-L2),
 * and seventeen `token/opacity` classes compiled to nothing for the subtler
 * reason described below.
 *
 * Sources are read through `import.meta.glob` rather than `node:fs`: this is
 * a browser app whose tsconfig carries no Node types, and a test is not a
 * reason to add them.
 */

import { describe, expect, it } from "vitest";

const SOURCES = Object.entries(
  import.meta.glob("../src/**/*.{ts,tsx}", { eager: true, query: "?raw", import: "default" }) as Record<
    string,
    string
  >,
);

const CONFIG = Object.values(
  import.meta.glob("../tailwind.config.ts", { eager: true, query: "?raw", import: "default" }) as Record<
    string,
    string
  >,
)[0] as string;

/** Tailwind's own palette, which needs no declaration of ours. */
const BUILT_IN = new Set([
  "inherit",
  "current",
  "transparent",
  "black",
  "white",
  "slate",
  "gray",
  "zinc",
  "neutral",
  "stone",
  "red",
  "orange",
  "amber",
  "yellow",
  "lime",
  "green",
  "emerald",
  "teal",
  "cyan",
  "sky",
  "blue",
  "indigo",
  "violet",
  "purple",
  "fuchsia",
  "pink",
  "rose",
]);

/**
 * Values that share a colour utility's prefix but are not colours.
 *
 * `text-sm` is a size, `border-t` is a side. Enumerated rather than guessed
 * at: the list is short, and a wrong pattern would either hide a real
 * undeclared token or fail the build over a font size.
 */
const NON_COLOUR: Record<string, Set<string>> = {
  text: new Set(["xs", "sm", "base", "lg", "xl", "left", "right", "center", "justify"]),
  border: new Set(["t", "b", "l", "r", "x", "y", "solid", "dashed", "dotted", "none", "border"]),
  bg: new Set(["none", "cover", "contain", "fixed", "local", "scroll"]),
};

const COLOUR_UTILITIES = [
  "bg",
  "text",
  "border",
  "decoration",
  "ring",
  "fill",
  "stroke",
  "from",
  "via",
  "to",
];

/**
 * Strip comments before scanning.
 *
 * A comment explaining why `bg-warning/10` is wrong has to be able to write
 * `bg-warning/10`, and flagging it there would make the rule unteachable.
 */
function code(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
}

/** Colour token names declared in `theme.extend.colors`. */
function declaredTokens(): Set<string> {
  const colours = CONFIG.slice(CONFIG.indexOf("colors: {"), CONFIG.indexOf("fontFamily:"));
  const tokens = new Set<string>();
  for (const match of colours.matchAll(/^\s*"?([a-z][a-z-]*)"?:\s*"var\(/gm)) {
    if (match[1]) tokens.add(match[1]);
  }
  return tokens;
}

function colourUsages(): Array<{ utility: string; token: string; path: string }> {
  const pattern = new RegExp(`\\b(${COLOUR_UTILITIES.join("|")})-([a-z][a-z-]*)\\b`, "g");
  const found: Array<{ utility: string; token: string; path: string }> = [];
  for (const [path, text] of SOURCES) {
    for (const match of code(text).matchAll(pattern)) {
      const [, utility, token] = match;
      if (utility && token) found.push({ utility, token, path });
    }
  }
  return found;
}

describe("tailwind colour tokens (T-L2)", () => {
  it("finds the config and the sources, so a silent no-op cannot pass for a green test", () => {
    expect(SOURCES.length).toBeGreaterThan(10);
    expect(declaredTokens().size).toBeGreaterThan(5);
    expect(colourUsages().length).toBeGreaterThan(20);
  });

  it("declares every colour token the source refers to", () => {
    const declared = declaredTokens();
    const undeclared = colourUsages().filter(
      ({ utility, token }) =>
        !declared.has(token) && !BUILT_IN.has(token) && !NON_COLOUR[utility]?.has(token),
    );

    // Name the class rather than count it: the point is to say which.
    expect([...new Set(undeclared.map((u) => `${u.utility}-${u.token}`))]).toEqual([]);
  });

  it("never applies an opacity modifier to a project colour token", () => {
    /*
     * A class like `bg-warning/10` compiles to nothing. These tokens are
     * declared as a bare `var(--x)`, and Tailwind 3 cannot synthesise an
     * alpha channel from one -- it needs `rgb(var(--x) / <alpha-value>)`, so
     * the utility is silently dropped and the element loses its tint with
     * nothing at all to say so.
     *
     * Declare a token that carries the opacity it needs (`halt-bg` beside
     * `halt`, `up-bg` beside `up`) rather than asking Tailwind to derive one.
     */
    const declared = declaredTokens();
    const pattern = new RegExp(`\\b(${COLOUR_UTILITIES.join("|")})-([a-z][a-z-]*)/\\d+`, "g");

    const offenders: string[] = [];
    for (const [path, text] of SOURCES) {
      for (const match of code(text).matchAll(pattern)) {
        const [whole, , token] = match;
        if (token && declared.has(token)) offenders.push(`${whole} in ${path.split("/").pop()}`);
      }
    }

    expect(offenders).toEqual([]);
  });
});

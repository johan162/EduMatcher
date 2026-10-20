// @vitest-environment jsdom
/** StatTile (D2.2): both colour modes put the threshold colour on the right element. */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { StatTile } from "../src/components/widgets/StatTile.js";
import { formatMicros } from "../src/lib/format.js";
import { usePrefsStore } from "../src/store/usePrefsStore.js";

beforeEach(() => usePrefsStore.setState({ statColorMode: "value" }));
afterEach(cleanup);

const tile = () => screen.getByRole("region", { name: "Engine p99" });
const value = () => screen.getByTestId("stat-value");
const p99 = (v: number | null, mode?: "value" | "background") => (
  <StatTile label="Engine p99" value={v} format={formatMicros} thresholds={{ warn: 500, crit: 2000 }} colorMode={mode} spark={[1, 3, 2]} sub="last 1 min" />
);

describe("colour modes", () => {
  it("value mode colours the value, not the tile", () => {
    render(p99(640, "value"));
    expect(value().className).toContain("text-warning");
    expect(tile().className).toContain("bg-bg-subtle");
    expect(tile().className).not.toContain("bg-warning");
  });

  it("background mode colours the tile and writes on it in --bg", () => {
    render(p99(2500, "background"));
    expect(tile().className).toContain("bg-error");
    expect(value().className).toContain("text-bg");
    expect(value().className).not.toContain("text-error");
  });

  it("an OK value is coloured OK in both modes, without a level word", () => {
    render(p99(100, "background"));
    expect(tile().className).toContain("bg-ok");
    expect(tile().textContent).not.toContain("OK");
  });

  it("the settings choice applies unless the tile says otherwise", () => {
    usePrefsStore.setState({ statColorMode: "background" });
    render(p99(640));
    expect(tile().className).toContain("bg-warning");
  });
});

describe("content", () => {
  it("names the level in words and a glyph, and the thresholds on hover", () => {
    render(p99(640));
    expect(tile().textContent).toContain("◐ WARN");
    expect(tile().getAttribute("title")).toBe("WARN above 500 µs, CRIT above 2.00 ms");
    expect(tile().getAttribute("data-level")).toBe("WARN");
  });

  it("without a figure shows a dash and no colour", () => {
    render(p99(null, "background"));
    expect(value().textContent).toBe("—");
    expect(tile().className).not.toContain("bg-ok");
    expect(tile().getAttribute("data-level")).toBe("NONE");
  });

  it("without thresholds is plain", () => {
    render(<StatTile label="Orders today" value={184_302} format={String} />);
    expect(screen.getByTestId("stat-value").className).toContain("text-fg");
  });
});

describe("edge cases (review)", () => {
  it("a value that is not a number shows a dash, uncoloured, even in background mode", () => {
    render(<StatTile label="Reject ratio" value={Number.NaN} format={formatMicros} thresholds={{ warn: 5 }} colorMode="background" />);
    expect(screen.getByTestId("stat-value").textContent).toBe("—");
    expect(screen.getByRole("region", { name: "Reject ratio" }).className).toContain("bg-bg-subtle");
  });

  it("a long value can be cut (it may shrink) and keeps its full text on hover; the level word cannot", () => {
    render(<StatTile label="Big" value={1} format={() => "123 456 789 012 345"} thresholds={{ warn: 0 }} />);
    const v = screen.getByTestId("stat-value");
    expect(v.className).toContain("truncate");
    expect(v.className).toContain("min-w-0");
    expect(v.getAttribute("title")).toBe("123 456 789 012 345");
    expect(screen.getByText(/WARN/).className).toContain("shrink-0");
  });
});

// @vitest-environment jsdom
/** Gauge (D2.1): the arc's geometry, threshold bands, invert, clamping. */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { arcPath, bands, Gauge, START_DEG, SWEEP_DEG, valueAngle } from "../src/components/widgets/Gauge.js";
import { formatPercent } from "../src/lib/format.js";
import { levelOf } from "../src/lib/thresholds.js";

afterEach(cleanup);

describe("geometry: clockwise from 150° over the top to 30°", () => {
  it("min, mid and max sit at 150°, 270° and 30°", () => {
    expect(valueAngle(0, 0, 100)).toBe(150);
    expect(valueAngle(50, 0, 100)).toBe(270);
    expect(valueAngle(100, 0, 100)).toBe(30);
    expect(valueAngle(25, 0, 100)).toBe(210);
    expect(START_DEG + SWEEP_DEG).toBe(390);
  });

  it("values outside min..max clamp to the ends", () => {
    expect(valueAngle(-20, 0, 100)).toBe(150);
    expect(valueAngle(130, 0, 100)).toBe(30);
    expect(valueAngle(5, 10, 10)).toBe(150); // an empty scale draws nothing past min
  });

  it("an arc's end point is on the circle at its end angle", () => {
    // From 150° sweeping 120° ends at 270°: straight above the centre.
    const d = arcPath(100, 100, 50, 150, 120);
    const [x, y] = d.split(" ").slice(-2).map(Number);
    expect(x).toBeCloseTo(100, 1);
    expect(y).toBeCloseTo(50, 1);
    expect(d).toContain(" 0 0 1 "); // small arc, clockwise
    expect(arcPath(100, 100, 50, 150, 240)).toContain(" 0 1 1 "); // large arc
    expect(arcPath(100, 100, 50, 150, 0)).toBe("");
  });
});

describe("threshold bands", () => {
  it("follow the thresholds: OK, then WARN, then CRIT", () => {
    expect(bands(0, 100, { warn: 80, crit: 95 })).toEqual([
      [0, 80, "OK"],
      [80, 95, "WARN"],
      [95, 100, "CRIT"],
    ]);
    expect(bands(0, 100, { warn: 80 })).toEqual([
      [0, 80, "OK"],
      [80, 100, "WARN"],
    ]);
  });

  it("invert swaps them: low is bad", () => {
    expect(bands(0, 100, { warn: 20, crit: 10, invert: true })).toEqual([
      [0, 10, "CRIT"],
      [10, 20, "WARN"],
      [20, 100, "OK"],
    ]);
  });

  it("thresholds beyond the scale are cut to it", () => {
    expect(bands(0, 100, { warn: 120, crit: 150 })).toEqual([[0, 100, "OK"]]);
  });

  it("levels are pm-monitor's: strictly above warn, strictly above crit", () => {
    expect(levelOf(80, { warn: 80, crit: 95 })).toBe("OK");
    expect(levelOf(80.01, { warn: 80, crit: 95 })).toBe("WARN");
    expect(levelOf(95.01, { warn: 80, crit: 95 })).toBe("CRIT");
    expect(levelOf(20, { warn: 20, crit: 10, invert: true })).toBe("OK");
    expect(levelOf(9, { warn: 20, crit: 10, invert: true })).toBe("CRIT");
  });
});

describe("rendering", () => {
  it("draws each band in its level's colour and the value in its own", () => {
    render(<Gauge label="Memory" value={86} format={formatPercent} thresholds={{ warn: 80, crit: 95 }} />);
    const meter = screen.getByRole("meter", { name: "Memory" });
    const colours = [...meter.querySelectorAll("[data-band]")].map((b) => [b.getAttribute("data-band"), b.getAttribute("stroke")]);
    expect(colours).toEqual([
      ["OK", "var(--ok)"],
      ["WARN", "var(--warn)"],
      ["CRIT", "var(--crit)"],
    ]);
    expect(screen.getByTestId("gauge-value").getAttribute("stroke")).toBe("var(--warn)");
    // Not by colour alone: the level in words, and the definition on hover.
    expect(meter.textContent).toContain("◐ WARN");
    expect(meter.getAttribute("aria-valuetext")).toBe("86.0%, WARN");
    expect(meter.querySelector("title")?.textContent).toBe("WARN above 80.0%, CRIT above 95.0%");
  });

  it("an inverted gauge is critical when low", () => {
    render(<Gauge label="Disk free" value={8} format={formatPercent} thresholds={{ warn: 20, crit: 10, invert: true }} />);
    expect(screen.getByTestId("gauge-value").getAttribute("stroke")).toBe("var(--crit)");
    expect(screen.getByRole("meter").querySelector("title")?.textContent).toBe("WARN below 20.0%, CRIT below 10.0%");
  });

  it("an out-of-range value is shown as it is, its arc stopping at max", () => {
    render(<Gauge label="Over" value={130} format={formatPercent} />);
    expect(screen.getByRole("meter").textContent).toContain("130%");
    expect(screen.getByTestId("gauge-value").getAttribute("d")).toBe(arcPath(80, 80, 64, 150, 240));
  });

  it("needle mode draws a line instead of the filled arc", () => {
    render(<Gauge label="CPU" value={50} format={formatPercent} mode="needle" />);
    const needle = screen.getByTestId("gauge-value");
    expect(needle.tagName).toBe("line");
    // At 50 % the needle points straight up: x stays at the centre.
    expect(Number(needle.getAttribute("x2"))).toBeCloseTo(80, 1);
    expect(Number(needle.getAttribute("y2"))).toBeLessThan(80);
  });
});

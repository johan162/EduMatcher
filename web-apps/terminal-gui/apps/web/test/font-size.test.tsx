// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { SettingsPopover } from "../src/components/shared/SettingsPopover.js";
import {
  FONT_SIZE_FACTOR,
  applyFontSizeToDocument,
  useFontSizeStore,
} from "../src/store/useFontSizeStore.js";

beforeEach(() => {
  cleanup();
  localStorage.clear();
  useFontSizeStore.setState({ fontSize: "XS" });
  document.body.innerHTML = '<div id="root"></div>';
});

describe("font-size store", () => {
  it("defaults to XS, the app's current (unscaled) text size", () => {
    expect(useFontSizeStore.getState().fontSize).toBe("XS");
  });

  it("persists the choice to localStorage under terminal-font-size", () => {
    useFontSizeStore.getState().setFontSize("XL");
    expect(JSON.parse(localStorage.getItem("terminal-font-size") ?? "{}").state.fontSize).toBe("XL");
  });

  it("XS is the unscaled baseline and the rest scale up by the stated percentages", () => {
    expect(FONT_SIZE_FACTOR.XS).toBe(1);
    expect(FONT_SIZE_FACTOR.S).toBeCloseTo(1.15);
    expect(FONT_SIZE_FACTOR.M).toBeCloseTo(1.25);
    expect(FONT_SIZE_FACTOR.L).toBeCloseTo(1.4);
    expect(FONT_SIZE_FACTOR.XL).toBeCloseTo(1.55);
    expect(FONT_SIZE_FACTOR.XXL).toBeCloseTo(1.85);
  });

  it("applyFontSizeToDocument sets #root's CSS zoom to the size's factor", () => {
    applyFontSizeToDocument("XXL");
    expect(document.getElementById("root")?.style.zoom).toBe("1.85");
    applyFontSizeToDocument("XS");
    expect(document.getElementById("root")?.style.zoom).toBe("1");
  });
});

describe("SettingsPopover font-size control", () => {
  it("shows all six sizes, XS selected by default, and switches on click", () => {
    render(<SettingsPopover />);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));

    const group = screen.getByRole("radiogroup", { name: "Font size" });
    const options = ["XS", "S", "M", "L", "XL", "XXL"].map((label) =>
      screen.getByRole("radio", { name: label }),
    );
    expect(options).toHaveLength(6);
    expect(group.contains(options[0]!)).toBe(true);
    expect(options[0]!.getAttribute("aria-checked")).toBe("true");
    expect(options[4]!.getAttribute("aria-checked")).toBe("false");

    fireEvent.click(options[4]!); // XL

    expect(useFontSizeStore.getState().fontSize).toBe("XL");
    expect(options[4]!.getAttribute("aria-checked")).toBe("true");
    expect(options[0]!.getAttribute("aria-checked")).toBe("false");
  });
});

// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SettingsPopover } from "../src/components/shared/SettingsPopover";
import {
  applyFontSizeToDocument,
  FONT_SIZE_FACTOR,
  useFontSizeStore,
} from "../src/store/useFontSizeStore";

beforeEach(() => {
  localStorage.clear();
  useFontSizeStore.setState({ fontSize: "XS" });
  document.body.innerHTML = '<div id="root"></div>';
});
afterEach(cleanup);

describe("SettingsPopover (WP-UI06)", () => {
  it("is closed until the Settings button is pressed, then offers every font size", () => {
    render(<SettingsPopover />);
    expect(screen.queryByRole("radiogroup", { name: "Font size" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(screen.getAllByRole("radio").map((r) => r.textContent)).toEqual(["XS", "S", "M", "L", "XL", "XXL"]);
  });

  it("changes the font size and remembers it in localStorage", () => {
    render(<SettingsPopover />);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.click(screen.getByRole("radio", { name: "L" }));
    expect(useFontSizeStore.getState().fontSize).toBe("L");
    expect(screen.getByRole("radio", { name: "L" }).getAttribute("aria-checked")).toBe("true");
    expect(JSON.parse(localStorage.getItem("log-font-size")!).state.fontSize).toBe("L");
  });

  it("closes on Escape", () => {
    render(<SettingsPopover />);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
  });
});

describe("applyFontSizeToDocument", () => {
  it("zooms #root by the size's factor and exposes it as --zoom", () => {
    applyFontSizeToDocument("XL");
    const root = document.getElementById("root")!;
    expect(root.style.zoom).toBe(String(FONT_SIZE_FACTOR.XL));
    expect(root.style.getPropertyValue("--zoom")).toBe(String(FONT_SIZE_FACTOR.XL));
  });
});

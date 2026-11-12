// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { useAuthStore } from "@/store/useAuthStore";
import { applyFontSizeToDocument, useFontSizeStore } from "@/store/useFontSizeStore";
import { renderApp, signIn, stubApi } from "./helpers";

beforeEach(() => {
  useAuthStore.getState().logout();
  useFontSizeStore.setState({ fontSize: "M" });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("top bar", () => {
  it("shows the pm-clearing-gui wordmark, and the settings popover changes the font size", async () => {
    signIn("TRADER", "TRADER01");
    stubApi({});
    renderApp("/me/positions");
    expect(screen.getByText("pm-clearing-gui")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    const xl = screen.getByRole("radio", { name: "XL" });
    expect(screen.getByRole("radio", { name: "M" }).getAttribute("aria-checked")).toBe("true");
    fireEvent.click(xl);
    expect(useFontSizeStore.getState().fontSize).toBe("XL");
    expect(JSON.parse(localStorage.getItem("clearing-font-size") ?? "{}").state.fontSize).toBe("XL");

    document.body.insertAdjacentHTML("beforeend", '<div id="root"></div>');
    applyFontSizeToDocument("XL");
    expect(document.getElementById("root")?.style.zoom).toBe("1.55");
  });

  it("the help button opens the help drawer; Escape closes it", async () => {
    signIn("ADMIN", "OPS01");
    stubApi({});
    renderApp("/overview");
    fireEvent.click(screen.getByRole("button", { name: "Help" }));
    const drawer = screen.getByRole("dialog", { name: "Help" });
    expect(drawer.textContent).toContain("Getting Started");
    fireEvent.click(screen.getByRole("button", { name: "Units" }));
    expect(drawer.textContent).toContain("minor units");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Help" })).toBeNull();
  });
});

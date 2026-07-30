// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import {
  DENSITY_ORDER,
  applyThemeToDocument,
  usePrefsStore,
} from "../src/store/usePrefsStore.js";

beforeEach(() => {
  localStorage.clear();
  usePrefsStore.setState({ theme: "dark", density: "standard" });
});

describe("theme", () => {
  it("defaults to dark, the working default for a trading screen", () => {
    expect(usePrefsStore.getState().theme).toBe("dark");
  });

  it("toggles between the two themes", () => {
    usePrefsStore.getState().toggleTheme();
    expect(usePrefsStore.getState().theme).toBe("light");
    usePrefsStore.getState().toggleTheme();
    expect(usePrefsStore.getState().theme).toBe("dark");
  });

  it("drives the class the CSS variables key off", () => {
    applyThemeToDocument("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);

    applyThemeToDocument("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("survives a reload", () => {
    usePrefsStore.getState().setTheme("light");
    expect(localStorage.getItem("terminal-prefs")).toContain("light");
  });
});

describe("density", () => {
  it("defaults to standard", () => {
    expect(usePrefsStore.getState().density).toBe("standard");
  });

  it("cycles through every preset and wraps", () => {
    const seen = DENSITY_ORDER.map(() => {
      const current = usePrefsStore.getState().density;
      usePrefsStore.getState().cycleDensity();
      return current;
    });

    expect(new Set(seen).size).toBe(DENSITY_ORDER.length);
    expect(usePrefsStore.getState().density).toBe("standard");
  });

  it("survives a reload", () => {
    usePrefsStore.getState().setDensity("dense");
    expect(localStorage.getItem("terminal-prefs")).toContain("dense");
  });
});

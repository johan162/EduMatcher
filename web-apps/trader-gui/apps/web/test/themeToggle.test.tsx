// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { TopBar } from "@/components/layout/TopBar";
import { applyThemeToDocument, useThemeStore } from "@/store/useThemeStore";

beforeEach(() => {
  cleanup();
  useThemeStore.setState({ theme: "dark" });
  document.documentElement.classList.add("dark");
});

describe("theme store", () => {
  it("defaults to dark and toggles both ways", () => {
    expect(useThemeStore.getState().theme).toBe("dark");
    useThemeStore.getState().toggleTheme();
    expect(useThemeStore.getState().theme).toBe("light");
    useThemeStore.getState().toggleTheme();
    expect(useThemeStore.getState().theme).toBe("dark");
  });

  it("persists the choice to localStorage under trader-theme", () => {
    useThemeStore.getState().toggleTheme();
    expect(JSON.parse(localStorage.getItem("trader-theme") ?? "{}").state.theme).toBe("light");
  });

  it("applyThemeToDocument sets the .dark class on <html>", () => {
    applyThemeToDocument("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    applyThemeToDocument("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});

describe("TopBar theme switch", () => {
  it("shows the Sun icon in dark mode and flips to the Moon icon in light mode", () => {
    render(<TopBar />);
    const button = screen.getByRole("button", { name: "Theme: dark" });
    expect(button.querySelector("svg.lucide-sun")).not.toBeNull();

    fireEvent.click(button);

    expect(useThemeStore.getState().theme).toBe("light");
    const flipped = screen.getByRole("button", { name: "Theme: light" });
    expect(flipped.querySelector("svg.lucide-moon")).not.toBeNull();
    expect(flipped.getAttribute("title")).toBe("Theme: light — click to switch");
  });
});

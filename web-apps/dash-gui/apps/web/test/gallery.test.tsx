// @vitest-environment jsdom
/**
 * WP-D2's "done when": every widget renders with synthetic data, in both
 * themes. jsdom cannot resolve the colours, so `make test-e2e` also opens
 * /widgets in Chrome and checks both palettes there.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { WidgetGallery } from "../src/views/WidgetGallery.js";
import { applyThemeToDocument } from "../src/store/usePrefsStore.js";

beforeAll(() => {
  // ResponsiveContainer observes its size; jsdom has no ResizeObserver.
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});
afterEach(cleanup);

describe.each(["dark", "light"] as const)("the widget gallery, %s theme", (theme) => {
  it("renders every widget", () => {
    applyThemeToDocument(theme);
    render(<WidgetGallery />);
    expect(document.documentElement.classList.contains("dark")).toBe(theme === "dark");
    expect(screen.getAllByRole("meter")).toHaveLength(4);
    for (const tile of ["Processes", "Orders today", "Engine p99", "Reject ratio", "Disk free", "Participants"]) {
      expect(screen.getAllByRole("region", { name: tile }).length).toBeGreaterThan(0);
    }
    for (const figure of ["CPU per process", "Exchange memory", "Orders per minute", "Participant connections"]) {
      expect(screen.getByRole("figure", { name: figure })).toBeTruthy();
    }
    expect(screen.getByRole("region", { name: "Memory per process" })).toBeTruthy();
    expect(screen.getByRole("table", { name: "Processes" })).toBeTruthy();
    expect(screen.getByRole("log")).toBeTruthy();
    expect(screen.getAllByRole("button", { expanded: true })).toHaveLength(3);
  });
});

// @vitest-environment jsdom
/**
 * In-app help (AG7): the canvas and the drawer are explained where they are
 * used, in the same words as the marks themselves.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { HELP_TOPICS } from "@/components/help/helpContent";
import { END_MARKS, MASK_EFFECT } from "@/lib/marks";
import { useAuthStore } from "@/store/useAuthStore";
import { useSnapshotStore } from "@/store/useSnapshotStore";
import { example, renderApp, signIn, stubApi } from "./helpers";

beforeEach(() => {
  useAuthStore.getState().logout();
  useSnapshotStore.getState().clear();
  signIn();
  stubApi({ "/api/v1/audit/collections": example("/api/v1/audit/collections") });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function topicText(id: string): string {
  const topic = HELP_TOPICS.find((t) => t.id === id);
  expect(topic, id).toBeDefined();
  return JSON.stringify(topic);
}

describe("help", () => {
  it("opens from the top bar, switches topics, and Escape closes it", () => {
    renderApp("/overview");
    fireEvent.click(screen.getByRole("button", { name: "Help" }));
    const drawer = screen.getByRole("dialog", { name: "Help" });
    const topics = within(drawer).getByRole("navigation", { name: "Help topics" });
    expect(within(topics).getAllByRole("button").map((b) => b.textContent)).toEqual(HELP_TOPICS.map((t) => t.title));
    fireEvent.click(within(topics).getByRole("button", { name: "Market canvas" }));
    expect(drawer.textContent).toContain("depth heatmap");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Help" })).toBeNull();
  });

  it("the canvas topic explains every end glyph and both masks in the marks' own words", () => {
    const text = topicText("market");
    for (const mark of Object.values(END_MARKS)) expect(text).toContain(`${mark.glyph} ${mark.text}`);
    expect(text).toContain(MASK_EFFECT.gap);
    expect(text).toContain(MASK_EFFECT.halt);
    expect(text).toContain("brush");
  });

  it("the drawer topic names its three tabs and the evidence banner topic its manifest states", () => {
    const drawer = topicText("drawer");
    for (const tab of ["Story", "Checks", "Raw evidence"]) expect(drawer).toContain(tab);
    const banner = topicText("evidence");
    for (const state of ["checked, unanchored", "failed", "no manifest"]) expect(banner).toContain(state);
  });

  it("says which clock every time is on", () => {
    expect(topicText("clocks")).toContain("receipt clock");
  });
});

// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { useAuthStore } from "@/store/useAuthStore";
import { useExplainStore } from "@/store/useExplainStore";
import { useSnapshotStore } from "@/store/useSnapshotStore";
import { currentPath, example, renderApp, signIn, stubApi } from "./helpers";

beforeEach(() => {
  useAuthStore.getState().logout();
  useSnapshotStore.getState().clear();
  useExplainStore.setState({ explain: true });
  signIn();
  stubApi({ "/api/v1/audit/collections": example("/api/v1/audit/collections") });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("shell", () => {
  it("offers the seven workspaces, grouped by the reviewer's workflow", () => {
    renderApp("/overview");
    const nav = screen.getByRole("navigation", { name: "Workspaces" });
    const groups = within(nav).getAllByRole("group");
    expect(
      groups.map((g) => [g.getAttribute("aria-label"), within(g).getAllByRole("link").map((a) => a.textContent)]),
    ).toEqual([
      ["Triage", ["Overview", "Findings"]],
      ["Investigate", ["Market", "Participants", "Explorer"]],
      ["Trust", ["Integrity & Coverage"]],
      ["Conclude", ["Investigations"]],
    ]);
  });

  it.each([
    ["/findings", "Findings"],
    ["/market", "Market"],
    ["/participants", "Participants"],
    ["/explorer", "Explorer"],
    ["/integrity", "Integrity & Coverage"],
    ["/investigations", "Investigations"],
  ])("%s is not in this release, and says so", (path, name) => {
    renderApp(path);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(name);
    expect(screen.getByText("Not in this release.")).toBeTruthy();
  });

  it("the root opens the Overview, which asks for a snapshot first", () => {
    renderApp("/");
    expect(currentPath()).toBe("/overview");
    expect(screen.getByText("No snapshot pinned")).toBeTruthy();
  });

  it("the top bar names the app, and Explain is one switch for the whole app", () => {
    renderApp("/overview");
    expect(screen.getByText("pm-audit-gui")).toBeTruthy();
    const explain = screen.getByRole("button", { name: "Explain" });
    expect(explain.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(explain);
    expect(useExplainStore.getState().explain).toBe(false);
  });

  it("logging out forgets the key and the snapshot", () => {
    useSnapshotStore.getState().select("world", "s-3f1c9a07be52d4e6a810");
    renderApp("/overview");
    fireEvent.click(screen.getByRole("button", { name: "Log out" }));
    expect(useAuthStore.getState().apiKey).toBeNull();
    expect(useSnapshotStore.getState().snapshotId).toBeNull();
    expect(currentPath()).toBe("/login");
  });
});

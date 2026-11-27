// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useAuthStore } from "@/store/useAuthStore";
import { useSnapshotStore } from "@/store/useSnapshotStore";
import { apiError, example, renderApp, signIn, snapshotExample, stubApi } from "./helpers";

const COLLECTIONS = {
  collections: [
    { id: "world", available: true, reason: null, files: 1 },
    { id: "moved", available: false, reason: "SOURCE_MISSING", files: 0 },
  ],
  count: 2,
};

beforeEach(() => {
  useAuthStore.getState().logout();
  useSnapshotStore.getState().clear();
  signIn();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function pick(id: string) {
  fireEvent.change(screen.getByLabelText("Evidence collection"), { target: { value: id } });
}

describe("snapshot picker", () => {
  it("lists the configured collections by id; an unavailable one cannot be chosen", async () => {
    stubApi({ "/api/v1/audit/collections": COLLECTIONS });
    renderApp("/overview");
    const select = screen.getByLabelText("Evidence collection");
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(3));
    const moved = within(select).getByRole("option", { name: /moved/ }) as HTMLOptionElement;
    expect(moved.disabled).toBe(true);
    expect(moved.textContent).toContain("SOURCE_MISSING");
    expect((within(select).getByRole("option", { name: "world" }) as HTMLOptionElement).disabled).toBe(false);
  });

  it("choosing one pins it and labels the view a historical snapshot", async () => {
    const snapshot = { ...snapshotExample(), collection_id: "world" };
    const api = stubApi({
      "/api/v1/audit/collections": COLLECTIONS,
      "POST /api/v1/audit/snapshots": () => new Response(JSON.stringify(snapshot), { status: 201 }),
      "/api/v1/audit/findings": example("/api/v1/audit/findings"),
    });
    renderApp("/overview");
    await screen.findByRole("option", { name: "world" });
    pick("world");
    const label = await screen.findByTestId("snapshot-label");
    expect(label.textContent).toContain("Historical snapshot");
    expect(label.textContent).toContain(snapshot.snapshot_id);
    expect(label.textContent).toContain("records to 2026-06-15 15:30:12.874 UTC");
    expect(label.textContent).toContain(`pinned ${snapshot.created_at.slice(0, 10)}`);
    expect(api.calls("/api/v1/audit/snapshots")).toEqual([
      { method: "POST", url: "/api/v1/audit/snapshots", body: { collection_id: "world" } },
    ]);
    expect(useSnapshotStore.getState()).toMatchObject({ collectionId: "world", snapshotId: snapshot.snapshot_id });
    expect(await screen.findByRole("region", { name: "Evidence" })).toBeTruthy();
  });

  it("a 503 while pinning is an error naming its reason, not an empty snapshot", async () => {
    stubApi({
      "/api/v1/audit/collections": COLLECTIONS,
      "POST /api/v1/audit/snapshots": apiError(503, "AUDIT_SOURCE_UNAVAILABLE", "collection world: gone", {
        reason: "SOURCE_MISSING",
      }),
    });
    renderApp("/overview");
    await screen.findByRole("option", { name: "world" });
    pick("world");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("AUDIT_SOURCE_UNAVAILABLE");
    expect(alert.textContent).toContain("SOURCE_MISSING");
    expect(screen.queryByRole("region", { name: "Evidence" })).toBeNull();
    expect(useSnapshotStore.getState().snapshotId).toBeNull();
  });

  it("a collections list the gateway cannot give is an error, not 'no collections'", async () => {
    stubApi({ "/api/v1/audit/collections": apiError(403, "ROLE_DENIED", "ADMIN only") });
    renderApp("/overview");
    expect((await screen.findByRole("alert")).textContent).toContain("ROLE_DENIED");
  });
});

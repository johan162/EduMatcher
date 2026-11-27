// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { useAuthStore } from "@/store/useAuthStore";
import { apiError, currentPath, example, renderApp, stubApi } from "./helpers";

beforeEach(() => useAuthStore.getState().logout());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function logIn(key: string) {
  renderApp("/login");
  fireEvent.change(screen.getByLabelText("API key"), { target: { value: key } });
  fireEvent.click(screen.getByRole("button", { name: "Connect" }));
}

describe("login", () => {
  it("an ADMIN key is kept (in memory) and opens the Overview", async () => {
    stubApi({
      "/api/v1/status": { ...example<Record<string, unknown>>("/api/v1/status"), gateway_id: "OPS01", gateway_role: "ADMIN" },
      "/api/v1/audit/collections": example("/api/v1/audit/collections"),
    });
    logIn("key-ops01");
    await waitFor(() => expect(currentPath()).toBe("/overview"));
    expect(useAuthStore.getState().apiKey).toBe("key-ops01");
  });

  it.each(["TRADER", "MARKET_MAKER"])("a %s key is refused with a clear message and not kept", async (role) => {
    stubApi({ "/api/v1/status": { gateway_id: "TRADER01", gateway_role: role } });
    logIn("key-trader01");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(`${role} key`);
    expect(alert.textContent).toContain("ADMIN");
    expect(useAuthStore.getState().apiKey).toBeNull();
    expect(currentPath()).toBe("/login");
  });

  it("a read-only key is refused as read-only", async () => {
    stubApi({ "/api/v1/status": apiError(403, "READ_ONLY", "Read-only key") });
    logIn("key-ro");
    expect((await screen.findByRole("alert")).textContent).toContain("read-only key");
    expect(useAuthStore.getState().apiKey).toBeNull();
  });

  it("an unknown key is invalid", async () => {
    stubApi({ "/api/v1/status": apiError(401, "UNAUTHORIZED") });
    logIn("nope");
    expect((await screen.findByRole("alert")).textContent).toBe("Invalid API key.");
  });

  it("a signed-out visit to a workspace goes to the login", () => {
    stubApi({});
    renderApp("/market");
    expect(currentPath()).toBe("/login");
  });
});

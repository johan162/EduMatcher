// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { useAuthStore } from "@/store/useAuthStore";
import { apiError, currentPath, example, renderApp, signIn, stubApi } from "./helpers";

/**
 * Login through GET /api/v1/status, the role landing pages, and RoleGuard.
 * Hiding a link is not authorization (the API enforces scope); the guard only
 * keeps a user from landing on a screen whose every request would be refused.
 */
beforeEach(() => {
  useAuthStore.getState().logout();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function logIn(key: string): Promise<void> {
  fireEvent.change(await screen.findByLabelText("API key"), { target: { value: key } });
  fireEvent.click(screen.getByRole("button", { name: "Connect" }));
}

describe("login", () => {
  it("an unauthenticated visit to a protected screen lands on the login page", async () => {
    stubApi({});
    renderApp("/me/positions");
    await waitFor(() => expect(currentPath()).toBe("/login"));
  });

  it("a TRADER key lands on My Clearing", async () => {
    stubApi({
      "/api/v1/status": example("/api/v1/status"),
      "/api/v1/clearing/positions": example("/api/v1/clearing/positions"),
      "/api/v1/clearing/exposure": example("/api/v1/clearing/exposure"),
    });
    renderApp("/login");
    await logIn("key-trader");
    await waitFor(() => expect(currentPath()).toBe("/me/positions"));
    expect(useAuthStore.getState()).toMatchObject({
      apiKey: "key-trader",
      gatewayId: "TRADER01",
      role: "TRADER",
    });
  });

  it("an ADMIN key lands on the Clearing Overview", async () => {
    stubApi({
      "/api/v1/status": { gateway_id: "OPS01", gateway_role: "ADMIN", gateway_count: 3 },
    });
    renderApp("/login");
    await logIn("key-ops");
    await waitFor(() => expect(currentPath()).toBe("/overview"));
  });

  it("a read-only key is refused with a reason and stays logged out", async () => {
    stubApi({ "/api/v1/status": apiError(403, "READ_ONLY", "API key is read-only") });
    renderApp("/login");
    await logIn("key-ro");
    expect((await screen.findByRole("alert")).textContent).toMatch(/read-only/i);
    expect(useAuthStore.getState().apiKey).toBeNull();
    expect(currentPath()).toBe("/login");
  });

  it("an unknown key says so", async () => {
    stubApi({ "/api/v1/status": apiError(401, "AUTH", "Unknown API key") });
    renderApp("/login");
    await logIn("nope");
    expect((await screen.findByRole("alert")).textContent).toContain("Invalid API key.");
  });

  it("an unreachable gateway is not reported as a bad key", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    renderApp("/login");
    await logIn("key-trader");
    expect((await screen.findByRole("alert")).textContent).toMatch(/Cannot reach the API gateway/);
  });
});

describe("role guard", () => {
  it.each([
    ["TRADER", "/overview", "/me/positions"],
    ["TRADER", "/reconciliation", "/me/positions"],
    ["TRADER", "/participants/MM01", "/me/positions"],
    ["TRADER", "/me/obligations", "/me/positions"],
    ["MARKET_MAKER", "/eod", "/me/positions"],
    ["ADMIN", "/me/positions", "/overview"],
  ] as const)("%s typing %s is sent to %s", async (role, path, landing) => {
    signIn(role);
    stubApi({});
    renderApp(path);
    await waitFor(() => expect(currentPath()).toBe(landing));
  });

  it("a MARKET_MAKER may open My Quote Obligations", async () => {
    signIn("MARKET_MAKER", "MM01");
    stubApi({ "/api/v1/symbols": example("/api/v1/symbols") });
    renderApp("/me/obligations");
    expect(await screen.findByRole("heading", { name: "My Quote Obligations" })).toBeTruthy();
    expect(currentPath()).toBe("/me/obligations");
  });

  it("logging out returns to the login page", async () => {
    signIn("TRADER");
    stubApi({});
    renderApp("/me/trades");
    fireEvent.click(await screen.findByRole("button", { name: "Log out" }));
    await waitFor(() => expect(currentPath()).toBe("/login"));
    expect(useAuthStore.getState().apiKey).toBeNull();
  });
});

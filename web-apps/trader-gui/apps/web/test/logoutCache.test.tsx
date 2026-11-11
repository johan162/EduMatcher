// @vitest-environment jsdom
/**
 * CG10: no cached response of one login survives a logout. Without it, a
 * second user logging in on the same tab within the 30 s stale time is shown
 * the first user's positions as fresh data, with no refetch.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

vi.mock(import("@/ws/WebSocketManager"), async (importOriginal) => ({
  ...(await importOriginal()),
  useWebSocketManager: () => {},
}));

/** Gateway A's positions; gateway B's request never answers. */
const apiFetchMock = vi.fn((path: string): Promise<unknown> => {
  if (path.startsWith("/api/v1/positions")) {
    return useAuthStore.getState().gatewayId === "GW_A"
      ? Promise.resolve({ positions: [{ symbol: "AAPL", net_qty: 500, last_price: 151.2 }] })
      : new Promise(() => {});
  }
  return new Promise(() => {});
});

vi.mock("@/api/apiFetch", () => ({
  apiFetch: (path: string) => apiFetchMock(path),
  ApiError: class ApiError extends Error {},
}));

import App from "@/App";
import { useAuthStore } from "@/store/useAuthStore";

beforeEach(() => {
  cleanup();
  apiFetchMock.mockClear();
  useAuthStore.getState().logout();
});

describe("query cache across logins (CG10)", () => {
  it("never shows gateway A's positions to gateway B", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
    act(() => useAuthStore.getState().login("key-a", "GW_A", "TRADER"));
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/positions"]}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("AAPL")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Logout" }));
    act(() => useAuthStore.getState().login("key-b", "GW_B", "TRADER"));
    fireEvent.click(await screen.findByRole("link", { name: /Positions/ }));

    expect(await screen.findByRole("heading", { name: "Positions" })).toBeTruthy();
    expect(screen.queryByText("AAPL")).toBeNull();
  });
});

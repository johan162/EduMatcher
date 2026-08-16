// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const apiFetchMock = vi.fn(async (path: string, _init?: { body?: string }) => {
  if (path.startsWith("/api/v1/admin/gateways") && path.endsWith("/disconnect")) {
    return { gateway_id: "GW01", status: "DISCONNECTED" };
  }
  if (path.startsWith("/api/v1/admin/gateways")) {
    return {
      gateways: [
        { id: "GW01", role: "TRADER", connected: true, description: "Desk A" },
        { id: "GW09", role: "ADMIN", connected: false, description: "Console" },
      ],
    };
  }
  if (path === "/api/v1/admin/kill-switch/symbol") {
    return { accepted: true, symbol: "AAPL", reason: "", cancelled_orders: 3, cancelled_quotes: 0 };
  }
  if (path === "/api/v1/admin/kill-switch/gateway") {
    return { accepted: true, target_gateway_id: "GW01", reason: "", cancelled_orders: 5, cancelled_quotes: 2 };
  }
  if (path === "/api/v1/admin/kill-switch/global") {
    return { accepted: true, reason: "", cancelled_orders: 9, cancelled_quotes: 4, affected_gateways: 3 };
  }
  return {};
});

vi.mock("@/api/apiFetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...(args as [string, { body?: string }])),
  ApiError: class ApiError extends Error {
    constructor(public status = 0, public code = "UNKNOWN", message = "") {
      super(message);
      this.name = "ApiError";
    }
  },
}));

import { AdminGatewaysPage } from "@/pages/AdminGatewaysPage";
import { useSymbolStore } from "@/store/useSymbolStore";
import type { Symbol } from "@/types/index";

const SYMBOLS: Symbol[] = [
  { symbol: "AAPL", tick_decimals: 2, prev_close: 150, collar_reference_price: null, level: null },
];

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

const called = (path: string) => apiFetchMock.mock.calls.some(([p]) => String(p) === path);

beforeEach(() => {
  cleanup();
  apiFetchMock.mockClear();
  useSymbolStore.setState({ symbols: SYMBOLS });
});

describe("AdminGatewaysPage (§15.7)", () => {
  it("renders the roster and disables Kick for an offline gateway", async () => {
    wrap(<AdminGatewaysPage />);
    await waitFor(() => expect(screen.getByText("GW01")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Kick gateway GW01" })).toHaveProperty("disabled", false);
    expect(screen.getByRole("button", { name: "Kick gateway GW09" })).toHaveProperty("disabled", true);
  });

  it("kicks a connected gateway after confirmation", async () => {
    wrap(<AdminGatewaysPage />);
    await waitFor(() => expect(screen.getByText("GW01")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Kick gateway GW01" }));
    expect(screen.getByText(/Disconnect gateway GW01\?/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    await waitFor(() => expect(called("/api/v1/admin/gateways/GW01/disconnect")).toBe(true));
  });
});

describe("KillSwitchPanel (§15.8)", () => {
  it("cancels by symbol after confirmation", async () => {
    wrap(<AdminGatewaysPage />);
    await waitFor(() => expect(screen.getByText("GW01")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Kill switch symbol"), { target: { value: "AAPL" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel symbol" }));
    // Dialog "Cancel symbol" confirm button; nothing posted yet.
    expect(screen.getByText(/Kill switch — symbol\?/)).toBeTruthy();
    expect(called("/api/v1/admin/kill-switch/symbol")).toBe(false);
    // The dialog's confirm button also reads "Cancel symbol" — pick the one in the dialog.
    const dialog = screen.getByRole("dialog", { name: "Kill switch — symbol?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel symbol" }));
    await waitFor(() => expect(called("/api/v1/admin/kill-switch/symbol")).toBe(true));
  });

  it("cancels by gateway after confirmation", async () => {
    wrap(<AdminGatewaysPage />);
    await waitFor(() => expect(screen.getByText("GW01")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Kill switch gateway"), { target: { value: "GW01" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel gateway" }));
    const dialog = screen.getByRole("dialog", { name: "Kill switch — gateway?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel gateway" }));
    await waitFor(() => expect(called("/api/v1/admin/kill-switch/gateway")).toBe(true));
    const body = JSON.parse(
      apiFetchMock.mock.calls.find(([p]) => p === "/api/v1/admin/kill-switch/gateway")![1]!.body as string,
    );
    expect(body).toEqual({ target_gateway_id: "GW01" });
  });

  it("global kill switch requires typing CONFIRM before Execute is enabled", async () => {
    wrap(<AdminGatewaysPage />);
    await waitFor(() => expect(screen.getByText("GW01")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Kill all" }));
    const execBtn = screen.getByRole("button", { name: "Execute global kill" });
    expect(execBtn).toHaveProperty("disabled", true);
    fireEvent.change(screen.getByLabelText("Type CONFIRM to confirm"), { target: { value: "CONFIRM" } });
    expect(screen.getByRole("button", { name: "Execute global kill" })).toHaveProperty("disabled", false);
    fireEvent.click(screen.getByRole("button", { name: "Execute global kill" }));
    await waitFor(() => expect(called("/api/v1/admin/kill-switch/global")).toBe(true));
  });
});

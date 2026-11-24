// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const ROSTER = [
  // 2026-11-16 08:30:05 UTC
  { id: "GW01", role: "TRADER", connected: true, description: "Desk A", connected_since_ns: 1_794_817_805_000_000_000 },
  { id: "GW09", role: "ADMIN", connected: false, description: "Console" },
];
let roster = ROSTER;

const apiFetchMock = vi.fn(async (path: string, _init?: { body?: string }) => {
  if (path.startsWith("/api/v1/admin/gateways") && path.endsWith("/disconnect")) {
    return { accepted: true, target_gateway_id: "GW01", reason: "" };
  }
  if (path.startsWith("/api/v1/admin/gateways")) {
    return { gateways: roster };
  }
  if (path === "/api/v1/admin/symbols/AAPL/cancel-orders") {
    return { accepted: true, symbol: "AAPL", reason: "", cancelled_orders: 3, cancelled_quotes: 0 };
  }
  if (path === "/api/v1/admin/gateways/GW01/kill-switch") {
    return { accepted: true, target_gateway_id: "GW01", reason: "", cancelled_orders: 5, cancelled_quotes: 2 };
  }
  if (path === "/api/v1/admin/market/kill-switch") {
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
import { useSessionStore } from "@/store/useSessionStore";
import { usePrefsStore } from "@/store/usePrefsStore";
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
  roster = ROSTER;
  usePrefsStore.setState({ participantsPageSize: 30 });
  useSessionStore.setState({ timezone: "UTC" });
  useSymbolStore.setState({ symbols: SYMBOLS });
});

describe("AdminGatewaysPage (§15.7)", () => {
  it("renders the roster and disables Kill for an offline gateway", async () => {
    wrap(<AdminGatewaysPage />);
    await waitFor(() => expect(screen.getByText("GW01")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Kill participant GW01" })).toHaveProperty("disabled", false);
    expect(screen.getByRole("button", { name: "Kill participant GW09" })).toHaveProperty("disabled", true);
  });

  it("kicks a connected gateway after confirmation", async () => {
    wrap(<AdminGatewaysPage />);
    await waitFor(() => expect(screen.getByText("GW01")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Kill participant GW01" }));
    expect(screen.getByText(/Disconnect participant GW01\?/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    await waitFor(() => expect(called("/api/v1/admin/gateways/GW01/disconnect")).toBe(true));
  });

  it("reports the engine's refusal to disconnect (409 DISCONNECT_REJECTED)", async () => {
    // L044: the endpoint now awaits the engine's answer instead of 202 for any id.
    const { ApiError } = await import("@/api/apiFetch");
    const { toast } = await import("sonner");
    wrap(<AdminGatewaysPage />);
    await waitFor(() => expect(screen.getByText("GW01")).toBeTruthy());
    apiFetchMock.mockRejectedValueOnce(
      new ApiError(409, "DISCONNECT_REJECTED", "Gateway not connected: GW01"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Kill participant GW01" }));
    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    await waitFor(() =>
      expect((toast.error as unknown as { mock: { calls: unknown[][] } }).mock.calls.at(-1)![0]).toBe(
        "DISCONNECT_REJECTED: Gateway not connected: GW01",
      ),
    );
  });
});

describe("Participant list filter and pager", () => {
  const rowIds = () => screen.getAllByRole("row").slice(1).map((r) => r.querySelector("td")?.textContent);

  it("finds by ID and filters by role, over the whole roster", async () => {
    wrap(<AdminGatewaysPage />);
    await waitFor(() => expect(screen.getByText("GW01")).toBeTruthy());
    expect(screen.getByText("2 participants")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Find ID"), { target: { value: "w09" } });
    expect(rowIds()).toEqual(["GW09"]);
    expect(screen.getByText("1 participant of 2")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Find ID"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Filter by role"), { target: { value: "TRADER" } });
    expect(rowIds()).toEqual(["GW01"]);
  });

  it("shows when each participant connected, and a dash while offline", async () => {
    wrap(<AdminGatewaysPage />);
    await waitFor(() => expect(screen.getByText("GW01")).toBeTruthy());
    const cells = (id: string) => [...screen.getByText(id).closest("tr")!.querySelectorAll("td")].map((td) => td.textContent);
    expect(screen.getByRole("columnheader", { name: /Connected since/ })).toBeTruthy();
    expect(cells("GW01")).toContain("2026-11-16 08:30:05");
    expect(cells("GW09")).toContain("—");
  });

  it("remembers the rows-per-page choice", async () => {
    wrap(<AdminGatewaysPage />);
    await waitFor(() => expect(screen.getByText("GW01")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Rows per page"), { target: { value: "50" } });
    expect(usePrefsStore.getState().participantsPageSize).toBe(50);
    expect(JSON.parse(localStorage.getItem("trader-prefs")!).state.participantsPageSize).toBe(50);
  });

  it("pages the roster, 30 rows by default, and resets to page 1 on a filter change", async () => {
    roster = Array.from({ length: 35 }, (_, i) => ({
      id: `P${String(i + 1).padStart(2, "0")}`,
      role: i % 2 ? "ADMIN" : "TRADER",
      connected: true,
      description: "",
    }));
    wrap(<AdminGatewaysPage />);
    await waitFor(() => expect(screen.getByText("P01")).toBeTruthy());
    expect(screen.getByText("Page 1/2")).toBeTruthy();
    expect(rowIds()).toHaveLength(30);
    expect(screen.getByRole("button", { name: "Previous page" })).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByText("Page 2/2")).toBeTruthy();
    expect(rowIds()).toEqual(["P31", "P32", "P33", "P34", "P35"]);
    fireEvent.change(screen.getByLabelText("Filter by role"), { target: { value: "ADMIN" } });
    expect(screen.getByText("Page 1/1")).toBeTruthy();
    expect(rowIds()).toHaveLength(17);
    fireEvent.change(screen.getByLabelText("Rows per page"), { target: { value: "10" } });
    expect(screen.getByText("Page 1/2")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Rows per page"), { target: { value: "0" } });
    expect(screen.getByText("Page 1/1")).toBeTruthy();
    expect(rowIds()).toHaveLength(17);
  });
});

describe("KillSwitchPanel (§15.8)", () => {
  it("cancels by symbol after confirmation", async () => {
    wrap(<AdminGatewaysPage />);
    await waitFor(() => expect(screen.getByText("GW01")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Mass cancel symbol"), { target: { value: "AAPL" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel symbol" }));
    // Dialog "Cancel symbol" confirm button; nothing posted yet.
    expect(screen.getByText(/Mass cancel — symbol\?/)).toBeTruthy();
    expect(called("/api/v1/admin/symbols/AAPL/cancel-orders")).toBe(false);
    // The dialog's confirm button also reads "Cancel symbol" — pick the one in the dialog.
    const dialog = screen.getByRole("dialog", { name: "Mass cancel — symbol?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel symbol" }));
    await waitFor(() => expect(called("/api/v1/admin/symbols/AAPL/cancel-orders")).toBe(true));
  });

  it("reports an engine refusal (409 KILL_SWITCH_REJECTED) with the engine's reason", async () => {
    // WP-API01: refusals used to arrive as 403 ROLE_DENIED.
    const { ApiError } = await import("@/api/apiFetch");
    const { toast } = await import("sonner");
    wrap(<AdminGatewaysPage />);
    await waitFor(() => expect(screen.getByText("GW01")).toBeTruthy());
    apiFetchMock.mockRejectedValueOnce(
      new ApiError(409, "KILL_SWITCH_REJECTED", "Symbol-level mass cancel is only allowed for ADMIN participants"),
    );
    fireEvent.change(screen.getByLabelText("Mass cancel symbol"), { target: { value: "AAPL" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel symbol" }));
    const dialog = screen.getByRole("dialog", { name: "Mass cancel — symbol?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel symbol" }));
    await waitFor(() =>
      expect((toast.error as unknown as { mock: { calls: unknown[][] } }).mock.calls.at(-1)![0]).toBe(
        "Rejected: Symbol-level mass cancel is only allowed for ADMIN participants",
      ),
    );
  });

  it("cancels by gateway after confirmation", async () => {
    wrap(<AdminGatewaysPage />);
    await waitFor(() => expect(screen.getByText("GW01")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Mass cancel participant"), { target: { value: "GW01" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel orders only" }));
    const dialog = screen.getByRole("dialog", { name: "Mass cancel — participant?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel orders only" }));
    // D1: the target gateway is the path segment, not a body field.
    await waitFor(() => expect(called("/api/v1/admin/gateways/GW01/kill-switch")).toBe(true));
    const body = JSON.parse(
      apiFetchMock.mock.calls.find(([p]) => p === "/api/v1/admin/gateways/GW01/kill-switch")![1]!.body as string,
    );
    expect(body).toEqual({});
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
    await waitFor(() => expect(called("/api/v1/admin/market/kill-switch")).toBe(true));
  });
});

describe("GatewayDrawer", () => {
  it("opens on row click, shows the gateway's monitor data, and closes", async () => {
    const { useMonitorStore } = await import("@/store/useMonitorStore");
    useMonitorStore.setState({
      orders: {
        o1: { order_id: "o1", gateway_id: "GW01", status: "ACKED", symbol: "AAPL", side: "BUY", price: 150, quantity: 10 },
        o2: { order_id: "o2", gateway_id: "GW09", status: "ACKED", symbol: "MSFT" },
      },
      events: [],
    });
    wrap(<AdminGatewaysPage />);
    await waitFor(() => expect(screen.getByText("GW01")).toBeTruthy());
    expect(screen.queryByRole("dialog", { name: "Participant GW01" })).toBeNull();
    fireEvent.click(screen.getByText("GW01"));
    const drawer = screen.getByRole("dialog", { name: "Participant GW01" });
    expect(within(drawer).getByText("AAPL")).toBeTruthy();
    expect(within(drawer).queryByText("MSFT")).toBeNull();
    fireEvent.click(within(drawer).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog", { name: "Participant GW01" })).toBeNull();
  });

  it("Kill in the row does not open the drawer", async () => {
    wrap(<AdminGatewaysPage />);
    await waitFor(() => expect(screen.getByText("GW01")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Kill participant GW01" }));
    expect(screen.queryByRole("dialog", { name: "Participant GW01" })).toBeNull();
  });
});

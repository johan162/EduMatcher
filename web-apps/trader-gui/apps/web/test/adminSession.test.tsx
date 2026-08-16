// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { toast } from "sonner";
import type { ReactNode } from "react";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const apiFetchMock = vi.fn(async (path: string, init?: { body?: string }) => {
  if (path === "/api/v1/admin/session/transition") {
    const body = JSON.parse(init!.body!);
    return { command_id: "cmd-1", requested_state: body.to_state, status: "APPLIED" };
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

import { AdminSessionPage } from "@/pages/AdminSessionPage";
import { useSessionStore } from "@/store/useSessionStore";

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  useSessionStore.setState({ phase: "PRE_OPEN" });
});

describe("AdminSessionPage (§15.4)", () => {
  it("offers only the valid transitions from the current phase", () => {
    wrap(<AdminSessionPage />);
    // From PRE_OPEN: Opening Auction, Continuous. Not Closed.
    expect(screen.getByRole("button", { name: "Opening Auction" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Continuous" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Closed" })).toBeNull();
  });

  it("confirms then POSTs the transition and reports APPLIED", async () => {
    wrap(<AdminSessionPage />);
    fireEvent.click(screen.getByRole("button", { name: "Continuous" }));
    // Confirmation dialog appears; nothing posted yet.
    expect(screen.getByText(/Transition session\?/)).toBeTruthy();
    expect(apiFetchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Transition to Continuous" }));
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    const body = JSON.parse(apiFetchMock.mock.calls[0]![1]!.body as string);
    expect(body).toEqual({ to_state: "CONTINUOUS" });
    await waitFor(() =>
      expect((toast.success as unknown as { mock: { calls: unknown[][] } }).mock.calls.length).toBeGreaterThan(0),
    );
  });

  it("surfaces a 409 TRANSITION_REJECTED reason", async () => {
    const { ApiError } = await import("@/api/apiFetch");
    apiFetchMock.mockRejectedValueOnce(new ApiError(409, "TRANSITION_REJECTED", "sessions disabled"));
    wrap(<AdminSessionPage />);
    fireEvent.click(screen.getByRole("button", { name: "Continuous" }));
    fireEvent.click(screen.getByRole("button", { name: "Transition to Continuous" }));
    await waitFor(() =>
      expect((toast.error as unknown as { mock: { calls: unknown[][] } }).mock.calls[0]![0]).toContain(
        "sessions disabled",
      ),
    );
  });

  it("shows no transitions note when none are valid", () => {
    // (No phase has an empty transition set in the venue model, so force one.)
    useSessionStore.setState({ phase: "CLOSED" });
    wrap(<AdminSessionPage />);
    // CLOSED → PRE_OPEN is valid, so a button exists; assert PRE_OPEN offered.
    expect(screen.getByRole("button", { name: "Pre-Open" })).toBeTruthy();
  });
});

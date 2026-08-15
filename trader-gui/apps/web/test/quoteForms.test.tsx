// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const apiFetchMock = vi.fn(async (path: string, _init?: { body?: string }) => {
  if (path.startsWith("/api/v1/quotes/")) return { symbol: "AAPL", status: "PENDING_CANCEL" };
  if (path.startsWith("/api/v1/quotes")) return { id: "mm-aapl-x", status: "PENDING", event: null };
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

import { NewQuoteForm } from "@/components/quotes/NewQuoteForm";
import { QuoteCard } from "@/components/quotes/QuoteCard";
import { useNotificationStore } from "@/store/useNotificationStore";
import { useQuotePrefillStore } from "@/store/useQuotePrefillStore";
import type { ActiveQuote } from "@/types/index";

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

function bodyFor(pathPart: string): Record<string, unknown> {
  const call = apiFetchMock.mock.calls.find(([p]) => String(p).includes(pathPart)) as
    | [string, { body: string }]
    | undefined;
  return JSON.parse(call![1].body);
}

function activeQuote(): ActiveQuote {
  return {
    quote_id: "mm-aapl-1",
    gateway_id: "MM",
    symbol: "AAPL",
    state: "ACTIVE",
    bid_order_id: "b1",
    ask_order_id: "a1",
    bid_price: 149.9,
    ask_price: 150.1,
    bid_qty: 500,
    ask_qty: 500,
    bid_remaining_qty: 200,
    ask_remaining_qty: 500,
    bid_status: "RESTING",
    ask_status: "RESTING",
  };
}

beforeEach(() => {
  cleanup();
  apiFetchMock.mockClear();
  useNotificationStore.setState({ entries: [], unread: 0 });
  useQuotePrefillStore.setState({ prefill: null });
});

describe("NewQuoteForm (§14.2)", () => {
  it("POSTs a two-sided quote with the exact field set", async () => {
    wrap(<NewQuoteForm symbol="AAPL" tickDecimals={2} onDone={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Bid price"), { target: { value: "149.9" } });
    fireEvent.change(screen.getByLabelText("Ask price"), { target: { value: "150.1" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit Quote" }));
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    expect(apiFetchMock.mock.calls.at(-1)![0]).toBe("/api/v1/quotes");
    const body = bodyFor("/api/v1/quotes");
    expect(body).toMatchObject({
      symbol: "AAPL",
      bid_price: 149.9,
      bid_qty: 500,
      ask_price: 150.1,
      ask_qty: 500,
      tif: "DAY",
    });
    expect(typeof body.quote_id).toBe("string");
  });

  it("records the response `id` (not quote_id) in the Event Center", async () => {
    wrap(<NewQuoteForm symbol="AAPL" tickDecimals={2} onDone={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Bid price"), { target: { value: "149.9" } });
    fireEvent.change(screen.getByLabelText("Ask price"), { target: { value: "150.1" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit Quote" }));
    await waitFor(() => expect(useNotificationStore.getState().entries.length).toBe(1));
    expect(useNotificationStore.getState().entries[0]!.title).toContain("mm-aapl-x");
  });

  it("blocks bid >= ask with an inline error and no POST", () => {
    wrap(<NewQuoteForm symbol="AAPL" tickDecimals={2} onDone={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Bid price"), { target: { value: "150.2" } });
    fireEvent.change(screen.getByLabelText("Ask price"), { target: { value: "150.1" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit Quote" }));
    expect(screen.getByText(/Ask price must be strictly greater than bid price/)).toBeTruthy();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("shows the live spread indicator in currency and ticks", () => {
    wrap(<NewQuoteForm symbol="AAPL" tickDecimals={2} onDone={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Bid price"), { target: { value: "149.9" } });
    fireEvent.change(screen.getByLabelText("Ask price"), { target: { value: "150.1" } });
    expect(screen.getByText(/Spread: 0\.20 \(20 ticks\)/)).toBeTruthy();
  });
});

describe("QuoteCard (§14.1)", () => {
  it("renders per-leg price, qty and fill progress from the ActiveQuote", () => {
    wrap(<QuoteCard symbol="AAPL" tickDecimals={2} quote={activeQuote()} />);
    expect(screen.getByText("149.90 × 500")).toBeTruthy();
    // bid filled = 500 - 200 = 300
    expect(screen.getByText("Fill: 300 / 500")).toBeTruthy();
    expect(screen.getByText("ACTIVE")).toBeTruthy();
  });

  it("cancels the quote by symbol after confirmation", async () => {
    wrap(<QuoteCard symbol="AAPL" tickDecimals={2} quote={activeQuote()} />);
    fireEvent.click(screen.getByRole("button", { name: "Cancel AAPL quote" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel quote" }));
    await waitFor(() =>
      expect(apiFetchMock.mock.calls.some(([p]) => String(p) === "/api/v1/quotes/AAPL")).toBe(true),
    );
    const call = apiFetchMock.mock.calls.find(([p]) => String(p) === "/api/v1/quotes/AAPL")!;
    expect((call[1] as { method: string }).method).toBe("DELETE");
  });

  it("opens the New Quote form prefilled when a Re-quote prefill lands", async () => {
    wrap(<QuoteCard symbol="AAPL" tickDecimals={2} quote={activeQuote()} />);
    expect(screen.queryByLabelText("Quote ID")).toBeNull();
    act(() => {
      useQuotePrefillStore.getState().setPrefill({
        symbol: "AAPL",
        bid_price: 149.9,
        bid_qty: 500,
        ask_price: 150.1,
        ask_qty: 500,
        quote_id: "mm-aapl-1",
      });
    });
    await waitFor(() => expect(screen.getByLabelText("Quote ID")).toBeTruthy());
    // Prefilled bid price carried over from the previous quote.
    expect((screen.getByLabelText("Bid price") as HTMLInputElement).value).toBe("149.9");
  });

  it("ignores a prefill aimed at a different symbol", () => {
    wrap(<QuoteCard symbol="MSFT" tickDecimals={2} quote={undefined} />);
    act(() => {
      useQuotePrefillStore.getState().setPrefill({
        symbol: "AAPL",
        bid_price: 1,
        bid_qty: 1,
        ask_price: 2,
        ask_qty: 1,
        quote_id: "x",
      });
    });
    expect(screen.queryByLabelText("Quote ID")).toBeNull();
  });
});

// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const apiFetchMock = vi.fn(async () => ({
  order_id: "ord-abcdef123456",
  client_order_id: null,
  status: "ACKED",
  accepted: true,
  event: null,
}));

vi.mock("@/api/apiFetch", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...(args as [])),
  ApiError: class ApiError extends Error {
    constructor(
      public status = 0,
      public code = "UNKNOWN",
      message = "",
    ) {
      super(message);
      this.name = "ApiError";
    }
  },
}));

import { OrderTicket } from "@/components/orders/OrderTicket";
import { ApiError } from "@/api/apiFetch";
import { useOrderFields } from "@/hooks/useOrderFields";
import { useSessionStore } from "@/store/useSessionStore";
import { useSymbolStore } from "@/store/useSymbolStore";
import { useBookStore } from "@/store/useBookStore";
import { useTicketPrefillStore } from "@/store/useTicketPrefillStore";
import { useNotificationStore } from "@/store/useNotificationStore";
import type { BookEntry } from "@/store/useBookStore";
import type { Symbol } from "@/types/index";

function bookEntry(symbol: string, patch: Partial<BookEntry> = {}): BookEntry {
  return {
    symbol,
    bids: [],
    asks: [],
    depth: null,
    lastPrice: null,
    lastQty: null,
    lastBuyPrice: null,
    lastSellPrice: null,
    recentTrades: [],
    liveVolume: 0,
    tickDecimals: 2,
    auction: null,
    updatedAt: Date.now(),
    ...patch,
  };
}

const SYMBOLS: Symbol[] = [
  { symbol: "AAPL", tick_decimals: 2, prev_close: 150.0, collar_reference_price: null, level: null },
];

function renderTicket(props: Parameters<typeof OrderTicket>[0] = {}): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  render(<OrderTicket lockedSymbol="AAPL" tickDecimals={2} {...props} />, { wrapper: Wrapper });
}

function lastBody(): Record<string, unknown> {
  const call = apiFetchMock.mock.calls.at(-1) as unknown as [string, { body: string }];
  return JSON.parse(call[1].body);
}

beforeEach(() => {
  cleanup();
  apiFetchMock.mockClear();
  useSymbolStore.setState({ symbols: SYMBOLS });
  useBookStore.setState({ books: {} });
  useSessionStore.setState({ phase: "CONTINUOUS" });
  useTicketPrefillStore.setState({ prefill: null });
  useNotificationStore.setState({ entries: [], unread: 0 });
});

describe("useOrderFields (§12.3)", () => {
  it("shows price for LIMIT and hides it for MARKET", () => {
    expect(useOrderFields("LIMIT").price).toBe(true);
    expect(useOrderFields("MARKET").price).toBe(false);
  });

  it("hides TIF for IOC only", () => {
    expect(useOrderFields("IOC").tif).toBe(false);
    expect(useOrderFields("LIMIT").tif).toBe(true);
  });

  it("shows the type-specific fields", () => {
    expect(useOrderFields("STOP").stop_price).toBe(true);
    expect(useOrderFields("ICEBERG").visible_qty).toBe(true);
    expect(useOrderFields("TRAILING_STOP").trail_offset).toBe(true);
  });
});

describe("OrderTicket field visibility per tab", () => {
  it("LIMIT shows Price and hides stop/visible/trail", () => {
    renderTicket();
    expect(screen.getByLabelText("Price")).toBeTruthy();
    expect(screen.queryByLabelText("Stop price")).toBeNull();
    expect(screen.queryByLabelText("Visible quantity")).toBeNull();
    expect(screen.queryByLabelText("Trail offset")).toBeNull();
  });

  it("MARKET hides Price", () => {
    renderTicket();
    fireEvent.click(screen.getByRole("tab", { name: "Market" }));
    expect(screen.queryByLabelText("Price")).toBeNull();
  });

  it("STOP-LIMIT shows both Price and Stop price", () => {
    renderTicket();
    fireEvent.click(screen.getByRole("tab", { name: "Stop-Limit" }));
    expect(screen.getByLabelText("Price")).toBeTruthy();
    expect(screen.getByLabelText("Stop price")).toBeTruthy();
  });

  it("ICEBERG shows Visible quantity", () => {
    renderTicket();
    fireEvent.click(screen.getByRole("tab", { name: "Iceberg" }));
    expect(screen.getByLabelText("Visible quantity")).toBeTruthy();
  });

  it("TRAILING_STOP shows Trail offset and hides Price", () => {
    renderTicket();
    fireEvent.click(screen.getByRole("tab", { name: "Trailing Stop" }));
    expect(screen.getByLabelText("Trail offset")).toBeTruthy();
    expect(screen.queryByLabelText("Price")).toBeNull();
  });

  it("IOC hides Time in force", () => {
    renderTicket();
    fireEvent.click(screen.getByRole("tab", { name: "IOC" }));
    expect(screen.queryByLabelText("Time in force")).toBeNull();
  });
});

describe("OrderTicket validation", () => {
  it("blocks a LIMIT submit with no price and shows an inline error", () => {
    renderTicket();
    fireEvent.click(screen.getByRole("button", { name: "BUY" }));
    expect(screen.getByText("Price required for this order type")).toBeTruthy();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });
});

describe("OrderTicket submit side (§12.9)", () => {
  it("BUY injects side BUY and posts with wait=ack", async () => {
    renderTicket();
    fireEvent.change(screen.getByLabelText("Price"), { target: { value: "150.25" } });
    fireEvent.click(screen.getByRole("button", { name: "BUY" }));
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    const call = apiFetchMock.mock.calls.at(-1) as unknown as [string, unknown];
    expect(call[0]).toBe("/api/v1/orders?wait=ack");
    const body = lastBody();
    expect(body.side).toBe("BUY");
    expect(body.order_type).toBe("LIMIT");
    expect(body.symbol).toBe("AAPL");
    expect(body.price).toBe(150.25);
  });

  it("SELL injects side SELL", async () => {
    renderTicket();
    fireEvent.change(screen.getByLabelText("Price"), { target: { value: "150.25" } });
    fireEvent.click(screen.getByRole("button", { name: "SELL" }));
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    expect(lastBody().side).toBe("SELL");
  });

  it("records an ACK Event Center entry on an accepted order", async () => {
    renderTicket();
    fireEvent.change(screen.getByLabelText("Price"), { target: { value: "150.25" } });
    fireEvent.click(screen.getByRole("button", { name: "BUY" }));
    await waitFor(() => expect(useNotificationStore.getState().entries.length).toBe(1));
    expect(useNotificationStore.getState().entries[0]!.kind).toBe("ACK");
  });

  it("omits smp_action unless explicitly chosen (Gateway default)", async () => {
    renderTicket();
    fireEvent.change(screen.getByLabelText("Price"), { target: { value: "150.25" } });
    fireEvent.click(screen.getByRole("button", { name: "BUY" }));
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    expect(lastBody()).not.toHaveProperty("smp_action");
  });

  it("treats a wait=ack timeout (503) as awaiting-confirmation, not a rejection", async () => {
    apiFetchMock.mockRejectedValueOnce(new ApiError(503, "ENGINE_TIMEOUT", "no ack in time"));
    renderTicket();
    fireEvent.change(screen.getByLabelText("Price"), { target: { value: "150.25" } });
    fireEvent.click(screen.getByRole("button", { name: "BUY" }));
    await waitFor(() => expect(useNotificationStore.getState().entries.length).toBe(1));
    const entry = useNotificationStore.getState().entries[0]!;
    // A submitted-but-unacked order must NOT be reported as REJECT (§12.9 step 6).
    expect(entry.kind).toBe("ACK");
    expect(entry.title).toMatch(/awaiting ACK/);
  });
});

describe("OrderTicket B/S hotkeys (§12.11)", () => {
  it("B submits a BUY when the ticket is not focused on a form field", async () => {
    renderTicket();
    fireEvent.click(screen.getByRole("tab", { name: "Market" }));
    fireEvent.keyDown(document, { key: "b", code: "KeyB" });
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    expect(lastBody().side).toBe("BUY");
    expect(lastBody().order_type).toBe("MARKET");
  });
});

describe("OrderTicket reference-price hint (§12.6)", () => {
  it("uses the live last trade price as the Ref hint", () => {
    useBookStore.setState({ books: { AAPL: bookEntry("AAPL", { lastPrice: 151.4 }) } });
    renderTicket();
    const price = screen.getByLabelText("Price") as HTMLInputElement;
    expect(price.placeholder).toBe("Ref: 151.40");
  });

  it("falls back to the bid/ask mid when no trade has printed", () => {
    useBookStore.setState({
      books: {
        AAPL: bookEntry("AAPL", {
          bids: [{ price: 150.0, qty: 10, count: 1 }],
          asks: [{ price: 150.2, qty: 10, count: 1 }],
        }),
      },
    });
    renderTicket();
    const price = screen.getByLabelText("Price") as HTMLInputElement;
    expect(price.placeholder).toBe("Ref: 150.10");
  });

  it("falls back to prev_close when the book has not streamed yet", () => {
    renderTicket(); // no book set; AAPL prev_close is 150.0
    const price = screen.getByLabelText("Price") as HTMLInputElement;
    expect(price.placeholder).toBe("Ref: 150.00");
  });
});

describe("OrderTicket auction banner (§12.10)", () => {
  it("shows the banner and disables MARKET/FOK/IOC during an auction", () => {
    useSessionStore.setState({ phase: "OPENING_AUCTION" });
    renderTicket();
    expect(screen.getByText(/Auction phase/)).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Market" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("tab", { name: "FOK" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("tab", { name: "IOC" })).toHaveProperty("disabled", true);
  });

  it("greys out BUY/SELL when the market is closed", () => {
    useSessionStore.setState({ phase: "CLOSED" });
    renderTicket();
    expect(screen.getByRole("button", { name: "BUY" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "SELL" })).toHaveProperty("disabled", true);
  });
});

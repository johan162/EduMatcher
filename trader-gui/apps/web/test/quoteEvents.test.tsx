// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, cleanup, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { toast } from "sonner";
import type { WsEnvelope, WsEventType, WsDataByType } from "@/types/index";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

const wsHandlers: Partial<Record<string, (env: unknown) => void>> = {};
vi.mock("@/hooks/useWsEvent", () => ({
  useWsEvent: <T extends WsEventType>(
    type: T,
    handler: (env: WsEnvelope<WsDataByType[T]>) => void,
  ) => {
    wsHandlers[type] = handler as (env: unknown) => void;
  },
}));

import { useQuoteEvents } from "@/hooks/useQuoteEvents";
import { useNotificationStore } from "@/store/useNotificationStore";
import { useQuotePrefillStore } from "@/store/useQuotePrefillStore";
import type { ActiveQuote } from "@/types/index";

const QUOTE: ActiveQuote = {
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
  bid_remaining_qty: 500,
  ask_remaining_qty: 500,
  bid_status: "RESTING",
  ask_status: "RESTING",
};

function Harness() {
  useQuoteEvents();
  return null;
}

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["quotes/bootstrap"], [QUOTE]);
  const invalidateSpy = vi.spyOn(qc, "invalidateQueries");
  render(
    <QueryClientProvider client={qc}>
      <Harness />
    </QueryClientProvider>,
  );
  return { qc, invalidateSpy };
}

const fire = (type: string, data: unknown) => act(() => wsHandlers[type]!({ data }));

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  for (const k of Object.keys(wsHandlers)) delete wsHandlers[k];
  useNotificationStore.setState({ entries: [], unread: 0 });
  useQuotePrefillStore.setState({ prefill: null });
});

describe("useQuoteEvents (§14.1.2)", () => {
  it("fires a fill alert resolving the symbol from the bootstrap cache", () => {
    setup();
    fire("quote.status", { quote_id: "mm-aapl-1", status: "INACTIVE_BID_FILLED" });
    expect(toast.success).toHaveBeenCalled();
    expect((toast.success as unknown as { mock: { calls: unknown[][] } }).mock.calls[0]![0]).toContain(
      "AAPL BID filled",
    );
    const entry = useNotificationStore.getState().entries[0]!;
    expect(entry.kind).toBe("FILL");
    expect(entry.title).toContain("AAPL BID");
  });

  it("Re-quote action prefills the New Quote form from the previous quote", () => {
    setup();
    fire("quote.status", { quote_id: "mm-aapl-1", status: "INACTIVE_ASK_FILLED" });
    const opts = (toast.success as unknown as { mock: { calls: unknown[][] } }).mock.calls[0]![1] as {
      action?: { onClick: () => void };
    };
    expect(opts.action).toBeTruthy();
    act(() => opts.action!.onClick());
    const prefill = useQuotePrefillStore.getState().prefill!;
    expect(prefill).toMatchObject({ symbol: "AAPL", bid_price: 149.9, ask_price: 150.1 });
  });

  it("toasts an error and records a REJECT on quote.ack accepted=false", () => {
    setup();
    fire("quote.ack", { quote_id: "mm-aapl-1", accepted: false, reason: "spread too wide", bid_order_id: "", ask_order_id: "" });
    expect(toast.error).toHaveBeenCalled();
    expect(useNotificationStore.getState().entries[0]!.kind).toBe("REJECT");
  });

  it("does not toast on an accepted quote.ack but records an ACK", () => {
    setup();
    fire("quote.ack", { quote_id: "mm-aapl-1", accepted: true, reason: "", bid_order_id: "b1", ask_order_id: "a1" });
    expect(toast.error).not.toHaveBeenCalled();
    expect(useNotificationStore.getState().entries[0]!.kind).toBe("ACK");
  });

  it("reconciles the quote caches on orders.snapshot (connect/reconnect)", () => {
    const { invalidateSpy } = setup();
    invalidateSpy.mockClear();
    fire("orders.snapshot", { orders: [], positions: {}, quote_legs: [] });
    const keys = invalidateSpy.mock.calls.map((c) => (c[0] as { queryKey: string[] }).queryKey[0]);
    expect(keys).toContain("quotes/bootstrap");
    expect(keys).toContain("quotes/legs");
  });
});

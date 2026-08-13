// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { OrdersBlotter } from "@/components/orders/OrdersBlotter";
import { normalizeOrder } from "@/types/index";
import type { Order } from "@/types/index";

function order(patch: Partial<Order> & { order_id: string }): Order {
  return normalizeOrder({
    symbol: "AAPL",
    side: "BUY",
    order_type: "LIMIT",
    tif: "DAY",
    quantity: 100,
    remaining_qty: 100,
    price: 150,
    status: "NEW",
    ...patch,
  });
}

function renderBlotter(orders: Order[], overrides: Record<string, unknown> = {}) {
  const props = {
    orders,
    tickDecimalsFor: () => 2,
    onOpenDetail: vi.fn(),
    onAmend: vi.fn(),
    onReplace: vi.fn(),
    onCancel: vi.fn(),
    onBulkCancel: vi.fn(),
    ...overrides,
  };
  render(<OrdersBlotter {...props} />);
  return props;
}

beforeEach(() => cleanup());

describe("OrdersBlotter", () => {
  it("shows the empty state when there are no orders", () => {
    renderBlotter([]);
    expect(screen.getByText(/No active orders/)).toBeTruthy();
  });

  it("renders a row with symbol, side and status pill", () => {
    renderBlotter([order({ order_id: "o1" })]);
    expect(screen.getByText("AAPL")).toBeTruthy();
    expect(screen.getByText("BUY")).toBeTruthy();
    expect(screen.getByText("NEW")).toBeTruthy();
  });

  it("row click opens the detail drawer", () => {
    const props = renderBlotter([order({ order_id: "o1" })]);
    fireEvent.click(screen.getByText("AAPL"));
    expect(props.onOpenDetail).toHaveBeenCalledWith("o1");
  });

  it("cancel button calls onCancel and does not open the drawer", () => {
    const props = renderBlotter([order({ order_id: "o1" })]);
    fireEvent.click(screen.getByLabelText("Cancel order o1"));
    expect(props.onCancel).toHaveBeenCalledTimes(1);
    const cancelled = (props.onCancel as ReturnType<typeof vi.fn>).mock.calls[0]?.[0] as Order;
    expect(cancelled.order_id).toBe("o1");
    expect(props.onOpenDetail).not.toHaveBeenCalled();
  });

  it("amend/replace buttons are disabled for a terminal order", () => {
    renderBlotter([order({ order_id: "o1", status: "FILLED", remaining_qty: 0 })]);
    expect(screen.getByLabelText("Amend order o1")).toHaveProperty("disabled", true);
    expect(screen.getByLabelText("Replace order o1")).toHaveProperty("disabled", true);
  });

  it("selecting rows reveals a bulk-cancel bar that reports the ids", () => {
    const props = renderBlotter([order({ order_id: "o1" }), order({ order_id: "o2" })]);
    fireEvent.click(screen.getByLabelText("Select order o1"));
    expect(screen.getByText(/1 order selected/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel all selected" }));
    expect(props.onBulkCancel).toHaveBeenCalledWith(["o1"]);
  });
});

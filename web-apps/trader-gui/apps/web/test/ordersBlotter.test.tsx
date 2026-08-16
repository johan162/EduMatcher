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

  it("single click selects the row (does not open the drawer)", () => {
    const props = renderBlotter([order({ order_id: "o1" })]);
    fireEvent.click(screen.getByText("AAPL"));
    expect(props.onOpenDetail).not.toHaveBeenCalled();
    expect(screen.getByText(/1 order selected/)).toBeTruthy();
  });

  it("double-click opens the detail drawer (§13.1.3)", () => {
    const props = renderBlotter([order({ order_id: "o1" })]);
    fireEvent.doubleClick(screen.getByText("AAPL"));
    expect(props.onOpenDetail).toHaveBeenCalledWith("o1");
  });

  it("Enter opens the drawer; Delete cancels the selection (§13.1.3)", () => {
    const props = renderBlotter([order({ order_id: "o1" })]);
    const row = screen.getByText("AAPL").closest("tr")!;
    fireEvent.keyDown(row, { key: "Enter" });
    expect(props.onOpenDetail).toHaveBeenCalledWith("o1");
    fireEvent.click(screen.getByText("AAPL")); // select it
    fireEvent.keyDown(row, { key: "Delete" });
    expect(props.onBulkCancel).toHaveBeenCalledWith(["o1"]);
  });

  it("ArrowDown / ArrowUp move focus between rows without changing selection (§21)", () => {
    renderBlotter([order({ order_id: "o1" }), order({ order_id: "o2" })]);
    const [r1, r2] = screen.getAllByText("AAPL").map((c) => c.closest("tr")!);
    r1!.focus();
    fireEvent.keyDown(r1!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(r2);
    fireEvent.keyDown(r2!, { key: "ArrowUp" });
    expect(document.activeElement).toBe(r1);
    // Focus moved, but nothing was selected — the bulk bar never appeared.
    expect(screen.queryByText(/selected/)).toBeNull();
  });

  it("ArrowUp on the first row and ArrowDown on the last are no-ops (§21)", () => {
    renderBlotter([order({ order_id: "o1" }), order({ order_id: "o2" })]);
    const [r1, r2] = screen.getAllByText("AAPL").map((c) => c.closest("tr")!);
    r1!.focus();
    fireEvent.keyDown(r1!, { key: "ArrowUp" });
    expect(document.activeElement).toBe(r1);
    r2!.focus();
    fireEvent.keyDown(r2!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(r2);
  });

  it("Ctrl+A selects every cancellable row, skipping terminal ones (§21)", () => {
    const props = renderBlotter([
      order({ order_id: "o1" }),
      order({ order_id: "o2", status: "FILLED", remaining_qty: 0 }),
      order({ order_id: "o3" }),
    ]);
    const row = screen.getAllByText("AAPL")[0]!.closest("tr")!;
    fireEvent.keyDown(row, { key: "a", ctrlKey: true });
    expect(screen.getByText(/2 orders selected/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel all selected" }));
    expect(props.onBulkCancel).toHaveBeenCalledWith(["o1", "o3"]);
  });

  it("Meta+A selects all as well (macOS)", () => {
    renderBlotter([order({ order_id: "o1" }), order({ order_id: "o2" })]);
    const row = screen.getAllByText("AAPL")[0]!.closest("tr")!;
    fireEvent.keyDown(row, { key: "a", metaKey: true });
    expect(screen.getByText(/2 orders selected/)).toBeTruthy();
  });

  it("shift-click selects a contiguous range (§13.1.3)", () => {
    const props = renderBlotter([order({ order_id: "o1" }), order({ order_id: "o2" })]);
    const [r1, r2] = screen.getAllByText("AAPL");
    fireEvent.click(r1!); // anchor
    fireEvent.click(r2!, { shiftKey: true });
    expect(screen.getByText(/2 orders selected/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel all selected" }));
    expect(props.onBulkCancel).toHaveBeenCalledWith(["o1", "o2"]);
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

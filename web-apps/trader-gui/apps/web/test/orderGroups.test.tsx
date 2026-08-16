// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { computeOrderGroups } from "@/lib/orderGroups";
import { OrderGroupsPanel } from "@/components/orders/OrderGroupsPanel";
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

beforeEach(() => cleanup());

describe("computeOrderGroups (§13.3)", () => {
  it("groups OCO legs and counts live vs terminal", () => {
    const orders = [
      order({ order_id: "a", oco_group_id: "oco-1", status: "NEW" }),
      order({ order_id: "b", oco_group_id: "oco-1", status: "CANCELLED" }),
    ];
    const groups = computeOrderGroups(orders);
    expect(groups).toHaveLength(1);
    expect(groups[0]).toMatchObject({ kind: "OCO", id: "oco-1", total: 2, live: 1 });
    expect(groups[0]!.statusLabel).toMatch(/1 live/);
    expect(groups[0]!.statusLabel).toMatch(/cancelled/);
  });

  it("groups combo legs under combo_parent_id", () => {
    const groups = computeOrderGroups([
      order({ order_id: "c", combo_parent_id: "combo-9", symbol: "AAPL" }),
      order({ order_id: "d", combo_parent_id: "combo-9", symbol: "MSFT" }),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0]).toMatchObject({ kind: "COMBO", id: "combo-9", total: 2 });
  });

  it("ignores ungrouped orders and sorts OCO before COMBO", () => {
    const groups = computeOrderGroups([
      order({ order_id: "x" }), // ungrouped
      order({ order_id: "c", combo_parent_id: "combo-1" }),
      order({ order_id: "o", oco_group_id: "oco-1" }),
    ]);
    expect(groups.map((g) => g.kind)).toEqual(["OCO", "COMBO"]);
  });

  it("reports a uniform group by its single status", () => {
    const groups = computeOrderGroups([
      order({ order_id: "a", oco_group_id: "g", status: "NEW" }),
      order({ order_id: "b", oco_group_id: "g", status: "NEW" }),
    ]);
    expect(groups[0]!.statusLabel).toBe("new");
  });
});

describe("OrderGroupsPanel (§13.3)", () => {
  it("renders nothing when there are no groups", () => {
    const { container } = render(
      <OrderGroupsPanel orders={[order({ order_id: "x" })]} onCancelGroup={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders a group row and fires Cancel group for the live members", () => {
    const onCancelGroup = vi.fn();
    render(
      <OrderGroupsPanel
        orders={[
          order({ order_id: "a", oco_group_id: "oco-1", status: "NEW" }),
          order({ order_id: "b", oco_group_id: "oco-1", status: "NEW" }),
        ]}
        onCancelGroup={onCancelGroup}
      />,
    );
    expect(screen.getByText("OCO")).toBeTruthy();
    expect(screen.getByText("oco-1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel OCO group oco-1" }));
    expect(onCancelGroup).toHaveBeenCalledTimes(1);
    expect(onCancelGroup.mock.calls[0]![0]).toMatchObject({ kind: "OCO", id: "oco-1" });
  });

  it("disables Cancel group when no members are live", () => {
    render(
      <OrderGroupsPanel
        orders={[
          order({ order_id: "a", oco_group_id: "oco-2", status: "FILLED", remaining_qty: 0 }),
          order({ order_id: "b", oco_group_id: "oco-2", status: "CANCELLED" }),
        ]}
        onCancelGroup={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Cancel OCO group oco-2" })).toHaveProperty(
      "disabled",
      true,
    );
  });
});

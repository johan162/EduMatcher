// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { EventCenter } from "@/components/notifications/EventCenter";
import { SettingsPopover } from "@/components/shared/SettingsPopover";
import { useNotificationStore, type NotificationEntry } from "@/store/useNotificationStore";
import { useUiStore } from "@/store/useUiStore";
import { useSettingsStore } from "@/store/useSettingsStore";

function entry(patch: Partial<NotificationEntry> & { id: string }): NotificationEntry {
  return {
    ts: Date.now(),
    kind: "FILL",
    title: "AAPL filled",
    detail: "100 @ 150",
    read: false,
    ...patch,
  };
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  useNotificationStore.setState({ entries: [], unread: 0 });
  useUiStore.setState({ eventCenterOpen: false, orderDetailId: null });
  useSettingsStore.setState({ confirmCancellations: true });
});

describe("useUiStore", () => {
  it("openOrderDetail sets the id and closes the Event Center so they don't stack", () => {
    useUiStore.setState({ eventCenterOpen: true });
    useUiStore.getState().openOrderDetail("o1");
    expect(useUiStore.getState().orderDetailId).toBe("o1");
    expect(useUiStore.getState().eventCenterOpen).toBe(false);
  });
});

describe("EventCenter (§20.2)", () => {
  it("marks all entries read on open (clears the unread badge)", () => {
    useNotificationStore.setState({
      entries: [entry({ id: "1" }), entry({ id: "2", kind: "REJECT" })],
      unread: 2,
    });
    render(<EventCenter />);
    expect(useNotificationStore.getState().unread).toBe(0);
    expect(useNotificationStore.getState().entries.every((e) => e.read)).toBe(true);
  });

  it("filters entries by kind", () => {
    useNotificationStore.setState({
      entries: [
        entry({ id: "1", kind: "FILL", title: "AAPL filled" }),
        entry({ id: "2", kind: "REJECT", title: "MSFT rejected" }),
      ],
      unread: 2,
    });
    render(<EventCenter />);
    expect(screen.getByText("AAPL filled")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "REJECT" }));
    expect(screen.queryByText("AAPL filled")).toBeNull();
    expect(screen.getByText("MSFT rejected")).toBeTruthy();
  });

  it("deep-links a fill entry to the Order Detail drawer", () => {
    useNotificationStore.setState({
      entries: [entry({ id: "1", kind: "FILL", title: "AAPL filled", orderId: "order-123" })],
      unread: 1,
    });
    render(<EventCenter />);
    fireEvent.click(screen.getByText("AAPL filled"));
    expect(useUiStore.getState().orderDetailId).toBe("order-123");
  });

  it("does not deep-link an entry without an orderId", () => {
    useNotificationStore.setState({
      entries: [entry({ id: "1", kind: "SESSION", title: "Session → CONTINUOUS", detail: "" })],
      unread: 1,
    });
    render(<EventCenter />);
    fireEvent.click(screen.getByText("Session → CONTINUOUS"));
    expect(useUiStore.getState().orderDetailId).toBeNull();
  });

  it("Clear empties the buffer", () => {
    useNotificationStore.setState({ entries: [entry({ id: "1" })], unread: 1 });
    render(<EventCenter />);
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(useNotificationStore.getState().entries).toHaveLength(0);
    expect(screen.getByText(/No events yet this session/)).toBeTruthy();
  });
});

describe("SettingsPopover (§20.3)", () => {
  it("toggles the confirm-cancellations setting", () => {
    render(<SettingsPopover />);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    const checkbox = screen.getByLabelText("Confirm order and quote cancellations") as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
    fireEvent.click(checkbox);
    expect(useSettingsStore.getState().confirmCancellations).toBe(false);
  });
});

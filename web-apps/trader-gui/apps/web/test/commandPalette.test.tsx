// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";

const navigateMock = vi.fn();
vi.mock("react-router-dom", () => ({ useNavigate: () => navigateMock }));

import { CommandPalette } from "@/components/command/CommandPalette";
import { useAuthStore } from "@/store/useAuthStore";
import { useSymbolStore } from "@/store/useSymbolStore";
import { useBookStore } from "@/store/useBookStore";
import { useWatchlistStore } from "@/store/useWatchlistStore";
import { useSymbolDetailStore } from "@/store/useSymbolDetailStore";
import { useActiveSymbolStore } from "@/store/useActiveSymbolStore";
import { useUiStore } from "@/store/useUiStore";
import type { Symbol } from "@/types/index";

const SYMBOLS: Symbol[] = [
  { symbol: "AAPL", tick_decimals: 2, prev_close: 150, collar_reference_price: null, level: null },
  { symbol: "MSFT", tick_decimals: 2, prev_close: 410, collar_reference_price: null, level: null },
];

const closeMock = vi.fn();

function input() {
  return screen.getByLabelText("Search symbols and actions");
}

beforeEach(() => {
  cleanup();
  navigateMock.mockClear();
  closeMock.mockClear();
  useAuthStore.setState({ role: "TRADER" });
  useSymbolStore.setState({ symbols: SYMBOLS });
  useBookStore.setState({ books: {} });
  useWatchlistStore.setState({ symbols: [] });
  useSymbolDetailStore.setState({ isOpen: false });
  useActiveSymbolStore.setState({ activeSymbol: null });
  useUiStore.setState({ closeCommandPalette: closeMock });
});

describe("CommandPalette (§21.1)", () => {
  it("lists symbols and role-aware actions", () => {
    render(<CommandPalette />);
    expect(screen.getByText("AAPL")).toBeTruthy();
    expect(screen.getByText("MSFT")).toBeTruthy();
    expect(screen.getByText("Trading Workspace")).toBeTruthy();
    expect(screen.getByText("Flatten All positions")).toBeTruthy();
  });

  it("filters by query across symbols and actions", () => {
    render(<CommandPalette />);
    fireEvent.change(input(), { target: { value: "MSFT" } });
    expect(screen.getByText("MSFT")).toBeTruthy();
    expect(screen.queryByText("AAPL")).toBeNull();
    expect(screen.queryByText("Trading Workspace")).toBeNull();

    fireEvent.change(input(), { target: { value: "positions" } });
    expect(screen.getByText("Positions")).toBeTruthy();
    expect(screen.queryByText("MSFT")).toBeNull();
  });

  it("Enter on a symbol opens Symbol Detail and sets the active symbol", () => {
    render(<CommandPalette />);
    // First item is the AAPL symbol (activeIndex defaults to 0).
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(useSymbolDetailStore.getState().isOpen).toBe(true);
    expect(useActiveSymbolStore.getState().activeSymbol).toBe("AAPL");
    expect(closeMock).toHaveBeenCalled();
  });

  it("arrow-down + Enter navigates to a selected action", () => {
    render(<CommandPalette />);
    fireEvent.change(input(), { target: { value: "workspace" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(navigateMock).toHaveBeenCalledWith("/workspace");
    expect(closeMock).toHaveBeenCalled();
  });

  it("the star toggles watchlist membership without selecting the symbol", () => {
    render(<CommandPalette />);
    fireEvent.click(screen.getByRole("button", { name: "Watch AAPL" }));
    expect(useWatchlistStore.getState().symbols).toContain("AAPL");
    // Toggling the star must not open Symbol Detail.
    expect(useSymbolDetailStore.getState().isOpen).toBe(false);
  });

  it("Escape closes the palette", () => {
    render(<CommandPalette />);
    fireEvent.keyDown(input(), { key: "Escape" });
    expect(closeMock).toHaveBeenCalled();
  });
});

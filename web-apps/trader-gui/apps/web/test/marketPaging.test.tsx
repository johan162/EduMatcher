// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { SortingState } from "@tanstack/react-table";
import { MarketTable } from "@/components/market/MarketTable";
import { pagination, TablePager } from "@/components/shared/TablePager";
import type { MarketRow } from "@/lib/marketRows";

// jsdom does no layout: give the scroll container a viewport so the
// virtualizer renders rows (600px ≈ 21 rows, more than a 10-row page).
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, value: 600 });
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, value: 800 });
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

afterEach(cleanup);

function row(symbol: string): MarketRow {
  return {
    symbol,
    tickDecimals: 2,
    bid: null,
    ask: null,
    last: null,
    open: null,
    changePct: null,
    volume: null,
    halted: false,
    haltLevel: null,
    auctionPrice: null,
    auctionIndicative: false,
    watched: false,
  };
}

// S01..S25, handed over out of order: the table sorts before it pages.
const ROWS = Array.from({ length: 25 }, (_, i) => row(`S${String(25 - i).padStart(2, "0")}`));

function shownSymbols(): string[] {
  return screen
    .getAllByRole("row")
    .slice(1) // header
    .map((r) => r.querySelector("td:nth-child(2)")?.textContent ?? "")
    .filter(Boolean);
}

function renderTable(sorting: SortingState, page?: { index: number; size: number }) {
  render(
    <MarketTable
      rows={ROWS}
      sorting={sorting}
      onSortingChange={() => {}}
      activeSymbol={null}
      showAuction={false}
      onSelect={() => {}}
      onToggleWatch={() => {}}
      page={page}
    />,
  );
}

describe("Market Overview paging", () => {
  it("shows one page of the sorted rows", () => {
    renderTable([{ id: "symbol", desc: false }], { index: 1, size: 10 });
    expect(shownSymbols()).toEqual([
      "S11",
      "S12",
      "S13",
      "S14",
      "S15",
      "S16",
      "S17",
      "S18",
      "S19",
      "S20",
    ]);
  });

  it("pages the whole sorted list, not the rows as given", () => {
    renderTable([{ id: "symbol", desc: true }], { index: 0, size: 10 });
    expect(shownSymbols()[0]).toBe("S25");
    expect(shownSymbols()).toHaveLength(10);
  });

  it("shows a short last page and, with no page, every row the viewport holds", () => {
    renderTable([{ id: "symbol", desc: false }], { index: 2, size: 10 });
    expect(shownSymbols()).toEqual(["S21", "S22", "S23", "S24", "S25"]);
    cleanup();
    renderTable([{ id: "symbol", desc: false }]);
    expect(shownSymbols()[0]).toBe("S01");
    expect(shownSymbols().length).toBeGreaterThan(10);
  });

  it("holds the requested page inside the page count, and 'All rows' is one page", () => {
    expect(pagination(25, 10, 0)).toEqual({ pageCount: 3, pageIndex: 0 });
    expect(pagination(25, 10, 7)).toEqual({ pageCount: 3, pageIndex: 2 });
    expect(pagination(0, 10, 0)).toEqual({ pageCount: 1, pageIndex: 0 });
    expect(pagination(25, 0, 4)).toEqual({ pageCount: 1, pageIndex: 0 });
  });

  it("offers 10/30/50/100/All rows and steps between pages", () => {
    const onPage = vi.fn();
    const onPageSize = vi.fn();
    render(
      <TablePager
        pageIndex={0}
        pageCount={3}
        pageSize={30}
        onPage={onPage}
        onPageSize={onPageSize}
      />,
    );
    const select = screen.getByRole("combobox", { name: "Rows per page" });
    expect([...select.querySelectorAll("option")].map((o) => o.textContent)).toEqual([
      "10 rows",
      "30 rows",
      "50 rows",
      "100 rows",
      "All rows",
    ]);
    expect(screen.getByText("Page 1/3")).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "Previous page" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(onPage).toHaveBeenCalledWith(1);
    fireEvent.change(select, { target: { value: "0" } });
    expect(onPageSize).toHaveBeenCalledWith(0);
  });
});

// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { DataTable, type Column } from "@/components/shared/DataTable";
import { Stat } from "@/components/shared/Ui";
import { useAuthStore } from "@/store/useAuthStore";
import { DEFAULT_PAGE_SIZE, usePageSizeStore } from "@/store/usePageSizeStore";
import { example, renderApp, signIn, stubApi } from "./helpers";

/**
 * CG18: the shared table pages its rows (10/30/50/100/All, one remembered
 * choice), shows which headers sort, and keeps its place sensibly while the
 * rows under it change.
 */

interface Row {
  id: number;
  name: string;
}

const COLUMNS: Column<Row>[] = [
  { id: "id", header: "Id", title: "The row number", cell: (r) => String(r.id), sortValue: (r) => r.id },
  { id: "name", header: "Name", cell: (r) => r.name },
];

function rows(n: number): Row[] {
  return Array.from({ length: n }, (_, i) => ({ id: i + 1, name: `row ${i + 1}` }));
}

function table(list: Row[], sortable?: boolean) {
  return (
    <DataTable caption="Test rows" columns={COLUMNS} rows={list} rowKey={(r) => String(r.id)} sortable={sortable} />
  );
}

/** The ids of the body rows on screen, in order. */
function shownIds(): number[] {
  return within(screen.getByRole("table"))
    .getAllByRole("row")
    .slice(1)
    .map((tr) => Number(tr.querySelector("td")!.textContent));
}

beforeEach(() => {
  localStorage.clear();
  usePageSizeStore.setState({ pageSize: 10 });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("DataTable paging", () => {
  it("shows one page of rows and moves between pages", () => {
    render(table(rows(25)));
    expect(screen.getByText("Page 1/3")).toBeTruthy();
    expect(shownIds()).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByText("Page 2/3")).toBeTruthy();
    expect(screen.getByText("Rows 11–20 of 25")).toBeTruthy();
    expect(shownIds()).toEqual([11, 12, 13, 14, 15, 16, 17, 18, 19, 20]);
    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    expect(shownIds()[0]).toBe(1);
  });

  it("holds the last page when a refresh leaves fewer rows", () => {
    const view = render(table(rows(25)));
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(shownIds()).toEqual([21, 22, 23, 24, 25]);
    view.rerender(table(rows(12)));
    expect(screen.getByText("Page 2/2")).toBeTruthy();
    expect(shownIds()).toEqual([11, 12]);
    // The requested page is kept: when the rows come back, so does page 3.
    view.rerender(table(rows(25)));
    expect(screen.getByText("Page 3/3")).toBeTruthy();
  });

  it("returns to the first page when the sort changes", () => {
    render(table(rows(25)));
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    fireEvent.click(screen.getByRole("button", { name: /Id/ }));
    expect(screen.getByText("Page 1/3")).toBeTruthy();
    expect(shownIds()[0]).toBe(25);
  });

  it("returns to the first page when the page size changes", () => {
    render(table(rows(120)));
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Rows per page" }), { target: { value: "50" } });
    expect(screen.getByText("Page 1/3")).toBeTruthy();
    expect(shownIds()).toHaveLength(50);
  });

  it("offers 10, 30, 50, 100 and All, and All shows every row", () => {
    render(table(rows(120)));
    const select = screen.getByRole("combobox", { name: "Rows per page" });
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "10 rows",
      "30 rows",
      "50 rows",
      "100 rows",
      "All rows",
    ]);
    fireEvent.change(select, { target: { value: "0" } });
    expect(shownIds()).toHaveLength(120);
    // Still offered, so All can be undone.
    expect(screen.getByRole("combobox", { name: "Rows per page" })).toBeTruthy();
  });

  it("remembers the page size for every table, across remounts", () => {
    const view = render(table(rows(120)));
    fireEvent.change(screen.getByRole("combobox", { name: "Rows per page" }), { target: { value: "50" } });
    view.unmount();
    render(table(rows(120)));
    expect(shownIds()).toHaveLength(50);
    expect(JSON.parse(localStorage.getItem("clearing-page-size") ?? "{}").state.pageSize).toBe(50);
  });

  it("defaults to 30 rows per page", () => {
    expect(DEFAULT_PAGE_SIZE).toBe(30);
  });

  it("draws no pager when the rows fit the smallest page", () => {
    render(table(rows(10)));
    expect(screen.queryByRole("navigation", { name: /pages/ })).toBeNull();
    expect(shownIds()).toHaveLength(10);
  });
});

describe("DataTable headers", () => {
  it("marks every sortable header with a sort icon, and only those", () => {
    render(table(rows(3)));
    const [id, name] = within(screen.getByRole("table")).getAllByRole("columnheader");
    expect(id!.querySelector("[data-sort-icon]")).not.toBeNull();
    expect(name!.querySelector("[data-sort-icon]")).toBeNull();
  });

  it("has no sort buttons when the table is not sortable", () => {
    render(table(rows(3), false));
    expect(within(screen.getByRole("table")).queryAllByRole("button")).toHaveLength(0);
    expect(screen.getByRole("table").querySelector("[data-sort-icon]")).toBeNull();
  });

  it("underlines a header that has a tooltip, and not one without", () => {
    render(table(rows(3)));
    const [id, name] = within(screen.getByRole("table")).getAllByRole("columnheader");
    expect(id!.getAttribute("title")).toBe("The row number");
    expect(id!.querySelector("[data-has-tooltip]")).not.toBeNull();
    expect(name!.querySelector("[data-has-tooltip]")).toBeNull();
  });
});

describe("Stat tooltip", () => {
  it("carries its explanation on the label", () => {
    render(<Stat label="Open positions" value={3} title="Positions with a non-zero quantity" />);
    const label = screen.getByText("Open positions");
    expect(label.getAttribute("title")).toBe("Positions with a non-zero quantity");
    expect(label.hasAttribute("data-has-tooltip")).toBe(true);
  });
});

describe("Paging on a screen", () => {
  const EVENTS = "/api/v1/clearing/session-events";

  function manyEvents(n: number): Record<string, unknown> {
    const base = example<{ events: Record<string, unknown>[] }>(EVENTS);
    const one = base.events[0]!;
    const events = Array.from({ length: n }, (_, i) => ({ ...one, id: i + 1 }));
    return { ...base, events, count: n, has_more: false };
  }

  it("goes back to the first page when the filters change", async () => {
    useAuthStore.getState().logout();
    signIn("ADMIN", "OPS01");
    stubApi({ [EVENTS]: () => manyEvents(25) });
    renderApp("/events");
    await screen.findByText("Page 1/3");
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByText("Page 2/3")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "PHASE" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(screen.getByText("Page 1/3")).toBeTruthy());
  });
});

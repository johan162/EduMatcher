// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { cleanup, render, screen, fireEvent, within } from "@testing-library/react";
import { NewsPanel } from "@/components/news/NewsPanel";
import { newsMatches, resolutions } from "@/lib/news";
import { NEWS_KEPT, useNewsStore } from "@/store/useNewsStore";
import type { NewsEvent } from "@/types";

function news(over: Partial<NewsEvent>): NewsEvent {
  return {
    id: "N1",
    ts_ns: 1_700_000_000_000_000_000,
    scope: "SYMBOL",
    targets: ["AAPL"],
    kind: "EARNINGS",
    status: "CONFIRMED",
    headline: "AAPL beats",
    sentiment: 0.5,
    related_id: "",
    ...over,
  };
}

const SECTOR_OF = { AAPL: "TECH", MSFT: "TECH", XOM: "ENERGY" };

describe("newsMatches", () => {
  it("matches a symbol's own, its sector's and the market's news", () => {
    expect(newsMatches(news({}), "aapl", SECTOR_OF)).toBe(true);
    expect(newsMatches(news({ targets: ["MSFT"] }), "AAPL", SECTOR_OF)).toBe(false);
    expect(newsMatches(news({ scope: "SECTOR", targets: ["TECH"] }), "AAPL", SECTOR_OF)).toBe(true);
    expect(newsMatches(news({ scope: "SECTOR", targets: ["ENERGY"] }), "AAPL", SECTOR_OF)).toBe(
      false,
    );
    expect(newsMatches(news({ scope: "MARKET", targets: [] }), "XOM", SECTOR_OF)).toBe(true);
  });

  it("matches a sector's own news and its symbols' news", () => {
    expect(newsMatches(news({ targets: ["MSFT"] }), "TECH", SECTOR_OF)).toBe(true);
    expect(newsMatches(news({ targets: ["XOM"] }), "TECH", SECTOR_OF)).toBe(false);
    expect(newsMatches(news({ scope: "SECTOR", targets: ["TECH"] }), "tech", SECTOR_OF)).toBe(true);
  });

  it("matches everything with no filter and nothing for an unknown name", () => {
    expect(newsMatches(news({}), "  ", SECTOR_OF)).toBe(true);
    expect(newsMatches(news({}), "ZZZ", SECTOR_OF)).toBe(false);
  });
});

describe("resolutions", () => {
  it("maps a rumour to how it ended", () => {
    const items = [
      news({ id: "N2", status: "RETRACTED", related_id: "N1" }),
      news({ id: "N1", status: "RUMOUR" }),
    ];
    expect(resolutions(items)).toEqual({ N1: "RETRACTED" });
  });
});

describe("useNewsStore", () => {
  beforeEach(() => useNewsStore.setState({ items: [], sectorOf: {} }));

  it("loads oldest-first snapshots newest first, dedupes and caps live adds", () => {
    useNewsStore
      .getState()
      .load({ news: [news({ id: "A" }), news({ id: "B" })], sectors: { TECH: ["AAPL"] } });
    expect(useNewsStore.getState().items.map((n) => n.id)).toEqual(["B", "A"]);
    expect(useNewsStore.getState().sectorOf).toEqual({ AAPL: "TECH" });
    useNewsStore.getState().add(news({ id: "B" }));
    expect(useNewsStore.getState().items).toHaveLength(2);
    for (let i = 0; i < NEWS_KEPT + 5; i++) useNewsStore.getState().add(news({ id: `X${i}` }));
    expect(useNewsStore.getState().items).toHaveLength(NEWS_KEPT);
    expect(useNewsStore.getState().items[0]!.id).toBe(`X${NEWS_KEPT + 4}`);
  });
});

describe("NewsPanel", () => {
  afterEach(cleanup);
  beforeEach(() => {
    useNewsStore.setState({
      items: [
        news({ id: "N3", status: "RETRACTED", related_id: "N1", headline: "AAPL takeover talk" }),
        news({
          id: "N2",
          scope: "SECTOR",
          targets: ["ENERGY"],
          headline: "Oil slumps",
          sentiment: -0.7,
        }),
        news({
          id: "N1",
          status: "RUMOUR",
          credibility: 0.4,
          headline: "Rumour: AAPL takeover talk",
        }),
      ],
      sectorOf: SECTOR_OF,
    });
  });

  it("badges rumours and strikes through a retracted rumour and its retraction", () => {
    render(<NewsPanel />);
    const rows = screen.getAllByTestId("news-row");
    expect(rows).toHaveLength(3);
    expect(within(rows[2]!).getByText("RUMOUR 40%")).toBeTruthy();
    expect(within(rows[0]!).getByText("RETRACTED")).toBeTruthy();
    expect(within(rows[2]!).getByText("Rumour: AAPL takeover talk").className).toContain(
      "line-through",
    );
    expect(within(rows[0]!).getByText("AAPL takeover talk").className).toContain("line-through");
    expect(within(rows[1]!).getByText("Oil slumps").className).not.toContain("line-through");
    expect(within(rows[1]!).getByText("Oil slumps").className).toContain("text-down");
  });

  it("filters by symbol or sector", () => {
    render(<NewsPanel />);
    const input = screen.getByLabelText("Filter news by symbol or sector");
    fireEvent.change(input, { target: { value: "XOM" } });
    expect(screen.getAllByTestId("news-row")).toHaveLength(1);
    fireEvent.change(input, { target: { value: "tech" } });
    expect(screen.getAllByTestId("news-row")).toHaveLength(2);
    fireEvent.change(input, { target: { value: "NOPE" } });
    expect(screen.getByText("No headlines match.")).toBeTruthy();
  });

  it("says when there is no news at all", () => {
    useNewsStore.setState({ items: [], sectorOf: {} });
    render(<NewsPanel />);
    expect(screen.getByText(/No news yet/)).toBeTruthy();
  });
});

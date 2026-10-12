// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { NewsEvent, NewsSnapshot } from "@edumatcher/terminal-types";
import { newsMatches, resolutions, sectorIndex } from "../src/lib/news.js";

const fetched: { snapshot: NewsSnapshot } = { snapshot: { news: [], sectors: {} } };
vi.mock("../src/lib/api.js", () => ({
  api: { news: vi.fn(async () => fetched.snapshot) },
}));

const { NewsView, NEWS_POLL_MS } = await import("../src/views/News.js");

function news(over: Partial<NewsEvent>): NewsEvent {
  return {
    id: "N1",
    ts_ns: 1_785_000_000_000_000_000,
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

const SECTOR_OF = sectorIndex({ TECH: ["AAPL", "MSFT"], ENERGY: ["XOM"] });

describe("news lib", () => {
  it("matches a symbol's, its sector's and the market's news", () => {
    expect(newsMatches(news({}), "aapl", SECTOR_OF)).toBe(true);
    expect(newsMatches(news({ scope: "SECTOR", targets: ["TECH"] }), "AAPL", SECTOR_OF)).toBe(true);
    expect(newsMatches(news({ scope: "SECTOR", targets: ["ENERGY"] }), "AAPL", SECTOR_OF)).toBe(false);
    expect(newsMatches(news({ targets: ["MSFT"] }), "TECH", SECTOR_OF)).toBe(true);
    expect(newsMatches(news({ scope: "MARKET", targets: [] }), "XOM", SECTOR_OF)).toBe(true);
    expect(newsMatches(news({}), "ZZZ", SECTOR_OF)).toBe(false);
  });

  it("maps a rumour to how it ended", () => {
    expect(resolutions([news({ id: "N2", status: "CONFIRMED", related_id: "N1" })])).toEqual({
      N1: "CONFIRMED",
    });
  });
});

describe("NewsView", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    fetched.snapshot = { news: [], sectors: {} };
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("polls, shows newest first, badges rumours and strikes retracted ones", async () => {
    render(<NewsView />);
    await act(async () => {});
    expect(screen.getByText(/No news yet/)).toBeTruthy();

    fetched.snapshot = {
      news: [
        news({ id: "N1", status: "RUMOUR", credibility: 0.3, headline: "Rumour: AAPL bid" }),
        news({ id: "N2", scope: "SECTOR", targets: ["ENERGY"], headline: "Oil slumps", sentiment: -0.6 }),
        news({ id: "N3", status: "RETRACTED", related_id: "N1", headline: "AAPL bid" }),
      ],
      sectors: { TECH: ["AAPL"], ENERGY: ["XOM"] },
    };
    await act(async () => {
      vi.advanceTimersByTime(NEWS_POLL_MS);
    });
    const rows = screen.getAllByTestId("news-row");
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("AAPL bid"),
      expect.stringContaining("Oil slumps"),
      expect.stringContaining("Rumour: AAPL bid"),
    ]);
    expect(within(rows[2]!).getByText("RUMOUR 30%")).toBeTruthy();
    expect(within(rows[2]!).getByText("Rumour: AAPL bid").className).toContain("line-through");
    expect(within(rows[0]!).getByText("RETRACTED")).toBeTruthy();
    expect(within(rows[1]!).getByText("Oil slumps").className).toContain("text-down");

    fireEvent.change(screen.getByLabelText("Filter news by symbol or sector"), { target: { value: "xom" } });
    expect(screen.getAllByTestId("news-row")).toHaveLength(1);
  });
});

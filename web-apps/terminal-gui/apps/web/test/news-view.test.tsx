// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { NewsEvent, NewsSnapshot } from "@edumatcher/terminal-types";
import type { NewsQuery } from "../src/lib/api.js";
import { newsWindowStart, sectorIndex } from "../src/lib/news.js";
import { useLiveStore } from "../src/store/useLiveStore.js";
import { usePrefsStore } from "../src/store/usePrefsStore.js";

/** The reply to every query, and the reply to the "newer" count query. */
const fetched: { snapshot: NewsSnapshot; newer: number } = { snapshot: page([]), newer: 0 };
const calls: NewsQuery[] = [];
vi.mock("../src/lib/api.js", () => ({
  api: {
    news: vi.fn(async (query: NewsQuery) => {
      calls.push(query);
      return query.limit === 1 ? page([], fetched.newer) : fetched.snapshot;
    }),
  },
}));

const { NewsView, NEWS_POLL_MS } = await import("../src/views/News.js");

const NOW = Date.parse("2026-11-22T12:00:00Z");

function page(news: NewsEvent[], total = news.length): NewsSnapshot {
  return { news, count: news.length, total, has_more: total > news.length, sectors: {} };
}

function news(over: Partial<NewsEvent>): NewsEvent {
  return {
    id: "N1",
    ts_ns: (NOW - 60_000) * 1e6,
    scope: "SYMBOL",
    targets: ["AAPL"],
    kind: "EARNINGS",
    status: "CONFIRMED",
    headline: "AAPL beats",
    sentiment: 0.5,
    related_id: "",
    resolution: null,
    ...over,
  };
}

const last = () => calls[calls.length - 1]!;
const lastPageQuery = () => calls.filter((q) => q.limit !== 1).at(-1)!;

async function renderView() {
  render(<NewsView />);
  await act(async () => {});
}

describe("news lib", () => {
  it("starts a rolling window back from now, and none for all", () => {
    expect(newsWindowStart("1h", NOW)).toBe("2026-11-22T11:00:00.000Z");
    expect(newsWindowStart("24h", NOW)).toBe("2026-11-21T12:00:00.000Z");
    expect(newsWindowStart("7d", NOW)).toBe("2026-11-15T12:00:00.000Z");
    expect(newsWindowStart("30d", NOW)).toBe("2026-10-23T12:00:00.000Z");
    expect(newsWindowStart("all", NOW)).toBeUndefined();
  });

  it("maps symbols to their sector", () => {
    expect(sectorIndex({ TECH: ["AAPL", "MSFT"] })).toEqual({ AAPL: "TECH", MSFT: "TECH" });
  });
});

describe("NewsView", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(NOW);
    calls.length = 0;
    fetched.snapshot = page([]);
    fetched.newer = 0;
    useLiveStore.getState().reset();
    usePrefsStore.setState({ newsWindow: "24h", newsStatus: "ALL", newsSentiment: "all" });
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("asks for the last 24 hours, newest page first, and polls", async () => {
    await renderView();
    expect(last()).toEqual({
      limit: 50,
      offset: 0,
      from: "2026-11-21T12:00:00.000Z",
      to: undefined,
      filter: undefined,
      status: undefined,
      sentiment: undefined,
    });
    expect(screen.getByText("No headlines match.")).toBeTruthy();

    await act(async () => {
      vi.advanceTimersByTime(NEWS_POLL_MS);
    });
    expect(last().from).toBe(new Date(NOW + NEWS_POLL_MS - 86_400_000).toISOString());
  });

  it("shows the rows as sent, badges rumours and strikes retracted ones", async () => {
    fetched.snapshot = page([
      news({ id: "N3", status: "RETRACTED", related_id: "N1", headline: "AAPL bid" }),
      news({ id: "N2", scope: "SECTOR", targets: ["ENERGY"], headline: "Oil slumps", sentiment: -0.6 }),
      news({
        id: "N1",
        status: "RUMOUR",
        credibility: 0.3,
        headline: "Rumour: AAPL bid",
        resolution: "RETRACTED",
      }),
      news({
        id: "N0",
        status: "RUMOUR",
        credibility: 0.8,
        headline: "Rumour: XOM deal",
        resolution: "CONFIRMED",
      }),
    ]);
    await renderView();
    const rows = screen.getAllByTestId("news-row");
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("AAPL bid"),
      expect.stringContaining("Oil slumps"),
      expect.stringContaining("Rumour: AAPL bid"),
      expect.stringContaining("Rumour: XOM deal"),
    ]);
    expect(within(rows[2]!).getByText("RUMOUR 30%")).toBeTruthy();
    expect(within(rows[2]!).getByText("Rumour: AAPL bid").className).toContain("line-through");
    expect(within(rows[3]!).getByText("Rumour: XOM deal").className).not.toContain("line-through");
    expect(within(rows[0]!).getByText("RETRACTED")).toBeTruthy();
    expect(within(rows[0]!).getByText("AAPL bid").className).toContain("line-through");
    expect(within(rows[1]!).getByText("Oil slumps").className).toContain("text-down");
  });

  it("sends the filter, window, status and sentiment, and keeps the selectors", async () => {
    await renderView();
    fireEvent.change(screen.getByLabelText("Filter news by symbol or sector"), {
      target: { value: " xom " },
    });
    await act(async () => {});
    expect(last().filter).toBe("xom");

    fireEvent.change(screen.getByLabelText("News time window"), { target: { value: "7d" } });
    fireEvent.change(screen.getByLabelText("News status"), { target: { value: "RUMOUR" } });
    fireEvent.change(screen.getByLabelText("News sentiment"), { target: { value: "negative" } });
    await act(async () => {});
    expect(last()).toMatchObject({
      from: "2026-11-15T12:00:00.000Z",
      status: "RUMOUR",
      sentiment: "negative",
      offset: 0,
    });
    expect(usePrefsStore.getState()).toMatchObject({
      newsWindow: "7d",
      newsStatus: "RUMOUR",
      newsSentiment: "negative",
    });

    fireEvent.change(screen.getByLabelText("News time window"), { target: { value: "all" } });
    await act(async () => {});
    expect(last().from).toBeUndefined();
  });

  it("pins the window off page 1 and offers the newer headlines", async () => {
    fetched.snapshot = page([news({})], 120);
    await renderView();
    expect(screen.getByText("120 headlines")).toBeTruthy();
    expect(screen.getByText("Page 1/3")).toBeTruthy();

    fireEvent.click(screen.getByLabelText("Next page"));
    await act(async () => {});
    const pinned = { from: "2026-11-21T12:00:00.000Z", to: "2026-11-22T12:00:00.000Z" };
    expect(lastPageQuery()).toMatchObject({ offset: 50, ...pinned });
    expect(screen.getByText("Page 2/3")).toBeTruthy();

    // Time moves on: page 2 keeps its ends, and the newer ones are counted.
    fetched.newer = 4;
    await act(async () => {
      vi.advanceTimersByTime(NEWS_POLL_MS);
    });
    expect(lastPageQuery()).toMatchObject({ offset: 50, ...pinned });
    expect(last()).toMatchObject({ limit: 1, from: "2026-11-22T12:00:00.001Z", to: undefined });
    fireEvent.click(screen.getByLabelText("Next page"));
    await act(async () => {});
    expect(lastPageQuery()).toMatchObject({ offset: 100, ...pinned });

    fireEvent.click(screen.getByText("4 new"));
    await act(async () => {});
    expect(lastPageQuery()).toMatchObject({ offset: 0, to: undefined });
    expect(lastPageQuery().from).toBe(new Date(NOW + NEWS_POLL_MS - 86_400_000).toISOString());
    expect(screen.queryByText("4 new")).toBeNull();
  });

  it("says when there is no news at all", async () => {
    usePrefsStore.setState({ newsWindow: "all" });
    await renderView();
    expect(screen.getByText(/No news yet/)).toBeTruthy();
  });

  it("renders times in the session timezone, dated when not today", async () => {
    useLiveStore.getState().applyFrame({
      type: "hello",
      symbols: [],
      tickDecimals: {},
      indexes: [],
      sessionTimezone: "Europe/Stockholm",
      calf: "ACTIVE",
      gateway: "gw",
    });
    fetched.snapshot = page([
      news({ id: "T", ts_ns: Date.parse("2026-11-22T10:02:17Z") * 1e6 }),
      news({ id: "Y", ts_ns: Date.parse("2026-07-30T11:02:17Z") * 1e6 }),
    ]);
    await renderView();
    const [today, older] = screen.getAllByTestId("news-row");
    expect(within(today!).getByText("11:02:17")).toBeTruthy();
    expect(within(older!).getByText("2026-07-30 13:02:17")).toBeTruthy();
  });
});

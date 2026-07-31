import { describe, expect, it } from "vitest";
import type {
  IndexDailyRow,
  IndexEventRow,
  IndexSnapshotRow,
} from "@edumatcher/terminal-types";
import {
  dailySeries,
  indexRangeStart,
  recentChanges,
  snapshotSeries,
  usesSnapshots,
  withLiveTail,
} from "../src/lib/index-series.js";

const snap = (timestamp: string, level: number | null): IndexSnapshotRow => ({
  index_id: "EDU100",
  timestamp,
  level,
});

const day = (date: string, close: number | null): IndexDailyRow => ({
  date,
  index_id: "EDU100",
  open_level: 1000,
  high_level: 1010,
  low_level: 990,
  close_level: close,
  close_session_state: "CLOSED",
});

describe("preset routing", () => {
  it("charts intraday ticks for 1D and 5D, daily bars beyond", () => {
    // pm-index writes one row per index.update, fine enough to chart with no
    // bucketing step — but only snapshots go back a few days.
    expect(usesSnapshots("1D")).toBe(true);
    expect(usesSnapshots("5D")).toBe(true);
    expect(usesSnapshots("1M")).toBe(false);
    expect(usesSnapshots("All")).toBe(false);
  });

  it("asks for no lower bound on All", () => {
    expect(indexRangeStart("All")).toBeUndefined();
  });

  it("anchors YTD to the first of January", () => {
    expect(indexRangeStart("YTD", new Date("2026-07-30T12:00:00Z"))).toBe("2026-01-01");
  });

  it("walks back the right span for the relative presets", () => {
    const now = new Date("2026-07-30T12:00:00Z");
    expect(indexRangeStart("1D", now)).toBe("2026-07-30");
    expect(indexRangeStart("5D", now)).toBe("2026-07-25");
    expect(indexRangeStart("1M", now)).toBe("2026-06-30");
    expect(indexRangeStart("3M", now)).toBe("2026-04-30");
  });
});

describe("snapshotSeries", () => {
  it("orders oldest first regardless of how rows arrived", () => {
    const rows = [
      snap("2026-07-30T10:00:00Z", 1050),
      snap("2026-07-30T09:30:00Z", 1042),
    ];
    expect(snapshotSeries(rows).map((p) => p.value)).toEqual([1042, 1050]);
  });

  it("drops a row with no recorded level rather than charting a gap as zero", () => {
    const rows = [snap("2026-07-30T09:30:00Z", null), snap("2026-07-30T10:00:00Z", 1050)];
    expect(snapshotSeries(rows)).toHaveLength(1);
  });

  it("drops an unparseable timestamp", () => {
    expect(snapshotSeries([snap("not-a-time", 1050)])).toEqual([]);
  });
});

describe("dailySeries", () => {
  it("charts closing levels oldest first", () => {
    const rows = [day("2026-07-30", 1048), day("2026-07-29", 1041)];
    expect(dailySeries(rows).map((p) => p.value)).toEqual([1041, 1048]);
  });

  it("skips a day that recorded no close", () => {
    expect(dailySeries([day("2026-07-30", null)])).toEqual([]);
  });
});

describe("withLiveTail", () => {
  const history = [
    { time: 100, value: 1040 },
    { time: 200, value: 1045 },
  ];

  it("appends the live level as the right-hand edge", () => {
    // §10.2a: for the current date the chart's edge must be the live IDX
    // tick, never the REST row's provisional close_level.
    const out = withLiveTail(history, 1050, 300);
    expect(out[out.length - 1]).toEqual({ time: 300, value: 1050 });
  });

  it("replaces rather than duplicates a point at or after the live instant", () => {
    // Otherwise a series that already reaches "now" grows a new point on
    // every tick and the chart accumulates a vertical smear.
    const out = withLiveTail(history, 1050, 200);
    expect(out).toHaveLength(2);
    expect(out[out.length - 1]).toEqual({ time: 200, value: 1050 });
  });

  it("leaves history untouched when nothing is live yet", () => {
    // A SNAP before pm-index has published carries no level at all.
    expect(withLiveTail(history, undefined, 300)).toEqual(history);
  });

  it("does not mutate the input", () => {
    withLiveTail(history, 1050, 300);
    expect(history).toHaveLength(2);
  });
});

describe("recentChanges", () => {
  const ev = (over: Partial<IndexEventRow> & { type: IndexEventRow["type"] }): IndexEventRow => ({
    timestamp: 1_780_000_000,
    ...over,
  });

  it("summarises additions and delistings, newest first", () => {
    const events = [
      ev({ type: "ADD_CONSTITUENT", symbol: "AMZN", timestamp: 1_781_000_000 }),
      ev({ type: "DELIST", symbol: "XYZ", timestamp: 1_780_000_000 }),
    ];
    const lines = recentChanges(events);
    expect(lines[0]).toContain("+ AMZN added");
    expect(lines[1]).toContain("− XYZ delisted");
  });

  it("drops INIT, which is not a change", () => {
    // Every index has one, and it would push a real event off a strip that
    // only ever shows a handful.
    const events = [ev({ type: "INIT" }), ev({ type: "DELIST", symbol: "XYZ" })];
    expect(recentChanges(events)).toHaveLength(1);
  });

  it("caps the strip", () => {
    const events = Array.from({ length: 10 }, (_, i) =>
      ev({ type: "ADD_CONSTITUENT", symbol: `S${i}`, timestamp: 1_780_000_000 + i }),
    );
    expect(recentChanges(events, 3)).toHaveLength(3);
  });

  it("returns nothing when only INIT exists, so the strip hides entirely", () => {
    expect(recentChanges([ev({ type: "INIT" })])).toEqual([]);
  });
});

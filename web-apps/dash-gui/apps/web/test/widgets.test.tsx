// @vitest-environment jsdom
/** StateTimeline (D2.5), BarGauge (D2.4), HealthTable, EventLog and Row (D2.6). */

import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { HealthEvent } from "@edumatcher/dash-types";
import { BarGauge } from "../src/components/widgets/BarGauge.js";
import { EventLog, windowOf } from "../src/components/widgets/EventLog.js";
import { HealthTable, ProcessStateBadge, type Column } from "../src/components/widgets/HealthTable.js";
import { Row } from "../src/components/widgets/Row.js";
import { MARK_WIDTH, markX, segmentBox, StateTimeline, xOf } from "../src/components/widgets/StateTimeline.js";
import { formatBytes } from "../src/lib/format.js";
import { useRowStore } from "../src/store/useRowStore.js";

const T0 = Date.parse("2026-10-19T08:00:00Z");
const MIN = 60_000;
const RANGE = { fromMs: T0, toMs: T0 + 60 * MIN };

beforeEach(() => {
  localStorage.clear();
  useRowStore.setState({ collapsed: {} });
});
afterEach(cleanup);

describe("StateTimeline", () => {
  it("maps time linearly onto x, clamped to the plot", () => {
    expect(xOf(T0, RANGE, 600)).toBe(0);
    expect(xOf(T0 + 15 * MIN, RANGE, 600)).toBe(150);
    expect(xOf(T0 + 30 * MIN, RANGE, 600)).toBe(300);
    expect(xOf(T0 + 60 * MIN, RANGE, 600)).toBe(600);
    expect(xOf(T0 - MIN, RANGE, 600)).toBe(0);
    expect(xOf(T0 + 90 * MIN, RANGE, 600)).toBe(600);
  });

  it("a segment's width is its duration's share, cut to the range", () => {
    expect(segmentBox({ from: T0 + 6 * MIN, to: T0 + 18 * MIN, state: "UP" }, RANGE, 600)).toEqual({ x: 60, width: 120 });
    expect(segmentBox({ from: T0 - 30 * MIN, to: T0 + 6 * MIN, state: "UP" }, RANGE, 600)).toEqual({ x: 0, width: 60 });
    expect(segmentBox({ from: T0 - 30 * MIN, to: T0, state: "UP" }, RANGE, 600)).toBeNull();
  });

  it("a mark at the range's edge is drawn inside", () => {
    expect(markX(RANGE.toMs, RANGE, 600)).toBe(600 - MARK_WIDTH);
    expect(markX(RANGE.fromMs, RANGE, 600)).toBe(0);
  });

  it("renders lanes, segments, marks with tooltips on the session clock, and a legend", () => {
    render(
      <StateTimeline
        label="Connections"
        lanes={[
          { id: "MM01", segments: [{ from: T0, to: T0 + 30 * MIN, state: "CONNECTED" }], marks: [{ ts: RANGE.toMs, kind: "HB" }, { ts: T0 - MIN, kind: "HB" }] },
          { id: "TR07", segments: [] },
        ]}
        range={RANGE}
        states={{ CONNECTED: { label: "connected", color: "var(--ok)" } }}
        marks={{ HB: { label: "heartbeat timeout", color: "var(--crit)" } }}
        tz="Europe/Stockholm"
        width={696}
        labelWidth={96}
      />,
    );
    const seg = document.querySelector("[data-segment=CONNECTED]")!;
    expect([seg.getAttribute("x"), seg.getAttribute("width")]).toEqual(["0", "300"]);
    expect(seg.querySelector("title")!.textContent).toBe("MM01: connected 10:00:00–10:30:00");
    const marks = document.querySelectorAll("[data-mark=HB]");
    expect(marks).toHaveLength(1); // the one before the range is not drawn
    expect(marks[0]!.getAttribute("x")).toBe(String(600 - MARK_WIDTH));
    expect(document.querySelectorAll("[data-lane]")).toHaveLength(2);
    expect(screen.getByRole("figure", { name: "Connections" }).textContent).toContain("heartbeat timeout");
  });
});

describe("BarGauge", () => {
  const items = [
    { label: "pm-engine", value: 412e6 },
    { label: "pm-stats", value: 96e6 },
    { label: "pm-api-gwy", value: 118e6 },
    { label: "pm-clearing", value: 88e6 },
    { label: "pm-index", value: 40e6 },
  ];

  it("sorts largest first and sums the rest into other, adding up to the total", () => {
    render(<BarGauge label="Memory" items={items} format={formatBytes} limit={3} />);
    const rows = [...document.querySelectorAll("[data-label]")].map((r) => r.getAttribute("data-label"));
    expect(rows).toEqual(["pm-engine", "pm-api-gwy", "pm-stats", "other (2)"]);
    expect(document.querySelector("[data-label='other (2)']")!.textContent).toContain(formatBytes(128e6));
  });

  it("colours a bar over a threshold and says so with a glyph", () => {
    render(<BarGauge label="Memory" items={items} format={formatBytes} thresholds={{ warn: 100e6, crit: 400e6 }} />);
    const engine = document.querySelector("[data-label=pm-engine]")!;
    expect(engine.getAttribute("data-level")).toBe("CRIT");
    expect(engine.textContent).toContain("✕");
    expect(document.querySelector("[data-label=pm-index]")!.getAttribute("data-level")).toBe("OK");
  });
});

interface Proc {
  key: string;
  state: "HEALTHY" | "HUNG";
  rss: number;
  bot: boolean;
}

describe("HealthTable", () => {
  const rows: Proc[] = [
    { key: "pm-stats", state: "HEALTHY", rss: 96, bot: false },
    { key: "pm-engine", state: "HEALTHY", rss: 412, bot: false },
    { key: "pm-mm-bot", state: "HEALTHY", rss: 61, bot: true },
    { key: "pm-clearing", state: "HUNG", rss: 88, bot: false },
  ];
  const columns: Column<Proc>[] = [
    { id: "key", header: "Process", render: (r) => r.key, sortKey: (r) => r.key },
    { id: "state", header: "State", render: (r) => <ProcessStateBadge state={r.state} /> },
    { id: "rss", header: "RSS", render: (r) => r.rss, sortKey: (r) => r.rss, align: "right" },
  ];
  const order = () => [...document.querySelectorAll("tbody tr[data-row]")].map((r) => r.getAttribute("data-row"));

  it("sorts by a column, toggling direction, and says so", () => {
    render(<HealthTable label="Processes" columns={columns} rows={rows} rowKey={(r) => r.key} />);
    expect(order()).toEqual(["pm-stats", "pm-engine", "pm-mm-bot", "pm-clearing"]); // as given
    fireEvent.click(screen.getByRole("button", { name: "RSS" }));
    expect(order()).toEqual(["pm-mm-bot", "pm-clearing", "pm-stats", "pm-engine"]);
    expect(screen.getByRole("columnheader", { name: /RSS/ }).getAttribute("aria-sort")).toBe("ascending");
    fireEvent.click(screen.getByRole("button", { name: /RSS/ }));
    expect(order()).toEqual(["pm-engine", "pm-stats", "pm-clearing", "pm-mm-bot"]);
    expect(screen.getByRole("columnheader", { name: /RSS/ }).getAttribute("aria-sort")).toBe("descending");
    expect(screen.queryByRole("button", { name: "State" })).toBeNull(); // no sort key, no sorting
  });

  it("sorts within groups, the groups in the order they first appear", () => {
    render(
      <HealthTable label="Processes" columns={columns} rows={rows} rowKey={(r) => r.key} group={(r) => (r.bot ? "Participant bots" : "Exchange")} initialSort={{ id: "key", dir: "asc" }} />,
    );
    expect(order()).toEqual(["pm-clearing", "pm-engine", "pm-stats", "pm-mm-bot"]);
    expect(screen.getByRole("rowheader", { name: "Participant bots" })).toBeTruthy();
  });

  it("shows state as glyph and word", () => {
    render(<HealthTable label="Processes" columns={columns} rows={rows} rowKey={(r) => r.key} />);
    expect(document.querySelector("[data-row=pm-clearing]")!.textContent).toContain("◆ HUNG");
  });

  it("a row click reaches the caller", () => {
    const clicked: string[] = [];
    render(<HealthTable label="Processes" columns={columns} rows={rows} rowKey={(r) => r.key} onRowClick={(r) => clicked.push(r.key)} />);
    fireEvent.click(document.querySelector("[data-row=pm-engine]")!);
    expect(clicked).toEqual(["pm-engine"]);
  });
});

describe("EventLog", () => {
  const event = (seq: number, kind: HealthEvent["kind"], minute = seq): HealthEvent => ({
    seq,
    ts: new Date(T0 + minute * MIN).toISOString(),
    kind,
    severity: kind === "PROCESS_STATUS" ? "CRIT" : "INFO",
    subject: `S${seq}`,
    detail: "",
  });
  const seqs = () => [...document.querySelectorAll("[data-seq]")].map((r) => Number(r.getAttribute("data-seq")));

  it("newest first, times on the session clock, severity in glyph and word", () => {
    render(<EventLog label="Events" events={[event(1, "CONNECT"), event(3, "PROCESS_STATUS"), event(2, "SESSION")]} tz="Europe/Stockholm" />);
    expect(seqs()).toEqual([3, 2, 1]);
    const newest = document.querySelector("[data-seq='3']")!.textContent!;
    expect(newest).toContain("10:03:00");
    expect(newest).toContain("✕ CRIT");
  });

  it("filters by kind, and back", () => {
    render(<EventLog label="Events" events={[event(1, "CONNECT"), event(2, "SESSION"), event(3, "CONNECT")]} tz="UTC" />);
    const kinds = screen.getByRole("group", { name: "Event kinds" });
    fireEvent.click(within(kinds).getByRole("button", { name: "CONNECT" }));
    expect(seqs()).toEqual([2]);
    expect(within(kinds).getByRole("button", { name: "CONNECT" }).getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(within(kinds).getByRole("button", { name: "CONNECT" }));
    expect(seqs()).toEqual([3, 2, 1]);
  });

  it("renders only the rows in view, and follows the scroll", () => {
    const many = Array.from({ length: 1000 }, (_, i) => event(i + 1, "CONNECT", i));
    render(<EventLog label="Events" events={many} tz="UTC" height={220} rowHeight={22} />);
    const log = screen.getByRole("log");
    expect(log.getAttribute("data-count")).toBe("1000");
    expect(seqs()).toHaveLength(15); // 10 in view + 5 below
    expect(seqs()[0]).toBe(1000);
    act(() => {
      log.scrollTop = 22 * 500;
      fireEvent.scroll(log);
    });
    expect(seqs()[0]).toBe(1000 - 495);
    expect(seqs()).toHaveLength(20);
    expect(windowOf(0, 220, 22, 3)).toEqual([0, 3]);
  });
});

describe("Row", () => {
  it("collapses and expands, with the badge in words", () => {
    render(
      <Row id="processes" title="Processes" badge="1 degraded">
        <p>content</p>
      </Row>,
    );
    const header = screen.getByRole("button", { name: /Processes/ });
    expect(header.textContent).toContain("1 degraded");
    expect(header.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(header);
    expect(screen.queryByText("content")).toBeNull();
    expect(header.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(header);
    expect(screen.getByText("content")).toBeTruthy();
  });

  it("is remembered per browser, row by row", async () => {
    render(
      <>
        <Row id="books" title="Books">books</Row>
        <Row id="gateways" title="Gateways">gateways</Row>
      </>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Books/ }));
    const saved = localStorage.getItem("dash-rows")!;
    expect(JSON.parse(saved).state.collapsed).toEqual({ books: true });
    // A new page load: a fresh store reading what the browser kept.
    cleanup();
    useRowStore.setState({ collapsed: {} });
    localStorage.setItem("dash-rows", saved);
    await act(() => useRowStore.persist.rehydrate());
    render(
      <>
        <Row id="books" title="Books">books</Row>
        <Row id="gateways" title="Gateways">gateways</Row>
      </>,
    );
    expect(screen.queryByText("books")).toBeNull();
    expect(screen.getByText("gateways")).toBeTruthy();
  });
});

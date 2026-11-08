// @vitest-environment jsdom
/**
 * WP-D3: the seven rows, end to end in the browser app -- the real App and
 * stores, a snapshot captured from a running exchange over a fake socket,
 * and a fake bridge REST API that records every request.
 */

import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HealthSnapshot, ProcessHealth, ProcessState, ServerFrame } from "@edumatcher/dash-types";
import App from "../src/App.js";
import { useLiveSeries } from "../src/hooks/history.js";
import { useDashStore } from "../src/store/useDashStore.js";
import { usePrefsStore } from "../src/store/usePrefsStore.js";
import { fakeBridge, NOW } from "./fake-bridge.js";
import { FakeSocket } from "./fake-socket.js";
import { CAPTURED, fixtureSnapshot } from "./fixtures/snapshots.js";

function renderAt(path = "/") {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
  const socket = FakeSocket.latest();
  socket.open();
  return socket;
}

const hello: ServerFrame = { type: "hello", version: "1", monitor: "UP", sessionTz: "Europe/Stockholm" };
const frame = (data: HealthSnapshot): ServerFrame => ({ type: "snapshot", data });
const row = (title: string) => screen.getByRole("region", { name: `${title} row` });
const tile = (label: string) => within(screen.getByRole("region", { name: label })).getByTestId("stat-value").textContent;

let bridge: ReturnType<typeof fakeBridge>;
beforeEach(() => {
  cleanup();
  localStorage.clear();
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  bridge = fakeBridge();
  useDashStore.setState({ socket: "CONNECTING", monitor: null, snapshot: null, events: [], recent: [], thresholds: null, links: null, range: "1h", refresh: "off" });
});
afterEach(() => vi.unstubAllGlobals());

describe("row 1, overview (D3.2)", () => {
  it("shows the captured snapshot's figures", async () => {
    const socket = renderAt();
    socket.deliver(hello, frame(CAPTURED));
    expect(tile("Processes")).toBe("10 / 10");
    expect(row("Overview").textContent).toContain("all healthy");
    expect(tile("Participants")).toBe("2 / 4");
    expect(tile("Orders today")).toBe("11");
    expect(tile("Trades today")).toBe("8");
    expect(tile("Engine p99")).toBe("23 µs");
    expect(screen.getAllByRole("meter").map((m) => m.getAttribute("aria-label"))).toEqual(["CPU", "Memory", "Disk free"]);
    // The thresholds arrive from /api/thresholds and reach the gauges.
    await waitFor(() => expect(screen.getByRole("meter", { name: "CPU" }).querySelector("title")?.textContent).toBe("WARN above 80.0%, CRIT above 95.0%"));
  });

  it("colours the processes tile by pm-monitor's verdict on the exchange (I118)", () => {
    const socket = renderAt();
    const tileLevel = () => screen.getByRole("region", { name: "Processes" }).getAttribute("data-level");
    const dead = CAPTURED.processes.map((p, i) => (i === 0 ? { ...p, state: "DEAD" as ProcessState } : p));
    socket.deliver(hello, frame(fixtureSnapshot({ processes: dead, exchange: { status: "IMPAIRED" } })));
    expect(tile("Processes")).toBe("9 / 10");
    expect(tileLevel()).toBe("CRIT");
    expect(screen.getByRole("region", { name: "Processes" }).textContent).toContain("1 DEAD");
    // Stopped on purpose (no profile roster): pm-monitor says OPERATIONAL, and so does the tile.
    const stopped = CAPTURED.processes.map((p, i) => (i === 0 ? { ...p, state: "STOPPED" as ProcessState } : p));
    socket.deliver(frame(fixtureSnapshot({ processes: stopped, exchange: { status: "OPERATIONAL" } })));
    expect(tile("Processes")).toBe("9 / 10");
    expect(tileLevel()).toBe("OK");
    socket.deliver(frame(fixtureSnapshot({ exchange: { status: "DEGRADED" } })));
    expect(tileLevel()).toBe("WARN");
  });

  it("gauges and the p99 tile take pm-monitor's level, not their own reading of the value (I118)", async () => {
    const socket = renderAt();
    const host = { ...CAPTURED.host, cpu_pct: 90 };
    socket.deliver(hello, frame(fixtureSnapshot({ host, thresholds: [] })));
    // Above the 80 % band, but pm-monitor has not judged it a breach (hysteresis, minimum samples).
    await waitFor(() => expect(screen.getByRole("meter", { name: "CPU" }).querySelector("title")?.textContent).toContain("80.0%"));
    expect(screen.getByRole("meter", { name: "CPU" }).getAttribute("aria-valuetext")).toBe("90.0%");
    const breach = { rule: "host_cpu_pct", subject: "host", level: "CRIT" as const, value: 96, threshold: 95, since: CAPTURED.ts };
    socket.deliver(frame(fixtureSnapshot({ host, thresholds: [breach] })));
    expect(screen.getByRole("meter", { name: "CPU" }).getAttribute("aria-valuetext")).toBe("90.0%, CRIT");
    const p99 = { rule: "engine_handle_p99_us", subject: "pm-engine@kappa1", level: "WARN" as const, value: 3000, threshold: 2000, since: CAPTURED.ts };
    socket.deliver(frame(fixtureSnapshot({ thresholds: [p99] })));
    expect(screen.getByRole("region", { name: "Engine p99" }).getAttribute("data-level")).toBe("WARN");
  });
});

describe("engine latency row", () => {
  it("shows order entry, other messages and garbage collection apart", async () => {
    const socket = renderAt();
    socket.deliver(hello, frame(fixtureSnapshot()));
    const r = row("Engine latency");
    expect(tile("Order p99")).toBe("23 µs");
    expect(tile("Other messages p99")).toBe("41 µs");
    expect(tile("Longest GC pause")).toBe("813 µs");
    // The captured engine had timed three order messages: too few for a p99.
    expect(r.textContent).toContain("3 samples: p99 is the maximum");
    const latency = () => bridge.calls.find((c) => c.startsWith("/api/series/multi?names="));
    await waitFor(() => expect(latency()).toBeDefined());
    const call = decodeURIComponent(latency()!);
    expect(call).toContain("engine.handle_us_p50,engine.handle_us_p99,engine.handle_us_p99_ex_gc,engine.gc_pause_us_max");
    expect(call).toContain("source=pm-engine@kappa1");
  });

  it("drops the warning once the p99 stands on enough samples", () => {
    const socket = renderAt();
    const trading = { ...CAPTURED.trading, handle_samples: 640 };
    socket.deliver(hello, frame(fixtureSnapshot({ trading })));
    expect(row("Engine latency").textContent).not.toContain("p99 is the maximum");
    expect(within(screen.getByRole("region", { name: "Order p99" })).getByText("640 samples")).toBeDefined();
  });
});

describe("row 2, processes (D3.3)", () => {
  it("renders each of the seven states with its glyph and word", () => {
    const states: [ProcessState, string][] = [
      ["HEALTHY", "●"],
      ["DEGRADED", "◐"],
      ["HUNG", "◆"],
      ["SILENT", "✕"],
      ["DEAD", "✕"],
      ["MISSING", "✕"],
      ["STOPPED", "○"],
    ];
    const processes: ProcessHealth[] = states.map(([state], i) => ({
      ...CAPTURED.processes[i]!,
      state,
      ...(state === "MISSING" ? { host: "", key: CAPTURED.processes[i]!.process } : {}),
    }));
    const socket = renderAt();
    socket.deliver(hello, frame(fixtureSnapshot({ processes })));
    const table = screen.getByRole("table", { name: "Processes" });
    for (const [i, [state, glyph]] of states.entries()) {
      const tr = table.querySelector(`[data-row="${processes[i]!.key}"]`)!;
      expect(tr.textContent, state).toContain(`${glyph} ${state}`);
    }
    // A process without a beacon has no figures to show.
    expect(table.querySelector(`[data-row="${processes[5]!.key}"]`)!.textContent).toContain("—");
    expect(row("Processes").textContent).toContain("1 DEAD, 1 SILENT, 1 MISSING, 1 HUNG, 1 STOPPED, 1 DEGRADED");
  });

  it("loop age is coloured per process as pm-monitor judges it; a stopped process has no current memory (I118)", () => {
    const engine = CAPTURED.processes.find((p) => p.process === "pm-engine")!;
    const processes = CAPTURED.processes.map((p) =>
      p.process === "pm-stats" ? { ...p, state: "DEAD" as ProcessState } : p.key === engine.key ? { ...p, loop_age_ms: 5000 } : p,
    );
    const breach = { rule: "loop_age_ms", subject: engine.key, level: "WARN" as const, value: 5000, threshold: 1000, since: CAPTURED.ts };
    const socket = renderAt();
    socket.deliver(hello, frame(fixtureSnapshot({ processes, thresholds: [breach] })));
    const table = screen.getByRole("table", { name: "Processes" });
    const loopCell = (key: string) => table.querySelector(`[data-row="${key}"]`)!.querySelectorAll("td")[5]!.firstElementChild!;
    expect(loopCell(engine.key).className).toContain("text-warning");
    const other = CAPTURED.processes.find((p) => p.process === "pm-md-gwy")!.key;
    expect(loopCell(other).className).not.toContain("text-warning");
    const bars = [...screen.getByRole("region", { name: "Memory per process" }).querySelectorAll("[data-label]")].map((li) => li.getAttribute("data-label"));
    expect(bars).toContain("pm-engine");
    expect(bars).not.toContain("pm-stats");
  });

  it("puts the participant bots after the exchange's own", () => {
    const bot = { ...CAPTURED.processes[0]!, key: "pm-mm-bot@kappa1", process: "pm-mm-bot", group: "BOT" as const };
    const socket = renderAt();
    socket.deliver(hello, frame(fixtureSnapshot({ processes: [bot, ...CAPTURED.processes] })));
    const table = screen.getByRole("table", { name: "Processes" });
    const keys = [...table.querySelectorAll("[data-row]")].map((r) => r.getAttribute("data-row"));
    expect(keys.at(-1)).toBe("pm-mm-bot@kappa1");
    expect(within(table).getByRole("rowheader", { name: "Participant bots" })).toBeTruthy();
  });
});

describe("rows 3-7 (D3.4)", () => {
  it("trading: why orders were rejected, and which window each average covers (I123)", () => {
    const socket = renderAt();
    const trading = { ...CAPTURED.trading, rejects_by_code: [{ code: "MM_MAX_SPREAD", count: 12 }, { code: "MARKET_CLOSED", count: 2 }] };
    socket.deliver(hello, frame(fixtureSnapshot({ trading })));
    const reasons = screen.getByRole("region", { name: "Rejects today by reason" });
    expect([...reasons.querySelectorAll("[data-label]")].map((li) => li.getAttribute("data-label"))).toEqual(["MM_MAX_SPREAD", "MARKET_CLOSED"]);
    expect(reasons.textContent).toContain("12");
    expect(screen.getByRole("region", { name: "Orders avg / min" }).textContent).toContain("last 60 min");
    expect(screen.getByRole("region", { name: "Orders avg / hour" }).textContent).toContain("today, per hour open");
    expect(screen.getByRole("region", { name: "Orders today" }).textContent).toContain("last hour");
    expect(row("Participants").textContent).toContain("avg/min over the last 60 min");
  });

  it("participants: the averages show — before a full day of data", () => {
    const socket = renderAt();
    socket.deliver(hello, frame(CAPTURED));
    const trader = screen.getByRole("table", { name: "Participants" }).querySelector('[data-row="TRADER01"]')!;
    const cells = [...trader.querySelectorAll("td")].map((td) => td.textContent);
    expect(CAPTURED.participants.find((p) => p.id === "TRADER01")!.orders.avg_per_day).toBeNull();
    expect(cells[8]).toBe("—"); // avg/day
    expect(cells[4]).toBe("8"); // orders today
    expect(cells[2]).toContain("yes");
    expect(row("Participants").textContent).toContain("2 / 4 connected");
    expect(tile("Orders avg / day")).toBe("—");
  });

  it("participants: the connected count over the range, and each one's lane in its row", () => {
    const socket = renderAt();
    socket.deliver(hello, frame(CAPTURED));
    expect(within(row("Participants")).getByRole("figure", { name: "Participants connected" }).textContent).toContain("heartbeat timeout");
    const table = screen.getByRole("table", { name: "Participants" });
    for (const p of CAPTURED.participants) {
      const lane = table.querySelector(`[data-row="${p.id}"] svg[data-lane="${p.id}"]`)!;
      expect(lane, p.id).toBeTruthy();
      expect(lane.querySelectorAll("[data-segment]").length > 0, p.id).toBe(p.connected);
    }
    expect(row("Participants").querySelector("[data-widget=state-timeline]")).toBeNull();
  });

  it("books: heap bloat is coloured only where pm-monitor judges it (I118)", () => {
    const socket = renderAt();
    const books = CAPTURED.books.map((b) => ({ ...b, heap_bloat_ratio: 2 }));
    const breach = { rule: "heap_bloat_ratio", subject: "MSFT", level: "WARN" as const, value: 2, threshold: 1.5, since: CAPTURED.ts };
    socket.deliver(hello, frame(fixtureSnapshot({ books, thresholds: [breach] })));
    const garbage = (symbol: string) => [...screen.getByRole("table", { name: "Order books" }).querySelector(`[data-row="${symbol}"]`)!.querySelectorAll("td")][7]!.textContent;
    expect(garbage("MSFT")).toBe("2.00× ◐");
    expect(garbage("AAPL")).toBe("2.00×"); // above the band, but pm-monitor has not judged it
  });

  it("books: paged, page size selectable, and the filter searches every book", () => {
    const socket = renderAt();
    usePrefsStore.setState({ booksPageSize: 30 });
    const template = CAPTURED.books[0]!;
    const books = Array.from({ length: 75 }, (_, i) => ({ ...template, symbol: `S${String(i).padStart(3, "0")}` }));
    socket.deliver(hello, frame(fixtureSnapshot({ books })));
    const rows = () => screen.getByRole("table", { name: "Order books" }).querySelectorAll("tbody tr").length;
    expect(rows()).toBe(30);
    fireEvent.click(within(row("Order books")).getByRole("button", { name: "Next page" }));
    expect(within(row("Order books")).getByText("Page 2/3")).toBeTruthy();
    fireEvent.change(within(row("Order books")).getByLabelText("Rows per page"), { target: { value: "10" } });
    expect(rows()).toBe(10);
    expect(usePrefsStore.getState().booksPageSize).toBe(10);
    expect(within(row("Order books")).getByText("Page 1/8")).toBeTruthy();
    fireEvent.change(within(row("Order books")).getByLabelText("Rows per page"), { target: { value: "0" } });
    expect(rows()).toBe(75);
    // S074 would be on the last page of 10; the search finds it from anywhere.
    fireEvent.change(within(row("Order books")).getByLabelText("Rows per page"), { target: { value: "10" } });
    fireEvent.change(within(row("Order books")).getByLabelText("Find symbol"), { target: { value: "s07" } });
    expect(rows()).toBe(5);
    expect(within(row("Order books")).getByText("5 symbols of 75")).toBeTruthy();
  });

  it("participants: paged, and filtered by role across every page", () => {
    const socket = renderAt();
    usePrefsStore.setState({ participantsPageSize: 10 });
    const template = CAPTURED.participants[0]!;
    const participants = Array.from({ length: 25 }, (_, i) => ({ ...template, id: `P${String(i).padStart(2, "0")}`, role: i % 5 === 0 ? "MARKET_MAKER" : "TRADER" }));
    socket.deliver(hello, frame(fixtureSnapshot({ participants })));
    const rows = () => screen.getByRole("table", { name: "Participants" }).querySelectorAll("tbody tr").length;
    const pager = () => within(row("Participants"));
    expect(rows()).toBe(10);
    expect(pager().getByText("Page 1/3")).toBeTruthy();
    fireEvent.change(pager().getByLabelText("Filter by role"), { target: { value: "MARKET_MAKER" } });
    expect(rows()).toBe(5);
    expect(pager().getByText("5 participants of 25")).toBeTruthy();
    // P20 is a market maker on the last page of the unfiltered table; the search finds it from anywhere.
    fireEvent.change(pager().getByLabelText("Find ID"), { target: { value: "p2" } });
    expect(rows()).toBe(1);
    fireEvent.change(pager().getByLabelText("Find ID"), { target: { value: "" } });
    fireEvent.change(pager().getByLabelText("Filter by role"), { target: { value: "" } });
    fireEvent.change(pager().getByLabelText("Rows per page"), { target: { value: "0" } });
    expect(rows()).toBe(25);
    expect(usePrefsStore.getState().participantsPageSize).toBe(0);
  });

  it("REST API: load and throttling per gateway and per key", async () => {
    const socket = renderAt();
    const breach = { rule: "api_throttled", subject: "pm-api-gwy/desk@kappa1", level: "WARN" as const, value: 2, threshold: 0, since: CAPTURED.ts };
    socket.deliver(hello, frame(fixtureSnapshot({ thresholds: [breach] })));
    const api = row("REST API");
    expect(api.textContent).toContain("2 throttled in 5 min"); // the row badge
    const within_ = within(api);
    expect(tile("API requests / s")).toBe("4.50 /s");
    expect(screen.getByRole("region", { name: "API peak / s" }).textContent).toContain("Bot");
    const table = within_.getByRole("table", { name: "API keys" });
    const cells = (label: string) => [...table.querySelector(`[data-row="${label}"]`)!.querySelectorAll("td")].map((td) => td.textContent);
    expect(cells("Bot")[6]).toBe("40 ▲"); // the key behind the peak
    expect(cells("Desk A")[6]).toBe("25");
    expect(cells("Bot")[7]).toBe("7");
    // The history charts: requests per second by key, and throttling by key.
    expect(within_.getByRole("figure", { name: "API requests / s by key" })).toBeTruthy();
    expect(within_.getByRole("figure", { name: "API throttled by key" })).toBeTruthy();
    await waitFor(() => expect(bridge.count("/api/rate/by-label?name=api.key_requests")).toBe(1));
    expect(bridge.count("/api/rate/by-label?name=api.key_throttled")).toBe(1);
    // Sorted by load now, busiest first.
    expect([...table.querySelectorAll("tbody tr")].map((r) => r.getAttribute("data-row"))).toEqual(["Desk A", "Bot"]);
  });

  it("REST API: a throttling breach colours only its own instance", () => {
    const socket = renderAt();
    const [desk] = CAPTURED.api;
    const quiet = { ...desk!, key: "pm-api-gwy/dashboards@kappa1", throttled_total: 0, throttled_5m: 0 };
    const breach = { rule: "api_throttled", subject: desk!.key, level: "WARN" as const, value: 2, threshold: 0, since: CAPTURED.ts };
    socket.deliver(hello, frame(fixtureSnapshot({ api: [desk!, quiet], thresholds: [breach] })));
    const throttledTile = (instance: string) =>
      within(screen.getByRole("region", { name: `REST API ${instance}` })).getByRole("region", { name: "API throttled" }).getAttribute("data-level");
    expect(throttledTile("pm-api-gwy/desk")).toBe("WARN");
    expect(throttledTile("pm-api-gwy/dashboards")).not.toBe("WARN");
  });

  it("books, gateways and the event log", async () => {
    const socket = renderAt();
    socket.deliver(hello, frame(CAPTURED));
    const aapl = screen.getByRole("table", { name: "Order books" }).querySelector('[data-row="AAPL"]')!;
    expect(aapl.textContent).toContain("trading");
    expect([...aapl.querySelectorAll("td")][8]!.textContent).toBe("8");
    expect([...aapl.querySelectorAll("td")][1]!.textContent).toBe("1");
    expect(screen.getByRole("table", { name: "Order books" }).querySelectorAll("th")[1]!.textContent).toContain("Long");
    expect(tile("Books")).toBe(String(CAPTURED.books.length));
    expect(tile("ALF clients")).toBe("2 / 1 024");
    expect(tile("API dropped events")).toBe("0");
    expect(within(row("Gateways & infrastructure")).getByText("DISPATCH_ERROR")).toBeTruthy();
    // The log's history comes from /api/events on connect.
    await waitFor(() => expect(within(screen.getByRole("log")).getByText("TRADER01")).toBeTruthy());
  });
});

describe("rules and links (I118)", () => {
  it("are asked again every refresh interval, so a redeployed artifact shows without a reload", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    try {
      useDashStore.setState({ refresh: "10s" });
      const socket = renderAt();
      socket.deliver(hello, frame(CAPTURED));
      await waitFor(() => expect(bridge.count("/api/thresholds")).toBe(1));
      expect(bridge.count("/api/bridge/status")).toBe(1);
      act(() => vi.advanceTimersByTime(10_000));
      await waitFor(() => expect(bridge.count("/api/thresholds")).toBe(2));
      expect(bridge.count("/api/bridge/status")).toBe(2);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("history wiring (D3.5)", () => {
  it("one request per panel; switching range refetches each once", async () => {
    const socket = renderAt();
    socket.deliver(hello, frame(CAPTURED));
    await waitFor(() => expect(bridge.count("/api/series/multi")).toBe(3)); // memory, CPU, engine latency
    expect(bridge.count("/api/rate/by-label")).toBe(3); // orders per participant, API requests and throttles per key
    expect(bridge.count("/api/rate?")).toBe(4); // trades, value, rejects, requests
    expect(bridge.count("/api/series?")).toBe(0); // the drawers' charts, none open
    expect(bridge.calls.find((c) => c.startsWith("/api/series/multi") && c.includes("proc.cpu_pct"))).toContain("range=1h");

    fireEvent.click(screen.getByRole("button", { name: /^Time range:/ }));
    fireEvent.click(within(screen.getByRole("listbox", { name: "Time range" })).getByText("Last 6 hours"));
    await waitFor(() => expect(bridge.count("/api/series/multi")).toBe(6));
    await new Promise((r) => setTimeout(r, 50));
    expect(bridge.count("/api/series/multi")).toBe(6); // once, not more
    expect(bridge.count("/api/rate/by-label")).toBe(6);
    expect(bridge.calls.filter((c) => c.startsWith("/api/series/multi")).slice(-1)[0]).toContain("range=6h");
  });

  it("live snapshots add no request", async () => {
    const socket = renderAt();
    socket.deliver(hello, frame(CAPTURED));
    await waitFor(() => expect(bridge.count("/api/series/multi")).toBe(3));
    const before = bridge.calls.length;
    for (let i = 1; i <= 30; i++) socket.deliver(frame(fixtureSnapshot({ seq: i, ts: new Date(NOW + i * 1000).toISOString() })));
    await new Promise((r) => setTimeout(r, 50));
    expect(bridge.calls.length).toBe(before);
  });

  it("live points are appended at the chart's resolution, without a fetch", () => {
    useDashStore.setState({ snapshot: CAPTURED });
    const base = [{ label: "pm-engine", points: [[NOW - 10_000, 1]] as [number, number][] }];
    const { result } = renderHook(() => useLiveSeries(base, 10_000, (s) => [s.processes[0]!.rss_bytes]));
    expect(result.current![0]!.points).toHaveLength(2); // the current bucket's live point
    const step = (ms: number) => act(() => useDashStore.setState({ snapshot: fixtureSnapshot({ ts: new Date(NOW + ms).toISOString() }) }));
    step(3_000);
    expect(result.current![0]!.points).toHaveLength(2); // same bucket: nothing new
    step(11_000);
    expect(result.current![0]!.points).toHaveLength(3);
    expect(result.current![0]!.points.at(-1)![1]).toBe(CAPTURED.processes[0]!.rss_bytes);
  });
});

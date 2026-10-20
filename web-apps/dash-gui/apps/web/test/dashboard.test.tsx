// @vitest-environment jsdom
/**
 * WP-D3: the seven rows, end to end in the browser app -- the real App and
 * stores, a snapshot captured from a running exchange over a fake socket,
 * and a fake bridge REST API that records every request.
 */

import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HealthSnapshot, ProcessHealth, ProcessState, ServerFrame, ThresholdRule } from "@edumatcher/dash-types";
import App from "../src/App.js";
import { useLiveSeries } from "../src/hooks/history.js";
import { useDashStore } from "../src/store/useDashStore.js";
import { FakeSocket } from "./fake-socket.js";
import { CAPTURED, fixtureSnapshot } from "./fixtures/snapshots.js";

const NOW = Date.parse(CAPTURED.ts);
const rule = (warn: number, crit: number | null, invert = false): ThresholdRule => ({ warn, crit, invert, configurable: crit !== null });

/** The REST answers, by path; every request is recorded. */
function fakeBridge() {
  const calls: string[] = [];
  const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  const fetcher = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://bridge");
    calls.push(`${url.pathname}?${url.searchParams.toString()}`);
    const q = url.searchParams;
    switch (url.pathname) {
      case "/api/thresholds":
        return json({
          source: "defaults",
          path: "",
          rules: {
            host_cpu_pct: rule(80, 95),
            host_mem_pct: rule(80, 92),
            disk_free_pct: rule(15, 5, true),
            engine_handle_p99_us: rule(2000, 10000),
            reject_pct_5m: rule(10, 30),
            heap_garbage_pct: rule(50, 80),
            loop_age_ms: rule(1000, null),
          },
        });
      case "/api/events":
        return json({ events: [{ seq: 1, ts: new Date(NOW - 60_000).toISOString(), kind: "CONNECT", severity: "INFO", subject: "TRADER01", detail: "" }] });
      case "/api/series/multi":
        return json({
          name: q.get("name"),
          resolution: "raw",
          bucketSec: 10,
          series: (q.get("sources") ?? "").split(",").map((source) => ({ label: "", source, points: [[NOW - 20_000, 1], [NOW - 10_000, 2]] })),
        });
      case "/api/rate/by-label":
        return json({ name: q.get("name"), bucket: "1m", series: [{ label: "TRADER01", points: [[NOW - 60_000, 8]] }, { label: "TRADER02", points: [[NOW - 60_000, 3]] }] });
      case "/api/rate":
        return json({ name: q.get("name") ?? q.get("names"), label: null, bucket: "1m", points: [[NOW - 60_000, 30]] });
      default:
        return new Response(JSON.stringify({ error: "not_found", message: url.pathname }), { status: 404 });
    }
  });
  vi.stubGlobal("fetch", fetcher);
  return { calls, count: (path: string) => calls.filter((c) => c.startsWith(path)).length };
}

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
  useDashStore.setState({ socket: "CONNECTING", monitor: null, snapshot: null, events: [], recent: [], thresholds: null, range: "1h", refresh: "off" });
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

  it("colours the processes tile by the worst state", () => {
    const socket = renderAt();
    const processes = CAPTURED.processes.map((p, i) => (i === 0 ? { ...p, state: "DEAD" as ProcessState } : p));
    socket.deliver(hello, frame(fixtureSnapshot({ processes })));
    expect(tile("Processes")).toBe("9 / 10");
    expect(screen.getByRole("region", { name: "Processes" }).getAttribute("data-level")).toBe("CRIT");
    expect(screen.getByRole("region", { name: "Processes" }).textContent).toContain("1 DEAD");
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

  it("books, gateways and the event log", async () => {
    const socket = renderAt();
    socket.deliver(hello, frame(CAPTURED));
    const aapl = screen.getByRole("table", { name: "Order books" }).querySelector('[data-row="AAPL"]')!;
    expect(aapl.textContent).toContain("trading");
    expect([...aapl.querySelectorAll("td")][7]!.textContent).toBe("8");
    expect(tile("Books")).toBe(String(CAPTURED.books.length));
    expect(tile("ALF clients")).toBe("2 / 1 024");
    expect(tile("API dropped events")).toBe("0");
    expect(within(row("Gateways & infrastructure")).getByText("DISPATCH_ERROR")).toBeTruthy();
    // The log's history comes from /api/events on connect.
    await waitFor(() => expect(within(screen.getByRole("log")).getByText("TRADER01")).toBeTruthy());
  });
});

describe("history wiring (D3.5)", () => {
  it("one request per panel; switching range refetches each once", async () => {
    const socket = renderAt();
    socket.deliver(hello, frame(CAPTURED));
    await waitFor(() => expect(bridge.count("/api/series/multi")).toBe(2)); // memory and CPU
    expect(bridge.count("/api/rate/by-label")).toBe(1);
    expect(bridge.count("/api/rate?")).toBe(4); // trades, value, rejects, requests
    expect(bridge.calls.find((c) => c.startsWith("/api/series/multi") && c.includes("proc.cpu_pct"))).toContain("range=1h");

    fireEvent.click(screen.getByRole("button", { name: /^Time range:/ }));
    fireEvent.click(within(screen.getByRole("listbox", { name: "Time range" })).getByText("Last 6 hours"));
    await waitFor(() => expect(bridge.count("/api/series/multi")).toBe(4));
    await new Promise((r) => setTimeout(r, 50));
    expect(bridge.count("/api/series/multi")).toBe(4); // once, not more
    expect(bridge.count("/api/rate/by-label")).toBe(2);
    expect(bridge.calls.filter((c) => c.startsWith("/api/series/multi")).slice(-1)[0]).toContain("range=6h");
  });

  it("live snapshots add no request", async () => {
    const socket = renderAt();
    socket.deliver(hello, frame(CAPTURED));
    await waitFor(() => expect(bridge.count("/api/series/multi")).toBe(2));
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

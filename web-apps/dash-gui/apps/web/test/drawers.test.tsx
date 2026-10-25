// @vitest-environment jsdom
/**
 * WP-D4: the process, participant and book drawers and their routes, in the
 * real App over the captured snapshot, a fake socket and a fake bridge.
 */

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CrossAppLinks, ServerFrame } from "@edumatcher/dash-types";
import App from "../src/App.js";
import { bookGuiUrl, drawerPath, logGuiUrl } from "../src/lib/links.js";
import { useDashStore } from "../src/store/useDashStore.js";
import { fakeBridge, type FakeBridge } from "./fake-bridge.js";
import { FakeSocket } from "./fake-socket.js";
import { CAPTURED } from "./fixtures/snapshots.js";

const API = "pm-api-gwy/desk@kappa1";
const hello: ServerFrame = { type: "hello", version: "1", monitor: "UP", sessionTz: "Europe/Stockholm" };
const snapshot: ServerFrame = { type: "snapshot", data: CAPTURED };

let where = "";
function Where() {
  const loc = useLocation();
  where = loc.pathname + loc.search;
  return null;
}

/** The app at `path`, connected; with `deliver` false no snapshot has arrived yet. */
function renderAt(path: string, deliver = true) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <Where />
    </MemoryRouter>,
  );
  const socket = FakeSocket.latest();
  socket.open();
  if (deliver) socket.deliver(hello, snapshot);
  return socket;
}

const drawer = () => screen.getByRole("dialog");
const facts = (label: string) => Object.fromEntries([...document.querySelector(`dl[aria-label="${label}"]`)!.querySelectorAll("div")].map((d) => [d.querySelector("dt")!.textContent, d.querySelector("dd")!.textContent]));

let bridge: FakeBridge;
function setup(links?: CrossAppLinks) {
  bridge = fakeBridge(links);
}
beforeEach(() => {
  cleanup();
  localStorage.clear();
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  setup();
  useDashStore.setState({ socket: "CONNECTING", monitor: null, snapshot: null, events: [], recent: [], thresholds: null, links: null, range: "1h", refresh: "off" });
});
afterEach(() => vi.unstubAllGlobals());

describe("links", () => {
  it("each id is one encoded path segment; the sibling apps' paths", () => {
    expect(drawerPath("process", API)).toBe("/process/pm-api-gwy%2Fdesk%40kappa1");
    expect(drawerPath("book", "BRK B")).toBe("/book/BRK%20B");
    expect(logGuiUrl("http://h:8091", "pm-api-gwy")).toBe("http://h:8091/logs?processes=pm-api-gwy");
    expect(bookGuiUrl("http://h:8094", "AAPL")).toBe("http://h:8094/book/AAPL");
  });
});

describe("routes (D4.1)", () => {
  it("a deep link opens its drawer over the dashboard, a key with / and @ included", async () => {
    renderAt(`${drawerPath("process", API)}?from=now-6h`);
    expect(within(drawer()).getByRole("heading", { level: 2 }).textContent).toBe(API);
    expect(screen.getByRole("region", { name: "Dashboard" })).toBeTruthy();
    expect(document.activeElement).toBe(within(drawer()).getByRole("heading", { level: 2 }));
    // Its charts are for this process, over the link's range.
    await waitFor(() => expect(bridge.count("/api/series?")).toBe(6));
    for (const call of bridge.calls.filter((c) => c.startsWith("/api/series?"))) {
      expect(call).toContain(`source=${encodeURIComponent(API)}`);
      expect(call).toContain("range=6h");
    }
  });

  it("a key typed in with a raw / works too; a path that is no view keeps the range (I118)", () => {
    renderAt(`/process/${API}?from=now-6h`);
    expect(within(drawer()).getByRole("heading", { level: 2 }).textContent).toBe(API);
    for (const path of ["/nowhere?from=now-6h", "/process/?from=now-6h", "/participant?from=now-6h"]) {
      cleanup();
      renderAt(path);
      expect(where, path).toBe("/?from=now-6h");
      expect(screen.queryByRole("dialog")).toBeNull();
    }
  });

  it("closing restores / with the same query string, by button or Escape", () => {
    renderAt(`${drawerPath("participant", "TRADER01")}?from=now-6h`);
    fireEvent.click(within(drawer()).getByRole("button", { name: "Close" }));
    expect(where).toBe("/?from=now-6h");
    expect(screen.queryByRole("dialog")).toBeNull();

    cleanup();
    renderAt(`${drawerPath("book", "AAPL")}?from=now-24h`);
    fireEvent.keyDown(drawer(), { key: "Escape" });
    expect(where).toBe("/?from=now-24h");
  });

  it("clicking a row opens its drawer, keeps the range, and does not reload the dashboard", async () => {
    renderAt("/?from=now-6h");
    await waitFor(() => expect(bridge.count("/api/series/multi")).toBe(3));
    const rows = bridge.calls.length;
    fireEvent.click(screen.getByRole("table", { name: "Processes" }).querySelector(`[data-row="${API}"]`)!);
    expect(where).toBe(`${drawerPath("process", API)}?from=now-6h`);
    expect(within(drawer()).getByRole("heading", { level: 2 }).textContent).toBe(API);
    fireEvent.keyDown(screen.getByRole("table", { name: "Order books" }).querySelector('[data-row="AAPL"]')!, { key: "Enter" });
    expect(where).toBe("/book/AAPL?from=now-6h");
    fireEvent.click(screen.getByRole("table", { name: "Participants" }).querySelector('[data-row="TRADER02"]')!);
    expect(where).toBe("/participant/TRADER02?from=now-6h");
    await waitFor(() => expect(bridge.count("/api/events?") ).toBeGreaterThan(1));
    // Only the drawers asked for anything: the rows' panels were not fetched again.
    expect(bridge.calls.slice(rows).filter((c) => c.startsWith("/api/series/multi") || c.startsWith("/api/rate/by-label"))).toEqual([]);
  });
});

describe("drawer content (D4.2)", () => {
  it("process: state, figures, application metrics and its events", async () => {
    renderAt(drawerPath("process", "pm-engine@kappa1"));
    const f = facts("Process figures");
    expect(f["State"]).toContain("HEALTHY");
    expect(f["Host"]).toBe("kappa1");
    const metrics = within(drawer()).getByRole("table", { name: "Application metrics" });
    expect(metrics.querySelector('[data-row="engine.busy_pct|"]')).toBeTruthy();
    // Its per-participant and per-symbol samples are not in the snapshot (I123); the drawer says where they are.
    expect(metrics.querySelector('[data-row="engine.orders_in|TRADER01"]')).toBeNull();
    expect(drawer().textContent).toContain("Per-participant and per-symbol figures are in the participant and order book drawers.");
    expect(within(drawer()).getAllByRole("region").map((r) => r.getAttribute("aria-label"))).toEqual(expect.arrayContaining(["Vitals", "Application metrics", "Events"]));
    await waitFor(() => expect(bridge.calls).toContain(`/api/events?range=1h&subject=${encodeURIComponent("pm-engine@kappa1")}&limit=500`));
  });

  it("participant: rates for it alone, resting orders, and its events", async () => {
    renderAt(drawerPath("participant", "TRADER01"));
    expect(facts("Participant figures")["Orders today"]).toBe("8");
    await waitFor(() => expect(bridge.count("/api/rate?name=engine.orders_in&label=TRADER01")).toBe(1));
    expect(bridge.count("/api/rate?name=engine.rejects&label=TRADER01")).toBe(1);
    expect(bridge.count("/api/rate?name=engine.fills&label=TRADER01")).toBe(1);
    expect(bridge.count("/api/series?name=engine.resting_orders&label=TRADER01")).toBe(1);
    await waitFor(() => expect(within(within(drawer()).getByRole("log")).getByText("CONNECT")).toBeTruthy());
  });

  it("book: figures, its charts and its halt", async () => {
    renderAt(drawerPath("book", "AAPL"));
    expect(facts("Book figures")["Trades today"]).toBe("8");
    await waitFor(() => expect(bridge.count("/api/rate?name=engine.trades&label=AAPL")).toBe(1));
    expect(bridge.count("/api/series?name=engine.book_heap_garbage_pct&label=AAPL")).toBe(1);
    await waitFor(() => expect(within(within(drawer()).getByRole("log")).getByText("HALT")).toBeTruthy());
  });

  it.each([
    ["process", "pm-nope@kappa1", "No process “pm-nope@kappa1” in the latest snapshot."],
    ["participant", "NOBODY", "No participant “NOBODY” in the latest snapshot."],
    ["book", "ZZZZ", "No order book “ZZZZ” in the latest snapshot."],
  ] as const)("an unknown %s shows not found, not a crash", (kind, id, text) => {
    renderAt(drawerPath(kind, id));
    expect(within(drawer()).getByRole("status").textContent).toBe(text);
    expect(screen.getByRole("region", { name: "Overview row" })).toBeTruthy();
  });

  it("before the first snapshot it waits, then shows the subject", () => {
    const socket = renderAt(drawerPath("book", "AAPL"), false);
    expect(within(drawer()).getByRole("status").textContent).toBe("Waiting for the first snapshot…");
    socket.deliver(hello, snapshot);
    expect(facts("Book figures")["State"]).toContain("trading");
  });

  it("a process the profile expects but has never been seen has no charts", () => {
    const missing = { ...CAPTURED.processes[0]!, key: "pm-index", process: "pm-index", host: "", state: "MISSING" as const };
    const socket = renderAt(drawerPath("process", "pm-index"), false);
    socket.deliver(hello, { type: "snapshot", data: { ...CAPTURED, processes: [...CAPTURED.processes, missing] } });
    expect(facts("Process figures")["PID"]).toBe("—");
    expect(within(drawer()).queryByRole("region", { name: "Vitals" })).toBeNull();
    expect(bridge.count("/api/series?")).toBe(0);
  });
});

describe("cross-app links (D4.3)", () => {
  it("absent while the bridge has none configured", async () => {
    renderAt(drawerPath("process", "pm-engine@kappa1"));
    await waitFor(() => expect(useDashStore.getState().links).toEqual({ logGui: null, bookGui: null }));
    expect(within(drawer()).queryByRole("link")).toBeNull();
    cleanup();
    renderAt(drawerPath("book", "AAPL"));
    expect(within(drawer()).queryByRole("link")).toBeNull();
  });

  it("to log-gui filtered by process, and to book-gui's book, when configured", async () => {
    setup({ logGui: "http://127.0.0.1:8091", bookGui: "http://127.0.0.1:8094" });
    renderAt(drawerPath("process", API));
    const logs = await within(drawer()).findByRole("link", { name: /log-gui/ });
    expect(logs.getAttribute("href")).toBe("http://127.0.0.1:8091/logs?processes=pm-api-gwy");
    expect(logs.getAttribute("target")).toBe("_blank");
    cleanup();
    renderAt(drawerPath("book", "AAPL"));
    expect((await within(drawer()).findByRole("link", { name: /book-gui/ })).getAttribute("href")).toBe("http://127.0.0.1:8094/book/AAPL");
    // A participant has no sibling-app view.
    cleanup();
    renderAt(drawerPath("participant", "TRADER01"));
    expect(within(drawer()).queryByRole("link")).toBeNull();
  });
});

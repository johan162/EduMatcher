// @vitest-environment jsdom
/**
 * WP-D1 end to end in the browser app: the real `App`, its stores and its
 * stream hook against a fake bridge socket. Top bar (D1.2), time picker and
 * URL (D1.3), the disconnected banner (D1.4), settings (D1.5).
 */

import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ExchangeStatusName, HealthSnapshot, ServerFrame } from "@edumatcher/dash-types";
import App from "../src/App.js";
import { useDashStore } from "../src/store/useDashStore.js";
import { useFontSizeStore } from "../src/store/useFontSizeStore.js";
import { usePrefsStore } from "../src/store/usePrefsStore.js";
import { FakeSocket } from "./fake-socket.js";
import { fixtureSnapshot } from "./fixtures/snapshots.js";

function Location() {
  const { search } = useLocation();
  return <output data-testid="location">{search}</output>;
}

function renderAt(path = "/") {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <Location />
    </MemoryRouter>,
  );
  const socket = FakeSocket.latest();
  socket.open();
  return socket;
}

const hello = (monitor: "UP" | "DOWN", sessionTz = "Europe/Stockholm"): ServerFrame => ({
  type: "hello",
  version: "1.2.3",
  monitor,
  sessionTz,
});

function snapshot(status: ExchangeStatusName, ts = "2026-10-19T09:42:05.000Z", tz = "Europe/Stockholm"): ServerFrame {
  return {
    type: "snapshot",
    data: fixtureSnapshot({ ts, seq: 1, exchange: { status, session_state: "CONTINUOUS", trading_date: "2026-10-19", session_timezone: tz } }),
  };
}

beforeEach(() => {
  cleanup();
  localStorage.clear();
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  useDashStore.setState({
    socket: "CONNECTING",
    monitor: null,
    bridgeVersion: null,
    sessionTz: "UTC",
    snapshot: null,
    events: [],
    range: "1h",
    refresh: "10s",
  });
  usePrefsStore.setState({ theme: "dark", statColorMode: "value" });
  useFontSizeStore.setState({ fontSize: "XS" });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("top bar (D1.2)", () => {
  it.each([
    ["OPERATIONAL", "●"],
    ["DEGRADED", "◐"],
    ["IMPAIRED", "◆"],
    ["DOWN", "✕"],
  ] as const)("shows %s as text and glyph, not colour only", (status, glyph) => {
    const socket = renderAt();
    socket.deliver(hello("UP"), snapshot(status));
    const pill = screen.getByRole("status", { name: `Exchange status ${status}` });
    expect(pill.textContent).toBe(`${glyph}${status}`);
  });

  it("says there is no data before the first snapshot", () => {
    renderAt();
    expect(screen.getByRole("status", { name: "Exchange status NO DATA" }).textContent).toBe("○NO DATA");
  });

  it("shows the session phase from md-gwy, the next phase and the countdown, with the trading date in the tooltip", () => {
    const socket = renderAt();
    const nextAt = new Date(Date.now() + 3 * 60_000 + 500).toISOString();
    socket.deliver(hello("UP"), snapshot("OPERATIONAL"), {
      type: "market_session",
      session: { state: "CONTINUOUS", nextState: "CLOSING_AUCTION", nextAt },
    });
    const badge = screen.getByTestId("session-badge");
    expect(badge.textContent).toMatch(/^Continuous→Closing Auctionin 0[23]:\d\d\d\d:\d\d:\d\d$/);
    expect(badge.getAttribute("title")).toBe("Trading date 2026-10-19 (Europe/Stockholm)");
  });

  it("shows the session as Unknown until md-gwy has reported it, and again when the bridge drops", () => {
    const socket = renderAt();
    expect(screen.getByLabelText("session phase").textContent).toBe("Unknown");
    socket.deliver(hello("UP"), { type: "market_session", session: { state: "PRE_OPEN", nextState: null, nextAt: null } });
    expect(screen.getByLabelText("session phase").textContent).toBe("Pre-Open");
    expect(screen.queryByLabelText("time to next session phase")).toBeNull();
    socket.drop();
    expect(screen.getByLabelText("session phase").textContent).toBe("Unknown");
  });

  it("shows the bridge connection: connecting, live, offline", () => {
    const socket = renderAt();
    expect(screen.getByText("LIVE")).toBeTruthy();
    socket.drop();
    expect(screen.getByText("OFFLINE")).toBeTruthy();
  });
});

describe("time range and refresh (D1.3)", () => {
  const range = () => screen.getByRole("button", { name: /^Time range:/ });

  it("choosing 6 hours updates the URL and the store", () => {
    renderAt("/?other=kept");
    expect(range().getAttribute("aria-label")).toBe("Time range: Last 1 hour");
    fireEvent.click(range());
    fireEvent.click(within(screen.getByRole("listbox", { name: "Time range" })).getByText("Last 6 hours"));
    expect(useDashStore.getState().range).toBe("6h");
    const params = new URLSearchParams(screen.getByTestId("location").textContent ?? "");
    expect(params.get("from")).toBe("now-6h");
    expect(params.get("other")).toBe("kept");
    expect(range().getAttribute("aria-label")).toBe("Time range: Last 6 hours");
  });

  it("a URL with from=now-24h selects 24 hours", () => {
    renderAt("/?from=now-24h");
    expect(useDashStore.getState().range).toBe("24h");
    expect(range().getAttribute("aria-label")).toBe("Time range: Last 24 hours");
  });

  it("an unknown from= falls back to the default hour", () => {
    useDashStore.setState({ range: "7d" });
    renderAt("/?from=now-3y");
    expect(useDashStore.getState().range).toBe("1h");
  });

  it("the list marks the current range, and Escape closes it", () => {
    renderAt("/?from=now-15m");
    fireEvent.click(range());
    const listbox = screen.getByRole("listbox", { name: "Time range" });
    expect(within(listbox).getByRole("option", { selected: true }).textContent).toBe("Last 15 minutes");
    fireEvent.keyDown(listbox, { key: "Escape" });
    expect(screen.queryByRole("listbox", { name: "Time range" })).toBeNull();
  });

  it("the refresh selector sets how often history is asked for", () => {
    renderAt();
    fireEvent.click(screen.getByRole("button", { name: "Refresh history: 10s" }));
    fireEvent.click(within(screen.getByRole("listbox", { name: "Refresh history" })).getByText("Off"));
    expect(useDashStore.getState().refresh).toBe("off");
    expect(screen.getByRole("button", { name: "Refresh history: Off" })).toBeTruthy();
  });
});

describe("disconnected banner (D1.4)", () => {
  const main = () => screen.getByRole("main");

  it("is absent while live, and the panels are not dimmed", () => {
    const socket = renderAt();
    socket.deliver(hello("UP"), snapshot("OPERATIONAL"));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(main().getAttribute("data-stale")).toBe("false");
  });

  it("pm-monitor down: says when the data froze, on the session clock, and dims the panels", () => {
    const socket = renderAt();
    // 09:42:05Z is 11:42:05 in Stockholm (CEST), the design's own example.
    socket.deliver(hello("UP"), snapshot("OPERATIONAL", "2026-10-19T09:42:05.000Z"));
    socket.deliver({ type: "monitor_state", monitor: "DOWN" });
    expect(screen.getByRole("alert").textContent).toBe("pm-monitor down — data frozen at 11:42:05");
    expect(main().getAttribute("data-stale")).toBe("true");
    expect(main().className).toContain("stale");
    // The last figures stay on screen, frozen, rather than vanishing.
    expect(screen.getByRole("status", { name: "Exchange status OPERATIONAL" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Dashboard" })).toBeTruthy();
  });

  it("the bridge gone: says so, keeps the frozen time, and clears when it is back", async () => {
    const socket = renderAt();
    socket.deliver(hello("UP", "Asia/Kolkata"), snapshot("DEGRADED", "2026-10-19T09:42:05.000Z", "Asia/Kolkata"));
    socket.drop();
    expect(screen.getByRole("alert").textContent).toBe(
      "pm-dash-bridge unreachable, reconnecting — data frozen at 15:12:05",
    );
    expect(screen.getByRole("status", { name: "Exchange status DEGRADED" })).toBeTruthy();

    await vi.waitFor(() => expect(FakeSocket.instances).toHaveLength(2), { timeout: 3000 });
    const again = FakeSocket.latest();
    again.open();
    again.deliver(hello("UP"), snapshot("OPERATIONAL"));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(main().getAttribute("data-stale")).toBe("false");
  });

  it("pm-monitor down before any snapshot: no data yet", () => {
    const socket = renderAt();
    socket.deliver(hello("DOWN"));
    expect(screen.getByRole("alert").textContent).toBe("pm-monitor down — no data yet");
  });
});

describe("settings (D1.5)", () => {
  function openSettings() {
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    return screen.getByRole("menu", { name: "Settings" });
  }

  it("sets theme, font size and stat tile colour, and remembers them", () => {
    renderAt();
    const menu = openSettings();
    fireEvent.click(within(within(menu).getByRole("radiogroup", { name: "Theme" })).getByText("Light"));
    fireEvent.click(within(within(menu).getByRole("radiogroup", { name: "Font size" })).getByText("L"));
    fireEvent.click(within(within(menu).getByRole("radiogroup", { name: "Stat tile colour" })).getByText("Background"));
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(JSON.parse(localStorage.getItem("dash-prefs") ?? "{}").state).toMatchObject({
      theme: "light",
      statColorMode: "background",
    });
    expect(JSON.parse(localStorage.getItem("dash-font-size") ?? "{}").state.fontSize).toBe("L");
  });

  it("a localStorage that throws on every call breaks nothing; the choice just is not kept", async () => {
    for (const method of ["getItem", "setItem", "removeItem"] as const) {
      vi.spyOn(Storage.prototype, method).mockImplementation(() => {
        throw new DOMException("quota exceeded", "QuotaExceededError");
      });
    }
    await act(() => usePrefsStore.persist.rehydrate());
    renderAt();
    const menu = openSettings();
    fireEvent.click(within(within(menu).getByRole("radiogroup", { name: "Stat tile colour" })).getByText("Background"));
    fireEvent.click(screen.getByRole("button", { name: "Theme: dark" }));
    expect(usePrefsStore.getState()).toMatchObject({ theme: "light", statColorMode: "background" });
    expect(screen.getByRole("button", { name: "Theme: light" })).toBeTruthy();
  });

  it("a localStorage that cannot even be reached breaks nothing either", async () => {
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    await act(() => useFontSizeStore.persist.rehydrate());
    renderAt();
    fireEvent.click(within(within(openSettings()).getByRole("radiogroup", { name: "Font size" })).getByText("XL"));
    expect(useFontSizeStore.getState().fontSize).toBe("XL");
  });
});

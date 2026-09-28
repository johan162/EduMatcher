// @vitest-environment jsdom
/**
 * The whole web app, end to end: the real `App` with its real stream hook and
 * stores, talking to a fake bridge socket. Covers every pm-viewer field
 * (design §3.1), symbol switching, themes, settings and connection states.
 */

import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BookFrame, ServerFrame, SessionFrame, TapeTrade } from "@edumatcher/book-types";
import App from "../src/App.js";
import { useBookStore } from "../src/store/useBookStore.js";
import { usePrefsStore } from "../src/store/usePrefsStore.js";
import appVersion from "../src/version.json";
import { FakeSocket } from "./fake-socket.js";

const HELLO: ServerFrame = {
  type: "hello",
  symbols: [
    { symbol: "AAPL", tickDecimals: 2 },
    { symbol: "BRK", tickDecimals: 0 },
    { symbol: "MSFT", tickDecimals: 2 },
  ],
  upstream: "ACTIVE",
  source: "edumatcher:8081",
};

const BOOK: BookFrame = {
  type: "book",
  sym: "AAPL",
  seq: 1,
  tickDecimals: 2,
  bids: [
    { price: 166.95, qty: 312, count: 5 },
    { price: 166.94, qty: 138, count: 4 },
  ],
  asks: [{ price: 166.96, qty: 93, count: 1 }],
  last: 166.96,
  lastQty: 3,
};

const trade = (n: number, px: number, iso: string, qty = 100): TapeTrade => ({
  id: `000001-${String(n).padStart(9, "0")}`,
  tsMs: Date.parse(iso),
  px,
  qty,
  side: "BUY",
});

const SESSION: SessionFrame = {
  type: "session",
  sym: "AAPL",
  stats: {
    open: 165,
    high: 168,
    low: 164.5,
    close: 166.96,
    prevClose: 166,
    volume: 12400,
    tradeCount: 3,
    partial: false,
    sessionDate: "2026-09-28",
    timezone: "Asia/Kolkata",
  },
  tape: [
    trade(1, 166, "2026-09-27T09:15:10.000Z"),
    trade(2, 166.5, "2026-09-27T09:15:20.100Z"),
    trade(3, 166.96, "2026-09-27T09:15:30.250Z"),
  ],
};

let location = "";
function LocationProbe() {
  location = useLocation().pathname;
  return null;
}

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <LocationProbe />
    </MemoryRouter>,
  );
  const socket = FakeSocket.latest();
  socket.open();
  return socket;
}

const text = (id: string) => screen.getByTestId(id).textContent;

function rows(panel: string) {
  return within(screen.getByRole("region", { name: panel })).queryAllByRole("row");
}

beforeEach(() => {
  cleanup();
  localStorage.clear();
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  // 20:00 UTC is already 01:30 on the 28th in the session timezone (UTC+5:30).
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-09-27T20:00:00Z"));
  useBookStore.setState({
    socketOpen: false,
    upstream: null,
    source: null,
    symbols: [],
    watched: null,
    book: null,
    stats: null,
    tape: [],
    lastBookAt: null,
    error: null,
    capacity: 0,
  });
  usePrefsStore.setState({ theme: "dark", zebra: false, maxLevels: "fit", lastSymbol: null });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("top bar", () => {
  it("shows the wordmark, the orange app name and the release version", () => {
    renderAt("/book/AAPL");
    expect(screen.getByText("EduMatcher")).toBeTruthy();
    expect(screen.getByText("pm-book").className).toContain("text-accent");
    expect(screen.getByText(`v${appVersion.version}`)).toBeTruthy();
  });

  it("shows the connection state and the gateway it reads", () => {
    const socket = renderAt("/book/AAPL");
    socket.deliver(HELLO);
    expect(screen.getByText("LIVE")).toBeTruthy();
    expect(screen.getByText("edumatcher:8081")).toBeTruthy();
    socket.deliver({ type: "bridge_status", upstream: "RECONNECTING", since: "", wsClients: 1 });
    expect(screen.getByText("RECONNECTING")).toBeTruthy();
  });
});

describe("the book", () => {
  it("watches the symbol in the URL", () => {
    const socket = renderAt("/book/aapl");
    socket.deliver(HELLO);
    expect(socket.watches()).toEqual(["AAPL"]);
    expect(usePrefsStore.getState().lastSymbol).toBe("AAPL");
  });

  it("renders every pm-viewer header field, in the session timezone", () => {
    const socket = renderAt("/book/AAPL");
    socket.deliver(HELLO, BOOK, SESSION);

    expect(text("last")).toBe("166.96 ▲");
    expect(text("chg")).toBe("+0.96");
    expect(text("pct")).toBe("+0.58%");
    expect(text("size")).toBe("3");
    expect(text("bid")).toBe("166.95");
    expect(text("ask")).toBe("166.96");
    expect(text("spread")).toBe("0.01");
    expect(text("open")).toBe("165.00");
    expect(text("high")).toBe("168.00");
    expect(text("low")).toBe("164.50");
    expect(text("close")).toBe("166.96");
    expect(text("prev")).toBe("166.00");
    expect(text("range")).toBe("3.50");
    expect(text("volume")).toBe("12,400");
    expect(text("basis")).toBe("prev-close");
    expect(text("clock")).toBe("01:30:00");
    expect(text("date")).toBe("2026-09-28");
    expect(screen.getByTestId("last").className).toContain("text-up");
    expect(screen.getByTestId("trend-line").getAttribute("data-trend")).toBe("up");
  });

  it("renders the mirrored ladders with depth bars scaled to the largest visible level", () => {
    const socket = renderAt("/book/AAPL");
    socket.deliver(HELLO, BOOK, SESSION);

    const bids = rows("BIDS");
    expect(bids).toHaveLength(2);
    expect(bids.map((r) => [...r.children].map((c) => c.textContent))).toEqual([
      ["5", "312", "166.95", ""],
      ["4", "138", "166.94", ""],
    ]);
    const asks = rows("ASKS");
    expect([...asks[0]!.children].map((c) => c.textContent)).toEqual(["", "166.96", "93", "1"]);

    const bars = within(screen.getByRole("region", { name: "BIDS" })).getAllByTestId("depth-bar");
    expect(bars.map((b) => b.style.width)).toEqual(["100%", `${(138 / 312) * 100}%`]);
  });

  it("renders the tape newest first, in session time, coloured by tick direction", () => {
    const socket = renderAt("/book/AAPL");
    socket.deliver(HELLO, BOOK, SESSION);

    const tape = rows("TRADES");
    expect(tape.map((r) => [...r.children].map((c) => c.textContent))).toEqual([
      ["14:45:30.250", "166.96", "100"],
      ["14:45:20.100", "166.50", "100"],
      ["14:45:10.000", "166.00", "100"],
    ]);
    expect(tape.map((r) => r.getAttribute("data-trend"))).toEqual(["up", "up", "flat"]);
  });

  it("adds each live print to the tape and the statistics", () => {
    const socket = renderAt("/book/AAPL");
    socket.deliver(HELLO, BOOK, SESSION);
    socket.deliver({
      type: "trade",
      sym: "AAPL",
      trade: trade(4, 166.2, "2026-09-27T09:16:00.000Z", 50),
      stats: { ...SESSION.stats, close: 166.2, volume: 12450, tradeCount: 4 },
    });

    const first = rows("TRADES")[0]!;
    expect([...first.children].map((c) => c.textContent)).toEqual(["14:46:00.000", "166.20", "50"]);
    expect(first.getAttribute("data-trend")).toBe("down");
    expect(text("volume")).toBe("12,450");
    expect(text("close")).toBe("166.20");
  });

  it("formats every price at the symbol's own precision", () => {
    const socket = renderAt("/book/BRK");
    socket.deliver(HELLO, {
      ...BOOK,
      sym: "BRK",
      tickDecimals: 0,
      bids: [{ price: 412, qty: 1, count: 1 }],
      asks: [{ price: 415, qty: 1, count: 1 }],
      last: 413,
    });
    expect(text("last")).toBe("413 ▬");
    expect(text("spread")).toBe("3");
  });

  it("says when statistics cover only live trades", () => {
    const socket = renderAt("/book/AAPL");
    socket.deliver(HELLO, BOOK, {
      ...SESSION,
      stats: {
        volume: 0,
        tradeCount: 0,
        partial: true,
        since: Date.parse("2026-09-27T19:45:00Z"),
        timezone: "UTC",
      },
      tape: [],
    });
    expect(text("basis")).toBe("live since 19:45");
    expect(text("prev")).toBe("n/a");
    expect(text("open")).toBe("—");
    expect(text("chg")).toBe("—");
  });

  it("reports how much of each ladder is on screen", () => {
    const socket = renderAt("/book/AAPL");
    act(() => usePrefsStore.getState().setMaxLevels(10));
    const deep = Array.from({ length: 20 }, (_, i) => ({ price: 100 - i, qty: 10, count: 1 }));
    socket.deliver(HELLO, { ...BOOK, bids: deep });

    expect(rows("BIDS")).toHaveLength(10);
    expect(text("levels-shown")).toBe("bids 10/20 · asks 1/1 levels shown");
  });
});

describe("switching books", () => {
  it("opens the picker with s, filters by prefix, and switches with Enter", () => {
    const socket = renderAt("/book/AAPL");
    socket.deliver(HELLO, BOOK, SESSION);

    fireEvent.keyDown(window, { key: "s" });
    const filter = screen.getByLabelText("Filter symbols");
    fireEvent.keyDown(filter, { key: "m" });
    expect(
      within(screen.getByRole("listbox"))
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["MSFT"]);
    fireEvent.keyDown(filter, { key: "Enter" });

    expect(location).toBe("/book/MSFT");
    expect(socket.watches()).toEqual(["AAPL", "MSFT"]);
    // Nothing of AAPL's is shown under MSFT's name — not even a late frame.
    expect(text("last")).toBe("— ▬");
    socket.deliver(BOOK);
    expect(text("last")).toBe("— ▬");
  });

  it("opens with F1 too, moves with the arrows, and Esc keeps the current book", () => {
    const socket = renderAt("/book/AAPL");
    socket.deliver(HELLO);

    fireEvent.keyDown(window, { key: "F1" });
    const filter = screen.getByLabelText("Filter symbols");
    fireEvent.keyDown(filter, { key: "ArrowDown" });
    expect(screen.getByRole("option", { selected: true }).textContent).toBe("BRK");
    fireEvent.keyDown(filter, { key: "Escape" });

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(location).toBe("/book/AAPL");
  });

  it("switches with a click", () => {
    const socket = renderAt("/book/AAPL");
    socket.deliver(HELLO);
    fireEvent.click(screen.getByRole("button", { name: "Change symbol" }));
    fireEvent.click(screen.getByRole("option", { name: "BRK" }));
    expect(location).toBe("/book/BRK");
    expect(socket.watches()).toEqual(["AAPL", "BRK"]);
  });

  it("refuses a symbol that is not listed, and does not remember it", () => {
    const socket = renderAt("/book/NOPE");
    // Asked before the universe was known; the bridge refuses it.
    socket.deliver({
      type: "error",
      code: "UNKNOWN_SYMBOL",
      sym: "NOPE",
      message: "NOPE is not a listed symbol",
    });
    expect(screen.getByRole("alert").textContent).toContain("NOPE is not a listed symbol");

    socket.deliver(HELLO);
    expect(screen.getByRole("alert").textContent).toContain("NOPE is not a listed symbol");
    expect(usePrefsStore.getState().lastSymbol).toBeNull();

    // Once the universe is known, an unlisted URL is never even asked for.
    cleanup();
    const next = renderAt("/book/ZZZ");
    expect(next.watches()).not.toContain("ZZZ");
    expect(screen.getByRole("alert").textContent).toContain("ZZZ is not a listed symbol");
  });

  it("opens the last book viewed at /, else the first listed symbol", () => {
    usePrefsStore.setState({ lastSymbol: "MSFT" });
    renderAt("/");
    expect(location).toBe("/book/MSFT");

    cleanup();
    usePrefsStore.setState({ lastSymbol: null });
    const socket = renderAt("/");
    expect(screen.getByText("Waiting for the symbol list…")).toBeTruthy();
    socket.deliver(HELLO);
    expect(location).toBe("/book/AAPL");
  });
});

describe("connection loss", () => {
  it("hides every value while the bridge is unreachable and re-watches on reconnect", async () => {
    const socket = renderAt("/book/AAPL");
    socket.deliver(HELLO, BOOK, SESSION);

    socket.drop();
    expect(screen.getByRole("alert").textContent).toContain("Disconnected from pm-book-bridge");
    expect(screen.queryByTestId("last")).toBeNull();
    expect(screen.getByText("OFFLINE")).toBeTruthy();

    await waitFor(() => expect(FakeSocket.instances).toHaveLength(2), { timeout: 3000 });
    const again = FakeSocket.latest();
    again.open();
    expect(again.watches()).toEqual(["AAPL"]);
  });
});

describe("theme and settings", () => {
  it("toggles between dark and light and remembers the choice", () => {
    renderAt("/book/AAPL");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Theme: dark" }));
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(JSON.parse(localStorage.getItem("book-prefs") ?? "{}").state.theme).toBe("light");
  });

  it("stripes alternate rows when zebra rows are on", () => {
    const socket = renderAt("/book/AAPL");
    socket.deliver(HELLO, BOOK, SESSION);
    expect(rows("BIDS")[1]!.className).not.toContain("bg-bg-subtle");

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.click(screen.getByRole("switch", { name: "Zebra rows" }));
    expect(rows("BIDS")[1]!.className).toContain("bg-bg-subtle");
    expect(rows("BIDS")[0]!.className).not.toContain("bg-bg-subtle");
  });

  it("caps the levels shown from the settings", () => {
    const socket = renderAt("/book/AAPL");
    const deep = Array.from({ length: 30 }, (_, i) => ({ price: 100 - i, qty: 10, count: 1 }));
    socket.deliver(HELLO, { ...BOOK, bids: deep });
    // jsdom has no layout, so "fit" falls back to 15 rows.
    expect(rows("BIDS")).toHaveLength(15);

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.click(screen.getByRole("radio", { name: "10" }));
    expect(rows("BIDS")).toHaveLength(10);
    expect(usePrefsStore.getState().maxLevels).toBe(10);
  });
});

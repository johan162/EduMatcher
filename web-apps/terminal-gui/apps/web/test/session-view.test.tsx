// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ClientFrame, ServerFrame } from "@edumatcher/terminal-types";

const sent: ClientFrame[] = [];
vi.mock("../src/lib/useTerminalStream.js", () => ({
  sendControl: (frame: ClientFrame) => sent.push(frame),
  useTerminalStream: () => undefined,
}));

const schedule = vi.fn();
vi.mock("../src/lib/api.js", () => ({ api: { schedule: () => schedule() } }));

const { useLiveStore } = await import("../src/store/useLiveStore.js");
const { SessionView } = await import("../src/views/Session.js");

const apply = (...frames: ServerFrame[]) => {
  for (const frame of frames) useLiveStore.getState().applyFrame(frame);
};

const halt = (sym: string, over: Record<string, unknown> = {}): ServerFrame =>
  ({
    type: "state",
    sym,
    seq: 1,
    ts: "2026-07-30T11:02:17.000Z",
    session: "HALTED",
    ...over,
  }) as ServerFrame;

const cb = (sym: string, over: Record<string, unknown> = {}): ServerFrame =>
  ({
    type: "halt_context",
    sym,
    seq: 2,
    ts: "2026-07-30T11:02:17.000Z",
    status: "HALTED",
    ...over,
  }) as ServerFrame;

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = (
    <QueryClientProvider client={client}>
      <SessionView />
    </QueryClientProvider>
  );
  const view = render(tree);
  return { ...view, reshow: () => view.rerender(tree) };
}

beforeEach(() => {
  sent.length = 0;
  schedule.mockResolvedValue({ sessions_enabled: false, country: null, schedule: null });
  useLiveStore.getState().reset();
});
afterEach(cleanup);

describe("halt board subscription lifecycle", () => {
  it("declares the board open on mount", () => {
    show();
    expect(sent).toEqual([{ t: "halt_board", open: true }]);
  });

  it("releases it on unmount, so the bridge can drop its CB subscriptions", () => {
    show().unmount();
    expect(sent).toEqual([
      { t: "halt_board", open: true },
      { t: "halt_board", open: false },
    ]);
  });
});

describe("empty states", () => {
  it("says so when nothing is halted", () => {
    show();
    expect(screen.getByText("No symbols currently halted")).toBeDefined();
  });

  it("says so when no auction has run", () => {
    show();
    expect(screen.getByText("No auctions completed yet this session")).toBeDefined();
  });
});

describe("session phase", () => {
  it("shows the exchange phase and what preceded it", () => {
    apply({
      type: "state",
      sym: "*",
      seq: 1,
      ts: "2026-07-30T09:30:00.000Z",
      session: "CONTINUOUS",
      prev: "OPENING_AUCTION",
    });
    show();

    expect(screen.getByText("CONTINUOUS")).toBeDefined();
    expect(screen.getByText(/prev OPENING_AUCTION/)).toBeDefined();
    // 09:30:00Z is 11:30:00 in Stockholm summer time, the store's default zone.
    expect(screen.getByText(/since 11:30:00/)).toBeDefined();
  });

  it("admits when it has not seen a session transition yet", () => {
    show();
    expect(screen.getByText("AWAITING SESSION")).toBeDefined();
  });
});

describe("active halts", () => {
  it("lists a halted symbol with its circuit-breaker detail", () => {
    apply(
      halt("TSLA"),
      cb("TSLA", {
        level: "L2",
        triggerPrice: 261.4,
        referencePrice: 248,
        resumeAt: "2026-07-30T11:07:17.000Z",
        haltSource: "CB",
      }),
    );
    show();

    expect(screen.getByText("TSLA")).toBeDefined();
    expect(screen.getByText("L2")).toBeDefined();
    expect(screen.getByText("261.40")).toBeDefined();
    expect(screen.getByText("248.00")).toBeDefined();
    // The halt began at 11:02:17Z: 13:02:17 in Stockholm summer time.
    expect(screen.getByText("13:02:17")).toBeDefined();
  });

  it("shows dashes for an operator halt, which carries no trigger price", () => {
    apply(halt("TSLA"), cb("TSLA", { level: "ADMIN_SYMBOL" }));
    show();

    expect(screen.getByText("ADMIN_SYMBOL")).toBeDefined();
    // Trigger and reference are both absent for an ADMIN halt.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  it("renders a halt before its CB detail has arrived", () => {
    // STATE and CB come from the same engine event but are separate frames.
    apply(halt("TSLA"));
    show();
    expect(screen.getByText("TSLA")).toBeDefined();
  });

  it("says Manual when no resume time was published, since only an operator ends it", () => {
    apply(halt("TSLA"), cb("TSLA", { level: "ADMIN_ALL", haltSource: "ADMIN" }));
    show();
    expect(screen.getByText("Manual")).toBeDefined();
  });

  it("shows who halted the symbol alongside when it reopens", () => {
    // Source and resume time are independent: a breaker halt can be
    // indefinite, and an operator halt is always indefinite.
    apply(halt("TSLA"), cb("TSLA", { level: "L2", resumeAt: "2026-07-30T11:07:17.000Z", haltSource: "CB" }));
    show();
    expect(screen.getByText("CB")).toBeDefined();
  });

  it("drops the row once the symbol resumes", () => {
    apply(halt("TSLA"));
    const view = show();
    expect(screen.getByText("TSLA")).toBeDefined();

    apply({ type: "state", sym: "TSLA", seq: 3, ts: "t", session: "CONTINUOUS" });
    view.reshow();

    expect(screen.queryByText("TSLA")).toBeNull();
    expect(screen.getByText("No symbols currently halted")).toBeDefined();
  });
});

describe("recent auction results", () => {
  it("shows an uncross with its equilibrium price and imbalance", () => {
    apply({
      type: "auction_result",
      sym: "AAPL",
      seq: 1,
      ts: "2026-07-30T09:30:02.000Z",
      eqPrice: 149.85,
      eqQty: 12400,
      tradesCount: 38,
      imbalanceSide: "BUY",
      imbalanceQty: 1400,
    });
    show();

    expect(screen.getByText("149.85")).toBeDefined();
    expect(screen.getByText("12,400")).toBeDefined();
    expect(screen.getByText("BUY 1,400")).toBeDefined();
    // 09:30:02Z is 11:30:02 in Stockholm summer time, the store's default zone.
    expect(screen.getByText("11:30:02")).toBeDefined();
  });

  it("labels a no-cross auction rather than showing a blank price", () => {
    apply({
      type: "auction_result",
      sym: "MSFT",
      seq: 1,
      ts: "2026-07-30T09:30:02.000Z",
      eqQty: 0,
      tradesCount: 0,
      imbalanceQty: 0,
    });
    show();

    expect(screen.getByText("(no cross)")).toBeDefined();
  });
});

describe("column help", () => {
  it("explains every column of both tables", () => {
    apply(halt("TSLA"), cb("TSLA", { level: "L2" }), {
      type: "auction_result",
      sym: "AAPL",
      seq: 1,
      ts: "2026-07-30T09:30:02.000Z",
      eqQty: 0,
      tradesCount: 0,
      imbalanceQty: 0,
    });
    show();

    for (const heading of [
      "Level",
      "Trigger",
      "Reference",
      "Resumes",
      "Since",
      "Eq. price",
      "Trades",
      "Imbalance",
    ]) {
      expect(screen.getByRole("button", { name: `${heading} help` })).toBeDefined();
    }
    // Symbol heads both tables; Qty and Time only the auctions.
    expect(screen.getAllByRole("button", { name: "Symbol help" })).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Qty help" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Time help" })).toBeDefined();
  });
});

describe("timetable", () => {
  const DAY = {
    pre_open: "08:00",
    opening_auction_start: "08:50",
    continuous_start: "09:00",
    closing_auction_start: "17:25",
    closing_auction_end: "17:30",
  };
  const WEEK = {
    mon: DAY,
    tue: DAY,
    wed: DAY,
    thu: DAY,
    fri: DAY,
    sat: null,
    sun: null,
    holidays: null,
    upcoming_holidays: [
      { date: "2026-12-25", name: "Juldagen" },
      { date: "2026-12-26", name: "Annandag jul" },
    ],
  };
  const sessionAt = (session: string, prev?: string) =>
    apply({ type: "state", sym: "*", seq: 1, ts: "2026-12-21T11:00:00.000Z", session, prev } as ServerFrame);

  beforeEach(() => {
    // Monday 21 December, 12:00 in Stockholm. Only Date is faked, so the
    // query's promises still settle.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-12-21T11:00:00Z"));
    schedule.mockResolvedValue({ sessions_enabled: true, country: "Sweden", schedule: WEEK });
  });
  afterEach(() => vi.useRealTimers());

  it("lights the current phase and puts the clock on the day", async () => {
    sessionAt("CONTINUOUS", "OPENING_AUCTION");
    show();

    const flow = await screen.findByRole("list", { name: "Session phases" });
    const current = within(flow)
      .getAllByRole("listitem")
      .find((li) => li.getAttribute("aria-current") === "step");
    expect(current?.textContent).toContain("Continuous");
    expect(within(flow).getByText("17:25")).toBeDefined();
    expect(screen.getByTestId("now-marker").textContent).toBe("12:00");
  });

  it("shows the week with its holiday and names the next one that closes the exchange", async () => {
    sessionAt("CONTINUOUS");
    show();

    const today = (await screen.findByText("Mon")).closest("li")!;
    expect(today.getAttribute("aria-current")).toBe("date");
    const friday = screen.getByText("Fri").closest("li")!;
    expect(friday.textContent).toContain("Closed");
    expect(friday.textContent).toContain("Juldagen");
    // Annandag jul falls on a Saturday, closed anyway, so Juldagen is next.
    expect(screen.getByText("Fri 25 Dec")).toBeDefined();
    expect(screen.getByText("in 4 days")).toBeDefined();
  });

  it("hides the clock when the session is off its timetable", async () => {
    sessionAt("CLOSED", "CONTINUOUS");
    show();

    const flow = await screen.findByRole("list", { name: "Session phases" });
    const items = within(flow).getAllByRole("listitem");
    // The evening CLOSED, reached from trading, not the morning one.
    expect(items.at(-1)?.getAttribute("aria-current")).toBe("step");
    expect(screen.queryByTestId("now-marker")).toBeNull();
    expect(screen.getByText(/off its timetable/)).toBeDefined();
  });

  it("shows the next trading day while today is closed", async () => {
    vi.setSystemTime(new Date("2026-12-26T11:00:00Z"));
    sessionAt("CLOSED");
    show();

    expect(await screen.findByText(/Next trading day · Mon 28 Dec/)).toBeDefined();
    expect(screen.queryByTestId("now-marker")).toBeNull();
  });

  it("says so when sessions are disabled", async () => {
    schedule.mockResolvedValue({ sessions_enabled: false, country: null, schedule: null });
    show();
    expect(await screen.findByText(/Sessions are disabled/)).toBeDefined();
  });

  it("explains each part", async () => {
    sessionAt("CONTINUOUS");
    show();
    for (const label of ["This week", "Timetable", "Next bank holiday"]) {
      expect(await screen.findByRole("button", { name: `${label} help` })).toBeDefined();
    }
  });
});

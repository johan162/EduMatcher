// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ClientFrame, ServerFrame } from "@edumatcher/terminal-types";

const sent: ClientFrame[] = [];
vi.mock("../src/lib/useTerminalStream.js", () => ({
  sendControl: (frame: ClientFrame) => sent.push(frame),
  useTerminalStream: () => undefined,
}));

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

beforeEach(() => {
  sent.length = 0;
  useLiveStore.getState().reset();
});
afterEach(cleanup);

describe("halt board subscription lifecycle", () => {
  it("declares the board open on mount", () => {
    render(<SessionView />);
    expect(sent).toEqual([{ t: "halt_board", open: true }]);
  });

  it("releases it on unmount, so the bridge can drop its CB subscriptions", () => {
    render(<SessionView />).unmount();
    expect(sent).toEqual([
      { t: "halt_board", open: true },
      { t: "halt_board", open: false },
    ]);
  });
});

describe("empty states", () => {
  it("says so when nothing is halted", () => {
    render(<SessionView />);
    expect(screen.getByText("No symbols currently halted")).toBeDefined();
  });

  it("says so when no auction has run", () => {
    render(<SessionView />);
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
    render(<SessionView />);

    expect(screen.getByText("CONTINUOUS")).toBeDefined();
    expect(screen.getByText(/prev OPENING_AUCTION/)).toBeDefined();
  });

  it("admits when it has not seen a session transition yet", () => {
    render(<SessionView />);
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
        resumptionMode: "AUCTION",
      }),
    );
    render(<SessionView />);

    expect(screen.getByText("TSLA")).toBeDefined();
    expect(screen.getByText("L2")).toBeDefined();
    expect(screen.getByText("261.40")).toBeDefined();
    expect(screen.getByText("248.00")).toBeDefined();
  });

  it("shows dashes for an operator halt, which carries no trigger price", () => {
    apply(halt("TSLA"), cb("TSLA", { level: "ADMIN_SYMBOL" }));
    render(<SessionView />);

    expect(screen.getByText("ADMIN_SYMBOL")).toBeDefined();
    // Trigger and reference are both absent for an ADMIN halt.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  it("renders a halt before its CB detail has arrived", () => {
    // STATE and CB come from the same engine event but are separate frames.
    apply(halt("TSLA"));
    render(<SessionView />);
    expect(screen.getByText("TSLA")).toBeDefined();
  });

  it("shows MANUAL with no time, since such a halt ends only on operator action", () => {
    apply(halt("TSLA"), cb("TSLA", { level: "ADMIN_ALL", resumptionMode: "MANUAL" }));
    render(<SessionView />);
    expect(screen.getByText("MANUAL")).toBeDefined();
  });

  it("drops the row once the symbol resumes", () => {
    apply(halt("TSLA"));
    const view = render(<SessionView />);
    expect(screen.getByText("TSLA")).toBeDefined();

    apply({ type: "state", sym: "TSLA", seq: 3, ts: "t", session: "CONTINUOUS" });
    view.rerender(<SessionView />);

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
    render(<SessionView />);

    expect(screen.getByText("149.85")).toBeDefined();
    expect(screen.getByText("12,400")).toBeDefined();
    expect(screen.getByText("BUY 1,400")).toBeDefined();
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
    render(<SessionView />);

    expect(screen.getByText("(no cross)")).toBeDefined();
  });
});

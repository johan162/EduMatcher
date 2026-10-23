// @vitest-environment jsdom
/** The top bar's session indicator (WP-UI01): pm-trader's reading. */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { TopBar } from "../src/components/layout/TopBar.js";
import { useLiveStore } from "../src/store/useLiveStore.js";

beforeEach(() => {
  useLiveStore.getState().reset();
  useLiveStore.setState({ wsStatus: "open", calf: "ACTIVE" });
});
afterEach(cleanup);

const phaseText = () => screen.getByLabelText("session phase").textContent;

describe("top bar session indicator", () => {
  it("shows the phase, the next phase and the time to it", () => {
    const nextAt = new Date(Date.now() + 10 * 60_000 + 500).toISOString();
    useLiveStore.getState().applyFrame({
      type: "state",
      sym: "*",
      seq: 1,
      ts: new Date().toISOString(),
      session: "PRE_OPEN",
      nextPhase: "OPENING_AUCTION",
      nextAt,
    });
    render(<MemoryRouter><TopBar /></MemoryRouter>);
    expect(phaseText()).toBe("Pre-Open");
    expect(screen.getByText("Opening Auction")).toBeDefined();
    expect(screen.getByLabelText("time to next session phase").textContent).toMatch(/^in (10:00|09:59)$/);
  });

  it("is Unknown before the first session state", () => {
    render(<MemoryRouter><TopBar /></MemoryRouter>);
    expect(phaseText()).toBe("Unknown");
  });

  it("is Unknown while the CALF feed is not live, rather than showing a stale phase", () => {
    useLiveStore.getState().applyFrame({
      type: "state",
      sym: "*",
      seq: 1,
      ts: new Date().toISOString(),
      session: "CONTINUOUS",
    });
    useLiveStore.setState({ calf: "RECONNECTING" });
    render(<MemoryRouter><TopBar /></MemoryRouter>);
    expect(phaseText()).toBe("Unknown");
  });
});

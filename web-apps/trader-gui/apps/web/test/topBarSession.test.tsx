// @vitest-environment jsdom
/** The top bar's session badge (WP-UI01): Unknown until the engine has said. */

import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { TopBar } from "@/components/layout/TopBar";
import { useSessionStore } from "@/store/useSessionStore";

beforeEach(() => {
  cleanup();
  useSessionStore.setState({
    phase: "CLOSED",
    prevPhase: null,
    phaseSince: null,
    nextTransitionAt: null,
    nextState: null,
    schedule: null,
  });
});

describe("TopBar session badge", () => {
  it("shows Unknown, and no countdown, before the first session state", () => {
    render(<TopBar />);
    expect(screen.getByLabelText("session phase").textContent).toBe("Unknown");
    expect(screen.queryByLabelText("time to next session phase")).toBeNull();
    expect(screen.queryByLabelText("time elapsed in phase")).toBeNull();
  });

  it("shows the phase and the countdown once the session state arrives", () => {
    useSessionStore.getState().setPhase("CONTINUOUS", null, {
      state: "CLOSING_AUCTION",
      at: new Date(Date.now() + 5 * 60_000 + 500).toISOString(),
    });
    render(<TopBar />);
    expect(screen.getByLabelText("session phase").textContent).toBe("Continuous");
    expect(screen.getByText("Closing Auction")).toBeTruthy();
    expect(screen.getByLabelText("time to next session phase").textContent).toMatch(/^in 0[45]:\d\d$/);
  });
});

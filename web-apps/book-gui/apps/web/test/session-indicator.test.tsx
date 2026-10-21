// @vitest-environment jsdom
/** The session indicator (WP-UI01): pm-trader's reading of the session phase. */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { formatCountdown, phaseMeta, SessionIndicator } from "../src/components/SessionIndicator.js";

afterEach(cleanup);

describe("formatCountdown", () => {
  it("is MM:SS below an hour and HH:MM:SS from one", () => {
    expect(formatCountdown(188_230)).toBe("03:08");
    expect(formatCountdown(3_862_000)).toBe("01:04:22");
  });

  it("never runs negative", () => {
    expect(formatCountdown(-5_000)).toBe("00:00");
  });
});

describe("phaseMeta", () => {
  it("uses pm-trader's labels and colours, and Unknown for anything else", () => {
    expect(phaseMeta("CONTINUOUS")).toEqual({ label: "Continuous", badge: "bg-emerald-500 text-black" });
    expect(phaseMeta("UNKNOWN").label).toBe("Unknown");
    expect(phaseMeta(null).label).toBe("Unknown");
  });
});

describe("SessionIndicator", () => {
  it("counts down to a future transition", () => {
    const nextAt = new Date(Date.now() + 90_500).toISOString();
    render(
      <SessionIndicator state="OPENING_AUCTION" nextState="CONTINUOUS" nextAt={nextAt} timeZone="UTC" />,
    );
    expect(screen.getByLabelText("session phase").textContent).toBe("Opening Auction");
    expect(screen.getByText("Continuous")).toBeTruthy();
    expect(screen.getByLabelText("time to next session phase").textContent).toMatch(/^in 01:(30|29)$/);
  });

  it("shows no countdown once the transition time has passed, rather than 00:00", () => {
    const nextAt = new Date(Date.now() - 1_000).toISOString();
    render(
      <SessionIndicator state="CONTINUOUS" nextState="CLOSING_AUCTION" nextAt={nextAt} timeZone="UTC" />,
    );
    expect(screen.queryByLabelText("time to next session phase")).toBeNull();
  });

  it("shows no countdown while the phase itself is unknown", () => {
    const nextAt = new Date(Date.now() + 60_000).toISOString();
    render(<SessionIndicator state="UNKNOWN" nextState="CONTINUOUS" nextAt={nextAt} timeZone="UTC" />);
    expect(screen.getByLabelText("session phase").textContent).toBe("Unknown");
    expect(screen.queryByLabelText("time to next session phase")).toBeNull();
    expect(screen.getByLabelText("exchange clock").textContent).toMatch(/^\d\d:\d\d:\d\d$/);
  });
});

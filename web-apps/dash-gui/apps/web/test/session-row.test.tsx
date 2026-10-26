// @vitest-environment jsdom
/**
 * The Session schedule row: pm-terminal's timetable over the bridge's
 * /api/reference/schedule and the session phase from pm-md-gwy.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReferenceSchedule } from "@edumatcher/dash-types";
import { useDashStore } from "../src/store/useDashStore.js";
import { useRowStore } from "../src/store/useRowStore.js";
import { SessionRow } from "../src/views/rows/SessionRow.js";

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

let reply: () => Response;
const json = (body: ReferenceSchedule) => () => new Response(JSON.stringify(body), { status: 200 });

function show(state: string | null) {
  useDashStore.setState({
    socket: "OPEN",
    sessionTz: "Europe/Stockholm",
    session: state ? { state, nextState: null, nextAt: null } : null,
  });
  return render(<SessionRow />);
}

beforeEach(() => {
  // Monday 21 December, 12:00 in Stockholm. Only Date is faked, so the
  // fetch promises still settle.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-12-21T11:00:00Z"));
  reply = json({ sessions_enabled: true, country: "Sweden", schedule: WEEK });
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => reply()),
  );
  useRowStore.setState({ collapsed: {} });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("session schedule row", () => {
  it("asks the bridge for the schedule and names the phase beside the title", async () => {
    show("CONTINUOUS");
    await screen.findByRole("list", { name: "Session phases" });
    expect(vi.mocked(fetch).mock.calls[0]?.[0]).toBe("/api/reference/schedule");
    expect(screen.getByRole("region", { name: "Session schedule row" }).textContent).toContain(
      "· Continuous",
    );
  });

  it("lights the current phase and puts the clock on the day", async () => {
    show("CONTINUOUS");
    const flow = await screen.findByRole("list", { name: "Session phases" });
    const current = within(flow)
      .getAllByRole("listitem")
      .find((li) => li.getAttribute("aria-current") === "step");
    expect(current?.textContent).toContain("Continuous");
    expect(within(flow).getByText("17:25")).toBeDefined();
    expect(screen.getByTestId("now-marker").textContent).toBe("12:00");
  });

  it("shows the week with its holiday and names the next one that closes the exchange", async () => {
    show("CONTINUOUS");
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
    show("CLOSED");
    await screen.findByRole("list", { name: "Session phases" });
    expect(screen.queryByTestId("now-marker")).toBeNull();
    expect(screen.getByText(/off its timetable/)).toBeDefined();
  });

  it("shows the next trading day while today is closed", async () => {
    vi.setSystemTime(new Date("2026-12-26T11:00:00Z"));
    show("CLOSED");
    expect(await screen.findByText(/Next trading day · Mon 28 Dec/)).toBeDefined();
    expect(screen.queryByTestId("now-marker")).toBeNull();
  });

  it("says so when sessions are disabled", async () => {
    reply = json({ sessions_enabled: false, country: null, schedule: null });
    show(null);
    expect(await screen.findByText(/Sessions are disabled/)).toBeDefined();
  });

  it("says why when the bridge cannot get the schedule", async () => {
    reply = () => new Response('{"error":"upstream_unavailable","message":"x"}', { status: 502 });
    show("CONTINUOUS");
    expect(await screen.findByText(/Timetable unavailable/)).toBeDefined();
  });

  it("explains each part", async () => {
    show("CONTINUOUS");
    for (const label of ["This week", "Timetable", "Next bank holiday"]) {
      expect(await screen.findByRole("button", { name: `${label} help` })).toBeDefined();
    }
  });
});

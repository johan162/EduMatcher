// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import { useAuthStore } from "@/store/useAuthStore";
import { useVenueTimeZoneStore } from "@/store/useVenueTimeZoneStore";
import { apiError, example, navigate, renderApp, signIn, stubApi } from "./helpers";

/**
 * CG19: the GUI learns the venue's session timezone from `GET /api/v1/session`
 * and shows every time in it; until then, or when that fails, times stay in
 * UTC and say so -- never an unnamed zone.
 */
const C = "/api/v1/clearing";
const SESSION = "/api/v1/session";
const SUMMARY = `${C}/summary`;
const HEALTH = `${C}/health`;
const PARTICIPANTS = `${C}/participants`;
const EVENTS = `${C}/session-events`;
const SETTLEMENTS = `${C}/settlements`;
const BALANCES = `${C}/balances`;

function overview(session: unknown): Record<string, unknown> {
  return {
    [SESSION]: session,
    [SUMMARY]: example(SUMMARY),
    [HEALTH]: example(HEALTH),
    [PARTICIPANTS]: example(PARTICIPANTS),
    [EVENTS]: example(EVENTS),
  };
}

const stockholm = () => ({ ...example(SESSION), session_timezone: "Europe/Stockholm" });

beforeEach(() => {
  useAuthStore.getState().logout();
  useVenueTimeZoneStore.setState({ timeZone: null });
  signIn("ADMIN", "OPS01");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("venue session timezone", () => {
  it("shows the Overview freshness line with dates, in the session zone", async () => {
    stubApi(overview(stockholm()));
    renderApp("/overview");
    await waitFor(() =>
      expect(screen.getByText(/Last clearing write/).textContent).toMatch(
        /Last clearing write \d{4}-\d\d-\d\d \d\d:\d\d:\d\d CES?T; newest trade \d{4}-\d\d-\d\d \d\d:\d\d:\d\d CES?T/,
      ),
    );
  });

  it("asks for the timezone once, whatever screens are opened", async () => {
    // Screens that do not show the session phase (the Overview polls it, CG23).
    const stub = stubApi({ ...overview(stockholm()), [`${C}/gateway-sessions`]: example(`${C}/gateway-sessions`) });
    renderApp("/events");
    const table = await screen.findByRole("table", { name: "Session events" });
    await waitFor(() => expect(within(table).getAllByText(/CES?T$/).length).toBeGreaterThan(0));
    navigate("/gateway-sessions");
    await screen.findByRole("table", { name: "Gateway sessions" });
    navigate("/events");
    await screen.findByRole("table", { name: "Session events" });
    expect(stub.calls(SESSION)).toHaveLength(1);
  });

  it("keeps times in labelled UTC when the session request fails", async () => {
    stubApi(overview(apiError(504, "ENGINE_TIMEOUT")));
    renderApp("/overview");
    const line = await screen.findByText(/Last clearing write/);
    await waitFor(() => expect(useVenueTimeZoneStore.getState().timeZone).toBeNull());
    expect(line.textContent).toMatch(/Last clearing write \d{4}-\d\d-\d\d \d\d:\d\d:\d\d UTC/);
  });

  it("shows an EOD run's finish in the session zone, under a header without UTC", async () => {
    stubApi({
      [SESSION]: stockholm(),
      [SETTLEMENTS]: example(SETTLEMENTS),
      [BALANCES]: example(BALANCES),
    });
    renderApp("/eod");
    const runs = await screen.findByRole("table", { name: "EOD runs" });
    expect(within(runs).getByRole("columnheader", { name: /Finished/ }).textContent).not.toMatch(/UTC/);
    await waitFor(() => expect(within(runs).getByText("2026-08-28 17:35:02 CEST")).toBeTruthy());
  });

  it("shows table times in the session zone", async () => {
    stubApi(overview(stockholm()));
    renderApp("/events");
    const table = await screen.findByRole("table", { name: "Session events" });
    await waitFor(() => expect(within(table).getAllByText(/\d\d:\d\d:\d\d CES?T$/).length).toBeGreaterThan(0));
    expect(within(table).queryByText(/UTC$/)).toBeNull();
  });
});

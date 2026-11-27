// @vitest-environment jsdom
/** "Top processes by error count" says why it is empty instead of showing a blank chart. */

import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DashboardView } from "../src/views/Dashboard.js";

// jsdom has no ResizeObserver; Recharts' ResponsiveContainer needs one.
beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderWithByProcess(response: () => Response) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.startsWith("/api/stats/by-process")) return response();
      if (url.startsWith("/api/logs")) return Response.json({ rows: [] });
      if (url.startsWith("/api/issues")) return Response.json({ issues: [] });
      if (url.startsWith("/api/stats/timeseries")) return Response.json({ buckets: [] });
      if (url.startsWith("/api/stats/summary"))
        return Response.json({ server: { total_log_events: 0 }, perProcess: [] });
      return Response.json({});
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DashboardView />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Dashboard top processes by error count", () => {
  it("names its one-hour window in the title", () => {
    renderWithByProcess(() => Response.json({ window: "1h", level: "ERROR", processes: [] }));
    expect(screen.getByText("Top processes by error count — last hour")).toBeTruthy();
  });

  it("says there were no errors in the window rather than drawing an empty chart", async () => {
    renderWithByProcess(() => Response.json({ window: "1h", level: "ERROR", processes: [] }));
    expect(await screen.findByText("No errors in the last hour.")).toBeTruthy();
  });

  it("reports a failed query instead of looking like a quiet hour", async () => {
    renderWithByProcess(() =>
      Response.json({ error: "log_db_unavailable", message: "log.db unavailable" }, { status: 503 }),
    );
    expect(await screen.findByText("Could not load error counts: log.db unavailable")).toBeTruthy();
    expect(screen.queryByText("No errors in the last hour.")).toBeNull();
  });
});

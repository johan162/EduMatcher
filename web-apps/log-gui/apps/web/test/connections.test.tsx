// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ProcessRow } from "@edumatcher/log-types";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { ConnectionsView } from "../src/views/Connections.js";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("shows elapsed time as total hours, minutes and seconds for connected processes", () => {
  const now = Date.parse("2026-11-27T12:00:00Z");
  vi.spyOn(Date, "now").mockReturnValue(now);
  const row = (process: string, elapsedMs: number, disconnected = false): ProcessRow => ({
    process,
    instance: null,
    pid: 1,
    host: "localhost",
    session: process,
    connected_at: "2026-11-26T00:00:00Z",
    last_seen_at: new Date(now - elapsedMs).toISOString(),
    disconnected_at: disconnected ? "2026-11-27T11:00:00Z" : null,
    log_count: 1,
    errorCount: 0,
  });
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  client.setQueryData(["ui-config"], { timezone: "UTC", processSilenceSec: 30 });
  client.setQueryData(["processes"], {
    processes: [
      row("recent", 9_000),
      row("rounded", 59_600),
      row("long", 90_061_000),
      row("future", -5_000),
      row("former-process", 9_000, true),
    ],
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ConnectionsView />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  const cells = (process: string) => within(screen.getByText(process).closest("tr")!).getAllByRole("cell");
  expect(cells("recent")[5]!.textContent).toBe("00:00:09 ago");
  expect(cells("rounded")[5]!.textContent).toBe("00:01:00 ago");
  expect(cells("long")[5]!.textContent).toBe("25:01:01 ago");
  expect(cells("long")[0]!.textContent).toBe("⚠");
  expect(cells("future")[5]!.textContent).toBe("00:00:00 ago");
  expect(cells("former-process")[5]!.textContent).toBe("disconnected");
});

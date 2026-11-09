// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { LedgerResponse, LogRow } from "@edumatcher/log-types";
import { LedgerPanels } from "../src/components/LedgerPanels";

const ROW: LogRow = {
  seq: 7,
  client_ts: "2026-11-09T10:00:00.000Z",
  server_ts: "2026-11-09T10:00:00.001Z",
  process: "pm-log-srv",
  instance: null,
  pid: 1,
  host: "h",
  session: "s",
  level: "ERROR",
  logger: "edumatcher.log_srv.writer",
  module: "writer",
  line: 1,
  has_exception: false,
  truncated: false,
  message:
    "writer thread: failed to persist batch of 50 rows (will retry): disk full",
  tpl: "0123456789ab",
};

const LEDGER: LedgerResponse = {
  available: true,
  entries: {
    "0123456789ab": {
      logger: ROW.logger,
      template:
        "writer thread: failed to persist batch of %d rows (will retry): %s",
      level: "ERROR",
      explanation: "Writing a batch of log rows to log.db failed.",
      actions: ["Check the disk with `df -h`.", "Watch for the error to stop."],
    },
  },
};

function renderWith(ledger: LedgerResponse, row: LogRow) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(ledger), { status: 200 })),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <LedgerPanels row={row} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("LedgerPanels", () => {
  it("shows the explanation and numbered actions, commands as code", async () => {
    renderWith(LEDGER, ROW);
    const explanation = await screen.findByRole("region", {
      name: "Explanation",
    });
    expect(explanation.textContent).toContain(
      "Writing a batch of log rows to log.db failed.",
    );
    const actions = screen.getByRole("region", { name: "Suggested actions" });
    expect(
      [...actions.querySelectorAll("li")].map((li) => li.textContent),
    ).toEqual(["Check the disk with df -h.", "Watch for the error to stop."]);
    expect(actions.querySelector("code")?.textContent).toBe("df -h");
  });

  it("says when a WARNING+ message has no entry", async () => {
    renderWith(LEDGER, { ...ROW, tpl: "ffffffffffff" });
    expect(
      await screen.findByText(
        "No ledger entry for this message (tpl=ffffffffffff).",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Explanation" })).toBeNull();
  });

  it("says why when the ledger is unavailable", async () => {
    renderWith(
      {
        available: false,
        reason: "pm-log-cli is not installed or not on PATH",
        entries: {},
      },
      ROW,
    );
    expect(
      await screen.findByText(
        "No explanations available: pm-log-cli is not installed or not on PATH",
      ),
    ).toBeTruthy();
  });

  it("shows nothing, and fetches nothing, below WARNING", () => {
    const { container } = renderWith(LEDGER, {
      ...ROW,
      level: "INFO",
      tpl: null,
    });
    expect(container.textContent).toBe("");
    expect(fetch).not.toHaveBeenCalled();
  });
});

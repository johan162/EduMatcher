// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import { ApiError, ContractError, NetworkError } from "@/api/errors";
import { QueryState } from "@/components/shared/QueryState";
import { newQueryClient } from "./helpers";

/**
 * Every data view renders through QueryState, so the distinction the design
 * insists on is made once: an unavailable ledger or a refused request is never
 * shown as an empty table, and an empty table is a true zero.
 */
afterEach(cleanup);

function View({ fn }: { fn: () => Promise<string[]> }) {
  const query = useQuery({ queryKey: ["t", fn], queryFn: fn });
  return (
    <QueryState query={query} isEmpty={(rows) => rows.length === 0} emptyTitle="No positions">
      {(rows) => <p>rows: {rows.join(",")}</p>}
    </QueryState>
  );
}

function show(fn: () => Promise<string[]>) {
  render(
    <QueryClientProvider client={newQueryClient()}>
      <View fn={fn} />
    </QueryClientProvider>,
  );
}

describe("QueryState", () => {
  it("shows a busy skeleton while the first fetch is in flight", () => {
    show(() => new Promise(() => {}));
    expect(screen.getByRole("status").getAttribute("aria-busy")).toBe("true");
  });

  it("renders the data", async () => {
    show(async () => ["AAPL"]);
    expect(await screen.findByText("rows: AAPL")).toBeTruthy();
  });

  it("an empty result is a true zero, said in words", async () => {
    show(async () => []);
    expect(await screen.findByText("No positions")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a 403 is a forbidden state, with the server's reason", async () => {
    show(async () => {
      throw new ApiError(403, "SCOPE_DENIED", "Gateway TRADER01 may read only its own data");
    });
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/not permitted/i);
    expect(alert.textContent).toContain("SCOPE_DENIED");
  });

  it("an unavailable ledger is an error with a retry, not an empty table", async () => {
    let attempts = 0;
    show(async () => {
      attempts += 1;
      throw new ApiError(503, "CLEARING_DB", "Clearing ledger unavailable: not found");
    });
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("CLEARING_DB");
    expect(screen.queryByText("No positions")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByRole("alert");
    expect(attempts).toBeGreaterThanOrEqual(2);
  });

  it("a response that breaks the contract says so", async () => {
    show(async () => {
      throw new ContractError("/api/v1/clearing/positions", "positions.0.net_qty: expected number");
    });
    expect((await screen.findByRole("alert")).textContent).toMatch(/API contract/);
  });

  it("an unreachable gateway says so", async () => {
    show(async () => {
      throw new NetworkError("Failed to fetch");
    });
    expect((await screen.findByRole("alert")).textContent).toMatch(/Cannot reach the API gateway/);
  });
});

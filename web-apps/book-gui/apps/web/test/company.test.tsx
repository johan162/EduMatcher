// @vitest-environment jsdom
/** The top bar's company info drawer: the watched symbol's profile, via the bridge. */

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { CompanyButton } from "../src/components/company/CompanyButton";
import { useBookStore } from "../src/store/useBookStore";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  useBookStore.setState({ watched: null });
});

const NULLS = Object.fromEntries(
  [
    "headquarters",
    "purpose",
    "key_market",
    "market_position",
    "origin",
    "founders",
    "founder_story",
    "founded_year",
    "ipo_year",
    "ipo_valuation_musd",
    "ceo_name",
    "ceo_since",
    "ceo_industry_years",
    "employees",
    "fiscal_year",
    "revenue_musd",
    "net_income_musd",
    "revenue_growth_pct",
    "operating_margin_pct",
    "free_cash_flow_musd",
    "market_cap_musd",
    "dividend_yield_pct",
    "debt_to_equity",
    "credit_rating",
    "competitors",
    "key_risk",
    "years_in_business",
    "ceo_tenure_years",
    "pe_ratio",
    "ps_ratio",
    "net_margin_pct",
  ].map((k) => [k, null]),
);

const PROFILE = {
  ...NULLS,
  symbol: "AAPL",
  name: "Apple Orchard Inc.",
  sector: "INFORMATION_TECHNOLOGY",
  industry: "Hardware",
  headquarters: "Cupertino",
  market_cap_musd: 2500000,
  pe_ratio: 28.43,
  revenue_growth_pct: 4.5,
  key_risk: "Supply chain",
};

function stubFetch(status: number, body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("CompanyButton", () => {
  it("is disabled until a symbol is watched", () => {
    render(<CompanyButton />);
    expect((screen.getByRole("button", { name: "Company info" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("opens a drawer with one Company tab showing the watched symbol's profile; Escape closes it", async () => {
    useBookStore.setState({ watched: "AAPL" });
    const fetchMock = stubFetch(200, PROFILE);
    render(<CompanyButton />);
    fireEvent.click(screen.getByRole("button", { name: "Company info" }));

    expect(fetchMock).toHaveBeenCalledWith("/api/company/AAPL");
    const drawer = screen.getByRole("dialog", { name: "AAPL company" });
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Company"]);
    expect(await screen.findByRole("heading", { name: "Apple Orchard Inc." })).toBeTruthy();
    expect(drawer.textContent).toContain("Information technology · Hardware · Cupertino");
    expect(drawer.textContent).toContain("2,500,000 M$");
    expect(drawer.textContent).toContain("28.4");
    expect(drawer.textContent).toContain("+4.50%");
    expect(drawer.textContent).toContain("Supply chain");
    expect(screen.getByRole("button", { name: "Market cap help" })).toBeTruthy();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("says when the venue has no company database", async () => {
    useBookStore.setState({ watched: "AAPL" });
    stubFetch(503, { error: { code: "COMPANY_DB_UNAVAILABLE" } });
    render(<CompanyButton />);
    fireEvent.click(screen.getByRole("button", { name: "Company info" }));
    expect(await screen.findByText(/company database is not available/)).toBeTruthy();
  });

  it("says when the symbol has no profile", async () => {
    useBookStore.setState({ watched: "AAPL" });
    stubFetch(404, { error: { code: "UNKNOWN_COMPANY" } });
    render(<CompanyButton />);
    fireEvent.click(screen.getByRole("button", { name: "Company info" }));
    expect(await screen.findByText("No company profile for AAPL.")).toBeTruthy();
  });
});

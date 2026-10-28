/**
 * `pm-api-gwy` `GET /api/v1/companies/{symbol}`, passed through unmodified by
 * the bridge: one pm-compdb-cli company profile. Money is in millions of USD;
 * the last five fields are derived by the database view.
 */

export interface CompanyProfile {
  symbol: string;
  name: string;
  sector: string;
  industry: string;
  headquarters: string | null;
  purpose: string | null;
  key_market: string | null;
  market_position: string | null;
  origin: string | null;
  founders: string | null;
  founder_story: string | null;
  founded_year: number | null;
  ipo_year: number | null;
  ipo_valuation_musd: number | null;
  ceo_name: string | null;
  ceo_since: number | null;
  ceo_industry_years: number | null;
  employees: number | null;
  fiscal_year: number | null;
  revenue_musd: number | null;
  net_income_musd: number | null;
  revenue_growth_pct: number | null;
  operating_margin_pct: number | null;
  free_cash_flow_musd: number | null;
  market_cap_musd: number | null;
  dividend_yield_pct: number | null;
  debt_to_equity: number | null;
  credit_rating: string | null;
  /** Comma-separated tickers. */
  competitors: string | null;
  key_risk: string | null;
  years_in_business: number | null;
  ceo_tenure_years: number | null;
  pe_ratio: number | null;
  ps_ratio: number | null;
  net_margin_pct: number | null;
}

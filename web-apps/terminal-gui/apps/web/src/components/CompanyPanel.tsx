import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { HttpError, api } from "../lib/api.js";
import type { CompanyProfile } from "@edumatcher/terminal-types";
import { companyHelp } from "../lib/companyHelp.js";
import { InfoTip } from "./shared/InfoTip.js";

/** Whole units, grouped: the same rounding as pm-trader's Company tab. */
const formatQty = (v: number) => v.toLocaleString("en-US", { maximumFractionDigits: 0 });
const formatPct = (v: number | null) => (v === null ? "—" : `${v.toFixed(2)}%`);
const musd = (v: number | null) => (v === null ? "—" : `${formatQty(v)} M$`);
const ratio = (v: number | null) => (v === null ? "—" : v.toFixed(1));
const signedPct = (v: number | null) => (v !== null && v > 0 ? `+${formatPct(v)}` : formatPct(v));
const years = (v: number | null) => (v === null ? "" : ` (${v} y)`);

/** "CONSUMER_DISC" → "Consumer disc". */
function words(v: string): string {
  const s = v.replace(/_/g, " ").toLowerCase();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** The "i" for a label, from the company help; nothing for a label without any. */
function Tip({ label }: { label: string }) {
  const help = companyHelp(label);
  return help ? <InfoTip label={label} help={help} /> : null;
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border bg-bg-subtle px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-fg-faint">
        {label} <Tip label={label} />
      </div>
      <div className="text-sm font-mono text-fg">{value}</div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h4 className="text-[10px] uppercase tracking-wide text-fg-faint">{title}</h4>
      {children}
    </section>
  );
}

/** A labelled line of prose, left out when the database has nothing for it. */
function Line({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <p className="text-xs text-fg-subtle">
      <span className="text-fg-subtle">{label}: </span>
      <Tip label={label} />{" "}
      {value}
    </p>
  );
}

function Profile({ c }: { c: CompanyProfile }) {
  const where = [words(c.sector), c.industry, c.headquarters].filter(Boolean).join(" · ");
  const fy = c.fiscal_year === null ? "" : ` (FY${c.fiscal_year})`;
  const ceo = c.ceo_name
    ? `${c.ceo_name}${c.ceo_since === null ? "" : `, since ${c.ceo_since}${years(c.ceo_tenure_years)}`}`
    : null;
  const ipo =
    c.ipo_year === null
      ? null
      : `${c.ipo_year}${c.ipo_valuation_musd === null ? "" : ` at ${musd(c.ipo_valuation_musd)}`}`;
  const origin = c.origin ? `${words(c.origin)}${c.founders ? ` — ${c.founders}` : ""}` : c.founders;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h3 className="text-lg font-semibold text-accent">{c.name}</h3>
        <div className="text-xs text-fg-subtle">{where}</div>
        {c.purpose && <p className="text-sm text-fg mt-2">{c.purpose}</p>}
      </div>

      <Section title="Valuation">
        <div className="grid grid-cols-3 gap-2">
          <Figure label="Market cap" value={musd(c.market_cap_musd)} />
          <Figure label="P/E" value={ratio(c.pe_ratio)} />
          <Figure label="P/S" value={ratio(c.ps_ratio)} />
          <Figure label="Dividend yield" value={formatPct(c.dividend_yield_pct)} />
          <Figure
            label="Debt / equity"
            value={c.debt_to_equity === null ? "—" : c.debt_to_equity.toFixed(2)}
          />
          <Figure label="Credit rating" value={c.credit_rating ?? "—"} />
        </div>
      </Section>

      <Section title={`Financials${fy}`}>
        <div className="grid grid-cols-3 gap-2">
          <Figure label="Revenue" value={musd(c.revenue_musd)} />
          <Figure label="Revenue growth" value={signedPct(c.revenue_growth_pct)} />
          <Figure label="Net income" value={musd(c.net_income_musd)} />
          <Figure label="Net margin" value={formatPct(c.net_margin_pct)} />
          <Figure label="Operating margin" value={formatPct(c.operating_margin_pct)} />
          <Figure label="Free cash flow" value={musd(c.free_cash_flow_musd)} />
        </div>
      </Section>

      <Section title="Position">
        <Line label="Key market" value={c.key_market} />
        <Line label="Market position" value={c.market_position} />
        <Line label="Competitors" value={c.competitors} />
        <Line label="Key risk" value={c.key_risk} />
      </Section>

      <Section title="Management">
        <Line label="CEO" value={ceo} />
        <Line
          label="Years in the industry"
          value={c.ceo_industry_years === null ? null : String(c.ceo_industry_years)}
        />
        <Line label="Employees" value={c.employees === null ? null : formatQty(c.employees)} />
      </Section>

      <Section title="History">
        <Line
          label="Founded"
          value={c.founded_year === null ? null : `${c.founded_year}${years(c.years_in_business)}`}
        />
        <Line label="IPO" value={ipo} />
        <Line label="Origin" value={origin} />
        {c.founder_story && <p className="text-xs text-fg-subtle">{c.founder_story}</p>}
      </Section>
    </div>
  );
}

/**
 * The company behind a symbol, from pm-compdb-cli's database via the gateway:
 * the name first, then what a trader weighs most — valuation, financials,
 * competitive position — and management and history last.
 */
export function CompanyPanel({ symbol }: { symbol: string }) {
  const query = useQuery({
    queryKey: ["company", symbol],
    queryFn: () => api.company(symbol),
    // A profile is static reference data; a 404 or 503 will not fix itself in a re-poll.
    retry: false,
    staleTime: 5 * 60_000,
  });

  if (query.isLoading) return <p className="text-xs text-fg-subtle">Loading company profile…</p>;
  if (query.data?.name) return <Profile c={query.data} />;
  const unavailable = query.error instanceof HttpError && query.error.status === 503;
  return (
    <p className="text-xs text-fg-faint">
      {unavailable
        ? "The company database is not available on this venue (pm-compdb-cli init builds it)."
        : `No company profile for ${symbol}.`}
    </p>
  );
}

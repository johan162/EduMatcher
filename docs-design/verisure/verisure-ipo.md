# Verisure: valuing a leveraged, capex-heavy security subscriber base with pm-valuation

*J. Persson, 2026*

This document values **Verisure plc (VSURE)**, the Swiss-headquartered home and
small-business security monitoring group, with `pm-valuation`, the same way
[EduMatcher-valuation.md](EduMatcher-valuation.md) values Tornfalk Security AB
and [ai-ipo.md](ai-ipo.md) values Nimbus Cognition: every input with its
source, every formula as the code applies it, and every intermediate number,
so each step can be checked by hand.

Unlike Nimbus, Verisure is **not fictive**. It is a real company that actually
listed on Nasdaq Stockholm on 8 October 2025 — one year to the day before this
document's "as of" date — and has reported two full quarters as a public
company since. That makes this a different kind of exercise from Nimbus: every
number below that is marked "you" is either a disclosed fact from Verisure's
own prospectus-era and post-IPO reporting, or an explicit, labelled assumption
where the public record doesn't give an exact figure. Section 10 then checks
the model's verdict against what the market actually did — something no
fictive exercise can offer. **This is an educational exercise in applying a
teaching DCF, not investment advice, and not a professional valuation.**

Two questions drive the analysis, chosen because they are genuinely uncertain
and the model can isolate them cleanly:

1. **How long does installed security hardware really last before it must be
   replaced?** Case A: 6 years. Case B: 10 years. Verisure discloses its
   *capex intensity* (capex ÷ revenue, ≈24–26%) precisely every quarter, but
   not the useful life it implies.
2. **How much does leverage alone cost the equity?** Verisure is a former
   private-equity buyout, and even after the IPO's paydown it still carries
   roughly €7.7bn of pre-IPO net debt at 4.8× EBITDA — far more than any
   growth-stock DCF case this tool was designed around.

## 1. Results

| | Case A: 6-year hardware life | Case B: 10-year hardware life |
|---|---:|---:|
| Capex, % of revenue | 25% | 25% |
| Enterprise value, DCF | −€2,352m | −€1,148m |
| DCF price per share | −€12.76 | −€11.26 |
| Comparables price per share (5× next year's revenue) | €12.11 | €12.11 |
| Fair value per share (70% DCF, 30% comparables) | **−€5.30** | **−€4.25** |
| Monte Carlo median fair value | −€6.36 | −€5.34 |
| Monte Carlo: P(DCF equity below zero) | 99.8% | 99.0% |
| **Verdict** | **POSTPONE** | **POSTPONE** |
| *Isolating leverage: same business, debt set to zero* | fair value **+€4.36**, PROCEED | (identical mechanism) |

In short:

- **On this model, Verisure's own disclosed leverage — not its operations —
  is what sinks the equity value.** The DCF generates a near-break-even to
  modestly negative enterprise value (−€2.35bn to −€1.15bn, depending on
  hardware life); the dominant term in the bridge from enterprise value to
  equity value is "+ cash − debt" at **−€7.73bn**, Verisure's actual net debt
  immediately before its IPO. Removing the debt alone (keeping every
  operating assumption fixed) flips the verdict from POSTPONE to PROCEED at
  a positive €4.36 per share.
- **Hardware life matters much less here than it did for Nimbus's GPUs.**
  Stretching the depreciation life from 6 to 10 years raises the DCF price by
  only €1.50 (from −€12.76 to −€11.26), because the capex itself (25% of
  revenue, taken directly from Verisure's own disclosed capex intensity) is
  fixed in both cases — only the *pace* of writing it off changes.
- **The comparables valuation (€12.11, at the 5× EV/revenue multiple this
  analysis assumes) is close to what the real market actually paid.**
  Verisure's real IPO priced near €13.25–13.68 per share, and even after
  the stock's subsequent decline, that comparables figure is far closer to
  reality than the fully-levered DCF — because real IPO investors price
  these businesses off EV/EBITDA and EV/revenue multiples applied to the
  *operating* business, then let the actual capital structure fall out of
  the market price, rather than hoping a textbook unlevered FCFF DCF
  organically clears €7.7bn of net debt.
- **The real outcome one year on is consistent with this picture.** Verisure
  listed at a premium to any pure cash-flow valuation, popped on debut, and
  by this document's "as of" date (8 October 2026) traded at €7.89 — down
  46% from its one-year peak and already below even this model's
  comparables-only value. See §10.

## 2. What is public

All figures are as reported by Verisure plc itself (annual report, quarterly
results, investor-relations key figures) or by the press covering the IPO.
Money in the model's inputs below is in euros (**EUR**), Verisure's actual
reporting and trading currency — not the Swedish krona the `se` market
preset's cosmetic currency label implies; every `se`-market default used here
(risk-free rate, ERP, tax rate, gross spread, etc.) is read as its literal
percentage or euro value, the FX conversion never applies because every money
figure below was supplied directly.

| Fact | Value | Date | Source |
|---|---|---|---|
| Listing | Nasdaq Stockholm, ticker VSURE; completed the offering | 8 Oct 2025 | [Wikipedia][wiki], [FT][ft] |
| Target price range / implied market cap | €12.25–13.50/share; €12.9–13.9bn | 29 Sep 2025 | [WSJ][wsj] |
| Amount raised; resulting valuation | €3.2bn raised; €13.7bn post-money | 8 Oct 2025 | [Wikipedia][wiki], [FT][ft] |
| First-day move | shares "jump 21% on debut" | 8 Oct 2025 | [FT][ft] |
| Pre-IPO shares (fully diluted) | 800,000,000 | at listing | [Verisure Q2 2026 report][q2]&nbsp;(EPS note) |
| Total shares after listing (incl. IPO-day issuance) | 1,033,962,264 | 8 Oct 2025 | [Verisure Q2 2026 report][q2] |
| Shares outstanding, most recent | 1,036,031,534 | 30 Sep 2026 | [Verisure press release][shares] |
| Pre-owner | Hellman & Friedman (sole owner pre-IPO) | 2025 | [Wikipedia][wiki] |
| Customers served | ~6.4m families and small businesses, 18 countries | Q2 2026 | [Verisure investors][investors] |
| Total customers (period end) | 6,377,300 (Q2 2026); 5,831,400 (Q2 2025, pre-IPO) | Jul 2026 | [Verisure Q2 2026 report][q2] |
| ARPU (monthly) | €48.20 (Q2 2026); €46.6 (Q2 2025, pre-IPO) | Jul 2026 | [Verisure Q2 2026 report][q2] |
| Annualised attrition (churn) | 7.4–7.5%, stable | Q2 2026 | [Verisure Q2 2026 report][q2] |
| Average customer lifetime | ~15 years | 2026 | [Verisure investors][investors] |
| Revenue, FY2025 | €3,745m, +9.9% y/y | FY2025 | [Verisure Annual Report 2025][ar2025] |
| ARR, FY2025 year-end | €3,448m, +12.4% y/y | FY2025 | [Verisure Annual Report 2025][ar2025] |
| ARR, latest (Q2 2026) | €3,619.8m, +12.2% y/y | Jul 2026 | [Verisure Q2 2026 report][q2] |
| Adjusted EBIT margin | 26.3% (Q2 2026); 25.4% (Q2 2025, pre-IPO) | Jul 2026 | [Verisure Q2 2026 report][q2] |
| Adjusted EBITDA margin (group) | 45.7% (Q2 2026) | Jul 2026 | [Verisure Q2 2026 report][q2] |
| Portfolio Services Adjusted EBITDA margin | 74.1% (servicing the existing base only) | Jul 2026 | [Verisure Q2 2026 report][q2] |
| Cost per acquisition (CPA) | €1,644 (Q2 2026, incl. rebrand); €1,474 (Q2 2025) | Jul 2026 | [Verisure Q2 2026 report][q2] |
| Capital expenditure intensity (capex ÷ revenue) | 23.9% (Q2 2026); 25.8% (Q2 2025) | Jul 2026 | [Verisure Q2 2026 report][q2] |
| Full-time employees | 24,767 | 2026 | [Yahoo Finance][yahoo] |
| Net debt / LTM net leverage, pre-IPO | €7,731.8m / 4.8× | Jun 2025 | [Verisure Q2 2026 report][q2] |
| Net debt / LTM net leverage, latest | €4,912.8m / 2.7× | Jun 2026 | [Verisure Q2 2026 report][q2] |
| Credit rating | Fitch BBB− (first investment-grade rating) | 16 Jun 2026 | [Verisure Q2 2026 report][q2] |
| Weighted average cost of debt, post-refinancing | ~4.25% | 2026 | [Verisure Q2 2026 report][q2] |
| Cash and cash equivalents | €21.8m (Jun 2025, pre-IPO) | Jun 2025 | [Verisure Q2 2026 report][q2] |
| Interim dividend | €0.10/share, 35% of H1 2026 Adjusted Net Income | 30 Jul 2026 | [Verisure Q2 2026 report][q2] |
| Share price, 8 Oct 2026 ("today") | €7.89, market cap €8.158bn | 8 Oct 2026 | [Yahoo Finance][yahoo] |
| 52-week range | €7.80–€16.61 | as of 8 Oct 2026 | [Yahoo Finance][yahoo] |
| 1-year total return | −45.84% | as of 8 Oct 2026 | [Yahoo Finance][yahoo] |

## 3. From public facts to model answers

Verisure lists in Sweden (`market: se`): a prospectus approved by
Finansinspektionen, Nasdaq Stockholm, and the EU Prospectus Regulation — all
true to the real listing. No sector preset fits a professionally-monitored
alarm subscription business exactly, so the model starts from
`telecom_operator` (the closest structural match: a subscriber base, heavy
infrastructure investment per customer, long asset life, moderate churn) and
overrides most of its defaults. Year 0 is the last reported pre-IPO figure
(mid-2025); year 1 is the first forecast year.

| Field | Answer | Why |
|---|---|---|
| Name, ticker | Verisure plc, VSURE | Real |
| Sector preset | telecom_operator | Closest structural fit: subscriber base, capex-per-customer, long asset life |
| Market structure | dominant (30% ceiling) | Verisure states it is #1 in 14 of 18 markets and "~6× larger than the next biggest competitor" |
| Total addressable market | €55bn | Assumption: global professionally-monitored residential/SMB security services |
| SAM share | 40% | Verisure's footprint (Europe + Latin America) as a share of the global TAM |
| Revenue, year 0 | €3.41bn | Derived: FY2025 revenue €3,745m ÷ 1.099 (its own disclosed +9.9% y/y growth) |
| Customers now | 5,831,400 | Actual Q2 2025 total subscribers — the last reported count before the real Oct 2025 IPO |
| ARPU | €559/year | €46.6/month (Q2 2025) × 12 |
| Churn | 7.4% | Disclosed LTM attrition |
| Customer growth, year 1 | 9% | Below the disclosed +9.4% y/y total-portfolio growth (which includes the Mexico acquisition); a mature, large-base business, not a startup |
| Headcount | 24,767 | Disclosed full-time employees |
| Loaded cost per employee | €48,000 | Assumption: blended across 18 countries including lower-cost Latin American markets |
| Staff split R&D / S&M / G&A / Ops | 3 / 12 / 10 / 75% | §3.1: most of the 24,767 staff are field technicians and call-centre/ARC operators, not a sales force (see below) |
| Infrastructure per customer | €60/year | Assumption: the non-labour share of servicing cost (connectivity, consumables, third-party monitoring); see §3.1 |
| Paid acquisition cost per customer | €1,000 | §3.1: the *expensed* share of the disclosed €1,644 cost-per-acquisition; the rest is capitalised and flows through capex |
| Capex | 25% | Verisure's own disclosed capital expenditure intensity (23.9–25.8%) |
| Useful life | 6 (A) / 10 (B) | Not disclosed; the two cases bracket a plausible range for installed alarm hardware |
| Cash | €22m | Disclosed cash, Jun 2025 (pre-IPO) |
| Debt | €7,754m | Gross debt sized so cash − debt = −€7,731.8m, Verisure's own disclosed pre-IPO net debt |
| Tax losses carried forward | €300m | Assumption, informed by reported net losses in the years before the IPO |
| Beta, years 1–5 / year 6 on | 1.1 / 0.9 | A mature, moderately-levered consumer-subscription business, not a speculative grower |
| Target debt ratio D/V; cost of debt | 35%; 6.0% | Assumption: pre-refinancing, sub-investment-grade blended cost of debt (before the 2026 BBB− upgrade cut Verisure's own WACD to ~4.25%) |
| Pre-IPO shares | 800,000,000 | Disclosed: the share count immediately before the IPO-day issuance |
| Primary raise | €3.2bn | Disclosed amount raised in the listing |
| Gross spread, other expenses | 3%, €30m | The `se` market default for a European IPO |
| Comparable EV / NTM revenue | 5× | Assumption, informed by Verisure's own actual offer-price-implied multiple and the model's `consumer_subscription` preset default |
| Minimum market cap (floor) | none | Unlike Nimbus, there is no prior-round "down round" floor to defend |

Everything else keeps its `se`-market or `telecom_operator` default.

### 3.1 Avoiding double-counting: the one subtlety this sector doesn't have in software

Verisure's economics put real money through *two* channels the model also has
two channels for, and getting the split wrong silently double-charges the
same euro twice:

- **Cost to serve existing customers.** Verisure discloses a Recurring
  Monthly Cost (RMC) of about €12.5 per customer per month — roughly €150 a
  year — against a *servicing-segment* ("Portfolio Services") Adjusted
  EBITDA margin of 74%. That €150 is a blended figure covering both
  non-labour costs (connectivity, consumables, third-party monitoring) *and*
  the labour cost of Verisure's own call-centre and field-maintenance staff.
  The model keeps those in two separate places — `infra_per_customer` (no
  staff) and the `ops` share of headcount cost — so using the full €150 as
  `infra_per_customer` *and* assigning most of the 24,767-strong workforce to
  `ops` charges the servicing labour twice. The model here uses
  `infra_per_customer: 60` (the non-labour share) and lets the 75% `ops`
  staff split carry the labour share instead.
- **Cost to win a new customer.** Verisure discloses a blended Cost Per
  Acquisition (CPA) of €1,644–1,474 per new customer, covering sales
  commissions, marketing, *and* the capitalised cost of the installed
  hardware itself (its own disclosure splits this explicitly into
  "Customer Acquisition expenses" and "Customer Acquisition capital
  expenditure"). The model's `cac_paid` field is an immediate expense; its
  `capex_pct` field is separately capitalised and depreciated over
  `useful_life`. Charging the *full* CPA through `cac_paid` while *also*
  running `capex_pct` at Verisure's real 25% double-counts the hardware
  portion of each new installation. This analysis therefore splits it:
  `cac_paid: 1,000` is the expensed (labour and marketing) share; the
  hardware share is left inside the 25% capex figure, which already includes
  it.

Both corrections matter in the same direction — without them, the model's
first attempt at this scenario priced the DCF at roughly −€40 per share,
far below either case reported here.

### 3.2 What the model cannot express

- **Capitalised labour.** IFRS lets Verisure capitalise part of its
  customer-acquisition *labour* cost onto the balance sheet (as part of the
  customer-portfolio intangible asset) rather than expensing it immediately.
  This teaching model has no such mechanism: every euro of `cac_paid` and
  every euro of `ops`/`snm` staff cost hits the income statement the year it
  is spent. That is the single biggest reason this model's EBIT margin
  (−3.0% in year 1, rising to only 2.4–5.5% by year 10) sits far below
  Verisure's own disclosed Adjusted EBIT margin of 26%: a meaningful share of
  what this model treats as a current-year expense, Verisure's own
  accounting treats as an asset to be amortised over many future years.
  "Adjusted EBITDA" for subscriber-acquisition-heavy businesses (telecoms,
  alarm companies, gym chains) has long drawn exactly this criticism from
  skeptical investors; this exercise's cash-flow-first DCF comes down on the
  stricter side of that debate by construction.
- **A single, static leverage ratio.** Verisure's own leverage fell from
  4.8× net debt/EBITDA (pre-IPO) to 2.7× within nine months, financed partly
  by the IPO proceeds and partly by strong free cash flow. The model takes
  one constant `debt_ratio`/`cost_of_debt` pair for the whole discount-rate
  calculation; it cannot model a de-levering glide path, so the 35%/6.0%
  assumption here is a blend across the forecast, not a snapshot of any one
  year.
- **Growth capex and the asset-replacement cycle**, exactly as noted for
  Nimbus's GPUs: capex is a fixed share of revenue, so it does not separate
  hardware for *new* customers from hardware *replacing* churned or ageing
  installations.

## 4. Case A: 6-year hardware life

All amounts in millions of euros (€m) unless stated; customers in absolute
numbers. The model computes in full precision and rounds only for display.

### 4.1 Market and customers

| | Y1 | Y2 | Y3 | Y4 | Y5 | Y6 | Y7 | Y8 | Y9 | Y10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| TAM (€bn) | 58.3 | 61.5 | 64.7 | 67.7 | 70.6 | 73.2 | 75.7 | 77.9 | 79.8 | 81.4 |
| SAM (€bn) | 23.32 | 24.62 | 25.87 | 27.08 | 28.22 | 29.29 | 30.27 | 31.14 | 31.90 | 32.54 |
| Customers, end | 6,356,226 | 6,868,201 | 7,358,951 | 7,821,034 | 8,248,181 | 8,635,411 | 8,979,020 | 9,276,485 | 9,526,310 | 9,727,857 |
| Penetration of the ceiling | 52.3% | 55.1% | 57.7% | 60.2% | 62.4% | 64.5% | 66.5% | 68.2% | 69.8% | 71.3% |
| ARPU (€) | 576 | 592 | 609 | 625 | 641 | 657 | 672 | 687 | 702 | 716 |
| **Revenue (€m)** | 3,508.6 | 3,917.1 | 4,331.2 | 4,744.5 | 5,150.7 | 5,544.1 | 5,919.0 | 6,270.8 | 6,595.1 | 6,888.5 |
| Revenue growth | 2.9% | 11.6% | 10.6% | 9.5% | 8.6% | 7.6% | 6.8% | 5.9% | 5.2% | 4.4% |

Year 1 growth (2.9%) is low because year 0 (€3.41bn) is already a trailing
full-year figure close to the real FY2025 actual (€3.745bn) once nine months
of further growth are added back — a mature base, not a ramping startup.

### 4.2 Unit economics and headcount

| | Year 1 | Year 5 | Year 10 |
|---|---:|---:|---:|
| LTV (ARPU × GM / churn) | 4,266 | 4,899 | 5,336 |
| Full CAC (S&M / gross adds) | 1,190 | 1,376 | 1,686 |
| LTV / CAC | 3.6 | 3.6 | 3.2 |
| CAC payback (months) | 45.2 | 45.5 | 51.2 |

A payback of 45–51 months (under 4 years) against a 15-year average customer
lifetime is a healthy ratio — consistent with Verisure's own disclosed
Acquisition Multiple of 3.6–3.8×.

| | Y1 | Y5 | Y10 |
|---|---:|---:|---:|
| Headcount | 25,510 | 31,053 | 36,419 |
| Staff cost (€m) | 1,273.5 | 1,813.5 | 2,587.6 |
| Revenue / employee (€) | 137,540 | 165,871 | 189,146 |

### 4.3 Income statement

| €m | Y1 | Y2 | Y3 | Y4 | Y5 | Y6 | Y7 | Y8 | Y9 | Y10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Revenue | 3,508.6 | 3,917.1 | 4,331.2 | 4,744.5 | 5,150.7 | 5,544.1 | 5,919.0 | 6,270.8 | 6,595.1 | 6,888.5 |
| Infrastructure + other COGS + ops staff | 1,585.0 | 1,743.0 | 1,905.4 | 2,070.6 | 2,238.2 | 2,406.1 | 2,573.5 | 2,736.2 | 2,891.5 | 3,037.9 |
| **Gross profit** | 1,923.6 | 2,174.1 | 2,425.8 | 2,673.6 | 2,912.5 | 3,137.9 | 3,345.3 | 3,530.5 | 3,683.9 | 3,801.7 |
| Gross margin | 54.8% | 55.5% | 56.0% | 56.4% | 56.5% | 56.6% | 56.5% | 56.3% | 55.9% | 55.2% |
| S&M (incl. €985–1,218m paid acquisition) | 1,137.9 | 1,210.3 | 1,275.8 | 1,333.6 | 1,383.7 | 1,426.1 | 1,461.1 | 1,489.1 | 1,511.5 | 1,528.8 |
| R&D, G&A, SBC | 463.8 | 510.2 | 558.0 | 606.8 | 656.2 | 705.9 | 755.3 | 804.7 | 855.3 | 907.3 |
| **EBITDA** | 321.9 | 453.6 | 592.0 | 733.1 | 872.6 | 1,005.8 | 1,128.7 | 1,236.7 | 1,317.1 | 1,365.7 |
| D&A | 426.2 | 501.4 | 581.0 | 664.7 | 751.6 | 840.9 | 931.8 | 1,023.1 | 1,113.9 | 1,203.0 |
| **EBIT** | −104.4 | −47.8 | 11.0 | 68.5 | 121.0 | 164.9 | 197.0 | 213.6 | 203.2 | 162.7 |
| EBIT margin | −3.0% | −1.2% | 0.3% | 1.4% | 2.3% | 3.0% | 3.3% | 3.4% | 3.1% | 2.4% |

EBIT margin peaks at 3.4% in year 8 and then falls again: a 6-year life means
D&A keeps pace with — and eventually outgrows — a capex base that is itself
25% of a growing revenue line, exactly the compounding pattern Nimbus's
3-year GPU case showed (§4.3 of [ai-ipo.md](ai-ipo.md)).

### 4.4 Free cash flow and the DCF

| €m | Y1 | Y2 | Y3 | Y4 | Y5 | Y6 | Y7 | Y8 | Y9 | Y10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| EBIT − tax + D&A | 321.9 | 453.6 | 581.0 | 664.6 | 751.6 | 840.9 | 909.1 | 979.1 | 1,072.0 | 1,169.5 |
| − Capex − ΔNWC | −874.2 | −967.0 | −1,070.4 | −1,173.7 | −1,275.5 | −1,374.2 | −1,468.6 | −1,557.1 | −1,639.1 | −1,713.3 |
| **= FCFF** | −552.3 | −513.5 | −478.4 | −440.6 | −402.9 | −368.4 | −362.4 | −364.4 | −363.8 | −381.2 |

```text
k_e1 = 3.00% + 1.1 × 5.6% + 0% + 2.0% = 11.16%     years 1–5
k_e2 = 3.00% + 0.9 × 5.6% + 0%        = 8.04%      year 6 on
Debt D/V 35%; after-tax cost of debt = 6.0% × (1 − 20.6%) = 4.76%
r1 = (1 − 35%) × 11.16% + 35% × 4.76% = 8.92%      years 1–5
r2 = (1 − 35%) × 8.04%  + 35% × 4.76% = 6.89%      year 6 on and the terminal value
```

| Year | Rate | FCFF | PV |
|---:|---:|---:|---:|
| 1–5 (stage 1) | 8.92% | −552.3 to −402.9 | sum −1,886.0 |
| 6–10 (stage 2) | 6.89% | −368.4 to −381.2 | sum −986.1 |
| **Σ PV, years 1–10** | | | **−2,872.1** |

```text
NOPAT_11          = EBIT_11 × (1 − 21%) = 88.4 × 0.79 = 70.2 €m
RONIC             = r2 + 2% = 8.89%
Reinvestment rate = g / RONIC = 2.0% / 8.89% = 22.5%
FCFF_11           = NOPAT_11 × (1 − reinvestment) = 54.4 €m
TV at year 10     = FCFF_11 / (r2 − g) = 54.4 / 4.89% = 1,112.2 €m
PV of TV          = 1,112.2 × 0.4674 = 519.8 €m
Enterprise value  = −2,872.1 + 519.8 = −2,352.3 €m
```

### 4.5 From enterprise value to fair value

```text
Equity_pre  = EV + cash − debt = −2,352.3 + 22.0 − 7,754.0 = −10,084.3 €m
Fees        = 3% × 3,200 + 30 = 126.0 €m
DCF price   = (−10,084.3 − 126.0) / 800.00m shares = −12.76 €
EV_comps    = 5× Revenue_1 = 5 × 3,508.6 = 17,543.2 €m
Comps price = (17,543.2 + 22.0 − 7,754.0 − 126.0) / 800.00m shares = 12.11 €
Fair value  = 0.70 × (−12.76) + 0.30 × 12.11 = −8.93 + 3.63 = −5.30 €
```

The DCF is entirely dominated by net debt: at −€10.08bn of pre-money equity
value, the −€2.35bn operating DCF is a small fraction of the −€7.73bn net
debt that sits beneath it. The comparables valuation, which starts from
enterprise value and applies the *same* bridge, is positive because 5× a
€3.5bn revenue line (€17.5bn) comfortably covers the debt; the DCF's much
smaller enterprise value does not.

### 4.6 Isolating the leverage effect

Re-running Case A with the debt set to zero (cash unchanged, every operating
assumption identical) flips the verdict:

| | With real net debt (€7.73bn) | With debt removed |
|---|---:|---:|
| Verdict | POSTPONE | **PROCEED** |
| Fair value per share | −€5.30 | **€4.36** |
| Price range | 0.01 – −€4.73 | €3.50 – €3.90 |
| Market capitalisation | n/a | €6,320m |

The same operating business, unlevered, is worth a positive €4.36 per share.
Verisure's actual capital structure costs its equity roughly €9.66 per share
on this model — a bigger single swing than either the useful-life assumption
(§5) or any other single driver tested in §7.

## 5. Case B: 10-year hardware life

Only the useful life changes; market, customers, revenue, staff, and every
cost above D&A are identical to Case A (§4.1–§4.3).

| | Y1 | Y2 | Y3 | Y4 | Y5 | Y6 | Y7 | Y8 | Y9 | Y10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| D&A | 426.2 | 471.3 | 522.1 | 578.2 | 639.0 | 703.9 | 772.1 | 842.8 | 915.3 | 988.7 |
| EBIT | −104.4 | −17.8 | 69.9 | 154.9 | 233.6 | 302.0 | 356.7 | 393.9 | 401.8 | 377.0 |
| EBIT margin | −3.0% | −0.5% | 1.6% | 3.3% | 4.5% | 5.4% | 6.0% | 6.3% | 6.1% | 5.5% |
| FCFF | −552.3 | −513.5 | −478.4 | −440.6 | −410.4 | −430.6 | −413.2 | −401.6 | −404.7 | −425.3 |

```text
Σ PV, years 1–10 = −3,004.9 €m
TV at year 10     = 194.4 / 4.89% = 3,973.7 €m;  PV of TV = 1,857.3 €m
Enterprise value  = −3,004.9 + 1,857.3 = −1,147.6 €m

Equity_pre  = −1,147.6 + 22.0 − 7,754.0 = −8,879.6 €m
DCF price   = (−8,879.6 − 126.0) / 800.00m = −11.26 €
Comps price = 12.11 € (unchanged: comparables don't see capex or useful life)
Fair value  = 0.70 × (−11.26) + 0.30 × 12.11 = −4.25 €
```

A 4-year longer hardware life raises peak EBIT margin from 3.4% (Case A,
year 8) to 6.3% (Case B, year 8) and the DCF price by €1.50 — real, but far
smaller than the €9.66 the leverage alone costs (§4.6), and smaller than the
GPU-life swing in the Nimbus case, because 25% capex is fixed in both cases;
only its depreciation *pace* differs.

## 6. The two cases, and the leverage counterfactual, side by side

| | Case A: 6yr | Case B: 10yr | Debt removed (Case A) |
|---|---:|---:|---:|
| Enterprise value | −€2,352m | −€1,148m | −€2,352m (unchanged) |
| DCF price | −€12.76 | −€11.26 | n/a (uses comps blend) |
| Fair value | −€5.30 | −€4.25 | **€4.36** |
| Verdict | POSTPONE | POSTPONE | **PROCEED** |

## 7. Monte Carlo

10,000 draws, seed 42, the scenario drivers varied as in §12 of the design
([EduMatcher-valuation.md](EduMatcher-valuation.md)):

| | Case A | Case B |
|---|---:|---:|
| Fair value, P5 | −€13.13 | −€12.20 |
| Fair value, median | −€6.36 | −€5.34 |
| Fair value, P95 | €0.13 | €1.33 |
| Mean fair value | −€6.41 | −€5.36 |
| P(DCF equity below zero) | 99.8% | 99.0% |

Even at the 95th percentile of every favourable driver simultaneously, fair
value barely clears zero in either case. On this model's architecture
— which expenses the full cash cost of acquisition rather than capitalising
the labour share Verisure's own accounting does (§3.2) — almost no plausible
combination of operating assumptions overcomes €7.7bn of net debt sitting
beneath a mid-single-digit-billion-euro operating DCF.

## 8. Sensitivity

Each row changes one assumption from the Case A base, holding debt at its
real €7.754bn. DCF and fair value per share in euros.

| Change | DCF price | Fair value |
|---|---:|---:|
| Base case (Case A) | −12.76 | −5.30 |
| Comparables multiple 7× instead of 5× | −12.76 | 2.78 |
| Comparables multiple 3× instead of 5× | −12.76 | −13.38 |
| Terminal growth 2.5% instead of 2.0% | −11.97 | −4.74 |
| Cost of debt 4.25% instead of 6.0% (the real post-upgrade WACD) | −10.42 | −4.01 |
| Churn 6% instead of 7.4% | −8.14 | −2.05 |
| **Debt removed entirely** | n/a | **4.36** |

- **Nothing except removing the debt itself reliably flips the verdict.**
  Even a two-point swing in the comparables multiple (5×→7×) only just
  clears zero; a cheaper cost of debt (matching Verisure's real post-upgrade
  4.25% WACD) narrows the gap but does not close it.
- **The comparables valuation is the one number in this whole exercise that
  lines up with reality.** At 5×, it values the business at €12.11/share —
  within shouting distance of the real €12.25–13.50 IPO range quoted by the
  WSJ, confirming that real investors priced this deal on a multiple of
  revenue applied to the operating business, exactly as the model's 30%
  comparables weight (on its own) would suggest.

## 9. What actually happened

Because Verisure is real, this section does something Nimbus's fictive case
cannot: compare the model's verdict with the market's own.

| | Model (this exercise) | The real IPO |
|---|---|---|
| Price range | postponed (fair value negative) | €12.25–13.50 |
| Offer price | n/a | ≈€13.25–13.68 (implied by the €3.2bn raised ÷ new shares, and by the €13.7bn post-money valuation ÷ 1.034bn shares) |
| First-day move | n/a | +21% ("jump on debut", per the [FT][ft]) |
| Comparables-only fair value | €12.11 | close to the actual offer price |
| Price one year later (8 Oct 2026) | n/a | €7.89 (market cap €8.158bn) |
| One-year total return | n/a | **−45.84%** |

The real market, like this model's 30%-weighted comparables view, priced
Verisure on a revenue multiple applied to a fast-growing, high-retention
subscriber base — not on an unlevered DCF of its cash flows net of €7.7bn of
debt. A year on, the stock has fallen toward levels much closer to what a
leverage-aware, cash-flow-first view (closer to this model's full −70%/30%
blend, which is deeply negative, or at least to a discount from the
comparables-only figure) would suggest. Whether that fall reflects the market
catching up with the DCF's warning about leverage, a re-rating of growth
stocks generally, company-specific execution issues, or some mix of all
three is outside what this model — or this document — can say; the 46%
decline is a fact, its cause is not.

## 10. What the analysis says

1. **A private-equity-leveraged subscription business is not a software
   company wearing a telecom's capex.** Verisure's gross margin and churn
   look like a best-in-class consumer subscription business; its balance
   sheet — 4.8× net debt/EBITDA at the point of listing — looks like a
   leveraged buyout, because that is exactly what it was. A valuation
   framework built around unlevered FCFF has to work hard to see past that
   much debt, and on this model's numbers, it largely fails to.
2. **"Capex intensity" and "useful life" are two different questions, and
   only one of them is disclosed.** Verisure discloses capex ÷ revenue every
   quarter (23.9–25.8%); it does not disclose how long the installed base
   lasts. Bracketing that unknown (6 vs 10 years) moved the DCF by only
   €1.50 per share here — far less than it moved Nimbus's GPU case — because
   the capex itself, unlike Nimbus's, is a real, fixed, disclosed number in
   both cases.
3. **Getting the acquisition-cost split wrong is the easiest way to break
   this kind of analysis.** A business that both expenses labour and
   capitalises hardware for the same unit of growth (a "customer") needs its
   cost-per-acquisition split carefully between the model's `cac_paid` and
   `capex_pct` inputs, or the same euro gets charged twice (§3.1). The first
   attempt at this exercise, before that correction, priced the DCF near
   −€40 per share.
4. **The comparables method, not the DCF, is what real IPO pricing actually
   rewarded here** — and, on the evidence of one subsequent year of trading,
   may have rewarded it more than the fundamentals could sustain.
5. **Debt dominates.** Of every lever tested in §8, only removing Verisure's
   actual €7.7bn of pre-IPO net debt reliably turns this model's verdict from
   POSTPONE to PROCEED. For a business this levered, the capital structure
   is not a footnote to the valuation; it is most of the valuation.

## 11. Reproducing the numbers

The two scenario files used here (Case B differs only in `capital.useful_life`):

```yaml
pm_valuation: 1
company:
  name: Verisure plc
  ticker: VSURE
  sector: telecom_operator
  dual_class: 'no'
  market: se
market:
  tam: 55bn
  tam_growth: 6%
  sam_share: 40%
  structure: dominant
customers:
  last_fy_revenue: 3.41bn
  now: 5,831,400
  arpu: 559
  arpu_growth: 3%
  churn: 7.4%
  growth_y1: 9%
people:
  headcount: 24,767
  loaded_cost: 48,000
  wage_inflation: 4%
  elasticity: '0.5'
  growth_floor: 3%
  split_rnd: 3%
  split_snm: 12%
  split_gna: 10%
  split_ops: 75%
costs:
  infra_fixed: 80m
  infra_per_customer: 60
  other_cogs_pct: 5%
  cac_paid: 1,000
  rnd_nonstaff_pct: 1%
  sbc_pct: 10%
capital:
  capex_pct: 25%
  useful_life: '6'
  nol: 300m
  cash: 22m
  debt: 7,754m
rates:
  beta_stage1: '1.1'
  beta_stage2: '0.9'
  size_premium_1: 0%
  size_premium_2: 0%
  execution_premium: 2%
  debt_ratio: 35%
  cost_of_debt: 6%
offering:
  shares_pre: 800,000,000
  raise: 3.2bn
  gross_spread: 3%
  other_expenses: 30m
investors:
  inst_interest: very_high
  n_institutions: '200'
  avg_ticket: 300m
  retail_interest: high
  n_retail: 300,000
  retail_application: 10,000
  hype: '6'
  comps_multiple: 5x
management:
  min_market_cap: none
```

```bash
pm-valuation --load verisure-6y.yaml --no-tui --mode deterministic --export verisure-6y.md
pm-valuation --load verisure-10y.yaml --no-tui --mode deterministic --export verisure-10y.md
pm-valuation --load verisure-6y.yaml --no-tui --mode montecarlo --export verisure-6y-mc.md
```

For §4.6, set `capital.debt: 22m` (equal to cash) and rerun. The report's
sections hold every table of §4–§7.

## Sources

[wiki]: https://en.wikipedia.org/wiki/Verisure
[ft]: https://www.ft.com/content/8d8ba743-bf9c-4ce2-b2b1-b1f3d85b07d9
[wsj]: https://www.wsj.com/finance/stocks/verisure-seeks-up-to-16-3-billion-valuation-in-largest-europe-ipo-since-2022-dfd9f94c
[investors]: https://www.verisure.com/investors
[q2]: https://www.verisure.com/press-releases/regulatory/verisure-q2-2026-results
[shares]: https://www.verisure.com/press-releases/regulatory/number-of-shares-and-votes-in-verisure-plc-1
[ar2025]: https://www.verisure.com/annual-reports
[yahoo]: https://finance.yahoo.com/quote/VSURE.ST/

- [Wikipedia: Verisure][wiki]
- [Financial Times, 8 Oct 2025: Verisure shares jump 21% on debut after raising €3.2bn in listing][ft]
- [The Wall Street Journal, 29 Sep 2025: Verisure Seeks Up to $16.3 Billion Valuation in Largest Europe IPO Since 2022][wsj]
- [Verisure plc: Investor relations — key figures][investors]
- [Verisure plc: Q2 2026 Results (30 Jul 2026)][q2]
- [Verisure plc: Number of shares and votes (30 Sep 2026)][shares]
- [Verisure plc: Annual Reports][ar2025]
- [Yahoo Finance: Verisure plc (VSURE.ST)][yahoo]
</content>

# AI IPO: valuing a loss-making frontier AI lab with pm-valuation

*J. Persson, 2026*

This document values a fictive frontier AI company, **Nimbus Cognition Inc.
(NMBS)**, with `pm-valuation`, the same way Appendix C of
[EduMatcher-valuation.md](EduMatcher-valuation.md) values Tornfalk Security AB:
every input with its source, every formula as the code applies it, and every
intermediate number, so each step can be checked by hand.

Nimbus is sized like Anthropic as publicly reported in mid-2026: about $65 bn
of annualized revenue, a last private valuation near $1 trillion, a few
thousand employees and an IPO raise of about $100 bn. It still lives on
investor money: its cash flow is negative, and it is about to list on Nasdaq.
It is an illustration of the model, built from press reports, **not a
valuation of Anthropic, OpenAI or any other real company, and not investment
advice**. Where the public record is silent, the numbers are assumptions,
marked as such.

Two questions drive the analysis:

1. **How fast do the GPUs lose their value?** Case A: worthless after 3
   years. Case B: after 5 years.
2. **What does a fierce market for AI talent do to the value?** Pay rises
   faster than elsewhere, and every employee holds a large share of options.

## 1. Results

| | Case A: 3-year GPUs | Case B: 5-year GPUs |
|---|---:|---:|
| Capex (GPU replacement), % of revenue | 30% | 18% |
| Enterprise value, DCF | −$3.4 bn | $259.5 bn |
| DCF price per share | $39.49 | $199.83 |
| Comparables price per share (12× next year's revenue) | $690.79 | $690.79 |
| Fair value per share (70% DCF, 30% comparables) | **$234.88** | **$347.12** |
| Price range | $185–210 | $280–310 |
| Management's floor (the last private round, $965 bn) | $527.44 | $527.44 |
| **Verdict** | **POSTPONE** | **POSTPONE** |
| *If management drops the floor:* offer price | $250.00 | $370.00 |
| Market capitalisation at that price | $510.0 bn | $706.8 bn |
| Book coverage at that price | 7.30× | 7.27× |
| Monte Carlo: chance fair value is below the offer price | 70.1% | 74.2% |

In short:

- **With 3-year GPUs, the business is worth roughly its cash.** Replacing
  the GPU fleet every three years costs 30% of revenue, for ever. That
  absorbs nearly all the operating cash, so free cash flow stays negative for
  all ten forecast years, and the DCF values the operations at about zero.
  Fair value, $234.88, comes almost entirely from the comparables.
- **With 5-year GPUs, the same company is worth five times as much on a DCF
  basis.** Free cash flow turns positive in year 3, and the DCF price rises
  from $39.49 to $199.83. The GPU life is the single most important
  assumption in the valuation.
- **Either way, the IPO cannot meet the last private round.** At $965 bn
  post-money, management's floor of $527.44 per share is far above fair
  value. The model postpones the IPO: it would be a *down round*. If
  management accepts the market's price, the company lists at $250 (A) or
  $370 (B), a market capitalisation of about half the last private round.
- **Demand, not value, sets the offer price.** In both cases the book is
  hot and the US rules let the deal price up to 20% above its range, so the
  offer price ends *above* fair value, and the Monte Carlo puts the chance
  that the shares are worth less than buyers pay at 70–74%.
- **Talent costs matter less than compute.** Pay rising 8% a year instead
  of 5%, and stock awards equal to cash pay, cost $23–27 per share of fair
  value (§8). Training compute and GPU replacement cost far more.

## 2. What is public

The reference company. All figures are as reported by the press or by data
providers; none are audited, and the sources do not always agree.

| Fact | Value | Date | Source |
|---|---|---|---|
| Annualized revenue run rate | $65 bn | July 2026 | [CNBC][cnbc], [Forge][forge] |
| Run rate history | $9 bn (end 2025), $14 bn (Feb), $30 bn (Apr), $47 bn (May) | 2025–26 | [Luminix][luminix] |
| Revenue, calendar 2025 | about $4.6 bn | 2025 | [Luminix][luminix] |
| Operating loss, 2025 | about $8 bn | 2025 | [Luminix][luminix] |
| Gross margin | about 40% in 2025; target 75–77% in 2028 | | [Tiger/The Information][tiger], [Luminix][luminix] |
| Last private round | Series H: $65 bn at $965 bn post-money, up to $589.01 per share | May 2026 | [Forge][forge], [Luminix][luminix] |
| Earlier round | Series G: $30 bn at $380 bn post-money | Feb 2026 | [Orrick][orrick] |
| Total capital raised | about $132 bn | June 2026 | [Luminix][luminix] |
| IPO | Nasdaq; raise approaching or over $100 bn; target valuation up to $2 trillion | autumn 2026 | [Forge][forge], [Luminix][luminix] |
| Founders' voting class | about 50.1% of the votes, being considered | 2026 | [Luminix][luminix] |
| Business customers | 300,000+ (80% of revenue); 1,000+ spending over $1 m a year | Oct 2025, Apr 2026 | [Sacra][sacra] |
| Revenue through AWS and Google Cloud | 47% | 2025 | [Luminix][luminix] |
| Compute commitments | $518 bn, about 80% non-cancellable | 2026 | [Luminix][luminix] |
| Employees | about 2,500–5,000 | Mar 2026 | [SaaStr][saastr] |
| Revenue expected in 2028 | almost $200 bn | | [Forge][forge] |
| OpenAI 2025, for comparison | revenue $13.1 bn, costs $34 bn, R&D $19.2 bn | 2025 | [ProPakistani][propk] |
| OpenAI stock pay | about $1.5 m per employee on average | 2025 | [Fortune][fortune] |
| GPU life | hyperscalers depreciate servers over about 5–6 years; critics argue GPUs are economically obsolete in 2–3 | 2025–26 | [Tiger][tigergpu], [FourWeekMBA][fwmba] |

Some reports say the reference company made an operating profit in mid-2026
before stock-based pay. Nimbus follows the premise of this analysis instead:
once stock pay and GPU depreciation are counted, it makes an operating loss,
and its cash flow is negative.

## 3. From public facts to model answers

Nimbus lists in the United States (`market: us`): amounts in dollars, a Form
S-1, the SEC, Nasdaq, a 4.25% risk-free rate, a 5% equity risk premium, 25%
tax, 2.5% inflation and long-run growth, and pricing up to 20% above the
range. No sector preset fits a frontier AI lab, so it starts from
`b2b_saas` (business software) and overrides almost every value. Year 0 is
the current run rate; year 1 is the twelve months after July 2026.

| Field | Answer | Why |
|---|---|---|
| Name, ticker | Nimbus Cognition Inc., NMBS | Fictive |
| Dual-class shares | yes | The founders' voting class under consideration |
| Total addressable market | $1,500 bn | Assumption: spending on AI models and AI-delivered work, growing 30% a year at first |
| TAM growth, year 1 | 30% | Assumption; fades to 2.5% by year 10 |
| SAM share | 60% | Enterprise and developer demand a frontier lab can serve |
| Market structure | oligopoly (15%) | A handful of frontier labs |
| Revenue, year 0 | $65 bn | The July 2026 run rate |
| Customers now | 400,000 | 300,000+ business customers in late 2025, grown since |
| ARPU | $162,500 | $65 bn ÷ 400,000: the run rate per customer |
| ARPU growth | 5% | Default |
| Churn | 10% | Assumption: customers switch models more easily than software |
| Customer growth, year 1 | 60% | Gives year-1 revenue of $88.7 bn and year 3 of $202 bn, close to "almost $200 bn" in 2028 |
| Headcount | 4,500 | Upper half of the 2,500–5,000 estimates |
| Loaded cost per employee | $1,050,000 | §3.2 |
| Wage inflation | 8% | §3.2: pay rises much faster than for ordinary companies |
| Headcount elasticity, floor | 0.5, 5% | Revenue grows with compute, not people |
| Staff split R&D / S&M / G&A / Ops | 55 / 20 / 12 / 13% | A research-led company |
| Infrastructure, fixed | $8 bn | Data centres, power, networking not in the GPU fleet |
| Infrastructure per customer | $30,000 | Serving capacity rented beyond the owned fleet: 18% of ARPU |
| Other cost of revenue | 10% | Cloud partners' share: 47% of revenue is sold through AWS and Google |
| Paid acquisition per customer | $48,750 | 0.3 × ARPU |
| R&D, non-staff | 22% of revenue | Training compute; OpenAI's R&D was 147% of its 2025 revenue, falling as revenue grows |
| Stock-based compensation | 100% of staff cost | §3.2 |
| Capex | 30% (A) / 18% (B) | §3.1 |
| Useful life | 3 (A) / 5 (B) years | §3.1 |
| Opening PP&E | $29.25 bn (derived) | capex × revenue × life ÷ 2: the same fleet in both cases |
| Tax losses carried forward | $15 bn | About the operating losses to date |
| Cash | $70 bn | Assumption: roughly half of the capital raised is unspent |
| Beta, years 1–5 / year 6 on | 1.8 / 1.3 | A young, volatile technology stock |
| Size premium | 0% / 0% | Not a small company |
| Execution premium | 5% | Technology, competition and regulation risk |
| Pre-IPO shares | 1,640,000,000 | $965 bn ÷ $589.01 per share |
| Primary raise | $100 bn | The reported IPO size |
| Gross spread, other expenses | 1.5%, $300 m | Very large IPOs pay far less than the 7% default |
| Institutional interest, retail interest, hype | very high, very high, 9 | The most anticipated listing of the year |
| Institutions, average order | 300, $1 bn | |
| Retail applicants, average application | 2,000,000, $5,000 | |
| Comparable EV / NTM revenue | 12× | Fast-growing listed software; the Series H was about 15× the run rate |
| Last private round, post-money | $965 bn | Series H; becomes management's minimum market cap |

Everything else keeps its default for the US market.

### 3.1 GPUs: fleet, life and replacement

The model has one place for long-lived equipment: **capex** (a share of
revenue) and **PP&E**, depreciated straight-line over its **useful life**.
Nimbus owns its GPU fleet there. We assume the fleet costs **0.9× annual
revenue** at cost (an assumption: about $58.5 bn of GPUs for $65 bn of
revenue). Keeping such a fleet means replacing it once per life:

```text
capex share = fleet ÷ life      Case A: 0.9 ÷ 3 = 30% of revenue      Case B: 0.9 ÷ 5 = 18% of revenue
opening PP&E = capex share × revenue × life ÷ 2 = 0.9 × 65 ÷ 2 = $29.25 bn in both cases
```

The opening fleet is the same in both cases; only how fast it must be
replaced differs. Training runs on rented or shared capacity are counted as
R&D (22% of revenue), and serving capacity beyond the fleet as
infrastructure.

### 3.2 Talent: pay and options

Frontier labs compete for a few thousand researchers. Reported stock awards
at OpenAI average about $1.5 m per employee a year, several times cash pay.
The model expresses stock pay as a share of cash staff cost, at most 100%, so:

```text
total pay per employee ≈ cash $600,000 + stock $1,500,000 = $2.1 m
loaded cost L, with stock pay = 100% of L:   2 × L = $2.1 m   →   L = $1,050,000
```

The loaded cost therefore carries the cash pay plus $450,000 of the stock,
and stock-based compensation adds the other $1,050,000. Pay then rises 8% a
year, against 3.5% for an ordinary company. Stock pay is a real cost in the
model (§6 of the design): it dilutes the owners even though no cash leaves.

### 3.3 What the model cannot express

- **Growth capex.** Capex is a fixed share of revenue, so the extra GPUs
  needed to *grow* the fleet are not charged separately. In years of 40–58%
  growth, both cases understate the cash needed.
- **Falling compute prices.** GPUs, power and inference get cheaper per unit
  over time; the model escalates infrastructure with inflation and keeps
  training at a fixed 22% of revenue.
- **Pay above the cap.** Stock pay is capped at 100% of cash pay, hence the
  construction in §3.2.
- **Committed compute.** $518 bn of commitments is an obligation, not debt
  in the bridge; it shows up only through the cost lines.
- **Revenue per employee.** At $15–37 m per employee, Nimbus is far outside
  the software sector's plausible range, and warning V020 fires. That is a
  real feature of AI labs, not an error in the inputs.

## 4. Case A: GPUs worthless after 3 years

All amounts in billions of dollars ($bn) unless stated; customers in
thousands. The model computes in full precision and rounds only for
display, so a sum of displayed numbers can differ in the last decimal.

### 4.1 Market and customers

The formulas are those of Appendix C.3 of the design document, with
N = 10. The S-curve's intensity is calibrated so that year 1 grows by
exactly the year-1 customer growth:

```text
Max customers_1 = 15% × (1,500 × 1.30 × 60%) ÷ (162,500 × 1.05) = 15% × 1,170 bn ÷ 170,625 = 1,028.6 k
a = (growth_1 + churn) ÷ (1 − C_0 ÷ Max customers_1) = (0.60 + 0.10) ÷ (1 − 400 ÷ 1,028.6) = 0.70 ÷ 0.611111 = 1.145455
Gross adds_1 = 1.145455 × 400 k × 0.611111 = 280.0 k;  churned = 10% × 400 k = 40.0 k;  end = 640.0 k
Revenue_1 = (400 + 640) ÷ 2 × 170,625 = 520 k × $170,625 = $88.7 bn       36.5% above the $65 bn run rate
```

Because year 0 is a run rate, not a year in which the customer base grew,
year-1 growth does not include the run-rate effect that Tornfalk's has.

| | Y1 | Y2 | Y3 | Y4 | Y5 | Y6 | Y7 | Y8 | Y9 | Y10 | Y11 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| TAM growth | 30.0% | 26.9% | 23.9% | 20.8% | 17.8% | 14.7% | 11.7% | 8.6% | 5.6% | 2.5% | 2.5% |
| TAM ($bn) | 1,950 | 2,475 | 3,067 | 3,706 | 4,364 | 5,007 | 5,591 | 6,073 | 6,410 | 6,570 | 6,734 |
| SAM = 60% × TAM | 1,170 | 1,485 | 1,840 | 2,223 | 2,619 | 3,004 | 3,355 | 3,644 | 3,846 | 3,942 | 4,041 |
| ARPU growth | 5.00% | 4.72% | 4.44% | 4.17% | 3.89% | 3.61% | 3.33% | 3.06% | 2.78% | 2.50% | 2.50% |
| ARPU ($) | 170,625 | 178,682 | 186,624 | 194,400 | 201,960 | 209,253 | 216,228 | 222,835 | 229,025 | 234,750 | 240,619 |
| Max customers (k) = 15% × SAM ÷ ARPU | 1,028.6 | 1,246.8 | 1,479.0 | 1,715.6 | 1,945.0 | 2,153.5 | 2,327.2 | 2,452.7 | 2,518.9 | 2,518.9 | 2,518.9 |
| Customers, start (k) | 400.0 | 640.0 | 932.8 | 1,234.1 | 1,507.4 | 1,745.1 | 1,949.7 | 2,117.0 | 2,237.2 | 2,300.1 | 2,299.0 |
| + Gross adds (k) | 280.0 | 356.8 | 394.6 | 396.7 | 388.4 | 379.1 | 362.3 | 331.9 | 286.7 | 228.9 | 229.9 |
| − Churned, 10% (k) | 40.0 | 64.0 | 93.3 | 123.4 | 150.7 | 174.5 | 195.0 | 211.7 | 223.7 | 230.0 | 229.9 |
| = Customers, end (k) | 640.0 | 932.8 | 1,234.1 | 1,507.4 | 1,745.1 | 1,949.7 | 2,117.0 | 2,237.2 | 2,300.1 | 2,299.0 | 2,299.0 |
| Penetration of the ceiling | 62% | 75% | 83% | 88% | 90% | 91% | 91% | 91% | 91% | 91% | 91% |
| **Revenue** | 88.7 | 140.5 | 202.2 | 266.5 | 328.4 | 386.6 | 439.7 | 485.1 | 519.6 | 539.8 | 553.2 |
| Revenue growth | 36.5% | 58.4% | 43.9% | 31.8% | 23.3% | 17.7% | 13.7% | 10.3% | 7.1% | 3.9% | 2.5% |

The company fills 91% of its ceiling by year 6: growth after that comes from
the market and the price, which both fade to 2.5%.

### 4.2 Staff

```text
Headcount growth_t = max(5%, 0.5 × revenue growth_t);   Loaded cost_t = $1,050,000 × 1.08^t
Year 1: 0.5 × 36.5% = 18.2%;  4,500 × 1.182 = 5,321;  $1,134,000 × 5,321 = $6.0 bn
```

| | Y1 | Y2 | Y3 | Y4 | Y5 | Y6 | Y7 | Y8 | Y9 | Y10 | Y11 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Headcount growth | 18.2% | 29.2% | 21.9% | 15.9% | 11.6% | 8.8% | 6.9% | 5.2% | 5.0% | 5.0% | 5.0% |
| Headcount | 5,321 | 6,874 | 8,383 | 9,716 | 10,845 | 11,805 | 12,616 | 13,268 | 13,931 | 14,628 | 15,359 |
| Loaded cost ($k) | 1,134 | 1,225 | 1,323 | 1,429 | 1,543 | 1,666 | 1,800 | 1,943 | 2,099 | 2,267 | 2,448 |
| Staff cost | 6.0 | 8.4 | 11.1 | 13.9 | 16.7 | 19.7 | 22.7 | 25.8 | 29.2 | 33.2 | 37.6 |
| Revenue per employee ($m) | 16.7 | 20.4 | 24.1 | 27.4 | 30.3 | 32.7 | 34.9 | 36.6 | 37.3 | 36.9 | 36.0 |

Staff cost is small next to revenue: $6.0 bn of $88.7 bn in year 1, doubled
by stock pay. Pay rising 8% a year against prices rising 2.5% in the long
run still squeezes the margin late in the forecast.

### 4.3 Costs and operating profit

```text
Infrastructure_t = ($8 bn + $30,000 × average customers_t) × 1.025^t
Year 1: ($8 bn + $30,000 × 520 k) × 1.025 = $23.6 bn × 1.025 = $24.2 bn
R&D_t = R&D staff_t + 22% × revenue_t (training compute)
D&A_t = PP&E at the start of the year ÷ 3
```

| | Y1 | Y2 | Y3 | Y4 | Y5 | Y6 | Y7 | Y8 | Y9 | Y10 | Y11 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Revenue | 88.7 | 140.5 | 202.2 | 266.5 | 328.4 | 386.6 | 439.7 | 485.1 | 519.6 | 539.8 | 553.2 |
| Infrastructure | 24.2 | 33.2 | 43.6 | 54.2 | 64.3 | 73.6 | 82.0 | 89.3 | 95.0 | 98.5 | 101.0 |
| Partner share and other (10%) | 8.9 | 14.1 | 20.2 | 26.6 | 32.8 | 38.7 | 44.0 | 48.5 | 52.0 | 54.0 | 55.3 |
| Ops staff (13%) | 0.8 | 1.1 | 1.4 | 1.8 | 2.2 | 2.6 | 3.0 | 3.4 | 3.8 | 4.3 | 4.9 |
| **Gross profit** | 54.9 | 92.2 | 136.9 | 183.8 | 229.2 | 271.8 | 310.7 | 343.9 | 368.8 | 383.0 | 392.0 |
| Gross margin | 61.9% | 65.6% | 67.7% | 69.0% | 69.8% | 70.3% | 70.7% | 70.9% | 71.0% | 70.9% | 70.9% |
| R&D: staff + training compute 22% | 22.8 | 35.5 | 50.6 | 66.3 | 81.5 | 95.9 | 109.2 | 120.9 | 130.4 | 137.0 | 142.4 |
| S&M: staff + acquisition | 15.3 | 20.1 | 23.2 | 24.5 | 25.3 | 26.0 | 26.3 | 25.7 | 24.1 | 21.6 | 23.0 |
| G&A | 3.4 | 5.2 | 7.4 | 9.7 | 11.9 | 14.0 | 15.9 | 17.7 | 19.1 | 20.2 | 21.1 |
| SBC = 100% of staff cost | 6.0 | 8.4 | 11.1 | 13.9 | 16.7 | 19.7 | 22.7 | 25.8 | 29.2 | 33.2 | 37.6 |
| **EBITDA** | 7.4 | 22.8 | 44.6 | 69.5 | 93.8 | 116.3 | 136.6 | 153.9 | 166.0 | 171.0 | 167.9 |
| D&A = opening PP&E ÷ 3 | 9.8 | 15.4 | 24.3 | 36.4 | 50.9 | 66.8 | 83.2 | 99.4 | 114.8 | 128.5 | 139.6 |
| **EBIT** | −2.4 | 7.5 | 20.3 | 33.0 | 42.9 | 49.5 | 53.4 | 54.5 | 51.2 | 42.5 | 28.2 |
| EBIT margin | −2.7% | 5.3% | 10.0% | 12.4% | 13.1% | 12.8% | 12.2% | 11.2% | 9.9% | 7.9% | 5.1% |

Gross margin climbs from 62% to 71%, in line with the reported path from
about 40% towards 75%. The operating loss of year 1 (−2.7%) turns into a
profit in year 2. From year 7 the margin falls again: depreciation catches up
with the 30% capex as the fleet matures, and pay outgrows prices.

### 4.4 Tax

| | Y1 | Y2 | Y3 | Y4 | Y5 | Y6 | Y7 | Y8 | Y9 | Y10 | Y11 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| EBIT | −2.4 | 7.5 | 20.3 | 33.0 | 42.9 | 49.5 | 53.4 | 54.5 | 51.2 | 42.5 | 28.2 |
| NOL, opening | 15.0 | 17.4 | 9.9 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| NOL used | 0.0 | 7.5 | 9.9 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| NOL, closing | 17.4 | 9.9 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Tax = 25% × (EBIT − used) | 0.0 | 0.0 | 2.6 | 8.3 | 10.7 | 12.4 | 13.4 | 13.6 | 12.8 | 10.6 | 7.1 |

The $15 bn of losses carried forward, plus year 1's loss, shelter years 2–3.

### 4.5 GPU fleet and free cash flow

```text
Capex_t = 30% × revenue_t;   PP&E_t = PP&E_{t−1} + capex_t − D&A_t;   NWC_t = −5% × revenue_t
FCFF_t = EBIT_t − tax_t + D&A_t − capex_t − ΔNWC_t
```

| | Y1 | Y2 | Y3 | Y4 | Y5 | Y6 | Y7 | Y8 | Y9 | Y10 | Y11 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GPU fleet (PP&E), opening | 29.2 | 46.1 | 72.9 | 109.3 | 152.8 | 200.4 | 249.6 | 298.3 | 344.4 | 385.5 | 418.9 |
| + Capex = 30% of revenue | 26.6 | 42.2 | 60.7 | 79.9 | 98.5 | 116.0 | 131.9 | 145.5 | 155.9 | 161.9 | 166.0 |
| − D&A | 9.8 | 15.4 | 24.3 | 36.4 | 50.9 | 66.8 | 83.2 | 99.4 | 114.8 | 128.5 | 139.6 |
| = PP&E, closing | 46.1 | 72.9 | 109.3 | 152.8 | 200.4 | 249.6 | 298.3 | 344.4 | 385.5 | 418.9 | 445.2 |
| ΔNWC (NWC = −5% of revenue) | −1.2 | −2.6 | −3.1 | −3.2 | −3.1 | −2.9 | −2.7 | −2.3 | −1.7 | −1.0 | −0.7 |
| EBIT − tax + D&A | 7.4 | 22.8 | 42.0 | 61.2 | 83.1 | 103.9 | 123.3 | 140.3 | 153.2 | 160.4 | 160.8 |
| − Capex − ΔNWC | −25.4 | −39.6 | −57.6 | −76.7 | −95.4 | −113.1 | −129.2 | −143.3 | −154.1 | −160.9 | −165.3 |
| **= FCFF** | −18.1 | −16.7 | −15.6 | −15.5 | −12.3 | −9.1 | −6.0 | −3.0 | −0.9 | −0.6 | −4.5 |

**Free cash flow never turns positive.** Each year, the cash the operations
generate is spent on replacing and extending a fleet that is worthless after
three years. Year 1 burns $18.1 bn, year 10 still $0.6 bn.

### 4.6 Discount rates

```text
k_e1 = 4.25% + 1.8 × 5.0% + 0% + 5.0% = 18.25%      years 1–5
k_e2 = 4.25% + 1.3 × 5.0% + 0%        = 10.75%      year 6 on and the terminal value
No debt, so both rates are costs of equity.
```

### 4.7 Enterprise value

| Year | Rate | Discount factor | FCFF | Present value |
|---:|---:|---:|---:|---:|
| 1 | 18.25% | 0.845666 | −18.1 | −15.3 |
| 2 | 18.25% | 0.715151 | −16.7 | −12.0 |
| 3 | 18.25% | 0.604779 | −15.6 | −9.4 |
| 4 | 18.25% | 0.511441 | −15.5 | −7.9 |
| 5 | 18.25% | 0.432508 | −12.3 | −5.3 |
| 6 | 10.75% | 0.390527 | −9.1 | −3.6 |
| 7 | 10.75% | 0.352620 | −6.0 | −2.1 |
| 8 | 10.75% | 0.318393 | −3.0 | −0.9 |
| 9 | 10.75% | 0.287488 | −0.9 | −0.3 |
| 10 | 10.75% | 0.259583 | −0.6 | −0.1 |
| **Sum** | | | | **−57.0** |

```text
NOPAT_11          = EBIT_11 × (1 − 25%) = 28.2 × 0.75 = 21.2 $bn
RONIC             = r_2 + 2% = 12.75%
Reinvestment rate = g / RONIC = 2.5% / 12.75% = 19.61%
FCFF_11           = NOPAT_11 × (1 − reinvestment) = 17.0 $bn
TV at year 10     = FCFF_11 / (r_2 − g) = 17.0 / (10.75% − 2.5%) = 206.2 $bn
PV of TV          = TV × DF_10 = 206.2 × 0.259583 = 53.5 $bn
Enterprise value  = −57.0 + 53.5 = −3.4 $bn
```

The ten years of burn are worth −$57.0 bn today, and the terminal value
+$53.5 bn: the operations are worth about nothing. (The report's
"terminal-value share" is meaningless here, as the enterprise value is
close to zero.)

### 4.8 From enterprise value to fair value

```text
Equity_pre  = EV + cash − debt = −3.4 + 70.0 − 0 = 66.6 $bn
Fees        = 1.5% × 100.0 + 0.3 = 1.8 $bn
DCF price   = (66.6 − 1.8) / 1.64 bn shares = 39.49 $
EV_comps    = 12 × Revenue_1 = 12 × 88.7 = 1,064.7 $bn
Comps price = (1,064.7 + 70.0 − 1.8) / 1.64 bn shares = 690.79 $
Fair value  = 0.70 × 39.49 + 0.30 × 690.79 = 27.64 + 207.24 = 234.88 $
```

The DCF price is almost entirely the $70 bn of cash. The comparables price
is 17 times larger, so warning V017 fires; fair value is 88% comparables in
dollars, although the comparables carry only 30% of the weight.

### 4.9 The price range and management's floor

```text
mid      = 234.88 × 0.85 = 199.65;  step = 5.00
range    = round down (189.66) – round up (209.63) = 185.00–210.00
floor    = (minimum market cap − raise) / shares = (965.0 − 100.0) / 1.64 bn = 527.44
moved    = 530.00–555.00, midpoint 542.50
discount = 1 − 542.50 / 234.88 = −131.0%  < 5% minimum  →  POSTPONED
```

The last private round valued Nimbus at $965 bn. Listing below it would be a
down round, so by default management refuses any market cap below it. That
floor, $527.44 per share, is 2.2 times fair value: no discount is left for
IPO buyers, and the model **postpones the IPO** (V012).

## 5. Case B: GPUs worthless after 5 years

Only capex (18% of revenue) and the useful life (5 years) change. Market,
customers, revenue, staff and every cost above EBITDA are identical to Case A
(§4.1–§4.2). The opening fleet is the same: 18% × $65 bn × 5 ÷ 2 = $29.25 bn.

### 5.1 Operating profit

| | Y1 | Y2 | Y3 | Y4 | Y5 | Y6 | Y7 | Y8 | Y9 | Y10 | Y11 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Revenue | 88.7 | 140.5 | 202.2 | 266.5 | 328.4 | 386.6 | 439.7 | 485.1 | 519.6 | 539.8 | 553.2 |
| Infrastructure | 24.2 | 33.2 | 43.6 | 54.2 | 64.3 | 73.6 | 82.0 | 89.3 | 95.0 | 98.5 | 101.0 |
| Partner share and other (10%) | 8.9 | 14.1 | 20.2 | 26.6 | 32.8 | 38.7 | 44.0 | 48.5 | 52.0 | 54.0 | 55.3 |
| Ops staff (13%) | 0.8 | 1.1 | 1.4 | 1.8 | 2.2 | 2.6 | 3.0 | 3.4 | 3.8 | 4.3 | 4.9 |
| **Gross profit** | 54.9 | 92.2 | 136.9 | 183.8 | 229.2 | 271.8 | 310.7 | 343.9 | 368.8 | 383.0 | 392.0 |
| Gross margin | 61.9% | 65.6% | 67.7% | 69.0% | 69.8% | 70.3% | 70.7% | 70.9% | 71.0% | 70.9% | 70.9% |
| R&D: staff + training compute 22% | 22.8 | 35.5 | 50.6 | 66.3 | 81.5 | 95.9 | 109.2 | 120.9 | 130.4 | 137.0 | 142.4 |
| S&M: staff + acquisition | 15.3 | 20.1 | 23.2 | 24.5 | 25.3 | 26.0 | 26.3 | 25.7 | 24.1 | 21.6 | 23.0 |
| G&A | 3.4 | 5.2 | 7.4 | 9.7 | 11.9 | 14.0 | 15.9 | 17.7 | 19.1 | 20.2 | 21.1 |
| SBC = 100% of staff cost | 6.0 | 8.4 | 11.1 | 13.9 | 16.7 | 19.7 | 22.7 | 25.8 | 29.2 | 33.2 | 37.6 |
| **EBITDA** | 7.4 | 22.8 | 44.6 | 69.5 | 93.8 | 116.3 | 136.6 | 153.9 | 166.0 | 171.0 | 167.9 |
| D&A = opening PP&E ÷ 5 | 5.8 | 7.9 | 11.4 | 16.4 | 22.7 | 30.0 | 37.9 | 46.1 | 54.4 | 62.2 | 69.2 |
| **EBIT** | 1.5 | 15.0 | 33.3 | 53.1 | 71.1 | 86.3 | 98.7 | 107.8 | 111.6 | 108.8 | 98.7 |
| EBIT margin | 1.7% | 10.7% | 16.4% | 19.9% | 21.7% | 22.3% | 22.5% | 22.2% | 21.5% | 20.2% | 17.8% |

The same company now shows an operating *profit* in year 1 (1.7%) instead of
a loss: depreciation over 5 years instead of 3 is $4.0 bn lower. Whether an
AI lab "makes a loss" can depend on nothing but its GPU accounting.

### 5.2 Tax

| | Y1 | Y2 | Y3 | Y4 | Y5 | Y6 | Y7 | Y8 | Y9 | Y10 | Y11 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| EBIT | 1.5 | 15.0 | 33.3 | 53.1 | 71.1 | 86.3 | 98.7 | 107.8 | 111.6 | 108.8 | 98.7 |
| NOL, opening | 15.0 | 13.5 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| NOL used | 1.5 | 13.5 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| NOL, closing | 13.5 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Tax = 25% × (EBIT − used) | 0.0 | 0.4 | 8.3 | 13.3 | 17.8 | 21.6 | 24.7 | 26.9 | 27.9 | 27.2 | 24.7 |

### 5.3 GPU fleet and free cash flow

| | Y1 | Y2 | Y3 | Y4 | Y5 | Y6 | Y7 | Y8 | Y9 | Y10 | Y11 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GPU fleet (PP&E), opening | 29.2 | 39.4 | 56.8 | 81.8 | 113.4 | 149.9 | 189.5 | 230.7 | 271.9 | 311.0 | 346.0 |
| + Capex = 18% of revenue | 16.0 | 25.3 | 36.4 | 48.0 | 59.1 | 69.6 | 79.1 | 87.3 | 93.5 | 97.2 | 99.6 |
| − D&A | 5.8 | 7.9 | 11.4 | 16.4 | 22.7 | 30.0 | 37.9 | 46.1 | 54.4 | 62.2 | 69.2 |
| = PP&E, closing | 39.4 | 56.8 | 81.8 | 113.4 | 149.9 | 189.5 | 230.7 | 271.9 | 311.0 | 346.0 | 376.4 |
| ΔNWC (NWC = −5% of revenue) | −1.2 | −2.6 | −3.1 | −3.2 | −3.1 | −2.9 | −2.7 | −2.3 | −1.7 | −1.0 | −0.7 |
| EBIT − tax + D&A | 7.4 | 22.5 | 36.3 | 56.2 | 76.0 | 94.7 | 111.9 | 127.0 | 138.1 | 143.8 | 143.2 |
| − Capex − ΔNWC | −14.8 | −22.7 | −33.3 | −44.8 | −56.0 | −66.7 | −76.5 | −85.0 | −91.8 | −96.2 | −98.9 |
| **= FCFF** | −7.4 | −0.2 | 3.0 | 11.4 | 20.0 | 28.1 | 35.5 | 41.9 | 46.3 | 47.7 | 44.3 |

Free cash flow is positive from year 3 and reaches $47.7 bn in year 10.

### 5.4 Enterprise value

| Year | Rate | Discount factor | FCFF | Present value |
|---:|---:|---:|---:|---:|
| 1 | 18.25% | 0.845666 | −7.4 | −6.3 |
| 2 | 18.25% | 0.715151 | −0.2 | −0.2 |
| 3 | 18.25% | 0.604779 | 3.0 | 1.8 |
| 4 | 18.25% | 0.511441 | 11.4 | 5.8 |
| 5 | 18.25% | 0.432508 | 20.0 | 8.7 |
| 6 | 10.75% | 0.390527 | 28.1 | 11.0 |
| 7 | 10.75% | 0.352620 | 35.5 | 12.5 |
| 8 | 10.75% | 0.318393 | 41.9 | 13.4 |
| 9 | 10.75% | 0.287488 | 46.3 | 13.3 |
| 10 | 10.75% | 0.259583 | 47.7 | 12.4 |
| **Sum** | | | | **72.4** |

```text
NOPAT_11          = EBIT_11 × (1 − 25%) = 98.7 × 0.75 = 74.0 $bn
RONIC             = r_2 + 2% = 12.75%
Reinvestment rate = g / RONIC = 2.5% / 12.75% = 19.61%
FCFF_11           = NOPAT_11 × (1 − reinvestment) = 59.5 $bn
TV at year 10     = FCFF_11 / (r_2 − g) = 59.5 / (10.75% − 2.5%) = 721.0 $bn
PV of TV          = TV × DF_10 = 721.0 × 0.259583 = 187.2 $bn
Enterprise value  = 72.4 + 187.2 = 259.5 $bn
```

### 5.5 Fair value and the floor

```text
Equity_pre  = EV + cash − debt = 259.5 + 70.0 − 0 = 329.5 $bn
Fees        = 1.5% × 100.0 + 0.3 = 1.8 $bn
DCF price   = (329.5 − 1.8) / 1.64 bn shares = 199.83 $
EV_comps    = 12 × Revenue_1 = 12 × 88.7 = 1,064.7 $bn
Comps price = (1,064.7 + 70.0 − 1.8) / 1.64 bn shares = 690.79 $
Fair value  = 0.70 × 199.83 + 0.30 × 690.79 = 139.88 + 207.24 = 347.12 $
mid      = 347.12 × 0.85 = 295.05;  step = 5.00
range    = round down (280.30) – round up (309.80) = 280.00–310.00
floor    = (minimum market cap − raise) / shares = (965.0 − 100.0) / 1.64 bn = 527.44
moved    = 530.00–560.00, midpoint 545.00
discount = 1 − 545.00 / 347.12 = −57.0%  < 5% minimum  →  POSTPONED
```

Even with a DCF five times higher, fair value is $180 below management's
floor, and the IPO is **postponed** again.

## 6. The two cases side by side

| | Case A: 3 years | Case B: 5 years | Difference |
|---|---:|---:|---:|
| Capex, % of revenue | 30% | 18% | 12 points |
| D&A, year 1 / year 10 | 9.8 / 128.5 | 5.8 / 62.2 | |
| EBIT margin, year 1 / year 5 / year 10 | −2.7% / 13.1% / 7.9% | 1.7% / 21.7% / 20.2% | |
| FCFF, year 1 / year 5 / year 10 | −18.1 / −12.3 / −0.6 | −7.4 / 20.0 / 47.7 | |
| PV of years 1–10 | −57.0 | 72.4 | 129.4 |
| PV of the terminal value | 53.5 | 187.2 | 133.7 |
| Enterprise value | −3.4 | 259.5 | 263.0 |
| DCF price | $39.49 | $199.83 | $160.34 |
| Fair value | $234.88 | $347.12 | $112.24 |

The 12-point difference in capex is worth $263 bn of enterprise value, or
$160 per share in the DCF. Because fair value gives the DCF only 70% weight
and the comparables do not see capex at all, $112 of it reaches fair value.

## 7. If management accepts the market's price

Suppose management drops its minimum market cap: `management.min_market_cap:
none`. The range is then fair value less the 15% IPO discount, and the book
decides the price. With prices around $200, the price step is $5.00
(Appendix C.12), and in the US the band runs from 80% of the range's low to
20% above its high.

| | Case A | Case B |
|---|---:|---:|
| Range midpoint = fair value × 0.85 | $199.65 | $295.05 |
| Price range | $185–210 | $280–310 |
| Book band (80% of low → 120% of high, $5 steps) | $145–250, 22 prices | $220–370, 31 prices |

The book at selected prices (institutional demand: 300 × $1 bn × 2.2 for
very high interest × 1.27 for hype 9 × 0.95 for dual-class shares × (fair
value ÷ price)³; retail: 2,000,000 × $5,000 × 2.2 × 3.25 for hype ×
(fair value ÷ price)^0.27; the index factor is 1, because a dual-class
company is not eligible for the index):

Case A:

| Price | Institutional ($bn) | Retail ($bn) | Coverage |
|---:|---:|---:|---:|
| 145.00 | 3,384.5 | 86.9 | 34.71× |
| 185.00 | 1,629.6 | 78.8 | 17.08× |
| 210.00 | 1,114.2 | 74.8 | 11.89× |
| 250.00 | 660.4 | 69.7 | 7.30× |

Case B:

| Price | Institutional ($bn) | Retail ($bn) | Coverage |
|---:|---:|---:|---:|
| 220.00 | 3,127.7 | 86.0 | 32.14× |
| 280.00 | 1,517.1 | 78.0 | 15.95× |
| 310.00 | 1,117.9 | 74.9 | 11.93× |
| 370.00 | 657.5 | 69.7 | 7.27× |

Every price in the band is covered more than three times, so the deal
prices at the top of the band, 20% above the range:

| At the offer price | Case A | Case B |
|---|---:|---:|
| **Offer price** | **$250.00** | **$370.00** |
| Position | above the range | above the range |
| Offer price ÷ fair value | 1.064 | 1.066 |
| New shares (= $100 bn ÷ price) | 400,000,000 | 270,270,270 |
| Shares after the IPO | 2,040,000,000 | 1,910,270,270 |
| Market capitalisation | $510.0 bn | $706.8 bn |
| … compared with the last private round ($965 bn) | −47% | −27% |
| Dilution (new ÷ all shares) | 19.6% | 14.1% |
| Coverage | 7.30× | 7.27× |
| Institutions / private investors receive | 13.6% / 14.3% of what they ordered | 13.7% / 14.4% |
| DCF value per share after the IPO | $80.76 | $223.90 |
| Expected first-day pop (heuristic) | 33.9% | 33.9% |
| Expected first-day close | $334.76 | $495.33 |
| Money left on the table | $33.9 bn | $33.9 bn |
| Index | not eligible: dual-class shares | not eligible: dual-class shares, free float 14.1% < 15% |
| Warnings | V008 margin, V014 hype, V017 methods disagree, V020 revenue per employee | V014, V015 free float, V017, V020 |

The offer price ends **above fair value** in both cases. Demand is so strong
that the book is covered more than seven times even at the top of the band;
the US rules allow pricing 20% above the range, and the hype factor of 9
lets the book run past the IPO discount entirely. In Sweden the maximum price
would be the top of the range: $210 and $310.

**Monte Carlo** (10,000 draws, seed 42, the ten scenario drivers varied as in
§12 of the design):

| | Case A | Case B |
|---|---:|---:|
| Fair value, 5th percentile | $170.80 | $261.94 |
| Fair value, median | $229.40 | $336.95 |
| Fair value, 95th percentile | $293.60 | $420.09 |
| Chance fair value is below the offer price | **70.1%** | **74.2%** |

In seven draws out of ten, IPO buyers pay more than the company is worth on
the model's assumptions. They buy the pop and the story, not the value.

**What would a $2 trillion IPO need?** A $2 trillion market cap after the
IPO means P × (1.64 bn + $100 bn ÷ P) = $2,000 bn, so P = $1,158.54 per share.
Even with all the weight on the comparables, that needs a multiple of
(1,158.54 × 1.64 − 70 + 1.8) ÷ 88.7 = about 20.6 times next year's revenue,
against the 12× assumed here.

## 8. Sensitivity

Each row changes one assumption from the base case, without management's
floor. DCF and fair value per share in dollars, and the resulting offer
price.

| Change | A: DCF | A: fair value | A: offer | B: DCF | B: fair value | B: offer |
|---|---:|---:|---:|---:|---:|---:|
| Base case | 39.49 | 234.88 | 250.00 | 199.83 | 347.12 | 370.00 |
| Wage inflation 5% instead of 8% | 72.76 | 258.17 | 280.00 | 233.08 | 370.39 | 400.00 |
| Stock pay 50% of cash pay instead of 100% | 78.13 | 261.93 | 280.00 | 238.34 | 374.08 | 400.00 |
| Training compute 15% of revenue instead of 22% | 127.02 | 296.15 | 315.00 | 287.20 | 408.27 | 435.00 |
| Comparable multiple 8× instead of 12× | 39.49 | 169.96 | 185.00 | 199.83 | 282.20 | 305.00 |
| Comparable multiple 16× | 39.49 | 299.80 | 320.00 | 199.83 | 412.04 | 440.00 |
| DCF weight 100% | 39.49 | 39.49 | 42.50 | 199.83 | 199.83 | 215.00 |
| Terminal growth 3.5% instead of 2.5% | 47.78 | 240.68 | 255.00 | 214.41 | 357.32 | 380.00 |
| GPU fleet 0.6× revenue (capex 20% / 12%) | 162.81 | 321.21 | 345.00 | 269.62 | 395.97 | 425.00 |

- **The GPUs dominate.** A fleet of 0.6× revenue instead of 0.9× (capex 20%
  instead of 30% for Case A) adds $123 to Case A's DCF price. Moving from 3- to
  5-year GPUs adds $160.
- **Training compute is next.** 15% of revenue instead of 22% adds $88 to
  either DCF.
- **Talent is real but smaller.** Pay rising 5% instead of 8% a year adds
  $33 to either DCF and $23 to fair value. Halving stock pay to 50% of cash
  pay adds $39 to either DCF and $27 to fair value.
- **The comparables move fair value one for one with the market's mood.**
  Each turn of the multiple is worth $16.2 per share of fair value (30% ×
  $88.7 bn ÷ 1.64 bn shares), in both cases.
- **On cash flows alone the IPO fails.** With 100% DCF weight, Case A is
  worth $39.49, its cash.

## 9. What the analysis says

1. **A frontier AI lab is an infrastructure business wearing software
   clothes.** Its gross margin can reach software levels, but its GPU fleet
   behaves like heavy industry's machinery: capex of 18–30% of revenue, for
   ever. How long the GPUs last decides whether the operations are worth
   nothing or a quarter of a trillion dollars.
2. **"Loss-making" is partly an accounting choice.** The same cash flows show
   an operating loss in year 1 with 3-year depreciation and a profit with
   5-year depreciation. Free cash flow, which the DCF values, is negative in
   year 1 either way.
3. **The private round is the obstacle.** Both cases value Nimbus far below
   the $965 bn post-money of its last round. A listing means a down round of
   27–47%, unless investors pay a comparables multiple far above 12×.
4. **The market, not the model, would set the price.** With hype at 9 and very
   high interest, the book runs to the top of the US band, above fair value,
   and the expected first-day pop is still 34%: about $34 bn left on the table.
5. **The talent war costs less than the compute war.** At $15–37 m of revenue
   per employee, people are a small share of costs, even at $2.1 m of pay
   each; compute and GPUs are most of them.

## 10. Reproducing the numbers

The two scenario files, written by `pm-valuation --save` from the answers in
§3 (Case B differs only in `capex_pct: 18%` and `useful_life: '5'`):

```yaml
pm_valuation: 1
company:
  name: Nimbus Cognition Inc.
  ticker: NMBS
  sector: b2b_saas
  dual_class: 'yes'
  market: us
market:
  tam: 1500bn
  tam_growth: 30%
  sam_share: 60%
  structure: oligopoly
customers:
  last_fy_revenue: 65bn
  now: 400,000
  arpu: 162,500
  arpu_growth: 5%
  churn: 10%
  growth_y1: 60%
people:
  headcount: 4,500
  loaded_cost: 1.05m
  wage_inflation: 8%
  elasticity: '0.5'
  growth_floor: 5%
  split_rnd: 55%
  split_snm: 20%
  split_gna: 12%
  split_ops: 13%
costs:
  infra_fixed: 8bn
  infra_per_customer: 30,000
  other_cogs_pct: 10%
  cac_paid: 48,750
  rnd_nonstaff_pct: 22%
  sbc_pct: 100%
capital:
  capex_pct: 30%
  useful_life: '3'
  nol: 15bn
  cash: 70bn
rates:
  beta_stage1: '1.8'
  beta_stage2: '1.3'
  size_premium_1: 0%
  size_premium_2: 0%
  execution_premium: 5%
offering:
  shares_pre: 1,640,000,000
  raise: 100bn
  gross_spread: 1.5%
  other_expenses: 300m
investors:
  inst_interest: very_high
  n_institutions: '300'
  avg_ticket: 1bn
  retail_interest: very_high
  n_retail: 2,000,000
  retail_application: 5,000
  hype: '9'
  comps_multiple: 12x
management:
  last_round: 965bn
```

```bash
pm-valuation --load nimbus-3y.yaml --no-tui --mode deterministic --export nimbus-3y.md
pm-valuation --load nimbus-5y.yaml --no-tui --mode deterministic --export nimbus-5y.md
```

For §7, add `min_market_cap: none` under `management:`; for the Monte Carlo,
use `--mode montecarlo`. The report's sections hold every table of §4–§7.

## Sources

[cnbc]: https://www.cnbc.com/2026/08/17/anthropic-says-annualized-revenue-climbed-to-65-billion-in-july.html
[forge]: https://forgeglobal.com/insights/anthropic-upcoming-ipo-news/
[luminix]: https://www.useluminix.com/reports/company-overviews/what-do-we-know-about-the-anthropic-ipo
[sacra]: https://sacra.com/c/anthropic/
[orrick]: https://www.orrick.com/News/2026/02/Anthropic-Raises-30B-Series-G-at-380B-Post-Money-Valuation
[tiger]: https://www.itiger.com/news/1154519858
[saastr]: https://www.saastr.com/anthropic-only-has-5000-employees/
[propk]: https://propakistani.pk/2026/06/19/openai-suffered-8x-more-losses-in-2025-spending-reached-34b/amp/
[fortune]: https://www.fortune.com/2026/02/18/openai-chatgpt-creator-record-million-dollar-equity-compensation-ai-tech-talent-war-career-retention-sam-altman-millionaire-staff
[tigergpu]: https://www.itiger.com/news/1107971573
[fwmba]: https://fourweekmba.com/ai-nvidia-gpu-depreciation-durability-debate-huang-2026/

- [CNBC, 17 Aug 2026: Anthropic tells investors annualized revenue run rate climbed to $65 billion in July][cnbc]
- [Forge Global: Anthropic upcoming IPO news][forge]
- [Luminix: What do we know about the Anthropic IPO][luminix]
- [Sacra: Anthropic revenue, valuation and funding][sacra]
- [Orrick: Anthropic raises $30B Series G at $380B post-money valuation][orrick]
- [Tiger Brokers / The Information: Anthropic lowers gross margin forecast][tiger]
- [SaaStr: Anthropic only has 5,000 employees][saastr]
- [ProPakistani: OpenAI 2025 losses and spending][propk]
- [Fortune, 18 Feb 2026: OpenAI's record equity compensation][fortune]
- [Tiger Brokers: Can GPUs really be used for 6 years?][tigergpu]
- [FourWeekMBA: The GPU depreciation debate][fwmba]

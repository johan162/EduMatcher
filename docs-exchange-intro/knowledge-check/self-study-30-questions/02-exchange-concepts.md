# Exchange Concepts Knowledge Check — Variant 02

Purpose: verify that the student has read [How a Financial Exchange Works](../how-exchange-works.md) and internalized the core principles of a modern exchange, across its full scope — market history, order mechanics, risk and compliance, and technology infrastructure.

## Name/ID

&nbsp;

---


&nbsp;

## Instructions

- There are 30 questions.
- Each question has five statements (A-E) which may be false or true.
- Select all statements you believe to be correct by clearly filling the square before the question.
- Each question may have multiple correct statements (for some, all five statements may be correct).
- There are always at least one correct statement.

## Scoring

- +1 point for each correct option selected.
- -2 points for each incorrect option selected.
- 0 points for options not selected.
- Final test score is capped at a minimum of 0: if raw total is negative, recorded score is 0.
- A passing score is 70% of the maximum rounded down to the nearest integer.

<div style="page-break-after: always;"></div>

## Questions

### 1. Debt, equity, and the IPO
- [ ] A. A bank loan is generally better suited than a bond issue to raising hundreds of millions of dollars
- [ ] B. Underwriters guarantee an IPO company its proceeds even if investor demand is weaker than expected
- [ ] C. A roadshow is used to gauge institutional demand and help set the IPO price
- [ ] D. Common stock typically carries a higher-priority claim on dividends than preferred stock
- [ ] E. Bondholders are creditors with a legal claim against a company's assets

### 2. The three promises of an exchange
- [ ] A. Price discovery means the current price reflects the aggregate opinion of willing participants
- [ ] B. Liquidity means a participant can convert an asset to cash without an indefinite wait for a counterparty
- [ ] C. The Securities Exchange Act of 1934 was passed before the 1929 crash
- [ ] D. Regulation NMS helped shape a US market with more than a dozen competing registered equity exchanges
- [ ] E. Fairness means the rules for who trades first are decided case-by-case by exchange staff

### 3. Participants and the maker/taker distinction
- [ ] A. Payment for order flow exists partly because retail flow is more profitable to serve than institutional flow
- [ ] B. A quote is always a strictly one-sided instruction submitted by any participant
- [ ] C. Institutional investors often use VWAP algorithms and dark pools to reduce market impact
- [ ] D. An aggressive order that immediately executes against a resting order is submitted by the "maker"
- [ ] E. Demutualisation converted many exchanges from member-owned mutuals to for-profit public companies

### 4. Regulators and rules
- [ ] A. The CFTC oversees US futures and derivatives exchanges
- [ ] B. FINRA is a self-regulatory organisation overseeing broker-dealers in the US
- [ ] C. The Market Access Rule (15c3-5) requires broker-dealers with market access to have pre-trade risk controls and the ability to halt trading
- [ ] D. MiFID II applies only to US equity markets
- [ ] E. Regulation SHO governs short sales, including the locate requirement

### 5. Historic market crashes
- [ ] A. The Dow fell approximately 89% from its 1929 peak to its 1932 trough
- [ ] B. The Brady Commission's central recommendation was to create automatic trading halts
- [ ] C. The 1929 crash was investigated and found free of manipulation or fraud
- [ ] D. Portfolio insurance selling is cited as an amplifying factor in the 1987 crash
- [ ] E. Black Monday, 19 October 1987, saw US markets fall 22.6% in a single day


### 6. Instruments and the round lot
- [ ] A. A futures contract is a claim on an asset that already exists, like a share
- [ ] B. Historically, odd-lot quotes were excluded from the NBBO and consolidated tape
- [ ] C. Regulators have never revisited the exclusion of odd-lot data from public feeds
- [ ] D. For most US equities, a round lot is commonly 100 shares
- [ ] E. An odd lot is an order for fewer shares than the symbol's round lot

### 7. Stop and stop-limit orders
- [ ] A. A stop-loss order is a sell stop used to automatically exit a losing position
- [ ] B. A stop-limit order can fail to fill if the market gaps through the limit price
- [ ] C. Stop orders are universally implemented at the exchange level on every venue
- [ ] D. A plain stop order converts to a market order when triggered
- [ ] E. A stop-limit order guarantees execution once triggered

### 8. Trailing stop mechanics
- [ ] A. Before it fires, a trailing stop competes for queue position against resting limit sell orders
- [ ] B. The mechanism that advances a trailing stop favourably is called the ratchet
- [ ] C. A trailing stop's stop price freezes when the market moves against the position
- [ ] D. Once triggered, a trailing stop matches directly against the best available bid
- [ ] E. If a $5 trail is set and the price rises from $150 to $170 then falls to $167, the stop is at $165

### 9. Hidden liquidity priority rules
- [ ] A. Dark pools always show full pre-trade transparency of resting orders
- [ ] B. On IEX, an aggressive order can cross to the midpoint against a resting midpoint peg
- [ ] C. A midpoint peg order never displays a price in the visible book
- [ ] D. The "back of queue on refresh" rule is the least common approach to iceberg replenishment
- [ ] E. On some exchanges, fully displayed orders have strict priority over hidden orders at the same price

### 10. OCO and combo orders in practice
- [ ] A. A pairs trade is an example of a combo order across two instruments
- [ ] B. A calendar spread on CME involves buying and selling the same futures contract month
- [ ] C. Eurex offers combination option strategies such as straddles, strangles, and butterflies
- [ ] D. A bracket order combines a take-profit and a stop-loss as an OCO pair
- [ ] E. Combo orders eliminate leg risk entirely by design

### 11. Implied orders
- [ ] A. A spread price of −$2.00 means January is trading $2.00 above February
- [ ] B. Most exchanges allow unlimited depth of implied-of-implied chains
- [ ] C. Implied orders are derived from combining orders in different but related books
- [ ] D. When an implied order matches, it consumes real orders from real underlying books
- [ ] E. Continuous recalculation of implied prices is required after every relevant book change

### 12. Time-in-force quick facts
- [ ] A. FOK orders accept partial fills as a matter of standard practice
- [ ] B. ATO orders are valid only during the opening auction
- [ ] C. GTD orders remain active until filled, cancelled, or their expiry date, whichever comes first
- [ ] D. An IOC order accepts a partial fill and cancels the unfilled remainder
- [ ] E. ATO orders submitted after the opening auction concludes are typically rejected

### 13. Depth and the order book
- [ ] A. A tight spread generally indicates a liquid, efficiently priced market
- [ ] B. Quantity at a price level is the sum of all resting orders' sizes at that exact price
- [ ] C. Level 2 data shows only the single best bid and ask
- [ ] D. The current market price is always identical to a value stored directly on a resting order
- [ ] E. The mid price is the arithmetic average of the best bid and best ask

### 14. Sweeping the book, numerically
*Scenario: the bid side holds 2,000 @ $150.34, 1,500 @ $150.33 and 3,200 @ $150.32, and a 3,500-share market sell arrives.*

- [ ] A. The spread between a best bid of $150.34 and best ask of $150.35 is $0.02
- [ ] B. The mid price between $150.34 and $150.35 is $150.345
- [ ] C. After the sweep, the new best bid is $150.32
- [ ] D. The market sell exhausts both the $150.34 and the $150.33 levels
- [ ] E. Sweeping through multiple book levels can never produce a worse average price than the top-of-book price

### 15. Price-time priority and amendments
- [ ] A. Pro-rata allocation rewards order size over arrival speed
- [ ] B. A cancel-and-replace always retains the original order's queue priority
- [ ] C. Better price always takes priority over an earlier-arriving order at a worse price
- [ ] D. CME uses a largely pro-rata "allocation" algorithm for its SOFR futures
- [ ] E. A quantity decrease amendment retains the resting order's original timestamp

### 16. Tick size history and regulation
- [ ] A. Rule 612 was adopted partly to prevent re-fragmentation into sub-penny quoting after decimalisation
- [ ] B. US stocks traded in fractions of a dollar from 1792 until decimalisation around 2000-2001
- [ ] C. CME's E-mini S&P 500 futures tick in increments of 0.25 index points
- [ ] D. Tick size is uniform across every venue that lists the same underlying stock
- [ ] E. Decimalisation roughly doubled quoted spreads on liquid stocks

### 17. Rounding a midpoint to a valid tick
*Scenario: the best bid is $150.30 (tick 15030) and the best ask is $150.33 (tick 15033).*

- [ ] A. The raw midpoint corresponds to a mathematically exact, tick-aligned price
- [ ] B. Round-half-to-even ("banker's rounding") is one common convention for resolving a midpoint that falls exactly halfway between two ticks
- [ ] C. Rounding the midpoint up gives the extra half-cent to the seller
- [ ] D. The raw midpoint tick count is 15031.5
- [ ] E. A matching engine and a downstream P&L system must apply the identical rounding rule to avoid reconciliation breaks

### 18. The matching engine's core loop
- [ ] A. Checking dormant stop orders happens before any fill events are published
- [ ] B. A fully filled order publishes a FILLED event and is removed from the book
- [ ] C. The engine dequeues messages and determines whether a new order can match resting orders
- [ ] D. A partially filled order rests the remaining unfilled quantity in the book
- [ ] E. Cancels and modifications also generate published events

### 19. The life of a trade
- [ ] A. The trade record captures the IDs of both orders and both gateways involved
- [ ] B. Every trade is published over the market data feed to subscribers
- [ ] C. A partial fill leaves an order resting with reduced remaining quantity
- [ ] D. Both sides of a fill receive execution reports detailing quantity, price, and remaining quantity
- [ ] E. The aggressor field only matters for regulatory reporting, not fee calculation

### 20. Market maker protection
- [ ] A. MMP counts fills within a configured rolling time window per market maker
- [ ] B. If MMP fires, all of that market maker's quotes are automatically cancelled
- [ ] C. MMP exists purely as a courtesy with no market-wide liquidity benefit
- [ ] D. A market maker enters a protection period after MMP fires, before re-quoting
- [ ] E. MMP parameters are typically configured per market maker per symbol

### 21. Auction imbalance and tie-breaking
- [ ] A. If imbalance is tied between two candidate prices, the algorithm prefers the price in the direction of remaining pressure
- [ ] B. NYSE begins publishing closing auction imbalances at 3:50pm for a 4:00pm uncross
- [ ] C. Imbalance messaging shows how many more shares are on one side than the other at the indicative price
- [ ] D. Proximity to a reference price is used as a final tie-breaker if imbalance and pressure are both equal
- [ ] E. The indicative uncross price is recalculated only once, at the very start of the auction

### 22. Trading session transitions
- [ ] A. PRE_OPEN transitions to OPENING_AUCTION at the scheduled auction start time
- [ ] B. CLOSED marks the point where GTC orders are persisted and the book state is saved
- [ ] C. The session state machine allows any transition the matching engine requests, without restriction
- [ ] D. CONTINUOUS can transition directly to CLOSING_AUCTION on an end-of-day signal
- [ ] E. HALTED can transition to RESUMPTION_AUCTION once the halt period expires

### 23. Index membership and consequences
- [ ] A. Russell and FTSE index families reconstitute with full committee discretion, exactly like the S&P 500
- [ ] B. S&P 500 eligibility requires, among other things, positive earnings over the most recent four quarters and the most recent quarter
- [ ] C. Committee approval is required for S&P 500 inclusion even if all numeric rules are met
- [ ] D. Free-float adjustment excludes shares held by founders or governments that never trade
- [ ] E. Removal from a major index tends to cause forced selling pressure

### 24. What indexes drive
- [ ] A. Index futures and index options settle against the published index level
- [ ] B. The VIX is calculated directly from a company's balance sheet rather than from option prices
- [ ] C. Index calculation is deliberately kept separate from the matching engine's critical path
- [ ] D. Stale prices can make an index lag reality when a constituent hasn't traded recently
- [ ] E. "Triple witching" refers to the simultaneous expiry of index futures, index options, and stock options

### 25. Pre-trade checks in sequence
- [ ] A. Format and syntax validation is typically the cheapest, and therefore earliest, pre-trade check
- [ ] B. Running all checks in parallel is described as the preferred design for minimising latency
- [ ] C. Position and credit limit checks are generally cheaper to run than a rate-limit check
- [ ] D. Fat-finger price checks compare the submitted price against a cached reference price
- [ ] E. A self-match prevention pre-check can occur before the order reaches the matching engine

### 26. Circuit breakers, design principles
- [ ] A. A minimum-halt-with-conditional-extension approach bounds uncertainty while allowing more time if needed
- [ ] B. Every major exchange uses an identical halt duration regardless of instrument or move size
- [ ] C. Eurex's volatility interruptions use an auction that runs until equilibrium is found, not a fixed timer
- [ ] D. A fixed halt duration offers participants predictability at the cost of calibration precision
- [ ] E. Larger price moves are argued to require more time for margin calls to be calculated and funded

### 27. Price collars and self-match prevention
- [ ] A. A static collar compares an order's price to the previous official close
- [ ] B. A kill switch leaves a participant's connection active so they can keep trading immediately
- [ ] C. Cancel Aggressor is described as the most common default SMP policy
- [ ] D. A dynamic collar compares an order's price to the most recent traded price
- [ ] E. Wash trading is legal as long as both resting and incoming orders come from the same participant

### 28. Mass cancel vs kill switch
- [ ] A. After a kill switch fires, reconnection and authentication are typically required before resuming
- [ ] B. Mass cancel messages generate individual cancellation events in the audit trail
- [ ] C. A mass cancel can be initiated by the exchange itself, never by the participant
- [ ] D. A kill switch can be triggered automatically on a lost gateway connection
- [ ] E. After a mass cancel, the participant's gateway connection remains fully active

### 29. Drop copy and the audit trail
- [ ] A. The audit trail must be complete, immutable, and retained for several years, commonly five to seven depending on jurisdiction and record type
- [ ] B. A drop copy sequence number lets a recipient detect and request replay of missed events
- [ ] C. A clearing broker can use drop copy to begin clearing and settlement before end-of-day reports arrive
- [ ] D. Drop copy is a public feed available to any market participant who subscribes
- [ ] E. Deterministic replay means the same input sequence must always reproduce the same fills and book state

### 30. Knight Capital, root causes
- [ ] A. The deployment process lacked automated verification that all eight servers ran the correct code
- [ ] B. Knight lacked clear incident-response guidance on when to disconnect a malfunctioning system
- [ ] C. Knight lacked a firm-wide position or notional limit that could have halted the runaway system sooner
- [ ] D. The exchange's own systems rejected the majority of Knight's erroneous orders
- [ ] E. The dangerous Power Peg code had been fully deleted from the codebase before the incident

&nbsp;

---

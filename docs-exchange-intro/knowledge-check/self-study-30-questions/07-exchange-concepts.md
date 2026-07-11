# Exchange Concepts Knowledge Check — Variant 07

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

### 1. Capital formation review
- [ ] A. Retained earnings, debt, and equity are the three broad categories of growth capital described
- [ ] B. A bond's face value is repaid in full when the bond matures, assuming no default
- [ ] C. Equity holders are guaranteed a fixed periodic payment analogous to a bond coupon
- [ ] D. Preferred shareholders typically lack the voting rights common shareholders have
- [ ] E. Limited liability means shareholders cannot lose more than what they invested

### 2. Historical figures and market lore
- [ ] A. Jesse Livermore is described as having profited heavily by shorting into the 1929 crash
- [ ] B. Thomas Peterffy's automated order submission dispute with NASDAQ predates modern algorithmic trading rules
- [ ] C. Joseph de la Vega's 1688 work is described as the oldest known book about stock trading
- [ ] D. The stock ticker was invented by Thomas Edison alone, with no earlier inventor mentioned
- [ ] E. Isaac Le Maire's 1609 VOC scheme is described as an early large-scale short-selling operation

### 3. Participants and fee incentives
- [ ] A. Retail order flow is generally considered less informed than institutional flow
- [ ] B. HFT firms are estimated to account for roughly half of US equity trading volume
- [ ] C. A maker earns a rebate under standard maker-taker fee structures because they provide liquidity
- [ ] D. Payment for order flow exists partly because retail orders carry low adverse-selection risk for market makers
- [ ] E. A prime broker's core clients are typically retail day traders

### 4. Regulatory landmarks
- [ ] A. Regulation NMS was adopted in 2005 and phased in through 2007
- [ ] B. MiFID II mandates algorithmic trading controls, including kill switch testing, in the EU
- [ ] C. The Market Access Rule (15c3-5) predates and is unrelated to the 2010 Flash Crash
- [ ] D. Regulation SHO governs the locate requirement for short sales
- [ ] E. Dodd-Frank and EMIR both push standardised OTC derivatives toward central clearing

### 5. Order types, a mixed review
- [ ] A. A market order's execution is generally treated as close to guaranteed in normal continuous trading, though its price is not
- [ ] B. An iceberg order's hidden reserve size is fully disclosed to other participants once the peak is visible
- [ ] C. A trailing stop's stop price can only move upward, never downward, once set for a long position
- [ ] D. An OCO pair automatically cancels the untouched leg once the other leg fills or is cancelled
- [ ] E. Implied orders derive synthetic prices from existing orders without consuming any real liquidity when matched

<div style="page-break-after: always;"></div>

### 6. Depth, spread, and the book
- [ ] A. A wide spread generally indicates an illiquid or uncertain market
- [ ] B. The order book contains only orders that have already executed
- [ ] C. Cumulative depth within N ticks estimates the shares tradeable before the price moves by roughly that range
- [ ] D. A shallow market can be swept through several price levels by a single moderately sized order
- [ ] E. Level 2 data is also referred to as market depth data

### 7. Price-time priority, amendments recap
- [ ] A. Increasing a resting order's quantity is treated as a concession and retains queue priority
- [ ] B. Decreasing a resting order's quantity is treated as a concession and retains queue priority
- [ ] C. A cancel-and-replace always produces a fresh timestamp regardless of what changed
- [ ] D. Under FIFO, the earliest-arriving order at a price level is filled first
- [ ] E. Options markets are cited as sometimes using pro-rata allocation instead of strict FIFO

### 8. Tick size, historical and modern
- [ ] A. NYSE traded in fractions of a dollar from 1792 until decimalisation around 2000-2001
- [ ] B. The "teenie" refers to a sixteenth of a dollar
- [ ] C. Decimalisation is described as roughly halving quoted spreads on liquid stocks
- [ ] D. The Tick Size Pilot Program clearly demonstrated that wider ticks improved small-cap liquidity
- [ ] E. MiFID II's European tick regime uses smaller absolute increments for lower-priced stocks

### 9. The matching engine and life of a trade
- [ ] A. A trade record captures the trade ID, symbol, price, quantity, and both order and gateway IDs
- [ ] B. The aggressor field can influence fee calculation, regulatory reporting, and clearing treatment
- [ ] C. A partial fill leaves the remaining unfilled quantity resting in the book
- [ ] D. An order can only ever receive a single fill notification over its entire lifetime
- [ ] E. Every trade is published over the market data feed within microseconds of occurring

### 10. Market makers and MMP, a review
- [ ] A. A presence obligation of 85% requires the market maker to quote for at least that share of the session
- [ ] B. Adverse selection describes a market maker systematically trading against better-informed counterparties
- [ ] C. MMP fires automatically once a configured fill-count threshold within a rolling window is exceeded
- [ ] D. After MMP fires, the market maker may resume quoting instantly with no assessment period
- [ ] E. Quote refresh policies determine what happens to the surviving leg after one side of a quote fills

<div style="page-break-after: always;"></div>

### 11. Auctions, a third worked scenario
- [ ] A. Given buy orders 300@$45, 600@$44 and sell orders 500@$44, 700@$45, the executable volume at $44 is 500
- [ ] B. In that same scenario, the executable volume at $45 is min(300, 500+700) = 300
- [ ] C. Between $44 (500 executable) and $45 (300 executable), the equilibrium price is $44
- [ ] D. A buyer bidding $45 in that scenario, if matched, pays the $44 equilibrium price
- [ ] E. Orders that cannot execute at the equilibrium price are discarded permanently rather than continuing into continuous trading

### 12. Indexes and risk control
- [ ] A. Market-wide circuit breakers in the US trigger from S&P 500 index moves, not single-stock moves
- [ ] B. The VIX is derived from index-option prices and functions as a market-wide volatility gauge
- [ ] C. Index calculation is deliberately handled by a component separate from the matching engine
- [ ] D. Triple witching refers to the simultaneous expiry of stock options, index options, and index futures
- [ ] E. A single incorrect index print is described as having no downstream effect on derivatives settlement

### 13. Circuit breakers, US tiers and LULD
- [ ] A. Level 1 and Level 2 US market-wide halts are not triggered in the last 35 minutes of the session
- [ ] B. Level 3 triggers regardless of time of day and ends trading for the remainder of the session
- [ ] C. LULD Tier 2 (other NMS stocks) has a wider regular-hours band than Tier 1
- [ ] D. A LULD pause is triggered the instant price exits its band, with no monitoring window
- [ ] E. March 2020 saw four Level 1 halts, and Level 2 was never triggered during that period

### 14. Clearing hierarchy and DvP, revisited
- [ ] A. A non-clearing member's trades are guaranteed to the CCP by a clearing broker
- [ ] B. DvP means securities and cash transfer conditionally, with neither released until both are available
- [ ] C. Herstatt risk refers to a bank collapsing between one leg of a settlement completing and the other failing
- [ ] D. US equities currently settle on a T+2 basis
- [ ] E. A clearing member's guarantee fund contribution is described as the very first loss layer before a defaulting participant's own margin

<div style="page-break-after: always;"></div>

### 15. Trade busting, real incidents
- [ ] A. Knight Capital's fills were, in the regulatory sense, mostly clearly erroneous trades
- [ ] B. The Facebook IPO delay in 2012 stemmed from a defect in NASDAQ's IPO cross process
- [ ] C. BATS withdrew its own IPO within minutes after its own matching engine defect crashed its stock's price
- [ ] D. NASDAQ paid a then-record SEC penalty related to the Facebook IPO malfunction
- [ ] E. Both the Facebook and BATS incidents involved a single erroneous order price rather than an engine-level defect

### 16. Regulatory surveillance, patterns and evidence
- [ ] A. Front running is described as a serious breach of fiduciary duty as well as illegal
- [ ] B. Insider trading is handled under the same regulatory framework as order-flow manipulation, per the document
- [ ] C. The audit trail is described as a key source of evidence in insider trading investigations
- [ ] D. Quote stuffing is intended to consume the matching engine's bandwidth to slow down competitors
- [ ] E. Modern surveillance systems are described as never using machine learning for pattern detection

### 17. Knight Capital, systemic lessons
- [ ] A. A lack of automated post-deployment verification allowed a misconfigured server to run stale code
- [ ] B. Dangerous legacy code being merely deactivated rather than deleted is cited as a root cause
- [ ] C. Every one of Knight's orders violated an explicit NYSE trading rule
- [ ] D. Automated anomaly detection comparing per-server activity could have flagged the problem within seconds
- [ ] E. The exchange itself was found capable of determining whether Knight's overall strategy made business sense

### 18. Speed bumps and market structure
- [ ] A. IEX's speed bump is implemented via a coiled fibre-optic cable rather than a software delay
- [ ] B. A fixed delay preserves relative timing differences between orders rather than erasing them
- [ ] C. Selectively delaying only cancel messages can counter last-look practices
- [ ] D. IEX is described as having captured a majority of total US equity trading volume since 2016
- [ ] E. European regulators have discussed asymmetric cancel-message speed bumps under MiFID II's algorithmic trading framework

<div style="page-break-after: always;"></div>

### 19. Technology transport and protocols, review
- [ ] A. FIX messages use the SOH control character as the field delimiter on the wire
- [ ] B. ITCH messages are parsed via fixed binary offsets rather than text scanning
- [ ] C. UDP multicast is preferred for market data partly because one packet reaches many subscribers at once
- [ ] D. TCP unicast is used as a recovery channel to retransmit missed sequence numbers
- [ ] E. Order submission generally uses UDP because reliability is not important for orders

### 20. Resilience, RPO/RTO, and order IDs
- [ ] A. A matching engine's RPO target is effectively zero committed trades or acknowledgements lost
- [ ] B. A batch reporting system generally has a stricter RTO requirement than a matching engine
- [ ] C. Pre-allocated ID ranges per site can leave gaps in the ID sequence after a failover
- [ ] D. UUIDs guarantee practical uniqueness without requiring coordination between sites
- [ ] E. Monotonic timestamp enforcement is described as unnecessary once sequencing infrastructure exists

### 21. Failover mechanics
- [ ] A. Active-passive failover with heartbeat monitoring risks a split-brain condition if both sites believe the other has failed
- [ ] B. Quorum requirements and fencing are both cited as mitigations for split-brain
- [ ] C. Active-active designs are described as common because distributed consensus adds negligible latency
- [ ] D. A near site plus a far site is described as a common compromise between fast failover and disaster protection
- [ ] E. Manual failover avoids false positives at the cost of slower response time

### 22. Market data architecture
- [ ] A. Incremental updates (deltas) describe only what changed since the previous message
- [ ] B. Periodic full snapshots let a subscriber resynchronise after missing incremental updates
- [ ] C. Conflation reduces message volume by merging updates at the cost of losing intermediate states
- [ ] D. Sequencing scope, reset policy, and wrap behaviour are all cited as details that must be explicit in protocol documentation
- [ ] E. Depth-of-book subscriptions require less bandwidth than top-of-book subscriptions

<div style="page-break-after: always;"></div>

### 23. Market data economics, a review
- [ ] A. A proprietary direct feed is generated by the venue's own matching engine, bypassing SIP aggregation delay
- [ ] B. The SIP's content and pricing are governed collectively by the exchanges under SEC oversight
- [ ] C. Critics argue exchanges have a conflict of interest between improving the public SIP and selling premium proprietary feeds
- [ ] D. Europe's consolidated tape debate under MiFID II is described as identical in structure to the long-established US SIP
- [ ] E. Market data and connectivity revenue is described as having grown to a substantial share of exchange profit

### 24. Latency and hardware acceleration
- [ ] A. Spread Networks' 2010 fibre route reduced Chicago-New York round-trip latency to roughly 13 milliseconds
- [ ] B. Microwave links later achieved the Chicago-New York route in roughly 8 milliseconds
- [ ] C. FPGAs implement logic in dedicated circuits, enabling responses in tens of nanoseconds
- [ ] D. Kernel bypass technologies like OpenOnload eliminate the standard Linux network stack's added latency
- [ ] E. PTP is described as less precise than standard NTP for clock synchronisation

### 25. Observability and incident command
- [ ] A. The four golden signals and related production metrics are broken out by session state because acceptable baselines differ by phase
- [ ] B. Metrics tell you *why* something went wrong, while logs tell you only *that* something is wrong
- [ ] C. A correlation ID lets an operator trace a single order's path across gateway, risk checks, matcher, and market-data publish
- [ ] D. An SLO paired with its target defines an error budget, the tolerated degradation over a period
- [ ] E. A severity classification (e.g., SEV1-SEV3) is described as driving escalation and communication expectations during an incident

### 26. Determinism, replay, and reference data
- [ ] A. A deterministic matching engine must avoid hidden non-determinism such as mid-execution clock reads
- [ ] B. Write-ahead logging records an input message before it is processed
- [ ] C. GTC orders are described as requiring persistence beyond the standard WAL mechanism
- [ ] D. A contract multiplier loaded at 500 instead of 50 would understate margin requirements by a factor of ten
- [ ] E. The 2015 NYSE outage is attributed to a gateway software version incompatibility

<div style="page-break-after: always;"></div>

### 27. Crypto venues, a final review
- [ ] A. Centralised crypto exchanges commonly act as both matching venue and de facto custodian for user balances
- [ ] B. A constant-product AMM keeps the product of its two pooled reserves constant during a trade
- [ ] C. Digital asset markets are overseen by a single unified regulator analogous to the SEC for US equities
- [ ] D. FTX's collapse is presented as illustrating the risk of collapsing matching, custody, and clearing into one entity
- [ ] E. Most crypto venues have historically lacked a defined opening or closing auction establishing a daily reference price

### 28. Corporate actions and reference data interplay
- [ ] A. A stock split changes a company's tick size and price scale in reference data
- [ ] B. Symbol changes from rebranding or mergers require systems tracking positions by symbol to handle remapping
- [ ] C. Reference data changes from corporate actions should propagate to all dependent systems atomically
- [ ] D. A reverse split changes the number of shares per position without changing per-share price
- [ ] E. Reference data errors are described as a rare cause of real exchange outages compared to matching-engine bugs

### 29. Options mechanics, pin risk revisited
- [ ] A. A writer of a call struck at $150 who is assigned when the stock closes at $150.03 must deliver at $150 regardless of Monday's opening price
- [ ] B. Pin risk is sharpest around triple witching, when many related instruments resolve exercise/assignment simultaneously
- [ ] C. A position that closes just out-of-the-money can never end up exercised, regardless of the official settlement print
- [ ] D. Physical delivery for one US equity option contract typically involves 100 shares
- [ ] E. Assignment is the writer's exercise decision, while exercise is the holder's obligation

<div style="page-break-after: always;"></div>

### 30. Cross-cutting numeric and factual review
- [ ] A. A midpoint peg fill between a $99.98 bid and $100.02 ask occurs at exactly $100.00
- [ ] B. A 10,000-share position with a VWAP entry of $153.33 and a current price of $160 has an unrealised P&L of roughly $66,700
- [ ] C. The equilibrium price in a call auction is the price that maximises min(cumulative bids, cumulative asks)
- [ ] D. A 2010 Flash Crash busting threshold of 60% deviation from a pre-crash reference price is cited in the document
- [ ] E. RPO for a matching engine is described as tolerating up to a few seconds of committed trade loss

&nbsp;

---

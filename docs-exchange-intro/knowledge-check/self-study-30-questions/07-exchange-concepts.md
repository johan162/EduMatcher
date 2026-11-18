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
- [ ] A. A bond's face value is repaid in full when the bond matures, assuming no default
- [ ] B. Retained earnings, debt, and equity are the three broad categories of growth capital described
- [ ] C. Preferred shareholders typically lack the voting rights common shareholders have
- [ ] D. Equity holders are guaranteed a fixed periodic payment analogous to a bond coupon
- [ ] E. Limited liability means shareholders cannot lose more than what they invested

### 2. Lessons from market history
- [ ] A. Short selling first appeared with electronic trading in the late 20th century
- [ ] B. Market-wide circuit breakers were introduced before any major crash had shown a need for them
- [ ] C. Black Monday 1987 showed how automated selling can feed back on itself and deepen a fall
- [ ] D. The 1929 crash led to the US securities laws of the 1930s and the creation of the SEC
- [ ] E. The 2010 Flash Crash showed that a large sell algorithm in a thinning book can move prices far from fair value within minutes

### 3. Participants and fee incentives
- [ ] A. Payment for order flow exists partly because retail orders carry low adverse-selection risk for market makers
- [ ] B. A prime broker's core clients are typically retail day traders
- [ ] C. HFT firms are estimated to account for roughly half of US equity trading volume
- [ ] D. Retail order flow is generally considered less informed than institutional flow
- [ ] E. A maker earns a rebate under standard maker-taker fee structures because they provide liquidity

### 4. Regulatory landmarks
- [ ] A. The Market Access Rule (15c3-5) was adopted before the May 2010 Flash Crash
- [ ] B. Regulation SHO governs the locate requirement for short sales
- [ ] C. Dodd-Frank and EMIR both push standardised OTC derivatives toward central clearing
- [ ] D. Regulation NMS was adopted in 2005 and phased in through 2007
- [ ] E. MiFID II mandates algorithmic trading controls, including kill switch testing, in the EU

### 5. Order types, a mixed review
- [ ] A. A market order's execution is generally treated as close to guaranteed in normal continuous trading, though its price is not
- [ ] B. Implied orders derive synthetic prices from existing orders without consuming any real liquidity when matched
- [ ] C. An OCO pair automatically cancels the untouched leg once the other leg fills or is cancelled
- [ ] D. An iceberg order's hidden reserve size is fully disclosed to other participants once the peak is visible
- [ ] E. A trailing stop's stop price can only move upward, never downward, once set for a long position

<div style="page-break-after: always;"></div>

### 6. Depth, spread, and the book
- [ ] A. A wide spread generally indicates an illiquid or uncertain market
- [ ] B. A shallow market can be swept through several price levels by a single moderately sized order
- [ ] C. The order book contains only orders that have already executed
- [ ] D. Level 2 data is also referred to as market depth data
- [ ] E. Cumulative depth within N ticks estimates the shares tradeable before the price moves by roughly that range

### 7. Price-time priority, amendments recap
- [ ] A. Under FIFO, the earliest-arriving order at a price level is filled first
- [ ] B. Decreasing a resting order's quantity is treated as a concession and retains queue priority
- [ ] C. Increasing a resting order's quantity is treated as a concession and retains queue priority
- [ ] D. A cancel-and-replace always produces a fresh timestamp regardless of what changed
- [ ] E. Options markets are cited as sometimes using pro-rata allocation instead of strict FIFO

### 8. Tick size, historical and modern
- [ ] A. Decimalisation is described as causing quoted spreads on actively traded stocks to fall sharply
- [ ] B. MiFID II's European tick regime uses smaller absolute increments for lower-priced stocks
- [ ] C. The Tick Size Pilot Program clearly demonstrated that wider ticks improved small-cap liquidity
- [ ] D. The "teenie" refers to a sixteenth of a dollar
- [ ] E. NYSE traded in fractions of a dollar from 1792 until decimalisation around 2000-2001

### 9. The matching engine and life of a trade
- [ ] A. The aggressor field can influence fee calculation, regulatory reporting, and clearing treatment
- [ ] B. An order can only ever receive a single fill notification over its entire lifetime
- [ ] C. A trade record captures the trade ID, symbol, price, quantity, and both order and gateway IDs
- [ ] D. A partial fill leaves the remaining unfilled quantity resting in the book
- [ ] E. Every trade is published over the market data feed within microseconds of occurring

### 10. Market makers and MMP, a review
- [ ] A. A presence obligation of 85% requires the market maker to quote for at least that share of the session
- [ ] B. After MMP fires, the market maker may resume quoting instantly with no assessment period
- [ ] C. MMP fires automatically once a configured fill-count threshold within a rolling window is exceeded
- [ ] D. Quote refresh policies determine what happens to the surviving leg after one side of a quote fills
- [ ] E. Adverse selection describes a market maker systematically trading against better-informed counterparties

<div style="page-break-after: always;"></div>

### 11. Auctions, a third worked scenario
*Scenario: the auction holds buy orders 300 @ $45, 600 @ $44 and sell orders 500 @ $44, 700 @ $45.*

- [ ] A. Orders that cannot execute at the equilibrium price are discarded permanently rather than continuing into continuous trading
- [ ] B. The executable volume at $44 is 500
- [ ] C. A buyer bidding $45, if matched, pays the $44 equilibrium price
- [ ] D. Between $44 (500 executable) and $45 (300 executable), the equilibrium price is $44
- [ ] E. The executable volume at $45 is min(300, 500+700) = 300

### 12. Indexes and risk control
- [ ] A. The VIX is derived from index-option prices and functions as a market-wide volatility gauge
- [ ] B. Index calculation is deliberately handled by a component separate from the matching engine
- [ ] C. A single incorrect index print is described as having no downstream effect on derivatives settlement
- [ ] D. Market-wide circuit breakers in the US trigger from S&P 500 index moves, not single-stock moves
- [ ] E. Triple witching refers to the simultaneous expiry of stock options, index options, and index futures

### 13. Circuit breakers, US tiers and LULD
- [ ] A. Level 1 and Level 2 US market-wide halts are not triggered in the last 35 minutes of the session
- [ ] B. Level 3 triggers regardless of time of day and ends trading for the remainder of the session
- [ ] C. March 2020 saw four Level 1 halts, and Level 2 was never triggered during that period
- [ ] D. A LULD pause is triggered the instant price exits its band, with no monitoring window
- [ ] E. LULD Tier 2 (other NMS stocks) has a wider regular-hours band than Tier 1

### 14. Clearing hierarchy and DvP, revisited
- [ ] A. Herstatt risk refers to a bank collapsing between one leg of a settlement completing and the other failing
- [ ] B. A clearing member's guarantee fund contribution is described as the very first loss layer before a defaulting participant's own margin
- [ ] C. US equities currently settle on a T+2 basis
- [ ] D. A non-clearing member's trades are guaranteed to the CCP by a clearing broker
- [ ] E. DvP means securities and cash transfer conditionally, with neither released until both are available

<div style="page-break-after: always;"></div>

### 15. Trade busting, real incidents
- [ ] A. BATS withdrew its own IPO after a defect in its own matching engine crashed its stock's price
- [ ] B. Both the Facebook and BATS incidents involved a single erroneous order price rather than an engine-level defect
- [ ] C. Knight Capital's fills were, in the regulatory sense, mostly clearly erroneous trades
- [ ] D. NASDAQ paid a then-record SEC penalty related to the Facebook IPO malfunction
- [ ] E. The Facebook IPO delay in 2012 stemmed from a defect in NASDAQ's IPO cross process

### 16. Regulatory surveillance, patterns and evidence
- [ ] A. Front running is described as a serious breach of fiduciary duty as well as illegal
- [ ] B. Modern surveillance systems are described as never using machine learning for pattern detection
- [ ] C. Quote stuffing is intended to consume the matching engine's bandwidth to slow down competitors
- [ ] D. The audit trail is described as a key source of evidence in insider trading investigations
- [ ] E. Insider trading is handled under the same regulatory framework as order-flow manipulation, per the document

### 17. Knight Capital, systemic lessons
- [ ] A. A lack of automated post-deployment verification allowed a misconfigured server to run stale code
- [ ] B. Every one of Knight's orders violated an explicit NYSE trading rule
- [ ] C. Dangerous legacy code being merely deactivated rather than deleted is cited as a root cause
- [ ] D. Automated anomaly detection comparing per-server activity could have flagged the problem within seconds
- [ ] E. The exchange itself was found capable of determining whether Knight's overall strategy made business sense

### 18. Speed bumps and market structure
- [ ] A. A fixed delay preserves relative timing differences between orders rather than erasing them
- [ ] B. Asymmetric speed bumps can delay aggressive orders while letting cancellations through at full speed
- [ ] C. IEX's speed bump is implemented via a coiled fibre-optic cable rather than a software delay
- [ ] D. IEX is described as having captured a majority of total US equity trading volume since 2016
- [ ] E. Eurex introduced an asymmetric speed bump, Passive Liquidity Protection, for certain options and FX futures in 2019

<div style="page-break-after: always;"></div>

### 19. Technology transport and protocols, review
- [ ] A. Order submission generally uses UDP because reliability is not important for orders
- [ ] B. ITCH messages are parsed via fixed binary offsets rather than text scanning
- [ ] C. UDP multicast is preferred for market data partly because one packet reaches many subscribers at once
- [ ] D. FIX messages use the SOH control character as the field delimiter on the wire
- [ ] E. TCP unicast is used as a recovery channel to retransmit missed sequence numbers

### 20. Resilience, RPO/RTO, and order IDs
- [ ] A. A batch reporting system generally has a stricter RTO requirement than a matching engine
- [ ] B. UUIDs guarantee practical uniqueness without requiring coordination between sites
- [ ] C. Pre-allocated ID ranges per site can leave gaps in the ID sequence after a failover
- [ ] D. A matching engine's RPO target is effectively zero committed trades or acknowledgements lost
- [ ] E. Monotonic timestamp enforcement is described as unnecessary once sequencing infrastructure exists

### 21. Failover mechanics
- [ ] A. Active-passive failover with heartbeat monitoring risks a split-brain condition if both sites believe the other has failed
- [ ] B. Manual failover avoids false positives at the cost of slower response time
- [ ] C. Active-active designs are described as common because distributed consensus adds negligible latency
- [ ] D. Quorum requirements and fencing are both cited as mitigations for split-brain
- [ ] E. A near site plus a far site is described as a common compromise between fast failover and disaster protection

### 22. Market data architecture
- [ ] A. Periodic full snapshots let a subscriber resynchronise after missing incremental updates
- [ ] B. Sequencing scope, reset policy, and wrap behaviour are all cited as details that must be explicit in protocol documentation
- [ ] C. Incremental updates (deltas) describe only what changed since the previous message
- [ ] D. Depth-of-book subscriptions require less bandwidth than top-of-book subscriptions
- [ ] E. Conflation reduces message volume by merging updates at the cost of losing intermediate states

<div style="page-break-after: always;"></div>

### 23. Market data economics, a review
- [ ] A. Europe's consolidated tape debate under MiFID II is described as identical in structure to the long-established US SIP
- [ ] B. A proprietary direct feed is generated by the venue's own matching engine, bypassing SIP aggregation delay
- [ ] C. Market data and connectivity revenue is described as having grown to a substantial share of exchange profit
- [ ] D. Critics argue exchanges have a conflict of interest between improving the public SIP and selling premium proprietary feeds
- [ ] E. The SIP's content and pricing are governed collectively by the exchanges under SEC oversight

### 24. Latency and hardware acceleration
- [ ] A. FPGAs implement logic in dedicated circuits, enabling responses in tens of nanoseconds
- [ ] B. Microwave links can beat fibre over long routes because radio travels faster through air than light through glass
- [ ] C. Kernel bypass technologies like OpenOnload eliminate the standard Linux network stack's added latency
- [ ] D. Over long distances, the signal's propagation speed through its medium sets a hard floor on latency
- [ ] E. PTP is described as less precise than standard NTP for clock synchronisation

### 25. Observability and incident command
- [ ] A. A severity classification (e.g., SEV1-SEV3) is described as driving escalation and communication expectations during an incident
- [ ] B. A correlation ID lets an operator trace a single order's path across gateway, risk checks, matcher, and market-data publish
- [ ] C. The four golden signals and related production metrics are broken out by session state because acceptable baselines differ by phase
- [ ] D. An SLO paired with its target defines an error budget, the tolerated degradation over a period
- [ ] E. Metrics tell you *why* something went wrong, while logs tell you only *that* something is wrong

### 26. Determinism, replay, and reference data
- [ ] A. The 2015 NYSE outage is attributed to a gateway software version incompatibility
- [ ] B. Write-ahead logging records an input message before it is processed
- [ ] C. A deterministic matching engine must avoid hidden non-determinism such as mid-execution clock reads
- [ ] D. GTC orders are described as requiring persistence beyond the standard WAL mechanism
- [ ] E. A contract multiplier loaded at 500 instead of 50 would understate margin requirements by a factor of ten

<div style="page-break-after: always;"></div>

### 27. Crypto venues, a final review
- [ ] A. A constant-product AMM keeps the product of its two pooled reserves constant during a trade
- [ ] B. Centralised crypto exchanges commonly act as both matching venue and de facto custodian for user balances
- [ ] C. FTX's collapse is presented as illustrating the risk of collapsing matching, custody, and clearing into one entity
- [ ] D. Most crypto venues have historically lacked a defined opening or closing auction establishing a daily reference price
- [ ] E. Digital asset markets are overseen by a single unified regulator analogous to the SEC for US equities

### 28. Corporate actions and reference data interplay
- [ ] A. Reference data errors are described as a rare cause of real exchange outages compared to matching-engine bugs
- [ ] B. A stock split can move a stock into a different tick-size band and changes the prices and quantities of resting orders
- [ ] C. Symbol changes from rebranding or mergers require systems tracking positions by symbol to handle remapping
- [ ] D. A reverse split changes the number of shares per position without changing per-share price
- [ ] E. Reference data changes from corporate actions should propagate to all dependent systems atomically

### 29. Options mechanics, pin risk revisited
- [ ] A. A writer of a call struck at $150 who is assigned when the stock closes at $150.03 must deliver at $150 regardless of Monday's opening price
- [ ] B. Physical delivery for one US equity option contract typically involves 100 shares
- [ ] C. A position that closes just out-of-the-money can never end up exercised, regardless of the official settlement print
- [ ] D. Pin risk is sharpest around triple witching, when many related instruments resolve exercise/assignment simultaneously
- [ ] E. Assignment is the writer's exercise decision, while exercise is the holder's obligation

<div style="page-break-after: always;"></div>

### 30. Cross-cutting numeric and factual review
- [ ] A. A 10,000-share position with a VWAP entry of $153.33 and a current price of $160 has an unrealised P&L of roughly $66,700
- [ ] B. The equilibrium price in a call auction is the price that maximises min(cumulative bids, cumulative asks)
- [ ] C. A 2010 Flash Crash busting threshold of 60% deviation from a pre-crash reference price is cited in the document
- [ ] D. RPO for a matching engine is described as tolerating up to a few seconds of committed trade loss
- [ ] E. A midpoint peg fill between a $99.98 bid and $100.02 ask occurs at exactly $100.00

&nbsp;

---

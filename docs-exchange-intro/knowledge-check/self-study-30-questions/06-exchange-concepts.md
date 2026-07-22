# Exchange Concepts Knowledge Check — Variant 06

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

### 1. Instruments and the exchange's promises
- [ ] A. Price discovery, liquidity, and fairness/transparency are described as the exchange's three implicit promises
- [ ] B. A futures contract is an agreement to transact at a specified future date and price
- [ ] C. FX pairs trade primarily on centralised exchanges rather than electronic networks
- [ ] D. Each symbol on an equity exchange has its own independent order book
- [ ] E. An option grants an obligation, not a right, to buy or sell an underlying

### 2. Market participants, roles
- [ ] A. A market maker's core function is continuously quoting both a bid and an ask
- [ ] B. Citadel Securities and Virtu Financial are cited as examples of HFT/prop trading firms
- [ ] C. A prime broker's clients are typically retail investors rather than hedge funds
- [ ] D. Exchanges are described as sometimes being publicly listed companies themselves
- [ ] E. Demutualisation converted many for-profit public exchanges into member-owned mutuals

### 3. Short selling, borrow economics
- [ ] A. A 50% annualised borrow rate held for one week costs roughly 1% just in borrowing fees
- [ ] B. A lender consents to having their shares lent out, usually via their account agreement
- [ ] C. A short seller who cannot deliver at settlement can trigger the failed settlement process
- [ ] D. Naked short selling refers to shorting with a valid, confirmed locate
- [ ] E. A recall can force a short seller to buy in the open market at an inopportune moment

### 4. Order book depth, a fresh imbalance scenario
- [ ] A. If bid depth is 8,000 and ask depth is 2,000 within a symmetric window, the imbalance ratio is 0.8
- [ ] B. An imbalance ratio of 0.8 in that scenario is often interpreted as short-term upward price pressure
- [ ] C. An imbalance ratio near 0.0 suggests heavier buying interest than selling interest
- [ ] D. Volume-at-touch refers specifically to Level 1 quantities
- [ ] E. Iceberg reserves can make total book depth understate real available liquidity

### 5. Price-time priority and pro-rata, a fresh scenario
- [ ] A. Under pro-rata, if Order A (300 lots) and Order B (200 lots) split an incoming 100-lot fill, Order A receives 60 lots
- [ ] B. Under strict FIFO, whichever of Order A or B arrived first receives the fill first, up to the available quantity
- [ ] C. Pro-rata is described as rewarding order size over arrival speed
- [ ] D. CME uses FIFO for its SOFR futures and pro-rata for its equity index futures
- [ ] E. Nanosecond timestamps combined with sequencing infrastructure together ensure fair, reproducible ordering

<div style="page-break-after: always;"></div>

### 6. Tick size and midpoint rounding, a fresh scenario
- [ ] A. Given a best bid of $99.98 (tick 9998) and best ask of $100.01 (tick 10001), the raw midpoint tick count is 9999.5
- [ ] B. That midpoint corresponds to a valid, tick-aligned price under a one-cent tick regime
- [ ] C. A consistent, documented rounding rule prevents reconciliation breaks between systems computing the same midpoint fill
- [ ] D. Round-half-to-even is described as one convention that avoids systematically favouring either side
- [ ] E. Rule 612 permits rounding to a sub-penny price if both counterparties agree

### 7. The matching engine's core loop
- [ ] A. The engine checks whether an incoming order can match against resting orders before deciding to rest it in the book
- [ ] B. Cancel and modify messages follow a different processing path than new orders in the flowchart
- [ ] C. Checking dormant stop orders is part of the described core loop
- [ ] D. All events are eventually published to the PUB socket
- [ ] E. The matching engine's core loop is described as requiring multiple threads to keep up with order volume

### 8. Market maker obligations, a fresh adverse-selection scenario
- [ ] A. If a market maker buys 800 shares at $75.00 and the price falls to $74.70, the mark-to-market loss is $240
- [ ] B. If that market maker's spread was $0.04 wide, the half-spread revenue on an 800-share fill is $16
- [ ] C. A single adverse-selection loss can exceed the spread revenue from several prior fills
- [ ] D. A maximum-distance-from-mid obligation prevents a market maker from quoting a wildly asymmetric bid and ask
- [ ] E. A re-quoting obligation requires no maximum delay before a fresh quote must appear

### 9. Auctions, a fresh tie-break scenario
- [ ] A. If both $60 and $61 produce an identical executable volume, the algorithm first tries to minimise the resulting imbalance
- [ ] B. If imbalances are still tied, the algorithm prefers the price in the direction of remaining pressure
- [ ] C. If everything else is tied, proximity to a reference price such as the previous close can be the deciding factor
- [ ] D. The indicative uncross price is recalculated after every new order arrives during accumulation
- [ ] E. NYSE's closing auction imbalance publication window begins at 4:00pm, the same moment as the uncross

<div style="page-break-after: always;"></div>

### 10. Trading sessions and state machine
- [ ] A. PRE_OPEN accepts orders but performs no matching
- [ ] B. OPENING_AUCTION transitions to CONTINUOUS once the equilibrium price is found and the uncross executes
- [ ] C. HALTED can transition directly to CLOSING_AUCTION if an end-of-day signal arrives during a halt
- [ ] D. CLOSED can transition back into CONTINUOUS later the same day if volume returns
- [ ] E. The session scheduler issues state-change commands to the matching engine at scheduled times

### 11. Index weighting, a comparative scenario
- [ ] A. In a price-weighted index, a $50 stock and a $500 stock contribute in proportion to their respective share prices
- [ ] B. A market-cap-weighted index gives more influence to a company with a larger total share value
- [ ] C. Free-float adjustment would reduce the effective weight of a company that is 70% government-owned
- [ ] D. Equal-weighted indexes require no rebalancing as prices drift apart over time
- [ ] E. The S&P 500's divisor evolves continuously as constituents split, pay dividends, or are replaced

### 12. Pre-trade risk checks, ordering and cost
- [ ] A. Format and syntax checks require zero external state lookups
- [ ] B. A rate-limiting check uses an in-memory counter rather than querying the clearing system
- [ ] C. Position and credit limit checks are described as the most expensive checks in the sequence
- [ ] D. SMP pre-checks are described as occurring earlier in the sequence than format validation
- [ ] E. The fail-fast ordering exists to minimise latency for both accepted and rejected orders

### 13. Circuit breakers and Japan's approach
- [ ] A. Japan's daily price limit approach keeps the market open while capping how far price can move
- [ ] B. If Japan's price hits the daily limit, trading halts completely rather than continuing at that price
- [ ] C. If the next day opens near Japan's limit, the limit is described as being widened
- [ ] D. The US LULD system varies trigger bands by instrument tier rather than by halt duration
- [ ] E. Eurex's volatility interruption approach is auction-based rather than a fixed timed pause

<div style="page-break-after: always;"></div>

### 14. Price collars and SMP, a fresh policy scenario
- [ ] A. A dynamic collar rejects orders that stray too far from the most recent traded price
- [ ] B. A static collar is recalculated at the start of each new session using the prior close
- [ ] C. Cancel Resting is described as useful when a market maker's new quote should supersede an old one
- [ ] D. Cancel Both eliminates both sides cleanly, useful when repositioning
- [ ] E. SMP is optional under most exchange regulations and can be safely left disabled in production

### 15. Clearing and settlement, GameStop
- [ ] A. Initial margin is a demand for additional collateral triggered when losses breach the maintenance threshold
- [ ] B. Variation margin is settled daily to reflect mark-to-market gains and losses
- [ ] C. The NSCC recalculated initial margin requirements as GameStop's volatility and position sizes spiked
- [ ] D. Robinhood restricted customers to selling only, not buying, GameStop during the January 2021 episode
- [ ] E. The GameStop episode is linked in the document to both PFOF economics and short-selling borrow mechanics

### 16. Trade busting, thresholds and process
- [ ] A. A trade's reference price is typically the last consolidated print before the questionable execution
- [ ] B. Clearly erroneous review can bust some fills from a single sweep while leaving others standing
- [ ] C. A participant typically has a short window, commonly around 30 minutes, to file a clearly erroneous request
- [ ] D. Multi-venue erroneous-price events require independent, uncoordinated rulings per exchange
- [ ] E. Price adjustment is one of two remedies alongside outright cancellation (busting)

### 17. Surveillance, layering, and CAT
- [ ] A. Layering places multiple large orders at various price levels to create a false impression of depth
- [ ] B. The Consolidated Audit Trail correlates order and trade events across every registered exchange and FINRA venue
- [ ] C. Before CAT, regulators could instantly correlate records across exchanges without any manual process
- [ ] D. A Suspicious Transaction Report can be filed with the SEC or CFTC depending on jurisdiction
- [ ] E. Navinder Singh Sarao's spoofing activity is linked by the document to conditions present during the 2010 Flash Crash

<div style="page-break-after: always;"></div>

### 18. Technology architecture, the gateway
- [ ] A. The gateway typically handles authentication, session management, and message translation
- [ ] B. Instrument-specific validation such as tick alignment is sometimes enforced in the matching engine or a dedicated risk layer rather than the gateway
- [ ] C. The gateway and matching engine are described as sharing a single codebase and deployment cadence
- [ ] D. FIX tag 54 represents the order side (1=Buy, 2=Sell) in the document's example message
- [ ] E. FIX tag 59 represents Time-In-Force in the document's example message

### 19. Onboarding and conformance testing
- [ ] A. Conformance testing occurs after membership and legal agreements are signed, per the described sequence
- [ ] B. A conformance test script only checks whether a connection can be established, nothing more
- [ ] C. Certification environments that run stale reference data are described as effectively certifying nothing
- [ ] D. Test symbols are typically dedicated, unrealistic-looking tickers rather than copies of real production symbols
- [ ] E. Offboarding requires no formal reconciliation of final positions with the participant's clearing broker

### 20. Smart order routing and dark pools
- [ ] A. The NBBO is computed as the highest bid and lowest ask across all exchanges
- [ ] B. A crossed market means one venue's bid actually exceeds another venue's ask
- [ ] C. Dark pools typically match orders at the midpoint of the NBBO
- [ ] D. A Smart Order Router considers venue fees, depth, and price impact simultaneously
- [ ] E. Regulation NMS explicitly encourages persistent, deliberate locked or crossed quoting as an efficient market feature

### 21. PFOF and fee models
- [ ] A. Wholesale market makers pay retail brokers for the right to internalise client order flow
- [ ] B. PFOF is currently permitted without restriction in the United Kingdom
- [ ] C. Under maker-taker, a resting order that provides liquidity typically earns a rebate
- [ ] D. Under an inverted (taker-maker) model, the aggressor is charged a fee while the resting order earns a rebate
- [ ] E. Best execution requires considering price, speed, and likelihood of execution, not price alone

<div style="page-break-after: always;"></div>

### 22. Execution algorithms
- [ ] A. A VWAP algorithm estimates the expected volume profile and participates proportionally throughout the day
- [ ] B. TWAP divides an order into equal slices across equal time intervals
- [ ] C. An Implementation Shortfall algorithm trades more slowly as the price moves away from the arrival price
- [ ] D. A Percentage of Volume algorithm adapts its participation to prevailing market volume
- [ ] E. Execution algorithms are described as responsible for the vast majority of real order flow

### 23. Cryptocurrency venues, a deeper look
- [ ] A. A centralised crypto exchange's internal trade matching is generally decoupled from actual blockchain settlement timing
- [ ] B. An automated market maker prices trades using a formula such as reserve_A × reserve_B = k
- [ ] C. Ethereum-based tokens commonly use eighteen decimal places of precision
- [ ] D. FTX is described as having maintained a fully independent CCP standing between its customers and its affiliated trading firm
- [ ] E. Bitcoin's smallest denomination, the satoshi, is one hundred-millionth of a unit

### 24. Corporate actions, mechanics
- [ ] A. A 4-for-1 split multiplies existing open limit order quantities by four and divides prices by four
- [ ] B. Ex-dividend price drops are typically absorbed via a divisor adjustment in index calculation
- [ ] C. A merger's target company shares are eventually delisted after conversion to cash or acquirer stock
- [ ] D. Corporate action changes are described as ideally propagating gradually over several minutes for safety
- [ ] E. A reverse split is used partly as a listing-compliance remedy for a depressed share price

### 25. Options mechanics, exercise and assignment
- [ ] A. American-style options can be exercised at any time up to expiry
- [ ] B. European-style options, including most cash-settled index options, can only be exercised at expiry
- [ ] C. The OCC automatically exercises an option that is in-the-money by as little as one cent absent contrary instruction
- [ ] D. Assignment allocation among a broker's clients is commonly done via random allocation or FIFO
- [ ] E. Cash settlement is standard for individual equity options rather than broad index options

<div style="page-break-after: always;"></div>

### 26. Reference data and its risks
- [ ] A. Reference data includes identity fields such as ISIN, CUSIP, or SEDOL
- [ ] B. Reference data is cached aggressively at startup for latency reasons
- [ ] C. A stale cached reference-data value affects every order processed during the stale period
- [ ] D. Reference data changes from corporate actions are described as ideally applied gradually rather than atomically
- [ ] E. Circuit breaker thresholds and position limits are both classified as risk parameters within reference data

### 27. Latency arbitrage and hardware
- [ ] A. Latency arbitrage exploits the propagation delay of price changes between venues
- [ ] B. A market maker with 10-microsecond-stale quotes is described as vulnerable to adverse selection
- [ ] C. SmartNICs with kernel-bypass stacks can reduce round-trip latency to roughly 1-5 microseconds
- [ ] D. Hardware timestamping records arrival time only after application software has processed the packet
- [ ] E. Deterministic (bounded worst-case) latency is described as mattering as much as average latency in HFT systems

### 28. Observability signals
- [ ] A. Sequence-gap and retransmission rates are cited as production signals to monitor on market-data channels
- [ ] B. Order-to-trade and cancel-to-fill ratios per participant are cited as monitored business signals
- [ ] C. Clock offset and drift rate relative to a reference source are described as first-class signals unique to exchange infrastructure
- [ ] D. Acceptable latency baselines are described as constant regardless of whether the venue is in an auction or continuous trading
- [ ] E. Traces use a correlation ID, typically the order ID, to follow a request across components

<div style="page-break-after: always;"></div>

### 29. Determinism and persistence, a fresh scenario
- [ ] A. A snapshot taken every 5 minutes bounds WAL replay to at most 5 minutes of entries on recovery
- [ ] B. A cold start typically completes faster than a warm restart
- [ ] C. Using a hash map with randomised iteration order in the matching path is described as a potential source of non-determinism
- [ ] D. In failover, a secondary that has been processing inputs in shadow mode already holds an up-to-date book state
- [ ] E. Determinism is described as valuable for auditing, debugging, and disaster recovery alike

### 30. Cross-cutting numeric review
- [ ] A. Given asks 2,000@$150.35, 1,500@$150.40, 1,500@$150.45, the market impact of a 5,000-share sweep is $0.045/share
- [ ] B. A pro-rata split of 60 lots between orders of 100 and 40 lots gives the smaller order roughly 17 lots
- [ ] C. An equilibrium auction price is chosen to minimise, not maximise, the executable volume
- [ ] D. A 45-minute delay in exercising a kill switch is cited as a key failure in the Knight Capital incident
- [ ] E. The NYSE closing auction is described as capable of accounting for 10-15% of a stock's entire daily volume

&nbsp;

---

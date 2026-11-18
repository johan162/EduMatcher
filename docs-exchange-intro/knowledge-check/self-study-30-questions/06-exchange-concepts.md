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
- [ ] A. A futures contract is an agreement to transact at a specified future date and price
- [ ] B. FX pairs trade primarily on centralised exchanges rather than electronic networks
- [ ] C. An option grants an obligation, not a right, to buy or sell an underlying
- [ ] D. Each symbol on an equity exchange has its own independent order book
- [ ] E. Price discovery, liquidity, and fairness/transparency are described as the exchange's three implicit promises

### 2. Market participants, roles
- [ ] A. A prime broker's clients are typically retail investors rather than hedge funds
- [ ] B. Demutualisation converted many for-profit public exchanges into member-owned mutuals
- [ ] C. Citadel Securities and Virtu Financial are cited as examples of HFT/prop trading firms
- [ ] D. Exchanges are described as sometimes being publicly listed companies themselves
- [ ] E. A market maker's core function is continuously quoting both a bid and an ask

### 3. Short selling, borrow economics
- [ ] A. A recall can force a short seller to buy in the open market at an inopportune moment
- [ ] B. Naked short selling refers to shorting with a valid, confirmed locate
- [ ] C. A 50% annualised borrow rate held for one week costs roughly 1% just in borrowing fees
- [ ] D. A lender consents to having their shares lent out, usually via their account agreement
- [ ] E. A short seller who cannot deliver at settlement can trigger the failed settlement process

### 4. Order book depth, a fresh imbalance scenario
*Scenario: within a symmetric window around the mid, bid depth is 8,000 and ask depth is 2,000.*

- [ ] A. An imbalance ratio near 0.0 suggests heavier buying interest than selling interest
- [ ] B. Iceberg reserves can make total book depth understate real available liquidity
- [ ] C. Volume-at-touch refers specifically to Level 1 quantities
- [ ] D. The imbalance ratio is 0.8
- [ ] E. An imbalance ratio of 0.8 is often interpreted as short-term upward price pressure

### 5. Price-time priority and pro-rata, a fresh scenario
- [ ] A. Under pro-rata, if Order A (300 lots) and Order B (200 lots) split an incoming 100-lot fill, Order A receives 60 lots
- [ ] B. Under strict FIFO, whichever of Order A or B arrived first receives the fill first, up to the available quantity
- [ ] C. CME uses FIFO for its SOFR futures and pro-rata for its equity index futures
- [ ] D. Pro-rata is described as rewarding order size over arrival speed
- [ ] E. Nanosecond timestamps combined with sequencing infrastructure together ensure fair, reproducible ordering

<div style="page-break-after: always;"></div>

### 6. Tick size and midpoint rounding, a fresh scenario
*Scenario: the best bid is $99.98 (tick 9998) and the best ask is $100.01 (tick 10001).*

- [ ] A. The raw midpoint corresponds to a valid, tick-aligned price under a one-cent tick regime
- [ ] B. The raw midpoint tick count is 9999.5
- [ ] C. Round-half-to-even is described as one convention that avoids systematically favouring either side
- [ ] D. A consistent, documented rounding rule prevents reconciliation breaks between systems computing the same midpoint fill
- [ ] E. Rule 612 permits rounding to a sub-penny price if both counterparties agree

### 7. The matching engine's core loop
- [ ] A. Cancel and modify messages follow a different processing path than new orders in the flowchart
- [ ] B. Checking dormant stop orders is part of the described core loop
- [ ] C. The matching engine's core loop is described as requiring multiple threads to keep up with order volume
- [ ] D. All events are eventually published to the PUB socket
- [ ] E. The engine checks whether an incoming order can match against resting orders before deciding to rest it in the book

### 8. Market maker obligations, a fresh adverse-selection scenario
- [ ] A. A re-quoting obligation requires no maximum delay before a fresh quote must appear
- [ ] B. If a market maker buys 800 shares at $75.00 and the price falls to $74.70, the mark-to-market loss is $240
- [ ] C. If that market maker's spread was $0.04 wide, the half-spread revenue on an 800-share fill is $16
- [ ] D. A single adverse-selection loss can exceed the spread revenue from several prior fills
- [ ] E. A maximum-distance-from-mid obligation prevents a market maker from quoting a wildly asymmetric bid and ask

### 9. Auctions, a fresh tie-break scenario
- [ ] A. If imbalances are still tied, the algorithm prefers the price in the direction of remaining pressure
- [ ] B. NYSE's closing auction imbalance publication window begins at 4:00pm, the same moment as the uncross
- [ ] C. If both $60 and $61 produce an identical executable volume, the algorithm first tries to minimise the resulting imbalance
- [ ] D. The indicative uncross price is recalculated after every new order arrives during accumulation
- [ ] E. If everything else is tied, proximity to a reference price such as the previous close can be the deciding factor

<div style="page-break-after: always;"></div>

### 10. Trading sessions and state machine
- [ ] A. HALTED can transition directly to CLOSING_AUCTION if an end-of-day signal arrives during a halt
- [ ] B. CLOSED can transition back into CONTINUOUS later the same day if volume returns
- [ ] C. PRE_OPEN accepts orders but performs no matching
- [ ] D. OPENING_AUCTION transitions to CONTINUOUS once the equilibrium price is found and the uncross executes
- [ ] E. The session scheduler issues state-change commands to the matching engine at scheduled times

### 11. Index weighting, a comparative scenario
- [ ] A. In a price-weighted index, a $50 stock and a $500 stock contribute in proportion to their respective share prices
- [ ] B. Free-float adjustment would reduce the effective weight of a company that is 70% government-owned
- [ ] C. The S&P 500's divisor changes when constituents are added or removed, or when share counts change through issuance or buybacks
- [ ] D. A market-cap-weighted index gives more influence to a company with a larger total share value
- [ ] E. Equal-weighted indexes require no rebalancing as prices drift apart over time

### 12. Pre-trade risk checks, ordering and cost
- [ ] A. SMP pre-checks are described as occurring earlier in the sequence than format validation
- [ ] B. Position and credit limit checks are described as the most expensive checks in the sequence
- [ ] C. Format and syntax checks require zero external state lookups
- [ ] D. The fail-fast ordering exists to minimise latency for both accepted and rejected orders
- [ ] E. A rate-limiting check uses an in-memory counter rather than querying the clearing system

### 13. Circuit breakers and Japan's approach
- [ ] A. The US LULD system varies trigger bands by instrument tier rather than by halt duration
- [ ] B. Japan's daily price limit approach keeps the market open while capping how far price can move
- [ ] C. If a stock stays pinned at Japan's daily limit without trading for consecutive days, the limit is described as being widened
- [ ] D. If Japan's price hits the daily limit, trading halts completely rather than continuing at that price
- [ ] E. Eurex's volatility interruption approach is auction-based rather than a fixed timed pause

<div style="page-break-after: always;"></div>

### 14. Price collars and SMP, a fresh policy scenario
- [ ] A. A static collar is recalculated at the start of each new session using the prior close
- [ ] B. A dynamic collar rejects orders that stray too far from the most recent traded price
- [ ] C. SMP is optional under most exchange regulations and can be safely left disabled in production
- [ ] D. Cancel Resting is described as useful when a market maker's new quote should supersede an old one
- [ ] E. Cancel Both eliminates both sides cleanly, useful when repositioning

### 15. Clearing and settlement, GameStop
- [ ] A. Initial margin is a demand for additional collateral triggered when losses breach the maintenance threshold
- [ ] B. Variation margin is settled daily to reflect mark-to-market gains and losses
- [ ] C. The NSCC recalculated initial margin requirements as GameStop's volatility and position sizes spiked
- [ ] D. The GameStop episode is linked in the document to both PFOF economics and short-selling borrow mechanics
- [ ] E. Robinhood restricted customers to selling only, not buying, GameStop during the January 2021 episode

### 16. Trade busting, thresholds and process
- [ ] A. Multi-venue erroneous-price events require independent, uncoordinated rulings per exchange
- [ ] B. Clearly erroneous review can bust some fills from a single sweep while leaving others standing
- [ ] C. A participant typically has a short window, commonly around 30 minutes, to file a clearly erroneous request
- [ ] D. Price adjustment is one of two remedies alongside outright cancellation (busting)
- [ ] E. A trade's reference price is typically the last consolidated print before the questionable execution

### 17. Surveillance, layering, and CAT
- [ ] A. Layering places multiple large orders at various price levels to create a false impression of depth
- [ ] B. Navinder Singh Sarao's spoofing activity is linked by the document to conditions present during the 2010 Flash Crash
- [ ] C. In the EU and UK, trading venues must file Suspicious Transaction and Order Reports (STORs) with the regulator
- [ ] D. Before CAT, regulators could instantly correlate records across exchanges without any manual process
- [ ] E. The Consolidated Audit Trail correlates order and trade events across every registered exchange and FINRA venue

<div style="page-break-after: always;"></div>

### 18. Technology architecture, the gateway
- [ ] A. Instrument-specific validation such as tick alignment is sometimes enforced in the matching engine or a dedicated risk layer rather than the gateway
- [ ] B. The gateway and matching engine are described as sharing a single codebase and deployment cadence
- [ ] C. The gateway typically handles authentication, session management, and message translation
- [ ] D. FIX's text tag=value encoding is slower to parse than binary order-entry protocols such as OUCH
- [ ] E. The gateway translates participant protocols such as FIX into the matching engine's internal message format

### 19. Onboarding and conformance testing
- [ ] A. Test symbols are typically dedicated, unrealistic-looking tickers rather than copies of real production symbols
- [ ] B. Certification environments that run stale reference data are described as effectively certifying nothing
- [ ] C. Conformance testing occurs after membership and legal agreements are signed, per the described sequence
- [ ] D. A conformance test script only checks whether a connection can be established, nothing more
- [ ] E. Offboarding requires no formal reconciliation of final positions with the participant's clearing broker

### 20. Smart order routing and dark pools
- [ ] A. The NBBO is computed as the highest bid and lowest ask across all exchanges
- [ ] B. Dark pools typically match orders at the midpoint of the NBBO
- [ ] C. A Smart Order Router considers venue fees, depth, and price impact simultaneously
- [ ] D. A crossed market means one venue's bid actually exceeds another venue's ask
- [ ] E. Regulation NMS explicitly encourages persistent, deliberate locked or crossed quoting as an efficient market feature

### 21. PFOF and fee models
- [ ] A. Under an inverted (taker-maker) model, the aggressor is charged a fee while the resting order earns a rebate
- [ ] B. Wholesale market makers pay retail brokers for the right to internalise client order flow
- [ ] C. PFOF is currently permitted without restriction in the United Kingdom
- [ ] D. Best execution requires considering price, speed, and likelihood of execution, not price alone
- [ ] E. Under maker-taker, a resting order that provides liquidity typically earns a rebate

<div style="page-break-after: always;"></div>

### 22. Execution algorithms
- [ ] A. Execution algorithms are described as responsible for the vast majority of real order flow
- [ ] B. An Implementation Shortfall algorithm trades more slowly as the price moves away from the arrival price
- [ ] C. TWAP divides an order into equal slices across equal time intervals
- [ ] D. A VWAP algorithm estimates the expected volume profile and participates proportionally throughout the day
- [ ] E. A Percentage of Volume algorithm adapts its participation to prevailing market volume

### 23. Cryptocurrency venues, a deeper look
- [ ] A. A centralised crypto exchange's internal trade matching is generally decoupled from actual blockchain settlement timing
- [ ] B. An automated market maker prices trades using a formula such as reserve_A × reserve_B = k
- [ ] C. FTX is described as having maintained a fully independent CCP standing between its customers and its affiliated trading firm
- [ ] D. Ethereum-based tokens commonly use eighteen decimal places of precision
- [ ] E. Bitcoin's smallest denomination, the satoshi, is one hundred-millionth of a unit

### 24. Corporate actions, mechanics
- [ ] A. A merger's target company shares are eventually delisted after conversion to cash or acquirer stock
- [ ] B. A 4-for-1 split multiplies existing open limit order quantities by four and divides prices by four
- [ ] C. Corporate action changes are described as ideally propagating gradually over several minutes for safety
- [ ] D. Ex-dividend price drops are typically absorbed via a divisor adjustment in index calculation
- [ ] E. A reverse split is used partly as a listing-compliance remedy for a depressed share price

### 25. Options mechanics, exercise and assignment
- [ ] A. Assignment allocation among a broker's clients is commonly done via random allocation or FIFO
- [ ] B. American-style options can be exercised at any time up to expiry
- [ ] C. The OCC automatically exercises an option that is in-the-money by as little as one cent absent contrary instruction
- [ ] D. Cash settlement is standard for individual equity options rather than broad index options
- [ ] E. European-style options, including most cash-settled index options, can only be exercised at expiry

<div style="page-break-after: always;"></div>

### 26. Reference data and its risks
- [ ] A. A stale cached reference-data value affects every order processed during the stale period
- [ ] B. Reference data is cached aggressively at startup for latency reasons
- [ ] C. Reference data changes from corporate actions are described as ideally applied gradually rather than atomically
- [ ] D. Circuit breaker thresholds and position limits are both classified as risk parameters within reference data
- [ ] E. Reference data includes identity fields such as ISIN, CUSIP, or SEDOL

### 27. Latency arbitrage and hardware
- [ ] A. Latency arbitrage exploits the propagation delay of price changes between venues
- [ ] B. A market maker with 10-microsecond-stale quotes is described as vulnerable to adverse selection
- [ ] C. SmartNICs with kernel-bypass stacks can reduce round-trip latency to roughly 1-5 microseconds
- [ ] D. Deterministic (bounded worst-case) latency is described as mattering as much as average latency in HFT systems
- [ ] E. Hardware timestamping records arrival time only after application software has processed the packet

### 28. Observability signals
- [ ] A. Sequence-gap and retransmission rates are cited as production signals to monitor on market-data channels
- [ ] B. Traces use a correlation ID, typically the order ID, to follow a request across components
- [ ] C. Clock offset and drift rate relative to a reference source are described as first-class signals unique to exchange infrastructure
- [ ] D. Acceptable latency baselines are described as constant regardless of whether the venue is in an auction or continuous trading
- [ ] E. Order-to-trade and cancel-to-fill ratios per participant are cited as monitored business signals

<div style="page-break-after: always;"></div>

### 29. Determinism and persistence, a fresh scenario
- [ ] A. In failover, a secondary that has been processing inputs in shadow mode already holds an up-to-date book state
- [ ] B. A cold start typically completes faster than a warm restart
- [ ] C. A snapshot taken every 5 minutes bounds WAL replay to at most 5 minutes of entries on recovery
- [ ] D. Using a hash map with randomised iteration order in the matching path is described as a potential source of non-determinism
- [ ] E. Determinism is described as valuable for auditing, debugging, and disaster recovery alike

### 30. Cross-cutting numeric review
- [ ] A. Closing auctions concentrate a large share of daily volume because index funds need to trade at the official closing price
- [ ] B. A pro-rata split of 60 lots between orders of 100 and 40 lots gives the smaller order roughly 17 lots
- [ ] C. Knight's inability to stop its runaway system for about 45 minutes is cited as a key failure in the incident
- [ ] D. Given asks 2,000@$150.35, 1,500@$150.40, 1,500@$150.45, the market impact of a 5,000-share sweep is $0.045/share
- [ ] E. An equilibrium auction price is chosen to minimise, not maximise, the executable volume

&nbsp;

---

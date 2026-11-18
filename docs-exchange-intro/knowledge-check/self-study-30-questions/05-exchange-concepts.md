# Exchange Concepts Knowledge Check — Variant 05

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

### 1. Debt, equity, and dilution
- [ ] A. Venture capital investors typically receive common stock rather than preferred stock
- [ ] B. Bonds cannot be resold before their maturity date
- [ ] C. A company that borrows via a bond has an unconditional obligation to pay unless it defaults
- [ ] D. Capital appreciation and dividends are both described as ways equity holders can benefit
- [ ] E. A 20% stake sold for $250,000 that raises a $1,000,000 company to a post-money value of $1,250,000 leaves the founder owning 80% of $1,250,000

### 2. Recovery objectives, RPO and RTO
- [ ] A. The 2015 NYSE halt lasting roughly 3.5 hours is cited as an example of an unacceptable RTO
- [ ] B. RPO measures the maximum acceptable amount of data loss
- [ ] C. RTO measures the maximum acceptable downtime
- [ ] D. A batch reporting system and a matching engine are described as having identical RTO requirements
- [ ] E. For a matching engine, RPO is effectively zero

### 3. Primary and secondary sites
- [ ] A. Placing the secondary very close to the primary protects best against a localised disaster like an earthquake
- [ ] B. Consensus protocols like Raft or Paxos guarantee zero data loss on failover at essentially no latency cost
- [ ] C. State replication and log-based replication (WAL) are both described as synchronisation approaches
- [ ] D. Active-active matching engines are described as common in production exchanges today
- [ ] E. A secondary site is a geographically separate, identical backup system

### 4. Failover and split-brain
- [ ] A. Quorum requirements demand agreement from a majority of nodes before a promotion to primary
- [ ] B. Fencing (STONITH) is one technique used to prevent split-brain
- [ ] C. Active-passive replication is described as the more common choice than active-active in production
- [ ] D. Split-brain occurs when both the primary and secondary simultaneously believe they should be active
- [ ] E. Manual failover is typically faster than automatic, heartbeat-triggered failover

### 5. Unique order identifiers
- [ ] A. A hybrid approach combining UUIDs with monotonically increasing timestamps is described as a practical compromise
- [ ] B. A single central counter is simple but creates a single point of failure and a bottleneck
- [ ] C. UUIDs are described as naturally sortable by arrival order
- [ ] D. Site-prefixed IDs make "which came first" comparisons trivial without stripping the prefix
- [ ] E. Pre-allocated ID ranges per site avoid collisions without requiring coordination at submission time

### 6. Exchange ownership and business models
- [ ] A. Market data revenue is negligible for modern exchanges
- [ ] B. Demutualisation turned many member-owned exchanges into for-profit companies, some listed on their own markets
- [ ] C. A for-profit exchange earns revenue from trading fees, market data, connectivity, and listings
- [ ] D. A demutualised exchange no longer needs to run market surveillance because members no longer own it
- [ ] E. Groups such as ICE, CME Group, and Deutsche Börse each operate several venues under one parent

### 7. Listing thresholds and alternatives
- [ ] A. Slack's 2019 NYSE listing is cited as a pioneering direct listing example
- [ ] B. A de-SPAC transaction is described as resembling a symbol change and delisting event
- [ ] C. A minimum bid price of roughly $4.00 is cited as typical at initial listing
- [ ] D. A company failing the minimum bid price rule is immediately and permanently delisted with no cure period
- [ ] E. NASDAQ's Global Select, Global Market, and Capital Market tiers differ in stringency

### 8. Order types recap with a twist
- [ ] A. GTD orders require no automatic cancellation task from the exchange's scheduler
- [ ] B. An iceberg order's visible peak is replenished from a hidden reserve after being consumed
- [ ] C. A midpoint peg order is recalculated dynamically as (best_bid + best_ask) / 2 at match time
- [ ] D. A buy stop-limit order converts to a limit order once triggered
- [ ] E. FOK requires the engine to perform a dry-run sweep before committing any fills

### 9. Depth and market impact, a fresh scenario
*Scenario: the ask side holds 1,000 @ $200.00, 800 @ $200.05 and 1,200 @ $200.10, and a 2,000-share market buy sweeps it.*

- [ ] A. A deep book requires less sweeping through levels to fill a given order size
- [ ] B. Depth is best described as a single fixed number rather than a shape
- [ ] C. The sweep's VWAP is (1000×200.00 + 800×200.05 + 200×200.10)/2000
- [ ] D. The sweep fully consumes the first two levels and part of the third
- [ ] E. Market impact is defined as the difference between the sweep's VWAP and the initial best ask

### 10. Price-time priority, a fresh amendment scenario
- [ ] A. A resting sell order amended in quantity from 800 to 300 shares retains its original timestamp
- [ ] B. A cancel-and-replace of a market maker's quote always retains the original quote's priority
- [ ] C. Pro-rata allocation is common in some options and interest-rate futures markets
- [ ] D. Better price always beats an earlier arrival time at a worse price
- [ ] E. A resting sell order amended from $150.40 down to $150.35 receives a new timestamp

### 11. Tick size and Rule 612
- [ ] A. Rule 612 sets a one-cent price-increment floor for NMS stocks priced at $1.00 or more
- [ ] B. The E-mini S&P 500 futures tick is 0.25 index points
- [ ] C. Tick size is defined once globally and never varies by venue or price band
- [ ] D. Sub-penny quoting is permitted for stocks priced below $1.00
- [ ] E. US Treasury futures tick in fractions of 1/32nd of a point

### 12. The matching engine's design
- [ ] A. Each tradeable symbol maintains an entirely independent order book from every other symbol
- [ ] B. Single-threaded matching is chosen primarily for its simplicity of implementation, not for determinism
- [ ] C. A heap-like structure gives O(1) access to the best price and O(log n) insertion/deletion
- [ ] D. Production engines often use balanced trees, skip lists, or intrusive linked lists indexed by price
- [ ] E. Sweeping through multiple price levels can generate slippage relative to the initial best price

### 13. The opening auction, a fresh worked scenario
*Scenario: the opening auction holds buy orders 400 @ $62 and 900 @ $60, and sell orders 700 @ $60 and 500 @ $61.*

- [ ] A. A remaining unmatched order after the uncross is always cancelled rather than transitioning to the continuous book
- [ ] B. All buyers and sellers who can trade at the equilibrium price trade at that single common price
- [ ] C. The executable volume at $60 is 700
- [ ] D. Comparing $60 (700 executable) and $61 (400 executable), the equilibrium price is $60
- [ ] E. The executable volume at $61 is min(400, 700+500) = 400

### 14. Indexes and the divisor, a fresh scenario
- [ ] A. A stock buyback that shrinks share count without a price change requires no divisor adjustment
- [ ] B. Rescaling the divisor after a non-price-driven cap change keeps the index level continuous at that instant
- [ ] C. If aggregate market cap rises from $500 billion to $525 billion due to a new constituent being added, the divisor should be rescaled
- [ ] D. Only future price movements change the index level after such a rescaling
- [ ] E. If aggregate market cap rises from $500 billion to $525 billion due only to price appreciation, the divisor is left unchanged

### 15. Circuit breaker tiers, revisited
- [ ] A. A leveraged ETF's LULD band can be multiplied by its leverage factor
- [ ] B. Level 3 (20% decline) can trigger a halt even in the final minutes of the session
- [ ] C. LULD triggers immediately upon a price moving outside its band with no monitoring period
- [ ] D. LULD's Tier 1 band widens during the early and late parts of the session compared to regular hours
- [ ] E. Level 1 (7% S&P 500 decline) and Level 2 (13%) both trigger a 15-minute halt if before 3:25pm

### 16. Clearing, margin, and Lehman
- [ ] A. Lehman Brothers' OTC derivatives lacked daily variation margin settlement through a CCP
- [ ] B. Maintenance margin is the minimum balance that, if breached, triggers a margin call
- [ ] C. Novation replaces bilateral counterparty exposure with exposure to the CCP on both sides
- [ ] D. Dodd-Frank and EMIR both moved to require central clearing for most standardised OTC derivatives
- [ ] E. CME futures participants suffered material uncollateralised losses from Lehman's default

### 17. Regulatory surveillance recap
- [ ] A. Spoofing is now explicitly illegal in both the US and the EU
- [ ] B. Wash trading generates artificial trading volume without a genuine change of ownership
- [ ] C. Quote stuffing is intended to improve overall market efficiency by adding liquidity
- [ ] D. The Consolidated Audit Trail (CAT) has been operational in the US since 2020
- [ ] E. Front running involves acting on knowledge of another participant's pending order

### 18. Knight Capital, controls that would have helped
- [ ] A. The exchange's matching engine should have rejected Knight's orders as invalid
- [ ] B. A firm-wide notional or position limit could have halted the runaway system early
- [ ] C. Clearly erroneous rules would have busted most of Knight's trades because they were unintended
- [ ] D. A kill switch the firm could trigger at once would have capped the losses
- [ ] E. The Market Access Rule requires broker-dealers to have pre-trade risk controls aimed at this kind of failure

### 19. Speed bumps and IEX, revisited
- [ ] A. Asymmetric speed bumps can delay aggressive orders while letting cancellations through, protecting market makers' quotes from latency arbitrage
- [ ] B. IEX routes orders through 38 miles of coiled fibre before reaching the matching engine
- [ ] C. IEX's delay is described as approximately 350 microseconds
- [ ] D. IEX's founders argued that speed advantages primarily benefit long-term investors over HFT firms
- [ ] E. IEX has displaced NYSE and NASDAQ as the largest US equity venue by volume

### 20. Technology transport layer
- [ ] A. Market data commonly uses UDP multicast while order entry commonly uses TCP
- [ ] B. FIX is described as a text-based protocol using a control character (SOH) as its field delimiter on the wire
- [ ] C. ITCH is a binary UDP-based market data protocol
- [ ] D. CME's MDP3 is based on the SBE (Simple Binary Encoding) standard
- [ ] E. OUCH is the FIX counterpart used exclusively for cancel messages

### 21. Market data architecture
- [ ] A. A snapshot is a complete picture of current book state, while an incremental update describes only what changed
- [ ] B. Conflated data is described as fully suitable for analytical systems requiring complete tick-by-tick history
- [ ] C. Tick-to-trade latency is usually measured at the firm's own network card, from receiving a market data message to sending the resulting order
- [ ] D. Conflation merges consecutive updates for the same price level into a single message
- [ ] E. Top-of-book data is also known as Level 2 data

### 22. Market data economics
- [ ] A. The SIP consolidates trade and quote data from every registered US exchange into one public feed
- [ ] B. Market data and connectivity fees are described as a shrinking share of major exchange revenue
- [ ] C. The SEC's Market Data Infrastructure rulemaking aimed to expand SIP content, including round-lot depth-of-book
- [ ] D. Exchanges that govern SIP pricing are the same companies that sell competing proprietary feeds
- [ ] E. A proprietary direct feed typically offers more information and lower latency than the SIP

### 23. Latency and co-location
- [ ] A. PTP synchronises clocks to sub-microsecond accuracy, more precise than standard NTP
- [ ] B. FPGAs can generate an order response in tens of nanoseconds
- [ ] C. Kernel bypass technologies add latency by routing packets through additional software layers
- [ ] D. Co-location places a participant's servers inside the same data centre as the matching engine
- [ ] E. Microwave links can be faster than fibre-optic cable over long distances because radio travels faster through air than light through glass

### 24. Operational observability
- [ ] A. Acceptable latency baselines are described as identical across every session phase, including auctions and halts
- [ ] B. Symptom-based alerts are generally preferred over cause-based alerts to reduce alert fatigue
- [ ] C. An SLO of "99.9% of order ACKs within 200 microseconds" is an example of a Service-Level Objective
- [ ] D. Metrics, logs, and traces are described as three complementary observability data types
- [ ] E. A dead-man's-switch alert fires when expected signals stop arriving

### 25. Incident response and Reg SCI
- [ ] A. MTTD and MTTR stand for time-to-detect and time-to-recover
- [ ] B. An Incident Commander and a communications lead are described as the same role
- [ ] C. Runbooks are described as needing no rehearsal under realistic load conditions
- [ ] D. A blameless postmortem is intended to encourage disclosure rather than assign individual blame
- [ ] E. Regulation SCI requires covered market infrastructure to report significant systems issues to regulators

### 26. Determinism, replay, and persistence
- [ ] A. A write-ahead log (WAL) is written before an input message is processed
- [ ] B. A warm restart from a snapshot is generally faster than a cold start from the beginning of the day
- [ ] C. A deterministic matching engine produces identical outputs given the same initial state and input sequence
- [ ] D. GTC orders require persistence beyond the WAL to survive session boundaries
- [ ] E. Reading the system clock directly mid-execution is described as a safe source of determinism

### 27. Sequence numbers and duplicate detection
- [ ] A. Ordered reconstruction during disaster recovery depends on replaying messages in sequence-number order
- [ ] B. A sequence number identifies a message on a specific channel, distinct from an order's lifetime ID
- [ ] C. Gap detection relies on sequence numbers arriving out of the expected order
- [ ] D. Detecting a message with an already-processed sequence number and discarding it approximates exactly-once processing
- [ ] E. A single order generates only one message and therefore only one sequence number over its lifetime

### 28. Reference data risks
- [ ] A. A contract multiplier error loaded ten times too large would make margin requirements ten times too large
- [ ] B. An ISIN is described as independent of which specific exchange a security trades on
- [ ] C. The 8 July 2015 NYSE outage lasting roughly 3.5 hours stemmed from a gateway software version mismatch
- [ ] D. Reference data is generally queried fresh from a database for every incoming order
- [ ] E. A wrong tick size can cause valid orders to be rejected as tick-misaligned even though the matching engine's own logic is correct

### 29. Cryptocurrency and digital asset venues
- [ ] A. The FTX collapse is presented as an example of what happens when matching, custody, and clearing are not kept institutionally separate
- [ ] B. Most cryptocurrency venues operate a defined daily open/close session with a scheduled closing auction
- [ ] C. A decentralised exchange's automated market maker prices trades from a pool ratio rather than matching resting orders
- [ ] D. Digital asset markets are described as operating under a single unified global regulator
- [ ] E. Order books, price-time priority, and deterministic matching are described as concepts that carry over to crypto venues

### 30. Cross-cutting numeric review
- [ ] A. VWAP for 100 shares at $150 and 50 shares at $160 is $153.33
- [ ] B. An index launching at base value 1000 with $7,007,100,000,000 aggregate cap implies a divisor of about 7.0071 billion
- [ ] C. A midpoint peg fill between a $150.30 bid and $150.35 ask occurs at $150.325
- [ ] D. A 60% deviation from a pre-crash reference price was the threshold used to bust trades after the 2010 Flash Crash
- [ ] E. Variation margin on 10,000 shares that fell $5 in a day is a $50,000 debit

&nbsp;

---

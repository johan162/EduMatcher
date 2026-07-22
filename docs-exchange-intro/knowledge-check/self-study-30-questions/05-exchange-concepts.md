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
- [ ] A. A company that borrows via a bond has an unconditional obligation to pay unless it defaults
- [ ] B. Venture capital investors typically receive common stock rather than preferred stock
- [ ] C. Capital appreciation and dividends are both described as ways equity holders can benefit
- [ ] D. A 20% stake sold for $250,000 that raises a $1,000,000 company to a post-money value of $1,250,000 leaves the founder owning 80% of $1,250,000
- [ ] E. Bonds cannot be resold before their maturity date

### 2. Recovery objectives, RPO and RTO
- [ ] A. RPO measures the maximum acceptable amount of data loss
- [ ] B. For a matching engine, RPO is effectively zero
- [ ] C. RTO measures the maximum acceptable downtime
- [ ] D. A batch reporting system and a matching engine are described as having identical RTO requirements
- [ ] E. The 2015 NYSE halt lasting roughly 3.5 hours is cited as an example of an unacceptable RTO

### 3. Primary and secondary sites
- [ ] A. A secondary site is a geographically separate, identical backup system
- [ ] B. State replication and log-based replication (WAL) are both described as synchronisation approaches
- [ ] C. Consensus protocols like Raft or Paxos guarantee zero data loss on failover at essentially no latency cost
- [ ] D. Placing the secondary very close to the primary protects best against a localised disaster like an earthquake
- [ ] E. Active-active matching engines are described as common in production exchanges today

### 4. Failover and split-brain
- [ ] A. Split-brain occurs when both the primary and secondary simultaneously believe they should be active
- [ ] B. Fencing (STONITH) is one technique used to prevent split-brain
- [ ] C. Quorum requirements demand agreement from a majority of nodes before a promotion to primary
- [ ] D. Manual failover is typically faster than automatic, heartbeat-triggered failover
- [ ] E. Active-passive replication is described as the more common choice than active-active in production

<div style="page-break-after: always;"></div>

### 5. Unique order identifiers
- [ ] A. A single central counter is simple but creates a single point of failure and a bottleneck
- [ ] B. Pre-allocated ID ranges per site avoid collisions without requiring coordination at submission time
- [ ] C. UUIDs are described as naturally sortable by arrival order
- [ ] D. Site-prefixed IDs make "which came first" comparisons trivial without stripping the prefix
- [ ] E. A hybrid approach combining UUIDs with monotonically increasing timestamps is described as a practical compromise

### 6. Real-world exchange facts
- [ ] A. NASDAQ launched in 1971 as described in the document
- [ ] B. Eurex is described as a European derivatives exchange
- [ ] C. Cboe is described in connection with the world of listed options
- [ ] D. LSE demutualised in 2001
- [ ] E. JPX runs on an all-electronic platform called "arrowhead"

### 7. Listing thresholds and alternatives
- [ ] A. A minimum bid price of roughly $4.00 is cited as typical at initial listing
- [ ] B. NASDAQ's Global Select, Global Market, and Capital Market tiers differ in stringency
- [ ] C. A company failing the minimum bid price rule is immediately and permanently delisted with no cure period
- [ ] D. Slack's 2019 NYSE listing is cited as a pioneering direct listing example
- [ ] E. A de-SPAC transaction is described as resembling a symbol change and delisting event

### 8. Order types recap with a twist
- [ ] A. A buy stop-limit order converts to a limit order once triggered
- [ ] B. FOK requires the engine to perform a dry-run sweep before committing any fills
- [ ] C. GTD orders require no automatic cancellation task from the exchange's scheduler
- [ ] D. An iceberg order's visible peak is replenished from a hidden reserve after being consumed
- [ ] E. A midpoint peg order is recalculated dynamically as (best_bid + best_ask) / 2 at match time

### 9. Depth and market impact, a fresh scenario
- [ ] A. Given asks of 1,000@$200.00, 800@$200.05, and 1,200@$200.10, a 2,000-share buy sweep fully consumes the first two levels and part of the third
- [ ] B. In that scenario, the VWAP of the 2,000-share sweep is (1000×200.00 + 800×200.05 + 200×200.10)/2000
- [ ] C. Market impact is defined as the difference between the sweep's VWAP and the initial best ask
- [ ] D. A deep book requires less sweeping through levels to fill a given order size
- [ ] E. Depth is best described as a single fixed number rather than a shape

<div style="page-break-after: always;"></div>

### 10. Price-time priority, a fresh amendment scenario
- [ ] A. A resting sell order amended from $150.40 down to $150.35 receives a new timestamp
- [ ] B. A resting sell order amended in quantity from 800 to 300 shares retains its original timestamp
- [ ] C. A cancel-and-replace of a market maker's quote always retains the original quote's priority
- [ ] D. Better price always beats an earlier arrival time at a worse price
- [ ] E. Pro-rata allocation is common in some options and interest-rate futures markets

### 11. Tick size and Rule 612
- [ ] A. Rule 612 sets a one-cent price-increment floor for NMS stocks priced at $1.00 or more
- [ ] B. Sub-penny quoting is permitted for stocks priced below $1.00
- [ ] C. The E-mini S&P 500 futures tick is 0.25 index points
- [ ] D. US Treasury futures tick in fractions of 1/32nd of a point
- [ ] E. Tick size is defined once globally and never varies by venue or price band

### 12. The matching engine's design
- [ ] A. Single-threaded matching is chosen primarily for its simplicity of implementation, not for determinism
- [ ] B. A heap-like structure gives O(1) access to the best price and O(log n) insertion/deletion
- [ ] C. Production engines often use balanced trees, skip lists, or intrusive linked lists indexed by price
- [ ] D. Sweeping through multiple price levels can generate slippage relative to the initial best price
- [ ] E. Each tradeable symbol maintains an entirely independent order book from every other symbol

### 13. The opening auction, a fresh worked scenario
- [ ] A. Given buy orders of 400@$62 and 900@$60, and sell orders of 700@$60 and 500@$61, the executable volume at $60 is 700
- [ ] B. In that same scenario, the executable volume at $61 is min(400, 700+500) = 400
- [ ] C. Comparing $60 (700 executable) and $61 (400 executable), the equilibrium price is $60
- [ ] D. All buyers and sellers who can trade at the equilibrium price trade at that single common price
- [ ] E. A remaining unmatched order after the uncross is always cancelled rather than transitioning to the continuous book

### 14. Indexes and the divisor, a fresh scenario
- [ ] A. If aggregate market cap rises from $500 billion to $525 billion due only to price appreciation, the divisor is left unchanged
- [ ] B. If aggregate market cap rises from $500 billion to $525 billion due to a new constituent being added, the divisor should be rescaled
- [ ] C. Rescaling the divisor after a non-price-driven cap change keeps the index level continuous at that instant
- [ ] D. Only future price movements change the index level after such a rescaling
- [ ] E. A stock buyback that shrinks share count without a price change requires no divisor adjustment

### 15. Circuit breaker tiers, revisited
- [ ] A. Level 1 (7% S&P 500 decline) and Level 2 (13%) both trigger a 15-minute halt if before 3:25pm
- [ ] B. Level 3 (20% decline) can trigger a halt even in the final minutes of the session
- [ ] C. LULD's Tier 1 band widens during the early and late parts of the session compared to regular hours
- [ ] D. A leveraged ETF's LULD band can be multiplied by its leverage factor
- [ ] E. LULD triggers immediately upon a price moving outside its band with no monitoring period

### 16. Clearing, margin, and Lehman
- [ ] A. Novation replaces bilateral counterparty exposure with exposure to the CCP on both sides
- [ ] B. Lehman Brothers' OTC derivatives lacked daily variation margin settlement through a CCP
- [ ] C. CME futures participants suffered material uncollateralised losses from Lehman's default
- [ ] D. Dodd-Frank and EMIR both moved to require central clearing for most standardised OTC derivatives
- [ ] E. Maintenance margin is the minimum balance that, if breached, triggers a margin call

### 17. Regulatory surveillance recap
- [ ] A. Spoofing is now explicitly illegal in both the US and the EU
- [ ] B. Front running involves acting on knowledge of another participant's pending order
- [ ] C. The Consolidated Audit Trail (CAT) has been operational in the US since 2020
- [ ] D. Quote stuffing is intended to improve overall market efficiency by adding liquidity
- [ ] E. Wash trading generates artificial trading volume without a genuine change of ownership

### 18. Knight Capital, the numbers
- [ ] A. Knight handled roughly 10-15% of all US equity trading volume before the incident
- [ ] B. The rogue system sent approximately 4 million orders over the 45-minute episode
- [ ] C. Knight's net positions spanned approximately 154 different stocks
- [ ] D. The firm's losses were smaller than its total pre-incident equity capital
- [ ] E. RLP (Retail Liquidity Program) was the new NYSE feature that triggered the deployment

### 19. Speed bumps and IEX, revisited
- [ ] A. IEX routes orders through 38 miles of coiled fibre before reaching the matching engine
- [ ] B. IEX's delay is described as approximately 350 microseconds
- [ ] C. Speed bumps applied only to cancel messages can defend against last-look practices
- [ ] D. IEX has displaced NYSE and NASDAQ as the largest US equity venue by volume
- [ ] E. IEX's founders argued that speed advantages primarily benefit long-term investors over HFT firms

<div style="page-break-after: always;"></div>

### 20. Technology transport layer
- [ ] A. FIX is described as a text-based protocol using a control character (SOH) as its field delimiter on the wire
- [ ] B. ITCH is a binary UDP-based market data protocol
- [ ] C. OUCH is the FIX counterpart used exclusively for cancel messages
- [ ] D. CME's MDP3 is based on the SBE (Simple Binary Encoding) standard
- [ ] E. Market data commonly uses UDP multicast while order entry commonly uses TCP

### 21. Market data architecture
- [ ] A. A snapshot is a complete picture of current book state, while an incremental update describes only what changed
- [ ] B. Conflation merges consecutive updates for the same price level into a single message
- [ ] C. Conflated data is described as fully suitable for analytical systems requiring complete tick-by-tick history
- [ ] D. Tick-to-trade latency measures the time from a market data message leaving the exchange to a resulting order being received back
- [ ] E. Top-of-book data is also known as Level 2 data

### 22. Market data economics
- [ ] A. The SIP consolidates trade and quote data from every registered US exchange into one public feed
- [ ] B. A proprietary direct feed typically offers more information and lower latency than the SIP
- [ ] C. Market data and connectivity fees are described as a shrinking share of major exchange revenue
- [ ] D. The SEC's Market Data Infrastructure rulemaking aimed to expand SIP content, including round-lot depth-of-book
- [ ] E. Exchanges that govern SIP pricing are the same companies that sell competing proprietary feeds

### 23. Latency and co-location
- [ ] A. Co-location places a participant's servers inside the same data centre as the matching engine
- [ ] B. Microwave links can be faster than fibre-optic cable over long distances because radio travels faster through air than light through glass
- [ ] C. FPGAs can generate an order response in tens of nanoseconds
- [ ] D. PTP synchronises clocks to sub-microsecond accuracy, more precise than standard NTP
- [ ] E. Kernel bypass technologies add latency by routing packets through additional software layers

<div style="page-break-after: always;"></div>

### 24. Operational observability
- [ ] A. Symptom-based alerts are generally preferred over cause-based alerts to reduce alert fatigue
- [ ] B. A dead-man's-switch alert fires when expected signals stop arriving
- [ ] C. An SLO of "99.9% of order ACKs within 200 microseconds" is an example of a Service-Level Objective
- [ ] D. Metrics, logs, and traces are described as three complementary observability data types
- [ ] E. Acceptable latency baselines are described as identical across every session phase, including auctions and halts

### 25. Incident response and Reg SCI
- [ ] A. A blameless postmortem is intended to encourage disclosure rather than assign individual blame
- [ ] B. MTTD and MTTR stand for time-to-detect and time-to-recover
- [ ] C. Regulation SCI requires covered market infrastructure to report significant systems issues to regulators
- [ ] D. An Incident Commander and a communications lead are described as the same role
- [ ] E. Runbooks are described as needing no rehearsal under realistic load conditions

### 26. Determinism, replay, and persistence
- [ ] A. A deterministic matching engine produces identical outputs given the same initial state and input sequence
- [ ] B. Reading the system clock directly mid-execution is described as a safe source of determinism
- [ ] C. A write-ahead log (WAL) is written before an input message is processed
- [ ] D. A warm restart from a snapshot is generally faster than a cold start from the beginning of the day
- [ ] E. GTC orders require persistence beyond the WAL to survive session boundaries

### 27. Sequence numbers and duplicate detection
- [ ] A. A sequence number identifies a message on a specific channel, distinct from an order's lifetime ID
- [ ] B. Detecting a message with an already-processed sequence number and discarding it approximates exactly-once processing
- [ ] C. A single order generates only one message and therefore only one sequence number over its lifetime
- [ ] D. Gap detection relies on sequence numbers arriving out of the expected order
- [ ] E. Ordered reconstruction during disaster recovery depends on replaying messages in sequence-number order

<div style="page-break-after: always;"></div>

### 28. Reference data risks
- [ ] A. An ISIN is described as independent of which specific exchange a security trades on
- [ ] B. A contract multiplier error loaded ten times too large would make margin requirements ten times too large
- [ ] C. Reference data is generally queried fresh from a database for every incoming order
- [ ] D. The 8 July 2015 NYSE outage lasting roughly 3.5 hours stemmed from a gateway software version mismatch
- [ ] E. A wrong tick size can cause valid orders to be rejected as tick-misaligned even though the matching engine's own logic is correct

### 29. Cryptocurrency and digital asset venues
- [ ] A. Order books, price-time priority, and deterministic matching are described as concepts that carry over to crypto venues
- [ ] B. Most cryptocurrency venues operate a defined daily open/close session with a scheduled closing auction
- [ ] C. A decentralised exchange's automated market maker prices trades from a pool ratio rather than matching resting orders
- [ ] D. The FTX collapse is presented as an example of what happens when matching, custody, and clearing are not kept institutionally separate
- [ ] E. Digital asset markets are described as operating under a single unified global regulator

### 30. Cross-cutting numeric review
- [ ] A. VWAP for 100 shares at $150 and 50 shares at $160 is $153.33
- [ ] B. Variation margin on 10,000 shares that fell $5 in a day is a $50,000 debit
- [ ] C. A midpoint peg fill between a $150.30 bid and $150.35 ask occurs at $150.325
- [ ] D. An index launching at base value 1000 with $7,007,100,000,000 aggregate cap implies a divisor of about 7.0071 billion
- [ ] E. A 60% deviation from a pre-crash reference price was the threshold used to bust trades after the 2010 Flash Crash

&nbsp;

---

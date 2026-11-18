# Exchange Concepts Knowledge Check — Variant 03
Purpose: verify that the student has read [How a Financial Exchange Works](../how-exchange-works.md) and internalized the core principles of a modern exchange, across its full scope — market history, order mechanics, risk and compliance, and technology infrastructure.

## Name/ID

&nbsp;

---

&nbsp;

## Instructions

- There are 20 questions.
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

### 1. Pre-trade risk controls
- [ ] A. Rate limiting/throttling caps the number of orders a gateway can submit per second
- [ ] B. Fail-fast check ordering typically evaluates cheap checks like format/syntax before expensive ones like live position/credit limits
- [ ] C. Pre-trade checks sit between the participant and the matching engine, so the engine itself can remain optimized purely for speed
- [ ] D. Position limits and credit limits measure exactly the same thing under different names
- [ ] E. Position and credit-limit checks are usually the cheapest checks to perform, since they don't need external data

### 2. Circuit breakers, general
- [ ] A. Circuit-breaker thresholds and halt durations have never been adjusted since their original 1988 introduction
- [ ] B. A halt typically ends via an instant resumption of continuous matching, with no auction step
- [ ] C. Circuit breakers trace their origin to the aftermath of the 1987 Black Monday crash and the Brady Commission's recommendations
- [ ] D. Level 3 of the US market-wide circuit breaker halts trading for the remainder of the trading day
- [ ] E. During a circuit-breaker halt, new orders cannot be submitted at all until the halt ends

### 3. LULD and the COVID-19 circuit-breaker events
- [ ] A. Single-stock LULD pauses operate independently from market-wide circuit breakers and were triggered far more frequently in March 2020
- [ ] B. A stock that stays in a limit state at its LULD band beyond the 15-second monitoring window enters a fixed-duration trading pause
- [ ] C. Level 1 US market-wide circuit breakers were triggered four times during the March 2020 COVID-19 crash
- [ ] D. Market-wide circuit-breaker thresholds are measured against the S&P 500's previous-day close throughout the trading day
- [ ] E. Level 2 was also triggered multiple times alongside Level 1 in March 2020

### 4. Fat-finger errors and price collars
- [ ] A. The 2005 Mizuho Securities incident involved a trader accidentally selling a huge quantity of shares at an absurdly low price instead of a small quantity at the intended price
- [ ] B. Static price collars compare an order's price to the most recently traded price rather than the prior close
- [ ] C. A dynamic price collar compares an order's price with the most recent trade price
- [ ] D. The Mizuho incident was caused by a matching-engine bug rather than a human order-entry error
- [ ] E. Price collars are a pre-trade control designed to catch fat-finger orders like Mizuho's before they reach the book

<div style="page-break-after: always;"></div>

### 5. Technology architecture
- [ ] A. Market data is commonly sent over TCP to each subscriber, while order entry commonly uses UDP multicast
- [ ] B. FIX is a text-based protocol whose wire delimiter is a non-printable SOH character, not a literal pipe symbol
- [ ] C. Binary protocols like ITCH and OUCH are generally more compact and faster to parse than an equivalent FIX message
- [ ] D. The gateway is typically the participant-facing component responsible for authentication and session management
- [ ] E. A hybrid design using UDP multicast for live data plus a separate recovery path, such as a TCP replay channel, is a standard exchange market-data pattern

### 6. Conformance testing and onboarding
- [ ] A. Recertification is typically required when the exchange changes something participants depend on, like a modified FIX tag
- [ ] B. Offboarding typically includes cancelling all resting orders and confirming final position/clearing reconciliation
- [ ] C. A stale, out-of-sync certification/UAT environment is still considered a valid basis for certifying participants
- [ ] D. Participants can typically connect a production gateway before completing formal conformance testing
- [ ] E. Conformance test scripts commonly simulate a disconnect/reconnect scenario to verify correct sequence-gap recovery

### 7. Recovery objectives
- [ ] A. RPO measures the maximum acceptable downtime, while RTO measures the maximum acceptable data loss
- [ ] B. Modern exchanges typically target sub-minute RTO for their most critical components
- [ ] C. For a matching engine, RPO is effectively zero — no committed trade or acknowledgement can be lost
- [ ] D. RTO tolerances are identical for a matching engine and for a batch reporting system
- [ ] E. The 2015 NYSE trading halt, lasting roughly 3.5 hours, is generally viewed as an example of an acceptable, well-managed RTO

<div style="page-break-after: always;"></div>

### 8. Failover and split-brain
- [ ] A. Manual, operator-controlled failover is generally slower than automatic failover but reduces the risk of a false failover
- [ ] B. Consensus protocols like Raft or Paxos can guarantee zero data loss on failover, at the cost of added latency
- [ ] C. Active-active failover, where both sites simultaneously process live orders with full consensus, is the most common production pattern among exchanges
- [ ] D. Split-brain occurs when both the primary and secondary site believe the other has failed, and each tries to become primary
- [ ] E. Fencing (STONITH) is a technique used to force a suspected-failed node to stop before a secondary takes over

### 9. Unique order numbering
- [ ] A. A single central counter for order IDs has no drawbacks as a scaling solution
- [ ] B. UUIDs guarantee practical global uniqueness without coordination, but they are not inherently sequential in arrival order
- [ ] C. Pre-allocated ID ranges per site can never create any gaps in the ID sequence
- [ ] D. Site-prefixed order IDs make it trivial to compare arrival order without stripping the prefix first
- [ ] E. Partitioning order books by symbol requires constant cross-server coordination for every single order

### 10. Market-data feed design
- [ ] A. Sequence numbers allow a subscriber to detect that a message was missed between two consecutive numbers
- [ ] B. Top-of-book and depth-of-book data both convey identical bandwidth and processing requirements
- [ ] C. Conflated feeds are considered fully acceptable for systems that need complete tick-by-tick analytical data
- [ ] D. Conflation merges consecutive updates to the same price level into a single message, which can lose intermediate states
- [ ] E. A snapshot represents the complete current book state, while an incremental update represents only what changed

### 11. SIP vs proprietary feeds
- [ ] A. The SIP is a public, consolidated feed aggregating data from every registered exchange under SEC oversight
- [ ] B. Proprietary direct feeds must wait for the SIP to aggregate the data before they can publish it
- [ ] C. Market data and connectivity revenue has become a substantial and growing share of major exchange profit
- [ ] D. Proprietary feeds can offer both more information and lower latency compared to the SIP
- [ ] E. Exchanges that jointly govern the SIP's pricing are, at the same time, the same companies selling competing proprietary feeds — a structural conflict of interest critics have raised

### 12. PFOF and dark pool settlements
- [ ] A. In the US, PFOF is fully banned outright with no ambiguity
- [ ] B. PFOF creates a potential conflict between where a broker routes an order and its duty of best execution to the client
- [ ] C. Zero-commission retail trading has no meaningful connection to payment for order flow
- [ ] D. Payment for order flow is effectively banned in the UK and, from 30 June 2026, across the EU
- [ ] E. Wholesale market makers pay for retail order flow because retail flow carries high adverse-selection risk

### 13. Smart order routing and fragmentation
- [ ] A. A marketable order must be routed to satisfy the NBBO or better, not a worse displayed price
- [ ] B. The NBBO is computed in real time as the best available bid and best available ask across all exchanges
- [ ] C. A locked market occurs when the best bid on one venue equals the best ask on another venue
- [ ] D. Smart order routers can consider factors like fees, queue-position probability, and venue toxicity signals, not just price alone
- [ ] E. A crossed market is actually less unusual and less exploitable than a locked market

### 14. Execution algorithms
- [ ] A. A Percentage of Volume strategy trades faster when market volume rises and slower when it falls
- [ ] B. Percentage of Volume strategies aim to match a fixed absolute share count regardless of market volume
- [ ] C. A TWAP algorithm slices an order evenly across time regardless of actual traded volume, unlike VWAP, which weights toward higher-volume periods
- [ ] D. VWAP algorithms ignore expected intraday volume patterns entirely
- [ ] E. Implementation Shortfall algorithms use a fixed, unchanging schedule regardless of how price moves

<div style="page-break-after: always;"></div>

### 15. Crypto venues
- [ ] A. Centralized crypto exchanges typically decouple trade matching from blockchain settlement, recording trades as internal ledger entries
- [ ] B. Decentralized exchanges commonly replace the order book with an automated market maker governed by a pricing formula like a constant-product rule
- [ ] C. Cryptocurrency venues are subject to one single unified global regulator, unlike traditional securities markets
- [ ] D. Centralized crypto exchanges always operate with an independent, regulated central counterparty separate from the exchange itself
- [ ] E. A trade on a typical AMM-based DEX is its own settlement, executed atomically within a single blockchain transaction

### 16. The FTX collapse
- [ ] A. FTX's founder was later convicted of fraud following the collapse
- [ ] B. FTX had an independent CCP performing novation between its customers, similar to traditional cleared markets
- [ ] C. Customer deposits were allegedly commingled with the affiliated trading firm's funds
- [ ] D. FTX's collapse has been compared to the Barings Bank and Knight Capital episodes as a cautionary tale about separation of duties
- [ ] E. FTX simultaneously operated as the trading venue and, through an affiliated firm, traded against its own customers

### 17. Latency and co-location
- [ ] A. PTP clock synchronization is generally less precise than NTP
- [ ] B. Co-locating a participant's servers inside the exchange's own data center can reduce round-trip latency to low single-digit microseconds
- [ ] C. FPGAs typically take milliseconds to parse a market-data message and generate a response
- [ ] D. Light travels faster through fibre-optic glass than radio waves travel through open air over the same distance
- [ ] E. Spread Networks' expensive new fiber route became less competitive within a few years, once microwave links achieved similar routes faster

### 18. Observability and the four golden signals
- [ ] A. Metrics alone are generally sufficient to explain exactly why one specific order behaved oddly
- [ ] B. Symptom-based alerting and cause-based alerting are considered equally effective and interchangeable approaches
- [ ] C. Saturation is typically described as a leading indicator that tends to rise before latency and errors visibly degrade
- [ ] D. The four golden signals used in SRE-style monitoring are Latency, Traffic, Errors, and Saturation
- [ ] E. An error budget represents the gap between a service's SLO target and 100% availability/performance

<div style="page-break-after: always;"></div>

### 19. Corporate actions and reference data
- [ ] A. Open limit orders generally need adjustment across a stock split, so that price and quantity reflect the new terms
- [ ] B. Reference data is typically loaded and cached aggressively at startup, because querying it per order would add unacceptable latency
- [ ] C. Corporate actions require coordinated updates across the order book engine, clearing system, market data system, and audit trail
- [ ] D. A wrongly loaded contract multiplier can make every P&L and margin calculation for that instrument wrong by the same proportional factor
- [ ] E. A stock split increases a company's total market capitalisation in proportion to the split ratio

### 20. The 2015 NYSE halt
- [ ] A. The 2015 NYSE halt demonstrated that reference-data/configuration issues cannot meaningfully affect exchange availability
- [ ] B. During the 2015 NYSE halt, all US equity trading nationwide came to a complete stop because no other venue could handle NYSE-listed stocks
- [ ] C. The 2015 NYSE halt was caused by a cyberattack on the exchange's matching engine
- [ ] D. The 2015 NYSE halt was resolved within a few seconds, due to automatic failover
- [ ] E. The 2015 NYSE trading halt, lasting roughly 3.5 hours, was ultimately traced to a software configuration mismatch from a gateway update


&nbsp;

---



# Exchange Concepts Knowledge Check — Variant 02

Purpose: verify that the student has read [How a Financial Exchange Works](../how-exchange-works.md) and internalized the core principles of a modern exchange.

## Instructions

- Each question has five options (A-E).
- Select all options you believe are correct.
- It is not known in advance how many options are correct in each question.

## Scoring

- +1 point for each correct option selected.
- -2 points for each incorrect option selected.
- 0 points for options not selected.
- Final test score is capped at a minimum of 0: if raw total is negative, recorded score is 0.

## Questions

### 1. Price discovery in an exchange
- [ ] A. Price discovery emerges from executable supply and demand
- [ ] B. Last traded price alone fully represents available liquidity
- [ ] C. Bid-ask spread is a direct indicator of immediate trading cost
- [ ] D. Deep books generally reduce price impact for moderate orders
- [ ] E. Exchanges should hide all pre-trade information to improve discovery

### 2. Roles in market structure
- [ ] A. Brokers route client orders to trading venues
- [ ] B. Market makers often provide continuous two-sided quotes
- [ ] C. Regulators define and enforce market conduct rules
- [ ] D. Exchanges are passive bulletin boards with no rule enforcement
- [ ] E. Different participants have different incentives and constraints

### 3. Core order handling concepts
- [ ] A. Orders carry intent, constraints, and lifecycle state
- [ ] B. Time-in-force defines how long an order may remain active
- [ ] C. Immediate-or-cancel can leave a residual resting quantity
- [ ] D. Fill-or-kill requires immediate full execution or cancellation
- [ ] E. Order acknowledgements are part of operational transparency

### 4. Order type behavior
- [ ] A. A market order may execute across multiple levels
- [ ] B. A stop order triggers based on a market condition
- [ ] C. A stop-limit combines a trigger with a limit price constraint
- [ ] D. Iceberg orders reveal full hidden quantity to all participants
- [ ] E. Hidden-liquidity design choices affect fairness and transparency debates

### 5. Why price-time priority matters
- [ ] A. It creates predictable queue behavior
- [ ] B. It discourages arbitrary matching decisions
- [ ] C. It guarantees equal fill size for all orders at a level
- [ ] D. It allows deterministic replay in incident analysis
- [ ] E. It supports participant trust in matching fairness

### 6. Matching and determinism
- [ ] A. Deterministic matching helps produce reproducible outcomes
- [ ] B. Replayability is important for compliance and debugging
- [ ] C. Concurrent writes to one book can complicate consistency
- [ ] D. Matching logic should be opaque to prevent gaming
- [ ] E. Event ordering is central to correct trade reconstruction

### 7. Auctions in the trading day
- [ ] A. Auctions aggregate liquidity at discrete times
- [ ] B. Opening auctions can reduce chaotic open prints
- [ ] C. Closing auctions are often important for benchmark pricing
- [ ] D. Auctions remove the need for continuous trading
- [ ] E. Session design is part of overall market quality

### 8. Market-maker mechanics
- [ ] A. Two-sided quoting supports continuous tradability
- [ ] B. Quote obligations can include spread/size requirements
- [ ] C. When one quote side fills, residual risk profile changes
- [ ] D. Quote refresh policy affects realized liquidity quality
- [ ] E. Market-making has no interaction with risk controls

### 9. Risk-control layers
- [ ] A. Some controls happen before an order reaches matching
- [ ] B. Other controls act during live market conditions
- [ ] C. Circuit breakers are one mechanism for disorderly moves
- [ ] D. Kill switches can be useful in operational incidents
- [ ] E. Strong controls and fair markets are contradictory goals

### 10. Drop copy and operational resilience
- [ ] A. Drop copy helps independent reconciliation of fills/events
- [ ] B. Sequence gaps should be detectable and recoverable
- [ ] C. Public quote feed and drop copy serve identical purposes
- [ ] D. Risk and compliance workflows rely on trustworthy records
- [ ] E. Time ordering of events matters for post-trade controls

### 11. Clearing, margin, and settlement
- [ ] A. Clearing houses manage counterparty exposure between trade and settlement
- [ ] B. Margin is a financial safeguard against default risk
- [ ] C. Settlement finalizes asset and cash transfer obligations
- [ ] D. Trade matching removes the need for clearing safeguards
- [ ] E. Post-trade robustness contributes to confidence in trading venues

### 12. Technology architecture principles
- [ ] A. Gateway, engine, and downstream consumers form distinct layers
- [ ] B. Message buses separate producers and subscribers operationally
- [ ] C. Snapshot plus incremental patterns can support market-data recovery
- [ ] D. Exchanges should avoid telemetry to maximize throughput
- [ ] E. Fault isolation improves resilience in multi-process designs

### 13. Fragmentation and routing
- [ ] A. Liquidity can be distributed across venues
- [ ] B. Routing logic can evaluate price, size, and policy constraints
- [ ] C. Consolidated top-of-book views can aid best-execution decisions
- [ ] D. Fragmented markets never face synchronization challenges
- [ ] E. Hidden venues complicate full visibility of available liquidity

### 14. Compliance and surveillance
- [ ] A. Surveillance attempts to detect manipulative behavior patterns
- [ ] B. Reliable audit trails improve accountability
- [ ] C. Compliance is purely a legal department concern, not system design
- [ ] D. Detection quality depends on data quality and lineage
- [ ] E. Exchange credibility depends partly on effective oversight

### 15. Integrated understanding
- [ ] A. Matching quality, risk controls, and post-trade are interdependent
- [ ] B. Fair access and deterministic rules are market-design principles
- [ ] C. Exchange engineering balances speed, safety, and transparency
- [ ] D. A modern exchange can ignore recovery planning if latency is low
- [ ] E. Robust operations require both technical and governance controls

### 16. Immediate full-or-cancel behavior
- [ ] A. LIMIT
- [ ] B. MARKET
- [ ] C. FOK
- [ ] D. DAY
- [ ] E. STOP_LIMIT

### 17. Same-price queue precedence
- [ ] A. Largest order size has priority
- [ ] B. Earliest timestamp has priority
- [ ] C. Latest timestamp has priority
- [ ] D. Hidden orders always jump queue
- [ ] E. Queue order is random

### 18. Circuit-breaker objectives
- [ ] A. Pause trading during extreme disorderly moves
- [ ] B. Guarantee profitable exits for all participants
- [ ] C. Provide a cooling-off period for reassessment
- [ ] D. Maximize message throughput under stress
- [ ] E. Reduce panic-driven feedback loops

### 19. Recovery after missed market-data messages
- [ ] A. Sequence numbers
- [ ] B. Gap replay/retransmission path
- [ ] C. Increasing terminal refresh rate
- [ ] D. Randomized order IDs
- [ ] E. Manual spreadsheet reconstruction only

### 20. Matching vs settlement
- [ ] A. Matching immediately finalizes cash and securities transfer
- [ ] B. Matching creates obligations; clearing/settlement finalize transfer
- [ ] C. Settlement occurs before matching
- [ ] D. Post-trade processing is optional in real exchanges
- [ ] E. Settlement has no role in market confidence

## Instructor Correction Key

| Q | Correct options |
|---|---|
| 1 | A, C, D |
| 2 | A, B, C, E |
| 3 | A, B, D, E |
| 4 | A, B, C, E |
| 5 | A, B, D, E |
| 6 | A, B, C, E |
| 7 | A, B, C, E |
| 8 | A, B, C, D |
| 9 | A, B, C, D |
| 10 | A, B, D, E |
| 11 | A, B, C, E |
| 12 | A, B, C, E |
| 13 | A, B, C, E |
| 14 | A, B, D, E |
| 15 | A, B, C, E |
| 16 | C |
| 17 | B |
| 18 | A, C, E |
| 19 | A, B |
| 20 | B |

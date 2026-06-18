# Exchange Concepts Knowledge Check — Variant 04

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

### 1. What does an exchange fundamentally provide?
- [ ] A. A standardized venue for matching buyers and sellers
- [ ] B. Guaranteed profits for all participants
- [ ] C. Transparent and rule-based trade execution
- [ ] D. A framework for market integrity and oversight
- [ ] E. Elimination of all counterparty and market risk

### 2. Primary vs secondary market
- [ ] A. Primary markets involve issuance of new securities
- [ ] B. Secondary markets are where investors trade existing securities
- [ ] C. Secondary liquidity can affect valuation and issuer attractiveness
- [ ] D. Secondary trades always send proceeds directly to the issuer
- [ ] E. Exchanges are primarily secondary-market trading venues

### 3. Order book interpretation
- [ ] A. The best bid is the highest available buy price
- [ ] B. The best ask is the lowest available sell price
- [ ] C. The spread equals ask minus bid
- [ ] D. Book depth can affect slippage for larger trades
- [ ] E. Top-of-book always shows all executable liquidity in the market

### 4. Order types and intent
- [ ] A. Limit orders prioritize price control
- [ ] B. Market orders prioritize certainty of execution speed
- [ ] C. Stop orders use trigger conditions
- [ ] D. Stop-limit orders remove all execution uncertainty
- [ ] E. Iceberg orders can partially conceal quantity

### 5. Price-time priority
- [ ] A. Better-priced orders rank ahead of worse prices
- [ ] B. At same price, earlier orders rank ahead of later ones
- [ ] C. Larger size always jumps queue at same price
- [ ] D. Amendments can affect queue priority depending on rule set
- [ ] E. Price-time supports fairness and predictability

### 6. Matching-engine principles
- [ ] A. Deterministic behavior helps replay and investigation
- [ ] B. A single writer per book can simplify consistency
- [ ] C. Matching outcomes should be non-repeatable to reduce gaming
- [ ] D. Correct event ordering is critical for downstream systems
- [ ] E. Auditability is a core requirement

### 7. Sessions and auctions
- [ ] A. Exchanges can have pre-open, auction, and continuous phases
- [ ] B. Opening auctions can concentrate liquidity for opening price discovery
- [ ] C. Closing auctions can matter for benchmark pricing
- [ ] D. Session state can influence order handling behavior
- [ ] E. Auctions replace the need for continuous trading entirely

### 8. Market makers
- [ ] A. Market makers often provide two-sided quotes
- [ ] B. Obligations can include spread and size constraints
- [ ] C. Fill on one side can create inventory risk asymmetry
- [ ] D. Quote refresh policy affects liquidity continuity
- [ ] E. Market making removes need for risk controls

### 9. Risk controls
- [ ] A. Pre-trade checks can reject invalid or risky orders
- [ ] B. Price collars can constrain extreme prices
- [ ] C. Circuit breakers can pause trading during disorderly moves
- [ ] D. Kill switch tools can rapidly reduce exposure
- [ ] E. Risk controls should be avoided in modern markets

### 10. Self-match prevention and surveillance
- [ ] A. SMP helps prevent self-trading scenarios
- [ ] B. SMP can reduce wash-trade risk
- [ ] C. Surveillance depends on high-quality event records
- [ ] D. Audit trails are useful for post-incident reconstruction
- [ ] E. Manipulation detection is irrelevant for exchanges

### 11. Market data and drop copy
- [ ] A. Public market data and drop copy have different purposes
- [ ] B. Sequence numbers help detect message gaps
- [ ] C. Replay can be used in recovery workflows
- [ ] D. Drop copy is only useful for retail charting
- [ ] E. Feed reliability and recoverability are both important

### 12. Clearing and settlement
- [ ] A. Matching and settlement are different lifecycle stages
- [ ] B. Clearing helps manage counterparty obligations
- [ ] C. Settlement is where cash/securities movement is finalized
- [ ] D. Margin can mitigate default risk
- [ ] E. A matched trade means settlement risk no longer exists

### 13. Fragmentation and routing
- [ ] A. Liquidity can be distributed across venues
- [ ] B. Smart routing can improve execution outcomes
- [ ] C. Fragmentation can increase routing complexity
- [ ] D. Venue choice can impact fees and fill probability
- [ ] E. Fragmentation guarantees identical prices and depth everywhere

### 14. Architecture and resilience
- [ ] A. Separation of components can improve operability
- [ ] B. Failover planning is part of robust exchange design
- [ ] C. Observability is important for safe operations
- [ ] D. Shared mutable state everywhere always improves reliability
- [ ] E. Capacity and recovery planning are both important

### 15. Big-picture understanding
- [ ] A. Exchange design balances speed, fairness, and safety
- [ ] B. Governance and technology both affect market quality
- [ ] C. Post-trade infrastructure is part of market trust
- [ ] D. Latency is the only meaningful objective
- [ ] E. Core principles span pre-trade, trade, and post-trade

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
| 3 | A, B, C, D |
| 4 | A, B, C, E |
| 5 | A, B, D, E |
| 6 | A, B, D, E |
| 7 | A, B, C, D |
| 8 | A, B, C, D |
| 9 | A, B, C, D |
| 10 | A, B, C, D |
| 11 | A, B, C, E |
| 12 | A, B, C, D |
| 13 | A, B, C, D |
| 14 | A, B, C, E |
| 15 | A, B, C, E |
| 16 | C |
| 17 | B |
| 18 | A, C, E |
| 19 | A, B |
| 20 | B |

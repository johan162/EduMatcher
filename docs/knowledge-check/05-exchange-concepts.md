# Exchange Concepts Knowledge Check — Variant 05

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

### 1. Exchange role in the financial system
- [ ] A. Supports transfer of ownership between participants
- [ ] B. Provides deterministic matching rules
- [ ] C. Guarantees no participant losses
- [ ] D. Enables transparent price formation
- [ ] E. Operates within a regulated framework

### 2. Financing and market structure
- [ ] A. Equity financing involves ownership dilution
- [ ] B. Debt financing creates repayment obligations
- [ ] C. Secondary market activity is unrelated to capital formation incentives
- [ ] D. IPOs are associated with primary issuance
- [ ] E. Strong secondary liquidity can support stronger primary issuance demand

### 3. Book mechanics
- [ ] A. Bid side contains buying interest
- [ ] B. Ask side contains selling interest
- [ ] C. Spread is a cost signal for immediate execution
- [ ] D. Depth is irrelevant for large orders
- [ ] E. Tick size constrains valid price increments

### 4. Execution semantics
- [ ] A. Market orders may walk the book in thin liquidity
- [ ] B. Limit orders can rest if not fully matched
- [ ] C. Partial fills are possible in continuous matching
- [ ] D. All accepted orders fully execute instantly
- [ ] E. Publication of trades supports transparency

### 5. Priority rules
- [ ] A. Price priority generally comes before time priority
- [ ] B. Same price typically uses FIFO-like ordering
- [ ] C. Queue position has no practical effect on outcomes
- [ ] D. Certain modifications can reset time priority
- [ ] E. Predictable priority contributes to fairness perception

### 6. Time-in-force concepts
- [ ] A. IOC can execute partially then cancel remainder
- [ ] B. FOK requires immediate full execution
- [ ] C. DAY and GTC represent different persistence behavior
- [ ] D. TIF selection can affect realized fill patterns
- [ ] E. TIF has no strategic relevance

### 7. Market makers and quote behavior
- [ ] A. Two-sided quoting can improve liquidity
- [ ] B. Quote obligations can constrain spread/size
- [ ] C. One-side fill can require quote state management
- [ ] D. Quote refresh policy matters after fill events
- [ ] E. Market makers never face inventory risk

### 8. Auctions and sessions
- [ ] A. Auctions can aggregate interest at discrete times
- [ ] B. Session states can change permissible actions
- [ ] C. Closing auctions can be important for index benchmarks
- [ ] D. Session-state communication is operationally useful
- [ ] E. Continuous session is the only meaningful phase

### 9. Risk architecture
- [ ] A. Pre-trade checks can prevent bad flow from hitting matching
- [ ] B. Circuit breakers are tools for disorderly conditions
- [ ] C. Collar logic can limit outlier executions
- [ ] D. Kill switches can be incident-response controls
- [ ] E. Market integrity improves when controls are absent

### 10. SMP and abuse controls
- [ ] A. SMP can reduce accidental/internal self-cross events
- [ ] B. Surveillance can detect manipulative patterns
- [ ] C. Audit records are useful for investigations
- [ ] D. Abuse controls are unnecessary in electronic markets
- [ ] E. Event chronology quality matters for enforcement

### 11. Data feed design
- [ ] A. Snapshot and incremental feeds can be complementary
- [ ] B. Sequence numbers support gap detection
- [ ] C. Replay is useful after disconnects
- [ ] D. Public feed and drop copy always have identical semantics
- [ ] E. Recovery design is part of robust distribution

### 12. Post-trade processes
- [ ] A. Clearing and settlement complete the trade lifecycle
- [ ] B. Clearing can reduce bilateral counterparty risk
- [ ] C. Margining is part of default risk management
- [ ] D. Settlement reliability contributes to trust
- [ ] E. Matching alone is sufficient for finality

### 13. Fragmentation and routing
- [ ] A. Liquidity can be fragmented across multiple venues
- [ ] B. Routing can optimize for multiple objectives
- [ ] C. Consolidated references can aid best execution
- [ ] D. Fragmentation never affects execution quality
- [ ] E. Hidden liquidity can complicate visibility

### 14. Engineering principles
- [ ] A. Determinism helps debugging and compliance
- [ ] B. Isolation of components can reduce blast radius
- [ ] C. Observability can be deferred indefinitely
- [ ] D. Resilience includes both failover and recovery testing
- [ ] E. Latency should be balanced with safety and correctness

### 15. Integrated market understanding
- [ ] A. Pre-trade, matching, and post-trade are interconnected
- [ ] B. Market design includes both policy and software choices
- [ ] C. Exchange quality cannot be evaluated only by speed
- [ ] D. Governance has no effect on technical outcomes
- [ ] E. Fairness and transparency are enduring core principles

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
| 1 | A, B, D, E |
| 2 | A, B, D, E |
| 3 | A, B, C, E |
| 4 | A, B, C, E |
| 5 | A, B, D, E |
| 6 | A, B, C, D |
| 7 | A, B, C, D |
| 8 | A, B, C, D |
| 9 | A, B, C, D |
| 10 | A, B, C, E |
| 11 | A, B, C, E |
| 12 | A, B, C, D |
| 13 | A, B, C, E |
| 14 | A, B, D, E |
| 15 | A, B, C, E |
| 16 | C |
| 17 | B |
| 18 | A, C, E |
| 19 | A, B |
| 20 | B |

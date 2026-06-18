# Exchange Concepts Knowledge Check — Variant 06

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

### 1. Why rule-based markets matter
- [ ] A. They make outcomes more explainable and auditable
- [ ] B. They remove all uncertainty from trading
- [ ] C. They support fair participant expectations
- [ ] D. They provide a shared framework for execution behavior
- [ ] E. They are independent from regulatory context

### 2. Market participants and incentives
- [ ] A. Brokers and market makers can have different objectives
- [ ] B. Exchanges enforce venue rules and protocols
- [ ] C. Regulators play no role in modern market oversight
- [ ] D. Participant behavior is influenced by structure and incentives
- [ ] E. Multiple participant roles can coexist in one market ecosystem

### 3. Price discovery and liquidity signals
- [ ] A. Spread is a useful indicator of immediate trading cost
- [ ] B. Book depth can inform expected impact of larger trades
- [ ] C. Last trade price always equals fair value
- [ ] D. Fragmented liquidity can complicate price discovery
- [ ] E. Top-of-book is one view, not always the full picture

### 4. Order handling fundamentals
- [ ] A. Limit orders can protect against poor execution prices
- [ ] B. Market orders can trade through multiple levels
- [ ] C. Stop-limit orders use trigger plus limit constraints
- [ ] D. All stop orders guarantee fill at trigger price
- [ ] E. OCO structures can automate conditional exits

### 5. Priority and queue dynamics
- [ ] A. Price improvement can supersede time priority
- [ ] B. At equal price, earlier order time often matters
- [ ] C. Queue position has no effect on probability of fill
- [ ] D. Amendments can alter queue placement in many systems
- [ ] E. Priority logic should be deterministic

### 6. Session and auction logic
- [ ] A. Opening/closing auctions can improve concentrated price discovery
- [ ] B. Session states can influence accepted order behaviors
- [ ] C. Continuous trading is the only useful trading phase
- [ ] D. Session transitions should be communicated clearly
- [ ] E. Operational controls often align with session logic

### 7. Market-maker concepts
- [ ] A. Two-sided quoting supports continuous tradability
- [ ] B. Quote obligations can be codified in policy/configuration
- [ ] C. Fill asymmetry can introduce inventory risk
- [ ] D. Quote lifecycle events matter for strategy control
- [ ] E. Market making eliminates need for controls like MMP

### 8. Risk controls in layered design
- [ ] A. Pre-trade checks can block invalid/risky orders early
- [ ] B. Circuit breakers can help stabilize disorderly conditions
- [ ] C. Collars can constrain extreme execution prices
- [ ] D. Kill switch tools can support incident response
- [ ] E. Layered controls are generally unnecessary

### 9. Surveillance and integrity
- [ ] A. Exchanges may monitor for manipulative behavior patterns
- [ ] B. High-fidelity audit trails aid investigations
- [ ] C. SMP can reduce self-trade issues
- [ ] D. Compliance can be separated completely from system design
- [ ] E. Event ordering accuracy is important for enforcement

### 10. Feed architecture
- [ ] A. Incremental feeds benefit from sequence control
- [ ] B. Snapshots can help state recovery
- [ ] C. Replay mechanisms are useful after data gaps
- [ ] D. Drop copy and public market data always have identical scopes
- [ ] E. Robust feed design balances speed and recoverability

### 11. Clearing and settlement lifecycle
- [ ] A. Matching does not by itself complete settlement finality
- [ ] B. Clearing helps manage obligations and counterparty exposure
- [ ] C. Margin can reduce default propagation risk
- [ ] D. DvP is a mechanism to reduce principal risk
- [ ] E. Settlement reliability has no impact on market confidence

### 12. Resilience architecture
- [ ] A. Failover planning is a core operational concern
- [ ] B. Recovery drills/testing can be important
- [ ] C. Capacity and latency both matter in production design
- [ ] D. Shared mutable global state always improves resilience
- [ ] E. Site topology choices involve trade-offs

### 13. Fragmentation and routing
- [ ] A. Smart order routing can evaluate price and non-price factors
- [ ] B. Fragmentation can split visible liquidity
- [ ] C. Consolidated references can assist execution decisions
- [ ] D. Venue selection can affect cost and fill quality
- [ ] E. Fragmentation makes routing logic obsolete

### 14. Technology and governance interplay
- [ ] A. Governance constraints influence technical design choices
- [ ] B. Technical controls can support policy objectives
- [ ] C. Market quality emerges from both rules and implementation
- [ ] D. Speed alone defines high-quality market design
- [ ] E. Transparency mechanisms improve trust and accountability

### 15. System-level synthesis
- [ ] A. Exchange systems span pre-trade, trade, and post-trade domains
- [ ] B. Deterministic matching and auditability are linked
- [ ] C. Risk controls and liquidity design can interact
- [ ] D. Post-trade concerns are unrelated to exchange architecture
- [ ] E. Core principles should remain robust under stress scenarios

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
| 2 | A, B, D, E |
| 3 | A, B, D, E |
| 4 | A, B, C, E |
| 5 | A, B, D, E |
| 6 | A, B, D, E |
| 7 | A, B, C, D |
| 8 | A, B, C, D |
| 9 | A, B, C, E |
| 10 | A, B, C, E |
| 11 | A, B, C, D |
| 12 | A, B, C, E |
| 13 | A, B, C, D |
| 14 | A, B, C, E |
| 15 | A, B, C, E |
| 16 | C |
| 17 | B |
| 18 | A, C, E |
| 19 | A, B |
| 20 | B |

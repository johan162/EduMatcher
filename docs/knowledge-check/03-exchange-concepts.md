# Exchange Concepts Knowledge Check — Variant 03

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

### 1. Core promises of an exchange
- [ ] A. Rule-based matching and transparent procedures
- [ ] B. Guaranteed profit for all participants
- [ ] C. Trusted venue for liquidity and price formation
- [ ] D. Operational controls for orderly markets
- [ ] E. Elimination of all volatility

### 2. Capital formation context
- [ ] A. Equity issuance is a way to raise growth capital
- [ ] B. Debt financing implies repayment obligations
- [ ] C. Secondary trading can improve attractiveness of primary issuance
- [ ] D. Secondary markets are irrelevant to company valuation
- [ ] E. IPOs connect issuers with public investors

### 3. Reading top of book
- [ ] A. Best bid is highest currently available buy price
- [ ] B. Best ask is lowest currently available sell price
- [ ] C. Spread equals ask minus bid at top of book
- [ ] D. Narrower spreads often indicate better immediate liquidity
- [ ] E. Top of book always reveals full hidden and conditional liquidity

### 4. Execution logic basics
- [ ] A. Aggressive orders can trade against resting passive liquidity
- [ ] B. Partial fills are possible when available opposite quantity is limited
- [ ] C. Every accepted order must execute immediately in continuous trading
- [ ] D. Remaining quantity can continue resting when order rules allow
- [ ] E. Trade publication is part of market transparency

### 5. Time-in-force understanding
- [ ] A. DAY orders generally expire by session end if unfilled
- [ ] B. GTC orders can persist across sessions until canceled or filled
- [ ] C. IOC allows immediate partial fill with remainder canceled
- [ ] D. FOK allows partial fills if completed quickly
- [ ] E. TIF expresses order lifetime intent

### 6. Price increments and fairness
- [ ] A. Tick size defines minimum price increment
- [ ] B. Tick constraints standardize price grid behavior
- [ ] C. Smaller ticks can alter queue dynamics and spread behavior
- [ ] D. Tick size has no influence on liquidity provision
- [ ] E. Correct tick handling is necessary for valid book states

### 7. Market makers in practice
- [ ] A. They provide tradable quotes on both sides
- [ ] B. They carry inventory risk while facilitating liquidity
- [ ] C. Quote lifecycle handling affects continuity of liquidity
- [ ] D. Market makers never need protection controls
- [ ] E. Quote and fill events must be tracked for accurate state

### 8. Session states and state machines
- [ ] A. Exchanges can move through defined session states
- [ ] B. Order handling policy can vary by session state
- [ ] C. Halt/resume controls are unrelated to session management
- [ ] D. Explicit state transitions improve predictability and controls
- [ ] E. Session-state dissemination helps participants synchronize behavior

### 9. Circuit breakers and collars
- [ ] A. Circuit breakers can pause trading after extreme moves
- [ ] B. Price collars can reject orders outside allowed bands
- [ ] C. Such controls aim to reduce disorderly trading conditions
- [ ] D. They are designed to maximize message throughput only
- [ ] E. They are part of market integrity tooling

### 10. SMP and anti-abuse mechanisms
- [ ] A. SMP helps prevent self-crossing activity
- [ ] B. Anti-abuse design combines rules, monitoring, and records
- [ ] C. Audit trails assist post-incident analysis
- [ ] D. Wash-trade concerns are solved only by faster matching
- [ ] E. Surveillance needs reliable event chronology

### 11. Data feeds and recovery
- [ ] A. Incremental feeds are efficient but need sequencing discipline
- [ ] B. Snapshot mechanisms help state recovery
- [ ] C. Sequence numbers can support gap detection/replay workflows
- [ ] D. Missing messages can always be inferred with zero ambiguity
- [ ] E. Robust feed design balances latency and recoverability

### 12. Clearing and post-trade lifecycle
- [ ] A. Clearing intermediates obligations after execution
- [ ] B. Settlement is the final exchange of value/assets
- [ ] C. Counterparty risk exists between trade and settlement
- [ ] D. Post-trade is optional if matching is deterministic
- [ ] E. Margin frameworks reduce default propagation risk

### 13. Fragmentation and smart routing
- [ ] A. Best execution can require searching multiple venues
- [ ] B. Fragmentation can split visible liquidity
- [ ] C. Routing must consider both market data and constraints
- [ ] D. Fragmentation removes the need for consolidated references
- [ ] E. Hidden venues can affect practical execution outcomes

### 14. Engineering and operations
- [ ] A. Determinism aids debugging, compliance, and trust
- [ ] B. Resilience planning includes failover and recovery strategy
- [ ] C. Exchange reliability is only a hardware topic
- [ ] D. Telemetry and auditability support safe operations
- [ ] E. Good architecture isolates failures between components

### 15. Big-picture synthesis
- [ ] A. A modern exchange is both a market institution and a software system
- [ ] B. Fairness, transparency, and resilience are design-level concerns
- [ ] C. Low latency is one objective among several competing objectives
- [ ] D. Governance and technology are independent in market quality outcomes
- [ ] E. Understanding order flow requires linking pre-trade, trade, and post-trade views

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
| 4 | A, B, D, E |
| 5 | A, B, C, E |
| 6 | A, B, C, E |
| 7 | A, B, C, E |
| 8 | A, B, D, E |
| 9 | A, B, C, E |
| 10 | A, B, C, E |
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

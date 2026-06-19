# Exchange Concepts Knowledge Check — Variant 01

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

### 1. Why does a financial exchange exist?
- [ ] A. To centralize buyers and sellers under transparent rules
- [ ] B. To guarantee fair matching logic and time-priority enforcement
- [ ] C. To eliminate all investment risk for participants
- [ ] D. To provide trusted price discovery from real supply and demand
- [ ] E. To replace all brokers in every market structure

### 2. Primary market vs secondary market
- [ ] A. IPO issuance happens in the primary market
- [ ] B. Most day-to-day trading between investors is in the secondary market
- [ ] C. Secondary-market liquidity can influence primary-market valuations
- [ ] D. The primary market is where a stock's bid-ask spread is continuously formed
- [ ] E. Exchanges mainly operate secondary-market trading venues

### 3. About order books
- [ ] A. An order book stores resting buy and sell interest
- [ ] B. Best bid is the highest buy price currently available
- [ ] C. Best ask is the lowest sell price currently available
- [ ] D. The spread is best ask minus best bid
- [ ] E. A trade can only happen when there is no spread

### 4. Limit and market orders
- [ ] A. A limit buy sets a maximum acceptable execution price
- [ ] B. A limit sell sets a minimum acceptable execution price
- [ ] C. A market order guarantees price but not execution
- [ ] D. A market order prioritizes execution speed over price control
- [ ] E. Limit orders can rest in the book if not immediately matched

### 5. Price-time priority
- [ ] A. Better price ranks ahead of worse price
- [ ] B. At equal price, earlier arrival ranks ahead of later arrival
- [ ] C. A large order always ranks ahead of smaller orders at same price
- [ ] D. Repricing an order can affect its queue priority
- [ ] E. Price-time priority is a fairness rule used by many central limit order books

### 6. Matching engine principles
- [ ] A. The matching engine is the authoritative component for book state
- [ ] B. Deterministic matching improves auditability and fairness
- [ ] C. Multiple independent writers to the same symbol book improve consistency
- [ ] D. Single-writer per book design avoids race conditions in matching
- [ ] E. Matching decisions should be explainable after the fact from event logs

### 7. Trading sessions and auctions
- [ ] A. Continuous trading is not the only session type in modern markets
- [ ] B. Opening auctions help establish an equilibrium opening price
- [ ] C. Closing auctions can concentrate liquidity near the close
- [ ] D. Session state can change order handling behavior
- [ ] E. Auctions exist only for derivatives, not equities

### 8. Market makers and liquidity
- [ ] A. Market makers generally quote both bid and ask sides
- [ ] B. They can improve market depth and narrow spreads
- [ ] C. One-sided quoting is sufficient to fulfill two-sided obligations
- [ ] D. Quote refresh behavior matters when one side is filled
- [ ] E. Market-maker protection controls can limit fill bursts

### 9. Risk controls before and during trading
- [ ] A. Pre-trade checks can reject orders before matching
- [ ] B. Price collars help block clearly erroneous prices
- [ ] C. Circuit breakers can pause trading during extreme moves
- [ ] D. Kill switch functionality can rapidly reduce exposure
- [ ] E. Risk controls are optional and should never intervene in production markets

### 10. Self-match prevention (SMP)
- [ ] A. SMP is designed to avoid a participant trading with itself
- [ ] B. SMP can reduce wash-trade risk
- [ ] C. SMP is equivalent to best-execution routing
- [ ] D. SMP policy affects how crossing self-orders are handled
- [ ] E. SMP is irrelevant for compliance monitoring

### 11. Market data vs drop copy
- [ ] A. Public market data is for broad market state dissemination
- [ ] B. Drop copy is a participant-focused shadow record for control and reconciliation
- [ ] C. Both feeds can use sequence numbers for gap detection
- [ ] D. Drop copy is only used for charting, never for operations
- [ ] E. Gap recovery is important when messages are missed

### 12. Clearing and settlement
- [ ] A. Matching creates a trade agreement, not final asset transfer
- [ ] B. Clearing manages obligations and counterparty risk handling
- [ ] C. Settlement is where cash and securities are exchanged
- [ ] D. Trade confirmation means settlement failure is impossible
- [ ] E. Post-trade processes are part of market integrity

### 13. Exchange surveillance and compliance
- [ ] A. Exchanges monitor for abusive patterns
- [ ] B. Audit trails support investigation and accountability
- [ ] C. Surveillance is only needed for dark pools
- [ ] D. Timestamped event records help reconstruct incidents
- [ ] E. Compliance concerns are separate from technology design

### 14. Market fragmentation and routing
- [ ] A. A symbol can trade across multiple venues
- [ ] B. Smart order routing seeks better execution across venues
- [ ] C. Fragmentation can create complexity in best-price discovery
- [ ] D. Fragmentation guarantees identical liquidity everywhere
- [ ] E. NBBO-like concepts exist to aggregate top-of-book information

### 15. Architecture principles of modern exchanges
- [ ] A. Reliability, fairness, and transparency are design priorities
- [ ] B. Low latency matters, but controls and resilience also matter
- [ ] C. Observability and replayability support operations and trust
- [ ] D. Exchange systems should optimize only for speed at any cost
- [ ] E. Risk, matching, and post-trade layers work together as one ecosystem

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
| 1 | A, B, D |
| 2 | A, B, C, E |
| 3 | A, B, C, D |
| 4 | A, B, D, E |
| 5 | A, B, D, E |
| 6 | A, B, D, E |
| 7 | A, B, C, D |
| 8 | A, B, D, E |
| 9 | A, B, C, D |
| 10 | A, B, D |
| 11 | A, B, C, E |
| 12 | A, B, C, E |
| 13 | A, B, D |
| 14 | A, B, C, E |
| 15 | A, B, C, E |
| 16 | C |
| 17 | B |
| 18 | A, C, E |
| 19 | A, B |
| 20 | B |

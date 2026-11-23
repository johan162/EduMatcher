# Exchange Concepts Knowledge Check — Variant 08

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

### 1. Capital raising and the exchange's role
- [ ] A. A company that self-funds via retained earnings avoids outside obligations but grows more slowly
- [ ] B. A liquid secondary market is described as a precondition that makes primary-market investment attractive
- [ ] C. The secondary market is where a company receives proceeds each time its shares trade
- [ ] D. Underwriters conduct a roadshow to gauge institutional demand before setting the IPO price
- [ ] E. Bonds, unlike shares, never trade on secondary markets once issued

### 2. Market history and language
- [ ] A. "Going short" is traced to a merchant having more inventory than needed to cover a delivery
- [ ] B. The NYSE specialist's paper ledger is the direct ancestor of "the book" in modern systems
- [ ] C. "Blue chip" is traced to a 1923 Dow Jones description of stocks trading at $200 or more
- [ ] D. The Brady Commission's report followed, rather than preceded, the introduction of NYSE's first circuit breakers
- [ ] E. Black Monday, 19 October 1987, saw markets fall roughly 22.6% in one day

### 3. Participants, once more
- [ ] A. Demutualisation is described as converting for-profit exchanges into member-owned mutuals
- [ ] B. A taker is the participant whose incoming order immediately executes against a resting order
- [ ] C. A quote, as distinct from an order, is a two-sided bid/ask instruction from a market maker
- [ ] D. Institutional investors are described as typically trading small, randomly timed orders like retail investors
- [ ] E. Retail order flow is attractive to market makers because it carries little adverse-selection risk

### 4. Real-world exchange facts, once more
- [ ] A. CME Group is described as one of the world's largest futures exchanges
- [ ] B. Every major exchange remains a non-profit, member-owned mutual today
- [ ] C. NYSE's parent company, ICE, is itself listed on NYSE
- [ ] D. Cboe is credited with pioneering the listed options market in 1973
- [ ] E. Eurex is Deutsche Börse's derivatives exchange, while Xetra is its cash-equity trading venue

### 5. Listing, delisting, and alternatives
- [ ] A. Voluntary delisting can occur when a company is taken private
- [ ] B. A direct listing establishes its opening trade through the exchange's normal opening auction mechanism
- [ ] C. A stock closing below $1.00 for 30 consecutive days can trigger a deficiency notice with a cure period
- [ ] D. A SPAC merger is described as requiring the target company to complete its own traditional IPO first
- [ ] E. Spotify's 2018 NYSE listing is cited as a pioneering direct listing

### 6. Order types, comprehensive review
- [ ] A. A trailing stop only ever moves in the direction favourable to the position, freezing otherwise
- [ ] B. An iceberg's replenishment typically retains its original queue priority rather than going to the back
- [ ] C. A stop-limit order trades price certainty for potential non-execution if the market gaps through the limit
- [ ] D. A combo order's legs are matched entirely independently, with no shared execution intent
- [ ] E. A midpoint peg order can offer price improvement to both sides of a trade simultaneously

### 7. TIF, a comprehensive review
- [ ] A. IOC orders can rest in the book awaiting a better price
- [ ] B. DAY orders expire automatically at session end if unfilled
- [ ] C. FOK requires a full, immediate fill or the entire order is rejected
- [ ] D. ATC orders specifically target the price set by the closing auction uncross
- [ ] E. GTC orders must be persisted and reloaded across sessions

### 8. Depth, spread, and market impact, a fresh scenario
*Scenario: the ask side holds $50.00/3,000, $50.05/2,000 and $50.10/1,000, and a 4,000-share market buy sweeps it.*

- [ ] A. Market impact equals the sweep's VWAP minus the initial best ask
- [ ] B. Iceberg reserves have no effect on the relationship between displayed and true available depth
- [ ] C. The sweep's VWAP is (3000×50.00 + 1000×50.05)/4000
- [ ] D. The sweep consumes the first two levels fully and part of the third
- [ ] E. A bid-ask imbalance of exactly 0.5 indicates a perfectly balanced book

### 9. Price-time priority, one more pass
- [ ] A. Pro-rata allocation splits an incoming fill proportionally to resting order size at a price level
- [ ] B. Cancel-and-replace can, in some systems, retain the original order's priority if requested
- [ ] C. A quantity-decrease amendment is the one case that preserves the original timestamp
- [ ] D. CME uses FIFO for its equity index futures products
- [ ] E. A price amendment always assigns a new timestamp, regardless of direction

### 10. Tick sizes, one more pass
- [ ] A. The Tick Size Pilot Program ran for a single trading day in 2016
- [ ] B. Rule 612 prohibits sub-penny quoting in NMS stocks priced at or above $1.00
- [ ] C. Tick size is treated as reference data that can vary by price band, product, and venue
- [ ] D. A price submitted off the valid tick grid is rejected and never enters the book
- [ ] E. Storing prices as integer tick counts avoids the binary floating-point representation problem

### 11. The matching engine, a comprehensive pass
- [ ] A. Single-threaded processing is chosen to guarantee deterministic, auditable outcomes
- [ ] B. A market order that cannot fill immediately rests quietly in the book
- [ ] C. Each symbol has its own logically separate order book
- [ ] D. Sweeping a large order through multiple price levels can generate slippage
- [ ] E. Calendar spreads require the engine to evaluate both legs of the trade together

### 12. Market makers, one more pass
- [ ] A. A maximum-spread obligation could prevent quoting a bid and ask more than a specified number of ticks apart
- [ ] B. MMP protection periods are described as giving the market maker time to reassess before re-quoting
- [ ] C. A market maker earns the spread by buying at the bid and selling at the ask
- [ ] D. A market maker's obligations exist without any corresponding privileges from the exchange
- [ ] E. Cancelling both legs of a quote immediately upon any fill is described as the most conservative refresh policy

### 13. Auctions, one more worked scenario
*Scenario: the auction holds buy orders 1,000 @ $25 and 400 @ $26, and sell orders 900 @ $25 and 300 @ $24.*

- [ ] A. Comparing $25 (1,200 executable) and $26 (400 executable), $25 is the equilibrium price
- [ ] B. The executable volume at $25 is min(1400, 900+300) = 1,200
- [ ] C. The equilibrium price is chosen without regard to how much volume would execute at each candidate
- [ ] D. The seller who asked $24 receives $25 if matched, one dollar better than their ask
- [ ] E. The executable volume at $26 is min(400, 900+300) = 400

### 14. Trading sessions, one more pass
- [ ] A. The session state machine permits transitions not explicitly defined, provided they are logically sound
- [ ] B. GTC orders reloaded at start-of-day are re-acknowledged to their originating participants
- [ ] C. Book state saves provide the starting point for a warm restart
- [ ] D. Intraday auctions can serve illiquid instruments or act as a softer alternative to a full halt
- [ ] E. Pre-open orders accumulate without matching until the opening auction runs

### 15. Indexes, one more pass
- [ ] A. A stock split, on its own, should not change the level of a cap-weighted index
- [ ] B. Free-float weighting excludes shares held by insiders or governments that do not trade
- [ ] C. Index-linked circuit breakers are described as applying to individual stocks rather than the whole market
- [ ] D. The S&P 500's committee-based approach contrasts with mechanically reconstituted families like Russell or FTSE
- [ ] E. Being removed from a major index tends to cause forced selling by index funds

### 16. Pre-trade risk controls, one more pass
- [ ] A. Credit limits require tracking outstanding order commitments as well as settled positions
- [ ] B. Rate limiting is checked using an in-memory, per-gateway counter
- [ ] C. The cheapest checks are deliberately run last to save computation for accepted orders
- [ ] D. A notional value check multiplies order quantity by price to catch decimal-point errors
- [ ] E. A short sale must be marked as such, but no locate is required anywhere in the order's path before it is accepted

### 17. Circuit breakers and collars, one more pass
- [ ] A. LULD varies the trigger band by tier while using a fixed halt duration
- [ ] B. A dynamic price collar compares an order's price to the previous session's official close
- [ ] C. China's 2016 mechanism was withdrawn after only four trading days
- [ ] D. Japan's approach continues trading at the daily limit rather than halting outright
- [ ] E. The US uses three explicit market-wide tiers: 7%, 13%, and 20%

### 18. SMP, kill switch, and mass cancel, one more pass
- [ ] A. A mass cancel requires reconnection and re-authentication before the participant can resume trading
- [ ] B. A kill switch can be triggered automatically upon a lost gateway connection
- [ ] C. Cancel Aggressor is described as the most common default SMP policy
- [ ] D. After a kill switch fires, a participant's connection is typically marked inactive
- [ ] E. Wash trading is illegal under most exchange manipulation regulations

### 19. Clearing, settlement, and margin, one more pass
- [ ] A. Novation makes the CCP the counterparty to both the original buyer and seller
- [ ] B. Maintenance margin breaches trigger a margin call demanding additional collateral
- [ ] C. Variation margin realises gains and losses in cash on a daily basis rather than letting them accumulate silently
- [ ] D. DvP is designed specifically to prevent the kind of failure that produced Herstatt risk
- [ ] E. US equities currently settle T+3

### 20. Trade busting and clearly erroneous trades, one more pass
- [ ] A. A participant typically has a short filing window, commonly around 30 minutes
- [ ] B. Busting reverses positions and cash movements as though the trade never happened
- [ ] C. Review is applied to an entire order as a single unit rather than execution by execution
- [ ] D. The clearly erroneous threshold table widens as the reference price falls into lower bands
- [ ] E. Price adjustment can preserve that a trade occurred while correcting an erroneous print

### 21. Regulatory surveillance, one more pass
- [ ] A. Spoofing involves cancelling orders before they can fill, once their market-moving effect is achieved
- [ ] B. Layering uses multiple orders at various price levels to create a false impression of depth
- [ ] C. The audit trail is required to be complete, immutable, and retained for a defined regulatory period
- [ ] D. The CAT database has been operational in the US since 2020
- [ ] E. A Suspicious Transaction Report is filed only when a regulator specifically requests one

### 22. Knight Capital, comprehensive review
- [ ] A. Knight later merged with Getco LLC to form KCG Holdings
- [ ] B. The incident occurred on a single misconfigured server out of eight deployed
- [ ] C. The incident is described as having no lasting influence on subsequent risk-control regulation
- [ ] D. Every one of Knight's orders was individually valid at the prevailing market price
- [ ] E. Approximately $440 million was lost in roughly 45 minutes

### 23. Technology architecture, comprehensive pass
- [ ] A. Market data commonly travels via UDP multicast while order entry commonly travels via TCP
- [ ] B. The matching engine and gateway are described as sharing an identical release cadence
- [ ] C. CME's MDP3 is based on the SBE (Simple Binary Encoding) standard
- [ ] D. The gateway typically performs authentication and message-format translation
- [ ] E. FIX is text-based; ITCH and OUCH are binary protocols developed by NASDAQ

### 24. Onboarding, resilience, and load balancing
- [ ] A. The sequencing infrastructure of the input queue, not the wall-clock timestamp, is described as what ultimately determines match priority
- [ ] B. Monotonic timestamp enforcement helps prevent a clock jump from assigning a "past" timestamp to a new order
- [ ] C. Partitioning by symbol allows different matching engine instances to scale independently
- [ ] D. Conformance testing verifies a participant's system handles rejections, partial fills, and reconnection correctly
- [ ] E. A single central order-ID counter is described as free of single-point-of-failure risk

### 25. Market data architecture and economics, comprehensive pass
- [ ] A. Conflation is acceptable for display purposes but not for systems needing complete tick data
- [ ] B. A snapshot gives a complete current view of the book; incremental updates describe only changes
- [ ] C. The SEC's Market Data Infrastructure rulemaking sought to expand SIP content and restructure revenue governance
- [ ] D. Exchanges are described as having no financial interest in how competitive the public SIP is relative to their own proprietary feeds
- [ ] E. A proprietary direct feed generally offers lower latency than the consolidated SIP feed

### 26. Latency, co-location, and observability
- [ ] A. Deterministic worst-case latency is described as unimportant compared to average latency
- [ ] B. Co-located servers can reduce round-trip latency to low single-digit microseconds on optimised networks
- [ ] C. PTP achieves sub-microsecond clock synchronisation accuracy
- [ ] D. Symptom-based alerts are generally favoured over cause-based alerts to reduce alert fatigue
- [ ] E. A blameless postmortem is intended to surface causes without individual punishment

### 27. Determinism, persistence, and reference data
- [ ] A. A warm restart from a recent snapshot is typically faster than a full cold start
- [ ] B. A write-ahead log is the source of truth, with in-memory book state treated as derived
- [ ] C. Determinism requires eliminating hidden randomness and mid-execution clock reads from the matching path
- [ ] D. An ISIN identifies a security independent of which specific exchange lists it
- [ ] E. Reference data is generally described as safe to leave unversioned since it changes so rarely

### 28. Corporate actions and options, comprehensive pass
- [ ] A. American-style options can be exercised at any point up to expiry
- [ ] B. A reverse split can serve as a remedy for a minimum-bid-price listing deficiency
- [ ] C. A stock split requires proportional adjustment of resting limit order price and quantity
- [ ] D. Cash settlement is standard for broad index options like SPX rather than physical delivery
- [ ] E. Pin risk arises only for options that are unambiguously deep in-the-money at expiry

### 29. Cryptocurrency and digital assets, comprehensive pass
- [ ] A. A decentralised exchange's AMM replaces order matching with algorithmic pricing from a liquidity pool
- [ ] B. Most crypto markets operate 24/7 without a defined daily open or close
- [ ] C. Core order book and price-time priority concepts are described as carrying over to crypto exchanges
- [ ] D. FTX is presented as an example of institutional separation working correctly to protect customers
- [ ] E. Precision requirements for assets like Bitcoin and Ethereum tokens are described as more demanding than traditional equities

### 30. Final cross-cutting numeric review
- [ ] A. A market maker's loss is $200 if a 400-share position bought at $150.30 is later marked at $149.80
- [ ] B. A 60% deviation from a pre-crash reference price was used as the bust threshold following the 2010 Flash Crash
- [ ] C. VWAP for a position of 100 shares at $150 and 50 shares at $160 is $153.33
- [ ] D. An index with $7,007,100,000,000 aggregate market cap launching at base value 1000 has a divisor near 7.0071 billion
- [ ] E. Knight Capital's inability to stop its runaway system for about 45 minutes is cited as a central failure in that incident

&nbsp;

---

# Exchange Concepts Knowledge Check — Variant 04

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

### 1. Debt vs equity trade-offs
- [ ] A. Preferred stock typically carries stronger voting rights than common stock
- [ ] B. A company's obligation to bondholders is unconditional, absent default
- [ ] C. Retained earnings create no dilution of existing ownership
- [ ] D. Equity dilution means new investors' percentage ownership can exceed what they actually paid for
- [ ] E. Debt investors generally accept lower risk in exchange for a capped, predictable return

### 2. The primary/secondary market cycle
- [ ] A. The primary and secondary markets are described as forming a virtuous, self-reinforcing cycle
- [ ] B. When you buy shares of a company on the secondary market, the seller receives your money, not the company
- [ ] C. Without an exit via the secondary market, investors would be less willing to buy into an IPO
- [ ] D. A liquid secondary market makes investors more willing to commit capital in the primary market
- [ ] E. The exchange is described as helping companies raise money directly on an ongoing basis

### 3. Participant categories
- [ ] A. A broker trades primarily for its own proprietary account
- [ ] B. Institutional investors often route through execution desks using dark pools and smart order routing
- [ ] C. A market maker's resting quotes provide the liquidity that takers consume
- [ ] D. HFT firms typically manage money on behalf of outside clients
- [ ] E. A market maker is simultaneously willing to buy from sellers and sell to buyers

### 4. Regulatory framework
- [ ] A. The FCA regulates UK trading venues and investment firms
- [ ] B. Regulation NMS was phased in gradually through 2007 after its 2005 adoption
- [ ] C. ESMA and national regulators oversee MiFID II compliance in the EU
- [ ] D. Exchanges themselves can act as self-regulatory organisations
- [ ] E. A matching engine with high throughput but an insufficient audit trail is described as a fully working system

### 5. Historic crash mechanics
- [ ] A. The Brady Commission reported to the President in January 1988
- [ ] B. Circuit breaker thresholds have been adjusted multiple times, including after March 2020
- [ ] C. NYSE introduced its first market-wide circuit breakers before the Brady Commission's report
- [ ] D. The 1929 crash led directly to the creation of the SEC via 1930s legislation
- [ ] E. The 1987 crash's feedback loop involved automated portfolio insurance selling

### 6. Round lots and reference data
- [ ] A. The matching engine cannot fill an odd-lot order under any circumstances
- [ ] B. Round lot size is treated as reference data that varies by symbol
- [ ] C. Odd-lot executions were historically fully counted in the NBBO calculation
- [ ] D. Asian markets often require order sizes to be a multiple of a larger minimum lot
- [ ] E. An order for 37 shares where the round lot is 100 is an example of an odd lot

### 7. Iceberg and hidden orders, priority
- [ ] A. Iceberg orders are used by institutional investors on venues such as the LSE and Deutsche Börse
- [ ] B. Showing only a small visible peak reduces the market impact of a large order
- [ ] C. Total book depth can understate true available liquidity when icebergs are present
- [ ] D. An iceberg order is also called a reserve order
- [ ] E. On every exchange, displayed orders always have strict priority over hidden orders regardless of arrival time

### 8. Midpoint peg mechanics, numerically
*Scenario: the best bid is $150.30 and the best ask is $150.35.*

- [ ] A. Both counterparties in a midpoint match are described as sharing the spread rather than each paying it in full
- [ ] B. The mid price is $150.325
- [ ] C. HFT firms and market makers are described as the primary heavy users of midpoint peg orders
- [ ] D. A midpoint peg seller receives $0.025 less than the quoted bid
- [ ] E. A midpoint peg buyer pays $0.025 less than the quoted ask

### 9. OCO, combos, and implied liquidity
- [ ] A. Implied orders can be derived from an outright order and a spread order together
- [ ] B. Preventing double-execution of the same underlying order is a stated engineering challenge for implied matching
- [ ] C. An implied order increases total liquidity in the system beyond what already existed
- [ ] D. A long call butterfly buys one low-strike and one high-strike call and sells two calls at the middle strike
- [ ] E. A straddle combines a long call and a long put at the same strike

### 10. Time-in-force in practice
- [ ] A. IOC and FOK orders can both rest in the book if not fully filled
- [ ] B. A fund manager expecting a specific news date might use GTD to auto-expire unfilled orders
- [ ] C. NYSE's Market-At-Open and Limit-At-Open orders are variants of the ATO time-in-force
- [ ] D. GTD behaves like GTC plus a scheduled expiry task
- [ ] E. ATC orders target the price that emerges from the closing auction uncross

### 11. Depth measures
- [ ] A. Cumulative depth within N ticks estimates how much can trade before the price moves by roughly that many ticks
- [ ] B. Level 1 data and Level 2 data show identical information
- [ ] C. A bid-ask imbalance near 0.0 suggests dominant selling pressure
- [ ] D. Available depth at cost computes the largest order size executable within a maximum acceptable price movement
- [ ] E. Professional traders often subscribe to Level 2 data specifically for near-term price-pressure signals

### 12. Order book prices in play
- [ ] A. The last trade price is what scrolling tickers typically display as the "current price"
- [ ] B. The mid price is used only after a trade occurs, never before
- [ ] C. A static price collar compares a new order's price against the previous closing price
- [ ] D. The mid price is derived from an actual completed transaction
- [ ] E. The previous day's closing price is set through the closing auction

### 13. Priority and pro-rata, a second scenario
- [ ] A. At the same price level, an order's queue position is determined solely by its size
- [ ] B. Options markets sometimes use pro-rata allocation rather than strict FIFO
- [ ] C. Nanosecond timestamps alone are sufficient to guarantee fairness without any further sequencing infrastructure
- [ ] D. Amending a resting order's price is treated the same as a cancel-and-new-order for priority purposes
- [ ] E. CME uses pro-rata allocation for its E-mini S&P 500 and E-mini Nasdaq 100 futures

### 14. Tick size in derivatives and history
- [ ] A. The SEC's Tick Size Pilot Program ran from October 2016 to October 2018
- [ ] B. Fractional quoting on NYSE traced back to the Spanish "piece of eight"
- [ ] C. A one-cent tick is regulatorily mandated for every instrument regardless of price
- [ ] D. The E-mini S&P 500 futures tick is worth $12.50 per contract given its $50 multiplier
- [ ] E. The narrowest fractional tick mentioned for NYSE before decimalisation was a "teenie," or 1/16th of a dollar

### 15. Matching engine architecture
- [ ] A. A doubly-linked list per price level is cited as a classic choice for O(1) append and removal
- [ ] B. Kernel bypass networking can reduce the network stack's added latency per packet
- [ ] C. NUMA awareness involves pinning matching threads to specific cores near their memory
- [ ] D. High-performance engines are described as favouring dynamic memory allocation on the hot path
- [ ] E. Direct indexing by price offset is described as O(1) when applicable

### 16. Trade lifecycle detail
- [ ] A. A partial fill changes an order's status to PARTIAL while it continues resting
- [ ] B. Fill notifications are also referred to as execution reports
- [ ] C. Regulatory reporting can classify trades as buy-initiated or sell-initiated based on the aggressor
- [ ] D. Every trade record omits the identity of the gateways involved, for confidentiality
- [ ] E. The aggressor field can affect fee calculation for a given trade

### 17. Market maker protection, a second scenario
- [ ] A. After MMP activation, a market maker typically must actively decide before re-quoting
- [ ] B. MMP thresholds are described as identical across every product regardless of liquidity
- [ ] C. A market maker who is aggressively bought from repeatedly in milliseconds can accumulate unwanted inventory quickly
- [ ] D. MMP is designed to counter adverse selection occurring at unusually high speed
- [ ] E. MMP is presented as protecting the whole market's liquidity provision, not just the individual firm

### 18. A different equilibrium price scenario
- [ ] A. Indicative uncross prices help participants adjust orders before the actual uncross
- [ ] B. A remaining unmatched sell order priced above the equilibrium price does not execute in the auction
- [ ] C. The equilibrium price is chosen independently of how much volume it would allow to trade
- [ ] D. The auction imbalance figure reflects the surplus of one side over the other at the indicative price
- [ ] E. If buyers are willing to pay $150 or more for 2,300 shares total but sellers at $150 offer only 600 shares, the executable volume at $150 is 600

### 19. Circuit breakers, regional comparison
- [ ] A. Eurex's volatility interruption duration is described as rigidly fixed regardless of price discovery progress
- [ ] B. A narrow gap between thresholds can create an incentive to sell immediately after resumption
- [ ] C. China's January 2016 mechanism used a 5% threshold for a 15-minute halt and a 7% threshold to close for the day
- [ ] D. Japan's daily price limit approach keeps the market open while bounding price movement
- [ ] E. The US uses a fixed 5-minute halt for every market-wide circuit breaker tier

### 20. Trade busting details
- [ ] A. The clearly erroneous review threshold in the document's table widens for lower-priced reference bands
- [ ] B. The Facebook IPO delay in 2012 involved a matching-engine defect rather than any single erroneous order price
- [ ] C. BATS withdrew its own IPO after a software defect affected its own listed stock's price
- [ ] D. Clearly erroneous review exists as a general-purpose mechanism to undo any trade a participant regrets
- [ ] E. A single sweep order can have some individual fills busted while others stand


### 21. Surveillance and the audit trail
- [ ] A. The audit trail is expected to omit rejected orders since they never affect the book
- [ ] B. Exchanges are described as having no legal obligation to file suspicious transaction reports
- [ ] C. Deterministic replay requires the same input sequence to always reproduce identical fills and book state
- [ ] D. Layering and spoofing are described as closely related manipulation patterns
- [ ] E. The Consolidated Audit Trail (CAT) correlates order and trade events by customer account across venues

### 22. Knight Capital, deeper detail
- [ ] A. Knight's losses left it unable to continue on its own capital, requiring an emergency rescue
- [ ] B. The incident had no influence on subsequent MiFID II or SEC rulemaking
- [ ] C. The malfunctioning code was triggered on a single misconfigured server out of eight
- [ ] D. Knight ultimately merged with Getco LLC to form KCG Holdings
- [ ] E. Power Peg bought at the offer and sold at the bid repeatedly, paying the spread each time

### 23. Speed bumps and IEX
- [ ] A. Asymmetric speed bumps can delay aggressive orders while letting cancellations through, protecting liquidity providers from latency arbitrage
- [ ] B. A fixed delay applied equally to all orders eliminates relative timing differences between participants
- [ ] C. IEX became a registered national securities exchange in 2016
- [ ] D. IEX is described as having captured the majority of total US equity trading volume
- [ ] E. IEX's speed bump introduces a fixed delay of approximately 350 microseconds

### 24. Gateway and matching engine separation
- [ ] A. The matching engine is described as optimised for speed rather than for pre-trade safety checks
- [ ] B. The gateway is described as the first system to touch an incoming order in most production architectures
- [ ] C. FIX messages use the SOH control character as the field delimiter on the wire
- [ ] D. Separating pre-trade risk checks from the matching engine is intended to keep the engine fast
- [ ] E. The gateway and matching engine are described as sharing an identical deployment cadence

### 25. Market fragmentation and NBBO
- [ ] A. The NBBO is the best bid and best ask computed across all exchanges
- [ ] B. A locked market occurs when one venue's best bid equals another venue's best ask
- [ ] C. Regulation NMS prohibits venues from trading through a better protected quote displayed on another registered venue
- [ ] D. A crossed market means a venue's bid is actually higher than another venue's ask
- [ ] E. Persistent, deliberate locked or crossed quoting by a venue is described as acceptable under Reg NMS

### 26. Dark pools, PFOF, and fee models
- [ ] A. Under a standard maker-taker model, makers pay a fee and takers receive a rebate
- [ ] B. PFOF is banned in the United Kingdom and, since 30 June 2026, in the European Union
- [ ] C. PFOF involves a wholesale market maker paying a broker for the right to execute client orders internally
- [ ] D. Dark pool orders are typically matched at the midpoint of the NBBO
- [ ] E. An inverted (taker-maker) fee model pays takers a rebate and charges makers a fee

### 27. Execution algorithms
- [ ] A. A TWAP algorithm divides an order evenly across equal time slices regardless of expected volume
- [ ] B. A Percentage of Volume algorithm participates at a fixed percentage of traded market volume
- [ ] C. Execution algorithms are described as generating only a small minority of real-world order flow
- [ ] D. A VWAP algorithm participates proportionally more heavily during expected high-volume periods
- [ ] E. Implementation Shortfall algorithms benchmark against the price at the moment of the investment decision

### 28. Cryptocurrency venues, contrasts
- [ ] A. Precision requirements for digital assets are described as more demanding than traditional tick-size handling
- [ ] B. A single unified global regulator is described as overseeing all crypto exchanges
- [ ] C. Order books and price-time priority concepts are described as carrying over to crypto venues
- [ ] D. Bitcoin's common denomination down to one hundred-millionth of a unit is called a satoshi
- [ ] E. Crypto markets are generally described as operating with fixed daily trading hours like traditional equities

### 29. Corporate actions and their propagation
- [ ] A. A stock split requires adjusting all open limit orders' price and quantity
- [ ] B. A merger typically results in the target company's shares eventually being delisted
- [ ] C. Reference data changes from corporate actions should propagate atomically across dependent systems
- [ ] D. Symbol changes need no special handling if position and order tracking use symbols as keys
- [ ] E. Historical price data is generally adjusted, or marked as pre-split, after a stock split

### 30. Reference data and options settlement
- [ ] A. A disproportionate share of real exchange outages are attributed to bad reference data rather than matching-engine bugs
- [ ] B. A wrongly-loaded contract multiplier can cause every P&L and margin calculation for an instrument to be wrong by the same factor
- [ ] C. Cash settlement is standard for broad-based index options such as SPX
- [ ] D. Physical delivery for a standard US equity option contract involves 100 shares per contract
- [ ] E. Reference data is typically loaded fresh from a database for every single order to guarantee accuracy

&nbsp;

---

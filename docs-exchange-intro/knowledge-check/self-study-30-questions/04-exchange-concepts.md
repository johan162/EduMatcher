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
- [ ] A. Debt investors generally accept lower risk in exchange for a capped, predictable return
- [ ] B. Equity dilution means new investors' percentage ownership can exceed what they actually paid for
- [ ] C. A company's obligation to bondholders is unconditional, absent default
- [ ] D. Preferred stock typically carries stronger voting rights than common stock
- [ ] E. Retained earnings create no dilution of existing ownership

### 2. The primary/secondary market cycle
- [ ] A. A liquid secondary market makes investors more willing to commit capital in the primary market
- [ ] B. The exchange is described as helping companies raise money directly on an ongoing basis
- [ ] C. Without an exit via the secondary market, investors would be less willing to buy into an IPO
- [ ] D. When you buy shares of a company on the secondary market, the seller receives your money, not the company
- [ ] E. The primary and secondary markets are described as forming a virtuous, self-reinforcing cycle

### 3. Participant categories
- [ ] A. Institutional investors often route through execution desks using dark pools and smart order routing
- [ ] B. HFT firms typically manage money on behalf of outside clients
- [ ] C. A market maker is simultaneously willing to buy from sellers and sell to buyers
- [ ] D. NYSE's term for its designated market makers is "Designated Market Makers"
- [ ] E. A broker trades primarily for its own proprietary account

### 4. Regulatory framework
- [ ] A. ESMA and national regulators oversee MiFID II compliance in the EU
- [ ] B. The FCA is the UK's financial regulator mentioned in the document
- [ ] C. Exchanges themselves can act as self-regulatory organisations
- [ ] D. A matching engine with high throughput but an insufficient audit trail is described as a fully working system
- [ ] E. Regulation NMS was phased in gradually through 2007 after its 2005 adoption

### 5. Historic crash mechanics
- [ ] A. The Brady Commission reported to the President in January 1988
- [ ] B. The 1987 crash's feedback loop involved automated portfolio insurance selling
- [ ] C. NYSE introduced its first market-wide circuit breakers before the Brady Commission's report
- [ ] D. Circuit breaker thresholds have been adjusted multiple times, including after March 2020
- [ ] E. The 1929 crash led directly to the creation of the SEC via 1930s legislation

<div style="page-break-after: always;"></div>

### 6. Round lots and reference data
- [ ] A. Asian markets often require order sizes to be a multiple of a larger minimum lot
- [ ] B. Odd-lot executions were historically fully counted in the NBBO calculation
- [ ] C. Round lot size is treated as reference data that varies by symbol
- [ ] D. An order for 37 shares where the round lot is 100 is an example of an odd lot
- [ ] E. The matching engine cannot fill an odd-lot order under any circumstances

### 7. Iceberg and hidden orders, priority
- [ ] A. An iceberg order is also called a reserve order
- [ ] B. Showing only a small visible peak reduces the market impact of a large order
- [ ] C. On every exchange, displayed orders always have strict priority over hidden orders regardless of arrival time
- [ ] D. Total book depth can understate true available liquidity when icebergs are present
- [ ] E. Iceberg orders are used by institutional investors on venues such as the LSE and Deutsche Börse

### 8. Midpoint peg mechanics, numerically
- [ ] A. With a best bid of $150.30 and best ask of $150.35, the mid price is $150.325
- [ ] B. A midpoint peg buyer in that scenario pays $0.025 less than the quoted ask
- [ ] C. A midpoint peg seller in that scenario receives $0.025 less than the quoted bid
- [ ] D. Both counterparties in a midpoint match are described as sharing the spread rather than each paying it in full
- [ ] E. HFT firms and market makers are described as the primary heavy users of midpoint peg orders

### 9. OCO, combos, and implied liquidity
- [ ] A. A straddle combines a long call and a long put at the same strike
- [ ] B. A butterfly options strategy uses three strikes across two legs long and one short
- [ ] C. Implied orders can be derived from an outright order and a spread order together
- [ ] D. An implied order increases total liquidity in the system beyond what already existed
- [ ] E. Preventing double-execution of the same underlying order is a stated engineering challenge for implied matching

### 10. Time-in-force in practice
- [ ] A. A fund manager expecting a specific news date might use GTD to auto-expire unfilled orders
- [ ] B. ATC orders target the price that emerges from the closing auction uncross
- [ ] C. IOC and FOK orders can both rest in the book if not fully filled
- [ ] D. GTD behaves like GTC plus a scheduled cancellation task
- [ ] E. NYSE's Market-At-Open and Limit-At-Open orders are variants of the ATO time-in-force

<div style="page-break-after: always;"></div>

### 11. Depth measures
- [ ] A. Cumulative depth within N ticks estimates how much can trade before the price moves by roughly that many ticks
- [ ] B. A bid-ask imbalance near 0.0 suggests dominant selling pressure
- [ ] C. Available depth at cost computes the largest order size executable within a maximum acceptable price movement
- [ ] D. Level 1 data and Level 2 data show identical information
- [ ] E. Professional traders often subscribe to Level 2 data specifically for near-term price-pressure signals

### 12. Order book prices in play
- [ ] A. The last trade price is what scrolling tickers typically display as the "current price"
- [ ] B. The mid price is derived from an actual completed transaction
- [ ] C. The previous day's closing price is set through the closing auction
- [ ] D. A static price collar compares a new order's price against the previous closing price
- [ ] E. The mid price is used only after a trade occurs, never before

### 13. Priority and pro-rata, a second scenario
- [ ] A. At the same price level, an order's queue position is determined solely by its size
- [ ] B. Amending a resting order's price is treated the same as a cancel-and-new-order for priority purposes
- [ ] C. CME uses pro-rata allocation for its E-mini S&P 500 and E-mini Nasdaq 100 futures
- [ ] D. Options markets sometimes use pro-rata allocation rather than strict FIFO
- [ ] E. Nanosecond timestamps alone are sufficient to guarantee fairness without any further sequencing infrastructure

### 14. Tick size in derivatives and history
- [ ] A. The E-mini S&P 500 futures tick is worth $12.50 per contract given its $50 multiplier
- [ ] B. Fractional quoting on NYSE traced back to the Spanish "piece of eight"
- [ ] C. The narrowest fractional tick mentioned for NYSE before decimalisation was a "teenie," or 1/16th of a dollar
- [ ] D. The SEC's Tick Size Pilot Program ran from October 2016 to October 2018
- [ ] E. A one-cent tick is regulatorily mandated for every instrument regardless of price

### 15. Matching engine architecture
- [ ] A. A doubly-linked list per price level is cited as a classic choice for O(1) append and removal
- [ ] B. Direct indexing by price offset is described as O(1) when applicable
- [ ] C. High-performance engines are described as favouring dynamic memory allocation on the hot path
- [ ] D. NUMA awareness involves pinning matching threads to specific cores near their memory
- [ ] E. Kernel bypass networking can reduce the network stack's added latency per packet

<div style="page-break-after: always;"></div>

### 16. Trade lifecycle detail
- [ ] A. The aggressor field can affect fee calculation for a given trade
- [ ] B. A partial fill changes an order's status to PARTIAL while it continues resting
- [ ] C. Regulatory reporting can classify trades as buy-initiated or sell-initiated based on the aggressor
- [ ] D. Every trade record omits the identity of the gateways involved, for confidentiality
- [ ] E. Fill notifications are also referred to as execution reports

### 17. Market maker protection, a second scenario
- [ ] A. MMP is designed to counter adverse selection occurring at unusually high speed
- [ ] B. A market maker who is aggressively bought from repeatedly in milliseconds can accumulate unwanted inventory quickly
- [ ] C. MMP thresholds are described as identical across every product regardless of liquidity
- [ ] D. After MMP activation, a market maker typically must actively decide before re-quoting
- [ ] E. MMP is presented as protecting the whole market's liquidity provision, not just the individual firm

### 18. A different equilibrium price scenario
- [ ] A. If buyers are willing to pay $150 or more for 2,300 shares total but sellers at $150 offer only 600 shares, the executable volume at $150 is 600
- [ ] B. The equilibrium price is chosen independently of how much volume it would allow to trade
- [ ] C. A remaining unmatched sell order priced above the equilibrium price does not execute in the auction
- [ ] D. Indicative uncross prices help participants adjust orders before the actual uncross
- [ ] E. The auction imbalance figure reflects the surplus of one side over the other at the indicative price

### 19. Circuit breakers, regional comparison
- [ ] A. The US uses a fixed 5-minute halt for every market-wide circuit breaker tier
- [ ] B. Japan's daily price limit approach keeps the market open while bounding price movement
- [ ] C. China's January 2016 mechanism used a 5% threshold for a 15-minute halt and a 7% threshold to close for the day
- [ ] D. A narrow gap between thresholds can create an incentive to sell immediately after resumption
- [ ] E. Eurex's volatility interruption duration is described as rigidly fixed regardless of price discovery progress

<div style="page-break-after: always;"></div>

### 20. Trade busting details
- [ ] A. The clearly erroneous review threshold in the document's table widens for lower-priced reference bands
- [ ] B. A single sweep order can have some individual fills busted while others stand
- [ ] C. The Facebook IPO delay in 2012 involved a matching-engine defect rather than any single erroneous order price
- [ ] D. BATS withdrew its own IPO after a software defect affected its own listed stock's price
- [ ] E. Clearly erroneous review exists as a general-purpose mechanism to undo any trade a participant regrets


### 21. Surveillance and the audit trail
- [ ] A. The Consolidated Audit Trail (CAT) correlates order and trade events by customer account across venues
- [ ] B. Exchanges are described as having no legal obligation to file suspicious transaction reports
- [ ] C. Deterministic replay requires the same input sequence to always reproduce identical fills and book state
- [ ] D. Layering and spoofing are described as closely related manipulation patterns
- [ ] E. The audit trail is expected to omit rejected orders since they never affect the book

### 22. Knight Capital, deeper detail
- [ ] A. The malfunctioning code was triggered on a single misconfigured server out of eight
- [ ] B. Power Peg bought at the offer and sold at the bid repeatedly, paying the spread each time
- [ ] C. Knight's losses were roughly equal to the firm's total pre-incident equity capital
- [ ] D. Knight ultimately merged with Getco LLC to form KCG Holdings
- [ ] E. The incident had no influence on subsequent MiFID II or SEC rulemaking

### 23. Speed bumps and IEX
- [ ] A. IEX's speed bump introduces a fixed delay of approximately 350 microseconds
- [ ] B. A fixed delay applied equally to all orders eliminates relative timing differences between participants
- [ ] C. IEX became a registered national securities exchange in 2016
- [ ] D. Speed bumps can be applied selectively to cancel messages to counter last-look practices
- [ ] E. IEX is described as having captured the majority of total US equity trading volume

### 24. Gateway and matching engine separation
- [ ] A. The gateway is described as the first system to touch an incoming order in most production architectures
- [ ] B. Separating pre-trade risk checks from the matching engine is intended to keep the engine fast
- [ ] C. The gateway and matching engine are described as sharing an identical deployment cadence
- [ ] D. FIX messages use the SOH control character as the field delimiter on the wire
- [ ] E. The matching engine is described as optimised for speed rather than for pre-trade safety checks

### 25. Market fragmentation and NBBO
- [ ] A. The NBBO is the best bid and best ask computed across all exchanges
- [ ] B. A locked market occurs when one venue's best bid equals another venue's best ask
- [ ] C. A crossed market means a venue's bid is actually higher than another venue's ask
- [ ] D. Regulation NMS requires orders to trade at the best available price across registered venues
- [ ] E. Persistent, deliberate locked or crossed quoting by a venue is described as acceptable under Reg NMS

### 26. Dark pools, PFOF, and fee models
- [ ] A. Dark pool orders are typically matched at the midpoint of the NBBO
- [ ] B. PFOF involves a wholesale market maker paying a broker for the right to execute client orders internally
- [ ] C. PFOF is currently banned in the United Kingdom and European Union
- [ ] D. Under a standard maker-taker model, makers pay a fee and takers receive a rebate
- [ ] E. An inverted (taker-maker) fee model pays takers a rebate and charges makers a fee

### 27. Execution algorithms
- [ ] A. A VWAP algorithm participates proportionally more heavily during expected high-volume periods
- [ ] B. A TWAP algorithm divides an order evenly across equal time slices regardless of expected volume
- [ ] C. Implementation Shortfall algorithms benchmark against the price at the moment of the investment decision
- [ ] D. A Percentage of Volume algorithm participates at a fixed percentage of traded market volume
- [ ] E. Execution algorithms are described as generating only a small minority of real-world order flow

### 28. Cryptocurrency venues, contrasts
- [ ] A. Order books and price-time priority concepts are described as carrying over to crypto venues
- [ ] B. Crypto markets are generally described as operating with fixed daily trading hours like traditional equities
- [ ] C. A single unified global regulator is described as overseeing all crypto exchanges
- [ ] D. Bitcoin's common denomination down to one hundred-millionth of a unit is called a satoshi
- [ ] E. Precision requirements for digital assets are described as more demanding than traditional tick-size handling

<div style="page-break-after: always;"></div>

### 29. Corporate actions and their propagation
- [ ] A. A stock split requires adjusting all open limit orders' price and quantity
- [ ] B. Reference data changes from corporate actions should propagate atomically across dependent systems
- [ ] C. A merger typically results in the target company's shares eventually being delisted
- [ ] D. Symbol changes need no special handling if position and order tracking use symbols as keys
- [ ] E. Historical price data is generally adjusted, or marked as pre-split, after a stock split

### 30. Reference data and options settlement
- [ ] A. A disproportionate share of real exchange outages are attributed to bad reference data rather than matching-engine bugs
- [ ] B. Reference data is typically loaded fresh from a database for every single order to guarantee accuracy
- [ ] C. Cash settlement is standard for broad-based index options such as SPX
- [ ] D. Physical delivery for a standard US equity option contract involves 100 shares per contract
- [ ] E. A wrongly-loaded contract multiplier can cause every P&L and margin calculation for an instrument to be wrong by the same factor

&nbsp;

---

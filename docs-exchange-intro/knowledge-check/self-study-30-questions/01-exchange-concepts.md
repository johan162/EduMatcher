# Exchange Concepts Knowledge Check — Variant 01

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

### 1. Raising capital before the exchange
- [ ] A. Retained earnings involve no outside parties and no repayment obligation
- [ ] B. A bond's coupon rate is fixed regardless of the issuer's creditworthiness at issuance
- [ ] C. Preferred stockholders are paid before common stockholders but after bondholders
- [ ] D. Dilution means existing owners hold a smaller fraction of a now-larger company
- [ ] E. Equity upside is capped at the value of the most recent dividend

### 2. Primary vs secondary market, numerically
- [ ] A. A founder who owned 100% of a $1,000,000 company and sells a 20% stake for $250,000 now owns 80% of a company worth $1,250,000
- [ ] B. In that scenario, the founder's absolute stake value is unchanged at $1,000,000
- [ ] C. The new investors own exactly what they paid, $250,000
- [ ] D. Buying AAPL shares on NASDAQ today sends cash to Apple Inc.
- [ ] E. A bond issuance is a primary-market transaction

### 3. Market participants
- [ ] A. Retail order flow is generally considered uninformed and therefore attractive to serve
- [ ] B. HFT firms are estimated to account for roughly half of US equity trading volume
- [ ] C. A prime broker's services can include securities lending and consolidated custody
- [ ] D. A "taker" is the participant whose resting order gets filled
- [ ] E. Most major exchanges remain member-owned mutuals today

### 4. Real-world exchanges
- [ ] A. IEX began as a dark pool before becoming a registered national securities exchange in 2016
- [ ] B. CME Group uses pro-rata allocation for every product it lists, including equity index futures
- [ ] C. Eurex runs a formal Market Making Programme with contractual quoting obligations
- [ ] D. JPX was formed by merging the Tokyo and Osaka exchanges
- [ ] E. NASDAQ launched as a purely electronic market with no floor specialists

### 5. Listing and delisting
- [ ] A. A stock closing below $1.00 for 30 consecutive trading days can trigger a deficiency notice
- [ ] B. A reverse stock split raises the nominal share price without changing the company's market value
- [ ] C. In a direct listing, new shares are issued and an underwriter guarantees the offer price
- [ ] D. A SPAC is an operating company that completes its own traditional IPO
- [ ] E. Voluntary delisting can occur when a company is taken private

<div style="page-break-after: always;"></div>

### 6. Origins of market language
- [ ] A. The word "broker" traces back to a term for someone who broaches and sells wine retail
- [ ] B. "Going short" derives from a merchant lacking enough inventory to cover a delivery promise
- [ ] C. The specialist's paper ledger is the direct historical ancestor of "the book"
- [ ] D. The ticker tape got its name from the ticking sound of the telegraph printer
- [ ] E. "Bull" and "bear" market terminology first appeared in the 20th century

### 7. Short selling mechanics
- [ ] A. A short seller must arrange a locate before selling shares they do not own
- [ ] B. Naked short selling means selling without a valid locate and is generally illegal
- [ ] C. Borrow rates are typically highest for the most liquid, easy-to-borrow large-cap stocks
- [ ] D. A lender can recall borrowed shares at any time with short notice
- [ ] E. The matching engine treats a short sale identically to any other sell order at the book level

### 8. Limit orders and price improvement
- [ ] A. A buy limit order can execute at a price better than its own limit price
- [ ] B. A sell limit at $150.25 crossing a $150.30 bid fills at $150.30
- [ ] C. A limit order's price is a ceiling for a buyer and a floor for a seller
- [ ] D. Resting limit orders are also called aggressive orders
- [ ] E. Price improvement statistics are reported by brokers under SEC Rule 605

### 9. Market and stop orders
- [ ] A. Market orders can rest in the book if no immediate counterparty is available
- [ ] B. A buy stop triggers when the price rises to the stop level
- [ ] C. A trailing stop's ratchet can move the stop price in both directions as the market fluctuates
- [ ] D. A trailing stop is a resting limit order competing for queue position
- [ ] E. When triggered, a trailing stop converts into a market order

### 10. Iceberg and midpoint orders
- [ ] A. An iceberg order's hidden reserve is fully visible to other market participants
- [ ] B. Each iceberg replenishment typically receives a fresh timestamp at the back of the queue
- [ ] C. A midpoint peg order displays its price openly in the visible book
- [ ] D. A midpoint peg buyer and seller can both receive a better price than the quoted ask and bid respectively
- [ ] E. Midpoint peg orders guarantee execution because they trade at a favourable price

<div style="page-break-after: always;"></div>

### 11. OCO, combo, and implied orders
- [ ] A. In an OCO pair, if one order fills the other is automatically cancelled
- [ ] B. A combo order executes all of its legs as entirely separate, unrelated trades
- [ ] C. Leg risk refers to the danger that one leg of a combo fills while the other does not
- [ ] D. Implied orders create genuinely new liquidity that did not exist in any other book
- [ ] E. An implied order can be derived by combining a spread order with an outright order

### 12. Time-in-force
- [ ] A. A DAY order is automatically cancelled at the end of the current session if unfilled
- [ ] B. GTC orders must be persisted to durable storage between sessions
- [ ] C. An IOC order can rest in the book if it is not immediately and fully filled
- [ ] D. FOK requires the entire order to fill immediately or the whole order is cancelled
- [ ] E. ATC orders submitted after the closing auction has run are accepted into the next day's opening auction

### 13. The order book and depth
- [ ] A. The spread is the difference between the best bid and the best ask
- [ ] B. Level 1 data shows the full depth of every resting price level
- [ ] C. A bid-ask imbalance value near 1.0 suggests heavier buying interest than selling interest
- [ ] D. The order book only contains orders that have already traded
- [ ] E. An iceberg's hidden reserve can make total book depth appear smaller than actual available liquidity

### 14. Market impact calculation
- [ ] A. Given asks of 2,000 @ $150.35, 1,500 @ $150.40, and 1,500 @ $150.45, a 5,000-share buy sweep has a VWAP of $150.395
- [ ] B. In that same scenario, the market impact relative to the initial best ask is $0.045 per share
- [ ] C. Cumulative depth within N ticks measures how much can be traded before moving the price by roughly that many ticks
- [ ] D. A deep, resilient book requires a single large order to sweep through many levels to fill
- [ ] E. Available depth at cost is the inverse calculation of estimating market impact for a target size

### 15. Price-time priority
- [ ] A. At the same price, the order that arrived earlier is filled first
- [ ] B. Amending a resting order's quantity downward causes it to lose queue priority
- [ ] C. Amending a resting order's price upward causes it to receive a new timestamp
- [ ] D. Under pro-rata allocation, a larger resting order receives a larger proportional share of an incoming fill
- [ ] E. CME uses FIFO for its equity index futures while using pro-rata for some interest-rate futures

<div style="page-break-after: always;"></div>

### 16. Tick sizes
- [ ] A. Storing prices as integer tick counts avoids floating-point representation errors
- [ ] B. Rule 612 of Regulation NMS permits sub-penny quoting for any stock priced above $1.00
- [ ] C. The London Stock Exchange's tick regime uses smaller absolute increments for lower-priced stocks
- [ ] D. The SEC's Tick Size Pilot Program found clear evidence that wider ticks improved small-cap liquidity
- [ ] E. A true midpoint between $150.30 and $150.33 is not always a valid tick-aligned price

### 17. The matching engine
- [ ] A. Most production matching engines are single-threaded to guarantee deterministic outcomes
- [ ] B. Single-threaded design is primarily a performance limitation rather than a deliberate choice
- [ ] C. Each tradeable symbol typically has its own independent order book
- [ ] D. Calendar spread orders require the engine to evaluate both legs together
- [ ] E. A market buy order that sweeps multiple price levels pays a single uniform price across the whole order

### 18. Order status lifecycle
- [ ] A. A REJECTED order never entered the book
- [ ] B. A PARTIAL order has had at least one fill but is not yet fully satisfied
- [ ] C. An EXPIRED status can result from a GTD order reaching its expiry date unfilled
- [ ] D. A CANCELLED order can never have had a prior fill
- [ ] E. A rejected order has no position impact for clearing purposes

### 19. Market maker obligations and adverse selection
- [ ] A. A market maker must maintain a live bid and ask simultaneously under two-sided quoting obligations
- [ ] B. Quoting only 50 shares when the minimum required size is 200 shares satisfies the obligation
- [ ] C. If a market maker buys 500 shares at $150.30 and the true price falls to $150.10, the loss is $100
- [ ] D. In that same scenario, the half-spread revenue on the fill was $25
- [ ] E. Market Maker Protection automatically cancels quotes once a configured fill-rate threshold is exceeded

### 20. Quote refresh policies
- [ ] A. Eurex-style inactivation cancels both sides of a quote the moment either leg fills
- [ ] B. Leaving both quote sides active after a fill is the most conservative refresh policy
- [ ] C. Cancelling only the filled side and leaving the other active can leave a stale quote in a moving market
- [ ] D. Refresh policy is generally configurable per market maker per product
- [ ] E. A re-quoting obligation requires a fresh quote within a specified maximum delay after a fill

<div style="page-break-after: always;"></div>

### 21. The opening auction, equilibrium price
- [ ] A. Given buy orders of 500@$152, 1,000@$151, 800@$150 and sell orders of 600@$150, 900@$151, 800@$152, the equilibrium price is $151
- [ ] B. At that equilibrium price, 1,500 shares execute
- [ ] C. A buyer who bid $152 in that scenario pays $152, not $151
- [ ] D. The 800-share sell order at $152 executes in full at the equilibrium price
- [ ] E. The equilibrium price is chosen to maximise total executable volume

### 22. Auction tie-breaking and mechanics
- [ ] A. If two candidate prices yield equal executable volume, the algorithm first tries to minimise the resulting imbalance
- [ ] B. An indicative uncross price is only published after the auction has already uncrossed
- [ ] C. NYSE publishes closing auction imbalance information before the final uncross
- [ ] D. All matched auction participants trade at their own individual limit prices rather than one common price
- [ ] E. The closing auction can account for a substantial share of a stock's total daily volume

### 23. Trading sessions and the state machine
- [ ] A. A market can transition directly from PRE_OPEN to CLOSED without any intermediate state
- [ ] B. GTC orders unfilled at the end of a session must be persisted for reload the next session
- [ ] C. An intraday auction is mechanically similar to the opening and closing auctions
- [ ] D. After a circuit-breaker halt, trading typically resumes via continuous matching with no resumption auction
- [ ] E. End-of-day batch processes include publishing the official closing price and generating clearing reports

### 24. Index weighting and the divisor
- [ ] A. In a price-weighted index, a $400 stock moves the index more than a $100 stock regardless of company size
- [ ] B. Market-capitalisation weighting is the methodology used by most modern serious indexes
- [ ] C. A stock split, on its own, should permanently change an index's level once absorbed
- [ ] D. If three constituents have a combined market cap of $7,007,100,000,000 and the index launches at 1000, the divisor is 7,007,100,000
- [ ] E. The divisor is rescaled after a corporate action so the index level does not jump for a non-price reason

<div style="page-break-after: always;"></div>

### 25. Index inclusion and integrity
- [ ] A. Index funds are contractually obliged to buy a newly added constituent regardless of price
- [ ] B. Tesla's 2020 S&P 500 addition is cited as an example of the index inclusion effect
- [ ] C. Index calculation is typically embedded directly inside the matching engine to minimise latency
- [ ] D. Market-wide circuit breakers in the US are triggered by the S&P 500 index, not a single stock
- [ ] E. Passive investing concentration is described as a potential source of regulatory concern

### 26. Pre-trade risk controls
- [ ] A. A notional limit check multiplies quantity by price to catch decimal-point errors
- [ ] B. Position limits and credit limits measure exactly the same thing
- [ ] C. Rate limiting protects the exchange from a flood of orders in a short time window
- [ ] D. Short sale flag checks are unrelated to Regulation SHO
- [ ] E. Cheaper checks, like format validation, are typically run before expensive ones, like position checks

### 27. Circuit breakers, US and global
- [ ] A. A Level 1 US market-wide halt is triggered by a 7% S&P 500 decline and lasts 15 minutes
- [ ] B. A Level 3 US market-wide halt ends trading for the remainder of the day
- [ ] C. LULD varies the halt duration by instrument tier rather than varying the trigger band
- [ ] D. China's January 2016 circuit breaker was suspended after only four trading days
- [ ] E. Japan uses continuous daily price limits rather than discrete trading halts

### 28. Clearing, margin, and settlement
- [ ] A. Through novation, the CCP becomes the buyer to every seller and the seller to every buyer
- [ ] B. Variation margin is settled in cash on a daily basis to reflect mark-to-market moves
- [ ] C. If you are long 10,000 shares bought at $150 and the close falls to $145, your variation margin debit is $50,000
- [ ] D. DvP allows securities to transfer even if the corresponding cash has not yet been confirmed
- [ ] E. Herstatt risk describes the danger that one leg of a settlement completes while the other fails

<div style="page-break-after: always;"></div>

### 29. Trade busting and market abuse
- [ ] A. Clearly erroneous review is applied trade-by-trade rather than to an entire order
- [ ] B. Knight Capital's individual executions were mostly found to be clearly erroneous trades
- [ ] C. Spoofing involves placing orders with genuine intent to trade that are simply cancelled early
- [ ] D. The 2010 Flash Crash saw exchanges bust trades that moved more than 60% from the pre-crash reference price
- [ ] E. Layering involves multiple orders placed on one side of the book to create a false impression of depth

### 30. Technology architecture
- [ ] A. FIX order submission typically uses TCP while live market data typically uses UDP multicast
- [ ] B. ITCH messages use fixed binary offsets rather than text field parsing
- [ ] C. A locked market occurs when the best bid on one venue equals the best ask on another
- [ ] D. Payment for order flow is banned in the United Kingdom and the European Union under MiFID II
- [ ] E. Maker-taker fee models charge the maker a fee and pay the taker a rebate

&nbsp;

---

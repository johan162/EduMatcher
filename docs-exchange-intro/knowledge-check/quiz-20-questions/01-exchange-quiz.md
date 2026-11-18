# Exchange Concepts Knowledge Check — Variant 01

Purpose: verify that the student has read [How a Financial Exchange Works](../how-exchange-works.md) and internalized the core principles of a modern exchange, across its full scope — market history, order mechanics, risk and compliance, and technology infrastructure.

## Name/ID

&nbsp;

---


&nbsp;

## Instructions

- There are 20 questions.
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

### 1. Debt and equity, fundamentals
- [ ] A. Preferred stockholders are typically paid before common stockholders but after bondholders
- [ ] B. A share's theoretical upside is capped at the bond coupon rate
- [ ] C. Retained earnings involve outside parties and create repayment obligations
- [ ] D. Bondholders are paid before shareholders in a bankruptcy
- [ ] E. Equity holders have no guaranteed repayment obligation from the company

### 2. IPOs and the primary/secondary market
- [ ] A. The stock exchange is itself the primary market
- [ ] B. When you buy AAPL shares on NASDAQ today, Apple receives the money
- [ ] C. In an IPO, proceeds from newly issued shares go to the company
- [ ] D. A liquid secondary market makes investors more willing to buy into a primary offering
- [ ] E. A bond issuance is a secondary-market transaction

### 3. Market language and what it means
- [ ] A. The ticker got its name because it displayed prices in real time on a screen
- [ ] B. The bid-ask spread is what a taker pays for immediate execution, and it is the foundation of the market maker's business model
- [ ] C. Being "short" originally meant being short of the asset: committed to deliver something not yet held
- [ ] D. "The book" derives from the physical ledger kept by NYSE floor specialists
- [ ] E. A "blue chip" stock is formally defined today as one trading at $200 a share or more


### 4. What an exchange is for
- [ ] A. Off-exchange venues handle only a negligible share of US equity volume
- [ ] B. A liquid secondary market makes investors more willing to fund companies in the primary market, because they know they can exit
- [ ] C. Clear rules on who trades with whom, at what price and in what order are part of what makes a marketplace an exchange
- [ ] D. When shares change hands on the exchange, the issuing company receives the proceeds of each trade
- [ ] E. An exchange brings buyers and sellers to one place under agreed rules, so that a single visible price reflects their combined interest

### 5. The US/EU regulatory landscape
- [ ] A. Reg SHO governs short sales, including the locate requirement
- [ ] B. MiFID II mandates algorithmic trading controls, including kill switch testing, in the EU
- [ ] C. Reg NMS's Order Protection Rule prohibits a venue from trading through a better displayed quote on another registered venue
- [ ] D. The Market Access Rule (15c3-5) applies only to exchanges, not to the broker-dealers that give clients access to them
- [ ] E. Reg NMS helped shape a US market with more than a dozen registered equity exchanges competing for order flow

<div style="page-break-after: always;"></div>

### 6. Real-world exchanges
- [ ] A. CME Group uses only price-time priority for every product it lists
- [ ] B. Price-time priority is the default allocation rule on NYSE, NASDAQ, CME, Eurex and LSE
- [ ] C. NYSE handles the majority (over 50%) of all US equity trading volume
- [ ] D. IEX became a registered national securities exchange in 2016, after starting as a dark pool
- [ ] E. NASDAQ launched as a purely electronic market, with no floor traders or Designated Market Makers

### 7. Listing and delisting mechanics
- [ ] A. A SPAC is an operating business that already holds a completed merger when it IPOs
- [ ] B. Delisted shares can never be traded again anywhere
- [ ] C. A reverse stock split increases a company's total market capitalization
- [ ] D. In a classic direct listing, no new shares are issued and there is no underwriter price guarantee
- [ ] E. A stock trading below $1.00 for 30 consecutive days typically triggers a deficiency notice

### 8. Iceberg, midpoint, OCO, and combo orders
- [ ] A. A midpoint peg order can offer price improvement to both the buyer and the seller simultaneously
- [ ] B. An iceberg order typically loses queue priority each time its hidden reserve replenishes the visible peak
- [ ] C. Implied orders in futures markets represent liquidity synthesized from existing orders in other books, not brand-new liquidity
- [ ] D. A combo (spread) order eliminates all risk of an unfilled leg
- [ ] E. An OCO order pair automatically cancels the other leg once one leg fills or is cancelled

### 9. IOC vs FOK
- [ ] A. A FOK order either fills completely on arrival or is cancelled without any fill
- [ ] B. IOC requires the entire order to fill immediately or it is cancelled in full
- [ ] C. FOK allows partial fills, with the remainder cancelled
- [ ] D. IOC can carry a limit price and fills as much as is immediately possible, cancelling the remainder
- [ ] E. Both IOC and FOK orders can rest in the book if not immediately filled

### 10. Price-time priority and amendments
- [ ] A. CME uses pro-rata allocation for some interest-rate futures while using FIFO for its equity index futures
- [ ] B. Pro-rata allocation distributes fills based on arrival time rather than order size
- [ ] C. Changing an order's price always preserves its original timestamp priority
- [ ] D. Increasing an order's quantity causes it to lose its queue priority
- [ ] E. Decreasing an order's quantity typically preserves its existing queue priority

<div style="page-break-after: always;"></div>

### 11. Opening and closing auctions
- [ ] A. The equilibrium price is chosen to maximise the total buy quantity entered, regardless of sell interest
- [ ] B. All matched auction orders execute at one single price rather than sweeping through multiple price levels
- [ ] C. The opening auction accumulates orders without matching them until a single uncrossing price is calculated
- [ ] D. A buyer who bid above the equilibrium price still only pays the equilibrium price
- [ ] E. The closing auction on NYSE can account for a large share of a stock's total daily volume, compressed into seconds

### 12. The trading session state machine
- [ ] A. The session state machine only allows a fixed set of defined transitions, not arbitrary jumps
- [ ] B. Continuous trading is the only state in which orders may be accepted
- [ ] C. A market can move directly from PRE_OPEN to CLOSED without passing through any other state
- [ ] D. Once a market enters CLOSED, it can revert directly back to CONTINUOUS trading later the same day
- [ ] E. A halted market can transition to a resumption auction before returning to continuous trading

### 13. Indexes
- [ ] A. Most modern serious indexes, including the S&P 500, are market-capitalization weighted
- [ ] B. The DJIA is a price-weighted index, where higher-priced stocks move the index more, regardless of company size
- [ ] C. An index's divisor is adjusted after corporate actions so the index level doesn't jump for reasons unrelated to genuine value change
- [ ] D. S&P 500 inclusion requires committee approval, unlike some mechanically-reconstituted index families
- [ ] E. Being added to the S&P 500 has no measurable effect on a stock's price, since inclusion is purely administrative

### 14. LULD vs market-wide circuit breakers
- [ ] A. LULD trigger bands vary the halt duration depending on how severe the price move is
- [ ] B. LULD applies a fixed-duration trading pause once a stock stays in a limit state at its band for a defined monitoring window
- [ ] C. Market-wide circuit breakers apply identical percentage thresholds and durations to every individual stock
- [ ] D. LULD bands become narrower during the first and last minutes of the trading session
- [ ] E. LULD and market-wide circuit breakers are actually the same regulatory mechanism under a different name

<div style="page-break-after: always;"></div>

### 15. Circuit-breaker design lessons
- [ ] A. The US uses wider gaps between circuit-breaker thresholds, partly to avoid the panic-selling dynamic seen in China
- [ ] B. The narrow gap between China's 5% and 7% thresholds encouraged investors to sell immediately after resumption to beat the second halt
- [ ] C. China's 2016 circuit-breaker mechanism was suspended after only four trading days
- [ ] D. China's circuit-breaker mechanism has remained in continuous, unmodified use since its introduction
- [ ] E. Japan's exchange uses fixed-duration trading pauses rather than continuous daily price limits

### 16. Knight Capital, August 2012
- [ ] A. The incident was triggered by dormant legacy code that was reactivated on a single misconfigured server
- [ ] B. A lack of firm-wide position/notional limits was cited as a root cause
- [ ] C. Knight Capital lost approximately $440 million in about 45 minutes
- [ ] D. The incident led to Knight later merging with another firm before eventually being acquired by Virtu Financial
- [ ] E. Every order Knight's system sent was rejected by NYSE's pre-trade risk checks, which is why losses accumulated

### 17. Mass cancel vs kill switch
- [ ] A. A mass cancel can be initiated only by the participant, not the exchange
- [ ] B. A kill switch can only ever be triggered manually by the participant, never automatically
- [ ] C. A kill switch leaves the participant's gateway active so they can keep submitting new orders
- [ ] D. A mass cancel always cancels every single order for a participant, with no way to target a subset
- [ ] E. After a kill switch fires, the participant typically must reconnect and re-authenticate before resuming

### 18. Clearing and settlement
- [ ] A. Delivery versus Payment ensures securities and cash transfer only when both are simultaneously available
- [ ] B. Herstatt risk refers to the risk that a matching engine produces a legally invalid trade record
- [ ] C. Novation means the CCP becomes the buyer to every seller and the seller to every buyer
- [ ] D. Variation margin is typically settled in cash on a daily basis to reflect mark-to-market gains and losses
- [ ] E. Matching alone finalizes the transfer of cash and securities between the two original parties

<div style="page-break-after: always;"></div>

### 19. Why reference data matters
- [ ] A. Reference-data changes should propagate to all dependent systems atomically rather than gradually
- [ ] B. Reference data includes identity fields like ticker symbol and ISIN
- [ ] C. A wrongly-loaded contract multiplier can cause every P&L and margin calculation for that instrument to be wrong by the same factor
- [ ] D. Reference data is usually queried from a database for every order, so the engine always sees the latest values
- [ ] E. A disproportionate share of real exchange outages trace back to bad reference data rather than matching-engine bugs

### 20. Options exercise styles
- [ ] A. Assignment is the holder's decision, while exercise is the writer's obligation
- [ ] B. Only American-style options create pre-expiry exercise and assignment risk
- [ ] C. Physical delivery is the standard settlement method for broad-based index options like SPX
- [ ] D. European-style options can be exercised at any time up to expiry
- [ ] E. American-style options can only be exercised on the expiry date itself

&nbsp;

---
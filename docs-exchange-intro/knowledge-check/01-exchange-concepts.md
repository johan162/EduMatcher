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
- [ ] A. Equity holders have no guaranteed repayment obligation from the company
- [ ] B. Bondholders are paid before shareholders in a bankruptcy
- [ ] C. A share's theoretical upside is capped at the bond coupon rate
- [ ] D. Retained earnings involve outside parties and create repayment obligations
- [ ] E. Preferred stockholders are typically paid before common stockholders but after bondholders

### 2. IPOs and the primary/secondary market
- [ ] A. In an IPO, proceeds from newly issued shares go to the company
- [ ] B. When you buy AAPL shares on NASDAQ today, Apple receives the money
- [ ] C. The stock exchange is itself the primary market
- [ ] D. A liquid secondary market makes investors more willing to buy into a primary offering
- [ ] E. A bond issuance is a secondary-market transaction

### 3. Origins of market language
- [ ] A. "The book" derives from the physical ledger kept by NYSE floor specialists
- [ ] B. NASDAQ launched in 1971 as the world's first electronic stock market
- [ ] C. "Going long" originates from a merchant's inventory lasting through time in a warehouse
- [ ] D. The term "blue chip" originated from a 1923 Dow Jones description of stocks trading at $200+/share
- [ ] E. The ticker got its name because it displayed prices in real time on a screen


### 4. Wall Street
- [ ] A. Wall Street is named after a stone fortress built by the British Navy
- [ ] B. Wall Street is named after a wooden palisade wall built by Dutch colonists in 1653
- [ ] C. Wall Street was the original site of the NASDAQ building
- [ ] D. Wall Street refers to a wall built around the NYSE trading floor in 1792
- [ ] E. Wall Street's name has no verified historical origin

### 5. The US/EU regulatory landscape
- [ ] A. Reg NMS requires equity orders receive the nationally best available price across registered venues
- [ ] B. Reg SHO governs short sales, including the locate requirement
- [ ] C. The Market Access Rule (15c3-5) was enacted in response to the 2010 Flash Crash
- [ ] D. MiFID II mandates algorithmic trading controls, including kill switch testing, in the EU
- [ ] E. Reg NMS is the reason the US has more than a dozen registered equity exchanges competing for order flow

<div style="page-break-after: always;"></div>

### 6. Real-world exchanges
- [ ] A. NYSE handles the majority (over 50%) of all US equity trading volume
- [ ] B. NASDAQ launched as a purely electronic market, with no floor traders or Designated Market Makers
- [ ] C. CME Group uses only price-time priority for every product it lists
- [ ] D. IEX became a registered national securities exchange in 2016, after starting as a dark pool
- [ ] E. Cboe invented the listed options market in 1973

### 7. Listing and delisting mechanics
- [ ] A. A stock trading below $1.00 for 30 consecutive days typically triggers a deficiency notice
- [ ] B. A reverse stock split increases a company's total market capitalization
- [ ] C. In a direct listing, no new shares are issued and there is no underwriter price guarantee
- [ ] D. A SPAC is an operating business that already holds a completed merger when it IPOs
- [ ] E. Delisted shares can never be traded again anywhere

### 8. Iceberg, midpoint, OCO, and combo orders
- [ ] A. An iceberg order typically loses queue priority each time its hidden reserve replenishes the visible peak
- [ ] B. A midpoint peg order can offer price improvement to both the buyer and the seller simultaneously
- [ ] C. An OCO order pair automatically cancels the other leg once one leg fills or is cancelled
- [ ] D. A combo (spread) order eliminates all risk of an unfilled leg
- [ ] E. Implied orders in futures markets represent liquidity synthesized from existing orders in other books, not brand-new liquidity

### 9. IOC vs FOK
- [ ] A. IOC requires the entire order to fill immediately or it is cancelled in full
- [ ] B. FOK allows partial fills, with the remainder cancelled
- [ ] C. IOC can carry a limit price and fills as much as is immediately possible, cancelling the remainder
- [ ] D. Both IOC and FOK orders can rest in the book if not immediately filled
- [ ] E. GTD orders automatically convert to IOC at the end of the day

### 10. Price-time priority and amendments
- [ ] A. Increasing an order's quantity causes it to lose its queue priority
- [ ] B. Decreasing an order's quantity typically preserves its existing queue priority
- [ ] C. Changing an order's price always preserves its original timestamp priority
- [ ] D. Pro-rata allocation distributes fills based on arrival time rather than order size
- [ ] E. CME uses pro-rata allocation for some interest-rate futures while using FIFO for its equity index futures

<div style="page-break-after: always;"></div>

### 11. Opening and closing auctions
- [ ] A. The opening auction accumulates orders without matching them until a single uncrossing price is calculated
- [ ] B. The equilibrium price is the price that maximizes the executable matched volume
- [ ] C. A buyer who bid above the equilibrium price still only pays the equilibrium price
- [ ] D. All matched auction orders execute at one single price rather than sweeping through multiple price levels
- [ ] E. The closing auction on NYSE can account for a large share of a stock's total daily volume, compressed into seconds

### 12. The trading session state machine
- [ ] A. A market can move directly from PRE_OPEN to CLOSED without passing through any other state
- [ ] B. A halted market can transition to a resumption auction before returning to continuous trading
- [ ] C. Continuous trading is the only state in which orders may be accepted
- [ ] D. The session state machine only allows a fixed set of defined transitions, not arbitrary jumps
- [ ] E. Once a market enters CLOSED, it can revert directly back to CONTINUOUS trading later the same day

### 13. Indexes
- [ ] A. The DJIA is a price-weighted index, where higher-priced stocks move the index more, regardless of company size
- [ ] B. Most modern serious indexes, including the S&P 500, are market-capitalization weighted
- [ ] C. An index's divisor is adjusted after corporate actions so the index level doesn't jump for reasons unrelated to genuine value change
- [ ] D. Being added to the S&P 500 has no measurable effect on a stock's price, since inclusion is purely administrative
- [ ] E. S&P 500 inclusion requires committee approval, unlike some mechanically-reconstituted index families

### 14. LULD vs market-wide circuit breakers
- [ ] A. LULD trigger bands vary the halt duration depending on how severe the price move is
- [ ] B. LULD applies a fixed-duration trading pause once a price stays outside its band for a defined monitoring window
- [ ] C. Market-wide circuit breakers apply identical percentage thresholds and durations to every individual stock
- [ ] D. LULD and market-wide circuit breakers are actually the same regulatory mechanism under a different name
- [ ] E. LULD bands become narrower during the first and last minutes of the trading session

<div style="page-break-after: always;"></div>

### 15. Circuit-breaker design lessons
- [ ] A. China's 2016 circuit-breaker mechanism was suspended after only four trading days
- [ ] B. The narrow gap between China's 5% and 7% thresholds encouraged investors to sell immediately after resumption to beat the second halt
- [ ] C. Japan's exchange uses fixed-duration trading pauses rather than continuous daily price limits
- [ ] D. The US uses wider gaps between circuit-breaker thresholds, partly to avoid the panic-selling dynamic seen in China
- [ ] E. China's circuit-breaker mechanism has remained in continuous, unmodified use since its introduction

### 16. Knight Capital, August 2012
- [ ] A. The incident was triggered by dormant legacy code that was reactivated on a single misconfigured server
- [ ] B. Knight Capital lost approximately $440 million in about 45 minutes
- [ ] C. Every order Knight's system sent was rejected by NYSE's pre-trade risk checks, which is why losses accumulated
- [ ] D. The incident led to Knight later merging with another firm before eventually being acquired by Virtu Financial
- [ ] E. A lack of firm-wide position/notional limits was cited as a root cause

### 17. Mass cancel vs kill switch
- [ ] A. A kill switch leaves the participant's gateway active so they can keep submitting new orders
- [ ] B. A mass cancel can be initiated only by the participant, not the exchange
- [ ] C. After a kill switch fires, the participant typically must reconnect and re-authenticate before resuming
- [ ] D. A mass cancel always cancels every single order for a participant, with no way to target a subset
- [ ] E. A kill switch can only ever be triggered manually by the participant, never automatically

### 18. Clearing and settlement
- [ ] A. Novation means the CCP becomes the buyer to every seller and the seller to every buyer
- [ ] B. Variation margin is typically settled in cash on a daily basis to reflect mark-to-market gains and losses
- [ ] C. Matching alone finalizes the transfer of cash and securities between the two original parties
- [ ] D. Delivery versus Payment ensures securities and cash transfer only when both are simultaneously available
- [ ] E. Herstatt risk refers to the risk that a matching engine produces a legally invalid trade record

<div style="page-break-after: always;"></div>

### 19. Why reference data matters
- [ ] A. Reference data includes identity fields like ticker symbol and ISIN
- [ ] B. A disproportionate share of real exchange outages trace back to bad reference data rather than matching-engine bugs
- [ ] C. Reference-data changes should propagate to all dependent systems atomically rather than gradually
- [ ] D. A wrongly-loaded contract multiplier can cause every P&L and margin calculation for that instrument to be wrong by the same factor
- [ ] E. Reference data is typically cached aggressively at startup rather than queried per order, for latency reasons

### 20. Options exercise styles
- [ ] A. American-style options can only be exercised on the expiry date itself
- [ ] B. European-style options can be exercised at any time up to expiry
- [ ] C. Only American-style options create pre-expiry exercise and assignment risk
- [ ] D. Physical delivery is the standard settlement method for broad-based index options like SPX
- [ ] E. Assignment is the holder's decision, while exercise is the writer's obligation

&nbsp;

---
# Exchange Concepts Knowledge Check — Variant 02
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

### 1. Order fundamentals
- [ ] A. A market order carries no price field, only symbol, side, and quantity
- [ ] B. Odd-lot orders were historically excluded from the consolidated tape and NBBO calculation
- [ ] C. A round lot is always exactly 1,000 shares, regardless of the stock
- [ ] D. Arrival timestamp on an order is irrelevant to price-time priority
- [ ] E. Recent SEC rules are gradually incorporating odd-lot information into consolidated market-data feeds

### 2. Limit orders and price improvement
- [ ] A. A limit order's stated price is always the exact price at which it executes, never better
- [ ] B. A resting limit buy order can be filled at a price better than its own limit price if the market allows
- [ ] C. Market orders can rest in the book if no immediate match exists
- [ ] D. SEC Rule 605 requires broker-dealers to publish statistics on how often price improvement occurs
- [ ] E. A limit price acts as a target price the engine tries to match exactly

### 3. Stop, stop-limit, and trailing stop orders
- [ ] A. A stop-limit order converts into a limit order once triggered, which can protect price but risks non-execution
- [ ] B. A trailing stop's trigger price automatically ratchets favorably as the market moves in the position's favor
- [ ] C. A stop order remains dormant and invisible in the market until its trigger condition is met
- [ ] D. When a trailing stop fires, it converts into a market order rather than a new resting limit order
- [ ] E. A basic stop order guarantees both the execution and the exact price once triggered

### 4. Fill-or-kill mechanics
- [ ] A. FOK orders require the matching engine to perform a hypothetical "dry-run" check before committing any fills
- [ ] B. FOK orders always fill at least partially before being cancelled
- [ ] C. FOK is a time-in-force exclusively used for GTC orders
- [ ] D. FOK orders can rest in the book if the full quantity isn't available
- [ ] E. FOK and ATC are functionally identical

### 5. Reading the order book
- [ ] A. The bid side of the book is sorted from highest to lowest price
- [ ] B. The ask side of the book is sorted from lowest to highest price
- [ ] C. Level 1 data shows only the best bid and ask, while Level 2 shows the full depth of resting price levels
- [ ] D. Visible book depth can understate true available liquidity when iceberg orders are present
- [ ] E. Bid-ask imbalance near 1.0 indicates heavy buy-side pressure relative to sell-side depth

### 6. Matching-engine design
- [ ] A. Modern matching engines are typically single-threaded per book by deliberate design, not due to a hardware limitation
- [ ] B. Single-threading a book's matching logic supports deterministic, auditable, and legally defensible outcomes
- [ ] C. Each symbol's order book is entirely independent of every other symbol, with no exceptions
- [ ] D. A "sweep" describes an aggressive order working through multiple price levels until filled or its limit is reached
- [ ] E. Matching engines commonly use a single global lock across all symbols to guarantee fairness

### 7. Order status lifecycle
- [ ] A. A REJECTED order was briefly present in the order book before being removed
- [ ] B. A CANCELLED order, unlike a REJECTED one, did exist in the book before being withdrawn
- [ ] C. PARTIAL status means the order has received at least one fill but has remaining unfilled quantity
- [ ] D. EXPIRED and CANCELLED describe exactly the same underlying event, just different labels
- [ ] E. FILLED orders can still receive additional fills afterward

### 8. Market maker obligations
- [ ] A. Two-sided quoting means a market maker must maintain a live bid and ask simultaneously
- [ ] B. Market Maker Protection automatically cancels all of a market maker's quotes if their fill rate exceeds a defined threshold in a rolling window
- [ ] C. Adverse selection describes a market maker systematically trading against better-informed counterparties simply by always being available
- [ ] D. Presence obligations commonly require a market maker to be actively quoting for the entire session with zero exceptions
- [ ] E. Re-quoting obligations require posting a fresh quote within a bounded delay after a fill

### 9. Pro-rata vs FIFO
- [ ] A. Pro-rata allocation distributes fills proportionally to each resting order's size rather than by arrival time
- [ ] B. FIFO allocation distributes fills proportionally to order size
- [ ] C. Pro-rata is the default matching rule on virtually every major exchange
- [ ] D. CME uses FIFO for its interest-rate futures and pro-rata for its equity index futures
- [ ] E. Pro-rata and price-time priority are two names for the same allocation method

<div style="page-break-after: always;"></div>

### 10. Tick sizes
- [ ] A. Prices are typically stored as integer tick counts internally to avoid floating-point representation errors
- [ ] B. Rule 612 of Regulation NMS bans quoting most NMS stocks priced at or above $1.00 in increments finer than a penny
- [ ] C. The SEC's Tick Size Pilot Program found that wider ticks clearly improved liquidity for small-cap stocks, leading to permanent adoption
- [ ] D. Tick size can legitimately vary by price band, by product, and even by listing venue for the same underlying stock
- [ ] E. Decimalization of US markets caused quoted spreads on liquid stocks to roughly double overnight

### 11. Auction mechanics, worked
- [ ] A. During the pre-open accumulation period, incoming orders are accepted but not yet matched
- [ ] B. The equilibrium price is the price that maximizes the minimum of cumulative buy and sell interest that can actually be matched
- [ ] C. A tie-breaking rule can favor minimizing the leftover unmatched imbalance when multiple prices tie for maximum volume
- [ ] D. Indicative uncross prices can be recalculated continuously as new orders arrive during the pre-open period
- [ ] E. NYSE publishes closing-auction imbalance information ahead of the actual close, to give participants time to react

### 12. ATO, ATC, and GTD nuances
- [ ] A. An ATO order that isn't filled during the opening auction automatically converts into a DAY order for the rest of the session
- [ ] B. ATC orders cannot be used to build a position gradually throughout the continuous session the way a DAY order can
- [ ] C. GTD orders are automatically cancelled once their specified expiry date/time is reached, regardless of fill status
- [ ] D. GTC orders are discarded at the end of each session and must be resubmitted the next day
- [ ] E. ATO and ATC orders can be freely submitted at any point during continuous trading

### 13. Trading sessions
- [ ] A. NYSE's continuous trading session runs from 9:30am to 4:00pm Eastern time
- [ ] B. Intraday auctions can serve as a softer alternative to a full trading halt on some exchanges
- [ ] C. Post-close/after-hours trading typically has the same liquidity and spreads as continuous trading
- [ ] D. GTC orders must be persisted to durable storage so they can be reloaded at the next session's pre-open
- [ ] E. End-of-day batch processes commonly include closing-price publication and generation of clearing/surveillance reports

<div style="page-break-after: always;"></div>

### 14. Implied orders
- [ ] A. Removing one of the underlying orders that generates an implied order makes that implied order disappear instantly
- [ ] B. Implied orders create genuinely new liquidity that did not exist anywhere in the market before
- [ ] C. Implied-out combines an outright order with a spread order to derive a synthetic outright in another delivery month
- [ ] D. Implied orders only exist for equities, never for futures markets
- [ ] E. Implied-order chains can nest indefinitely, with no practical depth limit

### 15. Session state machine transitions
- [ ] A. The state machine permits PRE_OPEN to transition to OPENING_AUCTION
- [ ] B. A HALTED state can transition to a RESUMPTION_AUCTION before returning to CONTINUOUS trading
- [ ] C. A HALTED state can also transition directly to CLOSING_AUCTION, given an end-of-day signal
- [ ] D. CLOSED can transition back to PRE_OPEN later the same calendar day if volume was low
- [ ] E. Only CONTINUOUS trading is ever allowed to transition into HALTED

### 16. Trade busting and clearly erroneous trades
- [ ] A. The clearly erroneous execution test is applied trade-by-trade (execution by execution), not to an entire order
- [ ] B. After the 2010 Flash Crash, trades executed more than a specific percentage away from the pre-crash reference price were busted
- [ ] C. Nearly all of Knight Capital's millions of erroneous orders were also ruled "clearly erroneous" trades and busted
- [ ] D. Cancellation/busting voids a trade entirely, while price adjustment preserves the trade but reprices it
- [ ] E. The filing window for a clearly-erroneous claim is commonly around 30 minutes after execution under US rules

### 17. Spoofing and the Sarao case
- [ ] A. Spoofing involves placing large orders with genuine intent to execute them
- [ ] B. Navinder Singh Sarao's layered orders were alleged to have contributed to conditions present during the May 2010 Flash Crash
- [ ] C. Quote stuffing involves flooding an exchange with orders/cancellations to slow down competitors
- [ ] D. Front running means trading only after a public news announcement, never before
- [ ] E. Layering is unrelated to spoofing and involves an entirely different regulatory concept

<div style="page-break-after: always;"></div>

### 18. The Consolidated Audit Trail
- [ ] A. The Consolidated Audit Trail (CAT) has been operational in the US since 2020
- [ ] B. Before CAT, regulators could pull cross-exchange order data instantly from one unified source
- [ ] C. Audit-trail records are generally expected to be retained for around seven years under US rules
- [ ] D. A properly maintained audit trail should allow deterministic replay that reproduces the exact same fills and book state
- [ ] E. Rejected orders are typically excluded from the audit trail, since they never affected the book

### 19. Barings Bank, 1995
- [ ] A. Nick Leeson accumulated a large notional position in Nikkei 225 futures while based in Singapore
- [ ] B. Leeson hid losing positions in an error account nicknamed "88888"
- [ ] C. The 1995 Kobe earthquake contributed to the market move that caused the positions to collapse
- [ ] D. Barings Bank was subsequently sold for a nominal sum after being placed into administration
- [ ] E. A root cause identified was the absence of firm-level position-limit checks and scrutiny of anomalous single-trader activity

### 20. GameStop, January 2021
- [ ] A. The NSCC's increased margin call on brokers during the GameStop squeeze had nothing to do with why Robinhood restricted buying
- [ ] B. Robinhood and other brokers temporarily restricted customers to sell-only trading in the affected stocks for a period during the squeeze
- [ ] C. The GameStop short squeeze was primarily organized by large hedge funds against retail investors
- [ ] D. DTCC's NSCC subsidiary has no role in determining broker margin/collateral requirements
- [ ] E. GameStop's stock price declined steadily throughout the squeeze period


&nbsp;

---

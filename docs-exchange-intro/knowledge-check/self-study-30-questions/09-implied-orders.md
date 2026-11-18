# Implied Orders Knowledge Check — Variant 09

Purpose: verify that the student has worked through the chapters *Implied Orders and Synthetic Liquidity* and *Multi-Layer Implied Orders and the Combinatorial Wall*, and can both explain the concepts and compute implied prices, quantities, fills, and P&L.

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

## Conventions

- Spread price S = Near month − Far month (for example S = January − February).
- Buying one spread = buying one lot of the near month and selling one lot of the far month.
- Prices are in US dollars per barrel with a $0.01 tick unless a question states otherwise. One lot = 1,000 barrels.
- Unless stated otherwise, the engine is first-generation: an implied quote is built from exactly two real orders.

## Scoring

- +1 point for each correct option selected.
- -2 points for each incorrect option selected.
- 0 points for options not selected.
- Final test score is capped at a minimum of 0: if raw total is negative, recorded score is 0.
- A passing score is 70% of the maximum rounded down to the nearest integer.

<div style="page-break-after: always;"></div>

## Questions

### 1. Why implied orders exist
- [ ] A. Implied functionality lets the exchange add liquidity that no participant has committed
- [ ] B. Without implied orders, related books can drift into cross-book price gaps that the fastest arbitrageur collects
- [ ] C. Listing a calendar spread for every pair of 12 delivery months gives 66 spread books, so the same traders are spread across 78 books
- [ ] D. Implied orders are mainly used in cash-equity markets
- [ ] E. Implied orders let a buyer in an empty outright book reach a seller whose willingness to sell is expressed inside a spread order

### 2. The spread sign convention
- [ ] A. A spread ask of −$2.10 is a worse (more expensive) ask than a spread ask of −$2.00
- [ ] B. Negative spread prices are normal when the market is in contango
- [ ] C. A spread bid of −$1.90 is a better bid than a spread bid of −$2.00
- [ ] D. Buying one Jan/Feb spread means buying one February lot and selling one January lot
- [ ] E. A Jan/Feb spread price of −$2.00 means January trades $2.00 below February

### 3. Spread P&L, numerically
- [ ] A. Selling 2 spreads at +$0.60 and seeing the spread move to +$0.85 gains $500
- [ ] B. Buying 4 Jan/Feb spreads at −$2.00 and seeing the spread move to −$1.70 gains $1,200
- [ ] C. A spread buyer can profit even while the outright price of oil falls
- [ ] D. If January and February both rise by exactly $1.00, a spread position's P&L is unchanged
- [ ] E. A spread price moving from −$1.20 to −$1.65 is a rise in the spread price

### 4. Orders as vectors
- [ ] A. A set of resting orders forms an implied order only if every unwanted leg cancels to zero
- [ ] B. Combining orders adds their position vectors and adds their cash amounts
- [ ] C. A January bid and a Jan/Feb spread bid together amount to an order in a single book
- [ ] D. A Jan/Feb spread bid has the position vector (Jan +1, Feb −1)
- [ ] E. A sell of February at $77.00 has a cash amount ("cash paid") of +77.00

### 5. The six first-generation formulas
- [ ] A. Implied spread ask = January bid − February bid
- [ ] B. Implied February bid = January bid − spread ask
- [ ] C. Implied spread bid = January bid − February ask
- [ ] D. Implied February ask = January ask − spread bid
- [ ] E. Implied January ask = February ask − spread ask

### 6. Which side is which
- [ ] A. An implied January bid is built from a February bid and a spread bid
- [ ] B. A resting spread bid is, among other things, a standing offer to sell February
- [ ] C. A resting spread ask is, among other things, a standing offer to sell February
- [ ] D. An implied February ask is built from a spread bid
- [ ] E. An implied far-month quote has the same side as the spread order inside it

### 7. Terminology
- [ ] A. Eurex offers implied functionality under the name "synthetic matching"
- [ ] B. A Jan/Feb spread bid and a Feb/Mar spread bid imply a Jan/Mar spread bid, which is neither classic implied IN nor implied OUT
- [ ] C. "Implied IN" is a spread quote derived from orders in the outright books
- [ ] D. "Implied OUT" is an outright quote derived from a spread order plus an outright order
- [ ] E. An implied quote can be built from a single real order

### 8. Implied OUT, a worked scenario
Books: January ask $80.10 × 40 lots; Jan/Feb spread bid −$1.25 × 25 lots; February book empty.
- [ ] A. A buyer of 10 February lots at $81.35 receives its February from the spread bidder, not from the January seller
- [ ] B. The implied February ask is $78.85
- [ ] C. The implied February ask quantity is 40 lots
- [ ] D. After that 10-lot trade, the implied February ask shows 15 lots
- [ ] E. The implied February ask is $81.35

### 9. Implied IN, a worked scenario
Books: January bid $63.40 × 15 lots; February ask $64.05 × 30 lots; spread book empty.
- [ ] A. An order to sell 10 spreads at −$0.70 trades at −$0.65
- [ ] B. An implied spread ask also exists
- [ ] C. In that trade, the spread seller gets a price $0.05 per barrel worse than its limit
- [ ] D. In that trade, the spread seller sells January at $63.40 and buys February at $64.05
- [ ] E. The implied spread bid is −$0.65 for 15 lots

### 10. An implied January ask
Books: February ask $71.30 × 20 lots (Trader P); Jan/Feb spread ask −$0.85 × 12 lots (Trader Q); January book empty.
- [ ] A. The implied January ask is $70.45 for 12 lots
- [ ] B. An order to buy 12 January at $70.50 pays $70.50
- [ ] C. In that trade, Q sells January and buys February from P at $71.30
- [ ] D. The implied quote sits on the January bid side
- [ ] E. After that trade, P has 8 February lots left and no implied January ask remains

### 11. Backwardation
Books: January bid $90.20 × 8 lots; Jan/Feb spread ask +$0.35 × 20 lots; February book empty.
- [ ] A. When an incoming order sells 8 February into the implied bid, the spread order's fill prints at +$0.40
- [ ] B. The implied February bid is $90.55
- [ ] C. An order to sell 8 February at $89.80 receives $89.85
- [ ] D. The implied February bid is $89.85 for 8 lots
- [ ] E. A positive spread price means the near month is more expensive than the far month

### 12. A tempting trap
The only two orders in the market: February bid $76.40 × 12 lots; Jan/Feb spread ask −$1.80 × 20 lots.
- [ ] A. Their position vectors sum to (Jan −1, Feb +2), which is not an order in any single book
- [ ] B. These two orders imply a January bid at $74.60
- [ ] C. Adding a resting January bid would let it combine with the spread ask to imply a February bid
- [ ] D. Publishing a quote computed from these two orders would advertise liquidity the engine cannot deliver
- [ ] E. The spread ask needs to buy February, and the only February order present is another buyer

### 13. No liquidity from nothing
- [ ] A. Every implied lot that trades consumes exactly one lot from each of its real ingredients
- [ ] B. If a 50-lot January ask also feeds a 30-lot implied February ask, 80 lots are for sale in total
- [ ] C. The fills of a correct implied execution sum to zero in every instrument and in cash
- [ ] D. Cancelling one ingredient must remove or shrink every implied quote built on it in the same processing step
- [ ] E. Anything an implied match does could have been done by hand as separate trades, but only with leg risk

### 14. Shared legs, numerically
Books: January ask $75.00 × 18 lots (Trader A); Jan/Feb spread bids at −$2.00 of 12 lots (Trader B) and 10 lots (Trader H).
- [ ] A. In this example, the spread bids are the shared leg
- [ ] B. If A's January order grows to 30 lots, the correct implied quantity becomes 22 lots
- [ ] C. The naive figure over-advertises by 4 lots
- [ ] D. A naive "pairwise min, then sum" implementation publishes 22 lots
- [ ] E. The correct implied February quantity at $77.00 is 18 lots

### 15. Implied depth, numerically
Books: January asks $60.00 × 6 and $60.02 × 10; Jan/Feb spread bids −$1.00 × 8 and −$1.03 × 5.
- [ ] A. The second implied February ask level is $61.02 × 2
- [ ] B. The best implied February ask level is $61.00 × 6
- [ ] C. The total correct implied depth across all levels is 13 lots
- [ ] D. Venues usually publish the full implied depth ladder because it is cheap to compute
- [ ] E. A correct implied ladder contains a level at $61.03

### 16. Recompute, never decrement
Books: January ask $75.00 × 20 lots; spread bid −$2.00 × 20 lots, giving an implied February ask $77.00 × 20. An ordinary January buyer then takes 15 of the January lots.
- [ ] A. Implied quotes should be recomputed after any event on any order in the related group, including cancels and amendments
- [ ] B. Recomputing is only a performance trade-off; decrementing is equally correct
- [ ] C. The correct implied February quantity is now 5 lots
- [ ] D. An engine that only decrements implied quantities on fills in the February implied book still shows 20 lots
- [ ] E. An incoming order to buy 12 February at $77.00 can now fill all 12 lots through the implied route

### 17. Real before implied, numerically
February book: real ask $77.00 × 6 (Trader G); implied ask $77.00 × 20 (from January ask $75.00 × 20 and spread bid −$2.00 × 25); real ask $77.03 × 10. An order to buy 30 February at $77.03 arrives.
- [ ] A. The buyer gets 26 lots at $77.00 and 4 lots at $77.03
- [ ] B. The real $77.00 ask fills before the implied $77.00 ask
- [ ] C. The implied quote fills first if it was displayed earlier than G's order
- [ ] D. Afterwards, the remaining 5 spread lots still imply a February ask
- [ ] E. The buyer's average price is $77.004

### 18. Who can be the aggressor
- [ ] A. Every implied trade has a real incoming order as its aggressor
- [ ] B. On CME, implied quantity in futures has time priority over real orders that arrive later at the same price
- [ ] C. On CME, implied bids do not trade against implied offers
- [ ] D. In a first-generation engine, an implied bid and an implied ask in the same book can be crossed without any bug
- [ ] E. Implied quotes act as the aggressor when the books around them change

### 19. Price improvement
Books: January ask $74.95 × 40; Jan/Feb spread bid −$2.00 × 25; real February ask $77.00 × 60. An order to buy 20 February at $77.00 arrives.
- [ ] A. The buyer pays $77.00, its limit price
- [ ] B. The real $77.00 February seller is not filled
- [ ] C. The spread bidder's fill prints at −$2.05
- [ ] D. The buyer saves $50 per lot against the real February ask, $1,000 on 20 lots
- [ ] E. The implied February ask is $76.95

### 20. Closing a cross-book gap
Resting: January ask $74.95 × 40; February bid $76.97 × 10 (Trader K). Then Trader B's spread bid −$2.00 × 25 arrives.
- [ ] A. Before B arrives, the engine publishes an implied spread ask at −$2.02
- [ ] B. B buys 10 spreads at −$2.02
- [ ] C. The price improvement goes to whichever real order arrived first
- [ ] D. B's remaining 15 spreads rest as a bid at −$2.00
- [ ] E. Without implied functionality, an arbitrageur could collect $0.02 per barrel risk-free from these three orders

### 21. Tick rounding, an implied ask
A product has an outright tick of 0.25 and a spread tick of 0.05. Resting: January ask 100.00; spread bid −0.35.
- [ ] A. When a buyer takes the published implied ask, the spread bidder's fill prints at −0.50, better than its limit
- [ ] B. Matching, market data, and clearing may each use their own rounding rule, as long as each one is documented
- [ ] C. The exact implied February ask is 100.35
- [ ] D. The published implied February ask is 100.25
- [ ] E. Rounding outwards guarantees that no real order trades worse than its limit

### 22. Tick rounding, an implied bid
Same product (outright tick 0.25, spread tick 0.05). Resting: January bid 50.00 × 10 (Trader J); spread ask +0.15 × 10 (Trader L).
- [ ] A. For an implied OUT quote, the rounding gain goes to the incoming outright order
- [ ] B. Rounding the bid up to 50.00 instead would make L's spread print at 0.00, below L's limit
- [ ] C. If an incoming order sells February at the published bid, L's spread fill prints at +0.25
- [ ] D. The exact implied February bid is 49.85
- [ ] E. The published implied February bid is 49.75

### 23. Signed prices in code
- [ ] A. Sorting spread bids by absolute value, largest first, ranks −$2.00 ahead of −$1.95
- [ ] B. That sorting bug gives an incoming spread seller a better price than the market offered
- [ ] C. A validation rule requiring price > 0 is safe for outright futures books
- [ ] D. Storing spread prices as signed integer ticks makes price priority work with ordinary numeric comparison
- [ ] E. That sorting bug is invisible while all spread prices are positive

### 24. Implied liquidity in market data
- [ ] A. Implied-enabled products typically generate fewer market-data messages per order message than other products
- [ ] B. Some venues publish implied quotes as a separate implied book next to the real book
- [ ] C. A data consumer that does not know a venue's implied publishing policy may rebuild a book that disagrees with the venue's
- [ ] D. An implied quote can disappear because of an event in a different book
- [ ] E. CME disseminates every implied quote it calculates

### 25. Engineering an implied match
- [ ] A. All fills of an implied match commit together or not at all
- [ ] B. An implied match prints only one trade, in the incoming order's book
- [ ] C. A common production design assigns a whole related instrument group to one sequencing thread
- [ ] D. Iterating over candidate combinations in hash-map order is a safe way to find implied quotes
- [ ] E. Serialised processing within the group stops two buyers in different books from both using the same January lots

### 26. Partial fills, leg risk, and leg prices
- [ ] A. A resting spread order partly filled through an implied match keeps its remainder resting with time priority intact
- [ ] B. Leg prices may be off-tick, as long as each spread's legs differ by exactly its trade price
- [ ] C. When an implied Jan/Mar match fills two spread orders against each other, the February leg price must be set by a documented rule
- [ ] D. Fill-Or-Kill orders never become ingredients of implied quotes because they never rest
- [ ] E. A spread trader filled through an implied match can end up holding a January leg without the matching February leg

### 27. Generations, numerically
Books: September bid 75.90 × 10; October ask 76.83 × 8; Oct/Nov spread bid −0.52 × 5.
- [ ] A. A generation-2 implied quote is built from two real orders
- [ ] B. A generation-2 engine shows an implied Sep/Nov spread bid at −1.45 for 5 lots
- [ ] C. The implied November ask is 77.35
- [ ] D. The implied Sep/Oct spread bid is −0.93
- [ ] E. A generation-1 engine also shows the Sep/Nov spread bid

### 28. Best route, numerically
Resting orders that can help a March buyer: January ask 50.00; February ask 50.40; real March ask 50.95; Jan/Feb spread bid −0.35; Feb/Mar spread bid −0.40; Jan/Mar spread bid −0.85.
- [ ] A. Finding the single best implied price through long chains of calendar spreads requires listing every route
- [ ] B. A cycle of resting orders whose total weight is non-negative is a crossed market
- [ ] C. A generation-1 engine's best March ask is 50.80
- [ ] D. The generation-2 route uses the January ask, the Jan/Feb spread bid, and the Feb/Mar spread bid
- [ ] E. A generation-2 engine's best March ask is 50.75

### 29. The combinatorial wall
- [ ] A. In a fully listed 12-month strip, the number of routes to one book grows factorially with the generation limit
- [ ] B. Butterflies turn implied matching from a path problem into an integer-programming problem
- [ ] C. Each extra generation adds new liquidity, which is why exchanges try to maximise the generation limit
- [ ] D. With generation 2 enabled in a fully listed 12-month strip, one June ask can affect quotes in all 78 books
- [ ] E. Fair allocation needs all equal-price routes, ranked, not just one best path

### 30. Testing implied logic
- [ ] A. Every party to an implied execution must trade at or better than its own limit
- [ ] B. An implied quote that survives the cancellation of one of its ingredients is a harmless display glitch
- [ ] C. Property-based fuzzing across three related books is a good fit for implied matching logic
- [ ] D. A firmness test checks that every published implied quote is executable at that instant
- [ ] E. A conservation test checks that every implied execution sums to zero in every instrument and in cash

&nbsp;

---

# Implied Orders Knowledge Check — Variant 07

Purpose: verify that the student has worked through the chapters *Implied Orders and Synthetic Liquidity* and *Multi-Layer Implied Orders and the Combinatorial Wall* in [How a Financial Exchange Works](../how-exchange-works.md), and can both explain the concepts and compute implied prices, quantities and fills.

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

## Conventions

- Spread price S = Near month − Far month (for example S = March − April).
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
- [ ] A. Implied orders are mainly an equity-market feature, because each stock lists many calendar spreads
- [ ] B. Implication lets a trader in one book trade against interest resting in other books, without leaving anyone with only one leg of a spread
- [ ] C. Without implication, the far-month sale inside a resting spread bid is invisible to a trader who looks only at the far-month book
- [ ] D. Implied orders work because the exchange trades with its own capital to fill gaps between the books
- [ ] E. A strip of 10 monthly contracts with every calendar spread listed has 45 spread books, so 55 books in all

### 2. Spread sign and spread P&L
*Scenario: a trader buys 5 March/April spreads at −$0.80. Later the spread trades at −$0.62.*

- [ ] A. At the entry price, March was trading $0.80 below April
- [ ] B. If March and April had both risen by $0.50 instead, the position would have gained $2,500
- [ ] C. A spread bid at −$0.75 is a better bid than one at −$0.80
- [ ] D. The trader's profit is $900
- [ ] E. Buying the spread means selling March and buying April

### 3. Orders as vectors
*Write each order as its position change over (March, April). A March bid is (+1, 0).*

- [ ] A. A March/April spread ask is (−1, +1)
- [ ] B. An April bid plus a March/April spread bid implies a March bid
- [ ] C. A March bid plus a March/April spread bid implies nothing
- [ ] D. A set of resting orders forms an implied order when their positions cancel in every book except one, leaving exactly one lot there
- [ ] E. The price of an implied order is the average of its ingredients' prices

### 4. Implied OUT, numerically
*Scenario: March ask $68.40 × 25 lots (Trader A); March/April spread bid −$0.90 × 15 lots (Trader B). The April book is empty.*

- [ ] A. A buyer of 10 April at $69.30 makes B buy 10 March from A at $68.40 and sell 10 April to the buyer at $69.30
- [ ] B. The implied April ask is $69.30 × 15
- [ ] C. When a buyer takes April lots from the implied ask, B's spread prints at +$0.90
- [ ] D. If a buyer takes 10 April lots, the implied April ask then shows $69.30 × 5
- [ ] E. The implied April ask is $67.50

### 5. Implied IN, numerically
*Scenario: March bid $71.15 × 20 (Trader C); April ask $71.95 × 12 (Trader D). The March/April spread book is empty.*

- [ ] A. An incoming order to sell spreads with a limit of −$0.75 would also trade against the implied bid
- [ ] B. An implied March/April spread bid exists at −$0.80 × 12
- [ ] C. An implied March/April spread ask exists at −$0.80
- [ ] D. When a spread seller trades against the implied bid, it sells March to C at $71.15 and buys April from D at $71.95
- [ ] E. An incoming order to sell 12 spreads with a limit of −$0.85 trades at −$0.80

### 6. Which side is which
*Near and far months, with S = Near − Far.*

- [ ] A. An implied far-month bid is priced at Near_bid + S_ask
- [ ] B. A spread ask combined with a near-month bid implies a far-month ask
- [ ] C. A spread bid combined with a far-month bid implies a near-month bid
- [ ] D. An implied near-month ask is priced at Far_ask + S_ask
- [ ] E. A spread bid combined with a near-month ask implies a far-month ask

### 7. Backwardation
*Scenario: May bid $82.40 × 10 (Trader E); May/June spread ask +$0.55 × 30 (Trader F). The June book is empty.*

- [ ] A. The implied June bid is $81.85 × 10
- [ ] B. When a June seller trades against the implied bid, F's spread prints at +$0.60
- [ ] C. The implied June bid is $82.95
- [ ] D. A positive spread price means May trades above June, which is backwardation
- [ ] E. An incoming order to sell 6 June with a limit of $81.80 receives $81.85

### 8. Two orders that imply nothing
- [ ] A. A March bid and a March/April spread ask imply an April bid
- [ ] B. An April bid and a March/April spread ask can complete each other into an implied quote
- [ ] C. A March bid and a March/April spread bid imply an April ask
- [ ] D. Publishing a quote from orders whose legs do not cancel breaks the firmness invariant
- [ ] E. A March ask and a March/April spread ask imply nothing

### 9. Shared legs
*Scenario: March ask $60.00 × 14 (Trader A); two March/April spread bids at −$0.50, one of 10 lots (Trader B) and one of 9 lots (Trader G).*

- [ ] A. Shared legs only cause problems when the two spread bids have different prices
- [ ] B. The correct implied quantity is 19 lots
- [ ] C. Computing each pair separately and adding the results overstates the quantity by 5 lots
- [ ] D. If A's March ask grows to 25 lots, the implied quantity becomes 19
- [ ] E. The implied April ask is $60.50 × 14

### 10. Implied depth
*Scenario: March asks $55.00 × 8 and $55.03 × 12; March/April spread bids −$0.40 × 5 and −$0.44 × 10. The April book is empty.*

- [ ] A. The best implied April ask is $55.40 × 5
- [ ] B. The third implied April ask level is $55.47 × 7
- [ ] C. The second implied April ask level is $55.43
- [ ] D. The ladder adds up to 20 implied lots
- [ ] E. The second implied April ask level is $55.44 × 3

### 11. Recompute, never decrement
*Scenario: March ask $70.00 × 30; March/April spread bid −$1.00 × 20; implied April ask $71.00 × 20. A March buyer then takes 25 March lots directly in the March book.*

- [ ] A. Because the trade happened in the March book, the implied April quote is unaffected
- [ ] B. An engine that only reduces implied quantity when the implied quote itself trades would still show 20 lots
- [ ] C. Implied quotes must be recomputed after every event on any of their ingredients
- [ ] D. The implied April ask is now $71.00 × 5
- [ ] E. Had the March buyer taken all 30 lots, the implied April ask would disappear

### 12. Real before implied
*Scenario: April real asks $72.50 × 4 (Trader H) and $72.53 × 20. An implied April ask $72.50 × 10 comes from a March ask $72.00 × 10 and a March/April spread bid −$0.50 × 30. A buyer sends a limit order to buy 20 April at $72.55.*

- [ ] A. The implied lots fill before H's order because they were calculated first
- [ ] B. The buyer receives 14 lots at $72.50 and 6 lots at $72.53
- [ ] C. The buyer's average price is about $72.509
- [ ] D. After the trade, the spread bidder still has 20 spreads resting at −$0.50
- [ ] E. H's 4 lots fill before any implied lot at $72.50

### 13. Who can be the aggressor
- [ ] A. CME calculates locked or crossed implied quotes but does not disseminate them
- [ ] B. Implied quotes have time priority over real orders at the same price, because they are refreshed constantly
- [ ] C. An incoming spread order can trade against an implied spread quote built from two outright orders
- [ ] D. In a first-generation engine, an implied bid can trade against an implied ask
- [ ] E. An implied quote can trade only when a real incoming order arrives against it

### 14. Price improvement
*Scenario: April real ask $66.20 × 30. A March ask $65.60 × 15 and a March/April spread bid −$0.55 × 15 imply an April ask. A buyer sends a limit order to buy 10 April at $66.20.*

- [ ] A. The buyer fills all 10 lots against the implied ask at $66.15
- [ ] B. Compared with the real ask, the buyer saves $500 in total
- [ ] C. The spread bidder's spread prints at −$0.55
- [ ] D. The buyer fills at $66.20, because real orders always trade before implied orders
- [ ] E. The improvement is 5 ticks

### 15. Closing a cross-book gap
*Scenario: a March ask $74.20 × 20 (Trader J) and an April bid $75.05 × 8 (Trader K) are resting. Trader L then sends a March/April spread bid at −$0.80 × 10.*

- [ ] A. Without implication, an arbitrageur could lock in $50 per lot with no risk
- [ ] B. L trades 8 spreads at −$0.85
- [ ] C. The implied March/April spread ask is −$0.85 × 8
- [ ] D. L trades at its own limit of −$0.80
- [ ] E. L's unfilled 2 spreads stay in the book at −$0.80

### 16. Tick rounding
*Scenario: outright tick $0.25, spread tick $0.05. March ask $100.00 × 10 (Trader A); March/April spread bid −$0.60 × 10 (Trader B).*

- [ ] A. At $100.75, B's spread prints at −$0.75, better than its limit
- [ ] B. The raw implied April ask, $100.60, is not a valid price
- [ ] C. Implied bids round up and implied asks round down
- [ ] D. The engine publishes the implied April ask at $100.75
- [ ] E. Rounding down to $100.50 would trade B's spread order beyond its limit

### 17. Generation 2
*Scenario: June ask $80.00 × 10 (Trader A); June/July spread bid −$0.30 × 6 (Trader B); July/August spread bid −$0.25 × 8 (Trader C). The July and August books are empty.*

- [ ] A. The August ask price can be written as 80.00 + 0.30 + 0.25, built directly from the three real orders
- [ ] B. A generation-1 implied July ask exists at $80.30 × 6
- [ ] C. The generation-2 quantity is limited by C's 8 lots
- [ ] D. A generation-2 implied August ask exists at $80.55 × 6
- [ ] E. A first-generation engine also publishes the August ask

### 18. The graph view
- [ ] A. A cycle of resting orders with non-negative total weight is a crossed market
- [ ] B. Finding the best price through chains of calendar spreads is intractable even for small strips
- [ ] C. A shortest-path search finds the best price, but fair allocation among equal prices needs every tied route
- [ ] D. A butterfly order can be drawn as a single edge between two months
- [ ] E. With orders drawn as weighted edges, the best implied bid for "long x, short y" is the maximum-weight path from x to y

### 19. The combinatorial wall and real venues
- [ ] A. CME limits implied options to the first generation
- [ ] B. The number of routes to a book grows factorially with the allowed chain length
- [ ] C. ICE implies across any number of generations, but only within a given strip type
- [ ] D. The book recommends making implication depth an explicit per-product setting, defaulting to 1
- [ ] E. CME's MDP 3.0 feed publishes the full depth of the implied book

### 20. Engineering and testing implied matching
- [ ] A. FOK and IOC orders are common ingredients of implied quotes
- [ ] B. All legs of an implied match are validated first and then committed together, so one failed leg voids the whole match
- [ ] C. "Partition by symbol" becomes "partition by related instrument group" in an implied-capable engine
- [ ] D. Conservation means one implied lot consumes exactly one lot of each ingredient
- [ ] E. The testing invariants hold for generation 1 but must be rewritten for deeper generations

&nbsp;

---

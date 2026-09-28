# Implied Orders and Synthetic Liquidity

This concept trips up almost every developer who meets a derivatives exchange for the first time, and for good reason: it is the first place in this book where a single incoming order can trade against orders resting in *other* order books. The arithmetic is school-level, but it arrives wrapped in an unusual sign convention, the quantity rules are less obvious than they look, the priority rules are subtle, and the engineering consequences are severe. This chapter therefore climbs in explicit levels. Each level introduces one new idea and works it through with numbers before the next level begins. The numbers carry over from level to level, so read every example even when the idea feels obvious.

By the end of the chapter you should be able to write a correct first-generation implied-matching module: compute implied prices and quantities, execute them atomically, keep them consistent as the books change, and test them. The chapter after this one then asks the obvious follow-up question, *why not imply from implied orders, and from those, and so on?*, and shows why every exchange stops after a few steps.

One promise before we begin, which the rest of the chapter proves over and over: **implied orders do not create liquidity out of nothing.** An implied order is a different *view* of commitments that already rest in other books. It never adds a single lot to the total that can be traded; it only makes existing lots reachable from one more place. Hold on to that sentence. Every level below is, in the end, a demonstration of it.

## Level 0: Futures in One Page

You do not need a finance background for this chapter, but you do need four facts about futures.

**1. A futures contract is a promise, not a purchase.** A futures contract is a standardised agreement to buy or sell a fixed quantity of something (crude oil, wheat, a stock index) at a price agreed *today*, for delivery on a fixed date in the *future*. Nothing changes hands at the moment of the trade except a good-faith deposit (the *margin*, covered in the clearing chapter of Part III). If you agree to buy, you are **long**; if you agree to sell, you are **short**. If the price later rises, the long side gains and the short side loses the same amount, and vice versa. Futures are a zero-sum game between the two sides of each trade.

**2. Everything in this chapter uses crude oil.** The running example is modelled on NYMEX WTI Light Sweet Crude Oil futures (symbol CL) at CME Group. One contract, also called one **lot**, covers **1,000 barrels**. Prices are quoted in **US dollars per barrel**, and the minimum price step (the **tick**, see the *Tick Sizes* chapter) is **$0.01 per barrel, worth $10 per contract** [CME Group, NYMEX Rulebook Chapter 200]. So when this chapter says "a price of $75.00", it means $75.00 per barrel, and one lot at that price represents $75,000 worth of oil.

**3. Every delivery month is a separate instrument with its own order book.** January crude and February crude are *different products*: different delivery dates, different buyers and sellers, different prices. An exchange lists many months at once, and each month has its own independent order book exactly like the ones in the *Order Book* chapter. Throughout this chapter we use two of them, **January** (the *near* month, delivered sooner) and **February** (the *far* month).

**4. Traders often care about the *difference* between two months more than about either price.** Three common reasons:

1. **Rolling a position.** A trader who is long January and wants to stay long oil beyond January's expiry must sell January and buy February. Doing that as two separate trades exposes them to the market moving between the two fills.
2. **Relative-value trading.** A trader may believe February is too expensive *relative to* January without having any opinion at all on where oil itself is going. The only thing they want exposure to is the difference.
3. **Margin efficiency.** Long January plus short February is largely protected against the overall oil price moving (if oil rises, one leg gains roughly what the other loses), so clearing houses require much less margin for the pair than for two unrelated positions. CME's margin methodology grants explicit *intra-commodity spread credits* for exactly this reason.

The naive way to get exposure to the difference is to submit two ordinary orders and hope both fill. That carries **leg risk**: one leg fills, the other does not, and the trader is left holding an outright position they never wanted. Exchanges solved this by listing the difference itself as a tradeable instrument, with its own order book. That instrument is where our story starts.

## Level 1: The Spread Instrument and Its Sign Convention

A **calendar spread** is a single listed instrument whose price is *defined* as the difference between two delivery months. Throughout this chapter we use the convention CME and most futures venues use for calendar spreads:

```
spread price   S  =  Near-month price  −  Far-month price
                     (here: S = January − February)
```

**Buying one spread** means buying one lot of the near month *and* selling one lot of the far month, simultaneously, as one instruction. **Selling one spread** is the mirror image: sell the near month, buy the far month. CME's own description of Treasury calendar spreads states this directly: "buying the calendar spread entails buying the nearby month ... and selling the deferred month" [CME Group, *Treasury Futures Calendar Spreads*, 2016].

### Why this convention makes sense

The convention is chosen so that **buying the spread is a bet that the number S goes up**, exactly as buying anything else is a bet that its price goes up. Work it through:

- You buy one Jan/Feb spread at S = −$2.00. Concretely, suppose you buy January at $75.00 and sell February at $77.00 (75.00 − 77.00 = −2.00).
- A week later January is $76.00 and February is $77.50, so S = 76.00 − 77.50 = **−$1.50**. The spread price *rose* from −2.00 to −1.50.
- Your January long gained $1.00 per barrel. Your February short lost $0.50 per barrel. Net: **+$0.50 per barrel**, which is exactly the change in S: (−1.50) − (−2.00) = +0.50.
- Per lot that is $0.50 × 1,000 barrels = **$500**.

Notice that the outright price of oil rose too, but that did not matter; only the difference did. That is the whole point of trading the spread.

### The four things that confuse every beginner

The convention is logical, but it produces four effects that look wrong the first time you see them. Name them now, and they will not ambush you later.

**Confusion 1: spread prices are routinely negative.** When the far month is more expensive than the near month (a market in **contango**, common in oil when storage is plentiful), S is negative. When the near month is more expensive (**backwardation**), S is positive. Both are completely normal:

| Spread price | Meaning | A spread *buyer* does, for example |
|---|---|---|
| S = −$2.00 | January trades $2.00 **below** February | buys Jan at $75.00 and sells Feb at $77.00 |
| S = +$0.50 | January trades $0.50 **above** February | buys Jan at $76.50 and sells Feb at $76.00 |

A negative price is not an error code, and your engine must not treat it as one. Nor are negative prices limited to spreads. On 20 April 2020, with storage at the Cushing, Oklahoma delivery point nearly full and the May 2020 WTI contract one day from expiry, May crude *settled at −$37.63 per barrel* [CFTC, Interim Staff Report, November 2020], while the June contract closed at $20.43 [Congressional Research Service, IN11354]. Holders of May contracts were, in effect, paying people to take oil off their hands, and the May/June spread was roughly −$58 per barrel. CME had warned its clearing members in early April that some energy contracts could trade below zero and had opened a test environment for negative prices [CME Clearing Advisories 20-152 and 20-160, April 2020]. Not every system was ready. The CFTC later found that at one large retail broker "negative prices were not displayed to customers and customers were unable to place orders with negative-priced limit orders", and ordered it to pay a $1.75 million penalty plus about $82.6 million in restitution to customers [CFTC press release 8432-21, 28 September 2021]. An assumption of `price > 0`, buried in one validation function, turned out to be a nine-figure bug.

**Confusion 2: "higher" and "better" need care.** −1.50 is *higher* than −2.00. A spread bid of −1.90 is therefore a *better* (more generous) bid than −2.00, and a spread ask of −2.10 is a better (cheaper) ask than −2.00. Price-time priority works exactly as in any other book, provided your comparison operators are signed. Storing spread prices as signed integer tick counts (−200 ticks for −$2.00) makes this automatic.

**Confusion 3: buying the spread *sells* the far month.** A spread *buyer* is a *seller* of February. So a resting spread **bid** is, among other things, a standing offer to **sell** February. This side-flip is the single most important fact in this chapter, and it is where most implementation bugs come from.

**Confusion 4: subtracting a negative number adds.** Because S = Jan − Feb, it follows that Feb = Jan − S. With S = −2.00 and Jan = 75.00, Feb = 75.00 − (−2.00) = **77.00**. Every time you see "minus a spread price" in this chapter, check the sign twice.

> **Convention warning.** Near-minus-far is the norm for calendar spreads on CME, and most futures venues use the same convention, but it is not a law of nature. Inter-commodity spreads, ratio spreads, and some venues' products define their price differently (some as a ratio of legs, some with legs weighted 2:3, and so on). Always read the product's definition before writing a single formula.

### Leg prices

When a spread trades at −$2.00, the clearing house still needs a concrete price for each leg, because positions, profit and loss, and margin are tracked per month. The exchange assigns leg prices using a documented rule. On CME, for example, one leg is anchored to a recent reference price for that month (its latest trade price, a current price indication, or its settlement price) and the other leg is derived so that the two legs differ by exactly the spread price [CME Group, *Treasury Futures Calendar Spreads*]. The spread traders' economics depend only on the difference; the leg prices exist so every system downstream can do per-instrument bookkeeping. We will return to leg prices at Level 9, where they stop being a formality.

## Level 2: The Developer's Model, Orders as Vectors

The rest of the chapter becomes mechanical, and much easier to implement correctly, once you describe every order with two numbers-with-structure.

**The position vector v.** For each instrument, how many lots does *one unit* of this order buy (+1) or sell (−1)?

**The cash amount c.** How much money (per barrel) does one unit of this order *pay*? A negative c means the order *receives* money.

For the four basic kinds of order:

| Order | Position vector v | Cash paid c (per barrel) |
|---|---|---|
| Buy January at price P | (Jan +1) | +P |
| Sell January at price P | (Jan −1) | −P |
| Buy Jan/Feb spread at price S | (Jan +1, Feb −1) | +S (pays the Jan price, receives the Feb price; Jan − Feb = S) |
| Sell Jan/Feb spread at price S | (Jan −1, Feb +1) | −S |

The one rule that powers everything else is this:

> **Combining orders adds their vectors and adds their cash.** If a set of resting orders is executed together, the combined effect on the world is the sum of their position vectors, and the combined money flow is the sum of their cash amounts.

An **implied order** is simply a set of resting orders whose vectors add up to something that *looks like a single order in some other book*. Here is the canonical case. Take one resting January ask at $75.00 and one resting spread bid at −$2.00:

```
  Sell Jan at 75.00          v = (Jan −1)            c = −75.00
+ Buy spread at −2.00        v = (Jan +1, Feb −1)    c = −2.00
  ----------------------------------------------------------------
  Combined                   v = (Feb −1)            c = −77.00
```

The January legs cancel. What remains sells one February lot and receives $77.00: that is precisely **an offer to sell February at $77.00**, even though nobody has placed an order in the February book. This is the complete theory of implied pricing. Everything else in this chapter (quantities, priority, rounding, market data) is engineering around this addition.

Two consequences follow immediately and should be memorised:

1. **Implied prices come from adding cash amounts**, so they are *exact* sums and differences of real order prices, no averaging, no estimation.
2. **Legs must cancel against an order on the opposite side.** The January leg of the spread bid (+1) cancels only against a January *sell* (−1). A January *bid* would add +1 to +1 and produce a two-lot January purchase, which is not an order in any book. This is the formal version of "an implied order needs every leg to be executable".

### The six first-generation implied prices

Apply the rule to every pair of orders that can cancel a leg, and exactly six implied quotes appear. This table is the reference for the whole chapter.

| Implied quote | Ingredients (both must be resting) | Vector check | Formula |
|---|---|---|---|
| Feb **ask** | Jan ask + Spread **bid** | (Jan −1) + (Jan +1, Feb −1) = (Feb −1) | Jan_ask − S_bid |
| Feb **bid** | Jan bid + Spread **ask** | (Jan +1) + (Jan −1, Feb +1) = (Feb +1) | Jan_bid − S_ask |
| Jan **ask** | Feb ask + Spread **ask** | (Feb −1) + (Jan −1, Feb +1) = (Jan −1) | Feb_ask + S_ask |
| Jan **bid** | Feb bid + Spread **bid** | (Feb +1) + (Jan +1, Feb −1) = (Jan +1) | Feb_bid + S_bid |
| Spread **ask** | Jan ask + Feb **bid** | (Jan −1) + (Feb +1) = (Jan −1, Feb +1) | Jan_ask − Feb_bid |
| Spread **bid** | Jan bid + Feb **ask** | (Jan +1) + (Feb −1) = (Jan +1, Feb −1) | Jan_bid − Feb_ask |

*(Reading the "Spread ask" row: the combined vector is (Jan −1, Feb +1), which is what one unit of a spread **sell** looks like; a resting set of orders that together behave like a seller is an **ask**. Its price is −c = −(−Jan_ask + Feb_bid) = Jan_ask − Feb_bid.)*

Check the sign-flip from Confusion 3 in the table: an implied February **ask** is built from a spread **bid**. Near-month quotes keep their side; far-month quotes flip it.

**Terminology.** CME defines the two families as follows [CME Group Client Systems Wiki, *Implied Orders*]:

- **Implied IN**: "an order CME Globex identifies as existing in the spread market based on orders in the outright market" (the bottom two rows: two outrights imply a spread quote).
- **Implied OUT**: "an order CME Globex identifies as existing in the outright market based on orders in the spread market" (the top four rows: a spread plus an outright imply an outright quote).

A mnemonic: implied **in**to the spread book, implied **out** of the spread book. Informal industry usage is not always consistent, so when reading another venue's documentation, check its definitions rather than assuming.

**How to never get a formula wrong.** Do not memorise the table. When you need a formula, write down the two vectors and add them. If the unwanted legs cancel, you have an implied order and its price falls out of the cash sum. If they do not cancel, there is no implied order, however tempting the arithmetic looks. Exercise E2 at the end of the chapter is a deliberate trap built on exactly this point.

## Level 3: Implied OUT, a Complete Worked Example

A spread order plus an outright order jointly produce a quote in a book that may otherwise be completely empty.

**The books before anything happens:**

| Book | Side | Price | Lots | Who |
|---|---|---|---|---|
| January (outright) | Ask | $75.00 | 50 | Trader A |
| Jan/Feb spread | Bid | −$2.00 | 30 | Trader B |
| February (outright) | – | *empty* | – | – |

Trader A will sell up to 50 January lots at $75.00 or more. Trader B will buy up to 30 spreads at −$2.00 or less, meaning B will buy January and sell February whenever February can be sold for at least $2.00 more than January costs.

**The operational question.** Could anyone, right now, firmly *buy* February, even though the February book is empty? Yes. Trader B is willing to sell February, *provided* B can simultaneously buy January $2.00 cheaper. Trader A is willing to sell January at $75.00. Chain the two commitments: B buys January from A at $75.00, so B can sell February at $75.00 − (−$2.00) = **$77.00**. This is row one of the table: implied Feb ask = Jan_ask − S_bid = 75.00 − (−2.00) = 77.00.

**Quantity** is capped by the scarcer ingredient: min(50, 30) = **30 lots**. B only wants 30 spreads, however much January A offers.

The engine therefore publishes in the February book:

| Book | Side | Price | Lots | Source |
|---|---|---|---|---|
| February | Ask | $77.00 | 30 | **Implied** (A's January ask + B's spread bid) |

**Execution.** Trader C submits an order to buy 20 February at $77.00. Matching it against the implied quote requires three fills that happen *together or not at all*:

```{.mermaid width=600}
sequenceDiagram
    participant C as Trader C (Feb buyer)
    participant ME as Matching Engine
    participant A as Trader A (Jan ask 75.00)
    participant B as Trader B (Spread bid −2.00)

    C->>ME: BUY 20 FEB @ 77.00
    Note over ME: Implied Feb ask 77.00 × 30 found.<br/>All three fills validated, then committed atomically.
    ME->>A: Fill 1: A SELLS 20 JAN @ 75.00 (to B)
    ME->>B: Fill 2: B BUYS 20 SPREADS @ −2.00
    ME->>C: Fill 3: C BUYS 20 FEB @ 77.00 (from B)
    Note over ME: Three trade prints: JAN 20@75.00,<br/>SPREAD 20@−2.00, FEB 20@77.00
```

Check that every party got exactly what its order asked for, and nothing it did not ask for:

- **A** sold 20 January at $75.00, precisely A's limit.
- **B** bought 20 spreads at −$2.00: long 20 January at $75.00 and short 20 February at $77.00; 75.00 − 77.00 = −2.00 ✓. B's margin is computed on the much smaller spread risk.
- **C** bought 20 February at $77.00, precisely C's limit. C need not know, and on most venues cannot tell from the fill, that the counterparty's February sale was part of a spread.

And check the vector bookkeeping: A's (Jan −20), B's (Jan +20, Feb −20) and C's (Feb +20) sum to zero in every instrument, and the cash sums to zero too. Using "cash paid" per barrel: A pays −(20 × 75.00) = −1,500, C pays +(20 × 77.00) = +1,540, and B pays 20 × (−2.00) = −40, that is, B *receives* the $2.00 difference on each of its 20 spreads. −1,500 + 1,540 − 40 = 0 (multiply by 1,000 barrels per lot for real dollars). Nothing was created and nothing was lost. Every correct implied execution balances to zero like this, and your test suite should assert it.

**The books after the match:**

| Book | Side | Price | Lots remaining |
|---|---|---|---|
| January (outright) | Ask | $75.00 | 30 *(was 50)* |
| Jan/Feb spread | Bid | −$2.00 | 10 *(was 30)* |
| February (implied) | Ask | $77.00 | **10** = min(30, 10) |

## Level 4: Implied IN, Two Outrights Produce a Spread Quote

Now the other direction: the *spread* book is empty, and the outright books are live.

**The books:**

| Book | Side | Price | Lots | Who |
|---|---|---|---|---|
| January (outright) | Bid | $74.40 | 25 | Trader D |
| February (outright) | Ask | $76.60 | 40 | Trader E |
| Jan/Feb spread | – | *empty* | – | – |

Add the vectors: D's January bid is (Jan +1) with c = +74.40; E's February ask is (Feb −1) with c = −76.60. Together: (Jan +1, Feb −1), which is the shape of a spread **buy**, paying 74.40 − 76.60 = **−$2.20**. The two outrights jointly *bid* −$2.20 for the spread.

In words: anyone who wants to **sell** the spread (sell January, buy February) can do it right now by selling January to D at $74.40 and buying February from E at $76.60, which is a spread sale at 74.40 − 76.60 = −2.20.

```
Implied S_bid = Jan_bid − Feb_ask = 74.40 − 76.60 = −2.20
Quantity      = min(25, 40)       = 25 lots
```

Trader F submits an order to sell 10 spreads at −$2.20. The engine executes atomically:

1. **January fill:** F sells 10 January at $74.40 to D.
2. **February fill:** F buys 10 February at $76.60 from E.
3. **Spread print:** F sold 10 spreads at 74.40 − 76.60 = −$2.20 ✓.

D and E each received an entirely ordinary outright fill at their own limit price. Afterwards the January bid has 15 lots left, the February ask has 30, and the implied spread bid is −$2.20 × min(15, 30) = 15.

The *opposite* implied quote needs the opposite ingredients. An implied spread **ask** requires a January *ask* and a February *bid* (Jan_ask − Feb_bid). With only D and E in the books, no implied spread ask exists: add the vectors of D and E any other way and nothing cancels.

## Level 5: The Promise Kept, Implied Orders Create No Liquidity

It is time to make the introduction's promise precise, because it is the single most important idea in the chapter, and because misunderstanding it leads directly to the most dangerous bugs.

**Argument 1: an implied trade is a trade anyone could have done by hand.** Go back to Level 3. Trader C wanted February and could have assembled it manually, without any implied functionality:

1. Sell 20 spreads to Trader B at −$2.00. (C now: sell 20 Jan, buy 20 Feb, and pays −2.00, i.e. *receives* $2.00 per barrel on the difference.)
2. Buy 20 January from Trader A at $75.00. (C's January sale and purchase cancel.)

C's net result: long 20 February, having paid $75.00 + $2.00 = $77.00 per barrel. Exactly the implied trade, same counterparties, same prices. The implied engine did not find any liquidity that was not already reachable. It did the legwork **atomically**, eliminating C's leg risk (the danger that A's January offer disappears between C's two trades) and letting C trade with a single ordinary order.

**Argument 2: the same lot must never be counted twice.** In Level 3's books, A's 50 January lots appear on screens in *two places*: as 50 lots in the January book, and (30 of them) inside the 30-lot implied February ask. It is tempting to add up what the screens show and conclude that 80 lots are for sale. That is wrong. If a January buyer takes all 50 of A's lots, the implied February ask **disappears**, because one of its ingredients is gone. The displayed quantities across related books are *alternative* uses of the same underlying commitments, not additional ones.

**Argument 3: the removal test.** Cancel A's January order and the implied February ask vanishes in the same processing step: there is nothing left to build it from. Cancel B's spread order and it vanishes too. An implied quote that survives the cancellation of one of its ingredients is not a harmless display glitch; it is the engine advertising a price it cannot honour.

**Argument 4: conservation in the arithmetic.** In Level 3, before the match, the system held 50 committed January lots and 30 committed spread lots. After C's trade, it held 30 January lots and 10 spread lots, and C held 20 February lots that each consumed *exactly one* of A's lots and *exactly one* of B's spreads. The vector sum of every trade is zero (Level 3). No lot was ever used twice, and none was conjured.

> **Implied orders move liquidity between books; they never add to it.** Every implied lot is a real lot from a real order, reachable by one more route. When it trades through one route, it is gone from all the others.

## Level 6: Quantity Rules, min(), Shared Legs, Depth, and Recomputation

The min() rule from Level 3 generalises, and the generalisation is where implementations start to acquire bugs.

**Shared legs.** Suppose a second spread bidder joins Level 3's original books:

| Book | Side | Price | Lots | Who |
|---|---|---|---|---|
| January | Ask | $75.00 | 50 | Trader A |
| Spread | Bid | −$2.00 | 30 | Trader B |
| Spread | Bid | −$2.00 | 15 | Trader H |

Both spread bids combine with the *same* January ask to imply February asks at $77.00. The correct implied quantity is min(50, 30 + 15) = **45**. Here that happens to equal the naive calculation min(50, 30) + min(50, 15) = 45, which is exactly why the naive calculation survives code review. Now shrink A's order to 40 lots. The correct answer is min(40, 45) = **40**. The naive "pairwise min, then sum" still says 30 + 15 = 45 and over-advertises by 5 lots that do not exist. A's January order is a **shared leg**: every construction that uses it draws from the same 40 lots.

The general statement: *the implied quantity is the largest quantity that can be routed through the contributing orders simultaneously, with no order used beyond its own size.* For a single chain that is the smallest ingredient; when chains share an order, the shared order caps their total. (Readers who know graph algorithms will recognise a maximum-flow problem; for first-generation implieds between two months it reduces to the simple sums and mins shown here.)

**Depth beyond the best price.** Books have more than one price level, and so do implied books. Suppose:

| Book | Side | Price | Lots |
|---|---|---|---|
| January | Ask | $75.00 | 10 |
| January | Ask | $75.01 | 20 |
| Spread | Bid | −$2.00 | 15 |
| Spread | Bid | −$2.02 | 10 |

Each implied February lot costs (January ask) − (spread bid), so the cheapest February lots come from pairing the cheapest January lots with the most generous spread bids. The correct implied February ask ladder is built by walking both ladders together, best against best, exactly like a merge of two sorted lists:

| Implied Feb ask | Lots | Built from |
|---|---|---|
| $77.00 | 10 | Jan 75.00 (all 10) with spread −2.00 (10 of 15) |
| $77.01 | 5 | Jan 75.01 (5 of 20) with spread −2.00 (remaining 5) |
| $77.03 | 10 | Jan 75.01 (10 of remaining 15) with spread −2.02 (all 10) |

Total: 25 lots, which equals min(30 January lots, 25 spread lots), as conservation demands. Notice what is *missing*: a naive implementation that pairs every January level with every spread level independently would also publish **$77.02 × 10** (Jan 75.00 with spread −2.02). That quote is fictitious: the January lots at $75.00 are already committed to the $77.00 level. Buy everything the naive ladder shows and the engine runs out of January oil before the order is filled. Because a correct implied depth ladder is *path-dependent* in this way, venues typically compute and publish only the top one or two implied levels (see Level 10).

**Recompute, never decrement.** After any event that touches a contributing order (a fill, a cancel, an amendment, a new order at a better price), the engine re-derives the affected implied quotes from the current state of the real books. Level 3's post-trade figure (implied 10 = min(30, 10)) is a recomputation, not "30 minus 20". The two happen to agree there, but Exercise E6 shows a case where they do not.

## Level 7: Priority, Real Orders Before Implied Orders

Suppose the February book contains both a real resting ask and an implied ask at the same price:

| February book | Price | Lots | Source |
|---|---|---|---|
| Ask | $77.00 | 5 | **Real**, Trader G, resting since 09:31 |
| Ask | $77.00 | 30 | Implied (A + B, as in Level 3) |

Trader C's order to buy 20 at $77.00 arrives. Who fills?

On CME, the answer for futures is explicit: "Outrights (generation 0) always trade first, then followed by spreads (1st generation)" [CME Group Client Systems Wiki, *Futures Implied Order Matching Priority*], and "implied quantity in futures markets does not have time priority" [CME, *Implied Orders*]. So at the same price, **real orders trade before implied orders**, no matter how long the implied quote has been displayed. C's order therefore fills 5 lots against G (an ordinary two-party trade) and 15 lots through the implied construction (the three-fill atomic execution from Level 3).

The rationale mirrors the displayed-before-hidden logic from the *Order Types* chapter: a participant who committed directly in this book is rewarded ahead of a price that is only a reflection of commitments elsewhere. There is also an engineering benefit: a two-party fill is cheaper and simpler than a multi-book atomic one, so using real liquidity first minimises the expensive path. When several *implied* constructions compete at the same price, CME breaks the tie with a documented sequence of criteria (strategy type, product codes, leg expirations, number of legs, and finally instrument identifiers), not by time. Treat "real before implied at the same price" as the strong default, and each product's rulebook as the authority.

Two further rules on CME are worth building in from day one [CME, *Implied Orders*]:

- **"Implication requires at minimum two orders in related markets in the proper combination."** An implied quote is never built from a single order.
- **"Implied bids do not trade against implied offers."** Every trade needs at least one real, *incoming* order as the aggressor. Implied quotes are only ever passive: they wait to be hit. We will see why this rule is natural in Level 8.

## Level 8: Price Improvement and Closing Cross-Book Gaps

Implication does not just fill empty books; it can *beat* the real book. Suppose:

| Book | Side | Price | Lots |
|---|---|---|---|
| January | Ask | $74.95 | 40 |
| Spread | Bid | −$2.00 | 25 |
| February | Ask (real) | $77.00 | 60 |

The implied February ask is 74.95 − (−2.00) = **$76.95**, which is 5 ticks ($0.05, or $50 per lot) *better* than the real February ask. An incoming order to buy 20 February at $77.00 fills all 20 at $76.95 through the implied construction, and the real $77.00 seller is not touched. The buyer receives price improvement exactly in the sense of the *Order Types* chapter: they were willing to pay $77.00 and paid $76.95.

**Closing gaps that would otherwise be free money.** Now add one more resting order: Trader K bids $76.97 for 10 February lots. Is anything wrong with these books?

| Book | Side | Price | Lots |
|---|---|---|---|
| January | Ask | $74.95 | 40 |
| Spread | Bid | −$2.00 | 25 |
| February | Bid (real, Trader K) | $76.97 | 10 |

Yes: they are **crossed across books**. K will buy February at $76.97, while the January seller and B together will sell February at $76.95. In a single book, a bid above an ask can never rest (the incoming one would have traded). Across books, without implied functionality, it can. And then it is free money for whoever notices first. An arbitrageur could:

1. Sell 10 spreads to B at −$2.00 (sell January at some price p, buy February at p + 2.00),
2. buy 10 January from A at $74.95, and
3. sell 10 February to K at $76.97.

The arbitrageur's January trades cancel, the February trades cancel, and the cash is p − 74.95 + 76.97 − (p + 2.00) = **+$0.02 per barrel**, $20 per lot, with no risk, provided all three fills happen before anyone else acts.

With implied functionality this state can never arise, because it could only be reached through an *arrival*, and the arriving order is matched when it arrives. Suppose K's bid rested first and B's spread bid is the last of the three orders to arrive. At that moment the engine already publishes an implied spread **ask** built from A's January ask and K's February bid: Jan_ask − Feb_bid = 74.95 − 76.97 = **−$2.02**. B's incoming bid of −$2.00 is willing to pay up to −2.00, and −2.02 is cheaper, so B trades immediately:

1. B buys 10 January from the January seller at $74.95.
2. B sells 10 February to K at $76.97.
3. B's spread fill prints at 74.95 − 76.97 = **−$2.02**, two ticks better than B's limit.

K's bid is now used up, so the implied spread ask disappears, and B's remaining 15 spreads rest as a bid at −$2.00 (where, together with the 30 January lots still offered, they again imply a February ask at $76.95 × 15).

The $0.02 that an arbitrageur would have pocketed goes instead to B, a real participant, as price improvement. This is the deeper purpose of implied functionality: it keeps the whole *family* of related books mutually consistent, so that cross-book gaps are closed by the exchange on behalf of resting orders rather than harvested by the fastest outsider.

It also explains the rule "implied bids do not trade against implied offers". If an implied bid ever crossed an implied offer, some set of *real* orders would be crossed through a cycle of books. But every real order was matched against everything it could reach at the moment it arrived. So a crossed cycle can only exist if the engine missed a match at an earlier arrival, a bug, not a situation the matching rules need to handle.

## Level 9: Tick Alignment and Leg Prices, Where Arithmetic Meets Reality

The formulas of Level 2 are exact arithmetic; real books live on price grids. Two complications follow, both descendants of the *Tick Sizes and Fractional Ticks* chapter.

**Spread grids can differ from outright grids.** Some venues list a spread on a finer tick grid than its legs, because spreads move less than outright prices. The moment the grids differ, an implied outright price computed from a spread price may land *between* valid outright ticks. For illustration, take a hypothetical product whose outright tick is 0.25 and whose spread tick is 0.05:

```
January ask        100.00   (valid outright tick)
Spread bid          −0.35   (valid spread tick)
Implied Feb ask  = 100.00 − (−0.35) = 100.35   ← not a multiple of 0.25
```

The engine cannot print a February trade at 100.35. The standard remedy is to **round outwards**, meaning in the direction that is worse for the party trading against the implied quote: an implied ask is rounded *up*, an implied bid *down*. So the implied Feb ask is published at **100.50**. Carruthers' analysis of CME's Treasury inter-commodity spreads describes exactly this rule: "For price-priority purposes, implied prices are rounded outwards to the nearest tick", with direct liquidity at the rounded price keeping priority over implied liquidity [Carruthers, *Inter-Commodity Spreads and Implied Pricing*, 2018].

Who gets the 0.15 difference when someone buys February at 100.50? Follow the money through the construction: the February buyer pays 100.50; A sells January at 100.00; so B's spread executes at 100.00 − 100.50 = **−0.50**. B was willing to buy the spread at −0.35 or lower, and −0.50 is lower, so B receives the 0.15 as price improvement. Every party trades at or better than its own limit, and all prints are on their grids (−0.50 is a valid 0.05 spread tick). Rounding outwards is what guarantees this: it never forces any real order to trade worse than its limit.

Whatever the rounding rule, it must be documented and implemented in **exactly one function**, shared by matching, market-data publication, and clearing. Two components that round differently will disagree about which prices exist.

**Leg prices must land on-tick and inside limits.** Every leg of every implied execution needs a price that is (a) a valid tick for its instrument, (b) consistent with every order involved, so that each spread's legs still differ by exactly its trade price, and (c) inside that instrument's price limits for the session. In the first-generation examples above, the real outright orders pin down the leg prices naturally. In the multi-layer constructions of the next chapter, some legs trade only *between two spread orders*, where no real outright price exists, and the engine must manufacture one by rule. Venues publish these leg-pricing algorithms. An engine that assigns an off-tick or out-of-limits leg price produces trades that clearing systems reject, a far worse failure than refusing the implied match up front.

## Level 10: How Implied Liquidity Appears in Market Data

Participants need to know that implied liquidity exists, and sophisticated participants need to know *which part* of a displayed quantity is implied, because an implied quote can vanish for reasons invisible in its own book (one of its ingredients in another book was cancelled or filled). Venues handle this in one of three ways:

1. **Publish implied quotes as a separate book** next to the real book. CME's MDP 3.0 market data feed disseminates a "2-deep best bid and ask ... for each implied-eligible futures contract" as a distinct implied book [CME Group Client Systems Wiki, *MDP 3.0 – Implied Book*], and documents how a client should consolidate it with the real book.
2. **Aggregate real and implied quantity** into one displayed number per price level.
3. **Show only the real book**, and let implied liquidity surface only at execution.

A market-data consumer must know which policy a venue uses, or its reconstructed book will disagree with the venue's, a classic source of "our depth doesn't match the exchange's" support tickets. And recall Level 6: implied depth beyond the first level or two is path-dependent, which is one reason venues keep the published implied book shallow.

## Engineering Deep-Dive

With the mechanics established, the engineering can be stated precisely.

### A minimal first-generation algorithm

For one pair of months (January, February) and their spread, the whole of implied matching fits in a page of pseudocode. Prices are signed integer ticks throughout.

```
# Real books: jan, feb, spr. Each side is a price-time-ordered queue of real orders.

function implied_quotes():                      # recomputed after EVERY event in the group
    return {
      FEB_ASK: pair(jan.asks, spr.bids, price = a.price - b.price),   # Jan_ask - S_bid
      FEB_BID: pair(jan.bids, spr.asks, price = a.price - b.price),   # Jan_bid - S_ask
      JAN_ASK: pair(feb.asks, spr.asks, price = a.price + b.price),   # Feb_ask + S_ask
      JAN_BID: pair(feb.bids, spr.bids, price = a.price + b.price),   # Feb_bid + S_bid
      SPR_ASK: pair(jan.asks, feb.bids, price = a.price - b.price),   # Jan_ask - Feb_bid
      SPR_BID: pair(jan.bids, feb.asks, price = a.price - b.price),   # Jan_bid - Feb_ask
    }
    # pair() walks both ladders best-first (the merge of Level 6), emitting
    # (implied_price, qty, [ingredient orders]) and never using an order's quantity twice.
    # Round each implied price outwards to its book's grid (Level 9).

function on_incoming(order):                    # order is always REAL: implied never aggresses
    while order.qty > 0:
        real = best_real_opposite(order.book)
        impl = best_implied_opposite(order.book, implied_quotes())
        best = better_price(real, impl, tie -> real)   # real before implied (Level 7)
        if best is none or not marketable(order, best): break
        if best is real:
            fill_two_party(order, best)
        else:
            q = min(order.qty, impl.qty)
            validate_all_legs(impl.ingredients, q)      # ticks, limits, risk: all or nothing
            commit_atomically(order, impl.ingredients, q)  # N fills, one sequence number
        # loop re-reads books and recomputes implied quotes: never decrements them
    rest_or_cancel_remainder(order)
    publish_real_and_implied_market_data()
```

Everything else in this section explains why each line of that pseudocode is the way it is.

**Recalculation triggers and fan-out.** Every order event on any instrument in a related group (new order, cancel, amendment, partial fill) can change implied quotes in every *other* book of the group. One cancelled spread order can move implied prices in two outright books at once, each change generating market data. Implied-enabled products therefore have a structurally higher ratio of market-data messages to order messages, which must be budgeted in the publishing path, not discovered in production.

**Atomicity.** All legs of an implied match commit together or not at all. The single-threaded-per-book design from *The Matching Engine* chapter now shows its limits: an implied match spans several books. Either the whole related group of instruments is assigned to one sequencing thread (the common production choice: "partition by symbol" becomes "partition by *related instrument group*"), or a cross-book commit protocol is required, with all the latency and complexity that implies.

**Double-execution prevention.** Trader A's January order participates in the January book *and*, simultaneously, in the implied February ask. If a January buyer and a February buyer arrive in adjacent events, both paths claim A's lots, and only one may win. Serialised processing within the instrument group resolves this naturally: whichever event is sequenced first consumes the lots, and recomputation (Level 6) shrinks or removes the implied quote before the second event is processed. Any design that evaluates implied quotes against a stale copy of the contributing books reintroduces the race.

**Determinism.** Implied recomputation must itself be deterministic: given the same event sequence, the same implied quotes must appear, in the same order, with the same rounding. Iterating over candidate combinations in hash-map order, or letting floating-point arithmetic creep into spread prices, breaks the replay guarantees of the *Determinism, Replay, and Persistence* chapter.

**Testing invariants.** Implied logic is an ideal target for property-based testing, because its correctness conditions are crisp global invariants rather than example-shaped assertions:

1. *Conservation:* every implied execution's fills sum to zero in every instrument and in cash (Level 3), and no real order's quantity is ever consumed twice or driven negative.
2. *Firmness:* every published implied quote is executable at that instant: each ingredient exists with sufficient quantity, including shared legs (Level 6).
3. *Grid consistency:* no published implied price and no assigned leg price is off-grid for its book (Level 9).
4. *No cross-book crossing:* after every event, no combination within the enabled implication depth is crossed (Level 8).
5. *Removal:* cancelling any single ingredient removes or correctly shrinks every implied quote built on it, within the same event.
6. *Limits respected:* every party to every implied execution trades at or better than its own limit price.

A fuzzer that generates random order flow across three related books and asserts these six properties after every event will find more implied-matching bugs than any hand-written example suite.

> **Key idea:** Implied orders are not free liquidity. They are the engine expressing, in one book, commitments already resting in others, so that related markets stay consistent, empty months stay tradeable, and cross-book price gaps are closed by the exchange rather than harvested by the fastest participant. When an implied order matches, real orders in real books are consumed, exactly once, atomically. Everything difficult about implementing implied orders (shared-leg quantities, depth, priority, tick rounding, fan-out, double-execution races) follows from taking that atomic, exactly-once consumption seriously.

## Real-World Implementations

**CME Globex** is the reference implementation for futures: implied IN and implied OUT per product, implied depth disseminated on MDP 3.0, and per-product documentation of which implied types are enabled. CME has extended implied functionality steadily for two decades; in 2004, for example, it announced that its revised implied functionality would "link contract liquidity in butterfly spread trades on GLOBEX with that in underlying markets" for Eurodollar futures, then among the most actively traded futures in the world [CME press release, 8 March 2004]. **Eurex T7** offers the same idea under the name *synthetic matching*: "orders of different simple and complex instruments are executed against each other", supported for futures spreads and inter-product spreads [Eurex, *Matching principles*]. **ICE Futures** runs implied pricing across its energy futures and their spreads, including implied prices derived from other implied prices, the subject of the next chapter [ICE, *ICE Futures Implied Prices* FAQ]. The vocabulary differs from venue to venue; the three-book mechanics of this chapter are the common core.

## Self-Check Exercises

*Answers follow; attempt each before reading on. Convention throughout: S = Near − Far, and all prices are per barrel with a $0.01 tick.*

**E1.** January: bid $74.20, ask $74.60. February: bid $76.10, ask $76.55. The spread book is empty. Compute the implied Jan/Feb spread bid and ask.

**E2.** The only two orders in the market are a February bid at $76.40 × 12 lots and a Jan/Feb spread ask at −$1.80 × 20 lots. What implied quote do they create, at what price and quantity?

**E3.** In Level 3's original books, Trader C instead submits an order to buy 40 February at $77.00. Describe the outcome, including every book afterwards.

**E4.** January ask $75.00 × 10; two spread bids at −$2.00 of 8 and 6 lots. What implied February quantity is published at $77.00, and why is 8 + 6 = 14 the wrong answer?

**E5.** You bought 3 Jan/Feb spreads at +$0.40. The spread now trades at +$0.15. What is your profit or loss, in dollars? (1 lot = 1,000 barrels.)

**E6.** A colleague's implementation decrements implied quantities on fills in the implied book instead of recomputing them, "for performance". Give a concrete sequence of events in which this publishes a quote the engine cannot honour.

**E7.** The books hold: January ask $75.10 × 10 and a spread bid of −$2.00 × 10, plus a real February bid of $77.05 × 10 that arrived last. What happens when the February bid arrives, and at what prices?

&nbsp;

<div style="page-break-after: always;"></div>

&nbsp;

### Solutions

**E1.** Implied S_bid = Jan_bid − Feb_ask = 74.20 − 76.55 = **−$2.35**. Implied S_ask = Jan_ask − Feb_bid = 74.60 − 76.10 = **−$1.50**. Sanity check: the implied spread market is 0.85 wide, which is the January bid-ask width (0.40) plus the February width (0.45). Trading the spread through the outrights means paying both outright spreads at once.

**E2.** This is a trap, and the trap is the point: **these two orders imply nothing.** Add the vectors. The February bid is (Feb +1). The spread ask is a committed spread *seller*: (Jan −1, Feb +1). Their sum is (Jan −1, Feb +2), which cancels nothing and is not the shape of any single order. In words: the spread seller needs to *buy* February to complete its legs, and the only February order present is another *buyer*. Cross-check against the Level 2 table: Feb_bid pairs with S_**bid** (implied Jan bid), and S_ask pairs with Feb_**ask** (implied Jan ask) or Jan_**bid** (implied Feb bid); "Feb_bid + S_ask" appears in no row. If you mechanically computed 76.40 + (−1.80) = $74.60 and published it as an implied January quote, you manufactured a price with nothing executable behind it, precisely the class of bug that testing invariant 2 exists to catch.

**E3.** The implied ask at $77.00 is 30 lots (min(50, 30)). C fills 30 lots through the three-fill construction: A sells 30 January at $75.00, B's spread fills 30 at −$2.00 (B's order is now complete), and C buys 30 February at $77.00. With B's order gone, the implied February ask recomputes to nothing, so C's remaining 10 lots rest as a real February bid at $77.00. Afterwards: January ask $75.00 × 20 (A); spread book empty of real orders; February bid $77.00 × 10 (C). And one more thing happens, which is easy to miss: C's new February bid is itself an ingredient. Together with A's January ask it implies a spread **ask** at Jan_ask − Feb_bid = 75.00 − 77.00 = **−$2.00**, quantity min(20, 10) = **10**. Every new real order is a candidate ingredient in every related book.

**E4.** Published quantity = min(10, 8 + 6) = **10**. The January ask is a shared leg: both spread bids route their February selling through the same 10 January lots, so together they can deliver at most 10. Pairwise-min-then-sum (min(10, 8) + min(10, 6) = 14) counts the shared leg twice and over-advertises by 4 lots that the engine could not deliver if a buyer took them.

**E5.** The spread price fell from +0.40 to +0.15, a change of −0.25 per barrel. You are long the spread, so you lose: −0.25 × 1,000 barrels × 3 lots = **−$750**. (Check with legs: suppose you bought January at $76.40 and sold February at $76.00; later January is $76.00 and February $75.85. January: −0.40; February short: +0.15; net −0.25 per barrel.)

**E6.** Books: January ask $75.00 × 20 (A); spread bid −$2.00 × 20 (B), so implied February ask $77.00 × 20. Event 1: an ordinary January buyer takes 15 of A's lots. A has 5 left, so the true implied quantity is min(5, 20) = 5. The decrement-only implementation saw no fill *in the February implied book* and still advertises 20. Event 2: a February buyer sends an order to buy 12 at $77.00. The engine can construct only 5 lots: it must either reject a fill against a quote it published, fill against a phantom, or (worst of all) begin an atomic commit that cannot complete. Recomputation on every event in the group is not an optimisation opportunity; it is the correctness mechanism.

**E7.** Before the February bid arrives, the engine publishes an implied February ask of 75.10 − (−2.00) = $77.10 × 10. The incoming bid of $77.05 is below $77.10, so it does **not** cross: nothing trades, and the bid rests. Now look for implied quotes involving the new order: January ask plus February bid imply a spread ask of 75.10 − 77.05 = **−$1.95**, and B's resting spread bid is −$2.00, which does not reach −1.95 either. The books are consistent and nothing trades. (Had the February bid been $77.10 or higher, it would have traded 10 lots at $77.10 through the implied construction. The price is always the *resting* side's price, and here the resting side is the implied ask.)

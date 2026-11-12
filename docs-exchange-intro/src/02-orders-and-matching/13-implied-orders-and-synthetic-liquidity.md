# Implied Orders and Synthetic Liquidity

This concept trips up almost every developer who meets a derivatives exchange for the first time, and for good reason: it is the first place in this book where a single incoming order can trade against orders resting in *other* order books. The arithmetic is school-level, but it arrives wrapped in an unusual sign convention, the quantity rules are less obvious than they look, the priority rules are subtle, and the engineering consequences are severe. This chapter therefore climbs in explicit levels. Each level introduces one new idea and works it through with numbers before the next level begins. The numbers carry over from level to level, so read every example even when the idea feels obvious.

By the end of the chapter you should be able to write a correct first-generation implied-matching module: compute implied prices and quantities, execute them atomically, keep them consistent as the books change, and test them. The chapter after this one then asks the obvious follow-up question, *why not imply from implied orders, and from those, and so on?*, and shows why every exchange stops after a few steps.

One promise before we begin, which the rest of the chapter proves over and over: **implied orders do not create liquidity out of nothing.** An implied order is a different *view* of commitments that already rest in other books. It never adds a single lot to the total that can be traded; it only makes existing lots reachable from one more place. Hold on to that sentence. Every level below is, in the end, a demonstration of it.

Implied orders are almost exclusively used in the derivatives markets (specifically forwards and futures), where multiple related instruments exist for the same underlying asset, such as different futures contracts for various delivery months or spreads between them. In Swedish both futures and forward contract are commonly known as "terminskontrakt" or "terminer". As Swedish only have one name for what in English are two distinct instruments, it is important to keep the context in mind when discussing them. In reality every Swedish trader uses the English terms when necessary to avoid ambiguity.

## Why Implied Orders Exist, and Where They Came From

Before any arithmetic, it is worth seeing the problem that implied orders solve, because once the problem is clear the solution feels almost inevitable.

### The problem: too many books, too little liquidity in each

A futures exchange does not list one crude oil contract; it lists one per delivery month, often for years ahead. Traders also want to trade the *differences* between months (you will see why in Level 0), so the exchange lists spread instruments as well, each with its own order book. Count what that means for a modest strip of 12 monthly contracts: 12 outright books, and up to 12 × 11 / 2 = 66 calendar-spread books if every pair of months is listed. That is 78 books for what is, economically, one commodity.

![Twelve delivery months, and a spread between every pair of them. Each circle is an outright book and each line is a calendar-spread book: 12 + 66 = 78 separate order books for one commodity.](assets/implied-78-books-small.png)

The traders, however, do not multiply. The same population of buyers and sellers is now spread thinly across 78 queues, and each queue can only match orders that happen to arrive in *that* queue. Three symptoms follow, and each will reappear later in this chapter with numbers attached:

1. **Empty or thin books.** A trader who wants to buy a far-dated month may find its book empty. Yet other participants may be perfectly willing to sell that month. They just expressed that willingness as *part* of an order in a different book, so it never shows up where the buyer is looking. The example below shows how that can happen.
2. **Leg risk.** A trader who wants a spread, and finds the spread book empty, can build it by trading the two months separately. Between the two trades the market can move, and the trader may end up with one half of the position and not the other.
3. **Inconsistent prices.** Because nothing connects the books, their prices can drift out of line with each other, creating risk-free gaps that only the fastest arbitrageur can collect.

### An example: the seller who is in the wrong book

The first symptom sounds like a contradiction: how can nobody be offering February if somebody is willing to sell it? The answer is that a willingness to sell February does not have to be a February order. Consider three order books, each a separate queue in the matching engine, and three traders:

| Book | Resting order | Who | What the trader actually wants |
|---|---|---|---|
| January | Sell 50 lots at $75.00 | Trader A | To sell January oil. |
| Jan/Feb spread | Buy 30 spreads, February at least $2.00 above January | Trader B | To buy January **and** sell February in one go, as long as February sells for at least $2.00 more than January costs. |
| February | *empty* | | |

A spread order is a single instruction covering two months at once (the next sections explain why traders want them and how they are priced). The point to notice here is that Trader B's order, although it sits in the spread book, *contains a sale of February*. B is a February seller with a condition attached: B will only sell February if B can buy January at the same moment, at least $2.00 cheaper.

Now Trader C arrives, wanting to buy 20 lots of February. C has no interest in January or in spreads and, quite reasonably, looks only at the February book. It is empty. Without help from the exchange, C concludes that nobody will sell February today.

But look at the three books together:

- B is willing to sell February, *provided* B can buy January at the same time for $2.00 less.
- A is willing to sell January at $75.00, so B's condition can be met: B buys January from A at $75.00.
- B can then sell February at $75.00 + $2.00 = **$77.00**, and that is exactly what C wants to buy.

So a February seller at $77.00 does exist. It is just split across two orders in two other books, and neither of them, on its own, looks like a February offer. C should not have to know about the January book or the spread book, and that is precisely the problem. Nothing in C's own book tells C that a seller is available, and even a C who spotted the opportunity would have to coordinate trades in other books to reach it.

An exchange with implied orders does that work for C. It notices that A's January offer and B's spread order *together* amount to an offer to sell February, and it displays that offer in the February book: **sell 30 lots of February at $77.00**, the quantity limited by the smaller of the two ingredients (B's 30 spreads). When C buys 20 lots, the engine executes all three pieces at once: A sells January to B, B completes its spread, and C receives February. From C's point of view it was an ordinary February trade. B's spread order is now partly filled: 20 of its 30 spreads are done, and the other 10 simply stay in the spread book, exactly as any partly filled limit order would. So the February book keeps showing an implied offer of 10 lots at $77.00 for the next buyer. Level 3 works through this exact example in full, once we have the vocabulary to do it precisely.

![The three books and the three traders. The engine shows C an implied February offer built from A's and B's orders. When C buys, the oil moves from A to B (January) and from B to C (February).](assets/implied-wrong-book-small.png)

Notice who actually traded with whom. C never dealt with A. C bought February from B, and B bought January from A. A's role was indirect: B was only willing to sell February if it could buy January at the same moment, so A's January offer was what made B's February sale possible. It was a precondition for C's trade, not a part of it. And notice what did *not* happen: no new oil appeared. The February that C bought came from B, who was willing to sell it all along; the engine merely supplied the January purchase that B's order required. This idea, that implied orders connect existing liquidity rather than create new liquidity, runs through the whole chapter.

On a trading floor, the connection between a spread and its legs could be made by people: a trader who heard a spread bid and an outright offer could combine them mentally and act on both. An electronic order book has no such person. Each book is an isolated queue, unless the matching engine itself connects them. **Implied orders are that connection**: the engine continuously asks "which combinations of orders resting in *other* books would amount to an order in *this* book?", displays the answer, and lets it trade. A 2001 patent filing by the New York Mercantile Exchange describes the purpose in one line: implied orders are generated "to provide order combinations which could not be directly entered into a trading system" [US Patent 7,039,610].

### A short history

The precise date and venue of the very first implied order is not well documented in public sources, so this section sticks to what primary documents show.

- **By 2001, first-generation implication was established practice.** The background section of NYMEX's patent application *Implied market trading system* (filed 4 October 2001 by Matt N. Morano, Iain West and Kai Neumann) already treats implied orders derived from real outright and spread orders as known technology. The invention it claimed went one step further: deriving implied markets from other implied, or even non-tradeable "bridge", markets, so as to create "all implied markets that are inherent in the combination of futures, calendar spread and inter-commodity spread real orders" [US Patent 7,039,610, granted 2 May 2006]. The patent was later assigned to the International Petroleum Exchange of London, which became ICE Futures and then ICE Futures Europe. Chaining implied orders in this way is exactly the subject of the next chapter.
- **2003–2004: implied spreads help move Eurodollars to the screen.** CME's Eurodollar futures, then the world's most actively traded short-term interest rate contract, were still traded almost entirely in the Chicago pit: electronic trading accounted for "nearly 4 percent" of total Eurodollar volume in 2003. CME had expanded Globex functionality "to improve spread trading capabilities for Eurodollar futures" in January 2003 [CME news release, 12 January 2004]. By March 2004 Globex offered implied calendar spreads for Eurodollars across "the first five years of the yield curve" [CME press release, 8 March 2004], and in October 2004 CME added implied butterfly spreads, generating both implied IN and implied OUT prices, "unlike most other futures exchanges". In the same release CME reported that Globex carried about 65 percent of Eurodollar futures volume in September 2004 [CME press release, 18 October 2004]. Many factors drove that migration, but CME's own announcements consistently presented spread and implied functionality as part of making the electronic market usable for the spread-heavy trading that dominated Eurodollars.
- **Today: a standard feature of futures venues.** CME Globex, ICE Futures and Eurex (under the name *synthetic matching*) all offer implied functionality, each with its own rules about which combinations are implied; the *Real-World Implementations* section at the end of this chapter summarises them.

The pattern behind this history is the one this chapter will make precise: once trading moves from people to an engine, the engine must take over the job of connecting related books, or liquidity fragments and spread traders stay away. With the motivation in place, we can start building the machinery.

## Level 0: Futures in One Page

You do not need a finance background for this chapter, but you do need four facts about futures.

**1. A futures contract is a promise, not a purchase.** A futures contract is a standardised agreement to buy or sell a fixed quantity of something (crude oil, wheat, a stock index) at a price agreed *today*, for delivery on a fixed date in the *future*. Nothing changes hands at the moment of the trade except a good-faith deposit (the *margin*, covered in the clearing chapter of Part III). If you agree to buy, you are **long**; if you agree to sell, you are **short**. If the price later rises, the long side gains and the short side loses the same amount, and vice versa. Futures are a zero-sum game between the two sides of each trade.

**2. Everything in this chapter uses crude oil.** The running example is modelled on NYMEX WTI Light Sweet Crude Oil futures (symbol CL) at CME Group. One contract, also called one **lot**, covers **1,000 barrels**. Prices are quoted in **US dollars per barrel**, and the minimum price step (the **tick**, see the *Tick Sizes* chapter) is **$0.01 per barrel, worth $10 per contract** [CME Group, NYMEX Rulebook Chapter 200]. So when this chapter says "a price of $75.00", it means $75.00 per barrel, and one lot at that price represents $75,000 worth of oil.

**3. Every delivery month is a separate instrument with its own order book.** January crude and February crude are *different products*: different delivery dates, different buyers and sellers, different prices. An exchange lists many months at once, and each month has its own independent order book exactly like the ones in the *Order Book* chapter. Throughout this chapter we use two of them, **January** (the *near* month, delivered sooner) and **February** (the *far* month). An ordinary order for a single delivery month is called an **outright** order, and its book an outright book, to distinguish it from the spread instruments introduced next.

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

A negative price is not an error code, and your engine must not treat it as one. Nor are negative prices limited to spreads. On 20 April 2020, with storage at the Cushing, Oklahoma delivery point nearly full and the May 2020 WTI contract one day from expiry, May crude *settled at −$37.63 per barrel* [CFTC, Interim Staff Report, November 2020], while the June contract closed at $20.43 [Congressional Research Service, IN11354]. Holders of May contracts were, in effect, paying people to take oil off their hands, and the May/June spread was roughly −$58 per barrel. CME had warned its clearing members in early April that some energy contracts could trade below zero and had opened a test environment for negative prices [CME Clearing Advisories 20-152 and 20-160, April 2020]. Not every system was ready. The CFTC later found that at one large retail broker "negative prices were not displayed to customers and customers were unable to place orders with negative-priced limit orders", and ordered it to pay a $1.75 million penalty plus about $82.6 million in restitution to customers [CFTC press release 8432-21, 28 September 2021]. An assumption of `price > 0`, buried in one validation function, turned out to be an eight-figure bug.

**Confusion 2: "higher" and "better" need care.** −1.50 is *higher* than −2.00. A spread bid of −1.90 is therefore a *better* (more generous) bid than −2.00, and a spread ask of −2.10 is a better (cheaper) ask than −2.00. Price-time priority works exactly as in any other book, provided your comparison operators are signed. Storing spread prices as signed integer tick counts (−200 ticks for −$2.00) makes this automatic.

**Confusion 3: buying the spread *sells* the far month.** A spread *buyer* is a *seller* of February. So a resting spread **bid** is, among other things, a standing offer to **sell** February. This side-flip is the single most important fact in this chapter, and it is where most implementation bugs come from.

**Confusion 4: subtracting a negative number adds.** Because S = Jan − Feb, it follows that Feb = Jan − S. With S = −2.00 and Jan = 75.00, Feb = 75.00 − (−2.00) = **77.00**. Every time you see "minus a spread price" in this chapter, check the sign twice.

> **Sign-convention cheat sheet.** Keep this box at hand; every formula in the chapter follows from it.
>
> - S = Near − Far = Jan − Feb. Rearranged: Feb = Jan − S, and Jan = Feb + S.
> - **Buy** one spread = buy 1 Jan + sell 1 Feb. Profits when S *rises*.
> - **Sell** one spread = sell 1 Jan + buy 1 Feb. Profits when S *falls*.
> - "Higher" always means "further towards +∞": −1.50 > −2.00 > −2.50.
> - The best bid is the *highest* signed price; the best ask is the *lowest* signed price.
> - A spread bid is (also) an offer to sell Feb; a spread ask is (also) a bid to buy Feb.

![The sign convention in one picture. Top: S is the step from the far month (February) to the near month (January). It is negative in contango and positive in backwardation. Bottom: spread prices are ordinary signed numbers, so "higher" means further right, even below zero.](assets/implied-sign-convention-small.png)

> **Convention warning.** Near-minus-far is the norm for calendar spreads on CME, and most futures venues use the same convention, but it is not a law of nature. Inter-commodity spreads, ratio spreads, and some venues' products define their price differently (some as a ratio of legs, some with legs weighted 2:3, and so on). CME's Treasury inter-commodity spreads, for instance, are not quoted as a simple difference of leg prices at all, but as a ratio-weighted difference of each leg's net change since the previous day's settlement [Wilson, CME Group, *Liquidity in implied inter-commodity spread markets*, 2024]. Always read the product's definition before writing a single formula.

### Leg prices

When a spread trades at −$2.00, the clearing house still needs a concrete price for each leg, because positions, profit and loss, and margin are tracked per month. The exchange assigns leg prices using a documented rule. On CME, for example, one leg is anchored to a recent reference price for that month (its latest trade price, a current price indication, or its settlement price) and the other leg is derived so that the two legs differ by exactly the spread price [CME Group, *Treasury Futures Calendar Spreads*]. The spread traders' economics depend only on the difference; the leg prices exist so every system downstream can do per-instrument bookkeeping. We will return to leg prices at Level 9, where they stop being a formality.

## Level 2: The Developer's Model, Orders as Vectors

The rest of the chapter becomes mechanical, and much easier to implement correctly, once you describe every order with two pieces of information.

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

![The same addition drawn as blocks. Green is a purchase (+1), red a sale (−1). In the January column the two blocks cancel; what remains is a sale of one February lot for $77.00.](assets/implied-vector-sum-small.png)

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

Check the sign-flip from Confusion 3 in the table: an implied February **ask** is built from a spread **bid**. The rule of thumb: an implied **near-month** (January) quote has the *same* side as the spread order inside it (Jan ask uses a spread ask, Jan bid uses a spread bid), while an implied **far-month** (February) quote has the *opposite* side (Feb ask uses a spread bid, Feb bid uses a spread ask).

The whole table fits in one picture. There are only three books, and any two of them can imply a quote in the third:

![Three books, any two imply the third. Each row highlights one target book (dashed) and the two books whose orders feed it, with the bid and ask formulas for that target.](assets/implied-triangle-small.png)

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

**What happens to B's other 10 spreads?** Nothing dramatic: they stay where they were. B's spread order is an ordinary resting limit order, and, as with any resting limit order (see the chapters on order types and the order book), a partial fill leaves the remainder in the book at the same price and with its time priority intact. After C's trade, B holds a 20-lot spread position and still has a working order to buy 10 more. Three consequences follow:

1. **The implied quote shrinks; it does not disappear.** The engine recomputes the February offer from what is left of its ingredients: min(30 January lots, 10 spreads) = 10 lots at $77.00. The next February buyer can take those 10, or a January/February spread seller can trade directly against B's 10 in the spread book. Whichever arrives first gets them, and once they are gone the implied February offer disappears too.
2. **B is never left half-hedged.** This is why a partial fill is acceptable to B. Each of the 20 spreads B bought came as a complete pair, one January bought and one February sold, both filled in the same atomic event. A partial fill leaves B with *fewer* spreads than wanted, but never with an unmatched January or February leg. That is exactly the leg risk B used a spread order to avoid, and implication does not reintroduce it.
3. **B stays in control.** B can cancel the remaining 10 spreads at any moment. The engine then withdraws the implied February offer, because one of its ingredients has gone.

**What if B would not accept a partial fill?** The conditions that refuse partial fills, Fill-Or-Kill and Immediate-Or-Cancel, apply only to orders that execute on arrival. Such orders never rest in a book, so they never become ingredients of an implied quote. An order only becomes an ingredient by resting, and an order rests on the understanding that it may be filled in pieces. A trader who wants all 30 spreads or none should not leave a resting order. Instead, the trader can wait until 30 lots are available, implied or real, and then send a Fill-Or-Kill order that takes them in one go.

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

D and E each received an entirely ordinary outright fill at their own limit price. Afterwards the January bid has 15 lots left, the February ask has 30, and the implied spread bid is recomputed as 15 lots (min(15, 30)) at −$2.20.

The *opposite* implied quote needs the opposite ingredients. An implied spread **ask** requires a January *ask* and a February *bid* (Jan_ask − Feb_bid). With only D and E in the books, no implied spread ask exists: add the vectors of D and E any other way and nothing cancels.

## Level 5: The Promise Kept, Implied Orders Create No Liquidity

It is time to make the introduction's promise precise, because it is the single most important idea in the chapter, and because misunderstanding it leads directly to the most dangerous bugs.

**Argument 1: an implied trade is a trade anyone could have done by hand.** Go back to Level 3. Trader C wanted February and could have assembled it manually, without any implied functionality:

1. Sell 20 spreads to Trader B at −$2.00. (C now: sell 20 Jan, buy 20 Feb. Selling a spread at S has cash c = −S = −(−2.00) = +2.00, so C *pays* $2.00 per barrel on the difference: the February C bought costs $2.00 more than the January C sold.)
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

![A shared leg. B's and H's spread bids both need A's January lots. Taking the min of each pair separately and adding the results counts 5 of A's lots twice.](assets/implied-shared-leg-small.png)

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

Total: 25 lots, which equals min(30 January lots, 25 spread lots), as conservation demands. Now compare a naive implementation that pairs every January level with every spread level independently, taking the min of each pair. It would publish $77.00 × 10, **$77.01 × 15**, **$77.02 × 10** (Jan 75.00 with spread −2.02) and $77.03 × 10: 45 lots in total, when only 25 exist. The $77.02 level is entirely fictitious, because the January lots at $75.00 are already committed to the $77.00 level, and the $77.01 level is overstated, because 10 of the 15 spread lots at −2.00 are likewise already used. Buy everything the naive ladder shows and the engine runs out of January oil before the order is filled. Because a correct implied depth ladder is *path-dependent* in this way, venues typically compute and publish only the top one or two implied levels (see Level 10).

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
- **"Implied bids do not trade against implied offers."** Every trade needs at least one real, *incoming* order as the aggressor (the order whose arrival triggers the trade). Implied quotes are only ever passive: they wait to be hit. We will see why this rule is natural in Level 8.

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
2. buy 10 January from the January seller at $74.95, and
3. sell 10 February to K at $76.97.

The arbitrageur's January trades cancel, the February trades cancel, and the cash is p − 74.95 + 76.97 − (p + 2.00) = **+$0.02 per barrel**, $20 per lot, with no risk, provided all three fills happen before anyone else acts.

With implied functionality this state can never arise, because it could only be reached through an *arrival*, and the arriving order is matched when it arrives. Suppose K's bid rested first and B's spread bid is the last of the three orders to arrive. At that moment the engine already publishes an implied spread **ask** built from A's January ask and K's February bid: Jan_ask − Feb_bid = 74.95 − 76.97 = **−$2.02**. B's incoming bid of −$2.00 is willing to pay up to −2.00, and −2.02 is cheaper, so B trades immediately:

1. B buys 10 January from the January seller at $74.95.
2. B sells 10 February to K at $76.97.
3. B's spread fill prints at 74.95 − 76.97 = **−$2.02**, two ticks better than B's limit.

K's bid is now used up, so the implied spread ask disappears, and B's remaining 15 spreads rest as a bid at −$2.00 (where, together with the 30 January lots still offered, they again imply a February ask at $76.95 × 15).

The $0.02 that an arbitrageur would have pocketed goes instead to B, a real participant, as price improvement. (Had K's February bid been the last order to arrive instead, K would have been the incoming order: it would have bought 10 February from the implied ask at $76.95, and the same $0.02 would have gone to K. Either way, the improvement goes to whichever real order arrives last, because trades happen at the resting side's price.) This is the deeper purpose of implied functionality: it keeps the whole *family* of related books mutually consistent, so that cross-book gaps are closed by the exchange in favour of real participants rather than harvested by the fastest outsider.

There is one limit to this guarantee, and it explains the rule "implied bids do not trade against implied offers". An arriving order is checked only against real quotes and first-generation implied quotes, which means against combinations of at most two other real orders. An implied bid and an implied offer in the same book together involve **four** real orders, one step beyond what a first-generation engine ever checks. Such a pair can therefore be locked or crossed without any bug. An example with a third month, March:

| Real order | Price | Implies in February |
|---|---|---|
| January bid | 75.00 | with the spread ask below: Feb **bid** = 75.00 − (−2.00) = **77.00** |
| Jan/Feb spread ask | −2.00 | |
| March ask | 77.40 | with the spread ask below: Feb **ask** = 77.40 + (−0.45) = **76.95** |
| Feb/Mar spread ask | −0.45 | |

The implied February bid (77.00) sits above the implied February ask (76.95). The four real orders together could trade with $0.05 per barrel to spare: their cash amounts are +75.00 (January bid), +2.00 (Jan/Feb spread ask, c = −S), −77.40 (March ask) and +0.45 (Feb/Mar spread ask, c = −S), summing to +0.05. But no single arrival exposed the crossing: when the last of the four orders arrived, the matching combination would have needed three other orders, a second-generation construction. CME states plainly that implied bids "can exist at the same or inverted price levels with implied offers", that it calculates but does not disseminate them, and that implied bids do not trade against implied offers [Wilson, CME Group, *Liquidity in implied inter-commodity spread markets*, 2024]. The rule is therefore not a bug guard but a scope boundary: closing gaps that need more real orders than the enabled implication depth is left to participants. The next chapter shows why venues do not simply raise the depth.

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

Who receives the rounding gain depends on the direction of implication. In the implied OUT example above, the passive spread order (B) receives it. For **implied IN** (a spread quote built from two outrights), both outright orders fill at their own limit prices, so the spread *aggressor* sees the rounded price on screen but effectively trades at the unrounded one, and the gain goes to the aggressor. CME documents exactly this split for its inter-commodity spread markets [Wilson, CME Group, *Liquidity in implied inter-commodity spread markets*, 2024].

Whatever the rounding rule, it must be documented and implemented in **exactly one function**, shared by matching, market-data publication, and clearing. Two components that round differently will disagree about which prices exist.

**Leg prices must land on-tick and inside limits.** Every leg of every implied execution needs a price that is (a) a valid tick for its instrument, (b) consistent with every order involved, so that each spread's legs still differ by exactly its trade price, and (c) inside that instrument's price limits for the session. In the first-generation examples above, the real outright orders pin down the leg prices naturally. In the multi-layer constructions of the next chapter, some legs trade only *between two spread orders*, where no real outright price exists, and the engine must manufacture one by rule. Venues publish these leg-pricing algorithms. An engine that assigns an off-tick or out-of-limits leg price produces trades that clearing systems reject, a far worse failure than refusing the implied match up front.

## Level 10: How Implied Liquidity Appears in Market Data

Participants need to know that implied liquidity exists, and sophisticated participants need to know *which part* of a displayed quantity is implied, because an implied quote can vanish for reasons invisible in its own book (one of its ingredients in another book was cancelled or filled). Venues handle this in one of three ways:

1. **Publish implied quotes as a separate book** next to the real book. CME's MDP 3.0 market data feed disseminates a "2-deep best bid and ask ... for each implied-eligible futures contract" as a distinct implied book [CME Group Client Systems Wiki, *MDP 3.0 – Implied Book*], and documents how a client should consolidate it with the real book.
2. **Aggregate real and implied quantity** into one displayed number per price level.
3. **Show only the real book**, and let implied liquidity surface only at execution.

Even a venue that publishes an implied book may not publish everything it calculates. CME, for example, calculates but does not disseminate implied bids that are locked or crossed with implied offers (Level 8), nor implied OUT quotes from inter-commodity spreads whose leg ratio is not 1:1; that liquidity is hidden but can still be traded against [Wilson, CME Group, *Liquidity in implied inter-commodity spread markets*, 2024].

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

**E8.** The January book is empty. The February book holds a real ask of $76.80 × 15 lots (Trader P). The spread book holds a real ask of −$1.90 × 25 lots (Trader Q). (a) Which implied quote exists, at what price and quantity? (b) Trader R sends an order to buy 10 January at $74.90. List every fill, check that every party traded within its limit, and verify that the cash sums to zero. (c) What do the books look like afterwards?

**E9.** The market is in backwardation. January bid $78.30 × 12 lots (Trader S); Jan/Feb spread ask +$0.45 × 20 lots (Trader T); the February book is empty. (a) Compute the implied quote in the February book. (b) Trader U sends an order to sell 12 February at $77.80. At what price does U trade, and who gives up what?

**E10.** The February book holds two real asks: $77.00 × 4 (Trader G2) and $77.02 × 8 (Trader G). In addition, January ask $75.00 × 10 and spread bid −$2.00 × 12 are resting. Trader V sends an order to buy 20 February at $77.02. Which orders fill, in what sequence, at what prices, and what is V's average price? What remains afterwards?

**E11.** You *sold* 5 Jan/Feb spreads at −$1.20. A week later the spread trades at −$1.65. (a) Did you make or lose money, and how much? (b) In words, what happened to the shape of the market that helped or hurt you?

**E12.** January bid $75.20 × 10 (Trader W); February ask $77.10 × 10 (Trader X); the spread book is empty. Trader Y sends an order to sell 5 spreads at −$2.00. Does Y trade? If so, at what price, and how much better or worse than Y's limit, in dollars?

**E13.** A hypothetical product has an outright tick of 0.25 and a spread tick of 0.05. Resting: January bid 99.75 × 10 (Trader J); spread ask +0.10 × 10 (Trader L). (a) Compute the exact and the published implied February quote. (b) Trader M sends an order to sell 5 February at 99.50. Show every fill. (c) Show why rounding the other way would have broken a rule.

**E14.** A developer stores spread prices as an absolute value plus a "negative" flag and sorts the bid side by absolute value, largest first ("the bigger the number, the better the bid"). Two spread bids arrive: −$2.00 at 09:00:01 and −$1.95 at 09:00:02. Explain what goes wrong when a spread seller arrives, and what the correct design is.

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

**E8.**

*(a) Find the implied quote by adding vectors.* P's February ask is (Feb −1) with c = −76.80. Q's spread ask is a spread *sell*: (Jan −1, Feb +1) with c = −S = −(−1.90) = +1.90. Sum: (Jan −1), c = −76.80 + 1.90 = −74.90. A combined effect of "sell one January, receive $74.90" is an **implied January ask at $74.90**. This is the Level 2 formula Jan_ask = Feb_ask + S_ask = 76.80 + (−1.90) = 74.90. Quantity = min(15, 25) = **15 lots**. Notice the side rule: an implied *near-month* quote has the same side as its spread order (spread ask → January ask).

In words: Q wants to sell January and buy February, as long as February costs no more than $1.90 above January. P sells February at $76.80, so Q can afford to sell January at 76.80 − 1.90 = $74.90.

*(b) Execution.* R's bid of $74.90 meets the implied ask of $74.90, so 10 lots trade atomically:

1. Q sells 10 January to R at $74.90.
2. Q buys 10 February from P at $76.80.
3. Q's spread fill prints at 74.90 − 76.80 = −$1.90.

Limits: R bought at $74.90, exactly R's limit. P sold at $76.80, exactly P's limit. Q sold the spread at −$1.90, exactly Q's limit (a spread seller wants −1.90 *or higher*). All three are satisfied.

Cash (per barrel, "cash paid" convention): R pays 10 × 74.90 = +749.00; P pays −(10 × 76.80) = −768.00 (P receives); Q pays 10 × (−S) = 10 × 1.90 = +19.00. Total: 749.00 − 768.00 + 19.00 = **0**. Positions: R (Jan +10), P (Feb −10), Q (Jan −10, Feb +10) also sum to zero.

*(c) Afterwards:* February ask $76.80 × 5 (P); spread ask −$1.90 × 15 (Q); January book still has no real orders, and the implied January ask is recomputed to $74.90 × min(5, 15) = **5 lots**. R holds a long position of 10 January.

**E9.**

*(a)* S's January bid is (Jan +1), c = +78.30. T's spread ask is a spread sell, (Jan −1, Feb +1), c = −0.45. Sum: (Feb +1), c = 78.30 − 0.45 = 77.85: "buy one February, pay $77.85". That is an **implied February bid at $77.85 × min(12, 20) = 12 lots**, matching the formula Feb_bid = Jan_bid − S_ask. Note the side flip: a spread *ask* produces a February *bid*. The positive spread price simply means January is the more expensive month (backwardation); none of the arithmetic changes.

*(b)* U is willing to sell at $77.80 or more. The best bid available is the implied $77.85, so U trades all 12 lots at **$77.85**, the resting side's price, which is $0.05 better than U's limit ($50 per lot, $600 in total). The fills:

1. T sells 12 January to S at $78.30 (S's limit).
2. T buys 12 February from U at $77.85.
3. T's spread prints at 78.30 − 77.85 = **+$0.45** (T's limit).

Nobody gave anything up: S and T traded exactly at their limits, and U received price improvement because the best available bid happened to be higher than U required. Cash check: S pays 12 × 78.30 = 939.60; U pays −(12 × 77.85) = −934.20; T pays 12 × (−0.45) = −5.40. Sum: 939.60 − 934.20 − 5.40 = 0. Afterwards: S's bid is used up, T has 8 spreads left at +$0.45, and with no January bid left there is no implied February bid.

**E10.**

First, build the February ask side as the engine sees it. The implied ask is Jan_ask − S_bid = 75.00 − (−2.00) = $77.00, quantity min(10, 12) = 10. So:

| February ask | Lots | Source | Priority at that price |
|---|---|---|---|
| $77.00 | 4 | Real (G2) | 1st (real before implied) |
| $77.00 | 10 | Implied (Jan ask + spread bid) | 2nd |
| $77.02 | 8 | Real (G) | 3rd (worse price) |

V wants 20 lots at up to $77.02, so V walks down the ladder (price first, then real before implied):

1. **4 lots at $77.00 from G2** (ordinary two-party trade). V needs 16 more.
2. **10 lots at $77.00 through the implied construction**: the January seller sells 10 January at $75.00 to the spread bidder, the spread bidder buys 10 spreads at −$2.00, and V buys 10 February at $77.00 from the spread bidder. V needs 6 more.
3. The engine recomputes. The January ask is now gone, so there is **no implied ask any more**, even though the spread bid still has 2 lots. The best remaining ask is G's real $77.02.
4. **6 lots at $77.02 from G**.

Average price: (14 × 77.00 + 6 × 77.02) / 20 = (1,078.00 + 462.12) / 20 = **$77.006** per barrel.

Afterwards: February ask $77.02 × 2 (G); January book empty; spread bid −$2.00 × 2. Does that spread bid imply anything? It could only combine with a January ask (none left) or a February bid (none exist), so no implied quotes are published. Step 3 is the lesson: the implied quantity was capped by the January leg, not by the spread leg, and only recomputation reveals that.

**E11.**

*(a)* A spread seller profits when S *falls*. S moved from −1.20 to −1.65, a change of (−1.65) − (−1.20) = −0.45. The number went down (it moved further below zero), so you **made money**: +0.45 per barrel × 1,000 barrels × 5 lots = **+$2,250**.

Leg check: suppose you sold January at $74.80 and bought February at $76.00 (74.80 − 76.00 = −1.20 ✓). Later January is $74.35 and February is still $76.00 (74.35 − 76.00 = −1.65 ✓). Your January short gained 74.80 − 74.35 = +0.45; your February long gained 0. Net +0.45 per barrel, as computed.

*(b)* The market was in contango (February above January) and the contango *deepened*: February's premium over January grew from $1.20 to $1.65. Selling the Jan/Feb spread is a bet on exactly that. A common beginner slip is to think "the spread went from 1.20 to 1.65, it went up". It did not: with signs, −1.65 is lower than −1.20.

**E12.**

The spread book has no real orders, but W and X imply a spread bid: W's January bid (Jan +1, c = +75.20) plus X's February ask (Feb −1, c = −77.10) sum to (Jan +1, Feb −1), the shape of a spread buyer, paying 75.20 − 77.10 = **−$1.90**, quantity min(10, 10) = 10.

Y will sell the spread at −$2.00 *or higher*. Is −1.90 higher than −2.00? Yes: on the number line −1.90 lies to the right of −2.00. So Y trades 5 spreads at **−$1.90** (the resting, implied price):

1. Y sells 5 January to W at $75.20.
2. Y buys 5 February from X at $77.10.
3. Y's spread prints at 75.20 − 77.10 = −$1.90.

Y receives price improvement of 0.10 per barrel × 1,000 × 5 = **$500** compared with its limit. Intuitively: Y was prepared for February to cost up to $2.00 more than the January it sells, and it only cost $1.90 more. Cash check: W pays 376.00, X pays −385.50, Y pays 5 × (−S) = 5 × 1.90 = 9.50; sum 0. Afterwards: January bid $75.20 × 5, February ask $77.10 × 5, implied spread bid −$1.90 × 5.

**E13.**

*(a)* J's January bid (Jan +1, c = 99.75) plus L's spread ask (Jan −1, Feb +1, c = −0.10) sum to (Feb +1), c = 99.65: an implied **February bid**. The exact price 99.75 − 0.10 = 99.65 is not a multiple of 0.25. Rounding outwards means rounding a *bid down* (worse for whoever sells into it), so the published implied bid is **99.50**, quantity min(10, 10) = 10.

*(b)* M sells 5 February at 99.50, which meets the implied bid:

1. L sells 5 January to J at 99.75 (J's limit).
2. L buys 5 February from M at 99.50 (M's limit).
3. L's spread prints at 99.75 − 99.50 = **+0.25**, a valid 0.05 spread tick.

L asked for at least +0.10 and received +0.25: 0.15 of price improvement, the leftover from rounding.

*(c)* Rounding *inwards* would publish the bid at 99.75. If M then sold at 99.75, L's spread would print at 99.75 − 99.75 = 0.00, which is *below* L's limit of +0.10. The engine would have sold L's spread cheaper than L allowed, a violation of the most basic matching rule. Outward rounding is the only choice that guarantees every real order trades at or better than its limit.

**E14.**

The correct bid priority is **−1.95 first**: it is the higher signed price, so it is the more generous bid (that bidder accepts a smaller February premium). Sorting by absolute value puts −2.00 first because 2.00 > 1.95.

Now a spread seller arrives: sell 1 spread at −$2.00. The buggy book matches it against the −2.00 bid at −2.00. The correct book matches it against the −1.95 bid at −1.95. The bug therefore (1) violates price priority, because the better −1.95 bid was skipped, and (2) gives the seller a worse price than the market offered: −2.00 instead of −1.95, 0.05 × 1,000 = $50 per lot. On the ask side the same bug sorts −1.95 ahead of −2.00, so buyers pay more than the best available offer. Note that the bug is invisible while all spread prices are positive, which is exactly why it survives testing in backwardated markets and appears in production on the first day of contango.

The correct design is the one from Confusion 2: store prices as **signed integer ticks** (−200 and −195) and use ordinary numeric comparison. Bids sort descending (−195 before −200), asks sort ascending, with no special cases for sign.

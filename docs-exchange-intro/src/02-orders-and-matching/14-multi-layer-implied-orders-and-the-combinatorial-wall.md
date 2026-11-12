# Multi-Layer Implied Orders and the Combinatorial Wall

The previous chapter combined exactly two real orders at a time. A January ask plus a spread bid implied a February ask; a January bid plus a February ask implied a spread bid. A curious developer immediately asks the next question: *if an implied February ask can be traded against, can it also be used as an ingredient?* Combine it with a Feb/Mar spread and you get an implied March ask. Combine that with a Mar/Apr spread and you get an implied April ask. Why stop?

This chapter answers that question. It extends the vector model of the previous chapter to chains of any length, shows a real multi-generation example published by ICE, re-derives the "no liquidity from nothing" promise for chains, and then walks into what this chapter calls **the combinatorial wall**: the reason every exchange that offers implied matching restricts it, whether by the number of steps, by the set of instruments, by the depth it publishes, or by the time it is switched on.

The short version, for readers in a hurry: finding the *single best* implied price through arbitrarily long chains of simple calendar spreads is a well-behaved shortest-path problem. Everything else an exchange must do with implied liquidity (allocate quantity, publish depth, break ties fairly, execute atomically, assign leg prices, support three- and four-legged strategies, and do all of it within microseconds after *every single event*) grows explosively with the number of steps allowed. The explosion, not the arithmetic, is what forces the limit.

## Generations: Counting the Links in the Chain

We need a precise way to say how "deep" an implied quote is. This chapter uses the convention implied by the ICE example below:

- **Generation 0**: a real order, resting in its own book.
- **Generation 1**: an implied quote built from **two** real orders (everything in the previous chapter).
- **Generation 2**: an implied quote that uses a generation-1 implied quote as an ingredient, so it is built from **three** real orders.
- **Generation *k***: built from ***k* + 1** real orders.

Venues word this differently. CME's matching-priority documentation, for instance, labels outright orders "generation 0" and spread orders "1st generation" when ordering sources for allocation [CME Group Client Systems Wiki, *Futures Implied Order Matching Priority*]. What matters is the underlying quantity: *how many real orders must execute together for one implied lot to trade*. That number drives every cost in this chapter.

## A Real Multi-Generation Example (ICE)

ICE Futures publishes the following example of implied prices across generations in a crude-oil-style strip of September, October and November contracts [ICE, *ICE Futures Implied Prices* FAQ]. The real orders are:

| Book | Side | Price |
|---|---|---|
| September | Bid | 75.90 |
| October | Ask | 76.83 |
| Oct/Nov spread | Bid | −0.52 |

(As in the previous chapter, spread price = near month − far month, and a spread bid buys the near month and sells the far month.)

ICE derives, and we can check with the vector rule:

**Generation 1, implied IN: a Sep/Oct spread bid at −0.93.**

```
  Buy Sep at 75.90           v = (Sep +1)              c = +75.90
+ Sell Oct at 76.83          v = (Oct −1)              c = −76.83
  ------------------------------------------------------------------
                             v = (Sep +1, Oct −1)      c =  −0.93   → Sep/Oct spread BID at −0.93
```

**Generation 1, implied OUT: a November ask at 77.35.**

```
  Sell Oct at 76.83          v = (Oct −1)              c = −76.83
+ Buy Oct/Nov at −0.52       v = (Oct +1, Nov −1)      c =  −0.52
  ------------------------------------------------------------------
                             v = (Nov −1)              c = −77.35   → November ASK at 77.35
```

**Generation 2: a Sep/Nov spread bid at −1.45**, built from the real September bid and the *implied* November ask:

```
  Buy Sep at 75.90           v = (Sep +1)              c = +75.90
+ implied Sell Nov at 77.35  v = (Nov −1)              c = −77.35
  ------------------------------------------------------------------
                             v = (Sep +1, Nov −1)      c =  −1.45   → Sep/Nov spread BID at −1.45
```

Unpack the implied November ask and the generation-2 quote is simply the sum of all **three** real orders: 75.90 − 76.83 − 0.52 = −1.45, with the October legs cancelling. The same number appears if you chain the other generation-1 quote instead: implied Sep/Oct bid (−0.93) plus real Oct/Nov bid (−0.52) = −1.45. That is not a coincidence. **An implied quote is a property of the set of real orders it uses, not of the order in which you combine them.** The "generation" is just a count of how many real orders are in the set, minus one.

### Executing a generation-2 trade

Give the three real orders some sizes and owners:

| Book | Side | Price | Lots | Who |
|---|---|---|---|---|
| September | Bid | 75.90 | 10 | Trader P |
| October | Ask | 76.83 | 8 | Trader Q |
| Oct/Nov spread | Bid | −0.52 | 5 | Trader R |

The implied Sep/Nov spread bid is −1.45 for min(10, 8, 5) = **5 lots**, bottlenecked by R, the smallest ingredient. Trader X now submits an order to **sell** 5 Sep/Nov spreads at −1.45 (sell September, buy November). The engine must commit **four** participants' fills atomically:

| Participant | Does | Position change | Price(s) |
|---|---|---|---|
| X (incoming) | sells 5 Sep/Nov spreads at −1.45 | Sep −5, Nov +5 | Sep 75.90, Nov 77.35 |
| P | buys 5 September | Sep +5 | 75.90 |
| Q | sells 5 October | Oct −5 | 76.83 |
| R | buys 5 Oct/Nov spreads at −0.52 | Oct +5, Nov −5 | Oct 76.83, Nov 77.35 |

The same trade as a sequence of events. Note that the engine validates every fill before committing any of them, exactly as in the previous chapter's three-party example, only with one more participant:

```{.mermaid width=600}
sequenceDiagram
    participant X as Trader X (sells Sep/Nov)
    participant ME as Matching Engine
    participant P as Trader P (Sep bid 75.90)
    participant Q as Trader Q (Oct ask 76.83)
    participant R as Trader R (Oct/Nov bid −0.52)

    X->>ME: SELL 5 SEP/NOV @ −1.45
    Note over ME: Implied Sep/Nov bid −1.45 × 5 found<br/>(generation 2: P + Q + R).<br/>All four fills validated, then committed atomically.
    ME->>P: Fill 1: P BUYS 5 SEP @ 75.90 (from X)
    ME->>Q: Fill 2: Q SELLS 5 OCT @ 76.83 (to R)
    ME->>R: Fill 3: R BUYS 5 OCT/NOV @ −0.52<br/>(Oct 76.83, Nov 77.35)
    ME->>X: Fill 4: X SELLS 5 SEP/NOV @ −1.45<br/>(Sep 75.90, Nov 77.35)
    Note over ME: Prints: SEP 5@75.90, OCT 5@76.83,<br/>OCT/NOV 5@−0.52, SEP/NOV 5@−1.45
```

Follow the oil, month by month: September flows from X to P; October flows from Q to R; November flows from R to X. Each month changes hands exactly once, between exactly two participants.

Check the columns. **Positions** sum to zero in every month: September −5 + 5 = 0; October −5 + 5 = 0; November +5 − 5 = 0. **Leg prices** are consistent with every order: X's legs differ by 75.90 − 77.35 = −1.45 ✓; R's legs differ by 76.83 − 77.35 = −0.52 ✓; P and Q trade exactly at their limits. **Cash**, using the "cash paid" convention of the previous chapter, per barrel: X pays 5 × 1.45 = 7.25 (selling a spread at −1.45 means paying 1.45 per unit), P pays 5 × 75.90 = 379.50, Q pays −5 × 76.83 = −384.15, and R pays 5 × (−0.52) = −2.60. Sum: 7.25 + 379.50 − 384.15 − 2.60 = **0** ✓.

As before, X could have done all of this by hand: sell September to P, buy October from Q, and sell the Oct/Nov spread to R. Three orders, three chances for the market to move in between, and one very unhappy trader if the third fill fails. Implied matching removes that leg risk. It does not add one lot of liquidity: the 5 lots X traded are 5 of P's lots, 5 of Q's lots and 5 of R's spreads, and every one of those is now gone from every book where it used to be visible. **Multi-layer implication, like single-layer implication, only adds routes.**

### Why go deeper at all?

If deeper implication only adds routes, why would an exchange bother? Because sometimes the deeper route is the *only* route. Compare what two engines would display for the same three real orders P, Q and R, one limited to generation 1 and one allowing generation 2:

| Book | Real orders in this book | Generation-1 engine displays | Generation-2 engine displays |
|---|---|---|---|
| September | P: bid 75.90 × 10 | bid 75.90 × 10 (real) | bid 75.90 × 10 (real) |
| October | Q: ask 76.83 × 8 | ask 76.83 × 8 (real) | ask 76.83 × 8 (real) |
| November | *none* | implied ask 77.35 × 5 (Q + R) | implied ask 77.35 × 5 (Q + R) |
| Sep/Oct spread | *none* | implied bid −0.93 × 8 (P + Q) | implied bid −0.93 × 8 (P + Q) |
| Oct/Nov spread | R: bid −0.52 × 5 | bid −0.52 × 5 (real) | bid −0.52 × 5 (real) |
| Sep/Nov spread | *none* | **nothing** | **implied bid −1.45 × 5 (P + Q + R)** |

Why can the generation-1 engine not price the Sep/Nov spread? A generation-1 Sep/Nov bid needs exactly two *real* orders whose legs cancel: a September bid plus a *real* November ask, or a *real* Sep/Oct bid plus a *real* Oct/Nov bid. The November ask and the Sep/Oct bid exist only as implied quotes, and a generation-1 engine never uses implied quotes as ingredients. So Trader X, who wants to sell the Sep/Nov spread, faces an empty book and must leg three separate trades by hand, with all the leg risk that brings. The generation-2 engine shows X a firm price and executes all of it atomically.

The lesson: deeper implication pays off where the books *between* two instruments are empty or thin, typically longer-dated months and less popular spread combinations. Where a short route already exists, a longer route rarely beats it on price (point 7 of the combinatorial wall below). Exchanges therefore weigh one question: how often does a deeper route provide a price that no shorter route does, and is that worth the cost described in the rest of this chapter?

### When leg prices must be manufactured

In the ICE example, every month in the chain had a real outright order, so every leg price was pinned down by a real limit price. That is not always the case. Take two spread orders and nothing else:

| Book | Side | Price | Lots |
|---|---|---|---|
| Jan/Feb spread | Bid | −2.00 | 30 |
| Feb/Mar spread | Bid | −1.50 | 20 |

The vectors (Jan +1, Feb −1) and (Feb +1, Mar −1) add up to (Jan +1, Mar −1): an implied **Jan/Mar spread bid** at (−2.00) + (−1.50) = **−3.50**, for min(30, 20) = 20 lots. Only two real orders are involved, so it is a generation-1 quote, but of a third kind that is neither CME's "implied IN" (spread from outrights) nor "implied OUT" (outright from spread): a spread implied from two other spreads.

When a Jan/Mar spread seller hits it for 20 lots, three participants take **six** leg positions (the seller: Jan −20, Mar +20; the Jan/Feb bidder: Jan +20, Feb −20; the Feb/Mar bidder: Feb +20, Mar −20). The two February legs trade *between the two spread bidders*, and nothing in any order says what the February price is. Only differences are fixed: Jan − Feb = −2.00 and Feb − Mar = −1.50. The engine must manufacture the actual prices by rule, typically anchoring one month to a reference price (its last trade or settlement, as in the previous chapter's leg-price discussion). With February anchored at 77.00, the legs become January 75.00, February 77.00, March 78.50, and every spread's legs differ by exactly its price. Every leg price must also be a valid tick and inside that month's price limits, and the anchor rule must be deterministic. The longer the chain, the more legs have no real price of their own and must be manufactured this way.

## The Graph View: Implied Pricing Is a Path Problem

To reason about chains of any length, the vector model becomes a graph.

- Draw one **node** per delivery month, plus one special node **$** that stands for "cash". An outright order swaps a month for cash, so its edge has $ at one end; a spread order swaps one month for another, so its edge joins two months.
- Every resting order becomes a **directed edge** u → v, meaning "this order is willing to go long u and short v". A buy of January is the edge Jan → $ (long January, giving up cash); a sell of January is $ → Jan; a Jan/Feb spread bid is Jan → Feb; a Jan/Feb spread ask is Feb → Jan.
- Give each edge a **weight** equal to the order's cash amount c from the previous chapter: the most it is willing to pay per unit. A negative weight means the order needs to *receive* at least that much.

| Resting order | Edge | Weight (= cash paid c) | Example |
|---|---|---|---|
| Outright bid at P | Month → $ | +P | Jan bid 74.40 → weight +74.40 |
| Outright ask at P | $ → Month | −P | Jan ask 75.00 → weight −75.00 |
| Spread bid at S | Near → Far | +S | Jan/Feb bid −2.00 → weight −2.00 |
| Spread ask at S | Far → Near | −S | Jan/Feb ask −1.80 → weight +1.80 |

Read the spread rows slowly: they are the previous chapter's sign convention in graph form. A spread bid goes *from* the near month (bought) *to* the far month (sold), and its weight is the spread price itself, sign included.

Step back and look at the whole strip this way, and the previous chapter's circle of 78 books takes on a new meaning. Put $ in the middle. Each outright book is now a spoke between a month and $, and each spread book is a chord between two months:

![The 12-month strip as a graph. Each line is one order book: a spoke for each outright, a chord for each spread. Each line can carry orders in both directions: bids one way, asks the other.](assets/implied-hub-78-edges-small.png)

Every one of the 78 books is now a single line, and every pair of the 13 points is joined. An implied quote is a walk along these lines, so the question "which implied quotes exist?" becomes "which walks exist?". The rest of this chapter is about how many walks a picture like this contains.

Now the whole theory of implied pricing fits in one sentence:

> **A path of resting orders from node x to node y is an implied order to go long x and short y, and the most it will pay is the sum of the weights along the path.**

The intermediate nodes cancel, exactly as the October legs cancelled above. Some checks against examples you already know:

- Path $ → Jan → Feb (Jan ask 75.00, weight −75.00; spread bid −2.00, weight −2.00): long nothing, short February, paying −77.00, that is, *receiving* 77.00. An implied **February ask at 77.00** ✓ (previous chapter, Level 3).
- Path Jan → $ → Feb (Jan bid 74.40, weight +74.40; Feb ask 76.60, weight −76.60): long January, short February, paying −2.20. An implied **spread bid at −2.20** ✓ (previous chapter, Level 4).
- Path Sep → $ → Oct → Nov (Sep bid +75.90, Oct ask −76.83, Oct/Nov bid −0.52): long Sep, short Nov, paying −1.45. The ICE generation-2 **Sep/Nov bid at −1.45** ✓.

Figure: the ICE example as a graph. Each arrow is one real order, and together the three arrows form the path of the generation-2 Sep/Nov bid.

```{.mermaid width=600}
flowchart LR
    SEP((Sep))
    CASH(("$"))
    OCT((Oct))
    NOV((Nov))
    SEP == "P: Sep bid 75.90<br/>weight +75.90" ==> CASH
    CASH == "Q: Oct ask 76.83<br/>weight −76.83" ==> OCT
    OCT == "R: Oct/Nov bid −0.52<br/>weight −0.52" ==> NOV
```

Read the picture from left to right and translate each arrow back into words. P will buy September and give up cash (Sep → $). Q will take cash and give up October ($ → Oct). R will take October and give up November (Oct → Nov). Chain them and the intermediate nodes ($ and October) are each entered once and left once, so they cancel: what remains is "long September, short November", the Sep/Nov spread bid. Its price is the sum along the path: +75.90 − 76.83 − 0.52 = −1.45. Every sub-path is an implied quote too: Sep → $ → Oct is the Sep/Oct bid at −0.93, and $ → Oct → Nov is the November ask at 77.35.

The generation of an implied quote is the number of edges in its path, minus one. Only **simple paths** count, meaning paths that never visit the same node twice: revisiting a node would mean going long and short the same month inside one construction, which just wastes orders.

**The best implied bid for "long x, short y" is therefore the maximum-weight path from x to y.** The same search also gives asks, because an ask is just a path in the other direction: the best implied February ask is the maximum-weight path from $ to Feb, and its price is minus that weight (as in the first check above, where weight −77.00 means an ask at 77.00). Equivalently, negate every weight and it becomes a *shortest-path* problem, one of the most thoroughly studied problems in computer science.

**Cycles are crossed markets.** A cycle of resting orders (a path from a node back to itself) has a position vector of zero: its orders could trade with each other and nobody else. They *can* do so exactly when the total they are willing to pay is at least zero, since the cash must balance. A January bid at 75.00 (weight +75.00) and a January ask at 74.99 (weight −74.99) form a cycle of weight +0.01: a crossed book. Because a matching engine trades every crossing it can see the moment it arises (the previous chapter's Level 8), a correctly running engine never has a cycle of non-negative weight at rest *within the scope of implication it has enabled*. (Cycles longer than the enabled depth can stay crossed; closing them is left to arbitrageurs. CME confirms that implied bids can sit at the same or inverted price levels as implied offers, and that they do not trade against each other [Wilson, CME Group, *Liquidity in implied inter-commodity spread markets*, 2024].) In shortest-path terms, **an uncrossed family of books is a graph with no negative cycles** (after negating the weights), which is precisely the condition under which classical algorithms such as Bellman–Ford (which repeatedly relaxes every edge until no path can be improved) find optimal paths in polynomial time, that is, in time that grows only moderately with the number of books and orders. The condition holds fully when implication is unlimited, because then every crossed cycle is traded away on arrival; with a depth limit, longer crossed cycles may exist and the search must also respect the limit.

### Finding the best route, step by step

How does an engine actually search? The core of Bellman–Ford is easy to run by hand, and doing so once makes "shortest path" concrete. Take a three-month strip and ask: **what is the cheapest way to buy one March lot?** That is the best (lowest) March ask, real or implied. The resting orders that can help a buyer are:

| Order | Edge | Cost to the buyer of using this edge |
|---|---|---|
| January ask 70.00 | $ → Jan | 70.00 |
| February ask 70.70 | $ → Feb | 70.70 |
| March ask 71.20 (real) | $ → Mar | 71.20 |
| Jan/Feb spread bid −0.60 | Jan → Feb | 0.60 |
| Feb/Mar spread bid −0.45 | Feb → Mar | 0.45 |
| Jan/Mar spread bid −1.10 | Jan → Mar | 1.10 |

The "cost" column is simply the negated weight, which is easier to read when shopping: it is what you pay to move one step along the edge. For example, the Jan/Feb spread bidder will take January from you and give you February, provided February is priced 0.60 above January, so turning one January lot into one February lot costs 0.60.

The algorithm keeps a table "cheapest known cost to get long each month" and improves it in **rounds**. In round *k* it is allowed to use at most *k* real orders, so round *k* finds the best price up to generation *k* − 1. Each round looks at every edge u → v and asks: "is (best cost of u from the previous round) + (edge cost) cheaper than what I know for v?" If yes, it records the new cost and remembers which edge produced it (so the route can be reconstructed later).

| Round (max orders) | Jan | Feb | Mar | What changed |
|---|---|---|---|---|
| 0 | — | — | — | Start: only $ is reachable, at cost 0. |
| 1 (generation 0) | 70.00 | 70.70 | 71.20 | Each month via its own real ask. |
| 2 (generation ≤ 1) | 70.00 | **70.60** | **71.10** | Feb: 70.00 + 0.60 = 70.60 beats 70.70. Mar: candidates 71.20 (real), 70.70 + 0.45 = 71.15 (via real Feb), 70.00 + 1.10 = 71.10 (via Jan/Mar spread); best 71.10. |
| 3 (generation ≤ 2) | 70.00 | 70.60 | **71.05** | Mar: 70.60 (round-2 Feb) + 0.45 = 71.05 beats 71.10. |
| 4 | 70.00 | 70.60 | 71.05 | No change: stop. |

Read the answer from the table. The best March ask is **71.05**, reached by the route $ → Jan → Feb → Mar (January ask, Jan/Feb bid, Feb/Mar bid): a generation-2 implied quote, 0.15 better than the real March ask. Two observations:

1. **The depth limit is just the number of rounds.** A generation-1 engine stops after round 2 and publishes 71.10; a generation-2 engine runs one more round and finds 71.05. That is how an exchange's "maximum generation" setting turns into code.
2. **The search is cheap; this is the good news.** Each round touches every edge once, and the number of rounds is at most the number of months. Finding the best price never required listing routes one by one. The trouble, as the next section shows, starts with everything the exchange must do *besides* finding this one number: here, for instance, the engine must also know that the 71.05 route and the 71.10 route both depend on the same January ask, so they cannot both be sold in full.

This is a genuinely useful result, and it matches what at least one exchange advertises: ICE states that its engine "will determine the best bid and offer price in each market regardless of the number of generations required", within a given strip type [ICE, *ICE Futures Implied Prices* FAQ]. For the *best price* in a world of simple two-legged calendar spreads, the number of generations is not the problem.

So where is the wall?

## The Combinatorial Wall

The best price is one number per book side. An exchange needs a great deal more than that, and each additional requirement is where the growth hides.

### 1. The number of routes grows factorially

Consider a model strip of **M = 12** consecutive monthly contracts, with every outright and every calendar spread between any two months listed: 12 outright books plus 12 × 11 / 2 = 66 spread books. (Real venues list fewer spreads, but many list a lot of them.) In the graph that is 13 nodes (12 months plus $), every pair joined by orders on both sides.

How many distinct *routes* (simple paths) lead from $ to, say, the December node, i.e. how many different constructions could produce an implied December ask? A route with L real orders visits L − 1 intermediate months chosen in order from the 11 others, so there are 11! / (12 − L)! routes of length L. The figure below draws the first four generations for the implied December ask. Each panel's black arrows show one example route. The orange lines show every line that at least one route of that generation uses, darker where more routes share it:

![Routes from $ to December, generation by generation. At generation 1 each route passes through one other month; by generation 3 almost every line in the strip is part of some route.](assets/implied-routes-by-gen-small.png)

The table counts them all:

| Generation (real orders − 1) | Routes of exactly this length | Cumulative routes up to this generation |
|---|---|---|
| 0 (the real December book) | 1 | 1 |
| 1 | 11 | 12 |
| 2 | 110 | 122 |
| 3 | 990 | 1,112 |
| 4 | 7,920 | 9,032 |
| 5 | 55,440 | 64,472 |
| 11 (no limit) | 39,916,800 | 108,505,112 |

On a logarithmic scale, where each gridline is ten times the one below, the cumulative count looks like this:

![Cumulative number of routes from $ to December as the maximum generation grows. Each step multiplies the total several times over, until the very last steps, where few months remain to choose from.](assets/implied-route-wall-small.png)

That is for **one** side of **one** of 78 books, with a single price level per book. Every additional resting price level multiplies the possibilities further. A best-price search avoids enumerating these routes, but several of the exchange's other obligations do not.

### 2. Fair allocation needs the ties, not just the best

When several constructions offer the same implied price, the engine must decide which real orders trade, in a documented and deterministic order. CME sorts competing implied sources by strategy type, product code, leg expirations, number of legs, and instrument identifiers [CME, *Futures Implied Order Matching Priority*]. A shortest-path algorithm returns *a* best path. Fair allocation needs *all* the best paths, ranked, and the number of equal-price paths can be as large as the route counts above.

### 3. Quantity and depth turn a path problem into a flow problem

The previous chapter showed that quantity is a bottleneck (the smallest ingredient) and that shared orders cap the total. Across many routes that share many orders, "how much can trade at this price, and at the next price, and the next?" is a **minimum-cost flow** problem: route as many lots as possible through the graph, cheapest routes first, never exceeding any order's size. That is still polynomial in theory, but it is far heavier than one shortest-path search, and it must be redone after every event because every fill and cancel changes the capacities. The previous chapter's warning about naive depth (a fictitious $77.02 level) applies with far more force when routes can be several orders long and share orders in the middle.

### 4. Every event can change every book

With implication depth unlimited, a single cancel of a single order in the middle of the strip can change the best implied price in *every* book whose best route passed through it: potentially all 78 books, both sides. Each change is a market-data message. The previous chapter's "fan-out" becomes a flood, and it hits hardest precisely when markets are busiest.

Even the tiny ICE example shows the effect. Suppose Trader Q cancels the October ask, one order in one book. A generation-2 engine must, in the same event, update four books:

| Book | Before Q's cancel | After | Why |
|---|---|---|---|
| October | ask 76.83 × 8 (real) | empty | Q's own order is gone. |
| Sep/Oct spread | implied bid −0.93 × 8 | empty | It was built from P + **Q**. |
| November | implied ask 77.35 × 5 | empty | It was built from **Q** + R. |
| Sep/Nov spread | implied bid −1.45 × 5 | empty | It was built from P + **Q** + R. |

One cancel, four market-data updates. A generation-1 engine would have had three (it never published the Sep/Nov quote). Now scale up: in a 12-month strip with generation 2 enabled, an order in a middle month can sit inside routes to dozens of books, and every one of them must be recomputed and republished before the engine processes the next event. That recomputation sits on the critical path of every order, cancel and fill in the group.

In the fully connected 12-month strip, the ripple goes further than "dozens". Take a single June ask and ask which books *could* have a quote that depends on it:

![Books whose implied quotes can depend on one June ask, by maximum generation. Each line is one book, as in the strip graph earlier in the chapter.](assets/implied-cancel-ripple-small.png)

- **Generation 0:** only the June book itself.
- **Generation ≤ 1:** add one other real order to the June ask. A spread order with June as one leg turns it into an implied ask in another month (11 outright books). A bid in another month turns it into an implied spread quote against June (11 spread books). Total 1 + 11 + 11 = **23 books**.
- **Generation ≤ 2:** add two other real orders. A bid in month X, the June ask, and a spread order joining June to month Y form an implied X/Y spread quote, for *any* two months other than June. That reaches the remaining 55 spread books: **all 78 books**.

Not every one of those quotes will change on a given cancel, only those whose best route actually ran through the June ask. But the engine cannot know which ones those are without checking, and with generation 2 enabled it must check all of them.

### 5. Atomic execution grows with the chain

A generation-*k* trade commits *k* + 1 real orders plus the incoming one, in *k* + 1 or more books, as one indivisible unit. Every leg must pass validation (price limits, tick grid, risk checks, self-match prevention) before anything commits; every internal leg with no real outright price must have its price manufactured; and every participant must receive a correct execution report. The longer the chain, the larger the unit that can fail, and one failed leg voids the whole trade.

### 6. Multi-legged strategies leave the world of paths

Everything so far assumed two-legged instruments: edges connect exactly two nodes. Real venues also list **butterflies** (buy 1 near, sell 2 middle, buy 1 far: CME launched implied IN *and* implied OUT functionality for Eurodollar butterflies in 2004, describing the new implied OUT functionality as "an industry first", and covered only the first three years of the Eurodollar curve [CME press release, 18 October 2004]), **condors**, **packs and bundles** (a strip of four or more consecutive contracts traded as one), and **ratio inter-commodity spreads** (for example, CME Treasury spreads in which legs trade in ratios such as 3:2, where implied prices can even fall on a grid finer than the direct spread's ticks [Carruthers, 2018]).

A butterfly's vector has entries (+1, −2, +1). It is not an edge between two nodes; it touches three at once, with a weight of 2 in the middle. Finding a set of resting orders whose vectors, with integer multiplicities, sum exactly to a target vector is no longer a path problem. In general it is an **integer programming** problem, a class for which no efficient general algorithm is known, and whose best-known methods can take exponential time in the worst case. An exchange cannot afford "exponential in the worst case" inside a matching loop that must answer in microseconds, deterministically, after every event.

### 7. The benefit shrinks while the cost explodes

Remember the promise: implication creates no liquidity. Each extra generation adds only more *routes* to the same real orders. A generation-5 route is bottlenecked by the smallest of six real orders and is usually beaten on price by a shorter one, because every extra link adds another bid-ask spread to cross (the previous chapter's Exercise E1 showed a single implied spread already costs both outright spreads). The marginal value of the sixth link is small; its marginal cost, in latency, fan-out, and failure modes, is large.

## How Real Venues Draw the Line

Every venue that offers implied matching restricts it along one or more of four axes. The examples below are all from the venues' own documentation.

**Limit the number of generations.** CME's implied options functionality is limited to generation 1: "all implied options orders must be built directly from customer orders; implied orders cannot be used to create another implied order (second generation implied)" [CME Group Client Systems Wiki, *Implied Options*].

**Limit the set of instruments.** CME's 2004 implied butterfly functionality covered only the first three years of the Eurodollar curve [CME, 18 October 2004]. ICE implies prices "regardless of the number of generations", but only within a given strip type (month, quarter, season or calendar) [ICE, *ICE Futures Implied Prices* FAQ]. Restricting the instrument set shrinks M, and the route counts in the table above shrink factorially with it.

**Limit what is published.** CME's MDP 3.0 feed carries only a "2-deep best bid and ask" for each implied-eligible futures contract [CME, *MDP 3.0 – Implied Book*]. Two levels of implied depth are cheap to compute and difficult to get wrong; forty would be neither.

**Limit when it runs.** CME implied options are "available *on demand* for a configurable time interval": implication for an options instrument is switched on by a request for quote and switched off again when the timer expires, with "no extension to the specified time under any circumstances" [CME, *Implied Options*]. The engine pays the cost of implication only when a participant has asked for a price, and only briefly.

Two further practical restrictions appear in venue documentation. On some products, implied prices are rounded outwards to whole ticks and direct liquidity at the rounded price keeps priority, so an implied price must be at least a whole tick better than the direct market before implied liquidity is reached first (Carruthers documents this for CME Treasury inter-commodity spreads). And all instruments in the group must be in an open trading state for implication to run at all (CME, *Implied Options*); CME also suspends implied calculation if implication would produce a trade outside price limits [Wilson, CME Group, *Liquidity in implied inter-commodity spread markets*, 2024].

## What This Means When You Build One

If you are designing an implied-capable engine, the lesson is not "implement Bellman–Ford and you are done". It is:

1. **Make the implication depth an explicit, per-product configuration value**, defaulting to 1, and give every increase a measured latency budget. Depth is a product decision with an engineering price tag, not a free feature.
2. **Bound the instrument graph.** Decide which spreads participate in implication and keep the group small enough to live on one sequencing thread, so that atomicity comes from serialisation rather than from a distributed commit protocol.
3. **Compute what you publish, and publish little.** Top-of-book or two levels of implied depth, recomputed after every event, beats a deep ladder that is expensive, path-dependent, and occasionally fictitious.
4. **Keep two-legged and multi-legged implication separate.** Paths are tractable; hyperedges (edges that touch three or more nodes at once, like the butterfly) are not. Support butterflies and packs only through explicitly enumerated, fixed construction templates, never through a general search.
5. **Reuse the invariants from the previous chapter unchanged.** Conservation, firmness, grid consistency, no cross-book crossing, removal, and limits respected are all statements about *sets of real orders*, so they hold for generation 5 exactly as for generation 1. A property-based test that checks them after every event is the only practical way to trust a multi-generation engine.

> **Key idea:** Chains of implied orders are sums of real orders, just like single implied orders, so they create no liquidity, only more routes to it. Finding the single best price through chains of simple calendar spreads is a tractable shortest-path problem. But fair allocation among equal prices, quantity and depth, market-data fan-out, atomic execution, manufactured leg prices, and multi-legged strategies all grow explosively with the number of links allowed. That is why every venue bounds implication, by generation, by instrument set, by published depth, or by time, and why a well-designed engine makes that bound an explicit, measured configuration choice.

## Self-Check Exercises

*Convention: spread price = near − far; all spreads are calendar spreads of one lot per leg.*

**E1.** Real orders: March bid 80.10 × 6; March/April spread ask −0.40 × 9; April/May spread ask −0.35 × 4. What is the best implied May quote, which side is it on, what generation is it, and what quantity?

**E2.** Using the edge-weight rules of the graph view, write down the weights of: a June ask at 81.00; a June/July spread bid at −0.30; a July bid at 81.25. Is there a cycle among these three orders, and if so, is the family of books crossed?

**E3.** In the ICE example, suppose Trader R's Oct/Nov bid is cancelled. Which of the three implied quotes survive?

**E4.** Using the route table, how many routes of generation 2 or less lead from $ to one month in a fully connected strip of M = 12 months? If an exchange restricts implication to adjacent-month spreads only (Jan/Feb, Feb/Mar, … , Nov/Dec), how many routes lead from $ to December, and why?

**E5.** Real orders in a January–March strip: January ask 70.00 × 10 (Trader A); Jan/Feb spread bid −0.60 × 8 (Trader B); Feb/Mar spread bid −0.45 × 6 (Trader C). The February and March outright books are empty. (a) Find the implied March quote, its generation and its quantity. (b) Trader D sends an order to buy 6 March at 71.05. List every participant's fills with leg prices, and check positions and cash. (c) Which implied quotes remain afterwards?

**E6.** Same orders as E5, but every order is now 5 lots, and a fourth order rests: a Jan/Mar spread bid at −1.00 × 5 (Trader E). (a) List both routes to an implied March ask, with price and generation. (b) Build the correct implied March ask ladder. (c) What would a naive engine that prices each route independently publish, and why is it wrong?

**E7.** The only orders are a Feb/Mar spread bid at −0.50 × 10 (Trader F) and a Mar/Apr spread bid at −0.40 × 10 (Trader G). (a) What implied quote exists? (b) Trader H sells 10 Feb/Apr spreads into it. Assign leg prices if the engine's rule anchors March at its reference price of 80.00. (c) Would any of the three traders be better or worse off if the anchor were 85.00 instead?

**E8.** Three spread orders rest: Jan/Feb bid −0.60, Feb/Mar bid −0.45, and Jan/Mar ask −1.00 (all 5 lots). (a) Draw the three edges with weights and evaluate the cycle. Are the books crossed? (b) A new Jan/Mar ask arrives at −1.08 × 5. What happens?

**E9.** A small, fully connected strip has M = 4 months (Jan, Feb, Mar, Apr): 4 outright books and all 6 calendar spreads, each with one resting order on each side. (a) Count the routes from $ to April for each generation by listing them. (b) How many remain if implication is limited to generation 1?

**E10.** Use this convention for a Jan/Feb/Mar **butterfly**: price B = Jan − 2 × Feb + Mar, and buying one butterfly means buying 1 January, selling 2 February and buying 1 March. Resting: Jan/Feb spread bid −0.60 × 8 and Feb/Mar spread ask −0.40 × 5. (a) Which implied butterfly quote do they create, at what price and quantity? (b) Why can a resting butterfly order not be drawn as an edge in the graph view? (c) Does a resting butterfly bid plus a January ask imply anything?

&nbsp;

<div style="page-break-after: always;"></div>

&nbsp;

### Solutions

**E1.** Chain the orders so that the unwanted legs cancel. The March bid is (Mar +1), weight +80.10. A March/April spread *ask* is a spread seller, (Mar −1, Apr +1), weight +0.40. An April/May spread ask is (Apr −1, May +1), weight +0.35. Sum: (May +1), weight 80.10 + 0.40 + 0.35 = **80.85**. The combination is willing to go long May paying up to 80.85: an implied **May bid at 80.85**. It uses three real orders, so it is **generation 2**, and its quantity is min(6, 9, 4) = **4** lots. (Check in words: someone selling May to this construction delivers May to the Apr/May spread seller, who buys May and sells April 0.35 lower; April goes to the Mar/Apr spread seller, who buys April and sells March 0.40 lower; March goes to the March bidder at 80.10. 80.10 + 0.40 + 0.35 = 80.85.)

**E2.** June ask: edge $ → Jun, weight −81.00. June/July spread bid: edge Jun → Jul, weight −0.30. July bid: edge Jul → $, weight +81.25. They form the cycle $ → Jun → Jul → $, with total weight −81.00 − 0.30 + 81.25 = **−0.05**. The cycle's weight is negative, so the books are **not** crossed. (In prices: the implied July ask from the first two orders is 81.00 + 0.30 = 81.30, which is above the July bid of 81.25: a five-cent-wide, uncrossed market.)

**E3.** The generation-1 Sep/Oct bid at −0.93 survives, because it uses only the September bid and the October ask. The implied November ask at 77.35 disappears, because R's order was one of its two ingredients. The generation-2 Sep/Nov bid at −1.45 disappears too, because it used R's order (through the implied November ask). This is the removal test from the previous chapter, applied to a chain: remove any real order, and every implied quote whose set of real orders contains it must go.

**E4.** From the table: 1 + 11 + 110 = **122** routes. With adjacent-month spreads only, the graph from $ is: $ to every month (the outright books), plus a line Jan – Feb – … – Dec. A simple path from $ to December leaves $ once, enters the line at some month, and walks along the line to December without revisiting a node. It can enter at any of the 12 months, so there are exactly **12** routes: one direct (generation 0) and one for each possible entry month from January to November. Restricting which spreads participate turned a factorial explosion into a straight line, which is exactly why venues restrict the instrument set.

**E5.**

*(a)* Add the vectors, or follow the graph path $ → Jan → Feb → Mar:

```
  Sell Jan at 70.00          v = (Jan −1)              c = −70.00
+ Buy Jan/Feb at −0.60       v = (Jan +1, Feb −1)      c =  −0.60
+ Buy Feb/Mar at −0.45       v = (Feb +1, Mar −1)      c =  −0.45
  ------------------------------------------------------------------
                             v = (Mar −1)              c = −71.05   → March ASK at 71.05
```

January and February cancel, leaving "sell one March, receive 71.05". It uses three real orders, so it is **generation 2**, with quantity min(10, 8, 6) = **6** lots, bottlenecked by C. In words: A sells January at 70.00; B will sell February 0.60 above the January it buys, so at 70.60; C will sell March 0.45 above the February it buys, so at 71.05.

*(b)* All four fills commit atomically:

| Participant | Does | Position change | Leg prices |
|---|---|---|---|
| D (incoming) | buys 6 March | Mar +6 | 71.05 |
| A | sells 6 January | Jan −6 | 70.00 |
| B | buys 6 Jan/Feb at −0.60 | Jan +6, Feb −6 | Jan 70.00, Feb 70.60 |
| C | buys 6 Feb/Mar at −0.45 | Feb +6, Mar −6 | Feb 70.60, Mar 71.05 |

Every leg price is pinned down by A's real January price, so nothing needs to be manufactured. B's legs differ by 70.00 − 70.60 = −0.60 ✓; C's by 70.60 − 71.05 = −0.45 ✓. Positions: January −6 + 6 = 0, February −6 + 6 = 0, March +6 − 6 = 0 ✓. Cash paid per barrel: D +426.30 (6 × 71.05), A −420.00, B 6 × (−0.60) = −3.60, C 6 × (−0.45) = −2.70. Sum: 426.30 − 420.00 − 3.60 − 2.70 = **0** ✓.

*(c)* Afterwards A has 4 lots, B has 2, C has none. The March route needed C, so the implied March ask is gone. But the shorter route $ → Jan → Feb still exists: an implied **February ask** at 70.00 + 0.60 = 70.60, generation 1, quantity min(4, 2) = **2**. Recomputation finds it; decrementing the old March quote never would.

**E6.**

*(a)* Two paths lead from $ to March:

- $ → Jan → Mar (A's January ask, then E's Jan/Mar bid): weight −70.00 − 1.00 = −71.00, so an ask at **71.00**, generation 1.
- $ → Jan → Feb → Mar (A, B, C as in E5): ask at **71.05**, generation 2.

*(b)* Price first: the 71.00 route is better. Its quantity is min(5, 5) = 5, which uses all 5 of A's January lots. The 71.05 route also starts with A's January ask, so after the first level is allocated it has nothing left. The correct ladder is **71.00 × 5**, and nothing more.

*(c)* A naive engine would compute each route's quantity separately, min(5, 5) = 5 and min(5, 5, 5) = 5, and publish 71.00 × 5 **and** 71.05 × 5: ten lots, when the strip contains only five January lots to deliver. This is the shared-leg error of the previous chapter, now hidden inside routes of different lengths. Note also that the shorter route gave the better price, which is typical: each extra link adds another order's price to the chain (point 7 of the combinatorial wall).

**E7.**

*(a)* F's bid is (Feb +1, Mar −1), c = −0.50; G's bid is (Mar +1, Apr −1), c = −0.40. Sum: (Feb +1, Apr −1), c = −0.90: an implied **Feb/Apr spread bid at −0.90** × min(10, 10) = 10. Two real orders, so generation 1, of the spread-from-spreads kind.

*(b)* Only the differences are fixed: Feb − Mar = −0.50 and Mar − Apr = −0.40. With March anchored at 80.00: February = 80.00 − 0.50 = **79.50**, April = 80.00 + 0.40 = **80.40**.

| Participant | Position change | Leg prices | Check |
|---|---|---|---|
| H (sells Feb/Apr at −0.90) | Feb −10, Apr +10 | Feb 79.50, Apr 80.40 | 79.50 − 80.40 = −0.90 ✓ |
| F (buys Feb/Mar at −0.50) | Feb +10, Mar −10 | Feb 79.50, Mar 80.00 | 79.50 − 80.00 = −0.50 ✓ |
| G (buys Mar/Apr at −0.40) | Mar +10, Apr −10 | Mar 80.00, Apr 80.40 | 80.00 − 80.40 = −0.40 ✓ |

The March legs trade between F and G, at a price no order specified.

*(c)* No. With an anchor of 85.00 every leg moves up by 5.00 (Feb 84.50, Mar 85.00, Apr 85.40), but each trader's legs still differ by exactly that trader's spread price, and each trader is long one month and short another by the same quantity, so the 5.00 shift cancels in every trader's profit and loss. The anchor matters to the *systems*, not to the traders' economics: every leg price must be on-tick, inside the month's price limits, and produced by the same deterministic rule in matching, market data and clearing. An anchor far from the market (85.00 when March trades near 80.00) might fall outside the daily price limits and get the whole trade rejected, which is why venues anchor to a recent reference price.

**E8.**

*(a)* Jan/Feb bid: edge Jan → Feb, weight −0.60. Feb/Mar bid: Feb → Mar, weight −0.45. Jan/Mar ask: Mar → Jan, weight −(−1.00) = +1.00. These form the cycle Jan → Feb → Mar → Jan with weight −0.60 − 0.45 + 1.00 = **−0.05**. Negative, so the books are **not crossed**. In prices: the two bids imply a Jan/Mar bid of −0.60 + (−0.45) = −1.05, and the real Jan/Mar ask is −1.00. The bid is below the ask, a market 0.05 wide.

*(b)* The new ask at −1.08 adds the edge Mar → Jan with weight +1.08, and the cycle Jan → Feb → Mar → Jan through it weighs −0.60 − 0.45 + 1.08 = **+0.03**: non-negative, so these orders can trade. The seller is willing to sell at −1.08 or higher; the implied bid of −1.05 is higher (−1.05 > −1.08), so all 5 lots trade at **−1.05**, the resting side's price. The seller does 0.03 × 1,000 = $30 per lot better than its limit. No month has a real outright price here, so the engine must manufacture all three leg prices from its anchor rule (for example February at 70.60 gives January 70.00 and March 71.05; the seller's legs then differ by 70.00 − 71.05 = −1.05 ✓). After the trade both spread bids are used up, so nothing crossed remains: the engine closed the cycle the moment it appeared.

**E9.**

*(a)* A route starts at $, buys into one month through its outright ask, then moves between months through spreads, and ends at April, never revisiting a month. Writing only the months visited:

- **Generation 0** (1 order): Apr. → **1** route.
- **Generation 1** (2 orders): Jan → Apr, Feb → Apr, Mar → Apr. → **3** routes.
- **Generation 2** (3 orders): two intermediate months in order, chosen from Jan, Feb, Mar: Jan → Feb → Apr, Jan → Mar → Apr, Feb → Jan → Apr, Feb → Mar → Apr, Mar → Jan → Apr, Mar → Feb → Apr. → **6** routes.
- **Generation 3** (4 orders): all three intermediate months in some order: 3 × 2 × 1 = **6** routes.

Total: 1 + 3 + 6 + 6 = **16**. The chapter's formula with 3 other months gives the same counts: 3! / (4 − L)! for L = 1, 2, 3, 4 real orders is 1, 3, 6, 6.

Routes like Feb → Jan → Apr look odd (going "backwards" in time) but are perfectly valid: the Feb/Jan step uses a Jan/Feb spread *ask*, which is an edge from Feb to Jan.

*(b)* Generation ≤ 1 keeps 1 + 3 = **4** routes, a quarter of the total. With 4 months the full count is still small; the table in the chapter shows how the same counting reaches tens of millions at 12 months.

**E10.**

*(a)* Jan/Feb bid: (Jan +1, Feb −1), c = −0.60. Feb/Mar ask is a spread *seller*: (Feb −1, Mar +1), c = −(−0.40) = +0.40. Sum: (Jan +1, Feb −2, Mar +1), c = −0.20. That vector is exactly one butterfly *purchase*, so the two orders imply a **butterfly bid at −0.20**, quantity min(8, 5) = **5**. Check with leg prices: anchor February at 70.60; then January = 70.60 − 0.60 = 70.00 and March = 70.60 + 0.40 = 71.00 (from Feb − Mar = −0.40). B = 70.00 − 2 × 70.60 + 71.00 = −0.20 ✓. In words: the butterfly is "Jan/Feb spread minus Feb/Mar spread", so buying it means buying the first spread and selling the second, and its price is S(Jan/Feb) − S(Feb/Mar) = −0.60 − (−0.40) = −0.20.

*(b)* An edge records "long one month, short one month, one lot each". The butterfly is long January, long March, and short *two* February at once: three months, with a 2 in the middle. No single arrow from one node to another can express that. Implying *into* the butterfly from two ordinary spreads (part a) still works, because each ingredient is an ordinary edge. Using a resting butterfly as an *ingredient* is the hard direction: the engine must find other orders whose vectors cancel the right entries in the right multiples, which is the integer-programming search described in point 6.

*(c)* Add the vectors: (Jan +1, Feb −2, Mar +1) + (Jan −1) = (Feb −2, Mar +1). That is "sell two February, buy one March", a 2:1 ratio that matches no listed book, so **nothing** is implied. Compare: butterfly bid + Feb/Mar spread *bid* (Feb +1, Mar −1) gives (Jan +1, Feb −1), a valid Jan/Feb spread. Finding which combinations work requires trying them, and with multi-legged instruments the number of combinations to try is what explodes. That is why point 4 of *What This Means When You Build One* recommends a small set of explicitly listed templates instead of a general search.

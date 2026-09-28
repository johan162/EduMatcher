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

Check the columns. **Positions** sum to zero in every month: September −5 + 5 = 0; October −5 + 5 = 0; November +5 − 5 = 0. **Leg prices** are consistent with every order: X's legs differ by 75.90 − 77.35 = −1.45 ✓; R's legs differ by 76.83 − 77.35 = −0.52 ✓; P and Q trade exactly at their limits. **Cash**, using the "cash paid" convention of the previous chapter, per barrel: X pays 5 × 1.45 = 7.25 (selling a spread at −1.45 means paying 1.45 per unit), P pays 5 × 75.90 = 379.50, Q pays −5 × 76.83 = −384.15, and R pays 5 × (−0.52) = −2.60. Sum: 7.25 + 379.50 − 384.15 − 2.60 = **0** ✓.

As before, X could have done all of this by hand: sell September to P, buy October from Q, and sell the Oct/Nov spread to R. Three orders, three chances for the market to move in between, and one very unhappy trader if the third fill fails. Implied matching removes that leg risk. It does not add one lot of liquidity: the 5 lots X traded are 5 of P's lots, 5 of Q's lots and 5 of R's spreads, and every one of those is now gone from every book where it used to be visible. **Multi-layer implication, like single-layer implication, only adds routes.**

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

- Draw one **node** per delivery month, plus one special node **$** that stands for "cash".
- Every resting order becomes a **directed edge** u → v, meaning "this order is willing to go long u and short v". A buy of January is the edge Jan → $; a sell of January is $ → Jan; a Jan/Feb spread bid is Jan → Feb; a Jan/Feb spread ask is Feb → Jan.
- Give each edge a **weight** equal to the order's cash amount c from the previous chapter: the most it is willing to pay per unit. A January bid at 74.40 has weight +74.40; a January ask at 75.00 has weight −75.00; a spread bid at −2.00 has weight −2.00; a spread ask at −1.80 has weight +1.80.

Now the whole theory of implied pricing fits in one sentence:

> **A path of resting orders from node x to node y is an implied order to go long x and short y, and the most it will pay is the sum of the weights along the path.**

The intermediate nodes cancel, exactly as the October legs cancelled above. Some checks against examples you already know:

- Path $ → Jan → Feb (Jan ask 75.00, weight −75.00; spread bid −2.00, weight −2.00): long nothing, short February, paying −77.00, that is, *receiving* 77.00. An implied **February ask at 77.00** ✓ (previous chapter, Level 3).
- Path Jan → $ → Feb (Jan bid 74.40, weight +74.40; Feb ask 76.60, weight −76.60): long January, short February, paying −2.20. An implied **spread bid at −2.20** ✓ (previous chapter, Level 4).
- Path Sep → $ → Oct → Nov (Sep bid +75.90, Oct ask −76.83, Oct/Nov bid −0.52): long Sep, short Nov, paying −1.45. The ICE generation-2 **Sep/Nov bid at −1.45** ✓.

The generation of an implied quote is the number of edges in its path, minus one.

**The best implied bid for "long x, short y" is therefore the maximum-weight path from x to y.** Equivalently, negate every weight and it becomes a *shortest-path* problem, one of the most thoroughly studied problems in computer science.

**Cycles are crossed markets.** A cycle of resting orders (a path from a node back to itself) has a position vector of zero: its orders could trade with each other and nobody else. They *can* do so exactly when the total they are willing to pay is at least zero, since the cash must balance. A January bid at 75.00 (weight +75.00) and a January ask at 74.99 (weight −74.99) form a cycle of weight +0.01: a crossed book. Because a matching engine trades every crossing it can see the moment it arises (the previous chapter's Level 8), a correctly running engine never has a cycle of non-negative weight at rest *within the scope of implication it has enabled*. (Cycles longer than the enabled depth can stay crossed; closing them is left to arbitrageurs.) In shortest-path terms, **an uncrossed family of books is a graph with no negative cycles** (after negating the weights), which is precisely the condition under which classical algorithms such as Bellman–Ford find optimal paths in polynomial time.

This is a genuinely useful result, and it matches what at least one exchange advertises: ICE states that its engine "will determine the best bid and offer price in each market regardless of the number of generations required", within a given strip type [ICE, *ICE Futures Implied Prices* FAQ]. For the *best price* in a world of simple two-legged calendar spreads, the number of generations is not the problem.

So where is the wall?

## The Combinatorial Wall

The best price is one number per book side. An exchange needs a great deal more than that, and each additional requirement is where the growth hides.

### 1. The number of routes grows factorially

Consider a model strip of **M = 12** consecutive monthly contracts, with every outright and every calendar spread between any two months listed: 12 outright books plus 12 × 11 / 2 = 66 spread books. (Real venues list fewer spreads, but many list a lot of them.) In the graph that is 13 nodes (12 months plus $), every pair joined by orders on both sides.

How many distinct *routes* (simple paths) lead from $ to, say, the December node, i.e. how many different constructions could produce an implied December ask? A route with L real orders visits L − 1 intermediate months chosen in order from the 11 others, so there are 11! / (12 − L)! routes of length L:

| Generation (real orders − 1) | Routes of exactly this length | Cumulative routes up to this generation |
|---|---|---|
| 0 (the real December book) | 1 | 1 |
| 1 | 11 | 12 |
| 2 | 110 | 122 |
| 3 | 990 | 1,112 |
| 4 | 7,920 | 9,032 |
| 5 | 55,440 | 64,472 |
| 11 (no limit) | 39,916,800 | 108,505,112 |

That is for **one** side of **one** of 78 books, with a single price level per book. Every additional resting price level multiplies the possibilities further. A best-price search avoids enumerating these routes, but several of the exchange's other obligations do not.

### 2. Fair allocation needs the ties, not just the best

When several constructions offer the same implied price, the engine must decide which real orders trade, in a documented and deterministic order. CME sorts competing implied sources by strategy type, product code, leg expirations, number of legs, and instrument identifiers [CME, *Futures Implied Order Matching Priority*]. A shortest-path algorithm returns *a* best path. Fair allocation needs *all* the best paths, ranked, and the number of equal-price paths can be as large as the route counts above.

### 3. Quantity and depth turn a path problem into a flow problem

The previous chapter showed that quantity is a bottleneck (the smallest ingredient) and that shared orders cap the total. Across many routes that share many orders, "how much can trade at this price, and at the next price, and the next?" is a **minimum-cost flow** problem: route as many lots as possible through the graph, cheapest routes first, never exceeding any order's size. That is still polynomial in theory, but it is far heavier than one shortest-path search, and it must be redone after every event because every fill and cancel changes the capacities. The previous chapter's warning about naive depth (a fictitious $77.02 level) applies with far more force when routes can be several orders long and share orders in the middle.

### 4. Every event can change every book

With implication depth unlimited, a single cancel of a single order in the middle of the strip can change the best implied price in *every* book whose best route passed through it: potentially all 78 books, both sides. Each change is a market-data message. The previous chapter's "fan-out" becomes a flood, and it hits hardest precisely when markets are busiest.

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

Two further practical restrictions are common: implied prices must usually beat the direct market by at least a whole tick before implied liquidity is accessed (Carruthers documents this for CME Treasury inter-commodity spreads), and all instruments in the group must be in an open trading state for implication to run at all (CME, *Implied Options*).

## What This Means When You Build One

If you are designing an implied-capable engine, the lesson is not "implement Bellman–Ford and you are done". It is:

1. **Make the implication depth an explicit, per-product configuration value**, defaulting to 1, and give every increase a measured latency budget. Depth is a product decision with an engineering price tag, not a free feature.
2. **Bound the instrument graph.** Decide which spreads participate in implication and keep the group small enough to live on one sequencing thread, so that atomicity comes from serialisation rather than from a distributed commit protocol.
3. **Compute what you publish, and publish little.** Top-of-book or two levels of implied depth, recomputed after every event, beats a deep ladder that is expensive, path-dependent, and occasionally fictitious.
4. **Keep two-legged and multi-legged implication separate.** Paths are tractable; hyperedges are not. Support butterflies and packs only through explicitly enumerated, fixed construction templates, never through a general search.
5. **Reuse the invariants from the previous chapter unchanged.** Conservation, firmness, grid consistency, no cross-book crossing, removal, and limits respected are all statements about *sets of real orders*, so they hold for generation 5 exactly as for generation 1. A property-based test that checks them after every event is the only practical way to trust a multi-generation engine.

> **Key idea:** Chains of implied orders are sums of real orders, just like single implied orders, so they create no liquidity, only more routes to it. Finding the single best price through chains of simple calendar spreads is a tractable shortest-path problem. But fair allocation among equal prices, quantity and depth, market-data fan-out, atomic execution, manufactured leg prices, and multi-legged strategies all grow explosively with the number of links allowed. That is why every venue bounds implication, by generation, by instrument set, by published depth, or by time, and why a well-designed engine makes that bound an explicit, measured configuration choice.

## Self-Check Exercises

*Convention: spread price = near − far; all spreads are calendar spreads of one lot per leg.*

**E1.** Real orders: March bid 80.10 × 6; March/April spread ask −0.40 × 9; April/May spread ask −0.35 × 4. What is the best implied May quote, which side is it on, what generation is it, and what quantity?

**E2.** Using the edge-weight rules of the graph view, write down the weights of: a June ask at 81.00; a June/July spread bid at −0.30; a July bid at 81.25. Is there a cycle among these three orders, and if so, is the family of books crossed?

**E3.** In the ICE example, suppose Trader R's Oct/Nov bid is cancelled. Which of the three implied quotes survive?

**E4.** Using the route table, how many routes of generation 2 or less lead from $ to one month in a fully connected strip of M = 12 months? If an exchange restricts implication to adjacent-month spreads only (Jan/Feb, Feb/Mar, … , Nov/Dec), how many routes lead from $ to December, and why?

&nbsp;

<div style="page-break-after: always;"></div>

&nbsp;

### Solutions

**E1.** Chain the orders so that the unwanted legs cancel. The March bid is (Mar +1), weight +80.10. A March/April spread *ask* is a spread seller, (Mar −1, Apr +1), weight +0.40. An April/May spread ask is (Apr −1, May +1), weight +0.35. Sum: (May +1), weight 80.10 + 0.40 + 0.35 = **80.85**. The combination is willing to go long May paying up to 80.85: an implied **May bid at 80.85**. It uses three real orders, so it is **generation 2**, and its quantity is min(6, 9, 4) = **4** lots. (Check in words: someone selling May to this construction delivers May to the Apr/May spread seller, who buys May and sells April 0.35 lower; April goes to the Mar/Apr spread seller, who buys April and sells March 0.40 lower; March goes to the March bidder at 80.10. 80.10 + 0.40 + 0.35 = 80.85.)

**E2.** June ask: edge $ → Jun, weight −81.00. June/July spread bid: edge Jun → Jul, weight −0.30. July bid: edge Jul → $, weight +81.25. They form the cycle $ → Jun → Jul → $, with total weight −81.00 − 0.30 + 81.25 = **−0.05**. The cycle's weight is negative, so the books are **not** crossed. (In prices: the implied July ask from the first two orders is 81.00 + 0.30 = 81.30, which is above the July bid of 81.25: a five-cent-wide, uncrossed market.)

**E3.** The generation-1 Sep/Oct bid at −0.93 survives, because it uses only the September bid and the October ask. The implied November ask at 77.35 disappears, because R's order was one of its two ingredients. The generation-2 Sep/Nov bid at −1.45 disappears too, because it used R's order (through the implied November ask). This is the removal test from the previous chapter, applied to a chain: remove any real order, and every implied quote whose set of real orders contains it must go.

**E4.** From the table: 1 + 11 + 110 = **122** routes. With adjacent-month spreads only, the graph from $ is: $ to every month (the outright books), plus a line Jan – Feb – … – Dec. A simple path from $ to December leaves $ once, enters the line at some month, and walks along the line to December without revisiting a node. It can enter at any of the 12 months, so there are exactly **12** routes: one direct (generation 0) and one for each possible entry month from January to November. Restricting which spreads participate turned a factorial explosion into a straight line, which is exactly why venues restrict the instrument set.

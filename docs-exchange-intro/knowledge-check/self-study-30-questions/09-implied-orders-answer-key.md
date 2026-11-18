# Answer Key — Implied Orders Knowledge Check, Variant 09

Correct statements are listed per question. Scoring: +1 per correct selection, -2 per incorrect selection, 0 for unselected, floor of 0 overall. The maximum possible score equals the total number of true statements below (99).

Conventions as in the quiz: S = Near − Far, one lot = 1,000 barrels, prices per barrel. "Cash paid" (c) is positive when an order pays money and negative when it receives money.

| # | Correct | | # | Correct |
|---|---|---|---|---|
| 1 | B, C, E | | 16 | A, C, D |
| 2 | B, C, E | | 17 | A, B, E |
| 3 | B, C, D | | 18 | A, C, D |
| 4 | A, B, D | | 19 | B, D, E |
| 5 | B, C, D | | 20 | A, B, D, E |
| 6 | A, B, D | | 21 | A, C, E |
| 7 | A, B, C, D | | 22 | B, C, D, E |
| 8 | A, D, E | | 23 | A, D, E |
| 9 | A, D, E | | 24 | B, C, D |
| 10 | A, C, E | | 25 | A, C, E |
| 11 | C, D, E | | 26 | A, C, D |
| 12 | A, C, D, E | | 27 | B, C, D |
| 13 | A, C, D, E | | 28 | B, C, D, E |
| 14 | B, C, D, E | | 29 | A, B, D, E |
| 15 | A, B, C | | 30 | A, C, D, E |

<div style="page-break-after: always;"></div>

## Detailed answers

### 1. Why implied orders exist — B, C, E

- **A — false.** Implied orders never create liquidity; they make existing commitments reachable from one more book.
- **B — true.** Unconnected books can become crossed across books, and the gap is free money for the fastest arbitrageur. Implication closes those gaps in favour of real participants.
- **C — true.** 12 × 11 / 2 = 66 spread books plus 12 outright books = 78 books, but the population of traders does not grow with the number of books.
- **D — false.** Implied orders are almost exclusively a futures (and forwards) feature, where many delivery months and spreads share one underlying.
- **E — true.** This is the "seller in the wrong book" problem: a spread bid contains a sale of the far month, which never appears in the far-month book unless the engine implies it.

### 2. The spread sign convention — B, C, E

- **A — false.** −2.10 is lower than −2.00, so an ask at −2.10 is *cheaper*, which makes it the better ask.
- **B — true.** In contango the far month is more expensive, so Near − Far is negative. That is normal, not an error.
- **C — true.** −1.90 is higher than −2.00, and a higher bid is a better bid.
- **D — false.** Buying the spread buys the *near* month (January) and sells the *far* month (February).
- **E — true.** S = Jan − Feb = −2.00, so Jan = Feb − 2.00.

### 3. Spread P&L, numerically — B, C, D

- **A — false.** A spread *seller* gains when S falls. S rose by +0.25, so the seller **loses** 0.25 × 1,000 × 2 = **$500**.
- **B — true.** A spread buyer gains when S rises: (−1.70) − (−2.00) = +0.30 per barrel × 1,000 × 4 lots = **+$1,200**.
- **C — true.** Only the difference between the months matters. If both legs fall but January falls less than February, S rises and the buyer gains.
- **D — true.** Both legs move by the same amount, so S is unchanged and so is the spread P&L.
- **E — false.** −1.65 is lower than −1.20; the spread price fell by 0.45.

### 4. Orders as vectors — A, B, D

- **A — true.** An implied order is a set of resting orders whose unwanted legs cancel, leaving the vector of a single order in another book.
- **B — true.** This single rule is the whole theory of implied pricing.
- **C — false.** (Jan +1) + (Jan +1, Feb −1) = (Jan +2, Feb −1). Nothing cancels, so this is not an order in any book. A spread bid's January leg can only cancel against a January *sell*.
- **D — true.** A spread bid buys one January (+1) and sells one February (−1).
- **E — false.** A sale *receives* money, so its cash paid is c = −77.00.

### 5. The six first-generation formulas — B, C, D

The full table: Feb ask = Jan_ask − S_bid; Feb bid = Jan_bid − S_ask; Jan ask = Feb_ask + S_ask; Jan bid = Feb_bid + S_bid; spread ask = Jan_ask − Feb_bid; spread bid = Jan_bid − Feb_ask.

- **A — false.** An implied spread *ask* needs a January **ask** and a February bid: Jan_ask − Feb_bid. Two bids cannot cancel anything.
- **B — true.** (Jan +1) + (Jan −1, Feb +1) = (Feb +1); cash Jan_bid − S_ask.
- **C — true.** (Jan +1) + (Feb −1) is a spread buy paying Jan_bid − Feb_ask.
- **D — true.** (Jan −1) + (Jan +1, Feb −1) = (Feb −1); cash −Jan_ask + S_bid, so the ask price is Jan_ask − S_bid.
- **E — false.** Feb ask (Feb −1, c = −Feb_ask) plus spread ask (Jan −1, Feb +1, c = −S_ask) gives (Jan −1) with c = −(Feb_ask + S_ask). The implied January ask is Feb_ask **+** S_ask.

### 6. Which side is which — A, B, D

The rule of thumb: an implied *near-month* quote has the *same* side as its spread order; an implied *far-month* quote has the *opposite* side.

- **A — true.** Jan bid = Feb_bid + S_bid: same side as the spread order, as the rule says for the near month.
- **B — true.** This side flip is the most important fact in the chapter and the source of most bugs.
- **C — false.** A spread ask *buys* February, so it is a standing bid for February.
- **D — true.** A spread bid sells February, so it feeds a February ask.
- **E — false.** It is the opposite side (a spread bid gives a February ask; a spread ask gives a February bid).

### 7. Terminology — A, B, C, D

- **A — true.** Eurex T7 calls it synthetic matching.
- **B — true.** (Jan +1, Feb −1) + (Feb +1, Mar −1) = (Jan +1, Mar −1), a Jan/Mar spread bid whose price is the sum of the two spread prices. It is a spread implied from two other spreads, a third kind.
- **C — true.** CME: implied IN is a quote "existing in the spread market based on orders in the outright market".
- **D — true.** Implied OUT is a quote in the outright market based on orders in the spread market (together with an outright order).
- **E — false.** CME: "Implication requires at minimum two orders in related markets in the proper combination."

### 8. Implied OUT, a worked scenario — A, D, E

- **A — true.** The spread bidder buys January from the January seller and sells February to the buyer. The buyer never deals with the January seller directly.
- **B — false.** $78.85 is 80.10 − 1.25, the classic sign error. Subtracting a negative spread price *adds*.
- **C — false.** Quantity is capped by the scarcer ingredient: min(40, 25) = **25 lots**.
- **D — true.** Recompute from what is left: January 40 − 10 = 30, spread 25 − 10 = 15, so min(30, 15) = **15 lots**.
- **E — true.** Feb ask = Jan_ask − S_bid = 80.10 − (−1.25) = **$81.35**.

### 9. Implied IN, a worked scenario — A, D, E

- **A — true.** A spread seller wants −0.70 *or higher*. −0.65 is higher, and trades happen at the resting (implied) price, so it trades at −$0.65.
- **B — false.** An implied spread ask needs a January ask and a February bid; neither exists.
- **C — false.** It gets a price $0.05 per barrel *better* than its limit: $50 per lot, $500 on 10 lots.
- **D — true.** Selling the spread means selling January (to the January bidder at $63.40) and buying February (from the February seller at $64.05): 63.40 − 64.05 = −0.65.
- **E — true.** Spread bid = Jan_bid − Feb_ask = 63.40 − 64.05 = **−$0.65**, quantity min(15, 30) = **15**.

### 10. An implied January ask — A, C, E

- **A — true.** P's ask (Feb −1, c = −71.30) plus Q's spread ask (Jan −1, Feb +1, c = −S = +0.85) sum to (Jan −1), c = −70.45: a January **ask** at 71.30 + (−0.85) = **$70.45**, quantity min(20, 12) = **12**.
- **B — false.** Trades happen at the resting price. The buyer pays $70.45, $0.05 better than its limit.
- **C — true.** Q sells 12 January to the buyer at $70.45 and buys 12 February from P at $71.30. Q's spread prints at 70.45 − 71.30 = −0.85, exactly Q's limit.
- **D — false.** The near-month quote has the same side as the spread order: a spread ask gives a January ask.
- **E — true.** P had 20 and sold 12, leaving 8. Q's 12 spreads are fully used, so nothing is left to build an implied January ask from.

### 11. Backwardation — C, D, E

- **A — false.** The spread order sells January at $90.20 and buys February at $89.85: 90.20 − 89.85 = **+$0.35**, exactly its limit.
- **B — false.** $90.55 is 90.20 + 0.35, a sign error.
- **C — true.** The seller accepts $89.80 or more; the best bid is the implied $89.85, so it receives $89.85 ($0.05 better than its limit).
- **D — true.** Feb bid = Jan_bid − S_ask = 90.20 − 0.35 = **$89.85**, quantity min(8, 20) = **8**.
- **E — true.** S = Near − Far > 0 means January is above February: backwardation.

### 12. A tempting trap — A, C, D, E

- **A — true.** (Feb +1) + (Jan −1, Feb +1) = (Jan −1, Feb +2). Nothing cancels.
- **B — false.** 76.40 + (−1.80) = 74.60 is arithmetic on orders that cannot be combined. Nothing is executable behind such a quote.
- **C — true.** January bid + spread ask = (Jan +1) + (Jan −1, Feb +1) = (Feb +1): an implied February bid at Jan_bid − S_ask.
- **D — true.** This is exactly the bug the "firmness" testing invariant exists to catch.
- **E — true.** A spread *ask* is a February *buyer*. Two February buyers cannot complete each other.

### 13. No liquidity from nothing — A, C, D, E

- **A — true.** Conservation: one implied lot consumes one lot of every ingredient, exactly once.
- **B — false.** The 30 implied lots are an *alternative* use of the same January lots, not extra ones. If a January buyer takes all 50, the implied February ask disappears.
- **C — true.** Positions and cash both sum to zero in every correct implied execution; nothing is created or lost.
- **D — true.** The removal test. An implied quote that outlives an ingredient advertises a price the engine cannot honour.
- **E — true.** A trader could do the same trades by hand, with the same counterparties and prices, but would carry leg risk between the separate fills.

### 14. Shared legs, numerically — B, C, D, E

- **A — false.** The *January ask* is the shared leg: every construction draws on the same 18 lots.
- **B — true.** min(30, 22) = **22**. With a larger January order, the spread bids become the bottleneck.
- **C — true.** 22 − 18 = **4 lots** that do not exist.
- **D — true.** min(18, 12) + min(18, 10) = 12 + 10 = **22**.
- **E — true.** Both spread bids route their February sales through the same January ask: min(18, 12 + 10) = min(18, 22) = **18**.

### 15. Implied depth, numerically — A, B, C

Each implied February lot costs (January ask) − (spread bid). Walk both ladders best against best, like merging two sorted lists:

| Implied Feb ask | Lots | Built from |
|---|---|---|
| 60.00 − (−1.00) = **61.00** | 6 | Jan 60.00 (all 6) with spread −1.00 (6 of 8) |
| 60.02 − (−1.00) = **61.02** | 2 | Jan 60.02 (2 of 10) with spread −1.00 (last 2) |
| 60.02 − (−1.03) = **61.05** | 5 | Jan 60.02 (5 of remaining 8) with spread −1.03 (all 5) |

- **A — true.** $61.02 × 2.
- **B — true.** $61.00 × 6.
- **C — true.** 6 + 2 + 5 = 13 = min(16 January lots, 13 spread lots), as conservation requires.
- **D — false.** A correct ladder is path-dependent and costly to compute, which is why venues typically publish only the top one or two implied levels.
- **E — false.** $61.03 would pair the $60.00 January lots with the −1.03 spread bid, but those January lots are already used at the $61.00 level. A naive pair-by-pair ladder publishes it (and 24 lots in total); it is fictitious.

### 16. Recompute, never decrement — A, C, D

- **A — true.** Any fill, cancel, amendment or new order on any ingredient can change implied quotes in other books.
- **B — false.** Recomputation on every event in the group is the *correctness* mechanism, not a performance choice.
- **C — true.** January has 20 − 15 = 5 lots left; min(5, 20) = **5**.
- **D — true.** The January fill happened in the January book, not the implied February book, so a decrement-only design never adjusts the implied quote.
- **E — false.** Only 5 lots can be constructed. The engine would have to reject a fill against its own published quote or begin an atomic commit that cannot complete.

### 17. Real before implied, numerically — A, B, E

- **A — true.** 6 lots from G at $77.00, then 20 implied lots at $77.00 (min(20, 25) = 20). The January ask is now used up, so the recomputed implied ask disappears, and the last 4 lots come from the real $77.03 ask.
- **B — true.** At the same price, real orders trade before implied orders (CME: outrights "always trade first").
- **C — false.** Implied quantity in futures has no time priority, however long it has been displayed.
- **D — false.** 5 spread lots remain, but with no January ask left there is nothing to combine them with.
- **E — true.** (26 × 77.00 + 4 × 77.03) / 30 = (2,002.00 + 308.12) / 30 = 2,310.12 / 30 = **$77.004**.

### 18. Who can be the aggressor — A, C, D

- **A — true.** Implied quotes are only ever passive; a trade needs a real incoming order.
- **B — false.** CME: "implied quantity in futures markets does not have time priority".
- **C — true.** CME states this explicitly.
- **D — true.** An implied bid and an implied ask together involve four real orders, one step beyond what a first-generation engine checks on arrival. CME calculates but does not disseminate such locked or crossed implied quotes.
- **E — false.** Implied quotes never aggress. A book change triggers recomputation, not a trade.

### 19. Price improvement — B, D, E

- **A — false.** Trades happen at the resting price: the buyer pays $76.95.
- **B — true.** The better-priced implied ask (25 lots available, min(40, 25)) fills all 20 lots first.
- **C — false.** The spread bidder buys January at $74.95 and sells February at $76.95: 74.95 − 76.95 = **−$2.00**, exactly its limit.
- **D — true.** $0.05 × 1,000 barrels = **$50 per lot**; × 20 lots = **$1,000**.
- **E — true.** 74.95 − (−2.00) = **$76.95**, 5 ticks better than the real $77.00 ask.

### 20. Closing a cross-book gap — A, B, D, E

- **A — true.** Implied spread ask = Jan_ask − Feb_bid = 74.95 − 76.97 = **−$2.02**, quantity min(40, 10) = 10.
- **B — true.** B bids up to −2.00 and −2.02 is cheaper, so B trades 10 spreads at the resting price −$2.02: B buys January at $74.95 and sells February to K at $76.97.
- **C — false.** The improvement goes to the real order that arrives *last*, because trades happen at the resting side's price. Here that is B.
- **D — true.** K's bid is used up, so the implied ask is gone; B's remaining 25 − 10 = 15 spreads rest at −$2.00 (and, with the 30 January lots left, they imply a February ask at $76.95 × 15).
- **E — true.** Sell 10 spreads to B at −2.00, buy January at 74.95, sell February to K at 76.97: 76.97 − 74.95 − 2.00 = **+$0.02** per barrel ($20 per lot), with no risk if all three fill.

### 21. Tick rounding, an implied ask — A, C, E

- **A — true.** The buyer pays 100.50, the January seller receives 100.00, so the spread prints at 100.00 − 100.50 = **−0.50**: 0.15 better than B's −0.35 limit and a valid 0.05 spread tick.
- **B — false.** The rounding rule must live in exactly one function shared by matching, market data and clearing; components that round differently disagree about which prices exist.
- **C — true.** 100.00 − (−0.35) = **100.35**, which is not a multiple of 0.25.
- **D — false.** Rounding is *outwards*, worse for whoever trades against the implied quote: an implied ask rounds **up**, to **100.50**. Publishing 100.25 would force the spread bidder to trade at 100.00 − 100.25 = −0.25, above its −0.35 limit.
- **E — true.** That is the reason for rounding outwards.

### 22. Tick rounding, an implied bid — B, C, D, E

- **A — false.** In implied OUT, the outright orders trade at the published (rounded) price and the gain goes to the *passive spread order* (L here). Only in implied IN does the gain go to the aggressor.
- **B — true.** Rounding up to 50.00 would make L's spread print at 50.00 − 50.00 = 0.00, worse than L's +0.15 limit. The engine would have traded L's order beyond its limit.
- **C — true.** L sells January to J at 50.00 and buys February from the incoming seller at 49.75: 50.00 − 49.75 = **+0.25**, 0.10 better than L's +0.15 limit.
- **D — true.** Feb bid = Jan_bid − S_ask = 50.00 − 0.15 = **49.85**, off the 0.25 grid.
- **E — true.** An implied bid rounds *down* (outwards): **49.75**.

### 23. Signed prices in code — A, D, E

- **A — true.** |−2.00| = 2.00 > 1.95, so the buggy sort puts −2.00 first, but −1.95 is the better bid.
- **B — false.** The seller is matched at −2.00 instead of the best bid −1.95, a *worse* price: $0.05 × 1,000 = $50 per lot.
- **C — false.** Outright futures prices can go negative too: May 2020 WTI settled at −$37.63, and a broker that assumed price > 0 paid a $1.75 million penalty plus about $82.6 million in restitution.
- **D — true.** −200 and −195 ticks compare correctly with ordinary integer comparison; bids sort descending and asks ascending, with no special cases.
- **E — true.** For positive prices absolute value and signed value sort the same way; the bug surfaces on the first day of contango.

### 24. Implied liquidity in market data — B, C, D

- **A — false.** The opposite: one order event can change implied quotes in several other books, so implied-enabled products have a structurally *higher* ratio of market-data messages to order messages.
- **B — true.** CME's MDP 3.0 disseminates a 2-deep implied book for implied-eligible futures.
- **C — true.** Venues publish implied liquidity separately, aggregated, or not at all; a consumer must know which.
- **D — true.** An implied quote vanishes when an ingredient in another book is cancelled or filled.
- **E — false.** CME calculates but does not disseminate, for example, implied bids locked or crossed with implied offers, and implied OUT quotes from non-1:1 inter-commodity spreads.

### 25. Engineering an implied match — A, C, E

- **A — true.** All legs are validated first and then committed atomically; one failed leg voids the whole match.
- **B — false.** A first-generation implied match prints a trade in every book involved; the Level 3 example prints January, spread and February trades.
- **C — true.** "Partition by symbol" becomes "partition by related instrument group", so one thread sequences every book an implied match can span.
- **D — false.** Hash-map iteration order can vary, which breaks determinism and replay.
- **E — true.** Whichever event is sequenced first consumes the lots, and recomputation shrinks or removes the implied quote before the next event is processed.

### 26. Partial fills, leg risk, and leg prices — A, C, D

- **A — true.** A resting spread order behaves like any resting limit order: the unfilled remainder stays at the same price with its priority intact.
- **B — false.** Every leg price must be on its instrument's tick grid, consistent with every order, and inside price limits, or clearing systems reject the trades.
- **C — true.** The two February legs trade between the two spread bidders, and no order states a February price; the engine anchors one month to a reference price by a documented, deterministic rule.
- **D — true.** FOK and IOC orders execute on arrival or are cancelled, so they never rest and never become ingredients.
- **E — false.** Each spread lot fills as a complete pair (one January bought, one February sold) in the same atomic event; a partial fill gives *fewer* spreads, never a lone leg.

### 27. Generations, numerically — B, C, D

- **A — false.** Generation *k* uses *k* + 1 real orders: generation 2 uses three.
- **B — true.** Sep bid + implied Nov ask: 75.90 − 77.35 = **−1.45**, equivalently the sum of all three real orders' weights, 75.90 − 76.83 − 0.52. Quantity min(10, 8, 5) = **5**, bottlenecked by the spread bid.
- **C — true.** Oct ask + Oct/Nov bid: 76.83 − (−0.52) = **77.35** (implied OUT), quantity min(8, 5) = 5.
- **D — true.** Sep bid + Oct ask: 75.90 − 76.83 = **−0.93** (implied IN), quantity min(10, 8) = 8.
- **E — false.** A generation-1 Sep/Nov bid needs two *real* orders (a real November ask or a real Sep/Oct bid). Those exist only as implied quotes, so a generation-1 engine shows nothing.

### 28. Best route, numerically — B, C, D, E

Edge costs for a March buyer: Jan ask 50.00, Feb ask 50.40, Mar ask 50.95; Jan → Feb 0.35; Feb → Mar 0.40; Jan → Mar 0.85. Run Bellman–Ford by rounds:

| Round (max real orders) | Jan | Feb | Mar |
|---|---|---|---|
| 1 (generation 0) | 50.00 | 50.40 | 50.95 |
| 2 (generation ≤ 1) | 50.00 | min(50.40, 50.00 + 0.35) = **50.35** | min(50.95, 50.40 + 0.40, 50.00 + 0.85) = **50.80** |
| 3 (generation ≤ 2) | 50.00 | 50.35 | min(50.80, 50.35 + 0.40) = **50.75** |

- **A — false.** Best-price search is a shortest-path problem; each round touches every edge once and needs no route enumeration. The trouble lies in allocation, depth, fan-out and atomicity, not in finding the best price.
- **B — true.** A cycle has a zero position vector; if its total weight is non-negative the orders could trade with each other. A correctly running engine leaves none at rest within its enabled depth.
- **C — true.** Round 2 gives 50.80 (real February ask + Feb/Mar spread bid).
- **D — true.** 50.00 (Jan ask) + 0.35 (Jan/Feb bid) + 0.40 (Feb/Mar bid) = 50.75, using three real orders.
- **E — true.** Round 3 gives 50.75.

### 29. The combinatorial wall — A, B, D, E

- **A — true.** Routes of length L to December number 11! / (12 − L)!: 1, 12, 122, 1,112, 9,032, … cumulatively, reaching about 108 million with no limit.
- **B — true.** A butterfly's vector (+1, −2, +1) touches three nodes at once, so it is not an edge. Finding orders that sum exactly to a target vector is in general integer programming.
- **C — false.** Extra generations add only *routes* to the same real orders. Each extra link adds another bid-ask spread to cross, so the benefit shrinks while the cost explodes.
- **D — true.** Generation ≤ 1 reaches 23 books (June itself, 11 outrights, 11 spreads against June); generation ≤ 2 adds every remaining spread between two other months: all 78.
- **E — true.** A shortest-path search returns *a* best path; documented, deterministic tie-breaking needs all of them, ranked.

### 30. Testing implied logic — A, C, D, E

- **A — true.** "Limits respected" is an invariant in its own right.
- **B — false.** Such a quote advertises a price the engine cannot honour; the removal invariant exists to catch it.
- **C — true.** The invariants are crisp global properties, ideal for a fuzzer that checks them after every event.
- **D — true.** Firmness, including shared legs.
- **E — true.** Conservation is the first of the six invariants.

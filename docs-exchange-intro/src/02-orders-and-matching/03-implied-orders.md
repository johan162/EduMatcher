# Implied Orders and Synthetic Liquidity

This concept trips up almost every developer encountering derivatives exchange systems for the first time — and unlike most topics in this book, it cannot be understood from a single example. Implied matching is genuinely layered: the price arithmetic is simple, the quantity rules are less simple, the priority interactions are subtle, and the engineering consequences are severe. This chapter therefore builds in ten explicit levels. Each level introduces exactly one new idea and works it through numerically before the next level begins. If a level feels obvious, read its example anyway — the numbers accumulate, and later levels reuse them.

One promise before we begin, which the rest of the chapter will prove repeatedly: **implied orders do not create liquidity from nowhere.** They are a different *expression* of liquidity that already exists in other books. Hold on to that sentence; every level below is ultimately a demonstration of it.

## Level 0: The Instruments

The clearest real-world home of implied orders is the **futures market**. A futures contract is a standardised agreement to buy or sell a fixed quantity of an underlying asset — crude oil, wheat, a stock index — at a predetermined price on a specified future delivery date. Each delivery month trades as a separate instrument with its own independent order book: January WTI crude and February WTI crude are two distinct products, each with its own buyers and sellers.

The same underlying therefore trades simultaneously in several month-dated books, and participants often want to trade the *difference* between two months just as much as either month outright. There are three standard motivations:

1. **Rolling a position.** A trader long January who wants to stay long crude past January's expiry must sell January and buy February. Doing this as two separate outright trades exposes them to the market moving between the two fills.
2. **Relative-value trading.** A trader may believe February is too expensive *relative to* January without having any view on the outright price of oil at all. Their desired exposure is purely the differential.
3. **Margin efficiency.** A long-January/short-February position is largely hedged against flat-price moves in crude, so clearing houses margin the *spread* far more lightly than two independent outright positions. (CME publishes these inter-month margin credits explicitly in its SPAN parameters.)

The naive way to get spread exposure — submit two outright orders and hope both fill — carries **leg risk**: one leg fills, the other does not, and the trader is left with an unintended outright position. Exchanges solved this by listing the spread itself as a tradeable instrument.

## Level 1: The Spread Instrument and Its Sign Convention

A **calendar spread** is a single listed instrument whose price is defined as the difference between two delivery months. Throughout this chapter we use the convention the major venues use for this product type:

```
spread price  S  =  Near-month price − Far-month price
             (here: S = January − February)
```

**Buying** the spread means buying the near month and selling the far month, simultaneously, as one instruction. **Selling** the spread is the mirror image.

The sign takes a moment to internalise, so work through both cases:

| Spread price | Meaning | A spread *buyer* does |
|---|---|---|
| S = −$2.00 | January trades $2.00 **below** February | Buys Jan, sells Feb; e.g., buys Jan at $75.00 and sells Feb at $77.00 |
| S = +$0.50 | January trades $0.50 **above** February | Buys Jan, sells Feb; e.g., buys Jan at $76.50 and sells Feb at $76.00 |

Note something slightly counterintuitive in the first row: the spread *buyer* at −$2.00 pays $75 and receives $77. Buying a negative-priced spread means *receiving* the differential. Nothing is broken; the price is simply a signed difference, and it trades on its own tick grid like any other instrument.

**Leg price assignment.** When a spread trade executes, the clearing system needs a concrete price for each leg, not just their difference. The exchange assigns leg prices using a documented rule — typically anchoring one leg to that month's last trade or settlement price and deriving the other so the difference equals the spread trade price, with both legs constrained to valid outright ticks. The economics for the traders depend only on the difference; the assignment rule exists so that positions, P&L, and margin can be computed per instrument. We will meet this again at Level 8.

## Level 2: The Core Identity and the Six Formulas

Everything in implied matching follows from rearranging one identity:

```
S = Jan − Feb     ⇔     Feb = Jan − S     ⇔     Jan = Feb + S
```

Each rearrangement says: *if you know a firm price in two of the three books, you know a synthetic price in the third.* Applying bid/ask logic to each rearrangement produces exactly six derived quotes. This table is the reference for the whole chapter; every worked example below is one row of it with numbers attached.

| Derived (implied) quote | Built from | Formula |
|---|---|---|
| Implied **Feb ask** | Jan ask + Spread bid | Jan_ask − S_bid |
| Implied **Feb bid** | Jan bid + Spread ask | Jan_bid − S_ask |
| Implied **Jan ask** | Feb ask + Spread ask | Feb_ask + S_ask |
| Implied **Jan bid** | Feb bid + Spread bid | Feb_bid + S_bid |
| Implied **Spread ask** | Jan ask + Feb bid | Jan_ask − Feb_bid |
| Implied **Spread bid** | Jan bid + Feb ask | Jan_bid − Feb_ask |

Two terms of art, used exactly as CME's Globex documentation uses them:

- **Implied IN**: an implied order created **in** the *spread* book, derived **from** two outright orders (the bottom two rows).
- **Implied OUT**: an implied order created in an *outright* book, derived **out of** a spread order plus an outright order (the top four rows).

The mnemonic: *in(to the spread), out (of the spread)*. Be aware that informal usage in the industry is inconsistent, so when reading a venue's documentation, check its definitions rather than assuming.

Do not memorise the table. Instead, when you need a formula, ask the operational question: *"Who does the synthetic counterparty trade with, on each leg, to make this price firm?"* The next two levels show exactly how that question is answered.

## Level 3: Implied OUT — A Complete Worked Example

This is the canonical case: a spread order plus an outright order jointly manufacture a quote in a book that may otherwise be completely empty.

**The books before anything happens:**

| Book | Side | Price | Lots | Who |
|---|---|---|---|---|
| January (outright) | Ask | $75.00 | 50 | Trader A |
| Jan/Feb Spread | Bid | −$2.00 | 30 | Trader B |
| February (outright) | — | *empty* | — | — |

Trader A wants to sell up to 50 January lots at $75.00 or better. Trader B wants to buy up to 30 spreads at −$2.00 — that is, B will buy January and sell February whenever February is at least $2.00 above January.

**Answering the operational question.** Could anyone, right now, firmly sell February even though the February book is empty? Yes: Trader B would. B is committed to selling February *provided* B simultaneously buys January $2.00 cheaper. Trader A is committed to selling January at $75.00. Chain the commitments: B can buy January at $75.00 from A, so B can sell February at $75.00 − (−$2.00) = **$77.00**. Formula row one, with numbers: Implied Feb ask = Jan_ask − S_bid = 75.00 − (−2.00) = 77.00.

**Quantity** is capped by the scarcer ingredient: min(50, 30) = **30 lots**. Trader B can only route 30 lots of February selling through this construction, however much January is on offer.

The engine therefore publishes into the February book:

| Book | Side | Price | Lots | Source |
|---|---|---|---|---|
| February | Ask | $77.00 | 30 | **Implied** (A's outright + B's spread) |

**Execution.** Trader C submits a buy limit for 20 February at $77.00. Matching the implied quote requires three legs to fire *simultaneously and atomically*:

```{.mermaid width=600}
sequenceDiagram
    participant C as Trader C (Feb buyer)
    participant ME as Matching Engine
    participant A as Trader A (Jan ask 75.00)
    participant B as Trader B (Spread bid −2.00)

    C->>ME: BUY 20 FEB @ 77.00
    Note over ME: Implied Feb ask 77.00 × 30 identified.<br/>All legs validated, then committed atomically.
    ME->>A: Leg 1 — A SELLS 20 JAN @ 75.00 to B
    ME->>B: Leg 2 — B's spread order FILLS 20 @ −2.00
    ME->>C: Leg 3 — B SELLS 20 FEB @ 77.00 to C
    Note over ME: Three trade prints: JAN 20@75.00,<br/>SPREAD 20@−2.00, FEB 20@77.00
```

Verify each party got exactly what their order asked for:

- **A** sold 20 January at $75.00 — precisely A's limit price.
- **B** bought 20 spreads at −$2.00: long 20 Jan at $75.00, short 20 Feb at $77.00; 75 − 77 = −2 ✓. B's margin is computed on the spread exposure, which is far smaller than two outrights.
- **C** bought 20 February at $77.00 — precisely C's limit price. C need never know, and on most feeds cannot know at fill time, that the counterparty was synthetic.

**The books after the match:**

| Book | Side | Price | Remaining lots |
|---|---|---|---|
| January (outright) | Ask | $75.00 | 30 *(was 50)* |
| Jan/Feb Spread | Bid | −$2.00 | 10 *(was 30)* |
| February (implied) | Ask | $77.00 | **10** = min(30, 10) |

**Conservation accounting — the promise from the introduction, kept.** Before the match, the system contained 50 committed January lots and 30 committed spread lots; the 30-lot February quote was a *view* of those commitments, not an addition to them. After the match, 30 January lots and 10 spread lots remain, and the implied view has shrunk accordingly. Every one of the 20 lots C bought was constructed from one of A's lots plus one of B's lots, and each was consumed exactly once.

**The removal test.** Cancel Trader A's January order and the implied February ask vanishes in the same event-processing cycle — there is nothing left to build it from. This is the definitive demonstration that the implied book holds no independent liquidity. Any implementation in which an implied quote can survive the cancellation of one of its ingredients is broken, and dangerously so: it is advertising a price the engine cannot honour.

## Level 4: Implied IN — Two Outrights Manufacture a Spread Quote

Now the other direction. This time the *spread* book is thin and the outrights are live.

**The books:**

| Book | Side | Price | Lots | Who |
|---|---|---|---|---|
| January (outright) | Bid | $74.40 | 25 | Trader D |
| February (outright) | Ask | $76.60 | 40 | Trader E |
| Jan/Feb Spread | — | *empty* | — | — |

The operational question: could anyone firmly *buy* the spread right now? Buying the spread means buying January and selling February — and neither of those is immediately possible against D and E (D is a January *buyer*, E is a February *seller*). Ask the mirror question instead: could anyone firmly **sell** the spread? Selling the spread means selling January and buying February. Selling January is possible — hit D's bid at $74.40. Buying February is possible — lift E's ask at $76.60. So an incoming spread seller can transact right now at 74.40 − 76.60 = **−$2.20**. The market is synthetically *bidding* −$2.20 for the spread:

```
Implied S_bid = Jan_bid − Feb_ask = 74.40 − 76.60 = −2.20
Quantity      = min(25, 40) = 25 lots
```

Trader F submits a sell for 10 spreads at −$2.20. Atomic decomposition:

1. **Jan leg:** F sells 10 January at $74.40 to Trader D.
2. **Feb leg:** F buys 10 February at $76.60 from Trader E.
3. **Spread print:** F sold 10 spreads at 74.40 − 76.60 = −$2.20 ✓.

D and E each received a perfectly ordinary outright fill at their own limit price; neither needs to know a spread order was the aggressor. Afterwards: Jan bid 15 lots remain, Feb ask 30 lots remain, implied spread bid −$2.20 × 15 = min(15, 30).

For completeness, the opposite synthetic quote needs the opposite ingredients: an implied spread **ask** requires a January *ask* and a February *bid* (Implied S_ask = Jan_ask − Feb_bid). With only D and E in the books, no implied spread ask exists — a synthetic quote exists only when every leg of its construction is individually executable.

## Level 5: Quantity Rules — min(), Aggregation, and Shared Legs

The min() rule from Level 3 generalises, and the generalisation is where implementations start to acquire bugs.

**Aggregation across contributors.** Suppose a second spread bidder joins Level 3's books:

| Book | Side | Price | Lots | Who |
|---|---|---|---|---|
| January | Ask | $75.00 | 50 | Trader A |
| Spread | Bid | −$2.00 | 30 | Trader B |
| Spread | Bid | −$2.00 | 15 | Trader H |

Both spread bids combine with the *same* January ask to imply February asks at $77.00. The published implied quantity is not min(50,30) + min(50,15) = 45 by coincidence — it is min(50, 30+15) = **45**, and the distinction matters. The January ask is a **shared leg**: if A's ask were only 40 lots, the correct implied quantity would be min(40, 45) = 40, even though each pairwise min would still compute 30 and 15. An implementation that computes implied quantity pairwise and sums will over-advertise whenever a leg is shared. The correct statement: *the implied quantity at a price is the maximum flow that can be routed through the contributing orders simultaneously* — for chains, the bottleneck leg; for aggregations sharing a leg, the shared leg caps the total.

**Regeneration after partial fills.** Implied quotes are recomputed, not decremented. After any fill or cancellation touching a contributing order, the engine re-derives the implied book from the current state of the real books. Level 3's post-trade table (implied 10 = min(30, 10)) is a recomputation, not "30 minus 20."

## Level 6: Priority — Real Orders vs Implied Orders at the Same Price

Suppose the February book contains both a real resting ask and an implied ask at the same price:

| February book | Price | Lots | Source |
|---|---|---|---|
| Ask | $77.00 | 5 | **Real** — Trader G, resting since 09:31 |
| Ask | $77.00 | 30 | Implied (A + B, per Level 3) |

Trader C's buy for 20 at $77.00 arrives. Who fills?

The general rule on the major venues: **at the same price level, direct (real) orders have priority over implied orders**, regardless of when the implied quote appeared. C's fill decomposes as 5 lots from G (a plain two-party outright trade), then 15 lots via the implied construction (the three-leg atomic execution from Level 3).

The rationale mirrors the displayed-vs-hidden priority logic from the *Hidden Liquidity* section: a participant who committed capital directly in this book is rewarded ahead of a price that is merely a synthetic reflection of commitments elsewhere. It also has a practical engineering justification — the two-party fill is cheaper and simpler, so exhausting real liquidity first minimises the number of multi-leg atomic executions. Exchanges document the exact allocation per product (CME specifies implied participation within each product's matching algorithm), so treat "real before implied at the same price" as the strong default, and the product's rulebook as authoritative.

## Level 7: Price Improvement Through Implication

Implication does not just fill empty books; it can *beat* the real book. Suppose:

| Book | Side | Price | Lots |
|---|---|---|---|
| January | Ask | $74.95 | 40 |
| Spread | Bid | −$2.00 | 25 |
| February | Ask (real) | $77.00 | 60 |

The implied February ask is 74.95 − (−2.00) = **$76.95** — one tick *better* than the real February ask. An incoming market buy for 20 February fills at $76.95 via the implied path, and the real $77.00 seller is not touched. This is price improvement in exactly the Part II sense, delivered by cross-book arbitrage that the engine performs internally and instantly, rather than leaving a five-cent-wide inconsistency for a fast participant to harvest.

This is the deeper purpose of implied functionality: it keeps the *set* of related books mutually consistent. Without implication, the relationship Jan_ask − S_bid < Feb_ask is a standing free lunch for whoever notices first; with implication, the engine itself closes the gap on behalf of the resting orders.

## Level 8: Second-Generation Implieds

Everything so far combined exactly two real orders. Some venues go further and allow an implied order to be built from a chain — most commonly, two spread orders whose middle legs cancel out.

Suppose a March book exists, along with a Feb/Mar spread (S₂ = Feb − Mar):

| Book | Side | Price | Lots |
|---|---|---|---|
| Jan/Feb Spread (S₁) | Bid | −$2.00 | 30 |
| Feb/Mar Spread (S₂) | Bid | −$1.50 | 20 |

The S₁ bidder stands ready to buy Jan and sell Feb; the S₂ bidder stands ready to buy Feb and sell Mar. Chain them and the February legs offset: jointly, the pair stands ready to buy January and sell **March** at (−2.00) + (−1.50) = **−$3.50**. That is an implied Jan/Mar spread bid at −$3.50, quantity min(30, 20) = 20 — an implied quote *both of whose ingredients are themselves spread orders*.

When an incoming Jan/Mar seller hits it, the decomposition produces four leg positions across three participants, and the two internal February legs trade against each other at an exchange-assigned price (Level 1's leg-price-assignment rule, now doing real work: the February price is invisible in every order involved and must be manufactured consistently, on-tick, by the engine).

**Why depth is limited.** Each additional generation multiplies the candidate combinations: with M related instruments, first-generation implieds already require examining every adjacent pair on every book event; second generation adds chains of chains, and the recomputation cost — and the size of the atomic multi-leg commit — grows combinatorially. Venues therefore cap implication depth, typically at one or two generations, and CME's product documentation specifies per product which implied types are enabled at all. When designing an engine, the implication depth is a configuration decision with a direct latency budget attached, not a free feature.

## Level 9: Tick Alignment — Where the Arithmetic Meets Reality

The formulas of Level 2 are exact arithmetic; real books are not. Two complications, both descendants of the *Tick Sizes and Fractional Ticks* chapter:

**Spread ticks can differ from outright ticks.** Venues sometimes list a spread on a finer tick grid than its outright legs, precisely because spreads are less volatile than outrights. The moment the grids differ, an implied outright price computed from a spread price may land off the outright grid, and an implied spread price computed from two outrights may land off the spread grid. The engine must round — and, as with midpoint pegs, the rounding direction is an economic decision (it gives the residual tick fraction to one side), must be documented, and must be implemented in exactly one authoritative function shared by matching, market data, and clearing.

**Leg price assignment must land on-tick.** Level 8's internally-generated February price must be a valid February tick, must keep every leg pair's difference equal to its spread trade price, and should stay inside that month's price collars. Venues publish their leg-pricing algorithms; an engine that assigns off-tick or collar-violating leg prices will produce trades that downstream systems reject — a failure mode far worse than rejecting the implied match up front.

## Level 10: How Implieds Appear in Market Data

Participants need to know implied liquidity exists, and sophisticated participants need to know *which part* of a displayed quantity is implied — an implied quote can vanish for reasons invisible in this book (its far-leg ingredient was cancelled), so its firmness has a different character than a real order's. Venues answer this in one of three documented ways: publish implied quantities as a separate book alongside the real book (CME's MDP3 feed disseminates implied depth distinctly for enabled products); aggregate real and implied quantity into one displayed number; or display only the real book and let implieds surface purely at execution. A market-data consumer must know which policy the venue uses, or its book reconstruction will disagree with the venue's — a classic source of "our depth doesn't match the exchange's" support tickets.

## Engineering Deep-Dive

With the mechanics established, the engineering challenges can be stated precisely.

**Recalculation triggers and fan-out.** Every order event on any instrument in a related group — add, cancel, amend, partial fill — potentially changes implied quotes in every other book of the group. One cancellation of a deep spread order can move implied prices in several outright books at once, each movement generating market data. This *event fan-out* means implied-enabled products have a structurally higher ratio of market-data messages to order messages, which must be budgeted in the publishing path, not discovered in production.

**Atomicity.** All legs of an implied match commit together or not at all. The single-threaded-per-book design from *The Matching Engine* chapter now shows its limits: an implied match spans multiple books, so either the related instrument group is assigned to one sequencer thread (the common production choice — the "partition by symbol" rule from Part IV becomes "partition by *related instrument group*"), or a cross-book commit protocol is required, with all the latency and complexity that implies.

**Double-execution prevention.** Trader A's January order participates simultaneously in the January book and in the implied February ask. If a direct January buyer and a February buyer arrive in adjacent events, both paths claim A's lots — and only one may win. Serialised processing within the instrument group resolves this naturally: whichever event is sequenced first consumes the lots, and the recomputation step (Level 5) shrinks or removes the implied quote before the second event is processed. Any design that evaluates implied quotes against a stale copy of the contributing books reintroduces the race.

**Determinism.** Implied recomputation must itself be deterministic: given the same event sequence, the same implied quotes must appear, in the same order, with the same rounding. Iterating over candidate combinations in hash-map order, or letting floating-point spread arithmetic creep in, breaks the replay guarantees the *Determinism, Replay, and Persistence* chapter establishes.

**Testing invariants.** Implied logic is an ideal target for property-based testing, because its correctness conditions are crisp global invariants rather than example-shaped assertions:

1. *Conservation:* after any event sequence, total resting quantity per real order never goes negative and is never consumed twice.
2. *Firmness:* every published implied quote is executable at that instant — each ingredient exists with sufficient quantity.
3. *Consistency:* no published implied price is off-grid for its book.
4. *No-arbitrage closure:* after quiescence, no combination within the enabled implication depth prices better than the published books (Level 7's gap is always closed).
5. *Removal test:* cancelling any single ingredient removes or correctly shrinks every implied quote built on it, within the same event cycle.

A fuzzer generating random order flow across three related books, asserting these five properties after every event, will find more implied-matching bugs than any hand-written example suite.

> **Key idea:** Implied orders are not free liquidity. They are the engine expressing, in one book, commitments already resting in others — so that related markets stay consistent, empty months stay tradeable, and cross-book price gaps are closed by the exchange itself rather than harvested by the fastest participant. When an implied order matches, real orders in real books are consumed, exactly once, atomically. Everything difficult about implementing implieds — shared-leg quantities, priority, tick rounding, fan-out, double-execution races — is downstream of taking that atomic, exactly-once consumption seriously.

## Real-World Implementations

**CME Globex** is the reference implementation for futures: implied IN and implied OUT functionality per product, implied depth disseminated on MDP3, and per-product documentation of which implied types and generations are enabled. **Eurex T7** provides equivalent functionality under the name *synthetic matching* for futures calendar spreads, with documented rules for synthetic price determination and leg pricing. **ICE** likewise operates implied pricing across its energy futures and their spread markets. The vocabulary differs per venue; the three-book mechanics of this chapter are the common core.

## Self-Check Exercises

*Answers follow; attempt each before reading on. Convention throughout: S = Near − Far.*

**E1.** January: bid $74.20, ask $74.60. February: bid $76.10, ask $76.55. Compute the implied Jan/Feb spread bid and ask.

**E2.** February bid $76.40 × 12 lots; Jan/Feb spread ask −$1.80 × 20 lots. What implied quote do these create, at what price and quantity?

**E3.** In Level 3's books, Trader C instead submits a buy for 40 February at $77.00. Describe the outcome.

**E4.** January ask $75.00 × 10; two spread bids at −$2.00 of 8 and 6 lots. What implied February quantity is published at $77.00, and why is 8 + 6 = 14 the wrong answer?

**E5.** Jan/Feb spread ask −$1.70; Feb/Mar spread ask −$1.20. What second-generation implied quote do these create?

**E6.** A colleague's implementation decrements implied quantities on fill instead of recomputing them, "for performance." Give one concrete sequence of events where this produces a firm-looking quote the engine cannot honour.

&nbsp;

<div style="page-break-after: always;"></div>

&nbsp;

### Solutions

**E1.** Implied S_bid = Jan_bid − Feb_ask = 74.20 − 76.55 = **−$2.35**. Implied S_ask = Jan_ask − Feb_bid = 74.60 − 76.10 = **−$1.50**. (Sanity check: the implied spread market −2.35 / −1.50 is wide because it stacks both outright spreads — an incoming spread trader pays both legs' crossing costs.)

**E2.** This is a trap, and the trap is the point: **these two orders imply nothing.** Check the legs. The spread *ask* is a committed spread seller — sells Jan, buys Feb. For any construction involving it to be firm, its Feb-buying leg needs a resting Feb *ask* to lift; the only Feb order present is a *bid*, another buyer. No leg-complete construction exists, so no implied quote is published. Cross-check against the Level 2 table: the combination Feb_bid + S_ask appears in no row — the table pairs Feb_bid with S_bid (implied Jan bid) and Feb_ask with S_ask (implied Jan ask). If you mechanically computed 76.40 + (−1.80) = $74.60 and called it an implied Jan quote, you manufactured a price with no executable legs behind it — precisely the class of bug that testing invariant 2 ("every published implied quote is executable at that instant") exists to catch. The lesson: derive implied quotes from the operational question, never from sign-blind arithmetic.

**E3.** The implied ask at $77.00 is 30 lots (min(50, 30)). C fills 30 lots via the three-leg construction: A sells 30 Jan at $75.00, B's spread fills 30 at −$2.00 (fully consumed), C buys 30 Feb at $77.00. B's spread order is exhausted, so the implied quote is recomputed to zero and C's remaining 10 lots rest as a real February bid at $77.00 — the February book now has genuine resting liquidity for the first time. A retains 20 January lots at $75.00.

**E4.** Published quantity = min(10, 8 + 6) = **10**. The January ask is a shared leg: both spread bids route their February selling through the same 10 January lots, so the construction can carry at most 10 lots in total. Pairwise-min-then-sum (min(10,8) + min(10,6) = 14) counts the shared leg twice and over-advertises by 4 lots — quantity the engine could not deliver if hit.

**E5.** Selling both spreads = (sell Jan, buy Feb) + (sell Feb, buy Mar) = sell Jan, buy Mar, with the Feb legs offsetting. Jointly they will *sell* the Jan/Mar spread at (−1.70) + (−1.20) = **−$2.90**: an implied Jan/Mar spread **ask** at −$2.90, quantity the min of the two spread quantities. The engine must additionally assign a consistent, on-tick February price for the two internal legs that cross each other.

**E6.** Books: Jan ask 75.00 × 20 (A); spread bid −2.00 × 20 (B) → implied Feb ask 77.00 × 20. Event 1: a direct January buyer lifts A for 15 lots. A's remaining quantity is 5, so the true implied quantity is min(5, 20) = 5. A decrement-only implementation saw no fill *in the February book* and still advertises 20. Event 2: a February buyer sends buy 12 at $77.00 — the engine can construct only 5 lots and must reject, partially fill against a phantom, or (worst) let the atomic commit fail midway. Recomputation on every contributing-book event is not an optimisation opportunity; it is the correctness mechanism.


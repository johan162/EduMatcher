# The Opening and Closing Auction


Trading does not simply start at 9:30am and stop at 4:00pm (for US equities). The transition between closed and open trading is managed through a **call auction**, also called a **fixing** or **uncross**.

## The Problem an Auction Solves

Imagine the exchange has been closed overnight. Many participants have new orders to submit. If the exchange simply opened and started matching immediately, the first few orders would define the opening price, which would be arbitrary and potentially far from "fair value" based on overnight news.

Instead, exchanges run an **opening auction**:

1. During a pre-open period (e.g., 7:00am–9:30am for NYSE), participants submit limit orders. These orders are accepted but not matched. The book quietly accumulates interest on both sides.

2. At the close of the auction period, the exchange's **equilibrium algorithm** finds the single price at which the maximum quantity can trade. This is the **equilibrium price** (also called the **clearing price** or **auction price**).

3. All orders that can trade at the equilibrium price are **uncrossed** (matched) simultaneously, all at that one price. There is no sweeping through levels, everyone trades at the same price.

4. Any remaining unfilled orders transition to the continuous book.

The result is a fair opening price that reflects the overnight information available to all participants simultaneously, rather than favouring whoever happened to submit their order a few milliseconds earlier.

## Finding the Equilibrium Price

The equilibrium price is the price that maximises total traded volume, the **maximum executable volume rule**. For each candidate price, the algorithm calculates:
- How many buy orders would trade at that price or better (buyers willing to pay at least that much)
- How many sell orders would trade at that price or better (sellers willing to accept at most that much)

The executable volume at each candidate price is `min(cumulative_bids, cumulative_asks)`. The price that maximises this is the equilibrium.

**A worked example.** During the pre-open period, the following orders have accumulated:

*Buy orders:* 500 shares at $152, 1,000 shares at $151, 800 shares at $150

*Sell orders:* 600 shares at $150, 900 shares at $151, 800 shares at $152

The equilibrium algorithm evaluates each candidate price:

| Candidate Price | Buyers willing to pay ≥ price | Sellers willing to accept ≤ price | Executable (min) |
|---|---|---|---|
| $150 | 500+1,000+800 = 2,300 | 600 | **600** |
| $151 | 500+1,000 = 1,500 | 600+900 = 1,500 | **1,500** ← maximum |
| $152 | 500 | 600+900+800 = 2,300 | **500** |

The equilibrium price is **$151** , the single price at which the most volume (1,500 shares) can trade. All buyers who bid $151 or more (1,500 shares total) and all sellers who asked $151 or less (1,500 shares total) trade simultaneously at $151, regardless of their individual limit prices. The buyer who bid $152 still pays only $151, receiving $1 per share of price improvement. The seller who asked $150 still receives $151, getting $1 above their minimum. The remaining 800-share sell order at $152 does not execute (too expensive; no buyers remain) and transitions to the continuous book.

**Tie-breaking when multiple prices produce the same volume:** If two candidate prices both yield 500 shares executable, the algorithm must choose between them. The standard tie-breaking rules, applied in order, are:

1. **Minimise the imbalance.** The imbalance is the unfilled quantity on the heavier side after the uncross. Prefer the price that leaves the smallest imbalance. If at $151 the buy side has 500 executable but 200 additional buy orders remain, the imbalance is 200. A price with a smaller imbalance is preferred.

2. **Match market pressure.** If imbalances remain equal, prefer the price in the direction of the remaining pressure, if there is a surplus of buys, choose the higher of the tied prices; if a surplus of sells, the lower.

3. **Proximity to reference price.** If all else is still equal, choose the price closest to a reference price (typically the previous close or the last traded price from the previous session).

**Indicative pricing during the accumulation period:** While the auction is still accumulating orders and before uncrossing, many exchanges continuously publish an **indicative uncross price**, the price that *would* result if uncrossing happened at that moment. This lets participants adjust their orders as the indicative price evolves. The indicative price is recalculated after every order arrives.

**Auction imbalance messaging:** Exchanges often publish the **imbalance**, how many more shares are on the buy side than the sell side at the indicative price, to help participants decide whether to submit offsetting orders before the uncross. NYSE publishes closing auction imbalances starting at 3:45pm, giving participants 15 minutes to respond before the 4:00pm uncross.

## The Closing Auction

The closing auction works identically but at the end of the day, establishing the official **closing price**. This is one of the most important prices in the market, it is used to benchmark fund performance, price derivatives, and compute official valuations of positions. The NYSE closing auction is one of the most liquidity-rich events in the US equity market: it regularly accounts for 10–15% of a stock's entire day's trading volume, compressed into a few seconds of uncrossing [NYSE Closing Auction Dynamics, 2023]. On some benchmark index rebalancing days the proportion is even higher, as index funds must trade at exactly the closing price to match their benchmarks.


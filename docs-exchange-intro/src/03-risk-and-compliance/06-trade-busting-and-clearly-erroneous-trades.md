# Trade Busting and Clearly Erroneous Trades

Every mechanism described so far in this Part, pre-trade risk controls, circuit breakers, price collars, SMP, kill switches, exists to stop a bad trade from happening in the first place. This section covers what happens when prevention fails and a bad trade has already executed. The matching engine has already produced a fill, both counterparties have a legally binding trade, and yet the exchange retains a narrow, rules-based power to undo it.

## Why This Power Has to Exist, and Why It Has to Be Narrow

The *Clearing and Settlement* section established that a matched trade is an obligation between two counterparties, not yet settled, but real and binding. Undoing a trade after the fact is therefore not a trivial administrative action, it reverses a legal commitment, and if exercised carelessly it would destroy the certainty that makes anyone willing to trade on an exchange in the first place. If trades could be unwound at either party's convenience whenever the price moved against them, the exchange's core promise of a fair, final, and trustworthy market would collapse.

At the same time, electronic markets can produce prices that are obviously not real prices, a market order sweeping an emptied book during a liquidity gap, a fat-finger error that slipped past pre-trade controls, or a software malfunction, and holding participants to those prices as if they reflected genuine supply and demand would be its own kind of unfairness. The resolution every major exchange has converged on is a **clearly erroneous execution (CEE)** rule: a narrowly defined, objectively measured, publicly documented threshold beyond which a trade can be reviewed and, if it qualifies, either adjusted to a different price or cancelled (**busted**) entirely.

## How a Clearly Erroneous Determination Works

The core test is **numerical, not subjective**: how far did the execution price move away from a reference price (typically the last consolidated print before the questionable trade, or the pre-halt reference price during a fast market), expressed as a percentage. US exchanges publish a table of thresholds that widen as the reference price falls and narrow as it rises, reflecting the same logic as tick-size price bands (see the *Tick Sizes and Fractional Ticks* section): a given percentage move is far more likely to be a genuine, if sharp, price movement on a low-priced or volatile stock than on a stable, high-priced one.

| Reference price band | Typical single-stock threshold (non-halt, normal conditions) |
|---|---|
| Above $50.00 | Roughly 5% away from reference |
| $10.01 – $50.00 | Roughly 10% away from reference |
| $5.01 – $10.00 | Roughly 15% away from reference |
| $5.00 or below | Roughly 25% (or more) away from reference |

(Exact thresholds vary by exchange, by whether the review follows a "multi-stock event," and are widened further during periods the exchange has designated as fast-moving. Consult the specific venue's rulebook for the governing numbers.)

**A worked example.** Reference price is $150.00. A market sell order sweeps a thin book and executes a slice at $128.00, a 14.7% move. Under the table above (10% threshold in the $10.01–$50.00 band does not directly apply here, but suppose this stock's applicable threshold is 10%), the trade exceeds the threshold and is a candidate for review. A second slice from the same sweep executes at $146.00, a 2.7% move, comfortably inside the threshold, and stands as a valid trade regardless of how the reviewer rules on the $128.00 print. Clearly erroneous review is applied **execution by execution**, not to an entire order or an entire event, which is why a single aggressive order that sweeps through many price levels can have some of its fills busted and others stand.

**The timing window matters as much as the threshold.** A participant (or the exchange itself) must typically file a clearly erroneous request within a short window after the execution, commonly 30 minutes under US rules, precisely because certainty needs to be restored quickly; clearing, margining, and downstream position management (see *Clearing and Settlement*) cannot proceed indefinitely on trades that might still be reversed.

**Multi-stock events require coordination.** Because modern equity markets are fragmented across a dozen or more venues (see the *Smart Order Routing* section of Part IV), a single erroneous-price event, a software bug, a bad data feed, a fast market during a broad decline, can generate questionable trades simultaneously across several exchanges in the same symbol. Exchanges coordinate through their self-regulatory functions to reach a single, consistent busting decision across all venues for the same event; it would undermine confidence in the entire market structure if the identical erroneous trade in the identical stock at the identical moment were busted on one exchange and left standing on another.

## Busting vs Adjusting

Two distinct remedies exist once a trade is found clearly erroneous:

**Cancellation (busting).** The trade is voided entirely, as if it never happened. Positions and cash movements are reversed. This is the standard remedy when no reasonable price can be assigned.

**Price adjustment.** Rather than cancelling, the exchange adjusts the trade to a different, non-erroneous price (typically the reference price used in the review, or a price at the edge of the applicable threshold). This preserves the fact that a trade occurred (useful when one party has already acted on the fill, for example, hedged it) while correcting the economically nonsensical part of the print.

## How This Connects to Events Already in This Book

**The 2010 Flash Crash** (see the *Market Orders* section of Part II) produced the canonical example of both remedies at scale: in the chaotic minutes when the E-mini sell algorithm swept a thinning book, some individual equities briefly traded at $0.01 or as high as $100,000. In the hours that followed, the SEC and the exchanges jointly reviewed the event and **busted trades that were more than 60% away from the pre-crash reference price**, a specific, published, retroactively-applied threshold designed for exactly this kind of extreme, multi-stock, multi-venue event. Positions built on those busted prints were unwound; trades within the 60% band, however uncomfortable, stood.

**Knight Capital** (see the dedicated cautionary tale in this Part) is the instructive negative case: despite the scale of the disaster, approximately $7 billion in unintended positions and $440 million in losses, essentially none of Knight's roughly four million erroneous *orders* produced clearly erroneous *trades* in the regulatory sense, because each individual execution occurred at or near the prevailing market price at the moment it happened. Power Peg was buying at the offer and selling at the bid, real, fair, non-erroneous prices, over and over again. This is precisely the distinction this section exists to draw: clearly erroneous review is about whether a *price* was divorced from the market at the moment of execution, not about whether a *participant's overall strategy* made any sense. Knight's trades were all individually "clean"; the catastrophe was in the aggregate, uncontrolled volume, which is exactly why the lesson of that chapter is pre-trade and firm-level risk controls, not post-trade busting. The two mechanisms protect against different failure modes and neither is a substitute for the other.

> **Historic Note: When the Exchange's Own Software Produces the Erroneous Price**
>
> The examples above involve a participant's order producing an erroneous price. Twice in 2012, it was the exchange's own matching software that was at fault, both times during an IPO, the single moment an exchange's opening-auction logic is under the most scrutiny and the least room for error.
>
> On **18 May 2012**, a matching-engine defect in NASDAQ's IPO cross process delayed the opening trade of **Facebook** by roughly 30 minutes and left many participants unable to confirm whether their orders had executed at all for hours afterward. NASDAQ ultimately paid a then-record $10 million SEC penalty for the design and systems-compliance failures and separately paid roughly $62 million to compensate market makers for losses caused by the malfunction [SEC Release No. 70694, 2013]. No individual trade was "clearly erroneous" in the price sense described above, the defect was in the auction mechanism itself, not in any single order, which is why NASDAQ's remedy took the form of a regulatory settlement and direct compensation rather than a batch of busted trades.
>
> Ten weeks earlier, on **23 March 2012**, **BATS Global Markets** attempted to list its own shares on its own exchange. A software defect in the BATS matching engine caused BATS stock to collapse from $15.25 to a fraction of a cent within roughly 900 milliseconds of the opening print, and the same underlying bug simultaneously disrupted trading in some unrelated symbols, including briefly affecting Apple shares on BATS. BATS withdrew its own IPO within minutes of discovering the fault, before the day's trading had even properly begun, cancelling the erroneous prints as part of unwinding the listing entirely. It remains one of the more pointed illustrations in exchange history that a venue's own listing event is not exempt from its own software defects, and that pre-deployment testing (a theme already covered in the Knight Capital section) applies to an exchange's matching engine every bit as much as to a participant's trading algorithm.

> **Key idea:** Pre-trade controls try to stop a bad trade before it happens; clearly erroneous execution rules are the narrow, threshold-based, time-boxed remedy for when one happens anyway. The test is objective (percentage deviation from a reference price, applied trade-by-trade), the window to act is short, and multi-venue events require coordinated, consistent rulings across exchanges. It is not a general-purpose undo button, and, as the Knight Capital case shows, a trade executed at a real market price is not clearly erroneous no matter how disastrous the accumulation of such trades turns out to be for the firm that sent them.

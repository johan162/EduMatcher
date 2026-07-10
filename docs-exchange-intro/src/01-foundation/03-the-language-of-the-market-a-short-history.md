# The Language of the Market: A Short History


Before you read about participants, orders, and matching engines, it is worth pausing on something that will serve you well throughout your career working on exchange systems: **much of the language you will encounter in this codebase has historical roots that no longer match the physical reality**. Terms that sound arbitrary or old-fashioned are fossil words, the language of a world of wooden desks, brass bells, and paper ledgers that gradually evolved into the nanosecond world of today. Understanding where the words came from will make them stick, and will save you from wondering why a system full of cutting-edge software keeps referring to things like "the book," "the tape," and "the floor."

## The Physical Book

Before electronic trading systems, every major exchange operated a physical trading floor, and on that floor, for every stock, there was a person responsible for maintaining order: in NYSE's terminology, this was called the **specialist**. The specialist's job was to act as a market maker for their assigned stocks, and to maintain, literally on paper, a record of every outstanding buy and sell order that had been submitted but not yet filled.

This record was kept in a physical **ledger book**. The book was divided into two columns: one for buy orders (bids) listing each buyer's offered price and quantity, and one for sell orders (asks) listing each seller's demanded price and quantity. The specialist would review the book, try to match buyers with sellers, and maintain an orderly market by quoting prices to floor brokers who came to trade.

When a broker wanted to buy shares and asked "what's the market in IBM?", the specialist would look at their book and say, for example, "fifty-five for five hundred, five hundred at fifty-five and a quarter", meaning the best available buyer was offering $55 for 500 shares, and the best available seller was asking $55.25 for 500 shares. The specialist was reading, live, from their paper book.

The physical book is gone. Every exchange in the world now maintains its order book in computer memory, with data structures designed for nanosecond access. But the **name** has survived completely intact. When developers and traders today say "the book," "working an order into the book," "resting in the book," or "taking from the book," they are using the exact same language that floor traders used when pointing at a physical ledger. The order book is one of the purest examples of terminology that crossed from physical to digital without losing a syllable.

## Open Outcry and the Pit

On exchange floors like CME Group's in Chicago, trading in futures contracts was conducted through **open outcry**, a method where traders stood in a sunken circular area called a **pit** and literally shouted their bids and asks at each other, using a combination of voice and hand signals to communicate price, quantity, and direction. The noise was enormous. The system worked because the pit was small enough that everyone could hear and see everyone else.

The CME Group operated open outcry pits for decades. Some products, particularly certain agricultural and options contracts, continued in open outcry long after equity markets went fully electronic, largely because the pit handled complex, illiquid products where human negotiation had genuine advantages. CME substantially wound down its open outcry operations in 2015 [9], though some niche trading still occurs. The physical pit is where terms like "floor broker" (a broker who executes trades on the physical floor), "floor trader" (a trader who trades for their own account from the floor), and "pit committee" originated.

The terms survive in documentation, regulations, and informal industry speech even though the pits themselves are mostly silent now.

## The Ticker Tape

Before electronic screens, prices of completed trades were published via the **stock ticker**, a telegraph-based machine, invented by Edward Calahan in 1867 [15] and later improved by Thomas Edison, that printed a continuous stream of abbreviated stock symbols and trade prices on a narrow paper tape. The tape moved fast (hence "ticker", the machine made a ticking sound) and the strip of paper would pile up on the floor of brokerages around the country as trades printed in real time.

Reading the tape was a skill. A **tape reader** was someone who could watch the continuous stream of prices and volumes and infer what institutional buyers and sellers were doing, one of the earliest forms of technical analysis. An even earlier form of market observation appears in Joseph de la Vega's *Confusión de Confusiones* (1688) [4], the oldest known book about stock trading, written in Amsterdam about the VOC share market, which describes participants reading order flow and inferring intent from patterns of buying and selling.

In 1878, the phone was invented. In 1929, the first electronic ticker was installed. By the 1960s, electronic displays began replacing paper. Today, the "ticker" refers to the digital price feeds streaming across screens in every trading firm, brokerage, and financial news channel, and the **ticker symbol** (AAPL, MSFT, GOOG) is the abbreviated code printed on the old paper tape.

When you see terms like "tick" (the minimum price movement), "tick data" (a record of every trade), or "ticker plant" (the server infrastructure that publishes market data), you are using the language of a machine that ran on telegraph cables and printed on paper strips.

!!! note "The Kennedy Slide, the Lagging Tape, and the Study That Created NASDAQ (1962–71)"

    On 28 May 1962 the Dow fell 5.7% in a single session — the sharpest one-day drop since 1929 — in what became known as the "Kennedy Slide." Operationally, the day's defining failure was informational: trading volume so overwhelmed the ticker that the tape ran more than an hour behind actual trading, meaning investors nationwide were making decisions on prices that no longer existed. The SEC's *Special Study of Securities Markets* (1963), a multi-volume examination already underway when the break occurred, documented the episode and, more consequentially, dissected the over-the-counter market's opaque, telephone-based quotation system, recommending that OTC quotations be automated. The NASD's answer to that recommendation went live on 8 February 1971 as NASDAQ — initially not a matching engine at all, but an automated *quotation display* system, exactly what the Special Study had prescribed. The lineage is worth stating plainly: the world's first electronic stock market exists because a regulator's post-crash study concluded that stale, inaccessible price information was itself a market-structure defect. Every market-data latency requirement in Part IV is a descendant of that conclusion.

    **References:** Kennedy Slide of 1962, Wikipedia, https://en.wikipedia.org/wiki/Kennedy_Slide_of_1962 



## The Language Lives in the Code

These historical terms are not just in trading rooms and textbooks. They are in the source code. A developer reading an exchange codebase for the first time will find:

- `bid_price`, `ask_price`, `spread` , the physical ledger's two columns, reduced to struct fields
- `lot_size`, `tick_size` , the standardisation introduced by the early commodity pits
- `aggressor_side` , which party crossed the spread; matters for fee calculation and regulatory reporting
- `book.add_order()`, `book.cancel_order()`, `book.sweep()` , the specialist's actions, now function calls
- `GTC`, `DAY`, `IOC` , time-in-force codes whose full names (Good-Till-Cancelled, Day, Immediate-or-Cancel) are rarely spoken, used daily in hundreds of millions of orders
- `tape_price`, `last_trade_price` , what the ticker printed, now a field in a trade record
- `long_position`, `short_position` , the Amsterdam merchant's grain warehouse, abstracted to a signed integer

Every time you read a function name or a variable name in exchange software that sounds like it belongs in a different century, it does. The codebase is the physical exchange, translated.

## Black Monday and the Origin of Circuit Breakers

On 19 October 1987, US stock markets fell **22.6%** in a single day, the largest single-day percentage drop in the history of the Dow Jones Industrial Average. This event, known as **Black Monday**, remains the most severe one-day market crash on record. A more detailed account of this is given in the *Risk Controls, Protecting the Market* section of Part III.

The crash was not driven by a single piece of bad news. It was amplified by automated **portfolio insurance** programmes, algorithmic selling strategies designed to protect institutional portfolios by automatically selling futures contracts as prices fell. As these programmes sold, prices fell further, triggering more programme selling, which pushed prices further down , a feedback loop that human traders could not interrupt. The lack of any coordinated mechanism to pause trading made the spiral self-reinforcing.

The Presidential Task Force on Market Mechanisms (the "Brady Commission"), reporting to President Reagan in January 1988, concluded that the absence of circuit breakers and coordinated pause mechanisms across markets had allowed the panic to become catastrophic. Its central recommendation was explicit: create automatic trading halts that could interrupt the feedback loop and give participants time to assess [Brady Commission Report, January 1988].

NYSE introduced the first market-wide circuit breakers in 1988 directly in response. The specific thresholds have been adjusted several times since (most recently after March 2020, when Level 1 was triggered four times in two weeks during the COVID-19 crash), but the mechanism traces directly to that January 1988 report.

This history matters for exchange system developers because circuit breakers are not bureaucratic decorations. They are the engineering response to a proven systemic failure mode: automated systems amplifying each other into a catastrophic spiral. Every halt threshold, every resumption auction, every "do not accept orders during HALTED state" condition in a matching engine exists because of what happened on 19 October 1987.

## Settling Up: Settlement Periods and Why They Exist

The historical reason settlement took multiple days has nothing to do with technology and everything to do with physical logistics. In the era of paper stock certificates, when you sold your shares, you had to physically deliver a paper certificate to the buyer, and they had to physically deliver cash or a cheque to you. Messengers on bicycles carried these documents between brokerage firms on Wall Street. Giving everyone five business days (the original settlement period was T+5) provided time for paperwork to move across Manhattan, be checked, and be processed.

As the industry moved to dematerialisation (electronic records replacing paper certificates) and electronic funds transfer, settlement windows shrank: T+5 became T+3 in the 1990s, T+2 in 2017, and T+1 in 2024 in the US [8]. The "T+N" notation remains standard even as the N shrinks. Some markets are exploring same-day (T+0) settlement, though this requires that cash and securities be available at the exact moment of trading, a more demanding operational requirement.

## The Bid, the Ask, and the Spread

The two most fundamental prices in any market are the **bid** and the **ask** (also called the **offer** in some contexts). These are ancient words in the context of markets.

**Bid** comes from Old English *beodan*, meaning to announce, command, or offer. To bid for something is to announce the price you are willing to pay. A bidder at an auction makes a bid; a trader in a market makes a bid. The word has been used in commercial contexts for over a thousand years.

**Ask** (or offer) is the counterpart: the price at which someone is willing to sell. Asking a price for goods is as old as commerce.

The **spread** is the difference between the best bid and the best ask at any moment: if the best bid is $150.30 and the best ask is $150.35, the spread is $0.05. The spread is both a measure of market quality (tight spreads mean the market is liquid and efficient; wide spreads mean it is illiquid or uncertain) and the primary source of income for market makers, who earn the spread by continuously standing ready to buy at the bid and sell at the ask.

The phrase **"crossing the spread"** means submitting an order aggressive enough to immediately match against a resting order. An investor who submits a buy order at $150.35 (the ask) rather than waiting at $150.30 (the bid) is crossing the spread and paying for the privilege of immediate execution. This small payment , a few cents, or a fraction of a cent in liquid markets , is the cost of immediacy, and it is the foundation of the market maker's business model.

## Blue Chips, Bulls, and Bears

Not all inherited terminology has to do with physical infrastructure. Some comes from adjacent worlds:

**Blue chip** stocks are large, well-established, financially sound companies, the most prestigious tier of the equity market. The term comes from poker: in casino chips, blue has traditionally been the highest denomination. The first recorded use in finance was by Oliver Gingold at Dow Jones in 1923, who described stocks trading at $200 or more per share as "blue chip stocks." [14]

**Bull market** (rising prices) and **bear market** (falling prices) have disputed origins, but the most widely cited explanation refers to how each animal attacks: a bull thrusts its horns upward, a bear swipes its paws downward. The terms appear in financial writing as early as the 18th century. Today, a market that has fallen 20% or more from a recent peak is formally defined as a bear market; a sustained rise of 20% or more from a trough is a bull market.

**Going long** and **going short** have roots far older than stock markets. Their origin lies in the physical trade of commodities, grain, spices, metals, cloth, timber, and other durable goods, that dominated commerce for centuries before financial securities existed.

A merchant in a 17th-century Amsterdam or London trading house who had purchased a large stock of grain and was storing it in a warehouse was described as being **long** in grain [4]. The word captured two ideas simultaneously: first, that they *possessed* the goods, they owned something tangible, in their hands, in their warehouse; and second, that durable goods could be held *over time*. Grain kept through winter. Spices kept for years. Metal did not spoil. A merchant who was "long" in such goods had an inventory that would *last a long time*, goods with longevity. The root connection is direct: long as in duration, as in possession extended through time.

This is still exactly what "going long" means in modern finance: you own the asset and you are exposed to its price over time. If you buy shares of a company and hold them, you are long those shares. If the price rises, your long position profits; if it falls, it loses. Nothing about the meaning has changed, only the asset has shifted from sacks of grain in a warehouse to electronic records in a clearing house.

**Going short** comes from the opposite situation: a merchant who had promised to deliver goods they did not yet possess. In forward contracts, common in the grain and commodity markets of the 17th and 18th centuries, a seller would commit to deliver a quantity of goods at a future date and price. If they had sold more than their warehouse contained, they were "short" of the goods, deficient, lacking, falling short of their obligations. The same word family as "we are short of supplies," "he fell short of expectations," or "shortage." Being short meant your inventory was insufficient to cover what you had committed to deliver. You would need to go into the market and buy before the delivery date, hoping prices had fallen so you could profit on the difference.

The Dutch East India Company (VOC), founded in 1602 and traded on the Amsterdam Exchange from that same year, pioneered many instruments still in use today, transferable shares, dividend payments, and the secondary market in those shares [5] [11], and became the arena for what is likely the first recorded large-scale short selling operation in financial history: in 1609, a merchant named Isaac Le Maire organised a group of traders to sell VOC shares they did not own, betting the price would fall so they could buy them back cheaply before delivery [5]. The scheme was disruptive enough that the Amsterdam city council attempted to ban short selling the following year, the earliest known attempt to regulate the practice [5]. It did not stick; short selling has been controversial, periodically banned, and always present in markets ever since.

"Long" and "short" thus carry the physical memory of a world where trading meant moving real goods between warehouses and ships. A developer reading `last_sell_price` or `position += signed_qty` in the matching engine's clearing code is working with concepts that a 17th-century spice merchant would have recognised immediately, even if the technology would be unrecognisable to them.


!!! note "Historic Notes"

    No episode in financial history is retold more often, or more loosely, than the Dutch tulip mania of 1636–37. The legend: a whole nation ruined, fortunes traded for single bulbs, the economy wrecked, and so on largely dissolves under archival scrutiny. Contract prices for rare bulbs did rise spectacularly through late 1636 and collapse in February 1637, but the trade was concentrated among a modest circle of merchants and craftsmen dealing in *forward contracts* on bulbs still in the ground, an early lesson that a derivative on an unharvestable underlying is a bet on a price, not a purchase of a thing. Archival work has found no wave of bankruptcies and no measurable damage to the Dutch economy; the most extreme prices in the popular telling trace to moralising pamphlets written *after* the crash, not to transaction records. The episode earns its place in this book twice over: as a genuinely early forward market discovering the hard way that contract enforceability matters (many February 1637 contracts were simply never honoured, and courts largely declined to enforce them), and as a standing reminder to check the primary record before repeating a market legend. <br>&nbsp;<br>

    **References:** 
    Peter M. Garber, *Famous First Bubbles: The Fundamentals of Early Manias* (MIT Press, 2000), <br>&nbsp;<br>
    *Tulipmania: Money, Honor, and Knowledge in the Dutch Golden Age* (University of Chicago Press, 2007).




## The Operational Mechanics of Short Selling, Borrow and Locate

The historical explanation above describes the *economics* of short selling. The modern operational reality involves several additional steps that are invisible in the exchange's order book but fundamental to how clearing and settlement actually work.

**You must borrow before you short.** Before a participant can sell shares they do not own, they must first arrange to borrow those shares from someone who does own them. This is called the **locate** process, finding and reserving a source of borrowable shares. In the US, Regulation SHO (adopted by the SEC in 2005) mandates that broker-dealers must have a reasonable grounds to believe shares can be borrowed before accepting a short sale order. Selling short without a locate is called **naked short selling** and is generally illegal.

**Where the borrow comes from.** Shares available to borrow come primarily from long investors who hold shares in custody through a broker or prime broker. These holders consent (usually automatically through their account agreements) to their shares being lent out in exchange for a **lending fee**. The custodian or prime broker intermediates: they find willing lenders and lend the shares to the short seller. The short seller pays a daily lending fee (the **borrow rate**) while the position is open.

**Borrow rates and hard-to-borrow stocks.** Most large-cap, liquid stocks are "easy to borrow", borrow rates are near zero because many shares are available. Smaller, heavily-shorted, or thinly-traded stocks can be "hard to borrow", rates of 5%, 20%, or even higher per annum, applied daily. For a stock with a 50% annualised borrow rate, a short position held for one week costs roughly 1% just in borrowing costs, before considering any price movement. The difficulty of finding borrows can itself become a market signal: rising borrow rates indicate increasing short interest and limited available supply.

**Short recall risk.** The lender can recall their shares at any time (with short notice). If the lender sells their shares or instructs their custodian to recall the loan, the short seller must return the shares immediately, either by buying in the open market (a **buy-in**) or finding a new lender. In volatile markets, recalls at inopportune moments can force short sellers to cover at bad prices.

**Settlement obligation.** At settlement (T+1 in the US), the short seller must deliver the shares. They do not own them, they borrowed them. Their clearing position shows a negative (short) holding. The CCP ensures delivery; if the short seller fails to deliver, the failed settlement process applies.

**Why this matters for exchange developers.** The exchange's matching engine processes short sales exactly like any other sell order, the distinction between a short sale and a long sale is invisible at the order book level. The matching engine does not know or care whether the seller owns the shares. The borrow and locate process happens entirely outside the exchange, in the prime brokerage and custody infrastructure. However, exchange reporting systems are required to flag short sales (in the US, short sale orders must be marked "short" in the FIX message and this appears in the audit trail), and some regulatory checks at the gateway level confirm the short sale flag is present.


## Wall Street

**Wall Street** is named after an actual wall, a wooden palisade built in 1653 by Dutch colonists along the northern edge of their settlement (then called New Amsterdam, now Lower Manhattan) to protect against British and Native American incursions. The wall is long gone; the street that replaced it became the financial centre of America, and now "Wall Street" is a metonym for the entire US financial industry, regardless of where the actual firms are physically located.

## Why This Matters for You

When you encounter a term in the codebase that seems oddly concrete for a piece of software, "the book," "the tape," "the spread," "the floor price," "tick by tick", the reason it sounds physical is that it *was* physical. These words have been used continuously, with the same meanings, through every technological revolution the industry has undergone, because the underlying concepts remained constant even as the implementation changed completely.

This is also why you will find financial terminology resistant to renaming even when better alternatives exist. Saying "priority queue" instead of "the book" would be technically precise but professionally unintelligible. Finance is a conservative industry with deep institutional memory, and the vocabulary is part of that memory. Learning the words, and where they came from, is learning the culture.


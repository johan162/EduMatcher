# What Is a Financial Exchange, and Why Does It Exist?


## The Core Problem

Imagine you own 1,000 shares of a technology company (you understand now what that means: you own a tiny fraction of that company, acquired when you bought the shares from a previous owner on the secondary market) and you want to sell them. Somewhere out there, someone wants to buy exactly 1,000 shares of that same company at roughly the price you have in mind. The problem is finding each other.

Before modern exchanges existed, this "finding" problem was enormous. Stock trading happened in coffee houses, in the street ("Exchange Alley Coffeehouses"), or through networks of personal contacts. One of the first places on record was "Jonathan's Coffee House" (The Forerunner to the London Stock Exchange) founded around 1680 by Jonathan Miles, Jonathan's became the primary gathering place for stock brokers, [Jonathan's Coffee-House](https://grokipedia.com/page/Jonathan's_Coffee-House).  Prices were inconsistent, you might sell at one price while, moments later, someone else sold the same shares at a very different price. There was no guarantee you were getting a fair deal, and there was no way to know what "fair" even meant.

> **Auctions by the Candle**
>
> Garraway's Coffee House was opened by Thomas Garway and famed for being the first place in England to retail tea (in 1657). It was quickly rebuilt on a grand scale after the 1666 Great Fire. While Jonathan's focused heavily on shares, Garraway's specialised in commodities, hosting the Hudson's Bay Company's first fur auction in 1671 and later auctioning Australian wool.
>
> Garraway's was legendary for its unique bidding system: an auctioneer would light an inch of tallow candle, and the last bid placed before the flame flickered out won the goods. [Candle Auction](https://en.wikipedia.org/wiki/Candle_auction)

The golden era of the informal Exchange Alley coffeehouses came to a catastrophic halt on March 25, 1748, when a massive fire broke out in Cornhill, destroying Jonathan's, Garraway's, and nearly 100 surrounding buildings. Though both shops were eventually rebuilt, the financial markets were rapidly moving toward formal, dedicated corporate buildings, leaving the casual coffeehouse model behind. 

A financial exchange solves this problem by acting as a **centralised marketplace**, a single place where all buyers and sellers come together, where prices are visible to everyone, and where agreed rules govern who trades with whom at what price. The NYSE was founded in 1792 under a buttonwood tree on Wall Street [10]; NASDAQ launched in 1971 as the world's first electronic stock market [10]. Both exist to solve the same fundamental problem: matching buyers with sellers fairly and efficiently.

It is worth noting that exchanges are among the most visible matching venues, but not the only ones. **Over-the-counter (OTC) markets** (where participants negotiate directly), **Alternative Trading Systems (ATSs)**, **Electronic Communication Networks (ECNs)**, and **internalisers** (brokers who match client orders internally against their own inventory) all also match trades. The concepts in this document apply most directly to regulated exchanges, but the same vocabulary, order book, spread, price-time priority, is used across all these venues.

## The Three Promises of an Exchange

Every exchange makes three implicit promises to its participants:

**1. Price discovery.** At any moment, the current price of an asset reflects the aggregate opinion of all participants currently willing to trade it. You can look at the market and see what "fair value" is right now.

**2. Liquidity.** You can convert your asset into cash (or vice versa) quickly, without having to wait indefinitely for a counterparty to appear. The exchange provides the infrastructure that makes counterparties findable.

**3. Fairness and transparency.** The rules for who trades first and at what price are known in advance, applied consistently, and visible to all participants equally. There is no backroom dealing.

## How Exchanges Are Regulated

Exchanges do not operate by custom alone. They are licensed and supervised by government regulators whose rules directly shape how exchange systems are designed and built.

In the United States, equity exchanges are overseen by the **Securities and Exchange Commission (SEC)**, established by the Securities Exchange Act of 1934 in the aftermath of the 1929 crash and subsequent Great Depression. The crash and its causes deserve a sentence of context here, because they explain why the SEC's mandate is what it is.

Between 1928 and September 1929, the US stock market had doubled. Investors were buying heavily on **margin**, borrowing money to buy more stock than they could afford outright. When prices began to fall in October 1929, margin calls forced widespread selling. Selling drove prices lower, which triggered more margin calls, which drove more selling , the same feedback loop that automated portfolio insurance would recreate in 1987. The Dow Jones Industrial Average fell 89% from its 1929 peak to its 1932 trough. Thousands of banks failed. Millions lost their savings. The subsequent investigation found rampant stock manipulation, insider trading, misleading corporate disclosures, and conflicts of interest at every level of the market. The Securities Act of 1933 and the Securities Exchange Act of 1934 were Congress's direct response: transparency requirements, registration of securities, prohibition of fraud, and the creation of the SEC to enforce the rules. The exchange system you are building operates under the regulatory framework those 1930s laws set in motion.

Several regulations appear throughout this document and in most exchange codebases. It is worth naming them here:

- **Regulation NMS (National Market System, 2005):** Requires that equity orders receive the nationally best available price across all registered trading venues. This single rule is the reason the US has 16+ registered equity exchanges competing for order flow, and the reason **smart order routing** exists , brokers must route to wherever the best price is, not just the closest or the cheapest.

- **Regulation SHO (2005):** Governs short sales, including the **locate** requirement (broker-dealers must verify shares can be borrowed before accepting a short sale order) and delivery obligations.

- **Market Access Rule (Rule 15c3-5, 2010):** Requires broker-dealers providing market access to have pre-trade risk controls: maximum order sizes, credit limits, and kill switches. Enacted directly in response to the 2010 Flash Crash.

In Europe, the equivalent framework is **MiFID II (Markets in Financial Instruments Directive II, 2018)**, which mandates best execution, algorithmic trading controls (including mandatory kill switch testing), trade reporting, and systematic internaliser reporting. Any exchange system intended to operate in EU markets must comply.

Understanding which regulator and which rules apply is not just a legal matter. It is an engineering specification: audit trail formats, kill switch accessibility, pre-trade check requirements, and market data publication rules are all regulatory mandates, not optional features.

## Instruments: What Is Being Traded?

An exchange does not trade "things" in a physical sense. It trades **instruments**, standardised financial contracts representing ownership or obligation. The most common are:

- **Equities (stocks):** A share represents a small piece of ownership in a company. When you buy one share of Apple (ticker symbol: AAPL), you own a tiny fraction of Apple Inc. NYSE and NASDAQ are primarily equity exchanges.

- **Futures contracts:** An agreement to buy or sell something (oil, gold, a stock index) at a specified price on a specified future date. CME Group is one of the world's largest futures exchanges.

- **Options:** The right (but not the obligation) to buy or sell an instrument at a specific price before a specific date. Cboe is a major options exchange.

- **Foreign exchange (FX) pairs:** The price of one currency expressed in another, such as EUR/USD (how many US dollars one Euro buys). FX trades largely on electronic networks rather than centralised exchanges, though the principles are similar.

An equity exchange handles each **symbol** (like AAPL, MSFT, or TSLA) as a separate tradeable instrument, each with its own independent order book.


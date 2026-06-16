# A Brief Tour of Real-World Exchanges


To ground these concepts in reality, here is a brief overview of the exchanges most relevant to exchange system developers.

## NYSE (New York Stock Exchange)

Founded in 1792, NYSE is the world's largest equity exchange by market capitalisation of listed companies. Its founding is traced to the **Buttonwood Agreement** of 17 May 1792, when 24 stockbrokers signed a document under a buttonwood tree on Wall Street agreeing to trade securities only among themselves and at fixed commission rates [10]. This agreement established the principle of a closed, rule-governed professional market — the model that all regulated exchanges follow today.

NYSE is a **hybrid market**: it combines electronic order matching with **Designated Market Makers (DMMs)** who have responsibilities to maintain fair and orderly markets and can intervene manually in certain situations. NYSE uses price-time priority and runs opening and closing auctions. Its closing auction is among the most important pricing events in global finance, determining the official closing prices that benchmark trillions of dollars of fund performance.

Despite being the iconic "stock exchange," NYSE handles only a fraction of total US equity volume. Due to fragmentation under Reg NMS, NYSE typically accounts for roughly 20–25% of US equity volume [1]; the rest routes to NASDAQ, Cboe, and dozens of other venues. This is not a sign of weakness — it reflects the fragmented, competitive nature of modern US equity markets.

## NASDAQ
NASDAQ launched in 1971 as the world's first fully electronic stock exchange. It is home to many of the world's largest technology companies (Apple, Microsoft, Amazon, Google). NASDAQ is a pure electronic market, no floor traders, no DMMs in the traditional sense. It pioneered the technology approach to exchange operation and drove down transaction costs dramatically.

## CME Group (Chicago Mercantile Exchange)
CME Group is the world's largest futures exchange, operating CME, CBOT (Chicago Board of Trade), NYMEX, and COMEX. Futures contracts on everything from interest rates to agricultural commodities to weather indices trade here. CME uses the Globex electronic trading platform, which processes millions of orders per day. CME uses both price-time priority and pro-rata allocation depending on the product.

## Eurex
Part of Deutsche Börse Group, Eurex is Europe's largest derivatives exchange, headquartered in Frankfurt. Eurex is known for its sophisticated market making programmes and its strict but fair treatment of high-frequency trading. The Eurex T7 trading system is used by multiple exchanges globally. Eurex introduced the concept of formally structured market maker obligations with MMP protection.

## LSE (London Stock Exchange)
The LSE is one of Europe's oldest exchanges, dating to the 17th century coffee houses. It trades equities, bonds, and ETFs. The LSE uses the SETS (Stock Exchange Electronic Trading System) for liquid equities and runs opening and closing auctions. The LSE's Millennium Exchange technology platform is used by dozens of exchanges globally.

## Euronext

Euronext is Europe's largest exchange group by number of listed companies, operating markets in Amsterdam, Brussels, Paris, Lisbon, Dublin, Oslo, and Milan. Originally formed in 2000 by the merger of the Paris, Amsterdam, and Brussels exchanges, it expanded significantly through subsequent acquisitions including the Milan Stock Exchange (Borsa Italiana) in 2021. Euronext uses the **Optiq** trading platform and operates under MiFID II. Its Amsterdam exchange is historically notable as the successor to the world's first stock exchange (the Amsterdam Exchange, 1602).

## Nasdaq Stockholm (Stockholmsbörsen, STO)

Nasdaq Stockholm is Sweden's primary regulated securities exchange and one of the core venues in the Nordic region. The original Stockholm Stock Exchange dates to 1863, and the modern market became part of the Nasdaq group through Nasdaq's acquisition of OMX in 2008. Today, Nasdaq Stockholm operates as part of the wider Nasdaq Nordic market structure alongside Copenhagen, Helsinki, and Icelandic venues.

For exchange developers, Nasdaq Stockholm is a useful real-world reference because it combines deep local equity liquidity with a highly standardised pan-Nordic technology model. The market is fully electronic, supports auction phases (including opening and closing auctions), and runs under the same MiFID II transparency and best-execution regime as other EU venues.

The venue's best-known benchmark is the **OMXS30** index, which tracks the 30 most traded shares on Nasdaq Stockholm. The exchange is the home listing venue for many major Swedish and Nordic companies, including names such as Ericsson, Volvo, Atlas Copco, and Investor AB, making it central to Nordic equity price discovery.

From an infrastructure perspective, Nasdaq Stockholm aligns with broader Nasdaq market technology standards (including INET-based matching architecture for cash equities) and interoperates with regional post-trade infrastructure such as Euroclear Sweden for securities settlement. In practical terms, this makes it a strong example of how a national exchange can preserve local market identity while operating inside a larger cross-border technology and regulatory framework.Nasdaq Stockholm is Sweden's primary regulated securities exchange and one of the core venues in the Nordic region. The original Stockholm Stock Exchange dates to 1863, and the modern market became part of the Nasdaq group through Nasdaq's acquisition of OMX in 2008. Today, Nasdaq Stockholm operates as part of the wider Nasdaq Nordic market structure alongside Copenhagen, Helsinki, and Icelandic venues.

For exchange developers, Nasdaq Stockholm is a useful real-world reference because it combines deep local equity liquidity with a highly standardised pan-Nordic technology model. The market is fully electronic, supports auction phases (including opening and closing auctions), and runs under the same MiFID II transparency and best-execution regime as other EU venues.

The venue's best-known benchmark is the **OMXS30** index, which tracks the 30 most traded shares on Nasdaq Stockholm. The exchange is the home listing venue for many major Swedish and Nordic companies, including names such as Ericsson, Volvo, Atlas Copco, and Investor AB, making it central to Nordic equity price discovery.

From an infrastructure perspective, Nasdaq Stockholm aligns with broader Nasdaq market technology standards (including INET-based matching architecture for cash equities) and interoperates with regional post-trade infrastructure such as Euroclear Sweden for securities settlement. In practical terms, this makes it a strong example of how a national exchange can preserve local market identity while operating inside a larger cross-border technology and regulatory framework.

## IEX (Investors Exchange)

IEX launched as a dark pool in 2013 and became a registered national securities exchange in 2016. It is the exchange that popularised the **speed bump**: a deliberate 350-microsecond delay applied to incoming orders, designed to level the playing field between HFT latency arbitrage strategies and slower institutional investors. IEX was the subject of Michael Lewis's 2014 book *Flash Boys*, which brought widespread public attention to HFT and exchange structure debates.

The speed bump attracted significant institutional support from large asset managers who believed it reduced predatory latency arbitrage. However, IEX has consistently captured a relatively small share of US equity volume (typically 2–3%) [1], suggesting that the speed bump's appeal did not translate into dominant market share. Whether this reflects genuine limitations of the model or simply the difficulty of displacing entrenched incumbent exchanges remains debated in market structure circles. IEX remains disproportionately influential in regulatory discussions given its size, having prompted rule-making discussions at the SEC around speed bumps and exchange access fees.

## Cboe (Chicago Board Options Exchange)
Cboe is the world's largest options exchange, operating Cboe, C2, BZX, BYX, EDGX, and EDGA exchanges. Cboe invented the listed options market in 1973. It calculates the VIX (Volatility Index, the "fear gauge" of the market) from options prices.

## JPX (Japan Exchange Group)
JPX was formed in 2013 by merging the Tokyo Stock Exchange (TSE) and Osaka Securities Exchange. It is the world's third-largest exchange by market capitalisation of listed companies, behind NYSE and NASDAQ. JPX operates on an all-electronic platform called arrowhead. Japanese markets have their own session structure, tick size rules, and circuit breaker conventions; the daily price limit system (where trading in a stock is suspended if it moves more than a set amount from the previous close) differs from the US LULD approach.

## HKEX (Hong Kong Exchanges and Clearing)
HKEX is the primary exchange for Hong Kong-listed equities and also provides the main electronic gateway for mainland China stocks through the Shanghai-Hong Kong Stock Connect and Shenzhen-Hong Kong Stock Connect programmes. Stock Connect allows international investors to trade China A-shares (mainland China stocks) and allows mainland investors to trade Hong Kong-listed stocks through a northbound/southbound quota system, a unique regulatory and technical arrangement that requires matching engines on both sides to coordinate.

## SGX (Singapore Exchange)

SGX is Southeast Asia's largest exchange, trading equities, derivatives, and fixed income. It is notable as a hub for Asian futures contracts, Nikkei 225 futures, MSCI Asia index futures, and iron ore contracts all trade on SGX. SGX acquired Scientific Beta (factor indices) and has invested heavily in data analytics services alongside its exchange operations.

## ASX (Australian Securities Exchange)

ASX serves the Australian equity and derivatives markets. It became notable in the technology community for its attempt to replace its CHESS (Clearing House Electronic Subregister System) settlement platform with a blockchain-based system, a project that was eventually cancelled in 2022 after years of development, at significant cost. The cancellation is a cautionary tale for exchange technologists about the risks of replacing proven settlement infrastructure with unproven technology.




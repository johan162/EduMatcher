# A Brief Tour of Real-World Exchanges


To ground these concepts in reality, here is a brief overview of the exchanges most relevant to exchange system developers.

## NYSE (New York Stock Exchange)

Founded in 1792, NYSE is the world's largest equity exchange by market capitalisation of listed companies. Its founding is traced to the **Buttonwood Agreement** of 17 May 1792, when 24 stockbrokers signed a document, traditionally said to have been under a buttonwood (sycamore) tree on Wall Street, agreeing to give each other preference in their dealings and never to charge less than a fixed minimum commission [10]. This agreement established the principle of a closed, rule-governed professional market, the model that all regulated exchanges follow today.

NYSE is a **hybrid market**: it combines electronic order matching with **Designated Market Makers (DMMs)** who have responsibilities to maintain fair and orderly markets and can intervene manually in certain situations. NYSE uses price-time priority and runs opening and closing auctions. Its closing auction is among the most important pricing events in global finance, determining the official closing prices that benchmark trillions of dollars of fund performance.

Despite being the iconic "stock exchange," NYSE handles only a fraction of total US equity volume. Due to fragmentation under Reg NMS, all of the NYSE group's exchanges together typically account for only around a fifth of US equity volume, and the flagship NYSE market alone for considerably less [1]; the rest goes to Nasdaq, Cboe, other exchanges, and the dozens of off-exchange venues (dark pools and broker internalisers) that in recent years have executed close to half of all US equity volume. This is not a sign of weakness, it reflects the fragmented, competitive nature of modern US equity markets.

!!! note "The Panic of 1792 and the Buttonwood Agreement"

    The Buttonwood Agreement of 17 May 1792 did not appear out of calm deliberation. Weeks earlier, New York had suffered the young republic's first financial panic: William Duer, a former Treasury official, had borrowed heavily to corner Bank of New York shares and government debt, and his failure in March 1792 set off a cascade of defaults. Alexander Hamilton's Treasury responded with open-market purchases of government securities and by encouraging banks to keep lending against good collateral, actions economic historians have described as a remarkably modern lender-of-last-resort operation, some eight decades before Walter Bagehot set out the doctrine in *Lombard Street* (1873). The 24 brokers who signed the Buttonwood Agreement that May were, in part, organising to restore confidence after the chaos: giving each other preference, at a fixed minimum commission of one-quarter percent, under known rules. The agreement is a single sentence long, and it is the founding text of American self-regulated exchange trading, written as a direct response to the market's first blow-up.

    **References:** The Buttonwood Agreement, https://en.wikipedia.org/wiki/Buttonwood_Agreement 


## NASDAQ
NASDAQ launched in 1971 as the world's first electronic stock market, initially an automated quotation system for over-the-counter stocks rather than an exchange; it became a registered national securities exchange in 2006. It is home to many of the world's largest technology companies (Apple, Microsoft, Amazon, Alphabet). NASDAQ is a pure electronic market: no trading floor and no DMMs in the NYSE sense. It pioneered the technology approach to exchange operation and drove down transaction costs dramatically.

## CME Group (Chicago Mercantile Exchange)
CME Group is the world's largest futures exchange group by most measures, operating CME, CBOT (Chicago Board of Trade), NYMEX, and COMEX. (By total number of derivatives contracts traded, India's National Stock Exchange has ranked first in recent years, driven by enormous volumes of very small index options.) Futures contracts on everything from interest rates to agricultural commodities to weather indices trade here. CME uses the Globex electronic trading platform, which processes millions of orders per day. CME uses both price-time priority and pro-rata allocation depending on the product.

## Eurex
Part of Deutsche Börse Group, Eurex is Europe's largest derivatives exchange, headquartered in Frankfurt. Eurex is known for its sophisticated market making programmes, and its Market Maker Protection (MMP) functionality is a widely studied example of the protection mechanisms described in Part II. Deutsche Börse's T7 trading system is also used by several other exchanges.

## LSE (London Stock Exchange)
The LSE is one of Europe's oldest exchanges, dating to the 17th century coffee houses. It trades equities, bonds, and ETFs. The LSE uses the SETS (Stock Exchange Electronic Trading System) for liquid equities and runs opening and closing auctions. The LSE's Millennium Exchange technology platform has also been licensed to a number of other exchanges.

!!! note "Historic Note: The Big Bang, 27 October 1986"

    The modern LSE is largely the product of a single day of deregulation known as the **Big Bang**. Until 1986, the LSE operated under a cartel-like structure inherited almost unchanged from its coffee-house origins: brokerage commissions were fixed by rule rather than set by competition, and firms were legally separated into **brokers** (who dealt with clients) and **jobbers** (who traded as principals on the floor), with outside and foreign ownership of member firms tightly restricted. On 27 October 1986, all of this changed at once: fixed commissions were abolished, the broker/jobber distinction was scrapped, non-member and foreign ownership was permitted, and open-outcry floor trading was replaced almost overnight by the screen-based **SEAQ** electronic quotation system. The changes were bundled together deliberately, as a negotiated settlement of a long-running restrictive-practices case brought by the UK government against the exchange, and the government wanted them delivered as a single event rather than a gradual transition. The effect was to compress a decade of gradual American-style deregulation into one day, and it is the direct reason the LSE moved from a floor-based, fixed-commission market to the electronic, competitive one described in this document. <br> &nbsp; <br>

    Big Bang has an almost exact American predecessor: on **1 May 1975** ("**May Day**"), the SEC abolished fixed brokerage commissions on the NYSE, ending nearly two centuries of fixed-rate trading that dated back to the original 1792 Buttonwood Agreement described earlier in this chapter. Commission rates had been fixed by NYSE rule for so long that the change was existential for many old-line brokerages; it also created the discount-brokerage industry (Charles Schwab's firm began offering discounted commissions that same year) and set in motion the competitive, cost-conscious order-routing dynamics, including, decades later, payment for order flow, that the *Smart Order Routing* section of Part IV describes in detail. May Day and Big Bang are worth holding in mind together: eleven years apart, one American and one British, both replacing a fixed-price professional cartel with open price competition, and both direct ancestors of the fee-driven, technology-mediated market structure this book describes throughout. <br>&nbsp;<br>
    
    **Reference:** Big Bang 20 years on, CENTRE FOR POLICY STUDIES,  https://web.archive.org/web/20211015091533/https://www.cps.org.uk/files/reports/original/111028101637-20061019EconomyBigBang20YearsOn.pdf


## Euronext

Euronext is continental Europe's largest exchange group, operating markets in Amsterdam, Brussels, Paris, Lisbon, Dublin, Oslo, and Milan. Originally formed in 2000 by the merger of the Paris, Amsterdam, and Brussels exchanges, it expanded significantly through subsequent acquisitions including the Milan Stock Exchange (Borsa Italiana) in 2021. Euronext uses the **Optiq** trading platform and operates under MiFID II. Its Amsterdam exchange is historically notable as the successor to what is widely regarded as the world's first stock exchange, where VOC shares traded from 1602.

## Nasdaq Stockholm (Stockholmsbörsen, STO)

Nasdaq Stockholm is Sweden's primary regulated securities exchange and one of the core venues in the Nordic region. The original Stockholm Stock Exchange dates to 1863, and the modern market became part of the Nasdaq group through Nasdaq's acquisition of OMX in 2008. Today, Nasdaq Stockholm operates as part of the wider Nasdaq Nordic market structure alongside Copenhagen, Helsinki, and Icelandic venues.

For exchange developers, Nasdaq Stockholm is a useful real-world reference because it combines deep local equity liquidity with a highly standardised pan-Nordic technology model. The market is fully electronic, supports auction phases (including opening and closing auctions), and runs under the same MiFID II transparency and best-execution regime as other EU venues.

The venue's best-known benchmark is the **OMXS30** index, which tracks the 30 most traded shares on Nasdaq Stockholm. The exchange is the home listing venue for many major Swedish and Nordic companies, including names such as Ericsson, Volvo, Atlas Copco, and Investor AB, making it central to Nordic equity price discovery.

From an infrastructure perspective, Nasdaq Stockholm aligns with broader Nasdaq market technology standards (including INET-based matching architecture for cash equities) and interoperates with regional post-trade infrastructure such as Euroclear Sweden for securities settlement. In practical terms, this makes it a strong example of how a national exchange can preserve local market identity while operating inside a larger cross-border technology and regulatory framework.

## IEX (Investors Exchange)

IEX launched as a dark pool in 2013 and became a registered national securities exchange in 2016. It is the exchange that popularised the **speed bump**: a deliberate 350-microsecond delay applied to incoming orders, designed to level the playing field between HFT latency arbitrage strategies and slower institutional investors. IEX was the subject of Michael Lewis's 2014 book *Flash Boys*, which brought widespread public attention to HFT and exchange structure debates.

The speed bump attracted significant institutional support from large asset managers who believed it reduced predatory latency arbitrage. However, IEX has consistently captured a relatively small share of US equity volume (typically 2–3%) [1], suggesting that the speed bump's appeal did not translate into dominant market share. Whether this reflects genuine limitations of the model or simply the difficulty of displacing entrenched incumbent exchanges remains debated in market structure circles. IEX remains disproportionately influential in regulatory discussions given its size, having prompted rule-making discussions at the SEC around speed bumps and exchange access fees.

## Cboe (Chicago Board Options Exchange)
Cboe Global Markets is the largest US options exchange group, operating Cboe Options, C2, BZX, BYX, EDGX, and EDGA among others. Cboe invented the listed options market in 1973. It calculates the VIX (Volatility Index, the "fear gauge" of the market) from options prices.

## JPX (Japan Exchange Group)
JPX was formed in 2013 by merging the Tokyo Stock Exchange (TSE) and Osaka Securities Exchange. It is consistently one of the world's largest exchanges by market capitalisation of listed companies, generally ranked just behind NYSE and NASDAQ and close to Shanghai, though the precise ordering shifts from year to year and depends on whether Shanghai and Shenzhen are counted as one market or two, so any "top three" claim should be checked against a dated source (e.g., World Federation of Exchanges statistics) rather than treated as fixed. JPX operates on an all-electronic platform called arrowhead. Japanese markets have their own session structure, tick size rules, and circuit breaker conventions; the daily price limit system (where trading in a stock is suspended if it moves more than a set amount from the previous close) differs from the US LULD approach.

## HKEX (Hong Kong Exchanges and Clearing)
HKEX is the primary exchange for Hong Kong-listed equities and also provides the main electronic gateway for mainland China stocks through the Shanghai-Hong Kong Stock Connect and Shenzhen-Hong Kong Stock Connect programmes. Stock Connect allows international investors to trade China A-shares (mainland China stocks) and allows mainland investors to trade Hong Kong-listed stocks through a northbound/southbound quota system, a unique regulatory and technical arrangement in which orders are routed across the border to the other market's matching engine, subject to real-time quota control.

## SGX (Singapore Exchange)

SGX is Southeast Asia's largest exchange, trading equities, derivatives, and fixed income. It is notable as a hub for Asian futures contracts, Nikkei 225 futures, MSCI Asia index futures, and iron ore contracts all trade on SGX. SGX acquired Scientific Beta (factor indices) and has invested heavily in data analytics services alongside its exchange operations.

## ASX (Australian Securities Exchange)

ASX serves the Australian equity and derivatives markets. It became notable in the technology community for its attempt to replace its CHESS (Clearing House Electronic Subregister System) settlement platform with a blockchain-based system, a project that was cancelled in November 2022 after years of development, with ASX writing off roughly A$250 million. The cancellation is a cautionary tale for exchange technologists about the risks of replacing proven settlement infrastructure with unproven technology.




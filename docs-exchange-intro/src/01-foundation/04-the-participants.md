# The Participants


Before diving into mechanics, it helps to know who is actually in the room.

## Traders and Investors

The broadest category of participant is anyone who buys or sells for themselves, whether they are profit-seeking or managing risk.

**Retail investors** are individuals trading their own money, typically through brokerage apps (Robinhood, Fidelity, Schwab, eToro). Retail orders tend to be small (a few hundred shares at most), arrive randomly throughout the day, and , critically , are considered **uninformed flow** by market makers, meaning they are statistically unlikely to be based on superior information about the company's near-term prospects. Retail flow is therefore profitable to serve: the spread can be captured with low adverse selection risk.

**Institutional investors** are organisations managing money on behalf of others: pension funds, mutual funds, hedge funds, insurance companies, sovereign wealth funds, endowments. They trade in sizes that can move markets , a pension fund rebalancing its portfolio may need to buy or sell millions of shares over days or weeks without moving the price against itself. Their orders are typically routed through execution desks that use VWAP algorithms, dark pools, and smart order routing to minimise market impact. The largest institutional investors (BlackRock manages over $10 trillion in assets [1]) have more market influence than many sovereign nations.

The distinction between retail and institutional matters for exchange designers because the two populations have different latency tolerances, different order sizes, different information sets, and different legal frameworks governing their trading. Payment for Order Flow (PFOF) exists because retail flow is genuinely more profitable to service than institutional flow, and this shapes the routing decisions of retail brokers.

In exchange terminology, when a participant submits an aggressive order that immediately executes against a resting order in the book, they are called a **taker** , they are "taking" liquidity that was already available. The participant whose resting order was filled is the **maker** (they "made" liquidity available).

## High-Frequency Trading (HFT) and Proprietary Trading Firms

A distinct and important participant type that does not fit neatly into the retail/institutional or maker/taker classification is the **high-frequency trading (HFT) firm** and broader class of **proprietary trading firms** (often called "prop shops").

These firms trade entirely for their own account, with their own capital, using automated strategies. They do not manage client money and do not act as brokers. Well-known firms include Citadel Securities, Virtu Financial, Jane Street, Jump Trading, and IMC. Some (like Citadel Securities and Virtu) are primarily market makers; others run arbitrage and statistical arbitrage strategies.

HFT firms are estimated to account for approximately 50% of equity trading volume on US exchanges [1], and a significant portion of derivatives volume. They make markets extremely tight (narrow spreads) in liquid products because competition between HFT market makers is intense. They also create controversy: critics argue that latency arbitrage gives them an unfair structural advantage over slower participants; defenders argue that their market making activity lowers costs for everyone.

For exchange developers, HFT firms are the most technically demanding participants. Their latency requirements drive the design of co-location services, the nanosecond timestamping standards, and the deterministic processing guarantees that define high-performance matching engine architecture. When an exchange system must process millions of messages per second with microsecond response times, it is largely because HFT participants require it.

## Market Makers

This is a concept worth understanding deeply, because it is central to how exchanges actually work in practice, and because the exchange system you are building contains a significant amount of code dedicated specifically to managing market makers.

A **market maker** is a professional participant who continuously quotes both a buy price and a sell price for an instrument. They are simultaneously willing to buy from anyone who wants to sell, and to sell to anyone who wants to buy. In exchange for taking on this obligation, they earn the **spread**, the small gap between the price they will buy at and the price they will sell at. Market makers are the reason you can usually buy or sell a stock immediately without waiting for a human counterparty to appear. Their standing orders are already in the book, waiting.

NYSE has what it calls **Designated Market Makers (DMMs)**, specific firms assigned to each stock with obligations to maintain fair and orderly markets. Nasdaq calls them **Market Makers**. Eurex, the European derivatives exchange, runs a formal **Market Making Programme** with contractual quoting obligations. When a market maker's resting order is later filled by someone else's incoming order, the market maker is called a **maker** (they "made" liquidity available). The person whose order triggered the fill is the **taker**. Exchanges frequently give makers a fee rebate and charge takers a fee, to incentivise the provision of liquidity.

> **Key idea:** Market makers earn the spread by continuously providing two-sided quotes, a standing bid and ask, making it possible for others to trade immediately at any time. They are not passive: their position changes with every fill, and they must manage inventory and information risk in real time. The *Market Makers* section of Part II examines the full operational detail: formal obligations, what happens when a quote is hit, protection mechanisms, and the software implications of supporting them.

## Brokers

**Broker** itself is an old word. The word "broker" traces back to Middle English (brocour) and Anglo-Norman (abrocour), originally referring to a middleman, small trader, or wine merchant. It referred originally to a person who "broaches" (opens) a cask and sells the wine retail, an intermediary between producer and consumer. By the late medieval period it had generalised to any trade intermediary, and it has carried that meaning into finance.

A broker does not trade for their own account. They act as an intermediary: they receive orders from clients and submit them to the exchange on the client's behalf. Retail brokerages (Fidelity, Schwab, eToro) aggregate small orders from millions of individuals. Institutional brokers (Goldman Sachs, Morgan Stanley, JPMorgan) execute large block orders for institutional clients with minimum market impact.

**Prime brokers** are a specific tier of broker providing a package of services to sophisticated clients, primarily hedge funds: securities lending (enabling short selling), leveraged financing, consolidated clearing and custody across multiple brokers, and sometimes execution services. Without a prime broker relationship, a hedge fund could not efficiently short sell or use leverage. The major prime brokers are divisions of the large investment banks.

## The Exchange Itself

The exchange is not a passive infrastructure provider. It is a regulated entity that enforces rules, monitors for manipulation, reports trades to regulators, and ensures the market functions fairly. In many jurisdictions, exchanges are themselves public companies listed on exchanges (NYSE's parent company, ICE, is listed on NYSE; NASDAQ lists on Nasdaq).

A significant historical shift: exchanges used to be **member-owned mutuals**, non-profit organisations run for the benefit of their broker-dealer members. Over the past 30 years, most major exchanges have **demutualised**, converting to for-profit public companies. NYSE demutualised and listed in 2006; London Stock Exchange demutualised in 2001. This shift changed the incentive structure of exchanges: they now compete for order flow and listing fees, and their technology investment decisions are driven partly by shareholder returns.

## Regulators

Regulators are not participants in the traditional sense, they do not submit orders, but they are the most consequential stakeholders in exchange system design. Every audit trail format, kill switch requirement, pre-trade check, and trade report exists to satisfy a regulatory obligation.

In the US, the **SEC** oversees equity exchanges and broker-dealers. The **CFTC** oversees futures and derivatives exchanges. **FINRA** (Financial Industry Regulatory Authority) is a self-regulatory organisation that oversees broker-dealers. Exchanges themselves are also self-regulatory organisations (SROs): they have obligations to monitor their own markets and report suspicious activity.

Internationally: the **FCA** (Financial Conduct Authority) in the UK, **ESMA** (European Securities and Markets Authority) and national regulators under MiFID II in the EU, the **FSA** in Japan, the **SFC** in Hong Kong, and ASIC in Australia.

For exchange developers, the practical implication is that regulatory requirements are non-negotiable features. A matching engine that produces a legally insufficient audit trail is not a working matching engine, regardless of its throughput. Understanding which regulator and which ruleset governs a given exchange is part of the technical specification.

> **Note, quotes vs orders:** Throughout this document, the terms "order" and "quote" are sometimes used to describe resting instructions in the book. Operationally they are different: a **quote** is a two-sided bid/ask pair submitted by a market maker (a single instruction generating two linked legs), while an **order** is a one-sided instruction submitted by any participant. A quote may internally generate one or two order records with linked identifiers; quote IDs and order IDs may differ. The *Market Makers* section of Part II covers this distinction in detail.


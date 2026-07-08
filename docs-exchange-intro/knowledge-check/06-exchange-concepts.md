# Exchange Concepts Knowledge Check — Variant 02
Purpose: verify that the student has read [How a Financial Exchange Works](../how-exchange-works.md) and internalized the core principles of a modern exchange, across its full scope — market history, order mechanics, risk and compliance, and technology infrastructure.

## Name/ID

&nbsp;

---

&nbsp;

## Instructions

- There are 20 questions.
- Each question has five statements (A-E) which may be false or true.
- Select all statements you believe to be correct by clearly filling the square before the question.
- Each question may have multiple correct statements (for some, all five statements may be correct).
- There are always at least one correct statement.

## Scoring

- +1 point for each correct option selected.
- -2 points for each incorrect option selected.
- 0 points for options not selected.
- Final test score is capped at a minimum of 0: if raw total is negative, recorded score is 0.
- A passing score is 70% of the maximum rounded down to the nearest integer. 

<div style="page-break-after: always;"></div>


## Questions

### 1. Instrument types
- [ ] A. Futures and options are contracts about future transactions, rather than direct claims on an already-existing asset
- [ ] B. ETFs are baskets of shares, bonds, or commodities that themselves trade on an exchange as a single instrument
- [ ] C. FX pairs like EUR/USD trade primarily on centralized exchanges rather than electronic networks
- [ ] D. Each equity symbol maintains its own separate, independent order book
- [ ] E. Market indices such as the S&P 500 can be directly bought and sold on an exchange the same way an individual stock can

### 2. Aggressor, maker, and taker
- [ ] A. The "aggressor" flag on a trade has no bearing on fee calculation under a maker-taker fee model
- [ ] B. A "taker" is the participant whose incoming order immediately executes against resting liquidity
- [ ] C. A "maker" is the participant whose resting order was filled by an incoming aggressive order
- [ ] D. Exchanges typically charge makers a fee while paying takers a rebate under the dominant US model
- [ ] E. The aggressor side has no relevance to regulatory reporting or market-microstructure analysis

### 3. Market capitalization, worked example
- [ ] A. Market capitalization is calculated as share price multiplied by the total number of shares outstanding
- [ ] B. The book's illustrative Apple example uses roughly 15.4 billion shares at $190 to arrive at a market cap of roughly $2.9 trillion
- [ ] C. A company's market cap and its total revenue are the same figure under a different name
- [ ] D. When exchange rankings describe "the world's largest exchange by listed market cap," they are summing the market caps of every company listed there
- [ ] E. Because market cap depends on share price, it fluctuates continuously throughout the trading day as the stock trades

### 4. Regulator responsibilities
- [ ] A. In the US, the SEC oversees equity exchanges while the CFTC oversees futures and derivatives exchanges
- [ ] B. FINRA is a government agency with statutory rule-making authority equal to the SEC
- [ ] C. ESMA and MiFID II govern equity market structure in the United States
- [ ] D. The FCA is the primary derivatives regulator in Japan
- [ ] E. Regulators are typically classified in the book as active order-submitting participants, just like brokers

### 5. Putting it all together, worked scenario
- [ ] A. A large aggressive sell order can sweep through several price levels, consuming resting liquidity including a market maker's quote, in a single continuous-trading event
- [ ] B. Consuming an iceberg order's visible peak can trigger a replenishment from its hidden reserve during that same sweep
- [ ] C. A dormant sell stop order can be triggered by a new trade price and then join the ongoing sweep once converted
- [ ] D. If the resulting price move breaches a circuit-breaker band, the engine can transition into a halted state and cancel resting market-maker quotes
- [ ] E. After a halt resolves via a resumption auction, the market can return to continuous trading, with any unmatched remaining quantity resting in the book

### 6. Message buses and subscribers
- [ ] A. Subscribers such as the clearing process, stats recorder, and audit log are described as passive receivers that do not write to the order book
- [ ] B. A message bus using a publish/subscribe pattern is one way exchange components distribute events to multiple downstream consumers
- [ ] C. Every subscriber to the message bus is required to also have write access to the live order book to function correctly
- [ ] D. Book snapshots aggregated by price level are commonly published on a periodic basis, such as roughly every 500 milliseconds per symbol
- [ ] E. A ticker or viewer/board application is an example of a component that writes new orders directly into the book

### 7. Recovery objectives, revisited
- [ ] A. RPO measures how much data loss is acceptable, while RTO measures how much downtime is acceptable
- [ ] B. Batch reporting systems generally require the same ultra-tight RTO as the live matching engine
- [ ] C. For a matching engine, an RPO target of several minutes of potential data loss is considered entirely acceptable
- [ ] D. RTO and RPO are two different names for exactly the same recovery concept
- [ ] E. The 2015 NYSE halt, lasting roughly 3.5 hours, is used in the book as a benchmark example of an unacceptably long RTO

<div style="page-break-after: always;"></div>

### 8. Crypto precision and settlement
- [ ] A. Bitcoin amounts are commonly denominated down to a hundred-millionth of a unit, called a satoshi
- [ ] B. Many Ethereum-based tokens use as many as 18 decimal places of precision
- [ ] C. Using ordinary floating-point arithmetic is considered even more acceptable for crypto-asset amounts than for traditional currency amounts, given crypto's digital-native design
- [ ] D. A constant-product AMM formula prices trades based on the relationship between the reserves of two pooled assets
- [ ] E. On a typical AMM-based DEX, a trade executes and settles atomically within a single blockchain transaction

### 9. The Sarao case, timeline
- [ ] A. Navinder Singh Sarao was arrested by UK authorities in April 2015 and pleaded guilty in the US in November 2016
- [ ] B. Sarao's alleged spoofing activity took place exclusively during a single afternoon in 2010, with no earlier or later pattern
- [ ] C. Sarao traded from a large institutional trading floor in New York
- [ ] D. Sarao's case established that spoofing prosecutions require every individual order to itself be fraudulent
- [ ] E. Sarao's alleged conduct was found to have no connection whatsoever to the events of May 6, 2010

### 10. Market-abuse taxonomy
- [ ] A. Spoofing involves placing orders with no genuine intent to trade, aimed at influencing perceived book pressure, then cancelling before fill
- [ ] B. Layering is described as a variant of spoofing, using multiple orders at various price levels to create a false impression of depth
- [ ] C. Front running means trading only using publicly available information that everyone else can also see at the same time
- [ ] D. Quote stuffing involves flooding an exchange with orders and cancellations to consume bandwidth and slow down competitors
- [ ] E. Wash trading and self-match prevention are unrelated concepts with no overlap

### 11. Market-wide circuit-breaker thresholds
- [ ] A. A 7% decline in the S&P 500 before 3:25pm can trigger a 15-minute Level 1 market-wide trading halt
- [ ] B. A 13% decline before 3:25pm can trigger a further 15-minute Level 2 halt
- [ ] C. A 20% decline triggers a Level 3 halt that stops trading for the remainder of the session, regardless of time of day
- [ ] D. Level 3 has never actually been triggered under the current rules, per the book
- [ ] E. These market-wide thresholds are measured against decline from the prior session's closing level

<div style="page-break-after: always;"></div>

### 12. Options contracts, numeric details
- [ ] A. One standard US equity option contract typically corresponds to 100 underlying shares
- [ ] B. Cash settlement, not physical delivery, is standard for individual single-stock equity options
- [ ] C. Cboe's VIX options and other broad index options are typically cash-settled, since physically delivering "the index" isn't meaningful
- [ ] D. A reference-data error loading a contract multiplier as 500 instead of the correct 50 would leave risk calculations unaffected
- [ ] E. Assigned option writers always know with certainty on expiry afternoon whether they will be assigned

### 13. Exchange revenue and real-exchange facts
- [ ] A. Exchanges generate revenue from trading fees, listing fees, and market data/connectivity fees, such as direct feeds and co-location rack space
- [ ] B. Data and connectivity revenue has grown to represent a substantial and, in some cases, faster-growing share of major exchange profit compared to trading-fee revenue
- [ ] C. Nasdaq Stockholm's benchmark index, the OMXS30, tracks its 30 most-traded shares
- [ ] D. Euronext was formed through a merger of exchanges including Paris, Amsterdam, and Brussels, and later acquired Borsa Italiana
- [ ] E. Exchanges have no financial incentive to actively court companies before their IPOs, since listing decisions are purely regulatory

### 14. Continued listing standards
- [ ] A. A stock whose closing price stays below $1.00 for 30 consecutive trading days commonly triggers a formal deficiency notice under continued listing standards
- [ ] B. Continued listing standards apply only at the moment of initial listing and are never checked again afterward
- [ ] C. A company that fails to cure a listing deficiency has no option to appeal and is delisted immediately, with no process
- [ ] D. A cure period for a minimum-bid-price deficiency is commonly measured in a small number of days, such as three
- [ ] E. Reverse stock splits are prohibited as a remedy for minimum-bid-price deficiencies

### 15. SLIs, SLOs, and alerting design
- [ ] A. An SLI is a precisely defined metric, while an SLO is the target value set for that metric
- [ ] B. An exhausted error budget is generally treated as a signal to shift engineering priority toward stability rather than shipping new features as fast as possible
- [ ] C. SLOs are typically defined as a single number that applies uniformly, regardless of which session phase (auction, continuous, halt) the system is in
- [ ] D. Symptom-based alerting, which pages when participants are actually affected, is generally preferred over paging on every minor cause-level fluctuation like elevated CPU
- [ ] E. Paging and ticketing are the same escalation mechanism and should always wake a human immediately

<div style="page-break-after: always;"></div>

### 16. Execution algorithms, comparative
- [ ] A. A VWAP algorithm estimates the expected volume profile across the day and participates more heavily during historically higher-volume periods like the open and close
- [ ] B. A TWAP algorithm divides an order into equal slices across equal time intervals, regardless of actual traded volume
- [ ] C. An Implementation Shortfall algorithm benchmarks itself against a fixed price set at the very end of the trading day
- [ ] D. A Percentage of Volume strategy adjusts its own trading pace to remain a fixed proportion of whatever volume is actually trading in the market
- [ ] E. Implementation Shortfall strategies can trade faster when the price moves unfavorably away from the arrival price and slower when it moves favorably

### 17. Tick-size banding
- [ ] A. Under MiFID II's banded tick-size regime, a lower-priced stock can trade in a smaller absolute tick increment than a higher-priced stock, within the same framework
- [ ] B. MiFID II's tick-size regime applies exactly one single fixed tick size across every price band and liquidity category
- [ ] C. Tick size for the same underlying stock is described in the book as always identical across every listing venue
- [ ] D. The E-mini S&P 500 futures contract is described as ticking in units of a full index point, rather than a fraction of one
- [ ] E. US Treasury futures are described in the book as ticking in units of 1/32nds

### 18. Fragmentation and routing, recap
- [ ] A. Reg NMS's requirement that orders receive the best available price across venues is described as a direct reason the US has more than a dozen registered equity exchanges competing for flow
- [ ] B. The book's illustrative AAPL volume-split example shows NASDAQ capturing a noticeably larger share of trading than NYSE
- [ ] C. Dark pools and internalisers are excluded entirely from the book's discussion of where AAPL's trading volume can be split across
- [ ] D. Fragmentation across many venues is presented in the book as adding complexity to routing decisions and best-price discovery
- [ ] E. A Smart Order Router's decision criteria are described as limited strictly to price, ignoring fees, depth, or queue-position probability

<div style="page-break-after: always;"></div>

### 19. Capstone synthesis
- [ ] A. Exchanges are described as making three implicit promises to participants: price discovery, liquidity, and fairness/transparency
- [ ] B. Regulatory requirements like audit-trail formats and kill-switch rules are treated in the book as engineering specifications, not merely legal formalities layered on afterward
- [ ] C. Deterministic, single-threaded matching is presented as supporting auditability and legal defensibility, not just raw performance
- [ ] D. Historical incidents such as Knight Capital, the 1987 crash, and the Flash Crash are used throughout the book to explain why specific risk controls exist today
- [ ] E. The book frames exchange engineering as inseparable from market structure, history, and regulation, rather than as a purely technical problem in isolation

### 20. The book's own caveats
- [ ] A. The book itself flags at least one of its own statistics, such as the NYSE closing auction's share of daily volume, as an illustrative figure rather than one tied to a single rigorously verifiable primary source
- [ ] B. Every single numeric figure in the book is presented as coming from a fully audited primary regulatory filing, with no caveats
- [ ] C. The book claims that circuit-breaker thresholds have remained completely fixed and unchanged since 1988
- [ ] D. The book states that odd-lot trading data has always been fully included in NBBO calculations since markets began
- [ ] E. The book asserts that reference-data errors are rarer causes of real exchange outages than matching-engine bugs

&nbsp;

---

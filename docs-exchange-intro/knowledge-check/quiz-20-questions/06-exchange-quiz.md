# Exchange Concepts Knowledge Check — Variant 06
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
- [ ] A. ETFs are baskets of shares, bonds, or commodities that themselves trade on an exchange as a single instrument
- [ ] B. Each equity symbol maintains its own separate, independent order book
- [ ] C. Market indices such as the S&P 500 can be directly bought and sold on an exchange the same way an individual stock can
- [ ] D. FX pairs like EUR/USD trade primarily on centralized exchanges rather than electronic networks
- [ ] E. Futures and options are contracts about future transactions, rather than direct claims on an already-existing asset

### 2. Aggressor, maker, and taker
- [ ] A. A "maker" is the participant whose resting order was filled by an incoming aggressive order
- [ ] B. The aggressor side has no relevance to regulatory reporting or market-microstructure analysis
- [ ] C. Exchanges typically charge makers a fee while paying takers a rebate under the dominant US model
- [ ] D. The "aggressor" flag on a trade has no bearing on fee calculation under a maker-taker fee model
- [ ] E. A "taker" is the participant whose incoming order immediately executes against resting liquidity

### 3. Market capitalization, worked example
- [ ] A. When exchange rankings describe "the world's largest exchange by listed market cap," they are summing the market caps of every company listed there
- [ ] B. Market capitalization is calculated as share price multiplied by the total number of shares outstanding
- [ ] C. A company's market cap and its total revenue are the same figure under a different name
- [ ] D. Because market cap depends on share price, it fluctuates continuously throughout the trading day as the stock trades
- [ ] E. The book's illustrative Apple example uses roughly 15.4 billion shares at $190 to arrive at a market cap of roughly $2.9 trillion

### 4. Regulator responsibilities
- [ ] A. FINRA is a government agency with statutory rule-making authority equal to the SEC
- [ ] B. Regulators are typically classified in the book as active order-submitting participants, just like brokers
- [ ] C. In the US, the SEC oversees equity exchanges while the CFTC oversees futures and derivatives exchanges
- [ ] D. ESMA and MiFID II govern equity market structure in the United States
- [ ] E. The FCA is the primary derivatives regulator in Japan

### 5. Putting it all together, worked scenario
- [ ] A. A dormant sell stop order can be triggered by a new trade price and then join the ongoing sweep once converted
- [ ] B. If the resulting price move breaches a circuit-breaker band, the engine can transition into a halted state and cancel resting market-maker quotes
- [ ] C. After a halt resolves via a resumption auction, any quantity the auction did not match is cancelled rather than resting in the book
- [ ] D. A large aggressive sell order can sweep through several price levels, consuming resting liquidity including a market maker's quote, in a single continuous-trading event
- [ ] E. Consuming an iceberg order's visible peak can trigger a replenishment from its hidden reserve during that same sweep

### 6. Message buses and subscribers
- [ ] A. A message bus using a publish/subscribe pattern is one way exchange components distribute events to multiple downstream consumers
- [ ] B. Subscribers such as the clearing process, stats recorder, and audit log are described as passive receivers that do not write to the order book
- [ ] C. In the book's reference exchange, snapshots aggregated by price level are published periodically, every 500 milliseconds per symbol
- [ ] D. Every subscriber to the message bus is required to also have write access to the live order book to function correctly
- [ ] E. A ticker or viewer/board application is an example of a component that writes new orders directly into the book

### 7. Recovery objectives, revisited
- [ ] A. Batch reporting systems generally require the same ultra-tight RTO as the live matching engine
- [ ] B. RTO and RPO are two different names for exactly the same recovery concept
- [ ] C. For a matching engine, an RPO target of several minutes of potential data loss is considered entirely acceptable
- [ ] D. RPO measures how much data loss is acceptable, while RTO measures how much downtime is acceptable
- [ ] E. The 2015 NYSE halt, lasting roughly 3.5 hours, is used in the book as a benchmark example of an unacceptably long RTO

<div style="page-break-after: always;"></div>

### 8. Crypto precision and settlement
- [ ] A. Bitcoin amounts are commonly denominated down to a hundred-millionth of a unit, called a satoshi
- [ ] B. A constant-product AMM formula prices trades based on the relationship between the reserves of two pooled assets
- [ ] C. Many Ethereum-based tokens use as many as 18 decimal places of precision
- [ ] D. Using ordinary floating-point arithmetic is considered even more acceptable for crypto-asset amounts than for traditional currency amounts, given crypto's digital-native design
- [ ] E. On a typical AMM-based DEX, a trade executes and settles atomically within a single blockchain transaction

### 9. Clearly erroneous trades
- [ ] A. Most of Knight Capital's August 2012 fills were busted as clearly erroneous
- [ ] B. Clearly erroneous rules act as a general-purpose undo for any trade a participant regrets
- [ ] C. A clearly erroneous request must be filed within a short window, commonly 30 minutes under US rules
- [ ] D. The clearly erroneous test is applied execution by execution, using the percentage deviation from a reference price
- [ ] E. An erroneous-price event that spans several venues needs coordinated, consistent rulings across those exchanges

### 10. Market-abuse taxonomy
- [ ] A. Layering is described as a variant of spoofing, using multiple orders at various price levels to create a false impression of depth
- [ ] B. Wash trading and self-match prevention are unrelated concepts with no overlap
- [ ] C. Front running means trading only using publicly available information that everyone else can also see at the same time
- [ ] D. Spoofing involves placing orders with no genuine intent to trade, aimed at influencing perceived book pressure, then cancelling before fill
- [ ] E. Quote stuffing involves flooding an exchange with orders and cancellations to consume bandwidth and slow down competitors

### 11. Market-wide circuit-breaker thresholds
- [ ] A. A 7% decline in the S&P 500 before 3:25pm can trigger a 15-minute Level 1 market-wide trading halt
- [ ] B. Level 3 has never actually been triggered under the current rules, per the book
- [ ] C. A 20% decline triggers a Level 3 halt that stops trading for the remainder of the session, regardless of time of day
- [ ] D. A 13% decline before 3:25pm triggers a Level 2 halt that ends trading for the rest of the day
- [ ] E. US market-wide circuit-breaker thresholds are measured as a decline from the prior session's S&P 500 close

<div style="page-break-after: always;"></div>

### 12. Options contracts, numeric details
- [ ] A. Cash settlement, not physical delivery, is standard for individual single-stock equity options
- [ ] B. Assigned option writers always know with certainty on expiry afternoon whether they will be assigned
- [ ] C. Cboe's VIX options and other broad index options are typically cash-settled, since physically delivering "the index" isn't meaningful
- [ ] D. One standard US equity option contract typically corresponds to 100 underlying shares
- [ ] E. A reference-data error loading a contract multiplier as 500 instead of the correct 50 would leave risk calculations unaffected

### 13. Exchange revenue and real-exchange facts
- [ ] A. Euronext was formed through a merger of exchanges including Paris, Amsterdam, and Brussels, and later acquired Borsa Italiana
- [ ] B. Exchanges compete to win IPO listings, because listings bring fees and trading volume
- [ ] C. Data and connectivity revenue has grown to represent a substantial and, in some cases, faster-growing share of major exchange profit compared to trading-fee revenue
- [ ] D. Exchanges generate revenue from trading fees, listing fees, and market data/connectivity fees, such as direct feeds and co-location rack space
- [ ] E. Exchanges have no financial incentive to actively court companies before their IPOs, since listing decisions are purely regulatory

### 14. Continued listing standards
- [ ] A. A cure period for a minimum-bid-price deficiency is commonly measured in a small number of days, such as three
- [ ] B. A reverse stock split is a common way to cure a minimum-bid-price deficiency
- [ ] C. A company that fails to cure a listing deficiency has no option to appeal and is delisted immediately, with no process
- [ ] D. A stock whose closing price stays below $1.00 for 30 consecutive trading days commonly triggers a formal deficiency notice under continued listing standards
- [ ] E. Continued listing standards apply only at the moment of initial listing and are never checked again afterward

### 15. SLIs, SLOs, and alerting design
- [ ] A. An exhausted error budget is generally treated as a signal to shift engineering priority toward stability rather than shipping new features as fast as possible
- [ ] B. Paging and ticketing are the same escalation mechanism and should always wake a human immediately
- [ ] C. SLOs are typically defined as a single number that applies uniformly, regardless of which session phase (auction, continuous, halt) the system is in
- [ ] D. Symptom-based alerting, which pages when participants are actually affected, is generally preferred over paging on every minor cause-level fluctuation like elevated CPU
- [ ] E. An SLI is a precisely defined metric, while an SLO is the target value set for that metric

<div style="page-break-after: always;"></div>

### 16. Execution algorithms, comparative
- [ ] A. A TWAP algorithm divides an order into equal slices across equal time intervals, regardless of actual traded volume
- [ ] B. A VWAP algorithm estimates the expected volume profile across the day and participates more heavily during historically higher-volume periods like the open and close
- [ ] C. A Percentage of Volume strategy adjusts its own trading pace to remain a fixed proportion of whatever volume is actually trading in the market
- [ ] D. Implementation Shortfall strategies can trade faster when the price moves unfavorably away from the arrival price and slower when it moves favorably
- [ ] E. An Implementation Shortfall algorithm benchmarks itself against a fixed price set at the very end of the trading day

### 17. Tick-size banding
- [ ] A. MiFID II's tick-size regime applies exactly one single fixed tick size across every price band and liquidity category
- [ ] B. The E-mini S&P 500 futures contract is described as ticking in units of a full index point, rather than a fraction of one
- [ ] C. Under MiFID II's banded tick-size regime, a lower-priced stock can trade in a smaller absolute tick increment than a higher-priced stock, within the same framework
- [ ] D. US Treasury futures are described in the book as ticking in 32nds of a point and fractions of a 32nd
- [ ] E. Tick size for the same underlying stock is described in the book as always identical across every listing venue

### 18. Fragmentation and routing, recap
- [ ] A. The book states that dark pools and internalisers play no meaningful role in where US equity volume executes
- [ ] B. Reg NMS, by forbidding venues to trade through better displayed prices elsewhere, is described as creating strong incentives for new venues to compete with NYSE and NASDAQ
- [ ] C. The book notes that, in recent years, close to half of all US equity volume has executed off-exchange
- [ ] D. A Smart Order Router's decision criteria are described as limited strictly to price, ignoring fees, depth, or queue-position probability
- [ ] E. Fragmentation across many venues is presented in the book as adding complexity to routing decisions and best-price discovery

<div style="page-break-after: always;"></div>

### 19. Capstone synthesis
- [ ] A. The book treats regulation as a legal formality that developers can bolt on after the engine is built
- [ ] B. Historical incidents such as Knight Capital, the 1987 crash, and the Flash Crash are used throughout the book to explain why specific risk controls exist today
- [ ] C. The book frames exchange engineering as inseparable from market structure, history, and regulation, rather than as a purely technical problem in isolation
- [ ] D. Regulatory requirements like audit-trail formats and kill-switch rules are treated in the book as engineering specifications, not merely legal formalities layered on afterward
- [ ] E. Deterministic, single-threaded matching is presented as supporting auditability and legal defensibility, not just raw performance

### 20. Odd lots and round lots
- [ ] A. Under the SEC's 2020 market-data-infrastructure rules, odd-lot information is being phased into the consolidated feeds
- [ ] B. For decades, odd-lot orders were excluded from the consolidated tape and the NBBO
- [ ] C. Because odd lots were excluded, a better-priced odd-lot quote could be missing from the public best bid and offer
- [ ] D. A round lot is always 1,000 shares, regardless of the stock
- [ ] E. The matching engine cannot fill odd-lot orders, which is why they were kept off the tape

&nbsp;

---

# Exchange Concepts Knowledge Check — Variant 04

Purpose: verify that the student has read [How a Financial Exchange Works](../how-exchange-works.md) and internalized the core principles of a modern exchange, across its full scope — market history, order mechanics, risk and compliance, and technology infrastructure.

## Instructions

- Each question has five options (A-E).
- Select all options you believe are correct.
- It is not known in advance how many options are correct in each question — it may be as few as one or as many as all five.

## Scoring

- +1 point for each correct option selected.
- -2 points for each incorrect option selected.
- 0 points for options not selected.
- Final test score is capped at a minimum of 0: if raw total is negative, recorded score is 0.
- A passing score is 70% of the maximum rounded down to the nearest integer. 

## Questions

### 1. HFT and proprietary trading firms
- [ ] A. HFT and proprietary trading firms manage money primarily on behalf of retail clients
- [ ] B. HFT firms are estimated to account for roughly half of US equity trading volume
- [ ] C. Some prominent proprietary trading firms are primarily market makers, while others run arbitrage/statistical-arbitrage strategies
- [ ] D. Uninformed retail flow is generally considered less profitable for market makers to serve than informed institutional flow
- [ ] E. HFT firms' latency requirements have significantly influenced co-location services and nanosecond timestamping standards

### 2. Brokers and prime brokers
- [ ] A. A broker trades primarily for its own account rather than on behalf of clients
- [ ] B. Prime brokers provide services like securities lending, leveraged financing, and consolidated clearing/custody, mainly to sophisticated clients such as hedge funds
- [ ] C. Without a prime broker relationship, a hedge fund would generally find it easier to efficiently short sell
- [ ] D. The word "broker" traces back to a Middle English/Anglo-Norman word originally describing a middleman who sold wine retail
- [ ] E. Prime brokerage services are typically offered directly by small independent retail brokerages rather than large investment banks

### 3. Demutualization and regulators
- [ ] A. Many major exchanges were historically member-owned mutuals before converting into for-profit public companies
- [ ] B. NYSE demutualized and listed as a public company in 2006
- [ ] C. Exchanges in the US are also self-regulatory organizations, with obligations to monitor their own markets
- [ ] D. FINRA oversees futures and derivatives exchanges in the US, while the SEC oversees broker-dealers
- [ ] E. The London Stock Exchange demutualized in 2001

### 4. LSE's "Big Bang"
- [ ] A. The 1986 "Big Bang" deregulation abolished fixed commissions and replaced open outcry with an electronic quotation system on the London Stock Exchange
- [ ] B. The "Big Bang" refers to the founding of the London Stock Exchange itself in the 17th century
- [ ] C. The "Big Bang" took place gradually over roughly a decade, rather than on a single day
- [ ] D. The "Big Bang" introduced fixed brokerage commissions to the London market for the first time
- [ ] E. The "Big Bang" had no connection to the earlier abolition of fixed commissions on NYSE

### 5. Real-world exchange facts
- [ ] A. CME Group operates multiple exchanges, including CME, CBOT, NYMEX, and COMEX, under its Globex electronic platform
- [ ] B. Eurex runs a formal Market Making Programme with contractual quoting obligations and MMP-style protection
- [ ] C. IEX popularized the concept of a deliberate speed bump using coiled fiber-optic cable to delay incoming orders
- [ ] D. JPX was formed by merging the Tokyo Stock Exchange and the Osaka Securities Exchange
- [ ] E. ASX's attempt to replace its clearing settlement system with a blockchain-based platform was cancelled after years of development

### 6. Listing standards, direct listings, and SPACs
- [ ] A. NASDAQ organizes its listing tiers from most to least stringent as Global Select, Global Market, and Capital Market
- [ ] B. A company pursuing a direct listing sets its opening trade price through a fixed price negotiated in advance with underwriters
- [ ] C. Spotify and Slack are cited as early, pioneering examples of direct listings
- [ ] D. SPAC listing volume increased sharply after 2022, following stricter SEC disclosure requirements
- [ ] E. A SPAC is a shell company that itself IPOs, holds cash in trust, and later merges with a private operating company

### 7. Hidden liquidity and iceberg priority
- [ ] A. Every exchange in the world applies exactly the same priority rule for hidden versus displayed orders
- [ ] B. Some exchanges give fully displayed orders strict priority over hidden/iceberg orders resting at the same price
- [ ] C. Iceberg orders are used exclusively on US exchanges and are unknown on European venues like LSE or Euronext
- [ ] D. An iceberg order's hidden reserve automatically replenishes the visible peak once it's consumed
- [ ] E. Replenishing an iceberg's visible peak always preserves its original queue timestamp under the most common rule

### 8. Midpoint pegs and market-maker inventory risk
- [ ] A. A midpoint peg order continuously tracks the midpoint between the best bid and best ask
- [ ] B. Both the buyer and seller in a midpoint match can receive price improvement relative to the quoted market simultaneously
- [ ] C. Midpoint peg orders are typically favored by HFT market makers who need absolute execution certainty
- [ ] D. When a market maker's bid or ask is filled, the resulting one-sided quote creates an inventory-risk asymmetry that must be managed
- [ ] E. Because the true midpoint may fall between valid tick increments, exchanges must apply a documented, consistent rounding rule across systems

### 9. Adverse selection, worked example
- [ ] A. In the book's worked example, a single adverse-selection fill event can wipe out the spread revenue earned from several ordinary trades
- [ ] B. Adverse selection describes a market maker's ability to selectively avoid ever trading with better-informed counterparties
- [ ] C. Adverse-selection risk applies equally regardless of whether a market maker continuously quotes both sides
- [ ] D. Adverse selection has no relationship to why exchanges offer market-maker protection mechanisms
- [ ] E. The book's worked example shows adverse-selection losses are always smaller than the spread revenue earned on the same fill

### 10. Margin, DvP, and Herstatt risk
- [ ] A. Initial margin is deposited when a position is opened, as an estimate of the maximum likely loss over a short period
- [ ] B. Variation margin is typically settled through a single lump-sum payment only when a position is finally closed, not daily
- [ ] C. Herstatt risk refers to the danger that one party in a currency settlement delivers value while the counterparty, due to time-zone/closure timing, never delivers in return
- [ ] D. Delivery versus Payment ensures securities and cash are exchanged simultaneously, so neither side is released without the other
- [ ] E. Maintenance-margin breaches never result in a forced liquidation of the position by the CCP

### 11. Lehman Brothers and central clearing
- [ ] A. Lehman Brothers filed for bankruptcy in September 2008 with liabilities exceeding $600 billion
- [ ] B. Lehman's large OTC derivatives exposure was bilateral and not centrally cleared, unlike CME's daily mark-to-market futures positions
- [ ] C. CME Clearing's daily mark-to-market process meant no CME futures participant suffered an uncollateralized loss from Lehman's default
- [ ] D. The 2008 crisis contributed to regulatory mandates such as the Dodd-Frank Act in the US and EMIR in the EU, requiring central clearing for many standardized OTC derivatives
- [ ] E. Central counterparty clearing reduces bilateral counterparty exposure by interposing the CCP between buyer and seller

### 12. GameStop, details
- [ ] A. GameStop's stock price rose more than ten times its starting level within days during the January 2021 squeeze
- [ ] B. The retail buying campaign behind the squeeze was primarily organized through a bank trading desk
- [ ] C. The episode triggered a US congressional hearing examining broker trading restrictions and clearing-margin dynamics
- [ ] D. Robinhood's overnight deposit requirement from the NSCC roughly halved compared to its normal level during the squeeze
- [ ] E. Hedge funds forced to cover short positions during the squeeze experienced no financial pressure from rising prices

### 13. The Facebook IPO glitch and the BATS IPO withdrawal
- [ ] A. NASDAQ's IPO cross software defect delayed Facebook's opening trade by roughly 30 minutes
- [ ] B. NASDAQ paid a then-record SEC penalty related to the Facebook IPO cross defect
- [ ] C. BATS Global Markets successfully completed its own IPO on its own exchange despite a software defect
- [ ] D. The BATS software defect caused its own stock price to collapse within under a second and briefly disrupted trading in unrelated symbols
- [ ] E. Both the Facebook and BATS incidents occurred within about ten weeks of each other in 2012

### 14. Regulation SCI and trade reporting
- [ ] A. Regulation SCI requires covered market infrastructure to maintain capacity/resilience and report significant systems issues to regulators
- [ ] B. Off-exchange US trades must be reported to a FINRA facility within 10 minutes of execution
- [ ] C. MiFID II allows unlimited reporting delay for all instrument types, regardless of liquidity
- [ ] D. Derivatives trades are typically reported to a Trade Repository only if both counterparties are US-based
- [ ] E. Trade-reporting obligations do not exist for off-exchange or dark-pool executions

### 15. Incident command
- [ ] A. An Incident Commander coordinates and makes decisions during an incident, distinct from a communications lead who keeps stakeholders informed
- [ ] B. MTTD measures the time it takes to fully resolve an incident, while MTTR measures only detection time
- [ ] C. A blameless postmortem focuses on recording a timeline and improving systems/processes rather than assigning individual blame
- [ ] D. A dead-man's-switch/heartbeat alert is designed to fire when expected signals stop arriving, catching silently-failed telemetry
- [ ] E. Paging and ticketing are treated as identical urgency levels, requiring the same immediate human response

### 16. Index divisors and free float
- [ ] A. An index's divisor is deliberately set at launch, partly so the index reads at a convenient, friendly base value
- [ ] B. When a company in a market-cap-weighted index undergoes a stock split, the divisor must be rescaled to prevent an artificial jump in the index level
- [ ] C. Most serious modern indexes count a company's full market capitalization, including founder and government-held blocks, without any free-float adjustment
- [ ] D. In a price-weighted index like the DJIA, a higher-priced stock moves the index more than a lower-priced one, regardless of the two companies' relative sizes
- [ ] E. Passive index funds' contractually obligatory buying on an index-reconstitution date is one hazard cited around index-inclusion events

### 17. Settlement mechanics
- [ ] A. US equity settlement has progressively shortened over time, from T+5 to T+1
- [ ] B. Some markets, such as certain money-market funds and US Treasuries, already commonly settle same-day
- [ ] C. A buy-in occurs when a seller purchases replacement shares in the open market at the buyer's expense
- [ ] D. DTCC's Depository Trust Company performs settlement exclusively through physical paper certificates today
- [ ] E. Settlement failures can never occur once a trade has matched successfully in the order book

### 18. VWAP and P&L
- [ ] A. VWAP is the volume-weighted average price across a set of trades, weighting each trade's price by its size
- [ ] B. Unrealised P&L reflects gains or losses on positions that remain open and updates continuously as prices move
- [ ] C. Realised P&L can change retroactively after a position has already been fully closed out
- [ ] D. Unrealised P&L is the figure that typically drives real-time margin calls and risk alerts, while realised P&L flows into official accounting at day's end
- [ ] E. VWAP calculations disregard trade size entirely and treat every trade as equally weighted

### 19. Pin risk and triple witching
- [ ] A. A written call option that closes barely in-the-money at expiry can still be automatically exercised, even by a single cent
- [ ] B. Automatic exercise at OCC applies unless the option holder files a contrary instruction
- [ ] C. An option writer may not know with certainty whether they'll be assigned until after the final settlement print and OCC's allocation process
- [ ] D. Triple witching refers to the quarterly simultaneous expiry of stock options, index options, and index futures
- [ ] E. Pin risk can expose an uncovered option writer to a large loss if the underlying gaps significantly after expiry-day assignment

### 20. Exercise, assignment, and allocation
- [ ] A. OCC commonly allocates assignment among a clearing member's short-position clients using methods such as random selection or FIFO by position age
- [ ] B. Assignment is the option holder's own voluntary decision to exercise their right
- [ ] C. European-style options can be exercised at any point before expiry, just like American-style options
- [ ] D. Physical delivery is the standard settlement method for broad index options like SPX
- [ ] E. Pin risk cannot occur in any form for European-style options, since exercise only happens at expiry


# Exchange Concepts Knowledge Check — Variant 04
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

### 1. HFT and proprietary trading firms
- [ ] A. Some prominent proprietary trading firms are primarily market makers, while others run arbitrage/statistical-arbitrage strategies
- [ ] B. HFT and proprietary trading firms manage money primarily on behalf of retail clients
- [ ] C. HFT firms are estimated to account for roughly half of US equity trading volume
- [ ] D. HFT firms' latency requirements have significantly influenced co-location services and nanosecond timestamping standards
- [ ] E. Uninformed retail flow is generally considered less profitable for market makers to serve than informed institutional flow

### 2. Brokers and prime brokers
- [ ] A. A broker trades primarily for its own account rather than on behalf of clients
- [ ] B. Without a prime broker relationship, a hedge fund would generally find it easier to efficiently short sell
- [ ] C. Prime brokerage services are typically offered directly by small independent retail brokerages rather than large investment banks
- [ ] D. Prime brokers provide services like securities lending, leveraged financing, and consolidated clearing/custody, mainly to sophisticated clients such as hedge funds
- [ ] E. A broker executes orders on behalf of clients, earning commissions rather than trading for its own account

### 3. Demutualization and regulators
- [ ] A. NYSE demutualized and listed as a public company in 2006
- [ ] B. Many major exchanges were historically member-owned mutuals before converting into for-profit public companies
- [ ] C. After demutualising, exchanges compete for order flow and listing fees, which changed how they invest in technology
- [ ] D. FINRA oversees futures and derivatives exchanges in the US, while the SEC oversees broker-dealers
- [ ] E. Exchanges in the US are also self-regulatory organizations, with obligations to monitor their own markets

### 4. Exchange business models
- [ ] A. A demutualised, shareholder-owned exchange still carries its market surveillance duties
- [ ] B. Co-location rack space next to the matching engine is sold as part of connectivity revenue
- [ ] C. Trading fees, listing fees, and market data and connectivity fees are the main exchange revenue lines
- [ ] D. Market data revenue is negligible compared with trading fees at major exchanges
- [ ] E. Maker-taker pricing charges the resting order a fee and pays the aggressor a rebate

### 5. Real-world exchanges, how they differ
- [ ] A. Eurex runs a formal Market Making Programme with contractual quoting obligations and MMP-style protection
- [ ] B. IEX's speed bump applies a fixed 350-microsecond delay to incoming orders
- [ ] C. CME Group operates multiple exchanges, including CME, CBOT, NYMEX, and COMEX, under its Globex electronic platform
- [ ] D. JPX handles extreme moves with discrete market-wide halts rather than daily price limits
- [ ] E. NASDAQ began as an automated quotation display rather than as a matching engine

### 6. Listing standards, direct listings, and SPACs
- [ ] A. A company pursuing a direct listing sets its opening trade price through a fixed price negotiated in advance with underwriters
- [ ] B. NASDAQ organizes its listing tiers from most to least stringent as Global Select, Global Market, and Capital Market
- [ ] C. SPAC listing volume increased sharply after 2022, following stricter SEC disclosure requirements
- [ ] D. A SPAC is a shell company that itself IPOs, holds cash in trust, and later merges with a private operating company
- [ ] E. Spotify and Slack are cited as early, pioneering examples of direct listings

### 7. Hidden liquidity and iceberg priority
- [ ] A. Some exchanges give fully displayed orders strict priority over hidden/iceberg orders resting at the same price
- [ ] B. Replenishing an iceberg's visible peak always preserves its original queue timestamp under the most common rule
- [ ] C. Iceberg orders are used exclusively on US exchanges and are unknown on European venues like LSE or Euronext
- [ ] D. An iceberg order's hidden reserve automatically replenishes the visible peak once it's consumed
- [ ] E. Every exchange in the world applies exactly the same priority rule for hidden versus displayed orders

### 8. Midpoint pegs and market-maker inventory risk
- [ ] A. When a market maker's bid or ask is filled, the resulting one-sided quote creates an inventory-risk asymmetry that must be managed
- [ ] B. Midpoint peg orders are typically favored by HFT market makers who need absolute execution certainty
- [ ] C. A midpoint peg order continuously tracks the midpoint between the best bid and best ask
- [ ] D. Both the buyer and seller in a midpoint match can receive price improvement relative to the quoted market simultaneously
- [ ] E. Because the true midpoint may fall between valid tick increments, exchanges must apply a documented, consistent rounding rule across systems

### 9. Adverse selection, worked example
- [ ] A. Adverse selection describes a market maker's ability to selectively avoid ever trading with better-informed counterparties
- [ ] B. In the book's worked example, a single adverse-selection fill event can wipe out the spread revenue earned from several ordinary trades
- [ ] C. The book's worked example shows adverse-selection losses are always smaller than the spread revenue earned on the same fill
- [ ] D. Adverse selection has no relationship to why exchanges offer market-maker protection mechanisms
- [ ] E. Adverse-selection risk applies equally regardless of whether a market maker continuously quotes both sides

### 10. Margin, DvP, and Herstatt risk
- [ ] A. Herstatt risk refers to the danger that one party in a currency settlement delivers value while the counterparty, due to time-zone/closure timing, never delivers in return
- [ ] B. Delivery versus Payment ensures securities and cash are exchanged simultaneously, so neither side is released without the other
- [ ] C. Variation margin is typically settled through a single lump-sum payment only when a position is finally closed, not daily
- [ ] D. Maintenance-margin breaches never result in a forced liquidation of the position by the CCP
- [ ] E. Initial margin is deposited when a position is opened, as an estimate of the maximum likely loss over a short period

### 11. Lehman Brothers and central clearing
- [ ] A. CME futures participants suffered large uncollateralised losses from Lehman's default, because CME marked positions to market only monthly
- [ ] B. Lehman Brothers filed for bankruptcy in September 2008 with liabilities exceeding $600 billion
- [ ] C. Lehman's large OTC derivatives exposure was bilateral and not centrally cleared, unlike CME's daily mark-to-market futures positions
- [ ] D. Central counterparty clearing reduces bilateral counterparty exposure by interposing the CCP between buyer and seller
- [ ] E. The 2008 crisis contributed to regulatory mandates such as the Dodd-Frank Act in the US and EMIR in the EU, requiring central clearing for many standardized OTC derivatives

### 12. GameStop, details
- [ ] A. The retail buying campaign behind the squeeze was primarily organized through a bank trading desk
- [ ] B. The episode triggered a US congressional hearing examining broker trading restrictions and clearing-margin dynamics
- [ ] C. GameStop's share price rose more than tenfold within a month during the January 2021 squeeze
- [ ] D. Robinhood's overnight deposit requirement from the NSCC roughly halved compared to its normal level during the squeeze
- [ ] E. Hedge funds forced to cover short positions during the squeeze experienced no financial pressure from rising prices

### 13. The Facebook IPO glitch and the BATS IPO withdrawal
- [ ] A. BATS Global Markets successfully completed its own IPO on its own exchange despite a software defect
- [ ] B. NASDAQ paid a then-record SEC penalty related to the Facebook IPO cross defect
- [ ] C. The BATS IPO failure came about eight weeks before the Facebook IPO glitch
- [ ] D. NASDAQ's IPO cross software defect delayed Facebook's opening trade by roughly 30 minutes
- [ ] E. The BATS software defect caused its own stock price to collapse within under a second and briefly disrupted trading in unrelated symbols

### 14. Regulation SCI and trade reporting
- [ ] A. Trade-reporting obligations do not exist for off-exchange or dark-pool executions
- [ ] B. Derivatives trades are typically reported to a Trade Repository only if both counterparties are US-based
- [ ] C. MiFID II allows unlimited reporting delay for all instrument types, regardless of liquidity
- [ ] D. Regulation SCI requires covered market infrastructure to maintain capacity/resilience and report significant systems issues to regulators
- [ ] E. Off-exchange US trades must be reported to a FINRA facility within 10 minutes of execution

### 15. Incident command
- [ ] A. A dead-man's-switch/heartbeat alert is designed to fire when expected signals stop arriving, catching silently-failed telemetry
- [ ] B. A blameless postmortem focuses on recording a timeline and improving systems/processes rather than assigning individual blame
- [ ] C. Paging and ticketing are treated as identical urgency levels, requiring the same immediate human response
- [ ] D. MTTD measures the time it takes to fully resolve an incident, while MTTR measures only detection time
- [ ] E. An Incident Commander coordinates and makes decisions during an incident, distinct from a communications lead who keeps stakeholders informed

### 16. Index divisors and free float
- [ ] A. Passive index funds' contractually obligatory buying on an index-reconstitution date is one hazard cited around index-inclusion events
- [ ] B. Most serious modern indexes count a company's full market capitalization, including founder and government-held blocks, without any free-float adjustment
- [ ] C. In a price-weighted index like the DJIA, a higher-priced stock moves the index more than a lower-priced one, regardless of the two companies' relative sizes
- [ ] D. An index's divisor is deliberately set at launch, partly so the index reads at a convenient, friendly base value
- [ ] E. When a company in a market-cap-weighted index undergoes a stock split, the divisor must be rescaled to prevent an artificial jump in the index level

### 17. Settlement mechanics
- [ ] A. Some instruments, including many money-market instruments and some US Treasury trades, already settle on the trade date (T+0)
- [ ] B. Settlement failures can never occur once a trade has matched successfully in the order book
- [ ] C. DTCC's Depository Trust Company performs settlement exclusively through physical paper certificates today
- [ ] D. US equity settlement has progressively shortened over time, from T+5 to T+1
- [ ] E. A buy-in occurs when a seller purchases replacement shares in the open market at the buyer's expense

### 18. VWAP and P&L
- [ ] A. VWAP calculations disregard trade size entirely and treat every trade as equally weighted
- [ ] B. Unrealised P&L reflects gains or losses on positions that remain open and updates continuously as prices move
- [ ] C. VWAP is the volume-weighted average price across a set of trades, weighting each trade's price by its size
- [ ] D. Realised P&L can change retroactively after a position has already been fully closed out
- [ ] E. Unrealised P&L is the figure that typically drives real-time margin calls and risk alerts, while realised P&L flows into official accounting at day's end

### 19. Pin risk and triple witching
- [ ] A. Pin risk can expose an uncovered option writer to a large loss if the underlying gaps significantly after expiry-day assignment
- [ ] B. A written call option that closes barely in-the-money at expiry can still be automatically exercised, even by a single cent
- [ ] C. Triple witching refers to three consecutive days of option expiries every month
- [ ] D. An option writer may not know with certainty whether they'll be assigned until after the final settlement print and OCC's allocation process
- [ ] E. Automatic exercise at OCC applies unless the option holder files a contrary instruction

### 20. Exercise, assignment, and allocation
- [ ] A. European-style options can be exercised at any point before expiry, just like American-style options
- [ ] B. Physical delivery is the standard settlement method for broad index options like SPX
- [ ] C. After the OCC assigns an exercise to a clearing member, the broker commonly allocates it among its short-position clients using random selection or FIFO by position age
- [ ] D. Pin risk cannot occur in any form for European-style options, since exercise only happens at expiry
- [ ] E. Assignment is the option holder's own voluntary decision to exercise their right


&nbsp;

---

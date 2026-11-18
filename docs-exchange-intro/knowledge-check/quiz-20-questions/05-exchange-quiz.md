# Exchange Concepts Knowledge Check — Variant 05
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

### 1. From coffeehouses to the electronic book
- [ ] A. Early share trading in London took place in coffeehouses such as Jonathan's, before any dedicated exchange building existed
- [ ] B. The electronic order book was introduced together with the first publicly traded shares in 1602
- [ ] C. In a candle auction, the winning bid was the loudest one shouted before the auctioneer called time
- [ ] D. The specialist's paper ledger of resting orders is the ancestor of the electronic order book
- [ ] E. NASDAQ was created after a regulator's study concluded that stale, inaccessible price information was itself a market-structure defect

### 2. The VOC and Isaac Le Maire
- [ ] A. The VOC's shares, first traded in 1602, are widely regarded as the world's first publicly traded shares
- [ ] B. Le Maire's scheme shows that short selling is centuries older than electronic trading
- [ ] C. The Dutch authorities' 1610 ban on short selling was successful and ended the practice permanently
- [ ] D. Joseph de la Vega's 1688 book about the VOC share market predates Le Maire's short-selling scheme
- [ ] E. Isaac Le Maire's 1609 short-selling scheme targeted shares of the Dutch East India Company (VOC)

### 3. The 1929 crash and the SEC's origin
- [ ] A. The DJIA fell by roughly 89% from its 1929 peak to its 1932 trough
- [ ] B. Falling prices in October 1929 triggered margin calls that forced further selling, deepening the decline in a feedback loop
- [ ] C. The US stock market roughly doubled between 1928 and September 1929, fueled partly by heavy margin buying
- [ ] D. The Securities Act of 1933 and the Securities Exchange Act of 1934 introduced measures like securities registration and fraud prohibition
- [ ] E. The Securities Exchange Act of 1934, which created the SEC, was passed before the 1929 crash occurred

### 4. Decimalization
- [ ] A. Rule 612 was adopted before decimalization occurred, to prepare markets for fractional pricing
- [ ] B. The "teenie" refers to a tick size of exactly one full dollar
- [ ] C. US markets fully converted from fractional pricing (eighths/sixteenths) to decimal pricing by around April 2001
- [ ] D. Decimalization caused quoted spreads on liquid stocks to roughly double
- [ ] E. NYSE traded in decimals from its founding in 1792

### 5. IPO pricing and share counts
- [ ] A. Market capitalisation equals the share price multiplied by the number of shares outstanding
- [ ] B. A company valued at $1.77 trillion at an IPO price of $135 a share has roughly 13.1 billion shares
- [ ] C. When an IPO jumps on its first day, the gain above the offer price goes to the company that issued the shares
- [ ] D. The 1923 "blue chip" threshold of $200 a share is still a formal requirement for premium listing tiers
- [ ] E. A mega-IPO priced below $200 a share says nothing about the company's size, because the share count is largely chosen by the company and its underwriters

### 6. Underwriting and dilution
- [ ] A. Dilution has no bearing on a founder's percentage ownership of a company, only on total share count
- [ ] B. In underwriting, investment banks guarantee to buy all IPO shares at a set price and then resell them, typically without actually getting stuck holding the shares
- [ ] C. A roadshow is a series of presentations to large institutional investors used to gauge demand and help set the final IPO price
- [ ] D. In an IPO, proceeds from newly created shares go to the company, while proceeds from existing shares sold by early investors go to those investors
- [ ] E. Selling a 20% ownership stake to raise new capital always reduces a founder's absolute dollar ownership value in the company

### 7. Common vs preferred stock
- [ ] A. Venture capital investors in early-stage companies almost always receive preferred stock rather than common stock
- [ ] B. On an IPO, most preferred shares typically convert to common shares
- [ ] C. Preferred shares, when listed, always trade under the exact same ticker as the common shares
- [ ] D. Preferred stock typically carries the same voting rights as common stock
- [ ] E. Preferred stockholders are typically paid after common stockholders in a liquidation

### 8. Borrow and locate mechanics
- [ ] A. Borrow rates for hard-to-borrow, thinly traded stocks can run well above zero, sometimes into double digits annually
- [ ] B. A short seller must arrange to borrow shares through a locate process before selling shares they do not own
- [ ] C. Naked short selling, meaning selling short without a locate, is generally illegal under Regulation SHO
- [ ] D. A share lender can never recall their loaned shares once a short position is open, regardless of circumstances
- [ ] E. The exchange's matching engine treats a short sale exactly like any other sell order at the point of matching

### 9. Settlement history
- [ ] A. T+1 settlement was adopted in the US before T+2
- [ ] B. The "T+N" notation stopped being used once settlement periods shortened below three days
- [ ] C. Settlement periods lengthened over time as electronic processing became more common
- [ ] D. Same-day (T+0) settlement is already the universal standard across all US markets today
- [ ] E. US equity settlement historically took multiple days in the paper-certificate era, mainly because of physical logistics like messengers moving documents between firms

### 10. IEX and Flash Boys
- [ ] A. Michael Lewis's book Flash Boys focused on IEX and the broader debate over high-frequency trading's speed advantages
- [ ] B. IEX quickly captured the majority of total US equity trading volume once it launched
- [ ] C. Speed bumps eliminate all relative timing differences between orders arriving microseconds apart
- [ ] D. IEX's speed bump imposes a fixed 350-microsecond delay using coiled fiber-optic cable
- [ ] E. IEX began as a dark pool before becoming a registered national securities exchange in 2016

### 11. Sequence numbers, gap recovery, and drop copy
- [ ] A. A subscriber that detects a gap can request retransmission of the missing messages via a separate channel
- [ ] B. Gap recovery is a standard operational concern across both order-lifecycle drop-copy feeds and public market-data feeds
- [ ] C. Sequence numbers let a subscriber detect that a message was missed when numbers are not consecutive
- [ ] D. Drop copy can help satisfy real-time monitoring obligations under rules like the US Market Access Rule
- [ ] E. Drop copy is broadcast publicly as part of the market-data feed

### 12. Warm restart vs cold start
- [ ] A. Snapshots eliminate the need for a write-ahead log entirely
- [ ] B. Deterministic matching requires eliminating hidden non-determinism sources, such as unlogged system clock reads mid-execution
- [ ] C. A warm restart, using a recent snapshot plus WAL replay, typically completes in seconds, while a cold start replaying the entire day takes considerably longer
- [ ] D. GTC order persistence relies solely on the write-ahead log, with no separate persistence layer
- [ ] E. The write-ahead log is written only after an order has already been processed and matched, never before

### 13. SBE, STPF, and quotes vs orders
- [ ] A. SBE messages are generally faster to decode than equivalent text-based FIX messages, contributing to microsecond order-submission times
- [ ] B. Quote IDs and the order IDs generated from a quote are always required to be identical
- [ ] C. SBE (Simple Binary Encoding) uses fixed-length, predictable schema fields, so an engine can locate data like an STPF ID without parsing text
- [ ] D. Some venues allow a self-match-prevention ID to be shared and recognized across multiple executing brokers
- [ ] E. A market maker's quote is a single instruction that can generate two linked order legs, one for the bid and one for the ask

### 14. Novation
- [ ] A. Novation eliminates the CCP's own need for a guarantee fund or margin requirements
- [ ] B. Novation only applies to futures contracts and never to equities
- [ ] C. Novation increases each trading party's direct counterparty exposure to the other original party
- [ ] D. Novation is the process by which a central counterparty steps between buyer and seller, so each faces the CCP rather than each other
- [ ] E. Novation is a settlement-layer concept unrelated to clearing

### 15. Auction equilibrium price, revisited
- [ ] A. When more than one price yields the same maximum executable volume, the auction algorithm has no consistent way to break the tie and must fail
- [ ] B. Indicative uncross prices are calculated once, at the very start of the pre-open period, and never updated again
- [ ] C. A buyer whose limit order bid above the eventual equilibrium price still pays only the equilibrium price, not their higher bid
- [ ] D. In an opening auction, the price that maximizes the executable volume — defined as the minimum of cumulative bids at or above that price and cumulative asks at or below it — is chosen as the equilibrium price
- [ ] E. Orders unmatched by the auction transition into the continuous trading book once it opens

### 16. Tick rounding, worked example
- [ ] A. Common rounding conventions mentioned in the book include round-half-up and round-half-to-even ("banker's rounding")
- [ ] B. Storing prices as integer tick counts rather than floating-point numbers helps avoid binary floating-point representation errors
- [ ] C. Exchanges are free to let each internal system apply its own independent rounding convention, as long as the final trade price is close enough
- [ ] D. Even a one-tick spread always produces a midpoint that falls between two valid ticks
- [ ] E. A midpoint price needing rounding to a valid tick typically arises when the bid and ask are an odd number of ticks apart

### 17. FIX tags and binary order-entry protocols
- [ ] A. CME's MDP3 protocol requires heap allocation for every message it parses, making it slower than FIX
- [ ] B. In FIX, tag 54 commonly represents the order's side, where 1 means buy and 2 means sell
- [ ] C. NASDAQ OUCH order-entry messages are typically transmitted over TCP rather than UDP for reliability
- [ ] D. FIX messages are delimited on the wire using a literal pipe character "|"
- [ ] E. NASDAQ's OUCH protocol is used for publishing market data, while ITCH is used for order submission

### 18. The consolidated tape and market-data governance
- [ ] A. SIP governance and pricing decisions are made by the same exchange companies that also sell competing proprietary data feeds
- [ ] B. Consolidated market-data fees have never been a subject of regulatory or industry debate in Europe
- [ ] C. The SEC's 2020 market-data-infrastructure rulemaking expanded SIP content to include more round-lot depth-of-book and odd-lot detail
- [ ] D. The SEC's market-data-infrastructure changes were contested through litigation and still evolving as of the book's writing
- [ ] E. A single mandated consolidated tape existed across all EU trading venues from MiFID II's very first day in force

### 19. Reg NMS, crossed markets, and fee models
- [ ] A. Inverted (taker-maker) fee models charge the aggressor a fee and pay the resting order a rebate
- [ ] B. A crossed market, where one venue's bid exceeds another venue's ask, represents a genuine, if fleeting, risk-free arbitrage opportunity
- [ ] C. Maker-taker fee models pay a rebate to resting "maker" orders and charge a fee to aggressive "taker" orders
- [ ] D. Reg NMS's best-price mandate is a key reason smart order routing exists as standard infrastructure among US brokers
- [ ] E. Best-execution obligations under rules like MiFID II and FINRA Rule 5310 consider factors beyond price alone, such as cost, speed, and likelihood of execution

### 20. Exchange demutualization
- [ ] A. Demutualization had no effect on an exchange's incentive structure or technology-investment decisions
- [ ] B. Demutualization occurred primarily in ancient, pre-20th-century financial history
- [ ] C. Exchanges are always for-profit entities and have never operated as non-profit, member-owned organizations
- [ ] D. A demutualized exchange can no longer list its own shares on any stock exchange
- [ ] E. Demutualization refers to a member-owned exchange converting into a for-profit, publicly listed company


&nbsp;

---

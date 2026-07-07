# Exchange Concepts Knowledge Check — Variant 05

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

### 1. Coffeehouse origins of the exchange
- [ ] A. Jonathan's Coffee House is described as a forerunner to the London Stock Exchange and a primary gathering place for early stockbrokers
- [ ] B. Garraway's Coffee House specialized in commodities and hosted an early fur auction for the Hudson's Bay Company
- [ ] C. A 1748 fire in Cornhill destroyed the original coffeehouses and pushed markets toward formal, dedicated buildings
- [ ] D. Candle auctions determined the winning bid by whoever shouted loudest before the auctioneer called time
- [ ] E. Garraway's was the first place in France to retail tea

### 2. The VOC and Isaac Le Maire
- [ ] A. Isaac Le Maire's 1609 short-selling scheme targeted shares of the Dutch East India Company (VOC)
- [ ] B. The Amsterdam city council's attempt to ban short selling in 1610 was successful and ended the practice permanently
- [ ] C. The VOC issued the world's first publicly traded shares, in 1602
- [ ] D. Le Maire's operation is generally cited as a single, isolated short sale involving one share
- [ ] E. Joseph de la Vega's 1688 book about the VOC share market predates Le Maire's short-selling scheme

### 3. The 1929 crash and the SEC's origin
- [ ] A. The US stock market roughly doubled between 1928 and September 1929, fueled partly by heavy margin buying
- [ ] B. Falling prices in October 1929 triggered margin calls that forced further selling, deepening the decline in a feedback loop
- [ ] C. The DJIA fell by roughly 89% from its 1929 peak to its 1932 trough
- [ ] D. The Securities Exchange Act of 1934, which created the SEC, was passed before the 1929 crash occurred
- [ ] E. The Securities Act of 1933 and the Securities Exchange Act of 1934 introduced measures like securities registration and fraud prohibition

### 4. Decimalization
- [ ] A. US markets fully converted from fractional pricing (eighths/sixteenths) to decimal pricing by around April 2001
- [ ] B. NYSE traded in decimals from its founding in 1792
- [ ] C. Decimalization caused quoted spreads on liquid stocks to roughly double
- [ ] D. The "teenie" refers to a tick size of exactly one full dollar
- [ ] E. Rule 612 was adopted before decimalization occurred, to prepare markets for fractional pricing

### 5. Landmark IPOs
- [ ] A. Saudi Aramco's 2019 IPO on the Saudi Exchange raised billions of dollars, among the largest IPOs by proceeds in the book's examples
- [ ] B. Alibaba's 2014 IPO took place on the NYSE
- [ ] C. Arm Holdings' IPO took place on NASDAQ in 2023
- [ ] D. The book notes that a mega-IPO's per-share price below $200 says nothing about a company's quality or size, since share count is set largely at the underwriters' and company's discretion
- [ ] E. Oliver Gingold's original 1923 "blue chip" $200 threshold was a nominal, era-specific figure that was never formally adjusted for inflation or turned into a rule

### 6. Underwriting and dilution
- [ ] A. In underwriting, investment banks guarantee to buy all IPO shares at a set price and then resell them, typically without actually getting stuck holding the shares
- [ ] B. A roadshow is a series of presentations to large institutional investors used to gauge demand and help set the final IPO price
- [ ] C. Selling a 20% ownership stake to raise new capital always reduces a founder's absolute dollar ownership value in the company
- [ ] D. In an IPO, new shares are created and the proceeds go to the company or to early investors who are cashing out
- [ ] E. Dilution has no bearing on a founder's percentage ownership of a company, only on total share count

### 7. Common vs preferred stock
- [ ] A. Preferred stockholders are typically paid after common stockholders in a liquidation
- [ ] B. Venture capital investors in early-stage companies almost always receive preferred stock rather than common stock
- [ ] C. Preferred stock typically carries the same voting rights as common stock
- [ ] D. On an IPO, most preferred shares typically convert to common shares
- [ ] E. Preferred shares, when listed, always trade under the exact same ticker as the common shares

### 8. Borrow and locate mechanics
- [ ] A. A short seller must arrange to borrow shares through a locate process before selling shares they do not own
- [ ] B. Naked short selling, meaning selling short without a locate, is generally illegal under Regulation SHO
- [ ] C. Borrow rates for hard-to-borrow, thinly traded stocks can run well above zero, sometimes into double digits annually
- [ ] D. A share lender can never recall their loaned shares once a short position is open, regardless of circumstances
- [ ] E. The exchange's matching engine treats a short sale exactly like any other sell order at the point of matching

### 9. Settlement history
- [ ] A. US equity settlement historically took multiple days in the paper-certificate era, mainly because of physical logistics like messengers moving documents between firms
- [ ] B. T+1 settlement was adopted in the US before T+2
- [ ] C. Same-day (T+0) settlement is already the universal standard across all US markets today
- [ ] D. The "T+N" notation stopped being used once settlement periods shortened below three days
- [ ] E. Settlement periods lengthened over time as electronic processing became more common

### 10. IEX and Flash Boys
- [ ] A. IEX began as a dark pool before becoming a registered national securities exchange in 2016
- [ ] B. IEX's speed bump imposes a fixed 350-microsecond delay using coiled fiber-optic cable
- [ ] C. IEX quickly captured the majority of total US equity trading volume once it launched
- [ ] D. Michael Lewis's book Flash Boys focused on IEX and the broader debate over high-frequency trading's speed advantages
- [ ] E. Speed bumps eliminate all relative timing differences between orders arriving microseconds apart

### 11. Sequence numbers, gap recovery, and drop copy
- [ ] A. Sequence numbers let a subscriber detect that a message was missed when numbers are not consecutive
- [ ] B. A subscriber that detects a gap can request retransmission of the missing messages via a separate channel
- [ ] C. Drop copy is a private, participant-specific record, distinct from the publicly distributed market-data feed
- [ ] D. Drop copy can help satisfy real-time monitoring obligations under rules like the US Market Access Rule
- [ ] E. Gap recovery is a standard operational concern across both order-lifecycle drop-copy feeds and public market-data feeds

### 12. Warm restart vs cold start
- [ ] A. A warm restart, using a recent snapshot plus WAL replay, typically completes in seconds, while a cold start replaying the entire day takes considerably longer
- [ ] B. The write-ahead log is written only after an order has already been processed and matched, never before
- [ ] C. Snapshots eliminate the need for a write-ahead log entirely
- [ ] D. GTC order persistence relies solely on the write-ahead log, with no separate persistence layer
- [ ] E. Deterministic matching requires eliminating hidden non-determinism sources, such as unlogged system clock reads mid-execution

### 13. SBE, STPF, and quotes vs orders
- [ ] A. SBE (Simple Binary Encoding) uses fixed-length, predictable schema fields, so an engine can locate data like an STPF ID without parsing text
- [ ] B. SBE messages are generally faster to decode than equivalent text-based FIX messages, contributing to microsecond order-submission times
- [ ] C. A market maker's quote is a single instruction that can generate two linked order legs, one for the bid and one for the ask
- [ ] D. Quote IDs and the order IDs generated from a quote are always required to be identical
- [ ] E. Cross-broker SMP-tagging standards can allow a self-match-prevention ID to be shared and recognized across multiple brokers

### 14. Novation
- [ ] A. Novation is the process by which a central counterparty steps between buyer and seller, so each faces the CCP rather than each other
- [ ] B. Novation increases each trading party's direct counterparty exposure to the other original party
- [ ] C. Novation is a settlement-layer concept unrelated to clearing
- [ ] D. Novation only applies to futures contracts and never to equities
- [ ] E. Novation eliminates the CCP's own need for a guarantee fund or margin requirements

### 15. Auction equilibrium price, revisited
- [ ] A. In an opening auction, the price that maximizes the executable volume — defined as the minimum of cumulative bids at or above that price and cumulative asks at or below it — is chosen as the equilibrium price
- [ ] B. A buyer whose limit order bid above the eventual equilibrium price still pays only the equilibrium price, not their higher bid
- [ ] C. When more than one price yields the same maximum executable volume, the auction algorithm has no consistent way to break the tie and must fail
- [ ] D. Orders unmatched by the auction transition into the continuous trading book once it opens
- [ ] E. Indicative uncross prices are calculated once, at the very start of the pre-open period, and never updated again

### 16. Tick rounding, worked example
- [ ] A. A midpoint price needing rounding to a valid tick typically arises when the bid and ask are an odd number of ticks apart
- [ ] B. Even the tightest possible one-tick spread can still require midpoint rounding, depending on the parity of the tick-count sum
- [ ] C. Common rounding conventions mentioned in the book include round-half-up and round-half-to-even ("banker's rounding")
- [ ] D. Exchanges are free to let each internal system apply its own independent rounding convention, as long as the final trade price is close enough
- [ ] E. Storing prices as integer tick counts rather than floating-point numbers helps avoid binary floating-point representation errors

### 17. FIX tags and binary order-entry protocols
- [ ] A. In FIX, tag 54 commonly represents the order's side, where 1 means buy and 2 means sell
- [ ] B. NASDAQ's OUCH protocol is used for publishing market data, while ITCH is used for order submission
- [ ] C. NASDAQ OUCH order-entry messages are typically transmitted over TCP rather than UDP for reliability
- [ ] D. FIX messages are delimited on the wire using a literal pipe character "|"
- [ ] E. CME's MDP3 protocol requires heap allocation for every message it parses, making it slower than FIX

### 18. The consolidated tape and market-data governance
- [ ] A. The SEC's 2020 market-data-infrastructure rulemaking expanded SIP content to include more round-lot depth-of-book and odd-lot detail
- [ ] B. A single mandated consolidated tape existed across all EU trading venues from MiFID II's very first day in force
- [ ] C. The SEC's market-data-infrastructure changes were contested through litigation and still evolving as of the book's writing
- [ ] D. SIP governance and pricing decisions are made by the same exchange companies that also sell competing proprietary data feeds
- [ ] E. Consolidated market-data fees have never been a subject of regulatory or industry debate in Europe

### 19. Reg NMS, crossed markets, and fee models
- [ ] A. Reg NMS's best-price mandate is a key reason smart order routing exists as standard infrastructure among US brokers
- [ ] B. A crossed market, where one venue's bid exceeds another venue's ask, represents a genuine, if fleeting, risk-free arbitrage opportunity
- [ ] C. Maker-taker fee models pay a rebate to resting "maker" orders and charge a fee to aggressive "taker" orders
- [ ] D. Inverted (taker-maker) fee models reverse these incentives, charging the resting order and rebating the aggressor
- [ ] E. Best-execution obligations under rules like MiFID II and FINRA Rule 5310 consider factors beyond price alone, such as cost, speed, and likelihood of execution

### 20. Exchange demutualization
- [ ] A. Exchanges are always for-profit entities and have never operated as non-profit, member-owned organizations
- [ ] B. Demutualization refers to a member-owned exchange converting into a for-profit, publicly listed company
- [ ] C. A demutualized exchange can no longer list its own shares on any stock exchange
- [ ] D. Demutualization occurred primarily in ancient, pre-20th-century financial history
- [ ] E. Demutualization had no effect on an exchange's incentive structure or technology-investment decisions


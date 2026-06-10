
# Glossary

The following definitions are written to be concise and standalone, useful as a quick reference after reading the document.

```{=latex}
\setcounter{secnumdepth}{1}
\renewcommand{\thesection}{}
```

## A {#glossary-a}

**Adverse Selection:** The risk a market maker faces when their quote is hit by a counterparty who has superior information about where prices are heading, causing the market maker to trade at a price that will quickly move against them. A market maker who is repeatedly adversely selected will lose money even while quoting at "correct" prices. MMP exists specifically to limit adverse selection damage.

**Aggressor / Taker:** The participant whose incoming order triggered a match by crossing the spread to meet a resting order. The aggressor "takes" liquidity that was already available. Contrast with *Maker*, the participant whose resting order was already in the book.

**Alternative Trading System (ATS):** A trading venue that matches orders but is not a registered national securities exchange. Includes ECNs and dark pools. Subject to lighter regulation than exchanges in some jurisdictions.

**Arbitrage:** The simultaneous purchase and sale of the same (or equivalent) asset on different markets to profit from a price difference. Pure arbitrage is risk-free (buy cheap here, sell expensive there at the same moment); in practice, most arbitrage involves some timing or execution risk. Arbitrage is the mechanism by which prices on different venues are kept consistent, arbitrageurs quickly eliminate price discrepancies, making markets more efficient. **Latency arbitrage** is a specific form exploiting the time it takes for price changes to propagate between venues.

**Ask / Offer:** The price at which a seller is willing to sell. The best (lowest) ask is the top of the sell side of the order book.

**ATC (At-The-Close):** An order TIF valid only during the closing auction.

**ATO (At-The-Open):** An order TIF valid only during the opening auction.

**Auction / Call Auction / Uncross / Fixing:** A trading mechanism where orders are collected over a period and then matched simultaneously at a single equilibrium price. Contrasts with continuous matching where orders match one at a time as they arrive.

**Auction Imbalance:** The excess of buy orders over sell orders (or vice versa) at the indicative uncross price during an auction. Published by exchanges to encourage offsetting orders before uncrossing.

**Audit Trail:** The complete, immutable, time-ordered record of every event in the exchange system, every order, fill, cancellation, and rejection, with precise timestamps. Required for regulatory reporting and replay-based recovery.


## B {#glossary-b}

**Basis:** In derivatives and futures markets, the price difference between two related instruments, most commonly between the spot/cash price and a futures price on the same underlying, or between two futures contracts with different expiry dates. In the implied order example in this document (the *Order Types* section of Part II), the spread price of −$2 between the January and February WTI contracts is the basis between those two contract months: January is $2 cheaper than February. The basis is not fixed; it changes continuously as supply and demand for the near and far months evolve independently. **Basis risk** is the risk that the expected relationship between two instruments diverges unexpectedly, a spread trader who expected the two legs to move together may find they do not, leaving an unintended net exposure. See *Implied Order*, *Calendar Spread*.

**Bear Market:** A sustained decline of 20% or more from a recent market peak. Originates from the image of a bear swiping its paws downward. Contrast with *Bull Market*.

**Best Execution:** The regulatory obligation for brokers and investment firms to take all reasonable steps to achieve the best possible result for their clients when executing orders. "Best" considers price, execution costs, speed, likelihood of execution, and market impact simultaneously, not just the quoted price in isolation. Mandated by MiFID II in the EU and the SEC's duty of best execution in the US. Best execution is the regulatory foundation that makes smart order routing (SOR) necessary: brokers must demonstrate their routing decisions genuinely serve clients' interests, not just the broker's economics.

**Bid:** The price at which a buyer is willing to buy. The best (highest) bid is the top of the buy side of the order book.

**Bid-Ask Imbalance:** A measure of depth asymmetry: bid_depth / (bid_depth + ask_depth), computed within a symmetric price window around the mid. Values near 1 indicate heavy buying interest; values near 0 indicate heavy selling interest. Used as a short-term price direction signal.

**Blue Chip:** A large, financially sound, well-established company, the most prestigious tier of the equity market. The term originates from poker, where blue chips represent the highest denomination.

**Bond:** A standardised debt instrument. The issuing company borrows money and promises to pay periodic interest (coupon payments) and return the face value (principal) at maturity. Bondholders are creditors, not owners, and are paid before equity holders in a bankruptcy. Bonds trade on secondary markets after issuance, allowing investors to exit before maturity. The financial term "bond" traces its roots back to the 14th century from the Old English word bindan and band, which eventually evolved into the standard English word "bind". The word was originally used to describe something that literally ties, fastens, or holds things together. Because a financial bond fundamentally operates as a formal, legally binding contract where an issuer promises to repay a loan with interest, the term stuck.

**Book Snapshot:** A periodic complete view of the current order book state (all price levels and their quantities) published by the exchange for subscribers who need to get up to speed.

**Borrow Rate:** The annualised fee charged to a short seller for borrowing shares from a lender. Easy-to-borrow large-cap stocks typically have borrow rates near zero. Hard-to-borrow, heavily-shorted, or illiquid stocks can carry rates of 5–50% or more per annum, applied daily to the short position. Rising borrow rates signal increasing short interest and decreasing availability of lendable shares, and are themselves a market signal.

**Broker:** An intermediary who executes orders on behalf of clients without trading for their own account. The word traces to Old French/Norse roots meaning someone who opens a cask and sells by the cup, a retail intermediary.

**Bull Market:** A sustained rise of 20% or more from a recent market trough. Originates from the image of a bull thrusting its horns upward. Contrast with *Bear Market*.

**Buy-In:** A remedy for failed settlement: if a seller cannot deliver securities, the buyer purchases them in the open market at the seller's expense.


## C {#glossary-c}

**Calendar Spread:** A derivatives strategy involving the simultaneous purchase and sale of contracts on the same underlying instrument but with different expiry dates, for example, buy the March futures contract, sell the June futures contract. Used to profit from expected changes in the price difference (the "spread") between contract months. Requires cross-symbol coordination in the matching engine.

**Capital Appreciation:** An increase in the market price of a share (or other asset) above the price paid. The primary way equity investors generate returns.

**Capital Gain:** The profit realised when an asset is sold for more than it was purchased for.

**CCP (Central Counterparty Clearing House):** An entity that stands between buyer and seller in a trade, becoming the legal counterparty to both, eliminating direct counterparty credit risk.

**Circuit Breaker:** An automatic trading halt triggered when price movement exceeds a threshold within a time window, designed to prevent cascading automated trading crashes.

**Clearing:** The process of confirming and recording a trade, and (via a CCP) guaranteeing its settlement.

**Co-location:** Placing a participant's trading servers physically inside the same data centre as the exchange's matching engine, minimising network round-trip latency to microseconds.

**Collar Band / Price Collar:** A price filter that rejects orders whose submitted price deviates too far from a reference price. Two distinct variants: the *static price collar* (compares against the last close) and the *dynamic price collar* (compares against the last trade). See those entries for details.

**Combo Order:** A single instruction to execute orders in multiple instruments simultaneously. Each component is a leg.

**Conflation (Market Data):** Merging consecutive market data updates for the same price level into a single message under high-load conditions. Reduces message volume at the cost of losing intermediate states.

**Continuous Trading:** The normal trading mode where orders match as soon as they arrive and a compatible counterparty is present. Contrasts with auction mode.

**Contract Multiplier:** For futures and options, the dollar (or other currency) value of a one-unit price move per contract. The E-mini S&P 500 has a multiplier of $50, a 1-point move in the index is worth $50 per contract. Essential reference data: a wrong multiplier affects every P&L and margin calculation.

**Corporate Action:** An event affecting a company's share structure, stock splits, dividends, mergers, delistings. Requires adjustments to all open orders, positions, and reference data in exchange systems.

**Counterparty Risk:** The risk that the other party to a trade defaults before settlement is complete. Cleared via CCP novation, which replaces bilateral counterparty risk with exposure to the CCP.

**Coupon:** The periodic interest payment on a bond. Named after the physical coupon strips that bond holders historically detached and redeemed for payment.

**Crossing the Spread:** Submitting an order at a price that matches an existing resting order, triggering an immediate fill.

**Cum-Dividend:** The period during which a share trades *with* entitlement to a declared dividend, the buyer receives the upcoming payment. A share trades cum-dividend from the dividend announcement up to (but not including) the ex-dividend date. After the ex-dividend date the share trades *ex-dividend* and the buyer is not entitled to the payment. The price typically drops by approximately the dividend amount on the ex-dividend date.

**CUSIP:** A 9-character identifier for US and Canadian securities used in clearing and settlement. Analogous to ISIN.

**Custody:** The safekeeping of securities on behalf of investors by a broker or custodian bank, with records maintained at a central securities depository.


## D {#glossary-d}

**Dark Fibre:** Unused optical fibre cable already laid in the ground but not yet carrying data traffic ("lit"). Trading firms and data providers lease dark fibre from infrastructure companies and run their own optical transceivers, creating private, dedicated network links between financial data centres. Dark fibre links are used between major exchange co-location sites (e.g., NYSE in Mahwah and NASDAQ in Carteret) to reduce cross-venue latency for arbitrage and hedging strategies.

**Dark Pool:** A private trading venue where orders are not displayed in a public order book. Participants submit orders and are matched against other participants' orders, typically at the midpoint of the NBBO, with the trade only reported publicly after it occurs. Used by large institutional investors to trade without revealing their intentions and causing adverse price movement. Contrast with *lit markets* (public exchanges) where resting orders are visible to all. See *Regulatory Surveillance*.

**DAY:** An order TIF valid only for the current trading session.

**Delivery versus Payment (DvP):** The settlement principle that the transfer of securities and cash happen simultaneously and conditionally, neither is released without the other. Eliminates principal risk in settlement.

**Depth (Market Depth):** The total quantity of resting orders available at each price level. Deep markets can absorb large orders with minimal price impact.

**Depth-of-Book (Level 2):** Market data showing multiple price levels and their resting quantities, rather than only the best bid and ask.

**Designated Market Maker (DMM):** A firm assigned by an exchange to maintain fair and orderly markets in specific securities, with both privileges and obligations. NYSE's term; Nasdaq calls them Market Makers.

**Determinism (Exchange):** The property that given the same initial state and the same ordered input messages, the matching engine always produces identical outputs. Essential for audit trail replay and disaster recovery.

**Dilution:** The reduction in existing shareholders' ownership percentage when new shares are issued. Selling 20% of a company to new investors reduces existing owners to 80%.

**Dividend:** A cash payment made by a company to its shareholders, distributed from retained profits. Not guaranteed, the board of directors decides whether, when, and how much to pay. Companies that pay regular dividends are typically mature, profitable businesses with stable cash flows. High-growth companies often pay no dividend, choosing to reinvest profits in expansion. The key dates are: the *declaration date* (when the board announces the dividend), the *ex-dividend date* (buyers on or after this date do not receive the payment), the *record date* (the register of shareholders eligible to receive payment), and the *payment date* (when the cash is distributed).

**Drop Copy:** A real-time copy of all order lifecycle events for a specific participant, sent to a designated third party such as a clearing broker or risk system.

**DTCC (Depository Trust and Clearing Corporation):** The central clearing and settlement infrastructure for US equity markets. Its subsidiary DTC is the US central securities depository.

**Dynamic Price Collar (Reference Price Filter):** A pre-trade risk control that rejects any order whose submitted price deviates more than a configured percentage from the most recent traded price. Protects against algorithms that walk the price incrementally through a series of small trades. Contrast with *Static Price Collar*, which uses the last close as the reference. Together, the two collars provide overlapping protection against both sudden errors and gradual drift.


## E {#glossary-e}

**ECN (Electronic Communication Network):** An electronic trading system that automatically matches buy and sell orders, typically with narrower spreads than exchanges but less regulatory oversight.

**Equilibrium Price (Auction Price):** The single price at which the maximum volume can trade in a call auction.

**Equity:** Ownership stake in a company. Equity holders (shareholders) have a residual claim on the company's assets and earnings after all creditors are paid.

**ETF (Exchange-Traded Fund):** A basket of securities (shares, bonds, commodities) that itself trades as a single share on an exchange.

**Ex-Dividend Date:** The date from which a stock trades without entitlement to a declared dividend. Buyers on or after this date do not receive the dividend.

**Execution Algorithm (Algo):** Software that breaks a large institutional order into smaller pieces and executes them over time to minimise market impact and achieve a target average price. Common types include VWAP (match the day's volume-weighted average price), TWAP (distribute uniformly over time), Implementation Shortfall (minimise the gap between decision price and execution price), and POV/In-Line (participate at a fixed percentage of market volume). Execution algorithms generate the majority of order flow on modern exchanges.


## F {#glossary-f}

**Face Value (Bond):** The principal amount of a bond, the amount the issuer promises to repay at maturity, and the basis on which coupon payments are calculated.

**Failover:** The process of switching from a failed primary system to a secondary (backup) system.

**Fat Finger:** Industry slang for an accidental trading error caused by mistyping an order parameter (quantity, price, etc.).

**FIFO (First-In, First-Out):** Within a price level, orders are filled in the order they arrived. Earlier arrivals have priority.

**Fill:** An execution, a match between a buy and sell order resulting in a trade. Partial fills consume part of an order; a complete fill consumes all of it.

**Fill-Or-Kill (FOK):** An order that must be completely filled immediately or cancelled entirely.

**FIX (Financial Information eXchange):** The industry-standard protocol for electronic order submission, used by most exchanges and brokers globally.

**Floor Broker:** Historically, a broker who executed trades on the physical exchange floor. The term persists in regulations and informal speech.

**FPGA (Field-Programmable Gate Array):** Reconfigurable hardware chips that can implement market data parsing or order routing in dedicated logic circuits, achieving nanosecond-level latency.

**Front Running:** Acting on advance knowledge of a pending client order to trade for one's own account before executing the client's order, then profiting from the price movement the client's order causes. Illegal under market manipulation regulations and a serious breach of fiduciary duty. Front running is detected by surveillance systems that flag cases where a participant's own trades immediately precede large client executions in the same direction.

**Futures Contract:** A standardised agreement to buy or sell a specified quantity of an underlying asset (commodity, index, currency, interest rate) at a predetermined price on a specified future date. Obligations are legally binding. Futures are exchange-traded, margined, and marked-to-market daily. Unlike equity ownership, futures do not represent ownership of an underlying asset, they represent an obligation about a future transaction.


## G {#glossary-g}

**Gap (Market Data):** A missing sequence number in a market data feed, indicating a lost message. Subscribers must request retransmission or resynchronise from the next full snapshot.

**Gateway:** The participant-facing interface to the exchange. Handles authentication, session management, and message translation.

**Going Long:** Owning an asset in expectation that its price will rise, so it can be sold later at a profit. You are "long" the asset. The term originates in physical commodity trading: a merchant who had purchased durable goods, grain, spices, metal, cloth, and was holding them in a warehouse was described as "long" in those goods. The word captured both *possession* (you own something tangible) and *duration* (durable goods last a long time and can be held through seasons or years). Being long in modern finance carries exactly the same meaning: you hold the asset and are exposed to its price over time. A long position profits when the price rises and loses when it falls.

**Going Short / Short Selling:** Selling an asset you do not currently own, typically by borrowing it from another party, with the intention of buying it back later at a lower price and returning it, pocketing the difference. The term originates in physical commodity trading: a merchant who had sold goods they did not yet possess, committing to deliver more than their warehouse held, was "short" of the goods. The same word family as "falling short," "short of supplies," or "shortage", deficient, insufficient, lacking. In the early forward markets of Amsterdam and London, a short seller would sell forward (promise future delivery), then purchase the goods in the market before delivery, hoping prices had fallen. Isaac Le Maire's 1609 campaign against VOC shares is the earliest recorded large-scale short selling operation. Today, a short position profits when the price falls (you buy back cheaper than you sold) and loses when it rises, in theory without limit, since a rising price has no ceiling.

**GTC (Good-Till-Cancelled):** An order TIF that persists across trading sessions until filled or cancelled.

**GTD (Good-Till-Date):** An order Time-In-Force variant that keeps an order active until it fills, is explicitly cancelled, or reaches a specified expiry date, whichever comes first. On the expiry date the order is automatically cancelled. Provides the persistence of GTC without the open-ended risk of an order remaining active indefinitely. Requires the exchange scheduler to track each GTD order's expiry and issue the cancellation at the right time.


## H {#glossary-h}

**Heap:** A data structure that gives O(1) access to the minimum (or maximum) element. Used in matching engines to efficiently maintain best price access.

**High-Frequency Trading (HFT):** Automated trading strategies that execute very large numbers of orders at extremely high speeds, typically holding positions for milliseconds or seconds rather than minutes or days. HFT firms invest heavily in low-latency infrastructure (co-location, microwave links, FPGAs) to gain speed advantages. Strategies include latency arbitrage, market making, and statistical arbitrage. Controversial because speed advantages can disadvantage slower participants; the subject of the IEX speed bump.


## I {#glossary-i}

**Iceberg Order / Hidden Order / Reserve Order:** An order that shows only a small visible peak while hiding a large reserve. Each time the visible portion fills, the order replenishes from the reserve.

**Immediate-Or-Cancel (IOC):** An order that fills as much as possible immediately and cancels any unfilled remainder. Never rests in the book.

**Implementation Shortfall (IS) / Arrival Price Algorithm:** An execution algorithm that minimises the difference between the *decision price* (the market price when the investment decision was made) and the actual average execution price. IS algos trade faster when the price moves against the position (urgency increases to avoid further shortfall) and slower when price moves favourably. More adaptive and sophisticated than VWAP or TWAP; preferred by quantitative funds whose models predict short-term price moves.

**Implied Matching:** A technique used in derivatives markets where the exchange combines spread orders and outright orders to synthesise matches that neither could achieve alone. For example: a spread order to buy March/sell June can be combined with a resting outright June sell to create an implied March buy. Implemented on CME Globex and Eurex for calendar spreads.

**Implied Order:** An order derived by the matching engine from a combination of existing spread and outright orders. Not submitted by any participant, computed from pre-existing orders and published in the relevant outright or spread book. When an implied order matches, all contributing orders execute simultaneously. If any contributing order is cancelled or filled by other means, the implied order disappears instantly.

**Implied-In:** A form of implied matching where an outright order in one month plus a spread order imply a new outright in the other month. Example: January sell at $75 + Jan/Feb spread buy at −$2 = implied February sell at $77.

**Implied-Out:** A form of implied matching where two outright orders imply a spread. Example: January buy at $75 + February sell at $77 = implied Jan/Feb spread sell at −$2.

**Inactivation (Quote):** Automatically cancelling or suspending the surviving leg of a two-sided quote the moment the other leg is filled. The market maker must re-quote both sides afresh within their re-quoting window. Used in conservative quote refresh policies (Eurex-style). Protects the market maker from being left with a stale unhedged quote after their inventory position has changed.

**Indicative Uncross Price:** During an auction accumulation period, the price at which uncrossing *would* occur if matching happened at that moment. Recalculated after every order arrival and published as a signal to help participants decide whether to adjust their orders before the actual uncross.

**Informed Flow:** Order flow that originates from participants who have an informational advantage about near-term price direction, for example, participants who have seen relevant news before others. When a market maker is repeatedly hit by informed flow, they accumulate inventory at prices that are about to move against them. Informed flow is the root cause of adverse selection.

**Initial Margin:** Collateral deposited when opening a position to cover potential losses. Calculated by the CCP based on the instrument's historical volatility and the position size.

**Insider Trading:** Trading on material, non-public information, for example, buying shares before a publicly unannounced merger is announced. Illegal in all major jurisdictions. The exchange's audit trail is a key source of evidence in insider trading investigations, as regulators can reconstruct exactly who traded, when, and at what prices relative to when news became public.

**Instrument / Symbol:** The specific financial product being traded. Each instrument has its own order book.

**Internaliser:** A broker-dealer that matches client orders internally against its own inventory or other clients' orders, rather than routing to an exchange. A form of OTC secondary trading.

**IPO (Initial Public Offering):** The first sale of a company's shares to the general public, after which the shares are listed and traded on a stock exchange.

**ISIN (International Securities Identification Number):** A 12-character global identifier for a security, independent of the exchange it trades on. A single company has one ISIN regardless of where its shares are listed.

**ITCH (NASDAQ TotalView-ITCH):** NASDAQ's binary, message-based market data feed protocol for order book dissemination. ITCH publishes sequenced events such as add order, modify/replace, cancel/delete, executions, and auction/trade messages so subscribers can reconstruct the full limit order book deterministically from the stream. Official specification: [NASDAQ TotalView-ITCH 5.0](https://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/nasdaq_totalview_itch50.pdf).


## K {#glossary-k}

**Kernel Bypass:** Technology that allows a network application to communicate directly with network hardware, bypassing the operating system kernel and reducing latency from microseconds to sub-microsecond.

**Kill Switch:** An emergency control that immediately cancels all resting orders and quotes for a specific participant AND marks their gateway as inactive, preventing new order submission until the participant reconnects and re-authenticates. Triggered by the participant (emergency self-halt), the exchange operator, or automatically on gateway disconnect. Mandatory under most exchange regulations including MiFID II. Contrast with *Mass Cancel*, which cancels orders but leaves the gateway active.


## L {#glossary-l}

**Latency:** The time delay between an action and its effect. In exchanges, latency is measured in microseconds or nanoseconds. Low latency is a competitive advantage.

**Latency Arbitrage:** Trading that profits from the brief period between when a price changes on one venue and when that change propagates to another venue.

**Layering:** A market manipulation practice: placing large orders to create a false impression of market depth, then cancelling them once the desired price movement occurs.

**LCH:** A major international clearing house, part of the London Stock Exchange Group. Clears interest rate swaps, equities, foreign exchange, and other products.

**Leg:** One component order within a combo order or spread strategy.

**Leg Risk / Legging Risk:** The risk that one leg of a combo order fills while another does not, leaving an unintended single-instrument position.

**Level 1 Data:** The best bid and ask prices and quantities only.

**Level 2 Data (Market Depth):** The full order book, all price levels and their quantities.

**Limit Order:** An order to trade at a specified price or better. May rest in the book if not immediately matched.

**Limit Up-Limit Down (LULD):** A US regulatory circuit breaker mechanism that pauses trading in an individual stock if its price moves outside a percentage band (the "price band") calculated from a reference price. The bands are tighter for liquid large-cap stocks and wider for smaller, more volatile ones. If the best offer falls below the lower band or the best bid rises above the upper band, trading pauses for 15 seconds; if the imbalance persists, a 5-minute trading halt begins. Implemented across all US equity exchanges.

**Liquidity:** The ease with which an asset can be bought or sold without significantly affecting its price. High liquidity = tight spread, large depth, easy trading.

**Locate:** The process of finding and reserving a source of borrowable shares before executing a short sale. Under US Regulation SHO, broker-dealers must have reasonable grounds to believe shares can be borrowed before accepting a short sale order. "Failing to locate" before shorting is called naked short selling, which is illegal in most jurisdictions.

**Lot:** The standard unit of quantity for an instrument.


## M {#glossary-m}

**Maintenance Margin:** The minimum collateral balance that must be maintained in a margin account. Falling below this level triggers a margin call.

**Maker:** The participant whose resting order was already in the book when a fill occurred. Contrast with *Aggressor/Taker*.

**Margin Call:** A demand from a clearing house or broker for a participant to deposit additional collateral to restore their margin account to the required level.

**Mark-to-Market:** The daily revaluation of positions at current market prices, with cash payments made to reflect daily gains and losses. The mechanism by which variation margin is calculated.

**Market capitalisation (market cap):** The total market value of all a company's outstanding shares, calculated as share price multiplied by the total number of shares in existence. If Apple has approximately 15.4 billion shares outstanding and each trades at $190, Apple's market cap is roughly $2.9 trillion [1]. Market cap is the most widely used shorthand for a company's size. When rankings refer to "the world's largest exchange by listed market cap," they are summing the market caps of every company listed there.

**Market Fragmentation:** The distribution of trading volume for a single instrument across multiple competing venues, exchanges, dark pools, ATSs, and internalisers. Modern equity markets are highly fragmented; in the US, AAPL may trade simultaneously across a dozen registered exchanges plus numerous alternative venues. Fragmentation improves competition and reduces fees but complicates order routing and best-execution analysis. Regulatory frameworks like Regulation NMS (US) and MiFID II (EU) were introduced partly in response to fragmentation.

**Market Impact / Slippage:** The adverse price movement caused by a large order sweeping through multiple price levels.

**Market Impact Estimation:** The process of computing, before order submission, the average price you would pay (or receive) by sweeping through available book levels for a given order size. Derived from the cumulative depth profile. Used by execution algorithms to size order slices and choose between aggressive execution and passive accumulation.

**Market Maker:** A professional participant obligated to continuously provide both buy and sell prices, ensuring liquidity for other participants.

**Market Maker Protection (MMP):** An exchange-provided mechanism that automatically cancels all of a market maker's resting quotes when fills arrive at a rate exceeding a configured threshold within a rolling time window. Protects market makers from being rapidly picked off by participants with superior information (adverse selection). After MMP fires, the market maker enters a protection period before re-quoting. Parameters (fill count, time window) are configured per market maker per symbol.

**Market Order:** An order that attempts immediate execution against available liquidity at the best obtainable prices. It prioritises execution certainty over price certainty, but execution is still subject to exchange state, available liquidity, price collars, and risk controls. A market order submitted during a halt, against an empty book, or rejected by a pre-trade risk check will not fill.

**Mass Cancel:** A participant-initiated message type that cancels multiple resting orders simultaneously, all orders for a symbol, all orders of a given type, or all orders system-wide. The gateway connection remains active after a mass cancel; the participant can submit new orders immediately. Contrast with *Kill Switch*, which inactivates the gateway and requires re-authentication.

**Matching Engine:** The core software that manages order books and matches buy and sell orders to produce trades.

**Maturity (Bond):** The date on which a bond's issuer must repay the face value to the bondholder.

**Microwave Link:** A radio communications link using microwave frequencies. Between financial data centres, microwave links provide lower latency than fibre-optic cables because radio waves travel faster through air than light through glass.

**Mid Price:** The average of the best bid and best ask: (best_bid + best_ask) / 2.

**Midpoint Peg Order:** An order whose price continuously tracks the current mid price (the average of the best bid and best ask). Executes only when a counterparty arrives whose order is also willing to trade at the midpoint. The mid is a *better* price for both parties than the quoted bid or ask, the buyer pays less than the ask, the seller receives more than the bid; the spread is shared rather than fully paid. Provides price improvement at the cost of uncertain execution timing: there is no guarantee a counterparty will appear. Common in dark pools; also supported on IEX on the lit market. Never competes in the regular price-time priority queue, maintained as a separate midpoint matching layer.

**MMP Threshold:** The fill count and time window that together trigger Market Maker Protection. For example, "5 fills within 1 second." If this threshold is exceeded, the exchange automatically cancels all of the market maker's resting quotes. The threshold is negotiated per market maker, per symbol, and finding the right value is a key parameter of market making strategy.

**Monotonic:** Strictly non-decreasing. A monotonic sequence is one where each value is equal to or greater than all previous values. A strictly monotonic sequence is one where each value is strictly greater.


## N {#glossary-n}

**Naked Short Selling:** Selling shares short without first locating and arranging to borrow them. The seller delivers nothing at settlement, creating a "fail to deliver." Illegal in most jurisdictions under short sale regulations (Regulation SHO in the US). Distinguished from covered short selling, where shares have been located and borrowed.

**Nanosecond:** One billionth of a second (10⁻⁹ seconds). Modern matching engines record timestamps at nanosecond precision.

**NBBO (National Best Bid and Offer):** The best available bid and ask prices aggregated across all US exchanges, as required by Regulation NMS. Brokers must offer clients execution at or better than the NBBO.

**Novation:** The legal process by which a CCP replaces the original buyer-seller relationship: the CCP becomes buyer to the seller and seller to the buyer, eliminating bilateral counterparty risk.

**NTP (Network Time Protocol):** A protocol for synchronising computer clocks over a network. Basic NTP achieves millisecond accuracy; higher-precision variants achieve sub-millisecond.


## O {#glossary-o}

**OCC (Options Clearing Corporation):** The central clearing house for equity options in the US.

**OCO (One-Cancels-Other):** Two linked orders where filling either automatically cancels the other.

**OHLCV:** Open, High, Low, Close, Volume, the five standard summary statistics recorded for each trading session (or any time period). Open: the first traded price. High: the highest traded price. Low: the lowest traded price. Close: the last traded price (the official closing price in a closing auction). Volume: total shares traded. OHLCV data forms the basis of almost all price charts and historical market analysis.

**Open Outcry:** The historical method of trading on exchange floors, where traders shouted bids and asks and used hand signals in a sunken circular area called a pit. Largely replaced by electronic trading.

**Options:** Contracts that give the buyer the right, but not the obligation, to buy (a **call option**) or sell (a **put option**) an underlying asset at a specified price (the **strike price**) before or on a specified date (the **expiry date**). The seller of an option takes on the corresponding obligation. Options are priced using models (Black-Scholes being the most famous) that account for time to expiry, volatility, interest rates, and the distance between the current price and the strike. Cboe is the world's largest options exchange.

**Order Book:** The central data structure of a matching engine, all resting buy and sell orders for a symbol, organised by price.

**Order ID:** A unique identifier assigned to each order upon submission. Must be unique across the entire system.

**OTC (Over-the-Counter):** Trading that occurs directly between two parties without going through an exchange. OTC trades are less transparent and subject to different regulations than exchange-traded transactions.

**OUCH (NASDAQ OUCH):** NASDAQ's high-performance binary order entry protocol used by member firms and low-latency trading systems to submit, modify, cancel, and manage orders directly at the matching engine. OUCH is session-based and message-oriented, with exchange acknowledgments and execution/cancel responses that let clients track the full order lifecycle deterministically. Official specification: [NASDAQ OUCH 5.0](https://www.nasdaqtrader.com/content/technicalsupport/specifications/TradingProducts/OUCH5.0.pdf).


## P {#glossary-p}

**P&L (Profit and Loss):** The financial gain or loss on a trading position.

**Payment for Order Flow (PFOF):** A practice in which retail brokers receive payment from wholesale market makers in exchange for routing client order flow to those market makers for internalisation rather than to lit exchanges. Market makers pay for retail flow because retail orders have lower adverse selection risk. Banned in the UK and EU under MiFID II. Controversial in the US, where it subsidises zero-commission brokerages but raises concerns about conflicts of interest and reduced price discovery. See *Best Execution*, *Internaliser*.

**Pit:** The sunken, octagonal or circular physical trading area on an exchange floor where open outcry trading happened. CME Group operated prominent futures pits in Chicago. Largely dormant today.

**Portfolio:** A collection of investments held by an investor, typically diversified across asset types (equities, bonds, etc.) to manage risk and return.

**Position:** A participant's current holding in an instrument, positive (long) if they own more than they have committed to deliver; negative (short) if they have committed to deliver more than they own; zero (flat) if both sides balance. Position tracking is the clearing system's primary responsibility.

**Pre-Trade Risk Controls:** Checks applied to orders before they reach the matching engine, quantity limits, notional limits, fat-finger filters, credit checks, and rate limiting. The gateway is typically the enforcement layer.

**Presence Obligation:** A market maker's contractual requirement to have live two-sided quotes resting in the book for a minimum percentage of the trading session, commonly 85% or more. Prevents market makers from only quoting on easy days and disappearing on volatile ones when liquidity is most needed.

**Price Discovery:** The process by which the market determines the current fair price of an asset through the interaction of buyers and sellers. A well-functioning exchange enables efficient price discovery: prices reflect all currently available information and update rapidly as new information arrives. Price discovery is one of the three core promises every exchange makes. Poor price discovery, where the traded price diverges significantly from fair value for extended periods, is a sign of market dysfunction.

**Price Level:** All resting orders at the same price on the same side of the book.

**Price-Time Priority:** The matching rule: better prices fill first; at the same price, earlier arrivals fill first.

**Primary Market:** Where new securities are issued and sold for the first time. The company (or government) receives the proceeds.

**Primary Site:** The active, live data centre running the production matching engine.

**Private Company:** A company whose shares are not publicly traded, held only by founders, employees, and private investors.

**Pro-Rata Allocation:** An alternative to price-time priority where fills at a price level are distributed proportionally among all resting orders at that level. Common in some futures markets.

**Protection Period:** The window of time after MMP fires during which a market maker has no active quotes and is expected to assess market conditions before deciding whether and at what prices to re-enter. The duration is typically a few seconds and is defined in the market maker agreement.

**PTP (Precision Time Protocol, IEEE 1588):** A network clock synchronisation protocol achieving sub-microsecond accuracy. Used in exchange infrastructure to ensure consistent timestamps across distributed systems.

**Public Company:** A company whose shares are listed on a stock exchange and available to any investor.


## Q {#glossary-q}

**Quote:** A two-sided order submitted by a market maker containing both a bid (buy) and an ask (sell) simultaneously. Unlike a regular order, the two legs are linked, what happens to one (a fill, a cancellation) triggers a defined response on the other according to the quote refresh policy.

**Quote Leg:** One side (bid or ask) of a two-sided market maker quote. Filling one leg triggers the quote refresh policy for the other leg.

**Quote Refresh Policy:** The rule governing what happens to the surviving leg of a two-sided quote when the other leg is filled. Three main variants: (1) cancel both sides immediately, the most conservative, used by Eurex-style inactivation; (2) cancel only the filled side, leave the other active; (3) leave both active. The choice reflects the market maker's balance between speed of re-entry and risk of holding stale inventory.

**Quote Stuffing:** A market manipulation practice where a participant rapidly submits and cancels a very large number of orders to consume exchange bandwidth, slow down competitors' systems, and create artificial confusion in market data. A form of denial-of-service abuse in electronic markets.


## R {#glossary-r}

**Ratchet:** The mechanism in a trailing stop that advances the stop price in the favourable direction but freezes it when the market reverses.

**Rate Limiting / Throttling:** A control that limits the number of orders a participant can submit per unit time. Prevents denial-of-service conditions from algorithmic misfires.

**Re-quoting Obligation:** A market maker's contractual requirement to post a fresh two-sided quote within a specified maximum delay after either leg of their previous quote is filled or after MMP fires. Failure to re-quote within this window counts against the presence obligation and may trigger penalties. The window is typically measured in milliseconds to low seconds.

**Reference Data / Instrument Master:** The configuration data describing a tradeable instrument, tick size, price scale, session schedule, contract multiplier, trading status, expiry date, position limits. Read by every exchange component; an error propagates system-wide. Treat it with the same rigour as code: version-controlled, tested, applied atomically.

**Regulation NMS:** A US Securities and Exchange Commission regulation requiring that equity orders be executed at the best available price across all exchanges (the NBBO). A primary driver of US market fragmentation.

**Regulation SHO:** A US Securities and Exchange Commission rule governing short sales in equity markets. Key requirements: broker-dealers must have a reasonable belief shares can be borrowed before accepting a short sale order (the "locate" requirement); persistent fail-to-deliver situations must be closed out; short sales must be marked as "short" in order records. Adopted in 2005 to address concerns about abusive naked short selling.

**Replay (Exchange):** Replaying a recorded sequence of input messages through the matching engine to reconstruct past market states. Requires the engine to be deterministic.

**Reserve Refresh Priority:** The queue position rule for iceberg replenishment. Most exchanges place a newly replenished iceberg peak at the back of the queue at its price level, equivalent to a brand-new arrival, rather than preserving the original queue position.

**Resting Order / Passive Order:** An order that has been accepted by the exchange and is waiting in the book for a counterparty.

**Retained Earnings:** Profits kept within the business rather than distributed to shareholders. A source of self-funding for company growth.

**Rolling Window (MMP):** The time period over which fills are counted for Market Maker Protection purposes. Fills older than the window are discarded from the count; only fills within the current window matter. For example, a 1-second rolling window means: "if more than N fills have arrived in any sliding 1-second period, MMP fires."


## S {#glossary-s}

**Secondary Market:** Where existing securities are traded between investors. The issuing company does not receive proceeds. Stock exchanges are secondary markets.

**Secondary Site / Backup Site:** A standby data centre that can take over exchange operation if the primary site fails.

**Securities Lending / Stock Borrow:** The temporary transfer of securities from a lender (typically a long-term investor or custodian) to a borrower (typically a short seller) in exchange for collateral and a lending fee (borrow rate). Short sellers must borrow shares before selling short. The lender retains economic ownership (receives manufactured dividends and can recall the shares) but transfers legal title temporarily. Recall risk, the lender demanding shares back at an inconvenient time, is a key risk for short sellers.

**SEDOL:** A 7-character UK security identifier used in settlement and clearing. Analogous to CUSIP.

**Self-Match Prevention (SMP):** A mechanism that detects when a participant would trade against their own orders and applies a cancellation policy.

**Sequence Number:** A monotonically increasing counter attached to events (in a drop copy or message feed) to enable detection of missed events and ordered replay.

**Session State Machine:** The formal model of an exchange's trading day phases (PRE_OPEN, OPENING_AUCTION, CONTINUOUS, CLOSING_AUCTION, CLOSED) and the permitted transitions between them.

**Settlement:** The final transfer of securities from seller to buyer and cash from buyer to seller. Legally completes the trade. In the US, equity settlement currently occurs on T+1.

**Settlement Method (Derivatives):** Whether a futures or options contract settles by cash payment or physical delivery of the underlying asset. Determines post-expiry processing required by the exchange and clearing house.

**Shadow Replication / Shadow Mode:** An architectural pattern for high-availability exchange systems. The secondary site receives and processes all input messages in parallel with the primary, maintaining an up-to-date copy of the order book, but does not publish outputs or accept participant connections. If the primary fails, the secondary's in-memory state is already current and it can begin accepting inputs and publishing outputs with minimal failover time. More common in production than true active-active matching.

**Share / Stock:** A single unit of equity ownership in a company. Each share represents a fractional claim on the company's assets, earnings, and votes.

**Smart Order Router (SOR):** Software that evaluates multiple trading venues and routes orders to achieve the best overall execution, balancing price, fees, available depth, and speed.

**SmartNIC / Ultra-Low-Latency NIC:** A specialised network interface card designed for trading and other latency-sensitive applications. Unlike commodity Ethernet cards, SmartNICs include an on-card kernel bypass networking stack (such as Solarflare's OpenOnload or Mellanox's RDMA), hardware timestamping of incoming packets to nanosecond precision, and CPU offload for networking tasks. Examples include the AMD Solarflare SFN series and NVIDIA Mellanox ConnectX series, widely deployed in exchange co-location environments.

**Snapshot (Persistence):** A complete dump of the matching engine's state (all resting orders, positions, key data) taken periodically to reduce recovery time by limiting the amount of write-ahead log that must be replayed.

**Specialist:** NYSE's historical term for the designated firm responsible for maintaining fair and orderly markets in a specific stock, including maintaining the physical order book. The modern equivalent is the Designated Market Maker (DMM).

**Speed Bump:** A deliberate artificial delay applied to all incoming orders to eliminate the advantage of being marginally faster than other participants. Pioneered by IEX.

**Split-Brain:** A failure mode in distributed systems where two nodes both believe themselves to be the active primary, leading to conflicting actions.

**Spoofing:** A market manipulation practice: placing orders with no intention of trading to move prices, then cancelling before execution. Illegal under market abuse regulations.

**Spread:** The difference between the best ask and the best bid. Market makers earn the spread; participants pay it as the cost of immediate trading.

**State Machine:** A formal model consisting of a finite set of states and explicit rules about which transitions between states are allowed.

**Static Price Collar (Fat-Finger Filter):** A pre-trade risk control that rejects any order whose submitted price deviates more than a configured percentage from the last official close price. Designed to catch obvious fat-finger errors, an order at $15.00 on a stock trading at $150.00 is almost certainly a decimal error. Because the reference is the previous close, the static collar is stable throughout the trading day. Contrast with *Dynamic Price Collar*, which tracks the most recent trade instead.

**Stop Order:** A conditional order that is dormant until the market price reaches the stop price, then converts to another order type.

**Stop Price:** The trigger price on a stop or stop-limit order. The order remains dormant until the market's last trade price reaches or crosses the stop price, at which point it activates and enters the book (as a market or limit order, depending on type). A buy stop has a stop price above the current market; a sell stop has a stop price below it.

**Stop-Limit Order:** A stop order that converts to a limit order when triggered. Provides price protection but may not execute if the market gaps.

**Stop-Loss:** A sell stop order used to automatically exit a losing long position if the price falls to a specified level.

**Sweeping:** The process of an aggressive order filling against resting orders at successive price levels.


## T {#glossary-t}

**T+1 / T+2 Settlement:** Settlement occurring 1 or 2 business days after the trade date. The US moved from T+3 to T+2 in 2017 and to T+1 in 2024.

**T+2 Settlement:** Settlement occurring two business days after the trade date. The US standard until 2024; most US equities now settle T+1. T+2 remains the standard in many other markets.

**Tick:** The minimum price movement for an instrument.

**Tick Count / Tick-Based Price:** A price represented as an integer number of minimum increments, rather than a decimal. Tick counts are exact; floating-point decimals are not.

**Tick Size:** The value of one tick, the minimum price increment for an instrument.

**Tick-to-Trade Latency:** The time from when a market data message leaves the exchange to when an order based on that message is received by the exchange. A key performance metric for market makers and HFT firms.

**Ticker / Ticker Symbol:** The abbreviated code identifying a tradeable instrument (e.g., AAPL for Apple Inc.). Named after the mechanical stock ticker machine that printed trade prices on paper tape using telegraph signals in the late 19th and early 20th centuries.

**Ticker Tape:** The narrow paper strip printed by the stock ticker machine, showing a continuous stream of trade symbols, prices, and volumes. The source of the term "tick" (minimum price movement) and related concepts.

**Time-In-Force (TIF):** The attribute specifying how long an order remains valid (DAY, GTC, IOC, FOK, ATO, ATC).

**Top-of-Book (Level 1):** Market data showing only the best bid price, best ask price, and their quantities. The minimum information needed to understand the current market.

**Trade:** An executed match between a buy and sell order. Also called a fill or execution.

**Trailing Stop:** A stop order whose trigger price automatically advances in the favourable direction as the market moves, protected by a fixed trail offset.

**TWAP (Time-Weighted Average Price Algorithm):** An execution algorithm that distributes a large order evenly across equal time intervals, regardless of trading volume. Simple and predictable, but less adaptive than VWAP. Used when a stock has no reliable volume profile or when the trader wants mechanically consistent participation. Performance is measured against the average of prices during the execution window, not the overall day's VWAP.

**Two-Sided Quote:** A market maker's simultaneous bid and ask for the same instrument. Both sides must be live at the same time to fulfil the two-sided quoting obligation. A one-sided quote (only bid or only ask) is a contractual breach of market maker obligations.


## U {#glossary-u}

**UUID (Universally Unique Identifier):** A 128-bit identifier designed to be unique without central coordination. UUID v4 is randomly generated; UUID v1 incorporates the current time and network address.


## V {#glossary-v}

**Variation Margin:** Daily cash payments reflecting mark-to-market gains and losses on open positions. Prevents losses from accumulating to unmanageable levels before settlement.

**Venture Capital (VC):** Private investment firms that provide funding to early-stage companies in exchange for equity stakes, before those companies are large enough to go public.

**VIX (Volatility Index):** A real-time index calculated by Cboe from the prices of S&P 500 options, representing the market's expectation of 30-day price volatility in the S&P 500. Commonly called the "fear gauge", when markets are uncertain or falling sharply, participants buy put options for protection, driving up option prices and therefore the VIX. Values above 30 typically indicate high market stress; values below 20 indicate relative calm. Derivatives on the VIX itself trade on Cboe.

**VWAP (Volume-Weighted Average Price):** The average price of a position weighted by the quantity traded at each price. Used as cost basis for P&L calculation.

**VWAP Algorithm:** An execution algorithm that slices a large order and executes it throughout the day in proportion to expected trading volume, more during high-volume periods (open, close) and less during low-volume periods (mid-day). The goal is to achieve an average execution price close to or better than the day's volume-weighted average price. The most widely used institutional execution benchmark. Distinct from *VWAP (Volume-Weighted Average Price)*, which is a measurement; the VWAP algorithm is the execution strategy aimed at matching that measurement.


## W {#glossary-w}

**Wash Trading / Wash Trade:** A transaction where the same participant is on both sides, generating artificial trading volume with no real change of ownership. Illegal in all major jurisdictions under market manipulation regulations (the EU's Market Abuse Regulation, the US SEC's Rule 10b-5, and others). Also called a wash sale. Sometimes performed accidentally, see *Self-Match Prevention (SMP)*, but when deliberate, it is a form of market abuse used to inflate trading volume figures or create false impressions of liquidity.

**Write-Ahead Log (WAL):** A persistent, append-only log of all input messages to the matching engine. Written before processing; used for recovery and replay. The source of truth from which all derived state (the in-memory order book) can be reconstructed.


## Z {#glossary-z}

**ZeroMQ (ZMQ):** A messaging library providing efficient pub/sub, push/pull, and other communication patterns. Commonly used as the message bus in exchange systems.

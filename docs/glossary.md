# Glossary

Financial and technical terms used throughout the EduMatcher documentation,
in alphabetical order.

---

## A

**Ask (Offer)**
The lowest price at which a seller is willing to sell. The ask is always higher
than the bid. When you submit a market buy, you pay at or near the ask.

**At-The-Close (ATC)**
A time-in-force value that restricts an order to the `CLOSING_AUCTION` phase
only. ATC orders are automatically expired when the closing auction ends.

**At-The-Open (ATO)**
A time-in-force value that restricts an order to the `OPENING_AUCTION` phase
only. ATO orders are automatically expired when the opening auction ends.

**Auction (Call Auction)**
A trading phase where orders accumulate without matching. At the end of the
phase, the exchange computes a single **equilibrium price** and executes all
crossable orders simultaneously. Auctions are used at the open and close of
each trading day. See [Auctions & Session Scheduling](auction.md).

---

## B

**Best Ask**
The lowest resting sell price in the order book — the price at which a buyer
can trade immediately.

**Best Bid**
The highest resting buy price in the order book — the price at which a seller
can trade immediately.

**Bid**
A resting buy order in the order book. Bids are sorted with the highest price
at the top (the "best" bid). See also: *Ask*.

**Bid-Ask Spread** → see *Spread*

**Book Depth**
The total volume (quantity of shares) resting near the top of the order book.
A deep book absorbs large orders without significant price impact. A thin (or
shallow) book moves quickly on even moderate order flow.

**Bracket Order**
A strategy combining an entry order with both a take-profit LIMIT and a
stop-loss STOP, typically implemented as an OCO pair. See
[OCO](order-types.md#12-oco-one-cancels-other).

---

## C

**Cascade Cancel**
When a COMBO order fails (any leg is cancelled or rejected), all remaining
unfilled legs of the combo are automatically cancelled. Previously executed
fills are not reversed.

**Central Limit Order Book (CLOB)**
The canonical order-matching mechanism used by most regulated equity exchanges.
Orders are queued by price and time; the best bid and best ask are continuously
matched when they overlap.

**Clearing**
The post-trade process of confirming that a trade took place, recording the
transaction, and updating account balances. EduMatcher implements instant
clearing with no credit risk. See [P&L & Clearing](pnl.md).

**Combo Order**
A multi-leg order bundling 2–10 child orders across different symbols into a
single atomic instruction. All legs share a lifecycle: if one fails, the rest
are cascade-cancelled. See [Combo Orders](combos.md).

**Continuous Trading**
The `CONTINUOUS` session phase where every new order is immediately swept
against resting orders using price-time priority. Most of the trading day
occurs in this phase.

**Crossable**
Two orders are crossable when they overlap in price: a buy at or above a
resting sell's price, or a sell at or below a resting buy's price. Crossable
orders produce a trade.

---

## D

**DAY**
A time-in-force value meaning the order is valid only for the current trading
session. DAY orders are expired at market close and are not reloaded next day.

**Depth** → see *Book Depth*

---

## E

**Equilibrium Price**
The single price at which an auction uncross executes. Computed as the price
that maximises the total volume of shares that can trade. Also called the
auction clearing price. See [Auctions & Session Scheduling](auction.md).

**Execution** → see *Fill*

---

## F

**Fill**
The full or partial execution of an order. When a trade occurs, both the buyer
and seller receive `order.fill` events. A **partial fill** means only part of
the requested quantity traded; the remainder continues to rest on the book.

**Flat**
Having no open position in a symbol (net quantity = 0). Neither long nor short.

**FOK (Fill-or-Kill)**
An order type that must be entirely filled immediately or is cancelled in full.
No partial fills. See [Order Types](order-types.md#5-fok-fill-or-kill).

---

## G

**Gateway**
A process (`pm-gateway`) representing one trader's connection to the matching
engine. Each gateway has a unique ID. Multiple gateways can connect
simultaneously.

**GTC (Good-Till-Cancelled)**
A time-in-force value that keeps an order alive across trading sessions. GTC
orders are serialised to `data/gtc_orders.json` at shutdown and reloaded next
session.

---

## I

**Iceberg Order**
A large limit order that hides most of its quantity, displaying only a visible
"peak." When the peak fills, a new peak is replenished from the hidden
quantity. See [Order Types](order-types.md#6-iceberg).

**Information Asymmetry**
A situation where some market participants have access to information (faster
data, better analytics) that others do not, giving them a trading advantage.
Auctions reduce information asymmetry by letting all participants submit orders
before any execution occurs.

**IOC (Immediate-Or-Cancel)**
A time-in-force (and order type) where an order sweeps available liquidity at
the limit price and any unfilled remainder is immediately cancelled. Never
rests on the book. See [Order Types](order-types.md#10-ioc-immediate-or-cancel).

---

## L

**Leg**
One component order within a COMBO or OCO pair. A two-leg combo has two
individual orders, each in a potentially different symbol.

**Leg Risk**
The risk that one leg of a multi-leg strategy fills while the other does not,
leaving an unintended one-sided position. COMBO orders are designed to manage
leg risk by coupling leg lifecycles.

**LIMIT Order**
An order with a maximum buy price (or minimum sell price) specified. Rests on
the book if not immediately matchable. Guarantees price but not execution. See
[Order Types](order-types.md#2-limit).

**Liquidity**
The ease with which an instrument can be bought or sold without significantly
moving the price. A liquid market has many resting orders (deep book, narrow
spread). An illiquid market has few (thin book, wide spread).

**Long Position**
Owning a positive quantity of shares. You profit if the price rises. Expressed
as a positive number in EduMatcher's P&L ledger.

---

## M

**Maker**
A passive order that rests on the book and provides liquidity for others to
trade against. See also: *Taker*.

**MARKET Order**
An order with no price limit. Executes immediately at whatever prices are
available in the order book. Guarantees execution but not price. See
[Order Types](order-types.md#1-market).

**Market Microstructure**
The study of how trading mechanisms, order types, and market rules affect
price formation and liquidity. EduMatcher is designed to demonstrate core
microstructure concepts.

**Matching Engine**
The central process (`pm-engine`) that receives orders, applies price-time
priority, produces trades, and broadcasts events to all subscribers.

**Mid-Price**
The arithmetic average of the best bid and best ask:
$\text{mid} = \frac{\text{best bid} + \text{best ask}}{2}$.
Often used as a reference price when the spread is non-zero.

---

## N

**NAV (Net Asset Value)**
The total value of a fund's holdings divided by the number of shares
outstanding. For mutual funds, NAV is computed daily using the official
**closing price** of each holding — one reason the closing price matters so
much.

---

## O

**OCO (One-Cancels-Other)**
A paired order construct where two orders are linked: when one reaches a
terminal state (filled, cancelled, rejected), the other is automatically
cancelled. See [Order Types](order-types.md#12-oco-one-cancels-other).

**Order Book** → see *Central Limit Order Book (CLOB)*

---

## P

**P&L (Profit and Loss)**
The running total of how much a trader has made or lost. Comprises
**realized P&L** (locked-in from closed trades) and **unrealized P&L**
(open position valued at current market price). See [P&L & Clearing](pnl.md).

**Passive Order** → see *Maker*

**Position**
The net quantity of an instrument a trader currently holds. Positive = long,
negative = short, zero = flat.

**Price Discovery**
The process by which the market arrives at a consensus price for an instrument,
incorporating all available information and participant interest. Opening
auctions are a key mechanism for price discovery after overnight news.

**Price-Time Priority**
The fill ordering rule used in EduMatcher (and most exchanges): orders at
better prices fill first; among orders at the same price, the earliest-arriving
order fills first. See [The Order Book](concepts-order-book.md#price-time-priority).

---

## Q

**Quote**
A bid or ask price posted by a participant. The best bid and best ask together
form the **inside quote** or **top of book**.

---

## R

**Realized P&L**
Profit or loss that has been "locked in" through a trade that reduced an open
position. Once realized, it cannot be reversed by subsequent price moves.

**Resting Order**
An order that has been accepted by the engine and is sitting on the order book
waiting for a counterparty. Also called a passive order or maker.

---

## S

**Session Phase**
The current operating mode of the exchange. EduMatcher has five phases:
`PRE_OPEN`, `OPENING_AUCTION`, `CONTINUOUS`, `CLOSING_AUCTION`, `CLOSED`.
See [A Full Trading Day](concepts-trading-day.md).

**Self Match Prevention (SMP)**
A rule that prevents a trader from accidentally trading against their own
orders. Configurable per order: `CANCEL_AGGRESSOR`, `CANCEL_RESTING`, or
`CANCEL_BOTH`.

**Short Position**
Selling shares you do not own (borrowed from a broker). You profit if the
price falls. Expressed as a negative number in EduMatcher's P&L ledger.

**Slippage**
The difference between the expected fill price and the actual average fill
price, caused by executing against multiple price levels in the book. Large
orders in thin books experience more slippage.

**Spread (Bid-Ask Spread)**
The difference between the best ask and the best bid. Represents the
cost of an immediate round-trip trade. Narrow spreads indicate liquid markets;
wide spreads indicate illiquid markets.

**STOP Order (Stop-Market)**
A dormant order that converts to a MARKET order when the last trade price
crosses the stop price. Used for stop-loss exits and breakout entries. See
[Order Types](order-types.md#3-stop-stop-market).

**STOP_LIMIT Order**
Like STOP, but converts to a LIMIT order (at a specified price) rather than a
MARKET order when triggered. Provides price protection after trigger at the
risk of non-fill. See [Order Types](order-types.md#4-stop_limit).

**Stop Price**
The trigger level for STOP, STOP_LIMIT, and TRAILING_STOP orders. Not the
execution price — it is the price that activates the dormant order.

---

## T

**Taker**
An aggressive order that crosses the spread and immediately matches against
resting orders. See also: *Maker*.

**Tick Size**
The minimum price increment for an instrument (e.g. $0.01 for US equities).
EduMatcher does not enforce tick sizes but the concept is relevant when
comparing to real exchanges.

**Time-in-Force (TIF)**
A field specifying how long an order remains active: `DAY`, `GTC`, `ATO`,
`ATC`, or `FOK`/`IOC`. See [Order Types — TIF](order-types.md#8-time-in-force-tif).

**TRAILING_STOP**
A stop order whose trigger price automatically ratchets in the trader's favour
as the market moves favourably, but never moves against them. See
[Order Types](order-types.md#11-trailing_stop).

**Trade**
The execution event produced when a buy order and sell order match. Both
parties receive fill confirmations; the clearing process updates P&L.

---

## U

**Uncross**
The single atomic batch execution that occurs at the end of an auction phase.
All crossable orders execute at the **equilibrium price** simultaneously.

**Unrealized P&L**
The theoretical profit or loss on an open position if it were closed at the
current market price. Changes continuously as the market moves. Becomes
realized P&L when the position is closed.

---

## V

**VWAP (Volume-Weighted Average Price)**
The average price paid for shares, weighted by the quantity traded at each
price level. EduMatcher uses VWAP as the cost basis for position tracking.
$$\text{VWAP} = \frac{\sum(\text{price}_i \times \text{qty}_i)}{\sum \text{qty}_i}$$

---

## Z

**ZeroMQ (ZMQ)**
The high-performance messaging library used by EduMatcher for inter-process
communication. Uses a broker-less PUSH/PULL and PUB/SUB topology. No external
message queue server is required. See [Architecture](architecture.md).

---

## T

**Tick**
The smallest permitted price increment for a symbol. EduMatcher stores prices
internally as integer counts of ticks.

**tick_decimals**
Configuration value defining the decimal precision of one tick for a symbol.
Example: `tick_decimals = 2` means one tick equals `0.01`.

**trail_offset_ticks**
Trailing stop offset represented in ticks. The stop ratchets using tick-domain
arithmetic to avoid mixed float/int behavior.

## N

**timestamp_ns**
Timestamp represented as integer nanoseconds. Used internally for strict
ordering and queue priority tie-breaks.

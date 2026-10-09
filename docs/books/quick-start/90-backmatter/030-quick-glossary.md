# Quick Glossary

The words this guide uses, in one page. The Reference Manual's
[Glossary](../../reference-manual/90-backmatter/010-glossary.md) has the full
vocabulary.

| Term | Meaning |
|---|---|
| **Ask** | The lowest price at which someone is currently willing to sell. Also called the *offer*. |
| **Auction** | A phase in which orders are collected and then all matched at once, at one price (the *equilibrium price*). Used to open and close the day. |
| **Bid** | The highest price at which someone is currently willing to buy. |
| **Circuit breaker** | A risk control that halts trading in a symbol after a large, fast price move. |
| **Configuration** | The YAML file that describes the whole exchange: symbols, participants, timetable and rules. It is *deployed* before the exchange uses it. |
| **Drop copy** | An independent copy of every fill, sent to risk and compliance systems. |
| **Engine** | `pm-engine`, the one process that owns the order books and matches orders. |
| **Fill** | An execution: part or all of an order traded. |
| **Gateway** | A process through which participants connect, or the connection itself. The participant ID is also called the *gateway ID*. |
| **Limit order** | An order with a price limit: buy at that price or lower, sell at that price or higher. |
| **Maker / taker** | The maker's order was resting in the book; the taker's order arrived and traded against it. |
| **Market maker** | A participant whose job is to quote both a bid and an ask, so others can always trade. |
| **Market order** | An order without a price: trade now at the best prices available. |
| **Order book** | All resting buy and sell orders for one symbol, best prices first. |
| **Participant** | A trader, market maker or operator configured to connect, with an ID such as `TRADER01` and a role. |
| **P&L** | Profit and loss. *Realized* P&L is locked in by closing a position; *unrealized* P&L is what an open position would make at the last price. |
| **Position** | How many shares a participant holds: positive is *long*, negative is *short*. |
| **Price-time priority** | The matching rule: better prices first; at the same price, earlier orders first. |
| **Resting** | An order waiting in the book for someone to trade with it. |
| **Session phase** | Where the trading day is: `PRE_OPEN`, `OPENING_AUCTION`, `CONTINUOUS`, `CLOSING_AUCTION`, `CLOSED`. |
| **Spread** | The gap between the best ask and the best bid. |
| **Symbol** | A tradeable instrument, such as `AAPL`, with its own order book. |
| **Tick** | The smallest allowed price step for a symbol, for example 0.01. |
| **Time in force (TIF)** | How long an order stays active: `DAY`, `GTC` (good till cancelled), `IOC`, `FOK`, or only in an auction (`ATO`, `ATC`). |
| **ALF, BALF, CALF, RALF, LALF** | EduMatcher's protocols: text order entry, binary order entry, market data, post-trade data and logging. |

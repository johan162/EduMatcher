# The Order: The Fundamental Unit

Everything in an exchange system revolves around the **order**. An order is an instruction from a participant to the exchange: "I want to buy (or sell) a certain quantity of a certain instrument, subject to certain conditions."

Every order carries several key pieces of information:

| Field | What it specifies | Notes |
|---|---|---|
| **Symbol** | Which instrument | "AAPL" = Apple; "ES" = E-mini S&P 500 futures. Each symbol has its own independent order book. |
| **Side** | BUY or SELL | Defines everything about how the order interacts with the book. |
| **Quantity** | How many units to trade | Typically a positive integer. The **lot** is the smallest unit an order can be submitted in; for US equities the matching engine will accept an order for as little as one share. Asian markets often require order sizes to be a whole multiple of a larger minimum lot, 100 or 1,000 shares. This minimum tradeable unit is a separate concept from the **round lot** used to define an odd lot, covered just below. |
| **Price** | Limit price (for limit orders) | Maximum a buyer will pay, or minimum a seller will accept. Market orders carry no price. |
| **Time-In-Force** | How long the order remains valid | So important it gets its own section below. |
| **Arrival timestamp** | When the exchange received the order | Recorded to nanosecond precision. Not just metadata , it is the tiebreaker in price-time priority. |
| **Identity** | Which gateway (participant) submitted it | Used for self-match prevention, kill switches, and regulatory reporting. |

## Round Lots and Odd Lots

Most reference to "the lot" assumes a **round lot**, the standard trading unit for a symbol (100 shares for most US equities, though this varies by price tier and market). An order for any quantity that is not a whole multiple of the round lot size is an **odd lot**, for example, an order for 37 shares of a stock whose round lot is 100.

Odd lots trade normally, the matching engine has no difficulty filling them, but they have a surprising history in US market data: for decades, odd-lot orders and executions were excluded entirely from the consolidated tape and from the NBBO calculation described in the *Smart Order Routing* section of Part IV. The reasoning at the time was that odd lots were assumed to come from small retail investors and were not representative of the "real" market price. This had a real consequence: a stock could have an odd-lot bid or offer that was better than the displayed round-lot NBBO, and that better price would simply not appear in public quote feeds. As retail trading in high-priced stocks grew (a single share of some stocks costs more than many investors want to commit per trade), odd lots became a much larger share of total volume, and regulators revisited this exclusion. Under the SEC's 2020 market-data-infrastructure rules, odd-lot information is being phased into the consolidated data feeds. For exchange developers, the practical lesson is that "the best displayed price" and "the best price actually available" have not always been the same thing, and reference data (round lot size per symbol) drives which orders count as odd lots and are handled differently by downstream reporting and NBBO logic.

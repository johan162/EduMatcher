# The Order: The Fundamental Unit

Everything in an exchange system revolves around the **order**. An order is an instruction from a participant to the exchange: "I want to buy (or sell) a certain quantity of a certain instrument, subject to certain conditions."

Every order carries several key pieces of information:

| Field | What it specifies | Notes |
|---|---|---|
| **Symbol** | Which instrument | "AAPL" = Apple; "ES" = E-mini S&P 500 futures. Each symbol has its own independent order book. |
| **Side** | BUY or SELL | Defines everything about how the order interacts with the book. |
| **Quantity** | How many units to trade | Typically a positive integer. The **lot** is the standard unit; for US equities one lot = one share; Asian markets often have lot sizes of 100 or 1,000 shares. |
| **Price** | Limit price (for limit orders) | Maximum a buyer will pay, or minimum a seller will accept. Market orders carry no price. |
| **Time-In-Force** | How long the order remains valid | So important it gets its own section below. |
| **Arrival timestamp** | When the exchange received the order | Recorded to nanosecond precision. Not just metadata — it is the tiebreaker in price-time priority. |
| **Identity** | Which gateway (participant) submitted it | Used for self-match prevention, kill switches, and regulatory reporting. |




# Trading Sessions, The Day in the Life of a Market


A trading day is structured into distinct phases, each with different rules about what is allowed.

## Pre-Open / Pre-Market

Before the formal opening, some exchanges accept orders for the day (limit orders, ATO orders, GTC orders from previous days). No matching occurs. This is the accumulation phase for the opening auction.

## Opening Auction

As described above, orders collected, equilibrium computed, uncross executed, continuous trading begins.

## Continuous Trading (the main session)

The normal matching mode. Orders arrive continuously, the engine matches them in real time, trades happen as soon as compatible orders meet. This is the primary trading session, NYSE runs from 9:30am to 4:00pm Eastern time, LSE from 8:00am to 4:30pm London time.

## Intraday Auction (optional)

Some exchanges run a brief scheduled auction during the continuous session, typically at a fixed time such as noon or 1:00pm. These **intraday auctions** serve several purposes.

For exchanges that handle both liquid and illiquid instruments, an intraday auction gives participants a chance to trade illiquid stocks against a concentrated pool of interest, rather than relying on sparse continuous liquidity throughout the day. Large institutional orders that are difficult to execute in continuous trading can be "parked" to the intraday auction where counterparties are known to aggregate.

For derivatives markets, intraday auctions are also used as **volatility auctions** , if a futures contract moves rapidly during continuous trading and triggers a volatility interruption (not a full halt, but a brief pause), the exchange may resume through a short auction rather than returning immediately to continuous matching. Eurex runs scheduled intraday auctions for certain futures products and uses volatility-triggered auctions as a softer alternative to full circuit breaker halts.

From the exchange system perspective, an intraday auction is mechanically identical to the opening or closing auction: orders accumulate during the auction call period, the engine computes the equilibrium price, and the uncross executes simultaneously.

## Post-Close

After the formal close, several important processes run:

**After-hours trading.** Some exchanges, particularly US equity venues, allow limited after-hours trading through electronic communication networks (ECNs). Volume and liquidity are substantially lower than during the regular session, spreads are wider, and price moves can be exaggerated. Not all order types are supported. The exchange may operate a separate "extended hours" trading mode with different rules from the main session.

**GTC order persistence.** Good-Till-Cancelled orders that did not fill during the session must be saved to durable storage so they can be reloaded into the order book when the next session begins. This is a non-trivial operation: each GTC order must be written to a persistent store with all its parameters (symbol, side, price, quantity, participant ID, original submission timestamp). At start-of-day, these orders are reloaded before the pre-open period begins, and each is re-acknowledged to the originating participant. If a GTC order's participant has disconnected overnight, the exchange must decide whether to hold the order or cancel it.

**End-of-day batch processes.** The close of session triggers a cascade of batch processes: the official closing price is published and broadcast to downstream systems; daily P&L is calculated for all participants; clearing reports are generated; statistics (OHLCV , Open, High, Low, Close, Volume) are finalised and archived; surveillance reports are run against the day's audit trail. These processes are not in the matching engine's critical path, but they must complete before the next session begins. Their failure can delay the next day's open.

**Book state save.** The complete state of the order book , including all resting limit orders that will carry forward , is written to disk. This is the snapshot that will be used as the starting point for warm restart if needed.

## State Machine

A well-designed exchange system models these transitions as a **state machine**, a finite set of states with explicit rules about which transitions are allowed. You cannot jump from PRE_OPEN directly to CLOSED without going through OPENING_AUCTION and CONTINUOUS. This prevents bugs where the engine enters an impossible state due to a software error or out-of-order messages. If the transition is not in the allowed list, the system rejects it.

```{.mermaid width=600}
stateDiagram-v2
    direction TB
    [*] --> PRE_OPEN

    PRE_OPEN --> OPENING_AUCTION : Auction start time
    note right of PRE_OPEN : Orders accepted, no matching

    OPENING_AUCTION --> CONTINUOUS : Equilibrium found, uncross executed
    note right of OPENING_AUCTION : Orders accumulate, no matching yet

    CONTINUOUS --> HALTED : Circuit breaker trip
    HALTED --> RESUMPTION_AUCTION : Halt period expires
    RESUMPTION_AUCTION --> CONTINUOUS : Resumption uncross complete

    CONTINUOUS --> CLOSING_AUCTION : End-of-day signal
    HALTED --> CLOSING_AUCTION : End-of-day signal during halt

    CLOSING_AUCTION --> CLOSED : Closing uncross complete
    note right of CLOSING_AUCTION : Final price determination

    CLOSED --> [*]
    note right of CLOSED : GTC orders persisted, book saved
```

Each arrow represents a permitted transition. Any attempt to trigger a transition not shown is rejected as invalid. This state machine is enforced in the exchange's session scheduler, which issues state change commands to the matching engine at the appropriate times.


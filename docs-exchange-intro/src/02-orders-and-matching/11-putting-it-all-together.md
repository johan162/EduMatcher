# Putting It All Together


Let us trace the life of a complex event through the entire system using the vocabulary we have now built.

**Scenario:** It is 10:47am. Trading is in the CONTINUOUS session. A large institutional investor decides to sell 50,000 shares of AAPL aggressively using a limit order priced at $150.20, while the best bid in the book is $150.35.

**Step 1:** The investor's trading system sends the order to the exchange gateway (GW03). The gateway parses the FIX message, validates the format, and forwards it to the matching engine.

**Step 2:** The engine receives the order, assigns it a unique order ID (say, `f3a7-... ` UUID) and a nanosecond timestamp. Status: NEW. The engine acknowledges to GW03.

**Step 3:** The engine checks the order type: LIMIT SELL at $150.20. Since the best bid is $150.35 (above the limit price), this order will immediately sweep the buy side.

**Step 4:** The engine sweeps. It fills against resting buy orders, starting at $150.35, then $150.30, then $150.25, then $150.20, until either the 50,000 shares are exhausted or all bids above $150.20 are consumed. Along the way:
- A market maker's GTC bid for 1,000 shares at $150.35 is completely consumed by the sweep. Status: NEW → FILLED.
- An iceberg order's visible 500-share peak at $150.30 gets filled, triggering replenishment from the hidden reserve.
- Several DAY limit orders at $150.25 get partially or fully filled.

**Step 5:** After each fill, the engine updates `last_trade_price`. After sweeping $150.35 bids (aggressive side is SELL), `last_sell_price` is also updated to $150.35.

**Step 6:** The engine checks dormant stops. Does the new `last_trade_price` trigger any waiting stop orders? Suppose a buy stop at $150.40 was waiting, but the price just moved down, not up, so it does not trigger. A sell stop at $150.30 was waiting, the last trade price of $150.25 is now below $150.30, so this sell stop triggers, converting to a market sell order and immediately joining the sweep.

**Step 7:** After all fills, the engine checks whether any circuit breaker thresholds have been breached. Suppose the last closing auction cleared at $153.50 and the collar band for this stock is ±2%. The lower band is $153.50 × 0.98 = $150.43. The sweep has driven the last trade price down to $150.20, which is below the lower band; a circuit breaker trips. The engine transitions to HALTED state, all market maker quotes are cancelled (stale quotes cannot be maintained during a halt), and a halt notification is published.

**Step 8:** All fill events are published to the PUB socket. GW03 receives fill notifications for the institutional investor's order (now showing PARTIAL status, 50,000 shares ordered, 38,000 filled before the halt, 12,000 remaining). Each market maker whose bid was hit receives their fill notification on their respective gateways.

**Step 9:** The drop copy feed receives a copy of all these fill events, tagged with sequence numbers, and forwards them to the clearing broker's risk system.

**Step 10:** The clearing process updates positions. The institutional investor's AAPL position decreases by 38,000. The various market makers' positions increase accordingly. P&L is updated for all parties.

**Step 11:** After the halt period (say, 5 minutes), the scheduler sends a RESUME command. The engine transitions back to CONTINUOUS trading (or, if specified, initiates a brief resumption auction first). Market makers re-quote. Trading resumes.

**Step 12:** The 12,000-share remainder of the institutional investor's sell order continues resting on the ask side at $150.20 and will fill when buyers willing to pay $150.20 or more appear.

In this single scenario, we used: limit orders, GTC orders, iceberg orders, fill notifications, last trade price, last sell price, stop orders, circuit breakers, collar bands, automatic market maker quote cancellation on halt, drop copy, clearing, P&L, trading sessions, and the state machine. Every piece of vocabulary we have discussed had a role to play.

The message flow between components in steps 1–10 can be visualised as follows:

```{.mermaid width=600}
sequenceDiagram
    participant INV as Institutional Investor
    participant GW3 as Gateway GW03
    participant ME as Matching Engine
    participant GW1 as Gateway GW01 (MM)
    participant PUB as PUB Socket
    participant DC as Drop Copy
    participant CL as Clearing

    INV->>GW3: FIX: SELL 50,000 AAPL LIMIT $150.20
    GW3->>ME: Validated order (internal format)
    ME->>GW3: ACK , order NEW (UUID assigned)
    GW3->>INV: Execution report: NEW

    loop Sweep bids $150.35 → $150.20
        ME->>PUB: Trade event (price, qty, both sides)
        PUB->>GW1: Fill notification → market maker FILLED
        PUB->>GW3: Fill notification → investor PARTIAL
        PUB->>DC: Drop copy fill event (seq numbered)
        PUB->>CL: Position update
    end

    ME->>ME: last_trade_price < collar band → HALT
    ME->>PUB: Session state: CONTINUOUS → HALTED
    PUB->>GW1: Cancel all MM quotes (stale during halt)
    PUB->>DC: HALT event (seq numbered)

    Note over ME,CL: 5-minute halt period

    ME->>ME: Scheduler: RESUME
    ME->>PUB: Session state: HALTED → CONTINUOUS
    GW1->>ME: Fresh two-sided quote re-submitted
```


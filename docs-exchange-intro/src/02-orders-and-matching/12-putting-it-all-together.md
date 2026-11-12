# Putting It All Together


Let us trace the life of a complex event through the entire system using the vocabulary we have now built.

**Scenario:** It is 10:47am. Trading is in the CONTINUOUS session. A large institutional investor decides to sell 50,000 shares of AAPL aggressively using a limit order priced at $150.20, while the best bid in the book is $150.35.

**Step 1:** The investor's trading system sends the order to the exchange gateway (GW03). The gateway parses the FIX message, validates the format, and forwards it to the matching engine.

**Step 2:** The engine receives the order, assigns it a unique order ID (say, `f3a7-... ` UUID) and a nanosecond timestamp. Status: NEW. The engine acknowledges to GW03.

**Step 3:** The engine checks the order type: LIMIT SELL at $150.20. Since the best bid is $150.35 (above the limit price), this order will immediately sweep the buy side.

**Step 4:** The engine sweeps. It fills against resting buy orders, starting at $150.35, then $150.30, then $150.25, and it would continue down to $150.20 until either the 50,000 shares are exhausted or all bids at $150.20 and above are consumed, unless something stops it first (see Step 7). Along the way:
- A market maker's GTC bid for 1,000 shares at $150.35 is completely consumed by the sweep. Status: NEW → FILLED.
- An iceberg order's visible 500-share peak at $150.30 gets filled, triggering replenishment from the hidden reserve.
- Several DAY limit orders at $150.25 get partially or fully filled.

**Step 5:** After each fill, the engine updates `last_trade_price`. Some engines also keep the last price per aggressor side; here the seller was the aggressor, so `last_sell_price` also becomes $150.35. Certain stop-order variants use these per-side prices as their trigger.

**Step 6:** The engine checks dormant stops. Does the new `last_trade_price` trigger any waiting stop orders? Suppose a buy stop at $150.40 was waiting, but the price just moved down, not up, so it does not trigger. A sell stop at $150.30 was waiting, the last trade price of $150.25 is now below $150.30, so this sell stop triggers, converting to a market sell order and immediately joining the sweep.

**Step 7:** Before each fill, the engine checks the price against the stock's **price band**: a limit on how far the price may move away from a reference price within a short time (Part III covers these bands, collars and LULD in detail). Suppose yesterday's closing auction cleared at $153.30 and the band for this stock is ±2%. The lower band is $153.30 × 0.98 = $150.234, which rounds *up* to $150.24, the lowest valid price inside the band. The fills at $150.35, $150.30 and $150.25 were inside the band, but the next resting bids, at $150.20, lie below it. Rather than print a trade outside the band, the engine stops the sweep and a circuit breaker trips. The engine transitions to HALTED state, all market maker quotes are cancelled (stale quotes cannot be maintained during a halt), and a halt notification is published.

**Step 8:** All fill events are published to the participants and to the market data feed. GW03 receives fill notifications for the institutional investor's order (now showing PARTIAL status, 50,000 shares ordered, 38,000 filled before the halt, 12,000 remaining). Each market maker whose bid was hit receives their fill notification on their respective gateways.

**Step 9:** The **drop copy** feed (a real-time duplicate of every fill, sent to a firm's risk and clearing systems; Part III has a chapter on it) receives a copy of all these fill events, tagged with sequence numbers, and forwards them to the clearing broker's risk system.

**Step 10:** The clearing process updates positions. The institutional investor's AAPL position decreases by 38,000. The positions of the market makers and other buyers increase accordingly. P&L is updated for all parties.

**Step 11:** After the halt period (say, 5 minutes), the scheduler sends a RESUME command. Following the state machine of the previous chapter, the engine first runs a short **resumption auction**, so that the price after the halt is found in one fair uncross rather than by whoever is fastest. Market makers re-quote, the auction uncrosses, and the engine returns to CONTINUOUS trading.

**Step 12:** The 12,000-share remainder of the institutional investor's sell order takes part in the resumption auction. The bids at $150.20 that the band blocked in Step 7 are still resting, so the auction can now match against them, at a single price set by the auction and checked against fresh bands. Whatever cannot be matched stays on the ask side at $150.20 and will fill when new buyers willing to pay $150.20 or more appear.

In this single scenario, we used: limit orders, GTC orders, iceberg orders, fill notifications, last trade price, last sell price, stop orders, circuit breakers, price bands, automatic market maker quote cancellation on halt, resumption auctions, drop copy, clearing, P&L, trading sessions, and the state machine. Every piece of vocabulary we have discussed had a role to play.

The message flow between components in steps 1–12 can be visualised as follows:

![Message flow for steps 1–12, read top to bottom. Each row is one message from the component on the left to the component on the right. The sweep rows repeat once per fill.](assets/together-message-flow-small.png)


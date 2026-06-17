# Drop Copy, The Shadow Record

A **drop copy** is a real-time copy of all order lifecycle events for a participant, sent simultaneously to a designated recipient, typically a **clearing broker**, **prime broker**, **risk management system**, or directly to a **regulator**.

The name comes from the physical world: the exchange, or the trader, used to drop a "carbon copy" of each order event to the designated desk as it happened.

## Why Drop Copy Exists

A large institutional investor might have dozens of trading desks, each submitting orders to the exchange through its own gateway. The firm's central risk management system needs to see all order and fill activity in real time to monitor aggregate position and exposure. But having the risk system receive from dozens of separate gateways is complex. Instead, the exchange provides a single drop copy feed that aggregates all activity for that firm, regardless of which gateway originated it.

Clearing brokers use drop copy to see fills on behalf of their clients in real time, so they can begin the clearing and settlement process immediately without waiting for end-of-day reports.

Regulators can mandate drop copy access to monitor for suspicious activity in real time. Under the SEC's 15c3-5 Market Access Rule, broker-dealers are required to have real-time monitoring capabilities; a drop copy feed to an independent risk system is one of the standard ways to satisfy this requirement.

## What a Drop Copy Message Contains

A drop copy event is a complete record of the order lifecycle event. A typical fill notification on the drop copy feed includes:

| Field | Purpose |
|---|---|
| **Sequence number** | Monotonically increasing counter for this feed |
| **Timestamp** | Nanosecond-precision time of the event |
| **Order ID** | The exchange-assigned unique order identifier |
| **Client Order ID** | The participant's own order reference |
| **Gateway ID** | Which connection submitted the order |
| **Symbol** | Which instrument |
| **Side** | BUY or SELL |
| **Order type** | LIMIT, MARKET, etc. |
| **Original quantity** | What the order was for |
| **Filled quantity** | How much filled in this event |
| **Remaining quantity** | What is left after this fill |
| **Fill price** | Price at which this fill occurred |
| **Order status** | NEW / PARTIAL / FILLED / CANCELLED |
| **Aggressor flag** | Was this order the aggressive (taker) side? |

The fill price and aggressor flag are used by the clearing broker to calculate real-time P&L and determine fee billing.

## Drop Copy vs Market Data

Drop copy is a **private** feed , it contains information about a specific participant's orders, which they would not want published to the whole market. Market data (the order book, trades) is **public**, published to all subscribers. Drop copy is delivered on a separate, secured channel, typically authenticated with the participant's credentials.

## Sequence Numbers and Gap Recovery

Each event in the drop copy includes a **sequence number**, a monotonically increasing counter. If the recipient momentarily loses their connection and reconnects, they can request a replay of missed events using the last received sequence number.

Worked example: the clearing broker's risk system receives sequence numbers 1, 2, 3, 4 and then loses connectivity briefly. When it reconnects, it sees sequence number 7 arrive. It immediately knows events 5 and 6 were missed. It sends a retransmission request: "resend from sequence 5." The exchange replays events 5, 6, 7 over a separate unicast channel. The risk system processes them in order and is now fully caught up before sequence 8 arrives.

Without sequence numbers, the risk system would have no reliable way to detect the gap. It might operate with a stale position view , showing a position of, say, 5,000 shares when the true position is 7,000 , until the next end-of-day reconciliation. For a real-time risk management system, this is unacceptable.

> **Key idea:** The drop copy sequence number is the risk manager's safety net. A system that processes drop copy events without checking sequence numbers for gaps will eventually make risk decisions based on incorrect positions. Sequence integrity monitoring is not optional.


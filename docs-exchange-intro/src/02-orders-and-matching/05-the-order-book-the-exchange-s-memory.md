## The Order Book, The Exchange's Memory


The **order book** (also called the **limit order book** or **LOB**) is the central data structure of a matching engine [1] [2]. It is the live record of every resting order in the market, all the buyers waiting to buy and all the sellers waiting to sell, organised by price.

![The Order Book](assets/order-book-illustration-small2.png)

***Figure 1:** The most important data structure in an Exchange - the book.*

> **Key idea:** The order book contains only *resting* orders, those waiting for a counterparty. The current "market price" is derived from the book (as the mid of best bid and ask) or from the last trade, not from a stored field.

Think of it as two sorted lists:

**The bid side**, all resting buy orders, sorted from the highest price (most attractive for sellers) down to the lowest. A buyer offering $150.34 is at the top of the bid side if no one else is offering more.

**The ask side** (also called the **offer side**), all resting sell orders, sorted from the lowest price (most attractive for buyers) up to the highest. A seller asking $150.35 is at the top of the ask side if no one is asking less.

**What a real order book looks like.** At any given moment, a simplified snapshot of the AAPL book might be:

| Bid Qty | Bid Price |                                  | Ask Price | Ask Qty |
|--------:|:---------:|----------------------------------|:---------:|:--------|
|   2,000 |  $150.34  | ← **best bid** \| **best ask** → |  $150.35  | 1,500   |
|   1,500 |  $150.33  |                                  |  $150.36  | 2,800   |
|   3,200 |  $150.32  |                                  |  $150.37  | 1,000   |
|     800 |  $150.31  |                                  |  $150.38  | 4,200   |

The **spread** here is $150.35 − $150.34 = $0.01. The **mid price** is ($150.34 + $150.35) / 2 = $150.345. If a market sell order for 3,500 shares arrives, it sweeps bid size: 2,000 shares at $150.34 (exhausting that level), then 1,500 at $150.33 (also exhausting that level). The new best bid after the sweep is $150.32 with 3,200 shares remaining at that price level.

### A Note on Implementation

It is probably safe to say that no other data structure in an exchange is as heavily optimised as the order book. A modern exchange may maintain tens of thousands of order books simultaneously (one per tradeable symbol) and process millions of operations per second across them. Shaving a microsecond ($10^{-6}$s) from each operation or reducing the per-order memory footprint by a few bytes can translate directly into measurable throughput and latency gains at scale. Understanding *why* involves looking at how software architecture is shaped by hardware constraints.

#### Principles of order book design

**Constant-time best price access.** The single most frequent operation is reading or modifying the best bid or best ask. Any design that requires traversal to find the top of book is immediately disqualified. Real implementations maintain direct pointers or indices to the best price level on each side, updated as levels are created or exhausted.

**O(1) insertion at an existing price level.** Once the correct price level is located, appending an order to the back of the queue at that level must be constant time. A doubly-linked list per price level is the classic choice: it gives O(1) append and O(1) removal by pointer (important for cancellations, which are the most common message type in modern markets).

**Efficient price-level lookup.** Finding the correct price level for a new limit order requires a structure keyed on price. Options include sorted arrays, red-black trees, skip lists, and direct-indexed arrays (when the price range is bounded and the tick size is fixed). Direct indexing by price offset is $O(1)$ and is preferred when applicable, at the cost of pre-allocated memory for the entire price range.

**Minimise allocations on the hot path.** Dynamic memory allocation (malloc/new) is unpredictable in latency due to fragmentation and system calls. High-performance engines pre-allocate pools of order objects and price-level nodes at startup, then dispense and recycle from the pool during trading, achieving deterministic allocation latency.

#### Aligning software architecture with hardware

Modern CPUs are fast enough that raw instruction throughput is rarely the bottleneck. Instead, the limiting factor is **memory access latency**: an L1 cache hit takes ~1ns, an L3 hit takes ~10ns, but a main-memory fetch costs 50–100ns. A single cache miss during a match can dominate total processing time. This hardware reality drives several architectural choices:

**Cache-line-friendly data layout.** Order book structures are laid out so that the data accessed together during a match (the top-of-book price level, the first few orders in the queue, the quantity and price fields) resides in adjacent cache lines. This often means using arrays of structs (AoS) or structs of arrays (SoA) tuned so that the hot fields pack into 64-byte cache-line boundaries.

**Hot-path fits in L3 (or even L2).** Engineers measure the working set of the critical matching path, the code and data touched for every single incoming order, and ensure it fits within the processor's L2 or L3 cache. If the hot path spills to main memory on every invocation, latency degrades dramatically. This constrains both the code size (keeping the matching loop tight and branchless where possible) and the data footprint per book.

**NUMA awareness.** On multi-socket servers, accessing memory attached to a remote socket costs 2–3x more than local memory. Exchange engines pin each matching thread to a specific CPU core and ensure that the order books it manages reside in the same NUMA node's memory.

**Branch prediction and prefetching.** Critical paths are written to minimise unpredictable branches. Where future memory accesses are known (e.g. walking a price-level queue), software prefetch instructions are inserted manually so data arrives in cache before it is needed.

#### How real exchanges achieve speed

**Single-threaded-per-book design.** Rather than using locks to protect a shared book from concurrent access, most production exchanges assign each order book to exactly one thread (or one core). All messages for that symbol are routed through a single sequencer thread. This eliminates lock contention entirely, which is the single largest source of latency variance in concurrent systems.

**Kernel bypass networking (DPDK / FPGA NICs).** The operating system's network stack adds 5–15μs of latency per packet. Exchanges bypass the kernel entirely using user-space networking frameworks (like DPDK or Solarflare's OpenOnload) or offload protocol parsing to FPGA-based network cards. Messages arrive directly in user-space memory, often with hardware timestamps accurate to nanoseconds.

**Busy-polling instead of interrupts.** Rather than sleeping and waiting for an interrupt when no message is pending, the matching thread continuously polls the network ring buffer. This trades CPU power for lower latency: when a message arrives, processing begins within nanoseconds rather than waiting for an interrupt-to-thread-wake cycle (~2–5μs).

**FPGA and ASIC acceleration.** Some exchanges (and many trading firms) implement parts of the matching logic or the entire order book in FPGAs, achieving sub-microsecond matching latency. The trade-off is development complexity and reduced flexibility for protocol changes.

**Huge pages and locked memory.** Using 2MB or 1GB huge pages reduces TLB (Translation Lookaside Buffer) misses, which are another source of unpredictable latency. Critical memory regions are also locked (mlock) to prevent the OS from swapping them to disk.

**Co-location and deterministic networking.** Exchanges offer co-location services where participants place their servers in the same data centre, with equalised cable lengths to ensure fair, low-latency access. The exchange's own matching infrastructure is connected via cut-through switches with sub-microsecond forwarding latency.

The cumulative effect of these techniques is that a modern exchange can process an order, match it against resting liquidity, update the book, generate execution reports, and publish market data, all in well under 10 microseconds from the moment the network packet arrives.

### The Data Structure in Detail: Three Operations, Step by Step

The principles above describe *what* properties the structure must have. This section shows *how* they fit together, by walking through the three operations that every order book must support, against one concrete arrangement of data structures. The goal is not to prescribe the only correct design, it is to make the abstract complexity claims ("O(1) cancel by pointer", "O(1) best-price access") tangible enough to implement.

**The concrete layout.** We assume the classic arrangement the previous sections described:

- Each **side** (bid, ask) owns a price-indexed map from price to a **price-level** object. For a bounded, fixed-tick instrument this map is a direct-indexed array (price offset → slot); for an unbounded one it is a balanced tree or skip list. Either way, we treat "find the level for price P" as its own step, and note its cost.
- Each **price level** holds a **doubly-linked list** of resting orders in strict time priority: head = oldest (front of queue), tail = newest (back of queue). It also caches its own `total_quantity` so depth queries need not walk the list.
- Each **side** caches a pointer to its **best** price level (`best_bid_level` / `best_ask_level`), so top-of-book access never searches.
- A global **order-ID → order-node** hash map lets a cancel or amend find the exact node in O(1) without knowing its price. Each order node stores back-pointers to its price level and its neighbours in the linked list.

```
Side (ASK)
 ├── best_ask_level ───────────────┐
 ├── price_map: {                   ▼
 │     15035 ──► PriceLevel(150.35, total=1500)
 │                 head► [O:501 q=1000 t=09:31:02] ◄──► [O:502 q=500 t=09:31:40] ◄tail
 │     15036 ──► PriceLevel(150.36, total=2800)
 │                 head► [O:503 q=2800 t=09:30:59] ◄tail
 │   }
 └── ...

order_index: { 501 ► node@150.35, 502 ► node@150.35, 503 ► node@150.36, ... }
```

Every claim of speed in the previous sections is a claim about one of the three walk-throughs that follow.

#### Operation 1: Insert a resting limit order

A limit buy for 400 shares at $150.33 arrives and does **not** cross the ask (we handle the crossing case as Operation 3). It must be filed at the back of the queue for its price level, creating that level if it does not yet exist.

```
function insert_resting(order):                 # order: {id, side, price, qty, ts}
    level = side(order.side).price_map.find(order.price)
    if level is null:
        level = pool.acquire_level(order.price)  # from pre-allocated pool, no malloc
        side(order.side).price_map.insert(order.price, level)
        update_best_pointer_on_insert(order.side, level)   # see note below
    node = pool.acquire_node(order)              # from pre-allocated pool
    list_append_tail(level, node)                # O(1): level.tail.next = node; ...
    level.total_quantity += order.qty            # keep cached depth correct
    order_index[order.id] = node                 # O(1) handle for later cancel/amend
    publish_market_data_add(order.price, order.qty)
```

Cost analysis, tying back to the design principles:

- `price_map.find` / `insert` is the *only* step whose cost depends on the price-map choice: O(1) for a direct-indexed array, O(log n) for a tree. Everything else is strictly O(1).
- `list_append_tail` is O(1) because the level caches its tail pointer, this is why time priority (append at back) is cheap while price improvement (a new best level) is handled purely by the best-pointer update.
- `update_best_pointer_on_insert` compares the new level's price to the current best on that side and, for a buy, replaces `best_bid_level` only if the new price is higher (for a sell, only if lower). This is the entire cost of a new order improving the top of book, one comparison, no search.
- Both `acquire_level` and `acquire_node` come from startup-allocated pools, honouring "no allocation on the hot path."

#### Operation 2: Cancel a resting order

Cancellation is the most common message type in modern markets, so it must be the cheapest. This is exactly what the order-ID index and the doubly-linked list buy us:

```
function cancel(order_id):
    node = order_index.get(order_id)
    if node is null: return REJECT_UNKNOWN_ORDER     # already filled/cancelled
    level = node.level
    list_unlink(node)                 # O(1): node.prev.next = node.next; node.next.prev = node.prev
    level.total_quantity -= node.qty
    order_index.remove(order_id)
    publish_market_data_delete(level.price, node.qty)
    if list_is_empty(level):
        side(node.side).price_map.remove(level.price)
        if side(node.side).best_pointer == level:
            recompute_best_pointer(node.side)   # only when the *best* level empties
        pool.release_level(level)
    pool.release_node(node)
```

The critical detail is `list_unlink`: because the list is *doubly* linked and the node holds pointers to both neighbours, removal is a couple of pointer writes with no traversal, regardless of where in the queue the order sat. A singly-linked list would force an O(queue-length) walk to find the predecessor, which is why the doubly-linked list is not a stylistic preference but a requirement. Note also that `recompute_best_pointer`, potentially the most expensive step, runs *only* when the level that emptied was itself the best on its side; a cancel deep in the book never touches the best pointer.

#### Operation 3: An aggressive order sweeps the book

Now the case that generates trades. A market (or marketable-limit) buy for 3,500 shares arrives against the ask side. It must consume resting liquidity from best price outward, in time priority within each level, until filled or until it runs out of book (or, for a limit, out of acceptable price).

```
function match_aggressive_buy(incoming):        # incoming: {qty, limit_price or ∞ for market}
    while incoming.qty > 0:
        level = ask_side.best_ask_level
        if level is null: break                       # book exhausted on this side
        if incoming.limit_price < level.price: break  # limit no longer marketable
        node = level.head                             # oldest order first: time priority
        while node is not null and incoming.qty > 0:
            traded = min(incoming.qty, node.qty)
            emit_trade(buyer=incoming, seller=node, price=level.price, qty=traded)
            incoming.qty     -= traded
            node.qty         -= traded
            level.total_quantity -= traded
            if node.qty == 0:                         # resting order fully filled
                next_node = node.next
                list_unlink(node)
                order_index.remove(node.id)
                pool.release_node(node)
                node = next_node
            else:
                node = node                           # partial fill of resting order; sweep stops here
                break
        if list_is_empty(level):
            ask_side.price_map.remove(level.price)
            pool.release_level(level)
            recompute_best_pointer(ASK)               # advance to next-best level
    if incoming.qty > 0 and incoming.is_limit:
        insert_resting(incoming)                      # unfilled remainder rests (Operation 1)
```

Trace it against the book from the start of this chapter, best ask $150.35 × 1,500, next $150.36 × 2,800:

1. `level` = $150.35. `traded = min(3500, 1500) = 1500`. Trade printed at **$150.35**. Incoming now needs 2,000; the level empties, is released, best pointer advances.
2. `level` = $150.36. `traded = min(2000, 2800) = 2000`. Trade printed at **$150.36**. Incoming is filled. The $150.36 level keeps 800 shares and becomes the new best ask.

Two properties of this loop are worth making explicit because both were asserted earlier in the chapter without proof:

- **Every fill in a sweep can print at a different price** (here $150.35 then $150.36). The single-price rule is a property of *auctions* (covered later), never of continuous sweeps, this loop is precisely where "market impact" and "slippage" come from.
- **The inner loop preserves time priority**: it always starts at `level.head`, the oldest order, and a partial fill of a resting order (`node.qty > 0` after trading) *stops* the sweep, because if the incoming order could not consume even the front order at this level, it certainly cannot reach the orders behind it. The remaining incoming quantity then either rests (limit) or is done (market).

> **Key idea:** The three operations, insert, cancel, sweep, are the entire contract of an order book, and each one's cost is dominated by a single step: the price-map lookup on insert, the pointer unlink on cancel, and the level-by-level walk on sweep. Every optimisation in the preceding sections (best-price pointers, doubly-linked queues, the order-ID index, pooled allocation) exists to make exactly one of those steps constant time. If you can implement these three functions with the costs annotated above, you have implemented the core of a matching engine; everything else is order types, risk checks, and protocol.

#### A note on determinism

Nothing in the three functions above reads a clock, consults a random source, or depends on iteration order of a hash map during matching (the `order_index` is used only for direct point lookups, never iterated during a match). This is deliberate, and it is what makes the engine replayable in the sense the *Determinism, Replay, and Persistence* chapter requires: given the same book state and the same ordered input, these functions produce identical trades in identical order. Introducing, say, a `map` whose iteration order varies between runs, or reading wall-clock time to break a tie, would silently destroy that guarantee.

### The Spread

The **spread** is the gap between the best bid (highest buy offer) and the best ask (lowest sell offer). If the best bid is $150.30 and the best ask is $150.35, the spread is $0.05.

The spread represents the immediate cost of trading: if you need to buy right now, you pay the ask price; if you need to sell right now, you receive the bid price. The round-trip cost of buying and immediately selling is the spread.

A **tight spread** (small gap) indicates a liquid, efficiently-priced market. A **wide spread** indicates illiquidity, less competition between market participants, higher trading costs. Market makers earn the spread: they buy at the bid and sell at the ask, pocketing the difference.

The **mid price** is the arithmetic average of the best bid and best ask: (150.30 + 150.35) / 2 = $150.325. This is often used as the "current price" of an instrument when no trade has occurred recently.

### Depth

**Depth** refers to how much quantity is resting at each price level. A market with 50,000 shares resting within $0.05 of the best bid is "deep", you can trade a large size without moving the price much. A market with only 100 shares available near the best price is "shallow", a single large order will sweep through multiple price levels.

**Level 1 data** shows only the best bid price, best ask price, and quantities. **Level 2 data** (also called **market depth** or the full order book) shows all resting price levels. Professional traders subscribe to Level 2 data because depth reveals information about near-term price pressure.

### Measuring Depth

Depth is not a single number, it is a shape. Practitioners and algorithms use several derived measures to quantify it for different purposes.

**Quantity at a price level.** The simplest measure: the total resting quantity at a single specific price. If there are three sell orders at $150.35 for 200, 500, and 300 shares respectively, the quantity at $150.35 is 1,000 shares. This is what Level 2 data shows at each row. (Note that this is exactly the `level.total_quantity` field the implementation above maintains incrementally, precisely so this query never walks the queue.)

**Cumulative depth within N ticks.** More useful than a single level is knowing how much total quantity is available within a price range. If AAPL has a best ask of $150.35 and you sum all resting ask quantities from $150.35 to $150.45 (10 ticks), you get the total shares you could buy while moving the price at most 10 cents. A large cumulative depth within a few ticks indicates a resilient, liquid market; a small cumulative depth means a single large order will sweep many levels quickly.

**Bid-ask imbalance (depth ratio).** Compare the total resting quantity on the bid side to the total on the ask side, within some symmetric window around the mid price:

```
Imbalance = bid_depth / (bid_depth + ask_depth)
```

A value of 0.5 means the book is balanced, roughly equal buying and selling interest. A value near 1.0 means the bid side is much heavier: many buyers, few sellers. This is often interpreted as short-term upward price pressure. A value near 0.0 means the ask side is dominant: selling pressure. Market microstructure research consistently finds that order book imbalance is a short-term predictor of price direction. Many trading algorithms compute it as a continuous signal.

**Market impact estimation.** Given a target order size S, you can compute the *average price* you would pay by sweeping through the book level by level. If you want to buy 5,000 shares and the book is:

| Ask price | Qty |
|---|---|
| $150.35 | 2,000 |
| $150.40 | 1,500 |
| $150.45 | 2,000 |

Your 5,000-share buy sweeps all three levels: 2,000 at $150.35, 1,500 at $150.40, 1,500 at $150.45. The volume-weighted average price is:

```
VWAP = (2000 × 150.35 + 1500 × 150.40 + 1500 × 150.45) / 5000 = $150.395
```

The **market impact** is the difference between this average and the initial best ask: $150.395 − $150.35 = $0.045 per share. Depth data lets a trader estimate their market impact before submitting, which is critical for execution strategy: split into smaller orders, use an iceberg, route to a dark pool, or simply accept the impact if time pressure is high. (This calculation is Operation 3 above, run as a read-only simulation against a copy of the book, rather than an actual match.)

**Available depth at cost.** The inverse of the above: given a maximum acceptable average price (or maximum price movement), how large an order can you execute within that budget? This is how automated execution algorithms compute optimal slice sizes.

**Volume-at-touch vs total book depth.** A useful distinction: *volume at touch* is only the best bid and ask (Level 1). *Total book depth* includes all visible levels. An iceberg order contributes only its visible peak to displayed depth, so total book depth may understate available liquidity if icebergs are present. This is why dark pool liquidity (invisible until matched) and iceberg reserves (invisible until refreshed) are relevant even to participants who believe they can read the full book.

### Price Levels

A **price level** is a single specific price at which one or more orders are resting. All orders at $150.30 form one price level on the bid side. When all orders at a given price level have been filled or cancelled, that price level disappears from the book. (In the implementation above, this is the `pool.release_level` step, and it is also the moment the best pointer may need to advance.)

### The Order Book Is Not the Market Price

This is a subtle but important point: the order book shows only **resting orders**, orders that have not yet traded. The current market price, as quoted in news tickers and trading apps, is typically the price of the **most recent actual trade**, not the price of any resting order. After a trade happens, the market price updates. Between trades, the price is conventionally shown as the mid of the book.

This means there are actually several distinct "prices" in play at any moment, each used for a different purpose:

**Last trade price.** The price at which the most recent fill occurred. This is what scrolling tickers and trading screens display as the "current price" during the session. It updates with every fill, potentially many times per second in a liquid market.

**Mid price.** The average of the best bid and best ask: (best_bid + best_ask) / 2. Used as a proxy for fair value between trades, particularly when no trade has occurred for a while. Derived from the book, not from any actual transaction.

**Previous day's closing price.** Once the session ends, the **official closing price** from the closing auction becomes the reference price for the entire period the market is closed, typically overnight and across weekends. This is the price used to value portfolios at end of day, to calculate overnight P&L, to set the reference for the next day's static price collars, and to publish the figures that appear in newspapers, financial reports, and fund valuations.

> **Closing Auction and Static Price Collar**
>
> Two terms in that paragraph will be unfamiliar at this point in the document, so a brief preview is warranted.
>
> The **closing auction** is a special matching procedure that runs at the end of the trading day: rather than matching orders one at a time as they arrive, the exchange collects all outstanding buy and sell interest over a short accumulation period and then computes the single price at which the greatest number of shares can trade simultaneously, matching all eligible orders at that one price. This produces a more authoritative closing price than simply taking the last trade of continuous trading, which might have been a small or unusual transaction. The closing auction is covered in full in the *Opening and Closing Auction* section of Part II.
>
> A **static price collar** (also called a fat-finger filter) is a pre-trade risk control that rejects any incoming order whose submitted price strays too far from the previous closing price, protecting against obvious entry errors such as a misplaced decimal point. Because it uses the closing price as its benchmark, it must be recalculated at the start of each new session. Static price collars are covered in full in the *Trading Sessions* section of Part II.

The closing price carries particular weight precisely because it is independently determined by a transparent auction process rather than by a single trade that could be anomalous or thin. A portfolio worth $10 million at 3:59pm might be marked at a slightly different value at 4:00pm if the closing auction produced a different price, but that closing price is considered more authoritative because it reflects the broadest simultaneous expression of supply and demand at that moment of the day.

For exchange developers, the closing price has several concrete implications. It is the reference that the static price collar compares each new day's orders against. It is the benchmark that performance reports are measured against. It is the number that triggers overnight margin calls if positions have moved far enough. And it is the price that must be persisted at end of session, broadcast to all downstream systems, and made available when the exchange reopens the following morning.

### What the World Sees vs What the Engine Knows

Most market participants see only an **aggregated view** of the book: total quantity at each price level, without knowing how many individual orders make up that quantity or who placed them. The exchange itself knows the full detail, every individual order, its owner, its arrival time, its type. Publishing the aggregated view is part of the exchange's **market data** service; it's how participants observe the market. (The engine's private, per-order detail is exactly the doubly-linked queue of nodes from the implementation section; the public aggregated view is the `total_quantity` per level. The two are kept consistent by updating the cached total on every insert, cancel, and fill.)

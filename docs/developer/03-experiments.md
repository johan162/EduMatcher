# Exchange Experiments Roadmap

This page proposes 15 hands-on experiments that close key gaps between EduMatcher and production exchanges, plus one suggested extension.

Each experiment uses the same format:

- Background
- Financial explanation and motivation (with definitions of all new terms)
- Technical details (scope, outcome, verification)
- Learning objective

The list is ordered from basic to very complex.

## How to use this page

1. Pick one experiment at a time.
2. Define acceptance criteria before coding.
3. Add tests first when possible.
4. Run the full quality gate after each change.
5. Keep a short implementation log with assumptions and tradeoffs.



## Experiment 1: Price-Time Priority Audit Trace

**Status: Still Valid**

Difficulty: Basic
Estimated effort: Less than 1 day
Gap vs real exchange: Real venues provide deterministic post-trade replay and explainability tooling.

Background:
Matching is deterministic, but learners often cannot explain why one order filled before another at the same price.

Financial explanation and motivation:

New terms:

- **Queue position**: The rank of a resting order among all orders at the same price on the same side. Orders that arrived earlier have a better (lower) rank and therefore have priority when a matching counterpart arrives.
- **Fill priority**: The sequencing rule applied at match time. Price-time priority means: best price first, and among orders at the same price, earliest arrival time first.
- **Alpha** (colloquial): A trader's statistical edge — any characteristic that improves their probability of profitable execution. In queue-based markets, a better queue position is itself a form of alpha because it raises fill probability at the target price without changing the price at all.
- **Adverse selection**: The risk that a fill occurs precisely because the counterpart has better information. An order that gets filled by an informed incoming order may find the price moves against the resting side immediately afterward. Understanding queue rank helps reason about when adverse selection is more or less likely.
- **Execution quality**: How closely an actual fill matches the trader's intended price, timing, and quantity. Better queue position tends to improve execution quality because fills happen at the intended price before the market moves.

Queue position is critical in electronic markets because many participants post limit orders at the same price. Being first in queue means your order is matched first when a counterpart arrives. Those at the back of the queue may not be filled at all if the incoming order is smaller than the combined queue depth.

Technical details:

- Add `trace_mode: bool` to engine config. When false, no tracing logic runs and behavior is identical to today.
- At match time, for each candidate resting order evaluated during a single matching cycle, emit a `match.trace` event with fields: `order_id` (str), `price_key` (str decimal), `time_key` (int, monotonic sequence), `side` (str), `was_selected` (bool).
- The selected order emits `was_selected: true`. All other candidates evaluated in the same cycle emit `was_selected: false`.
- Trace events are published to the audit channel before the corresponding `trade.executed` event for the same match.
- The sequence of trace events within one matching cycle must be ordered by `time_key`.

Expected outcome:
A student can reconstruct exactly why each fill happened and which queue rule was decisive.

How to verify:

- Unit test: submit two same-price limit buy orders in sequence (order A then order B), then one sell order that fills only order A. Assert A has `was_selected: true` and B has `was_selected: false`.
- Schema test: serialize one `match.trace` event to JSON and lock the exact field names and types in a snapshot test.
- Regression test: run the same scenario with `trace_mode: false` and assert fill events are identical to baseline (no extra events emitted).

Learning objective:
Understand deterministic matching and queue priority mechanics at a forensic level.



## Experiment 2: Exchange Tick-Size Regime per Symbol

**Status: Partially Implemented — Phase 2 Enhancement**

*Current state*: `tick_decimals` per symbol exists in config. New work: add `tick_size` (exact increment), variable-tick bands, and price validation.

Difficulty: Basic
Estimated effort: 1 to 2 days
Gap vs real exchange: Production exchanges enforce symbol-specific tick tables.

Background:
Current pricing accepts flexible decimal values, but real symbols trade only on valid increments.

Tick concept (new terms):

- A **tick** is the minimum allowed price movement for an instrument. It is the atomic unit of price on that venue for that symbol.
- **Tick size** is the numeric value of that minimum increment (for example `0.01`).
- If tick size is `0.01`, valid prices include `100.00`, `100.01`, `100.02`; invalid examples include `100.005`.
- In general, a price P is valid when `(P - reference_price) mod tick_size == 0`.
- **Bid**: A standing offer to buy at a specified price. The best bid is the highest price any buyer is currently willing to pay.
- **Ask (offer)**: A standing offer to sell at a specified price. The best ask is the lowest price any seller is currently willing to accept.
- **Spread**: The difference between the best ask and best bid. A narrow spread means lower round-trip cost for traders who need to both buy and sell.
- **Depth**: The quantity available at each price level in the order book, not just the best bid and ask.
- **Market maker**: A participant who continuously posts both a bid and an ask, earning the spread as compensation for providing liquidity. Market makers are sensitive to tick size because it defines the minimum spread they can quote.

Why exchanges enforce this:

- It standardizes price competition and prevents fractional undercutting noise.
- It improves queue fairness by forcing participants to compete in meaningful increments.
- It directly shapes spread and liquidity depth.

Financial explanation and motivation:
Tick size is a deliberate market design parameter. Larger tick sizes widen spreads and concentrate depth at fewer price levels, making queue position more valuable. Smaller tick sizes tighten spreads but fragment liquidity across more levels. Market makers, latency traders, and execution algorithms all adapt their behavior when tick regimes change.

Technical details:

- Extend symbol config with `tick_size: Decimal` (required, no default) and optional `tick_bands: list[{from_price, to_price, tick_size}]` for variable-tick regimes.
- Validate price in the NEW order path, AMEND path, stop-limit trigger price, and iceberg limit price, all using the same `is_valid_tick(price, symbol_config)` function.
- Reject invalid prices with reason code `INVALID_TICK` and include `{price, tick_size, symbol}` in the reject payload.
- Implement `is_valid_tick` using integer arithmetic: multiply both `price` and `tick_size` by a common scale factor to make them integers, then check divisibility. Do not use floating-point modulo.

Expected outcome:
Invalid price steps are blocked; valid prices align to venue rules.

How to verify:

- Parametric tests: for each of three symbols with different tick sizes (`0.01`, `0.25`, `0.50`), test at least one valid and two invalid price values on NEW and AMEND paths.
- Test stop-limit trigger price and iceberg limit price separately.
- Verify reject payload contains `symbol`, `price`, and `tick_size`.
- Verify existing valid orders on all paths are unaffected.

Learning objective:
See how market design constraints shape order entry and liquidity formation.



## Experiment 3: Session-Aware Order Entry Policy Matrix

**Status: Partially Implemented — Phase 2 Enhancement**

*Current state*: Session states (PRE_OPEN, OPENING_AUCTION, CONTINUOUS, CLOSING_AUCTION, CLOSED) and phase checking exist. New work: add per-phase admissibility matrix for (order_type, TIF) combinations.

Difficulty: Basic
Estimated effort: 1 to 2 days
Gap vs real exchange: Venues apply strict policy by phase (pre-open, auction, continuous, close).

Background:
The scheduler changes phases, but policy granularity can be expanded to reflect real venue behavior.

Financial explanation and motivation:

New terms:

- **Session phase**: A distinct period of the trading day with different rules for what can be submitted and matched. The five standard phases are:
    - `pre-open`: orders may be entered but no matching occurs; the book is being populated.
    - `auction`: orders are collected for a batch match; continuous matching is suspended.
    - `continuous`: normal order-by-order matching, the most common intra-day state.
    - `close`: wind-down period with restricted entry; typically only limit orders are accepted.
    - `halt`: all activity is frozen, usually due to a news event or circuit breaker.
- **TIF (Time-In-Force)**: The policy controlling how long an order remains active. Common values: `DAY` (expires at session end), `GTC` (Good Till Cancelled, survives across sessions), `IOC` (Immediate-or-Cancel: fill what you can right now, cancel any unfilled remainder), `FOK` (Fill-or-Kill: fill the entire quantity immediately or cancel entirely).
- **Order admissibility**: Whether a given order type + TIF combination is permitted during a given phase. For example, Market orders are blocked during pre-open because no reference price exists for a fair execution.
- **Opening volatility**: The price instability at the start of the continuous session, caused by accumulated overnight orders. Session policies reduce this risk by restricting the most unpredictable order types until the auction establishes an opening price.

A session policy matrix defines admissibility as a two-dimensional table: rows are session phases, columns are (order-type, TIF) combinations, and cells are ALLOW or DENY. Real exchanges publish these tables in their rulebooks.

Example partial matrix:

| Phase      | Market/DAY | Limit/DAY | Limit/GTC | Market/IOC |
|------------|-----------|-----------|-----------|------------|
| pre-open   | DENY      | ALLOW     | ALLOW     | DENY       |
| auction    | DENY      | ALLOW     | ALLOW     | DENY       |
| continuous | ALLOW     | ALLOW     | ALLOW     | ALLOW      |
| close      | DENY      | ALLOW     | DENY      | DENY       |
| halt       | DENY      | DENY      | DENY      | DENY       |

Technical details:

- Define a `session_policy` config section: a mapping from phase name to a list of allowed `(order_type, tif)` pairs. Anything not listed is denied (allowlist approach).
- Enforce in engine validation before any book processing or risk checks.
- Reject with reason code `PHASE_POLICY_VIOLATION` and include `{phase, order_type, tif}` in the reject payload.
- Policy is evaluated at each phase transition without restarting the engine.

Expected outcome:
Different order classes are accepted or rejected according to phase; policy violations produce informative rejects.

How to verify:

- Transition programmatically through all five phases in tests.
- For each phase, test at least one ALLOW and one DENY combination from the matrix.
- Verify reject payload contains `phase`, `order_type`, and `tif`.
- Verify existing passing combinations in `continuous` phase are unaffected.

Learning objective:
Understand how session design controls market behavior and participant risk.



## Experiment 4: Per-Gateway Rate Limits and Burst Controls

**Status: Still Valid**

Difficulty: Intermediate
Estimated effort: 1 to 2 days
Gap vs real exchange: Real gateways enforce throughput and abuse controls.

Background:
Bot and human gateways can currently submit at very high rates without any throttle.

Financial explanation and motivation:

New terms:

- **Throughput**: The number of messages (orders, amends, cancels) per unit time that a gateway is permitted to send to the exchange.
- **Burst**: A short-duration spike in submission rate above the sustained throughput limit. Real exchanges allow moderate bursts to accommodate legitimate clustering of events (e.g., a strategy responding to news).
- **Token bucket**: A rate-limiting algorithm. A bucket holds up to `capacity` tokens. Tokens refill at `refill_rate` tokens per `refill_interval_ms`. Each incoming message consumes one token. If the bucket is empty, the message is rejected or queued depending on policy. This allows bursts up to `capacity` while limiting the sustained rate to `refill_rate / refill_interval_ms` messages per millisecond.
- **Queue stuffing**: A manipulative tactic where a participant floods the exchange with orders and cancels in rapid succession with no real intent to trade, in order to slow down competitor systems and exchange processing. Prohibited by most regulators.
- **Fair access**: The principle that all market participants have equal opportunity to submit orders within their entitlements, without one participant's volume degrading the service seen by others.

Rate limits protect fair access and market stability. Without them, a single misbehaving participant — or a bug in a trading algorithm — can degrade exchange performance for all others.

Technical details:

- Add a `rate_limit` config section per gateway with fields: `capacity` (int, maximum burst tokens), `refill_rate` (int, tokens added per interval), `refill_interval_ms` (int), `policy` (str: `reject` or `delay`).
- Track NEW, AMEND, and CANCEL message types against a single shared bucket per gateway (configurable to separate buckets per type).
- On empty bucket: `reject` policy emits a `RATE_LIMIT_EXCEEDED` reject immediately; `delay` policy queues the message until a token is available, up to a `max_queue_depth`; overflow beyond that is rejected.
- Expose per-gateway counters via the stats channel: `tokens_remaining`, `messages_accepted`, `messages_rejected`, `messages_delayed`.
- Bucket state resets at each session start.

Expected outcome:
Gateway behavior is constrained to configured throughput with observability; under-limit flow is unaffected.

How to verify:

- Stress test: submit 2× the bucket `capacity` in a single burst. Assert exactly `capacity` messages are accepted and the rest are rejected (reject policy).
- Verify counter values match accepted and rejected counts exactly.
- Verify under-limit flow (sending at the refill rate) produces zero rejections over a sustained window.
- Refill test: exhaust the bucket, wait one `refill_interval_ms`, confirm exactly one more message is accepted.

Learning objective:
Learn the tradeoff between open access, fairness, and operational safety.



## Experiment 5: Fee and Rebate Model (Maker-Taker)

**Status: Still Valid**

Difficulty: Intermediate
Estimated effort: 1 to 2 days
Gap vs real exchange: Real venues expose fee schedules that alter trader behavior.

Background:
Clearing currently tracks profit and loss without exchange fee microstructure.

Financial explanation and motivation:

New terms:

- **PnL (Profit and Loss)**: The net financial result of trading activity. **Gross PnL** is computed solely from fill prices and quantities (buy-sell price difference times quantity). **Net PnL** is gross PnL minus all fees paid plus all rebates received.
- **Liquidity**: The ease with which a participant can buy or sell without significantly moving the price. High liquidity means tight spreads and large available quantities.
- **Maker**: An order that *adds* liquidity to the book. A limit order that does not immediately match rests passively; when it is later filled by an incoming order, it is the maker side of that trade.
- **Taker**: An order that *removes* liquidity from the book. Any order that matches immediately — market orders, or limit orders aggressive enough to cross the spread — is the taker side.
- **Maker rebate**: A payment made by the exchange *to* the maker. The exchange pays this rebate to incentivize participants to post resting orders and provide continuous liquidity.
- **Taker fee**: A charge levied by the exchange *on* the taker. It is the primary revenue source for exchanges using the maker-taker model. The taker fee is typically larger than the maker rebate, and the difference is the exchange's margin.
- **Notional value**: The total monetary value of a trade: `price × quantity`. Fee rates are applied to this figure.
- **Fee schedule**: The table of fee and rebate rates, typically expressed as a fraction of notional value. For example, a taker rate of `0.0030` means 0.30% of trade notional.

Example calculation: taker rate `0.0030`, maker rate `-0.0010` (negative = rebate). Fill of 100 shares at $50.00 (notional $5,000):

- Taker pays: $5,000 × 0.0030 = **$15.00 fee**
- Maker receives: $5,000 × 0.0010 = **$5.00 rebate** (a credit, not a charge)

Fee structures change strategy incentives. A maker rebate encourages posting passive limit orders. A taker fee discourages aggressive flow unless the price signal is strong enough to justify the cost.

Technical details:

- Add `fee_schedule` section to symbol config with fields: `taker_rate: Decimal`, `maker_rate: Decimal`. A negative `maker_rate` means a rebate (credit to the participant).
- Compute fees at fill time in clearing. For each fill event: `fee = price * qty * rate`, where rate is `taker_rate` for the aggressor side and `maker_rate` for the resting side.
- Extend the clearing fill record and session report with: `gross_pnl`, `fee_charged` (positive = paid by participant), `rebate_received`, `net_pnl`.
- Fees accumulate per participant per session.
- When `fee_schedule` is absent for a symbol, behavior is identical to today (zero fees, backward compatible).

Expected outcome:
Net PnL differs from gross PnL when fees are active; fee-free mode remains backward compatible.

How to verify:

- Controlled scenario: one maker and one taker, known fill price and quantity. Assert `fee_charged` and `rebate_received` match hand calculations to full decimal precision.
- Verify maker-side rebate produces a negative `fee_charged` (a credit).
- Verify taker-side fee increases total cost above the raw execution price.
- Run with no `fee_schedule` and assert all fee fields are zero and gross PnL is unchanged.

Learning objective:
Understand execution economics beyond simple price and quantity.



## Experiment 6: Realistic Cancel/Amend Latency Simulation

**Status: Still Valid**

Difficulty: Intermediate
Estimated effort: 1 to 2 days
Gap vs real exchange: Matching systems have non-zero network and processing latency.

Background:
Immediate local execution can mask race conditions that dominate live markets.

Financial explanation and motivation:

New terms:

- **Latency**: The time delay between sending a message (order, cancel, amend) and the exchange processing it. In production this is measured in microseconds to low milliseconds.
- **Cancel latency risk**: The risk that a cancel request arrives at the engine *after* the order has already been filled, because a matching counterpart arrived in the same narrow time window. The cancel "loses the race" and the fill stands.
- **Quote fade**: When a passive resting order is cancelled just before an incoming aggressive order would have matched it. From the aggressor's perspective, the liquidity appeared to be there but vanished. Quote fade is a significant friction in fast markets.
- **Race condition**: A situation where the final outcome depends on the relative timing of two or more independent events. Cancel-vs-fill races are a major source of operational risk in live trading systems.
- **Adverse selection (HFT context)**: When a fill occurs specifically because an informed participant's order arrived faster than the resting side's cancel. The resting participant is "picked off" — filled at a price that immediately moves against them.

In a local simulation, all messages are processed in strict submission order with zero delay. This hides behavioral differences that are important in production: a cancel submitted 200µs before an aggressive order might arrive *after* it if the aggressive order takes a faster network path.

Technical details:

- Add optional `latency_simulation` config section with fields: `enabled: bool`, `distribution: str` (one of `uniform`, `normal`, `lognormal`), `min_ms: float`, `max_ms: float`, `mean_ms: float`, `stddev_ms: float`, `seed: int`.
- Implement as a message-queue wrapper: each incoming message is timestamped on arrival and held for a delay drawn from the configured distribution. The internal queue processes messages in timestamp-order (earliest delivery time first).
- Provide three named presets selectable by `profile` string: `low` (uniform 0.1–1ms), `medium` (uniform 1–20ms), `stressed` (uniform 10–200ms). Individual field values override presets.
- Use `seed` for fully reproducible replays: the same seed always produces the same delay sequence.
- When `enabled: false`, all messages are processed in submission order as today, with no timing overhead.

Expected outcome:
Race conditions become observable and repeatable; strategy robustness can be measured under different latency profiles.

How to verify:

- Seeded determinism test: run the same scenario twice with the same seed and assert fill outcomes are identical.
- Bounds test: over 10,000 draws, confirm no delay falls outside `[min_ms, max_ms]`.
- Race test: submit a cancel and an aggressive order in sequence; under non-zero latency the race outcome may differ from zero-latency. Assert each mode produces consistent deterministic output.
- Disabled test: run the same scenario with `enabled: false` and assert fill events are byte-identical to the baseline.

Learning objective:
See how latency changes strategy outcomes and risk exposure.



## Experiment 7: Full Order State Machine with Reason Codes

**Status: Partially Implemented — Phase 2 Enhancement**

*Current state*: Order status enum (NEW, PARTIAL, FILLED, CANCELLED, REJECTED, EXPIRED) exists. New work: formalize state transition table, validate transitions, add machine-readable reason codes on all lifecycle events.

Difficulty: Intermediate
Estimated effort: 1 to 3 days
Gap vs real exchange: Real systems standardize lifecycle states and reject codes.

Background:
Order status is present, but lifecycle transitions can be made more explicit, exhaustive, and auditable.

Financial explanation and motivation:

New terms:

- **Order state machine**: A formal description of all states an order can be in and all permitted transitions between them. A state machine prevents illegal combinations such as amending a fully-filled order.
- **Terminal state**: A state from which no further transitions are possible. `FILLED`, `CANCELLED`, `EXPIRED`, and `REJECTED` are all terminal. Once an order reaches a terminal state it cannot be modified.
- **Reason code**: A machine-readable string attached to terminal or exceptional transitions, explaining why the transition occurred. Examples: `CANCELLED_BY_USER`, `EXPIRED_SESSION_END`, `REJECTED_INVALID_TICK`. Reason codes allow automated systems to handle each case correctly without parsing free-text messages.
- **Partial fill**: A state where an order has been matched for less than its full quantity and continues to rest in the book for the remainder. The partially-filled state is not terminal.
- **Reconciliation**: The process of comparing two independent records to verify they agree. An operations team reconciles their internal order records against the exchange's records to confirm every order reached a known terminal state and no fills are missing. Stable reason codes make this comparison unambiguous.

Valid state progression (all paths must terminate):

```
NEW → ACKNOWLEDGED → ACTIVE → FILLED (terminal)
                   → PARTIALLY_FILLED → FILLED (terminal)
                   → PARTIALLY_FILLED → CANCELLED (terminal, filled-qty preserved)
                   → CANCELLED (terminal)
                   → EXPIRED (terminal)
NEW → REJECTED (terminal)
```

Illegal transitions that must be blocked: amend on any terminal order, cancel on a rejected order, fill on a cancelled order.

Technical details:

- Introduce an `OrderState` enum containing all states listed above.
- Add a `transition(order, new_state, reason_code)` function that validates the proposed transition against an allowable-transitions table. Raise `InvalidStateTransition` if the transition is not permitted.
- All engine handlers that mutate order state must call `transition()` rather than setting state directly.
- Emit reason codes in all state-change events: ACK, FILL, CANCEL, EXPIRE, REJECT.
- Reason code format: `SCREAMING_SNAKE_CASE`, max 64 characters, stable across versions (never rename a code that has shipped).

Expected outcome:
Orders always follow valid state paths; all terminal transitions carry a machine-parseable reason code.

How to verify:

- Transition matrix test: for every (current_state, new_state) pair, assert `transition()` either succeeds or raises `InvalidStateTransition` as expected per the table.
- Integration tests across: amend (active → active), partial fill, cancel after partial fill, session expiry.
- Snapshot test: lock all reason code strings so accidental renames are caught in CI.
- Illegal transition test: attempt to fill a cancelled order and assert `InvalidStateTransition` is raised.

Learning objective:
Understand order lifecycle reliability and protocol discipline.



## Experiment 8: Market Data Channel Separation (Level 1 vs Level 2)

**Status: Partially Implemented — Phase 2 Enhancement**

*Current state*: Depth metrics via `depth_snapshot()` and `encode(f"depth.{symbol}", depth)` publication exist. New work: introduce formal `book.l1.*` and `book.l2.*` topic namespaces with contract-enforced payloads, configurable publish cadence, and sequence counters per channel.

Difficulty: Intermediate
Estimated effort: 2 to 3 days
Gap vs real exchange: Production venues separate feed products and entitlement tiers.

Background:
Current subscribers consume broad book topics with a single payload format, receiving more data than many consumers need.

Financial explanation and motivation:

New terms:

- **Level 1 data** (top-of-book): The minimum market data product. It contains only four values per symbol: best bid price, best bid quantity, best ask price, and best ask quantity. Sufficient for most simple strategies and retail display.
- **Level 2 data** (market depth): The full order book at all available price levels. Each entry lists a price level, the total quantity of all resting orders at that price, and the count of those orders. Essential for market makers and execution algorithms that need to see where liquidity is concentrated.
- **Top-of-book**: The single best price on each side (highest bid, lowest ask). Level 1 carries only this.
- **Depth**: All price levels beyond the best bid and ask, showing available liquidity at each increment.
- **Entitlement tier**: A subscription category that controls which data products a participant receives. Level 1 is cheap and widely distributed; Level 2 is more expensive and used by professionals. Separate channels allow the exchange to enforce and monetize this distinction.
- **Strategy edge from depth data**: Knowing that a large resting order sits three ticks below the best bid can inform execution decisions — it signals a likely price support level. This information is not available from Level 1 alone.

Technical details:

- Define two topic namespaces: `book.l1.<symbol>` and `book.l2.<symbol>`.
- Level 1 payload schema (7 fields): `{symbol, seq, ts, bid_price, bid_qty, ask_price, ask_qty}`.
- Level 2 payload schema: `{symbol, seq, ts, bids: [{price, qty, count}], asks: [{price, qty, count}]}`. Bids ordered descending by price (best first); asks ordered ascending by price (best first).
- Add `publish_cadence_ms` config per channel: `l1` defaults to publishing on every book change; `l2` defaults to 100ms throttled snapshots.
- Each channel maintains its own sequence counter, starting at 1 each session.
- The existing `book.*` topic continues to function during this transition (deprecated but not removed).

Expected outcome:
Consumers can subscribe to exactly the data product they need; payload size difference between L1 and L2 is measurable.

How to verify:

- Contract test for `book.l1.*`: assert the payload contains exactly the 7 L1 fields and no depth arrays.
- Contract test for `book.l2.*`: assert `bids` and `asks` arrays are present, non-empty, and each array is correctly ordered.
- Size test: run a 100-order scenario and measure the average L1 vs L2 payload byte size.
- Backward compatibility: confirm existing `book.*` subscribers still receive data unchanged.

Learning objective:
Understand market data product design and distribution tradeoffs.



## Experiment 9: User and Account Domain Refactor

**Status: Still Valid**

Difficulty: Complex
Estimated effort: 3 to 5 days
Gap vs real exchange: Venues operate with firm, user, account, and permission hierarchies.

Background:
Gateway ID currently acts as both identity and account boundary. Real exchanges separate these concerns.

Financial explanation and motivation:

New terms:

- **Firm**: The legal entity — broker, market maker, or proprietary trading firm — that has a contractual relationship with the exchange. A firm has one or more trading accounts.
- **Account**: A trading account owned by a firm. Risk limits, positions, fills, and PnL are all tracked at the account level. A firm may have multiple accounts for different desks, strategies, or regulatory purposes.
- **Gateway (connection)**: The network session between a trading system and the exchange. A single account may have multiple gateways for redundancy (so that a network failure on one connection does not halt trading). Multiple accounts at the same firm may also share a single gateway connection.
- **Risk boundary**: The unit at which position limits, notional limits, and loss limits are enforced. Real exchanges enforce at the account level, not the connection level. This means limits apply consistently regardless of which gateway submits the order.
- **Compliance**: The obligation to meet regulatory and exchange rules. Account-level tracking enables the audit trails required by regulators: which account placed which order, when, and for what stated purpose.

The current model conflates connection identity with trading account. This breaks down when a firm runs redundant gateways (both map to the same account and positions should aggregate), or when one gateway needs to manage orders across multiple accounts.

Technical details:

- Introduce an `Account` domain object: `{account_id: str, firm_id: str, gateway_ids: list[str]}`.
- All order messages include `account_id` in addition to `gateway_id`.
- Position tracking, fill records, and PnL reports are keyed by `account_id`, not `gateway_id`.
- Cancel-on-disconnect cancels all open orders whose `account_id` maps to the disconnecting gateway, but only those submitted by that specific gateway (not orders submitted by other gateways on the same account, unless configured differently).
- Authorization: a gateway may only act on `account_id` values listed in its own registration.
- Migration path: if `account_id` is absent in an incoming message, derive it from `gateway_id` using a fallback lookup table (backward compatible with existing configs).

Expected outcome:
Multiple gateways can share one account and positions aggregate correctly; controls apply consistently at the account level.

How to verify:

- Multi-gateway test: two gateways submit orders for the same `account_id`. Assert positions sum at the account level.
- Cancel-on-disconnect test: disconnect one gateway, assert only its orders are cancelled (not orders from the other gateway on the same account).
- Authorization test: a gateway that attempts to submit for an `account_id` it is not registered to is rejected.
- Migration test: a message without `account_id` is accepted and the correct account is derived via fallback.

Learning objective:
Understand how real exchange participants are modeled beyond a single connection ID.



## Experiment 10: Kill Switch and Fat-Finger Controls

**Status: Partially Implemented — Phase 2 Enhancement**

*Current state*: Kill-switch gateway cancellation exists (`_handle_kill_switch()`). New work: hard-stop governance (privileged-only reset), notional value guards (`max_order_notional`), and price-distance guardrails (`max_price_distance_ticks`).

Difficulty: Complex
Estimated effort: 2 to 4 days
Gap vs real exchange: Exchanges and brokers provide hard kill-switch controls.

Background:
Runaway order flow needs immediate containment beyond normal strategy logic.

Financial explanation and motivation:

New terms:

- **Fat-finger error**: An accidental order entry mistake — for example, submitting 1,000,000 shares instead of 1,000, or a price of $0.01 instead of $100.01. Fat-finger events have caused multi-million dollar losses and temporary market disruptions on real venues.
- **Notional value**: The total monetary value of an order: `price × quantity`. A fat-finger check compares this against a configured maximum to catch orders that are impossibly large relative to normal activity.
- **Price distance guardrail**: A check that rejects any order whose price is more than a configured number of ticks away from the current best price (or last trade price). This prevents orders accidentally submitted at the wrong end of the price scale from resting in the book.
- **Kill switch**: An emergency mechanism — triggered by a risk manager or automated monitor — that immediately cancels all open orders for a gateway or account and blocks all further new orders until re-enabled by a privileged source.
- **Hard stop**: A kill-switch state that cannot be reset by the gateway itself. Only a separate privileged process (the risk manager endpoint) can re-enable the gateway. This prevents a buggy algorithm from resetting its own kill switch.

Technical details:

- Add kill-switch state per gateway and per account: `active` (normal) or `killed`.
- Kill switch API: a privileged `KILL` message (distinct from order messages, requires a separate auth token) transitions state to `killed`, triggers immediate cancel-all for all open orders of the target, and blocks all NEW and AMEND messages. Only a `RESET` message from the same privileged source can return to `active`.
- Add `max_order_notional: Decimal` per gateway config. Reject any NEW or AMEND where `price * qty > max_order_notional` with reason code `FAT_FINGER_NOTIONAL`.
- Add `max_price_distance_ticks: int` per symbol config. Reject any order priced more than this many ticks from the last published best price on the same side. Reason code: `FAT_FINGER_PRICE_DISTANCE`.
- Emit a `KILL_SWITCH_TRIGGERED` audit event with: timestamp, target (gateway or account ID), trigger source, and count of orders cancelled.

Expected outcome:
Unsafe flow is stopped instantly and deterministically; every kill and reset action produces a clear audit trail.

How to verify:

- Runaway scenario: submit 50 orders from one gateway, trigger kill switch, assert all 50 open orders are cancelled within one processing cycle and no further orders are accepted.
- Notional test: submit an order with `price * qty > max_order_notional` and assert `FAT_FINGER_NOTIONAL` reject with the correct payload fields.
- Price distance test: submit an order 100 ticks from the best price and assert `FAT_FINGER_PRICE_DISTANCE` reject.
- Hard stop test: confirm the gateway cannot self-reset; confirm a privileged `RESET` message re-enables it.
- Audit test: assert the `KILL_SWITCH_TRIGGERED` event exists with the correct cancelled-order count.

Learning objective:
Learn real-time safety controls used in production trading systems.



## Experiment 11: Drop Copy and Post-Trade Reconciliation Stream

**Status: Partially Implemented — Phase 2 Enhancement**

*Current state*: Drop copy publisher, sequencing, and in-memory replay buffer exist (`DropCopyPublisher`). New work: durable append-only log file, session-scoped rotation, reconciliation tooling for gap detection and quantity validation.

Difficulty: Complex
Estimated effort: 2 to 4 days
Gap vs real exchange: Participants usually consume independent drop copy for control and compliance.

Background:
Execution feedback currently arrives only through strategy-facing channels. There is no independent audit stream.

Financial explanation and motivation:

New terms:

- **Drop copy**: An independent, real-time copy of all order lifecycle events (new, acknowledged, filled, cancelled, expired) sent to a separate consumer. The name comes from the physical practice of "dropping" a carbon copy of each trade ticket for the operations desk. Drop copy is consumed by risk managers, compliance teams, and operations staff who monitor activity without being part of the trading strategy itself.
- **Sequence number**: A monotonically increasing integer assigned to every drop-copy event in order. Recipients use sequence numbers to detect gaps — if event 1042 arrives after 1040, the recipient knows event 1041 is missing and must be requested.
- **Gap detection**: The process of identifying missing events in a numbered sequence. A sequence gap means a fill, cancel, or rejection may have been silently lost, creating a discrepancy between the exchange's record and the participant's record.
- **Reconciliation** (post-trade): The end-of-day (or intra-day) process of comparing a participant's internal trade records against the exchange's official drop-copy records to find any discrepancies. Unresolved discrepancies must be escalated.
- **Durable replay**: The ability to re-read past events from a stored log, in order, to recover state after a crash or fill in a detected gap.

Technical details:

- Add a `dropcopy.*` topic namespace mirroring all order lifecycle events: `dropcopy.new`, `dropcopy.ack`, `dropcopy.fill`, `dropcopy.cancel`, `dropcopy.expire`, `dropcopy.reject`.
- Each drop-copy event includes: `seq` (int, session-global monotonically increasing, starting at 1), `ts` (microsecond timestamp), and the full original event payload unchanged.
- Write all drop-copy events to a durable append-only log file `dropcopy_YYYYMMDD.log` in JSON-lines format (one event per line). The file is closed and renamed at session end.
- Provide a `dropcopy_reconcile.py` utility that reads the log file and a participant's local fill records and outputs three lists: missing events (gap in sequence), duplicate events (seq appears twice), quantity mismatches (fill qty in log differs from local record).
- Sequence numbers reset to 1 at each session start.

Expected outcome:
Operations can verify completeness and detect missing events; the reconciliation utility identifies all gaps in a controlled scenario.

How to verify:

- Submit 100 orders through their full lifecycle. Assert the drop-copy log file contains exactly the expected number of events with no sequence gaps.
- Gap detection test: delete one line from the log file, run reconciliation, assert it reports exactly one gap at the correct sequence number.
- End-to-end replay: feed the drop-copy log to a stateless consumer and assert it reconstructs the correct final position for each account.
- Quantity mismatch test: modify one fill qty in the log, assert reconciliation flags it.

Learning objective:
Understand operational controls and post-trade integrity pipelines.



## Experiment 12: Matching Mode Plug-in Layer (Pro-Rata vs Price-Time)

**Status: Still Valid**

Difficulty: Complex
Estimated effort: 4 to 7 days
Gap vs real exchange: Different asset classes and venues use different allocation algorithms.

Background:
The current engine uses a single matching priority (price-time). Many real venues — particularly derivatives and fixed income — use alternative algorithms.

Financial explanation and motivation:

New terms:

- **Price-time priority**: The standard equity matching rule. Among all orders at the same price, the one that arrived first is filled first. Queue position (time of entry) is the decisive factor after price.
- **Pro-rata allocation**: An alternative matching rule common in derivatives markets. When a new order matches at a price where multiple resting orders exist, the incoming quantity is distributed *proportionally* to the resting size of each order at that price, regardless of arrival time.
    - Example: three resting orders at the same price with sizes 100, 200, 300 (total 600). An incoming order for 300 arrives. Allocations: 100 × (300/600) = 50, 200 × (300/600) = 100, 300 × (300/600) = 150.
    - Remainders from integer rounding are distributed to the largest under-allocated order(s) using price-time order as a tiebreak.
- **Queue value**: Under price-time, being first in queue is extremely valuable. Under pro-rata, queue position does not matter — size is everything. This fundamentally changes who provides liquidity and how they manage resting orders.
- **Fill fragmentation**: The average number of separate fill events that a single incoming order generates. Price-time typically produces low fragmentation (starts with the first resting order). Pro-rata produces high fragmentation (splits across many resting orders). High fragmentation increases post-trade processing cost.
- **Market maker economics under pro-rata**: Market makers are incentivized to post large resting sizes (to receive a larger proportional share of each fill). This tends to increase displayed liquidity but can also inflate book size without proportional depth improvement.

Technical details:

- Define a `MatchAllocator` protocol with a single method: `allocate(incoming_qty: int, candidates: list[RestingOrder]) -> list[Allocation]`.
- Implement `PriceTimeAllocator` (refactored existing behavior) and `ProRataAllocator` (new).
- Pro-rata implementation: `allocation_i = floor(incoming_qty * size_i / total_resting_size)`. Distribute any unallocated remainder quantity one unit at a time to the largest fractional-remainder orders, using time_key to break ties.
- Both allocators must produce fills that sum exactly to `min(incoming_qty, total_resting_qty)`. Add an assertion for this invariant.
- Configure per symbol via `matching_mode: price_time | pro_rata` in symbol config. Default is `price_time`.

Expected outcome:
The same order flow yields measurably different fills under the two allocation policies.

How to verify:

- Price-time scenario: three resting orders at the same price. Assert first-arrived is filled first.
- Pro-rata scenario: same three orders. Assert fills are proportional to size with correct remainder handling.
- Overflow scenario: incoming order larger than all resting liquidity. Assert all resting orders are fully filled under both modes.
- Fragmentation measurement: run a 1,000-order scenario under both modes and compare average fills-per-incoming-order.
- Backward compatibility: run the full regression suite with `matching_mode: price_time` (default) and assert no behavior changes.

Learning objective:
See how market design choices alter participant incentives and microstructure dynamics.



## Experiment 13: Cross-Product Risk and Portfolio Margin Approximation

**Status: Still Valid**

Difficulty: Very Complex
Estimated effort: 1 to 2 weeks
Gap vs real exchange: Risk is usually portfolio-aware across correlated products.

Background:
Current controls are per-symbol and per-gateway. No cross-product risk netting is applied.

Financial explanation and motivation:

New terms:

- **Position**: The net quantity of a symbol held by an account. A **long position** means more bought than sold (the account gains if price rises). A **short position** means more sold than bought (the account gains if price falls).
- **Portfolio**: The complete set of positions across all symbols held by an account.
- **Margin**: A capital deposit or requirement an account must maintain to support its open positions. It acts as a buffer against potential losses. If the account's losses would exceed the margin, the exchange may force-close positions.
- **Portfolio margin** (risk-based margin): A margin calculation that accounts for correlations between positions. If an account is simultaneously long Symbol A and short Symbol B, and A and B tend to move together, the combined risk is lower than the sum of individual risks. Portfolio margin rewards this hedging by requiring less total margin, freeing capital for other trades.
- **Correlation**: A number between -1.0 and +1.0 expressing how closely two instruments move together. Correlation +1.0: identical movement. Correlation -1.0: opposite movement. Correlation 0: no relationship.
- **Haircut**: A reduction applied to the offset credit granted for a correlated hedge. A correlation of 0.85 with a haircut factor of 0.80 means the hedge only offsets `0.85 × 0.80 = 68%` of the opposing position's margin requirement.
- **Mark-to-market (MtM)**: Revaluing all positions at the current market price to compute unrealized PnL and current margin requirements. Done continuously in production.
- **Stress test**: Applying a hypothetical extreme price move (for example, all prices fall 10% simultaneously) to current positions to verify that margin requirements would cover the resulting loss.

Example: Account holds +100 AAPL (long) and −80 MSFT (short). AAPL/MSFT correlation is 0.85. Siloed margin charges full margin for each independently. Portfolio margin reduces the total requirement because the short MSFT offsets some of the AAPL long-side risk.

Technical details:

- Add a `RiskEngine` module that subscribes to fill events and maintains per-account positions in memory, recomputing after each fill.
- Load a symbol correlation matrix from config: `correlations: {AAPL: {MSFT: 0.85}, MSFT: {AAPL: 0.85}}`.
- Per-symbol margin rate configured as `symbol_margin_rate: Decimal` per symbol.
- Portfolio margin formula: compute base margin as `sum(abs(position_i) * price_i * symbol_margin_rate_i)` for all symbols. Then for each pair of offsetting positions (one long, one short) with positive correlation, apply a haircut credit: `credit = min(margin_A, margin_B) * correlation_AB * haircut_factor`. Net margin = base margin − sum(all credits).
- If portfolio margin exceeds `margin_limit` for the account, reject any new order that would increase net exposure, with reason `MARGIN_LIMIT_EXCEEDED`.
- Emit `risk.margin_update` event after each recomputation: `{account_id, portfolio_margin, margin_limit, headroom}`.

Expected outcome:
Risk controls become portfolio-sensitive; accounts with offsetting positions can hold larger combined positions than siloed limits would allow.

How to verify:

- Scenario A: two uncorrelated symbols (correlation 0.0). Assert portfolio margin equals the sum of individual margins.
- Scenario B: two correlated symbols (correlation 0.90, haircut 0.80). Assert portfolio margin is lower than the sum by the expected haircut amount, verified by hand calculation.
- Scenario C: submit a risk-increasing order that pushes portfolio margin above `margin_limit`. Assert `MARGIN_LIMIT_EXCEEDED` reject.
- Stress test: apply a 10% price shock to all symbols and verify portfolio margin increases proportionally.

Learning objective:
Understand portfolio-level risk governance in modern exchanges and clearing ecosystems.



## Experiment 14: Auction Imbalance Feed and Indicative Price Model

**Status: Still Valid**

Difficulty: Very Complex
Estimated effort: 1 to 2 weeks
Gap vs real exchange: Opening and closing auctions publish rich imbalance signals.

Background:
Session support exists, but indicative auction data is not yet computed or published.

Financial explanation and motivation:

New terms:

- **Auction**: A trading session phase where all buy and sell orders are collected over a window and then matched at a single clearing price when the window closes. Unlike continuous trading, no matching occurs while the auction is collecting orders.
- **Uncross**: The moment when the auction ends and the engine matches all compatible orders. Every eligible buy order at or above the clearing price and every eligible sell order at or below it is filled at that single price simultaneously.
- **Auction clearing price**: The price that maximizes the total quantity matched. This is found by scanning all resting price levels and computing, for each candidate price P, how many units can be matched: `matched(P) = min(total_buy_qty_at_or_above_P, total_sell_qty_at_or_below_P)`. The clearing price is the P that produces the highest matched quantity.
- **Indicative price**: The hypothetical clearing price if the auction were to uncross *right now*, given the current state of submitted orders. It is published periodically during the auction and changes as new orders arrive.
- **Indicative matched volume**: The total quantity that would be filled at the current indicative price.
- **Imbalance**: The net surplus of buy or sell quantity at the current indicative price. If 5,000 buy units and 3,000 sell units would be matched, the imbalance is 2,000 on the buy side. The imbalance signals to sellers that there is excess buy demand not yet being met.
- **Price discovery**: The market mechanism for finding the "correct" price for an asset. Auctions are used at the open and close specifically because they aggregate all available order interest at once, making them more efficient at establishing a reference price than a single order would be.

The indicative price feed allows liquidity providers to respond to imbalances before the uncross. A large buy imbalance may cause the auction to clear higher; a seller can profitably submit sell orders to improve their share of fills and potentially lower the clearing price. Without this feed, participants are blind until the uncross occurs.

Technical details:

- At configurable intervals during the auction phase (`indicative_publish_interval_ms`, default 500ms), compute and publish an `auction.indicative.<symbol>` event.
- Indicative price algorithm: for each candidate price P in the set of all limit prices in the current book, compute `matched_qty(P)`. Select P* = argmax of `matched_qty(P)`. Tie-break rule (multiple P* values): prefer the price closest to the last-traded price; if no last trade exists, prefer the price closest to the midpoint of the highest buy and lowest sell.
- Event payload: `{symbol, indicative_price, indicative_volume, buy_imbalance_qty, sell_imbalance_qty, ts, auction_phase}`.
- `buy_imbalance_qty = total_buy_qty_at_or_above_P* − matched_qty(P*)`. Equivalently for sell.
- At uncross, the final clearing price must equal the last published indicative price, or the deviation must be explained by a deterministic tie-break rule documented in the spec.

Expected outcome:
Participants can observe auction pressure and respond before uncross; the final clearing price is predictable from the indicative feed.

How to verify:

- Hand-calculation test: insert a known set of buy and sell limit orders at specific prices. Compute the expected indicative price manually. Assert the published indicative price matches.
- Imbalance test: construct a book with 500 excess buy units at the indicative price. Assert `buy_imbalance_qty == 500` and `sell_imbalance_qty == 0`.
- Uncross consistency test: assert the final clearing price equals the last published indicative price.
- Cadence test: assert at least one indicative event is published per `indicative_publish_interval_ms` during the auction phase.

Learning objective:
Understand auction mechanics and pre-open/pre-close transparency products.



## Experiment 15: Synthetic Orders Engine (Parent-Child Execution)

**Status: Still Valid**

Difficulty: Very Complex
Estimated effort: 2 to 4 weeks
Gap vs real exchange: Institutional workflows rely on synthetic and algorithmic parent-child orders.

Background:
The matcher supports several advanced order types but not a full parent orchestration layer for institutional-scale execution.

Financial explanation and motivation:

New terms:

- **Parent order**: A high-level execution intent — for example, "buy 500,000 shares of AAPL over the next 60 minutes". The parent is not itself submitted to the exchange; it is the instruction given to an execution algorithm.
- **Child order**: A small individual order generated by the algorithm from the parent intent and submitted to the exchange. The sum of all child fills should approach the parent quantity over time.
- **Market impact**: The adverse price movement caused by trading. A large order submitted all at once will push prices against the buyer (ask prices rise as the order consumes available sell liquidity). Slicing into children reduces this impact.
- **Signaling risk**: The risk that other participants detect the pattern of systematic child orders and trade ahead of the parent, moving the price before execution completes. A buy child order every 30 seconds at a fixed size is detectable and exploitable.
- **TWAP (Time-Weighted Average Price)**: An execution strategy that divides the parent quantity into equal-sized child orders and submits them at equal time intervals over the execution window. Simple, predictable, and reduces market impact by spreading buying pressure over time.
- **POV (Percentage of Volume, also called Participation Rate)**: An execution strategy that sizes each child order as a fixed percentage of recent observed market volume. If the market is trading 10,000 shares per minute and the POV rate is 10%, each interval targets 1,000 shares. This adapts to market activity rather than using a fixed clock.
- **VWAP (Volume-Weighted Average Price)**: The ratio of total traded value to total traded volume over a period: `VWAP = sum(price_i × qty_i) / sum(qty_i)`. Used as an execution quality benchmark. Executing at or better than VWAP is generally considered a good outcome.
- **Arrival price**: The mid-price (midpoint between best bid and best ask) at the exact moment the parent order was first submitted. Used as a benchmark: did the algorithm cause the price to move adversely from the point of decision?
- **Slippage**: The difference between the arrival price and the average execution price. Positive slippage for a buy means the algorithm paid more than the arrival price, indicating market impact or timing cost.

Technical details:

- Add a `ParentOrderManager` service that subscribes to fill and market data events and maintains parent order state independent of the core engine.
- Parent order fields: `parent_id` (str), `symbol` (str), `side` (str), `total_qty` (int), `strategy` (str: `twap` or `pov`), `start_time` (ms epoch), `end_time` (ms epoch), `pov_rate` (Decimal, for POV only), `max_child_qty` (int, upper cap per child order), `child_limit_offset_ticks` (int, how far from best price to place child limit orders).
- TWAP scheduler: compute `num_intervals = (end_time - start_time) / interval_ms`. Each interval, submit a child limit order for `ceil(remaining_qty / remaining_intervals)` units, priced at `best_opposite_price - child_limit_offset_ticks` (buy) or `+ offset` (sell).
- POV scheduler: each interval, query recent volume from a rolling market data window. Compute `target_qty = round(window_volume * pov_rate)`. Submit child order for `min(target_qty, max_child_qty, remaining_qty)`.
- Child lifecycle: on ACK, record child as active. On FILL, accumulate `filled_qty` on the parent. On child CANCEL (e.g., due to a market halt), re-schedule the quantity.
- Parent terminal states: `COMPLETED` (filled_qty == total_qty), `CANCELLED` (explicit cancel request), `EXPIRED` (end_time reached with unfilled remainder logged as shortfall).
- Emit `parent.progress` each interval: `{parent_id, filled_qty, total_qty, pct_complete, avg_fill_price, arrival_price, slippage_bps}` where `slippage_bps = (avg_fill_price - arrival_price) / arrival_price × 10000` for a buy.

Expected outcome:
Large parent intents execute as controlled child streams with measurable execution quality metrics.

How to verify:

- TWAP determinism test: fixed market with no fills, known interval count, assert correct number of child orders submitted at the expected intervals.
- POV scaling test: inject known volume events, assert child sizes scale with market volume at the configured rate.
- Completion test: fill all children; assert parent reaches `COMPLETED` with correct `avg_fill_price`.
- Slippage test: compare `avg_fill_price` to `arrival_price` in a controlled scenario and assert slippage is within expected bounds.
- Stale data test: pause market data for longer than the stale threshold; assert the parent pauses child submission and resumes when data returns.

Learning objective:
Understand how high-level execution intent is translated into low-level exchange orders.



## Suggested progression path

1. **Phase 1 (Core)**: Complete Experiments 1, 4, 5, 6, 9, 12, 13, 14, 15 — these cover edge cases and advanced market design with no blockers.
2. **Phase 2 (Hardening)**: Tackle partially-implemented experiments: 2, 3, 7, 8, 10, 11, 16 — these integrate with existing subsystems and add operational maturity.
3. **Phase 3 (New opportunities)**: Experiments 17–20 open new integration and observability tracks.

This progression mirrors how real venues evolve: deterministic matching first, then control frameworks, then advanced market products.

**Note**: Experiment 16 (Self-Trade Prevention) is already implemented in the gateway and matching engine as `SmpAction` modes. It serves as a validation that the roadmap's abstractions align with production needs.



## Experiment 16: Self-Trade Prevention

**Status: Already Implemented ✓**

*Implementation location*: `src/edumatcher/models/order.py` (SmpAction enum), `src/edumatcher/engine/order_book.py` (`_sweep()` and `_smp_cancel_resting()`), `src/edumatcher/gateway/main.py` (SMP command syntax).

*Why included anyway*: Demonstrates that the roadmap's high-level abstractions map cleanly onto production code patterns. Can serve as a learning reference for understanding the matching engine's self-trade enforcement.

Difficulty: Intermediate
Estimated effort: —
Gap vs real exchange: Every regulated exchange prevents an account from trading against itself.

Background:
Currently a gateway can submit both a buy and a sell order at matching prices and they will fill against each other. In production this is prohibited.

Financial explanation and motivation:

New terms:

- **Self-trade**: A trade where the buy order and the sell order belong to the same account. No real economic transfer occurs because the participant is simultaneously on both sides. Inventory and cash net to zero; only the exchange's record of a "trade" changes.
- **Wash trade**: A trade that creates the appearance of market activity but involves no genuine change of ownership or economic risk. Wash trading is illegal in most jurisdictions because it inflates reported volume, misleads other participants about market activity, and can be used to manipulate prices. A self-trade is a form of wash trade.
- **STP (Self-Trade Prevention)**: A mechanism that detects an imminent self-trade at match time and applies a defined action to prevent it. The action is configurable per account or per gateway. Four standard industry modes exist:
    - **Cancel New (CN)**: The incoming order is rejected. The resting order remains in the book unchanged.
    - **Cancel Resting (CR)**: The resting order is cancelled. The incoming order proceeds to match against other participants' orders.
    - **Cancel Both (CB)**: Both the incoming and the resting order are cancelled.
    - **Decrement and Cancel (DC)**: The sizes of the two orders are compared. The smaller is cancelled; the larger has its quantity reduced by the smaller's quantity. If they are equal, both are cancelled. This minimises disruption while still preventing the self-trade.

STP is mandatory on regulated exchanges. In a simulation it is equally important: without it, a bot that submits orders on both sides inflates its own fill statistics and produces meaningless PnL numbers, defeating the educational purpose of the simulation.

Technical details:

- Add `stp_mode: CN | CR | CB | DC` to gateway or account config. Default: `CN`.
- At match time, before executing any fill, check whether the resting order's `account_id` equals the incoming order's `account_id`. If Experiment 9 (account domain) is not yet implemented, use `gateway_id` as a simpler proxy.
- If a self-trade is detected, apply the configured STP action and do not execute the fill. Emit a `stp.triggered` event with fields: `incoming_order_id`, `resting_order_id`, `account_id`, `stp_mode`, `action_taken` (one of `incoming_cancelled`, `resting_cancelled`, `both_cancelled`, `quantity_adjusted`).
- `stp.triggered` events are published to both the audit channel and the drop-copy channel.
- STP check applies to all order types that can generate fills: Limit, Market, Stop-Limit, Iceberg.

Expected outcome:
Self-trades are blocked under all four modes; audit events are produced for every STP action; fills between different accounts are unaffected.

How to verify:

- For each of the four STP modes, set up one resting order and one incoming order from the same account that would self-trade. Assert the correct action is taken per mode.
- DC mode edge case: resting qty 100, incoming qty 150. Assert resting is cancelled and incoming qty is reduced to 50, which then proceeds normally.
- Cross-account test: orders from two different accounts at the same price still fill normally with STP enabled.
- Audit test: assert the `stp.triggered` event contains all required fields.
- No-config test: two accounts with no STP config can trade against each other normally.

Learning objective:
Understand wash-trade prevention, regulatory compliance mechanics, and account identity in order routing.

---

## Experiment 17: Statistics SQL Query CLI Layer

Difficulty: Intermediate
Estimated effort: 2 to 3 days
Gap vs real exchange: Operators and compliance teams need safe, ergonomic CLI tools to extract analytics without writing raw SQL.

Background:
The statistics database (SQLite) is currently only accessible via direct SQL queries, which is error-prone and requires database knowledge. Real operations teams use pre-built CLI commands to pull reports by date, gateway, symbol, and time window.

Financial explanation and motivation:

New terms:

- **Report automation**: The process of generating standard operational reports (daily PnL, volume by symbol, gateway activity) on a schedule or on-demand.
- **Audit trail**: Complete record of all orders, fills, and cancellations for regulatory review. Typically filtered by gateway, date range, and symbol.
- **Dashboard data feed**: Time-series metrics (OHLC, volume, imbalance) published to real-time monitoring dashboards.
- **Data governance**: Policies on which operators can query which data, and what time delays apply (e.g., compliance can query historical but not live data).

Without a CLI abstraction, operators either run ad-hoc SQL (risky, slow to learn) or build one-off Python scripts (not scalable). Real exchanges expose ~20–50 named report templates covering daily settlement, regulatory reporting, and performance analytics.

Technical details:

- Add a new `pm-stats-query` or `pm-report` CLI command (or extend `pm-admin-cli` with subcommands).
- Pre-build query templates for common reports:
  - `daily-pnl [--date YYYY-MM-DD] [--gateway GATEWAY]` — gross and net PnL per account.
  - `volume-by-symbol [--date YYYY-MM-DD] [--start-time HH:MM] [--end-time HH:MM]` — total notional and share volume.
  - `gateway-activity [--gateway GATEWAY] [--date YYYY-MM-DD]` — order count, fill rate, rejection rate.
  - `fills-by-symbol [--symbol SYMBOL] [--date YYYY-MM-DD]` — OHLC, volume, imbalance.
  - `audit-trail [--gateway GATEWAY] [--date YYYY-MM-DD] [--symbol SYMBOL]` — full order lifecycle log.
- Output format options: `--format json | csv | table` (table is the default for human readability).
- Queries execute against the SQLite stats database; no custom aggregation logic needed — the DB schema already supports these views.
- Add optional `--limit N` to cap result row count (default: 10,000).

Expected outcome:
Operators can run `pm-report daily-pnl --date 2026-06-14 --format csv` and get a CSV without writing SQL. Audit queries become repeatable and auditable.

How to verify:

- Integration test: run each template query and assert output schema matches expected columns.
- End-to-end test: load sample session data, run a daily-pnl query, verify sum of gateway PnL matches engine's reported total.
- Output format test: run with `--format json` and `--format csv` and assert parseable output.
- Regression test: verify raw SQL equivalent queries return identical results.

Learning objective:
Understand operational reporting patterns, data access abstraction, and human-centered CLI design.


## Experiment 18: Drop Copy Durability and Restart Recovery

Difficulty: Intermediate
Estimated effort: 2 to 4 days
Gap vs real exchange: Production drop-copy systems survive process restarts and network outages.

Background:
The current drop-copy buffer is in-memory and bounded (10,000 messages). If the engine restarts, all buffered events are lost. Participants need to re-bootstrap their view of positions from trade history, which is slow and error-prone during high-volume sessions.

Financial explanation and motivation:

New terms:

- **Durable log**: An append-only file written to disk, guaranteeing that events persist across process restarts.
- **Session rotation**: A new log file per trading session (e.g., `dropcopy_20260614.log`), simplifying rotation and archival.
- **Replay window**: The newest N messages available for replay without querying the archive. Typical: last 1 hour of events.
- **Gap tolerance**: How long a subscriber can be offline before gap detection kicks in. Typical: 15–60 minutes.
- **Restart sequence**: On engine restart, drop-copy publisher re-initializes and continues publishing with sequence numbers reset to 1.

Technical details:

- Write all drop-copy events to a durable JSON-lines log file: `data/dropcopy_YYYYMMDD.log`.
- One event per line: `{"seq": 1, "timestamp": 1718000000000000000, "gateway_id": "TRADER01", "event_type": "order.fill", ...}`.
- At session end (when engine receives CLOSED state transition), rename file to `dropcopy_YYYYMMDD.HHMMSS.CLOSED.log` to mark it immutable.
- On engine startup, scan for the most recent unclosed log file. If found, initialize drop-copy sequence counter to `max_seq + 1` from that file.
- Add `dropcopy_tail` utility: read the last N lines of the log file and re-publish them on the drop-copy socket for slow subscribers to catch up.
- Add `dropcopy_reconcile` utility: read two log files (local participant log vs. engine archive), align by sequence number, and report any gaps or duplicates.

Expected outcome:
Drop-copy events survive engine restarts. Participants can query historical drop-copy by session date and get exact sequence continuity.

How to verify:

- Persistence test: write 100 events, restart engine, verify next 10 events have sequence numbers 101–110 (no reset).
- Rotation test: run through a full session, verify CLOSED log file is created and new session starts with fresh sequence.
- Recovery test: simulate a participant re-connecting 1 hour after disconnect; run `dropcopy_tail` and verify they receive the last 50 events.
- Gap detection test: delete one line from a log file, run `dropcopy_reconcile`, assert it reports exactly one gap at the correct sequence.

Learning objective:
Understand durability patterns, log rotation, and participant recovery workflows in high-availability systems.


## Experiment 19: Cross-Host Operational Validation Matrix

Difficulty: Intermediate
Estimated effort: 2 to 3 days
Gap vs real exchange: Multi-host deployments must pass deterministic end-to-end tests before going live.

Background:
The runtime now supports configurable data and config paths plus cross-host endpoint resolution. A multi-host exchange (engine on host A, gateways on hosts B and C) must maintain order determinism and message ordering across network boundaries. The validation matrix ensures this works.

Financial explanation and motivation:

New terms:

- **Latency parity**: Behavior remains deterministic even when network latencies between hosts vary.
- **Message ordering guarantee**: Orders submitted by different gateways are processed in submit-timestamp order, not arrival order, so latency does not affect fills.
- **Startup sequence**: The order in which processes bind sockets and wait for others to connect. If violated, processes hang or fail.
- **Network fault injection**: Simulate packet loss, reordering, or delays to validate that the exchange does not diverge from its single-host behavior.

Technical details:

- Create a test matrix that runs the same 100-order scenario under three topologies:
  1. **Single-host** (baseline): all processes on localhost, default ZMQ configuration.
  2. **LAN multi-host**: engine on 10.0.0.10, gateway on 10.0.0.11, ~1ms latency (network overhead).
  3. **WAN multi-host** (simulated): engine on 10.0.0.10, gateway on 10.0.0.11 + 50ms injected delay via tc (traffic control).
- For each topology, verify:
  - Final order book state is identical across all topologies.
  - Fill prices and quantities match exactly.
  - Drop-copy sequence numbers are contiguous (no gaps or duplicates).
  - Audit log is byte-identical (same topic order, same event payloads).
- Add a `stress_cross_host.sh` script that runs all three topologies back-to-back with different random seeds and reports pass/fail.

Expected outcome:
Operators gain confidence that cross-host deployments will not diverge from single-host behavior due to network variations.

How to verify:

- Topology equivalence test: run the same scenario on single-host and LAN multi-host, hash the audit logs, assert hashes match.
- Latency robustness test: inject 50–200ms delays via network emulation and re-run; audit logs should still match.
- Fault injection test: drop 0.1% of messages at the network layer (using tc or netcat), verify engine detects and reports the gap or reconnect.
- Determinism test: run 10 times with the same seed on each topology; assert all 10 runs produce identical results on each topology (but not necessarily identical between topologies if latencies differ).

Learning objective:
Understand distributed systems testing, latency-robust message ordering, and operational validation patterns.


## Experiment 20: Installed-Mode vs. Source-Mode Parity Validation

Difficulty: Basic
Estimated effort: 1 to 2 days
Gap vs real exchange: Installation and setup are common operational concerns; deployment paths must be equivalent.

Background:
EduMatcher supports two run modes: **source mode** (Poetry + git clone) and **installed mode** (pipx + `pm-setup`). Both should behave identically. Currently, there is no automated test that validates parity across these modes.

Financial explanation and motivation:

New terms:

- **Source mode**: Developer runs `poetry run pm-engine` from a git clone.
- **Installed mode**: End user runs `pm-setup`, then `pm-engine` from PATH after `pip install` (or pipx).
- **Configuration parity**: Same config files, same environment variable resolution, same default paths.
- **Reproducibility**: Users should get the same behavior regardless of which installation method they choose.

Technical details:

- Create a `test_mode_parity.py` test suite that:
  1. Starts the engine in **source mode** (Poetry), runs a 50-order scenario, saves the audit log and final book state.
  2. Installs the package with `pipx install .` (or equivalent).
  3. Runs `pm-setup --data-dir /tmp/test-installed` to initialize the installed-mode directory.
  4. Starts the engine in **installed mode** using the same config, runs the same 50-order scenario.
  5. Compares audit logs and book state between modes; they should match exactly.
- Test both configuration resolution paths:
  - Via `EDUMATCHER_CONFIG` env var.
  - Via default fallback (current directory, then `~/.local/share/edumatcher`).
- Verify data directory resolution:
  - Via `EDUMATCHER_DATA_DIR` env var.
  - Via default fallback.

Expected outcome:
CI pipeline gains a gate that prevents installed mode regressions. Users are confident that `pipx install` works correctly.

How to verify:

- Build parity test: install edumatcher with `pipx`, run test suite, assert it passes.
- Config path test: test that `EDUMATCHER_CONFIG` and `EDUMATCHER_DATA_DIR` override defaults correctly in both modes.
- Audit log equivalence: run test scenario in both modes, assert audit logs are byte-identical.
- Performance parity: measure latency per order in both modes; should differ by < 5%.

Learning objective:
Understand packaging, installation, and deployment verification best practices.

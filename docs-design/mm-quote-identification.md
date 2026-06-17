Version: 1.0.0

Date: 2026-06-17

Status: Design Proposal

# MM quote identification and quote-leg mapping

## Scope

This note documents how EduMatcher identifies MM quotes, maps each quote to its two resting limit-order legs, and informs the MM when a leg is taken.

It answers these questions:

1. Is a quote identified by quote_id, or by (SYMBOL, GATEWAY_ID)?
2. How is a quote mapped to the resting order(s)?
3. How does the MM learn that one quote leg was taken?
4. When and how should the MM cancel both legs and re-quote?

## Direct answers

### 1) Quote identity: quote_id vs (gateway_id, symbol)

Both are used, but for different purposes:

- Engine active-quote lookup key: (gateway_id, symbol)
- Business identifier and external correlation key: quote_id

Practical consequence:

- The engine allows only one active quote per (gateway_id, symbol).
- Replacing a quote for the same (gateway_id, symbol) first removes/cancels the previous quote entry, then installs the new one.
- quote_id is still carried on both quote-leg orders and on quote lifecycle messages, so MM systems can correlate events to a logical quote instance.

So: unique active quote slot is per (gateway_id, symbol), while quote_id identifies the specific quote generation occupying that slot.

### 2) Mapping to the corresponding resting order for each leg

A quote is implemented as two normal LIMIT orders:

- Bid leg: side=BUY
- Ask leg: side=SELL

Mapping is maintained in two places:

- QuoteIndex entry (indexed by (gateway_id, symbol)) stores:
  - quote_id
  - bid_order_id
  - ask_order_id
- Each leg order stores origin=QUOTE and quote_id=<same quote_id>

This gives bi-directional linkage:

- quote -> legs through QuoteIndex (bid_order_id, ask_order_id)
- leg -> quote through Order.quote_id

### 3) How MM learns a quote leg was taken

The MM is informed through normal order.fill events for the affected leg order_id.

Additionally, quote lifecycle notifications are emitted:

- quote.status.<gateway_id> with INACTIVE_BID_FILLED or INACTIVE_ASK_FILLED when policy causes inactivation.
- order.cancelled.<gateway_id> for the sibling leg when the engine can cancel that sibling as a resting order.

Important detail:

- The order.fill payload does not reliably include quote_id.
- Therefore, MM should correlate fill.order_id against the bid_order_id/ask_order_id received in quote.ack.
- quote.status is the explicit quote-level lifecycle signal containing quote_id.

## Quote model and identifiers

### Identifier layers

- quote_id
  - Optional at submission; if missing, engine auto-generates one.
  - Present in quote.ack and quote.status.
  - Copied into both leg orders (Order.quote_id).

- Active quote key
  - QuoteIndex key is (gateway_id, symbol).
  - Enforces one active quote per gateway+symbol.

- Leg order IDs
  - Generated UUIDs for each of bid/ask child orders.
  - Returned in quote.ack as bid_order_id and ask_order_id.
  - Used by all order-level events (fill/cancel/etc).

### Why this split exists

- (gateway_id, symbol) gives O(1) active quote routing for replace/cancel/kill-switch behavior.
- quote_id gives a stable logical quote label for external systems, logs, and MM analytics.
- order_id remains the execution primitive for matching and fill events.

## Start-to-finish quote lifecycle

## 0) MM submits quote

Gateway command:

- QUOTE|SYM=<sym>|BID=<p>|ASK=<p>|BID_QTY=<n>|ASK_QTY=<n>[|TIF=...][|QUOTE_ID=...]

Gateway sends:

- topic quote.new
- payload includes gateway_id, symbol, bid/ask price+qty, tif, and optional quote_id

## 1) Engine validates and normalizes

Checks include:

- Gateway is connected/authorized.
- Participant role is MARKET_MAKER.
- Symbol exists and is not halted.
- Quantities > 0 and bid_price < ask_price.
- Optional MM obligation checks (max spread, min size), depending on config.

If invalid:

- quote.ack.<gateway_id> with accepted=false, reason, and provided quote_id (if any)

## 2) Engine handles replacement semantics

Before creating new legs:

- Engine removes any existing QuoteIndex entry for the same (gateway_id, symbol).
- If one existed, both old legs are cancelled and quote.status CANCELLED is published (reason: replaced).

This is why only one active quote can exist per gateway+symbol.

## 3) Engine creates two leg orders

For accepted quote:

- Create BUY LIMIT leg and SELL LIMIT leg.
- Set origin=QUOTE on both.
- Set quote_id on both.
- Track order_id -> symbol in order routing map.
- Store QuoteEntry in QuoteIndex with quote_id, bid_order_id, ask_order_id.

## 4) Immediate matching on insert

Each leg is inserted through normal order-book processing and can match immediately.

If immediate fills occur:

- order.fill.<gateway_id> is published for the affected leg order_id.
- Trade messages are published.
- Quote inactivation logic may run immediately if a quote leg is filled.

## 5) Quote accepted and becomes active

After insertion processing:

- quote.ack.<gateway_id> accepted=true with:
  - quote_id
  - bid_order_id
  - ask_order_id
- quote.status.<gateway_id> ACTIVE

MM should persist this mapping:

- quote_id -> {symbol, bid_order_id, ask_order_id, state=ACTIVE}
- order_id -> quote_id (reverse index for fast fill correlation)

## Resting phase: how fills and quote state interact

### What arrives when one leg is hit

When another participant trades against one leg:

- MM receives order.fill.<gateway_id> for that leg order_id (normal fill event).

Engine then checks quote policy using the filled order and current QuoteEntry.

### Quote refresh policies

Configured per gateway via quote_refresh_policy:

- INACTIVATE_ON_ANY_FILL (default):
  - Any partial/full fill in one leg inactivates quote.
  - Engine removes quote entry, cancels sibling leg, emits quote.status INACTIVE_*.

- INACTIVATE_ON_FULL_FILL:
  - Only full fill (remaining=0) in one leg inactivates quote.
  - Partial fill does not inactivate.

- NEVER_INACTIVATE:
  - Quote entry remains active even when one leg fills.
  - No automatic sibling cancellation due to fill.

### Inactivation status values

If inactivated, status is side-specific:

- INACTIVE_BID_FILLED means BUY leg filled, ASK sibling cancelled.
- INACTIVE_ASK_FILLED means SELL leg filled, BUY sibling cancelled.

### Is fill enough to know it was a quote leg?

Yes, if MM keeps quote.ack mappings.

Recommended correlation rule:

- if fill.order_id in active_quote_order_ids then fill belongs to that quote leg

Do not depend on quote_id in fill payload for this correlation.

## Cancellation paths affecting quotes

Quotes can leave ACTIVE state through several paths:

- Explicit quote cancel:
  - Request is by gateway_id + symbol (not by quote_id).
  - Engine finds active quote slot via QuoteIndex key, cancels both legs, emits quote.status CANCELLED and quote.ack accepted=true.

- Quote replace (new quote on same gateway+symbol):
  - Old quote cancelled, new quote installed.

- Fill-driven inactivation:
  - Depending on quote_refresh_policy.

- Kill switch:
  - Cancels quote legs for gateway (optionally symbol-scoped).

- Gateway disconnect (policy dependent):
  - Commonly cancels quotes.

- Halt and risk admin actions:
  - Symbol/global halts and symbol mass cancel clear quote legs for affected symbols.

- Session/circuit-breaker transitions:
  - Symbol-level quote cancellations can be triggered by risk/session flows.

## How MM should manage quote state in practice

### Minimal state machine per quote

Use states:

- PENDING_SUBMIT
- ACTIVE
- INACTIVE_BID_FILLED
- INACTIVE_ASK_FILLED
- CANCELLED
- REJECTED

### Event-driven handling model

On quote.ack accepted=true:

- Register quote_id and both order IDs.
- Mark ACTIVE.

On order.fill:

- Lookup order_id in reverse index.
- If found, mark leg fill progress.
- If policy expects auto-inactivation, await quote.status INACTIVE_* and/or sibling cancel.

On quote.status INACTIVE_*:

- Mark quote inactive.
- Remove both leg order IDs from active set.
- Trigger re-quote logic if strategy wants continuous two-sided quoting.

On quote.status CANCELLED:

- Mark quote inactive and clear mapping.

On order.cancelled for one of quote legs:

- If quote already inactive/cancelled, treat as expected sibling cleanup.

### Should MM manually cancel both legs when one leg is taken?

Default configuration usually makes this unnecessary:

- INACTIVATE_ON_ANY_FILL auto-cancels sibling and marks quote inactive.

Manual cancel is needed when:

- policy is NEVER_INACTIVATE, or
- MM wants faster/stricter behavior than configured server policy.

Manual cancellation API path is symbol-based:

- QUOTE_CANCEL with symbol
- It targets current active quote slot for that gateway+symbol.

## Sequence examples

### A) Typical default flow (auto inactivate on first fill)

1. MM sends quote.new for AAPL with quote_id Q123.
2. Engine accepts, creates bid/ask orders B1/S1, stores QuoteEntry(Q123, B1, S1).
3. Engine sends quote.ack(Q123, B1, S1), then quote.status ACTIVE.
4. Taker trades against B1; MM receives order.fill(order_id=B1,...).
5. Engine policy inactivates quote, cancels sibling S1.
6. MM receives quote.status INACTIVE_BID_FILLED (Q123), and typically also order.cancelled(S1) when S1 was still resting.
7. MM submits replacement quote.

### B) NEVER_INACTIVATE flow

1. Same steps 1-4.
2. Engine does not inactivate quote after fill.
3. Sibling remains resting unless explicitly cancelled or otherwise removed.
4. MM strategy decides when to QUOTE_CANCEL and re-quote.

## Practical conclusions for the original questions

- Quote slot ownership is per (gateway_id, symbol); quote_id identifies the specific quote instance occupying that slot.
- Mapping to resting legs is explicit and deterministic through quote.ack bid_order_id/ask_order_id plus internal QuoteEntry and Order.quote_id.
- MM learns a taken leg through normal order.fill on leg order_id; quote-level semantics are confirmed via quote.status (INACTIVE_* / CANCELLED).
- For robust MM logic, keep an in-memory mapping of quote_id <-> {bid_order_id, ask_order_id} and order_id -> quote_id; treat quote.status as authoritative lifecycle and order.fill as execution detail.

## Operational checklist for MM implementation

- On submit, always send your own quote_id for easier reconciliation.
- Persist quote.ack mapping immediately.
- Correlate fills by order_id, not by quote_id in fill payload.
- Subscribe to both order.fill.<gw> and quote.status.<gw>.
- Handle policy-specific behavior:
  - ANY_FILL: expect immediate inactivation and sibling cancel.
  - FULL_FILL: expect inactivation only at remaining=0.
  - NEVER: implement explicit cancel/re-quote policy in MM logic.
- On disconnect/reconnect, rebuild active mapping via ORDERS plus local state/bootstrap rules.

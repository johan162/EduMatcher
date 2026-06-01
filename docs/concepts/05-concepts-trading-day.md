# A Full Trading Day

!!! note "Learning objectives"
    After reading this page you will understand:

    - How a real exchange trading day is structured into phases
    - What happens during opening and closing auctions
    - Which order types are valid in each phase
    - How price discovery works at the open
    - What happens to resting orders at phase transitions

---

## The shape of a trading day

A stock exchange does not run as a single continuous matching session from
open to close. Instead, the day is divided into **session phases**, each with
different rules about which orders are accepted and whether matching occurs.

This structure exists because:

- The opening price matters enormously (indices, ETF valuations, fund NAVs all
  reference it). A noisy first few seconds of continuous trading would produce
  a poor opening price.
- The closing price is even more important — it is the official daily
  settlement price used by clearinghouses and portfolio managers worldwide.
- Auctions give all participants equal footing at key moments, preventing fast
  players from exploiting slow ones at the open and close.

---

## The five phases

```
  ┌─────────────┬─────────────────┬────────────────┬──────────────────┬─────────┐
  │  PRE_OPEN   │ OPENING_AUCTION │   CONTINUOUS   │ CLOSING_AUCTION  │ CLOSED  │
  │             │                 │                │                  │         │
  │  Orders     │  Orders rest,   │  Live matching │  Orders rest,    │  No     │
  │  rest,      │  no matching    │  on every new  │  no matching     │  orders │
  │  no match   │  ATO orders ok  │  order         │  ATC orders ok   │         │
  └─────────────┴─────────────────┴────────────────┴──────────────────┴─────────┘
  6:00 AM       8:00 AM           9:30 AM          3:50 PM            4:00 PM
  (typical US equity schedule — EduMatcher timings are configurable)
```

| Phase | Orders accepted? | Matching? | Special order types |
|-------|-----------------|-----------|---------------------|
| `PRE_OPEN` | Yes | No | LIMIT, STOP, STOP_LIMIT, ICEBERG |
| `OPENING_AUCTION` | Yes | No | + `TIF=ATO` (At-The-Open) |
| `CONTINUOUS` | Yes | Yes | All types including MARKET, FOK, IOC |
| `CLOSING_AUCTION` | Yes | No | + `TIF=ATC` (At-The-Close) |
| `CLOSED` | No | No | — all orders rejected |

---

## Enabling or disabling session handling

Session-phase enforcement is controlled by `sessions_enabled` in
`engine_config.yaml`:

```yaml
sessions_enabled: true
```

- `sessions_enabled: true`:
  the engine starts in `CLOSED`, accepts new orders only in open phases, and
  enforces auction/session rules from scheduler transitions.
- `sessions_enabled: false`:
  the engine ignores `session.transition` messages and runs in perpetual
  `CONTINUOUS` behavior, which is useful for always-open local testing.

When sessions are enabled, starting the engine outside configured session
times will keep it closed until `pm-scheduler` sends a transition to an
order-accepting phase.

---

## Specifying time for the daily session

Phase transition times are configured in `engine_config.yaml` under a `schedule`
section, which is read by `pm-scheduler` (not by the engine itself):

```yaml
sessions_enabled: true

schedule:
  pre_open:              "09:00"
  opening_auction_start: "09:25"
  continuous_start:      "09:30"
  closing_auction_start: "16:00"
  closing_auction_end:   "16:05"
```

All values are `HH:MM` in the **local time of the machine running the
scheduler**.

| Key | Phase triggered | Default |
|-----|----------------|---------|
| `pre_open` | `PRE_OPEN` | `09:00` |
| `opening_auction_start` | `OPENING_AUCTION` | `09:25` |
| `continuous_start` | `CONTINUOUS` | `09:30` |
| `closing_auction_start` | `CLOSING_AUCTION` | `16:00` |
| `closing_auction_end` | `CLOSED` | `16:05` |

**If the `schedule` section is absent entirely**, the scheduler falls back to
the built-in defaults shown above.  If it is present but a key is missing,
that specific transition is **never sent** that day — there is no per-key
fallback.  So if you define `schedule:` but omit `closing_auction_end`, the
market will never transition to `CLOSED` automatically.

`sessions_enabled` must be `true` for the scheduler-driven schedule to take
effect.  With it set to `false`, the engine ignores all `session.transition`
messages and stays in perpetual continuous mode regardless of the `schedule`
block.

---

## Phase 1 — PRE_OPEN

The market is warming up. Traders can submit LIMIT orders that rest on the
book, but no matching occurs. This allows participants to gauge where the
market might open by watching the accumulating order book.

**Example: GW01 submits a pre-open bid**

```
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=200|PRICE=149.50
```

The order is accepted and rests. No trade happens yet.

---

## Phase 2 — OPENING_AUCTION

The exchange accumulates all interest before computing a single opening price.
The special `TIF=ATO` (At-The-Open) order type is only valid here.

**Example: several participants add interest**

```
# GW01 — institutional buy
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=500|PRICE=150.00|TIF=ATO

# GW02 — sell at limit
NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=300|PRICE=149.80|TIF=ATO

# GW03 — sell at limit (willing to sell at a lower price)
NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=400|PRICE=149.50|TIF=ATO
```

The accumulated order book before uncross might look like:

```
BID side (buys):          ASK side (sells):
200 @ 149.50 (pre-open)   300 @ 149.80
500 @ 150.00 (ATO)        400 @ 149.50
```

### The uncross — how the opening price is computed

At the end of OPENING_AUCTION, the engine finds the price that
**maximises the total quantity traded**. It does this by scanning all prices
and asking: "if we execute at price P, how many shares would fill?"

For our example:

| Candidate price | Matchable buys | Matchable sells | Volume |
|----------------|---------------|-----------------|--------|
| 149.50 | 200 + 500 = 700 | 400 | 400 |
| 149.80 | 200 + 500 = 700 | 300 + 400 = 700 | 700 ← maximum |
| 150.00 | 200 + 500 = 700 | 300 + 400 = 700 | 700 (tie — lower price chosen) |

**Equilibrium price = $149.80** (maximises volume; in a tie, the lower price
is chosen to protect buyers).

All crossable orders execute at $149.80:
- GW01's ATO 500-share buy fills at $149.80
- GW02's 300-share sell fills at $149.80
- GW03's 400-share sell fills at $149.80 (partially: 200 shares)
- GW01's pre-open 200-share buy fills at $149.80

**Result published:**
```
auction.result.AAPL: price=149.80 volume=700
```

After the uncross, ATO orders that didn't fill are **expired** (not cancelled
by the trader — automatically removed by the engine). The market transitions
to CONTINUOUS.

---

## Phase 3 — CONTINUOUS

This is the main trading session. Every new order is immediately swept against
resting liquidity. All ten order types are valid here.

**Price-time priority is in full effect.** See [The Order Book](01-concepts-order-book.md)
for a detailed explanation.

**Example: continuous trading in action**

```
# GW01 posts a limit bid
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=149.90

# GW02 sweeps it with a market order
NEW|SYM=AAPL|SIDE=SELL|TYPE=MARKET|QTY=100

# Trade: 100 shares @ 149.90
```

STOP and TRAILING_STOP orders activate here when `last_trade_price` crosses
their trigger levels. See [Stop Trigger Logic](../user-guide/04-order-types.md#9-stop-trigger-logic)
for details.

---

## Phase 4 — CLOSING_AUCTION

The closing auction works exactly like the opening auction, but for the end of
the day. The `TIF=ATC` (At-The-Close) order type is only valid in this phase.

The closing price is particularly important because:
- **Index rebalancing** — index funds must buy/sell to match new index weights
  at the close, generating predictable large order flow.
- **Fund NAV calculation** — mutual funds value their portfolios at the
  official closing price.
- **Options expiry** — many options settle based on the closing price.

**Example: closing auction**

```
# Large index rebalancing buy
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=1000|PRICE=152.00|TIF=ATC

# Institutional sell (taking profit)
NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=800|PRICE=151.50|TIF=ATC
```

The uncross algorithm runs and produces the official closing price.

---

## Phase 5 — CLOSED

The market is closed. All incoming orders are rejected:

```
[GW01] order.ack: accepted=false reason="Market is CLOSED"
```

When the engine shuts down it:
1. Serialises all resting **GTC** (Good-Till-Cancelled) orders to `data/gtc_orders.json`.
2. Publishes `order.expired` for all resting **DAY** orders (they are discarded at close).
3. Publishes `system.eod` to all subscribers.

---

## What happens to my orders at each transition?

| Order TIF | At CONTINUOUS start | At CLOSED |
|-----------|--------------------|-----------| 
| `DAY` | Keeps resting | Expired and discarded |
| `GTC` | Keeps resting | Persisted to file, reloaded next day |
| `ATO` | **Expired** if unfilled at OPENING_AUCTION end | — |
| `ATC` | — | **Expired** if unfilled at CLOSING_AUCTION end |

---

## Triggering phase transitions in EduMatcher

In production, a scheduler process drives phase transitions automatically:

```bash
poetry run pm-scheduler --now
```

`--now` starts immediately in PRE_OPEN and progresses through all phases.
Transition times are configurable in `engine_config.yaml`.

You can also trigger transitions manually from a gateway during development:

```
SESSION|TRANSITION=OPENING_AUCTION
SESSION|TRANSITION=CONTINUOUS
SESSION|TRANSITION=CLOSING_AUCTION
SESSION|TRANSITION=CLOSED
```

---

## Putting it all together — a full-day scenario

| Time | Phase | Event |
|------|-------|-------|
| 06:00 | PRE_OPEN | Engine starts; GTC orders reload from file |
| 06:00–08:00 | PRE_OPEN | Participants submit limit orders; book fills but no trades |
| 08:00 | → OPENING_AUCTION | ATO orders now accepted |
| 08:00–09:30 | OPENING_AUCTION | Book accumulates; price discovery happening |
| 09:30 | → CONTINUOUS | **Uncross at equilibrium price**; ATO unfilled orders expired |
| 09:30–15:50 | CONTINUOUS | Live matching; all order types active; stops triggering |
| 15:50 | → CLOSING_AUCTION | ATC orders now accepted; new MARKETs rejected |
| 15:50–16:00 | CLOSING_AUCTION | Final accumulation |
| 16:00 | → CLOSED | **Uncross at closing price**; ATC orders expired; GTC orders saved; DAY orders expired |

---

[← Your First Trade](04-concepts-first-trade.md) | [Next: Glossary →](../glossary.md)

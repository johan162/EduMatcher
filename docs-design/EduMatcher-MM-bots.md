Version: 0.1.0

Date: 2026-06-17

Status: Design Proposal

# EduMatcher — Market-Maker Bot (pm-mm-bot)



## Table of Contents

- [EduMatcher — Market-Maker Bot (pm-mm-bot)](#edumatcher--market-maker-bot-pm-mm-bot)
  - [Table of Contents](#table-of-contents)
  - [1. Motivation](#1-motivation)
    - [1.1 Scope Statement](#11-scope-statement)
  - [2. Financial Concepts Primer](#2-financial-concepts-primer)
  - [3. Architecture Overview](#3-architecture-overview)
    - [3.1 ZMQ Topics Subscribed](#31-zmq-topics-subscribed)
  - [4. Bot Lifecycle and State Machine](#4-bot-lifecycle-and-state-machine)
    - [4.1 State Descriptions](#41-state-descriptions)
    - [4.2 Startup Sequence](#42-startup-sequence)
    - [4.3 Graceful Shutdown](#43-graceful-shutdown)
  - [5. Price Reference and Quote Placement](#5-price-reference-and-quote-placement)
    - [5.1 Mid-Price Tracking](#51-mid-price-tracking)
    - [5.2 Quote Price Calculation](#52-quote-price-calculation)
    - [5.3 Drift Detection](#53-drift-detection)
    - [5.4 Quantity Policy](#54-quantity-policy)
  - [6. Quote Refresh Logic](#6-quote-refresh-logic)
    - [6.1 Refresh Triggers](#61-refresh-triggers)
    - [6.2 Reissue Delay](#62-reissue-delay)
    - [6.3 Cancel Before Reissue](#63-cancel-before-reissue)
    - [6.4 Heartbeat Guard](#64-heartbeat-guard)
  - [7. Session State Handling](#7-session-state-handling)
    - [7.1 Allowed Quoting States](#71-allowed-quoting-states)
    - [7.2 Transition to CONTINUOUS](#72-transition-to-continuous)
    - [7.3 Quote Cancellation on Auction Entry](#73-quote-cancellation-on-auction-entry)
    - [7.4 Circuit Breaker Halt](#74-circuit-breaker-halt)
  - [8. Entry Point and CLI Reference](#8-entry-point-and-cli-reference)
    - [8.1 Entry Point](#81-entry-point)
    - [8.2 Basic Usage](#82-basic-usage)
    - [8.3 CLI Arguments](#83-cli-arguments)
    - [8.4 Gap Guidelines](#84-gap-guidelines)
  - [9. Gateway Identity and Configuration](#9-gateway-identity-and-configuration)
    - [9.1 Gateway ID Convention](#91-gateway-id-convention)
    - [9.2 Required engine\_config.yaml Entries](#92-required-engine_configyaml-entries)
    - [9.3 Recommended disconnect\_behaviour](#93-recommended-disconnect_behaviour)
  - [10. ZMQ Message Flow](#10-zmq-message-flow)
    - [10.1 Messages Sent by the Bot (PUSH → Engine)](#101-messages-sent-by-the-bot-push--engine)
    - [10.2 Messages Received by the Bot (SUB ← Engine)](#102-messages-received-by-the-bot-sub--engine)
    - [10.3 Full Normal Trading Cycle](#103-full-normal-trading-cycle)
    - [10.4 Mid-Price Drift Reprice](#104-mid-price-drift-reprice)
  - [11. New Files and Changes to Existing Files](#11-new-files-and-changes-to-existing-files)
    - [11.1 New Files](#111-new-files)
    - [11.2 Changes to Existing Files](#112-changes-to-existing-files)
    - [11.3 Module Responsibilities](#113-module-responsibilities)
      - [`mm_bot/main.py`](#mm_botmainpy)
      - [`mm_bot/bot.py`](#mm_botbotpy)
      - [`mm_bot/pricer.py`](#mm_botpricerpy)
  - [12. Configuration Reference](#12-configuration-reference)
    - [12.1 Full YAML Example](#121-full-yaml-example)
    - [12.2 Bot Launch Reference](#122-bot-launch-reference)
    - [12.3 Parameter Quick Reference](#123-parameter-quick-reference)
  - [13. Testing Guide](#13-testing-guide)
    - [13.1 Unit Tests — `QuotePricer`](#131-unit-tests--quotepricer)
    - [13.2 Integration Tests — `MMBot`](#132-integration-tests--mmbot)
    - [13.3 Running Tests](#133-running-tests)
  - [14. Open Questions and Future Work](#14-open-questions-and-future-work)
    - [14.1 Inventory Skewing](#141-inventory-skewing)
    - [14.2 Volatility-Adaptive Spread](#142-volatility-adaptive-spread)
    - [14.3 Multi-Symbol Mode](#143-multi-symbol-mode)
    - [14.4 Config-File Mode](#144-config-file-mode)
    - [14.5 Coordination Between MM Instances](#145-coordination-between-mm-instances)
    - [14.6 Metrics and Observability](#146-metrics-and-observability)



## 1. Motivation

EduMatcher already models market-maker quoting through the `QUOTE` command and
the `MARKET_MAKER` gateway role. However, using this capability today requires a
human operator to type `QUOTE` commands at the gateway terminal and manually
react to fill events. This is impractical for a classroom session where:

- The instructor wants the book to always have two-sided liquidity.
- Students should be able to trade immediately without waiting for a human MM.
- The spread and quote sizes should stay disciplined and predictable.
- When a quote side is hit, the remaining half must be cancelled and a fresh
  two-sided quote re-issued promptly.

`pm-mm-bot` is an autonomous market-maker bot that runs as a dedicated process
for one symbol. Multiple instances can run simultaneously — one per symbol, or
several competing MMs on the same symbol. Each instance connects to the engine
as a `MARKET_MAKER` gateway using the naming convention `MM_<SYMBOL>_<nn>`.

The bot's sole responsibility is to keep its assigned symbol liquid: it watches
the book, tracks the current mid-price, posts a two-sided `QUOTE`, detects when
either leg is partially or fully filled, cancels any stale remnant, and re-issues
a fresh quote aligned to the updated mid-price.

### 1.1 Scope Statement

**pm-mm-bot v1 covers:**

- Single-symbol market-making per process instance.
- Quote placement at configurable spread around the current mid-price.
- Automatic cancellation of partially filled or fully consumed quote legs.
- Re-quoting after fills, mid-price drift, and session state transitions.
- Respect for session states: only active quoting during `CONTINUOUS`.
- Optional obligation enforcement via `--gap` and `--qty` CLI flags.
- Multiple independent instances on the same symbol (competing MMs).

**pm-mm-bot v1 intentionally excludes:**

- Inventory hedging or position limits beyond a configurable cap.
- Skewing bid/ask based on position (asymmetric quoting).
- Multi-symbol quoting from a single process instance.
- P&L tracking or reporting.
- MMP (Market Maker Protection) — this is enforced server-side.



## 2. Financial Concepts Primer

These concepts are essential for understanding the bot's design decisions.

**Market maker (MM)** — A participant who continuously posts a two-sided price
for an instrument: a price at which they will buy (bid) and a price at which they
will sell (ask). The MM earns the spread over many transactions, compensating for
the risk of holding inventory. Without MMs, buyers and sellers must find each
other organically, which can mean long waits with no price to trade at.

**Two-sided quote** — A simultaneous bid and ask submitted as a linked pair.
In EduMatcher this is the `QUOTE` command. Both legs are regular `LIMIT` orders
in the order book, tagged as a pair so the engine can manage their lifecycle
together (inactivation, status messages, cancel-on-disconnect).

**Spread** — The difference between the ask price and the bid price. For a quote
with `BID=149.95` and `ASK=150.05`, the spread is `$0.10`. The MM collects the
spread when both sides are filled by different counterparties. This document calls
the total spread value the **gap**.

**Half-gap** — Spread / 2. If `gap = 0.10`, the MM places the bid at
`mid - 0.05` and the ask at `mid + 0.05`.

**Mid-price** — `(best_bid + best_ask) / 2`. The MM uses this as the neutral
reference price around which both sides of the quote are placed symmetrically.

**Tick** — The minimum price increment for a symbol (e.g. `0.01` for most
equities). Bid and ask prices must always be rounded to the nearest tick. The
gap must be at least two ticks wide so bid < ask after rounding.

**Quote inactivation** — When one leg of a quote fills, the engine (optionally,
depending on `quote_refresh_policy`) cancels the remaining leg and marks the
quote as inactive. This prevents the MM from having only one side of the market
exposed after a fill. The bot receives a `quote.status` event when this happens
and must re-issue a new quote.

**Partial fill** — A fill that consumes only part of a quote leg. If a resting
ask of 500 is partially lifted for 100, the quote leg has 400 remaining. Depending
on `quote_refresh_policy`, the bid may or may not be cancelled. Regardless, the
bot must detect the partial state and eventually re-issue a fresh full-size quote.

**Drift** — The change in mid-price over time. If the mid moves several ticks
from where the current quote was placed, the bot's quote is no longer centred on
the market. A drifted quote either falls behind the market (increasing adverse
selection risk) or gets lifted aggressively. The bot reprices when the mid drifts
beyond a configurable threshold.

**Adverse selection** — When an MM is filled by a trader who has better
information about the true fair price. For example, if news about AAPL breaks
the MM's ask at 150.05 may be hit by someone who knows the price is about to
jump to 155. The MM sold below the new fair value. Frequent adverse selection
erodes the MM's P&L and is why MMs widen spreads in volatile markets.



## 3. Architecture Overview

Each `pm-mm-bot` instance is a standalone process. It connects to the engine as
a regular `MARKET_MAKER` gateway using the ZMQ PUSH/SUB socket pair.

```mermaid
flowchart LR
    E["pm-engine\nPULL :5555 / PUB :5556"]
    B1["pm-mm-bot\nMM_AAPL_01\nSYM=AAPL"]
    B2["pm-mm-bot\nMM_AAPL_02\nSYM=AAPL"]
    B3["pm-mm-bot\nMM_MSFT_01\nSYM=MSFT"]
    GW["pm-gateway\nParticipant"]

    B1 -- "QUOTE / CANCEL → PUSH :5555" --> E
    B2 -- "QUOTE / CANCEL → PUSH :5555" --> E
    B3 -- "QUOTE / CANCEL → PUSH :5555" --> E
    GW -- "order.new → PUSH :5555" --> E
    E -- "book.AAPL, quote.fill, quote.status → SUB :5556" --> B1
    E -- "book.AAPL, quote.fill, quote.status → SUB :5556" --> B2
    E -- "book.MSFT, quote.fill, quote.status → SUB :5556" --> B3
```

Each bot instance is entirely independent. Two bots quoting the same symbol
(`MM_AAPL_01` and `MM_AAPL_02`) compete as separate market makers — their quotes
appear as separate orders in the book and their fills are tracked separately.
They do not communicate with each other; the engine's order matching handles any
interaction between their quotes naturally.

### 3.1 ZMQ Topics Subscribed

The bot subscribes to the following topics on the engine PUB socket:

| Topic | Purpose |
|---|---|
| `system.gateway_auth.{GW_ID}` | Confirm connection was accepted |
| `system.symbols.{GW_ID}` | Receive the list of tradeable symbols on startup |
| `book.{SYMBOL}` | Track best bid/ask and mid-price updates |
| `trade.executed` | Update last-trade reference price when no book data is available |
| `quote.fill.{GW_ID}` | Know immediately when a quote leg is filled |
| `quote.status.{GW_ID}` | Know when a quote transitions to INACTIVE or CANCELLED |
| `session.state` | Pause and resume quoting based on session phase |
| `circuit_breaker.halt.{SYMBOL}` | Stop quoting immediately on a symbol halt |
| `circuit_breaker.resume.{SYMBOL}` | Resume quoting after a halt is lifted |



## 4. Bot Lifecycle and State Machine

The bot progresses through a well-defined set of internal states from startup
to shutdown. Understanding this state machine is essential before writing any code.

```mermaid
stateDiagram-v2
    [*] --> CONNECTING : process start
    CONNECTING --> AUTHENTICATING : ZMQ sockets open
    AUTHENTICATING --> WAITING_FOR_SESSION : gateway_auth ACK received
    AUTHENTICATING --> [*] : auth rejected or timeout
    WAITING_FOR_SESSION --> QUOTING : session = CONTINUOUS
    WAITING_FOR_SESSION --> WAITING_FOR_SESSION : session = PRE_OPEN / AUCTION / CLOSED
    QUOTING --> QUOTING : book update, drift within threshold
    QUOTING --> REPRICING : mid drift exceeds threshold
    QUOTING --> REISSUING : quote.status = INACTIVE_* received
    QUOTING --> PAUSED : session != CONTINUOUS, or HALTED
    REPRICING --> REISSUING : old quote cancelled
    REISSUING --> QUOTING : new QUOTE sent, ack received
    REISSUING --> REISSUING : ack rejected, retry after delay
    PAUSED --> WAITING_FOR_SESSION : resume trigger received
    QUOTING --> [*] : SIGINT / SIGTERM — cancel quote, disconnect
    PAUSED --> [*] : SIGINT / SIGTERM
```

### 4.1 State Descriptions

| State | Description |
|---|---|
| `CONNECTING` | Opening ZMQ PUSH and SUB sockets; not yet authenticated |
| `AUTHENTICATING` | `gateway_connect` sent; waiting for `gateway_auth` ACK |
| `WAITING_FOR_SESSION` | Connected but session is not `CONTINUOUS`; no quotes posted |
| `QUOTING` | Active quote resting in the book; monitoring for fills and drift |
| `REPRICING` | Mid-price has drifted; cancelling existing quote before re-issuing |
| `REISSUING` | Sending a fresh `QUOTE` command; waiting for engine `quote.ack` |
| `PAUSED` | Session transitioned to a non-trading phase or symbol halted |

### 4.2 Startup Sequence

```mermaid
sequenceDiagram
    participant B as pm-mm-bot
    participant E as pm-engine

    B->>E: system.gateway_connect gateway_id=MM_AAPL_01
    E-->>B: system.gateway_auth.MM_AAPL_01 accepted=true
    B->>E: system.symbols_request gateway_id=MM_AAPL_01
    E-->>B: system.symbols.MM_AAPL_01 symbols=AAPL/MSFT/...
    Note over B: verify assigned symbol is in the list
    Note over B: wait for first book.AAPL to get mid-price
    E-->>B: book.AAPL best_bid=149.95 best_ask=150.05
    Note over B: mid = 150.00 -- compute bid/ask
    B->>E: quote.new SYM=AAPL BID=149.95 ASK=150.05
    E-->>B: quote.ack.MM_AAPL_01 accepted=true
    Note over B: state = QUOTING
```

### 4.3 Graceful Shutdown

On `SIGINT` or `SIGTERM` the bot:

1. Sends `CANCEL|QUOTE_ID=<current_id>` to pull its live quote.
2. Waits up to `shutdown_timeout_sec` (default: 2 s) for `quote.status` confirmation.
3. Closes ZMQ sockets and exits.

If the engine does not reply within the timeout, the bot exits anyway. The engine
will cancel the quote on disconnect according to the gateway's `disconnect_behaviour`
setting (which must be `CANCEL_QUOTES_ONLY` or `CANCEL_ALL` for MM gateways).



## 5. Price Reference and Quote Placement

### 5.1 Mid-Price Tracking

The bot maintains a running `_mid_price` derived from the most recent
`book.{SYMBOL}` event. Mid-price is recomputed on every book update:

```python
def _update_mid(self, best_bid: float | None, best_ask: float | None) -> None:
    if best_bid is not None and best_ask is not None:
        self._mid_price = (best_bid + best_ask) / 2.0
    elif best_ask is not None:
        # One-sided ask-only book: use ask as reference
        self._mid_price = best_ask
    elif best_bid is not None:
        # One-sided bid-only book: use bid as reference
        self._mid_price = best_bid
    # else: no book data yet — keep previous _mid_price
```

If no book event has arrived yet (the book is completely empty), the bot also
listens to `trade.executed` for the symbol and uses the last trade price as a
fallback reference. If neither source is available, the bot remains in
`WAITING_FOR_SESSION` until at least one price reference is established.

### 5.2 Quote Price Calculation

Given `mid_price`, `gap`, and `tick_size`:

```python
def _compute_quote_prices(self) -> tuple[float, float]:
    """
    Return (bid_price, ask_price) rounded to the nearest tick.

    The gap is the total spread. Half-gap is placed on each side of mid.
    After rounding, a final sanity check ensures bid < ask.
    """
    half_gap = self._gap / 2.0
    raw_bid = self._mid_price - half_gap
    raw_ask = self._mid_price + half_gap

    # Round to nearest tick (away from zero for ask, toward zero for bid)
    bid = math.floor(raw_bid / self._tick_size + 0.5) * self._tick_size
    ask = math.ceil(raw_ask / self._tick_size - 0.5) * self._tick_size

    # Guarantee minimum spread of 2 ticks even after rounding
    if ask - bid < 2 * self._tick_size:
        ask = bid + 2 * self._tick_size

    return round(bid, _PRICE_DECIMALS), round(ask, _PRICE_DECIMALS)
```

> **`_PRICE_DECIMALS`** is derived from `tick_size`: e.g. `tick_size=0.01`
> gives `_PRICE_DECIMALS=2`. It is computed once at startup from the symbol
> config in the `system.symbols` payload.

### 5.3 Drift Detection

After posting a quote, the bot records the mid-price at the time of posting as
`_quoted_at_mid`. On each subsequent `book.{SYMBOL}` event, it checks whether
the mid has moved by more than `drift_ticks`:

```python
def _mid_has_drifted(self) -> bool:
    if self._quoted_at_mid is None:
        return False
    drift = abs(self._mid_price - self._quoted_at_mid)
    return drift > self._drift_ticks * self._tick_size
```

When drift is detected and the bot is in state `QUOTING`, it transitions to
`REPRICING`: it cancels the existing quote and immediately re-issues at the
updated mid. This keeps the quote centred on the current market at all times.

### 5.4 Quantity Policy

Quote size is controlled by `--qty` (default: `500`). Both bid and ask legs
always post the full `--qty` value. After a partial fill, the remaining
quantity on the filled leg drops below `--qty`, but the bot does not top it up
in place — it cancels the quote and re-issues a fresh full-size quote. This
keeps the logic simple and avoids accumulating stale partial quotes.



## 6. Quote Refresh Logic

This is the core of the bot's responsibility: ensuring the symbol always has
a live two-sided quote.

### 6.1 Refresh Triggers

The bot re-issues a quote in response to any of these events:

| Trigger | Source | Action |
|---|---|---|
| `quote.status` with `INACTIVE_BID_FILLED` | Engine → Bot | Cancel ask leg if still live, then reissue |
| `quote.status` with `INACTIVE_ASK_FILLED` | Engine → Bot | Cancel bid leg if still live, then reissue |
| `quote.status` with `CANCELLED` | Engine → Bot | Reissue immediately (unless in PAUSED state) |
| `quote.fill` with `remaining_qty = 0` | Engine → Bot | Full fill on one leg; reissue after delay |
| `quote.fill` with `remaining_qty > 0` | Engine → Bot | Partial fill; schedule reissue after `reissue_delay_ms` |
| Mid-price drift exceeds `drift_ticks` | `book.SYMBOL` event | Cancel current quote, reissue at new mid |
| Periodic heartbeat check | Internal timer | If no active quote and session is CONTINUOUS, reissue |

### 6.2 Reissue Delay

An immediate reissue after every fill would spam the engine with new quotes,
many of which would be cancelled fractions of a second later as the next fill
arrives. The bot waits for `reissue_delay_ms` (default: `200 ms`) after a fill
event before sending the next quote. This batches rapid successive fills into a
single re-quote cycle.

The delay timer is reset if another fill arrives while it is running (the bot
starts the timer over), so a burst of fills results in exactly one reissue
`reissue_delay_ms` after the last fill in the burst.

```python
def _on_quote_fill(self, payload: dict) -> None:
    """Called when a fill event arrives for our quote."""
    self._log(f"Fill: {payload['filled_side']} {payload['fill_qty']}@{payload['fill_price']}")
    # Reset or start the reissue timer
    self._reissue_at = time.monotonic() + self._reissue_delay_sec

def _tick(self) -> None:
    """Called in the main loop on every iteration."""
    now = time.monotonic()
    if self._reissue_at is not None and now >= self._reissue_at:
        self._reissue_at = None
        self._cancel_and_reissue()
```

### 6.3 Cancel Before Reissue

Before posting a new quote the bot always cancels the previous one explicitly,
even if it believes the quote is already fully consumed. This defensive approach
handles edge cases where:

- A partial fill left one leg partially alive.
- The engine inactivated one leg but the other is still resting.
- A network hiccup delayed a status update.

The cancellation uses `CANCEL|QUOTE_ID=<id>` (symbol-specific cancel). After
sending the cancel, the bot waits for the `quote.status` event confirming
`CANCELLED` state, then issues the new `QUOTE`. If no confirmation arrives
within `cancel_timeout_sec` (default: 1 s), the bot issues the new quote anyway
to avoid being stuck without liquidity.

```mermaid
sequenceDiagram
    participant B as pm-mm-bot
    participant E as pm-engine

    Note over B: fill received -- start reissue_delay timer
    Note over B: timer fires
    B->>E: CANCEL|QUOTE_ID=q-001
    E-->>B: quote.status.MM_AAPL_01 status=CANCELLED
    Note over B: compute new bid/ask from current mid
    B->>E: QUOTE|SYM=AAPL|BID=149.97|ASK=150.03|BID_QTY=500|ASK_QTY=500
    E-->>B: quote.ack.MM_AAPL_01 accepted=true quote_id=q-002
    Note over B: state = QUOTING
    Note over B: _quoted_at_mid = current_mid
```

### 6.4 Heartbeat Guard

In addition to event-driven refresh, the bot runs a periodic check every
`heartbeat_interval_sec` (default: `5 s`). If it is in state `QUOTING` but
has no record of an active `quote_id` — which should never happen but can occur
after a missed event — it logs a warning and re-issues the quote.

This provides resilience against dropped ZMQ messages in unreliable network
environments.



## 7. Session State Handling

The bot must respect the exchange session lifecycle. Posting quotes during an
auction or while the exchange is closed is wasteful and will be rejected by the
engine.

### 7.1 Allowed Quoting States

| Session State | Bot Behaviour |
|---|---|
| `PRE_OPEN` | Stay in `WAITING_FOR_SESSION`; do not post quotes |
| `OPENING_AUCTION` | Stay in `WAITING_FOR_SESSION`; cancel any live quote |
| `CONTINUOUS` | Post and maintain a live two-sided quote |
| `CLOSING_AUCTION` | Transition to `PAUSED`; cancel any live quote |
| `CLOSED` | Transition to `PAUSED`; cancel any live quote |
| `HALTED` (symbol-specific) | Transition to `PAUSED`; cancel any live quote |

### 7.2 Transition to CONTINUOUS

When a `session.state` event arrives with `state=CONTINUOUS`, the bot transitions
from `WAITING_FOR_SESSION` (or `PAUSED`) to `REISSUING`. It first checks that a
valid `_mid_price` is available. If no book data has been received yet (the book
is empty), it waits for the first `book.{SYMBOL}` event before posting.

### 7.3 Quote Cancellation on Auction Entry

When a `session.state` event signals `OPENING_AUCTION` or `CLOSING_AUCTION`,
the bot sends `CANCEL|QUOTE_ID=<id>` immediately without waiting for the
reissue delay. Auction phases collect orders under different rules; the MM
bot should not interfere with the auction price formation.

### 7.4 Circuit Breaker Halt

`circuit_breaker.halt.{SYMBOL}` is a per-symbol topic. When received:

1. The bot cancels any live quote.
2. It transitions to `PAUSED` regardless of the session state.
3. It logs the halt and waits.

When `circuit_breaker.resume.{SYMBOL}` arrives, the bot transitions back to
`WAITING_FOR_SESSION` and then to `QUOTING` on the next `book.{SYMBOL}` event.



## 8. Entry Point and CLI Reference

### 8.1 Entry Point

The bot is registered as a `pm-mm-bot` console script in `pyproject.toml`:

```toml
pm-mm-bot = "edumatcher.mm_bot.main:main"
```

### 8.2 Basic Usage

```bash
# Minimal — symbol is the only required argument
pm-mm-bot --symbol AAPL

# Explicit gap and quantity
pm-mm-bot --symbol AAPL --gap 0.10 --qty 500

# Second MM instance on the same symbol (running number 02)
pm-mm-bot --symbol AAPL --gap 0.12 --qty 300 --id-suffix 02

# Faster repricing for volatile sessions
pm-mm-bot --symbol MSFT --gap 0.20 --drift-ticks 1 --reissue-delay-ms 100

# GTC quotes that survive session boundaries
pm-mm-bot --symbol TSLA --gap 0.30 --tif GTC

# In developer (Poetry) mode
poetry run pm-mm-bot --symbol AAPL --gap 0.10 --qty 500 -v
```

### 8.3 CLI Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `--symbol SYM` | **Yes** | — | Instrument to make a market in (e.g. `AAPL`) |
| `--gap PRICE` | No | `0.10` | Total spread in price units (bid placed at mid−gap/2, ask at mid+gap/2). Must be ≥ 2 ticks |
| `--qty N` | No | `500` | Quote size on each leg |
| `--id-suffix NN` | No | `01` | Running number appended to the gateway ID (`MM_AAPL_01`). Allows multiple instances |
| `--drift-ticks N` | No | `3` | Reprice the quote when mid moves by this many ticks from the posted mid |
| `--reissue-delay-ms N` | No | `200` | Milliseconds to wait after a fill before re-issuing |
| `--tif {DAY,GTC}` | No | `DAY` | Time-in-force for quote legs |
| `--heartbeat-interval-sec F` | No | `5.0` | Interval for the periodic "do I have a live quote?" check |
| `--cancel-timeout-sec F` | No | `1.0` | Max wait for cancel confirmation before proceeding with reissue |
| `--shutdown-timeout-sec F` | No | `2.0` | Max wait for cancel confirmation on SIGINT/SIGTERM |
| `--engine-pull ADDR` | No | `tcp://127.0.0.1:5555` | Engine PUSH/PULL address |
| `--engine-pub ADDR` | No | `tcp://127.0.0.1:5556` | Engine PUB address |
| `-v`, `--verbose` | No | `false` | Print debug-level events (every book update, fill, status) |

### 8.4 Gap Guidelines

If `mm_max_spread_ticks` is configured on the engine for this symbol, the
`--gap` value must satisfy:

```
gap ≤ mm_max_spread_ticks × tick_size
```

The bot validates this at startup (after receiving the `system.symbols` response
which includes `tick_size`) and exits with a clear error message if the gap
violates the obligation. The operator is expected to fix the gap and restart.

If `--gap` is not provided and the engine's `mm_max_spread_ticks` for the symbol
is known, the bot **defaults the gap to half of the maximum** as a conservative
starting point:

```python
default_gap = (mm_max_spread_ticks / 2) * tick_size
```

If neither `--gap` is set nor `mm_max_spread_ticks` is configured, the bot
defaults to `0.10` as a safe starting value for demonstration purposes.



## 9. Gateway Identity and Configuration

### 9.1 Gateway ID Convention

Each bot instance uses the gateway ID format:

```
MM_<SYMBOL>_<nn>
```

Where `<SYMBOL>` is the symbol in uppercase and `<nn>` is the two-digit
running number from `--id-suffix` (zero-padded). Examples:

| `--symbol` | `--id-suffix` | Gateway ID |
|---|---|---|
| `AAPL` | `01` (default) | `MM_AAPL_01` |
| `AAPL` | `02` | `MM_AAPL_02` |
| `MSFT` | `01` | `MM_MSFT_01` |
| `TSLA` | `03` | `MM_TSLA_03` |

This convention makes bot gateway IDs immediately identifiable in logs, the
admin console, and the order book viewer.

### 9.2 Required engine_config.yaml Entries

Before starting a bot, each gateway ID it will use must be pre-registered in
`engine_config.yaml` with `role: MARKET_MAKER`. Without this, the engine will
reject the `QUOTE` command with: _"Quotes are only allowed for MARKET_MAKER
participants"_.

```yaml
gateways:
  alf:
    # Bot instances for AAPL
    - id: MM_AAPL_01
      description: "AAPL market-maker bot instance 1"
      role: MARKET_MAKER
      disconnect_behaviour: CANCEL_QUOTES_ONLY
      quote_refresh_policy: INACTIVATE_ON_ANY_FILL
      enforce_mm_obligation: true
      mm_max_spread_ticks: 10      # max 10 ticks = $0.10 for tick_size=0.01
      mm_min_qty: 100

    - id: MM_AAPL_02
      description: "AAPL market-maker bot instance 2"
      role: MARKET_MAKER
      disconnect_behaviour: CANCEL_QUOTES_ONLY
      quote_refresh_policy: INACTIVATE_ON_ANY_FILL

    # Bot instance for MSFT
    - id: MM_MSFT_01
      description: "MSFT market-maker bot instance 1"
      role: MARKET_MAKER
      disconnect_behaviour: CANCEL_QUOTES_ONLY
      quote_refresh_policy: INACTIVATE_ON_ANY_FILL
```

> **Tip:** Use `pm-config-gen --gateways MM_AAPL_01:MARKET_MAKER MM_MSFT_01:MARKET_MAKER`
> to generate the gateway stanzas automatically.

### 9.3 Recommended disconnect_behaviour

MM bot gateways should always use `disconnect_behaviour: CANCEL_QUOTES_ONLY`.
This ensures that if the bot crashes or is restarted, its quotes are immediately
pulled from the book. A dead bot cannot react to market moves; leaving its stale
quotes resting would mislead other participants.



## 10. ZMQ Message Flow

### 10.1 Messages Sent by the Bot (PUSH → Engine)

| Message | When Sent | Key Fields |
|---|---|---|
| `system.gateway_connect` | Startup | `gateway_id` |
| `system.symbols_request` | After auth ACK | `gateway_id` |
| `quote.new` | Entering QUOTING state | `gateway_id`, `symbol`, `bid`, `ask`, `bid_qty`, `ask_qty`, `quote_id`, `tif` |
| `quote.cancel` | Before reissue; on PAUSED; on shutdown | `gateway_id`, `symbol` (or `quote_id`) |

> The `QUOTE` command on the ALF gateway protocol translates to a `quote.new`
> ZMQ message. The bot uses the same message structure directly, bypassing the
> text terminal. This is the same pattern used by `pm-ai-trader`.

### 10.2 Messages Received by the Bot (SUB ← Engine)

| Topic | When Received | Action |
|---|---|---|
| `system.gateway_auth.{GW}` | After connect | Check `accepted`; abort if false |
| `system.symbols.{GW}` | After symbols request | Extract symbol list; verify assigned symbol exists; get `tick_size` |
| `book.{SYMBOL}` | On every book update | Update `_mid_price`; check for drift |
| `trade.executed` | On every fill | Update last-trade price if book mid unavailable |
| `quote.ack.{GW}` | After QUOTE sent | Record `quote_id`; transition to QUOTING |
| `quote.fill.{GW}` | When a quote leg is hit | Log fill; start/reset reissue timer |
| `quote.status.{GW}` | When quote state changes | Handle INACTIVE/CANCELLED; trigger reissue |
| `session.state` | On every session transition | Update session state; trigger PAUSED/QUOTING |
| `circuit_breaker.halt.{SYMBOL}` | On circuit breaker fire | Cancel quote; enter PAUSED |
| `circuit_breaker.resume.{SYMBOL}` | On circuit breaker lift | Re-enter WAITING_FOR_SESSION |

### 10.3 Full Normal Trading Cycle

```mermaid
sequenceDiagram 
    participant B as pm-mm-bot
    participant E as pm-engine
    participant T as Trader Gateway

    Note over B,E: bot is QUOTING — bid=149.97 / ask=150.03
    T->>E: NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.03
    E-->>T: order.fill.TRD01 100@150.03
    E-->>B: quote.fill.MM_AAPL_01 filled_side=ASK qty=100 remaining=400
    E-->>B: quote.status.MM_AAPL_01 status=INACTIVE_ASK_FILLED
    Note over B: bid still resting at 149.97 for 500
    Note over B: ask inactivated -- 400 remaining
    Note over B: reissue timer started
    Note over B: timer fires
    B->>E: CANCEL|QUOTE_ID=q-001
    E-->>B: quote.status.MM_AAPL_01 status=CANCELLED
    Note over B: mid still 150.00 -- recompute bid/ask
    B->>E: QUOTE|SYM=AAPL|BID=149.97|ASK=150.03|BID_QTY=500|ASK_QTY=500
    E-->>B: quote.ack.MM_AAPL_01 accepted=true quote_id=q-002
    Note over B: state = QUOTING with fresh full-size quote
```

### 10.4 Mid-Price Drift Reprice

```mermaid
sequenceDiagram
    participant B as pm-mm-bot
    participant E as pm-engine

    Note over B: QUOTING — bid=149.95 / ask=150.05
    Note over B: _quoted_at_mid = 150.00
    E-->>B: book.AAPL best_bid=150.08 best_ask=150.12
    Note over B: new mid = 150.10
    Note over B: drift = 0.10 exceeds drift_ticks=3 threshold
    Note over B: state = REPRICING
    B->>E: CANCEL|QUOTE_ID=q-002
    E-->>B: quote.status.MM_AAPL_01 status=CANCELLED
    Note over B: compute new bid=150.05 / ask=150.15
    B->>E: QUOTE|SYM=AAPL|BID=150.05|ASK=150.15|BID_QTY=500|ASK_QTY=500
    E-->>B: quote.ack.MM_AAPL_01 accepted=true quote_id=q-003
    Note over B: state = QUOTING
    Note over B: _quoted_at_mid = 150.10
```



## 11. New Files and Changes to Existing Files

### 11.1 New Files

| File | Purpose |
|---|---|
| `src/edumatcher/mm_bot/__init__.py` | Package marker |
| `src/edumatcher/mm_bot/main.py` | Entry point; `main()` function; argument parsing |
| `src/edumatcher/mm_bot/bot.py` | `MMBot` class; state machine; event loop |
| `src/edumatcher/mm_bot/pricer.py` | `QuotePricer` class; mid-price, quote price calculation, drift detection |
| `tests/test_mm_bot.py` | Unit tests (see Section 13) |

### 11.2 Changes to Existing Files

| File | Change |
|---|---|
| `pyproject.toml` | Add `pm-mm-bot = "edumatcher.mm_bot.main:main"` to `[tool.poetry.scripts]` |
| `engine_config.yaml` (example) | Add sample `MM_*` gateway entries (see Section 9.2) |
| `docs/user-guide/15-ai-traders.md` | Add a note pointing to the new MM bot |

No changes are required to the engine, models, or message layer — all necessary
ZMQ message types (`quote.new`, `quote.cancel`, `quote.fill`, `quote.status`,
`quote.ack`) are already implemented.

### 11.3 Module Responsibilities

#### `mm_bot/main.py`

- Parse CLI arguments.
- Validate `--gap` against `mm_max_spread_ticks` after receiving symbol config.
- Instantiate `MMBot` and call `bot.run()`.
- Install signal handlers for `SIGINT`/`SIGTERM` that call `bot.shutdown()`.

#### `mm_bot/bot.py`

- Own the ZMQ sockets (`push_sock`, `sub_sock`).
- Implement the event loop: `zmq.Poller` on `sub_sock` with a timeout equal
  to `min(heartbeat_interval_sec, reissue_delay_sec / 2)`.
- Dispatch incoming messages to handler methods.
- Manage the `_state`, `_quote_id`, `_reissue_at`, and `_quoted_at_mid` fields.
- Delegate price calculation to `QuotePricer`.

#### `mm_bot/pricer.py`

- `QuotePricer(tick_size, gap, drift_ticks)` — pure logic with no ZMQ dependency.
- `update_mid(best_bid, best_ask)` → updates internal mid.
- `compute_prices()` → `(bid, ask)`.
- `has_drifted(quoted_at_mid)` → `bool`.
- Fully testable without any ZMQ or engine dependency.



## 12. Configuration Reference

### 12.1 Full YAML Example

```yaml
# engine_config.yaml excerpt — market-maker bot gateway registrations

mm_obligation_defaults:
  enforce_mm_obligation: true
  mm_max_spread_ticks: 10         # max gap = 10 ticks = $0.10 at tick_size=0.01
  mm_min_qty: 100                 # min qty on each quote leg

  symbols:
    AAPL:
      mm_max_spread_ticks: 8      # tighter spread obligation for AAPL
      mm_min_qty: 200

    MSFT:
      mm_max_spread_ticks: 12
      mm_min_qty: 100

gateways:
  alf:
    # AAPL market makers — two competing instances
    - id: MM_AAPL_01
      description: "AAPL MM bot — primary"
      role: MARKET_MAKER
      disconnect_behaviour: CANCEL_QUOTES_ONLY
      quote_refresh_policy: INACTIVATE_ON_ANY_FILL
      enforce_mm_obligation: true

    - id: MM_AAPL_02
      description: "AAPL MM bot — secondary (wider spread)"
      role: MARKET_MAKER
      disconnect_behaviour: CANCEL_QUOTES_ONLY
      quote_refresh_policy: INACTIVATE_ON_ANY_FILL

    # MSFT market maker — single instance
    - id: MM_MSFT_01
      description: "MSFT MM bot"
      role: MARKET_MAKER
      disconnect_behaviour: CANCEL_QUOTES_ONLY
      quote_refresh_policy: INACTIVATE_ON_FULL_FILL
```

### 12.2 Bot Launch Reference

```bash
# Start all MM bots for a typical classroom session
pm-mm-bot --symbol AAPL --gap 0.08 --qty 500 &
pm-mm-bot --symbol AAPL --gap 0.12 --qty 300 --id-suffix 02 &
pm-mm-bot --symbol MSFT --gap 0.10 --qty 500 &
```

Or using the provided launch script that detects pipx vs. Poetry mode:

```bash
./tools/launch_mm_bots.sh   # starts MM bots for all symbols in engine_config.yaml
```

### 12.3 Parameter Quick Reference

| Parameter | CLI Flag | YAML (gateway) | Default | Notes |
|---|---|---|---|---|
| Gap (total spread) | `--gap` | — (runtime only) | `0.10` or auto from `mm_max_spread_ticks/2 × tick_size` | Must satisfy `mm_max_spread_ticks` obligation if set |
| Quote quantity | `--qty` | — (runtime only) | `500` | Must satisfy `mm_min_qty` obligation if set |
| Drift threshold | `--drift-ticks` | — (runtime only) | `3` | Ticks from posted mid before reprice |
| Reissue delay | `--reissue-delay-ms` | — (runtime only) | `200` | Batches rapid fills |
| TIF | `--tif` | — (runtime only) | `DAY` | `DAY` or `GTC` |
| Refresh policy | — | `quote_refresh_policy` | `INACTIVATE_ON_ANY_FILL` | Engine-side; controls automatic inactivation |
| Disconnect policy | — | `disconnect_behaviour` | `CANCEL_QUOTES_ONLY` | Engine-side; controls cleanup on crash |



## 13. Testing Guide

### 13.1 Unit Tests — `QuotePricer`

`QuotePricer` has no ZMQ dependency and can be tested directly.

| Test | Verifies |
|---|---|
| `test_prices_symmetric` | `bid = mid − gap/2`, `ask = mid + gap/2`, both tick-aligned |
| `test_prices_minimum_spread` | Rounding never produces `bid >= ask`; always at least 2 ticks apart |
| `test_drift_detected` | `has_drifted()` returns True when mid moves by > drift_ticks ticks |
| `test_drift_not_detected` | Returns False when mid moves within threshold |
| `test_mid_from_book` | `update_mid(bid, ask)` uses average when both sides present |
| `test_mid_from_ask_only` | Falls back to ask when no bid |
| `test_mid_from_bid_only` | Falls back to bid when no ask |
| `test_gap_validation` | Raises `ValueError` when `gap < 2 × tick_size` |

### 13.2 Integration Tests — `MMBot`

These tests use the same `_DummySocket` / `monkeypatch` pattern as `test_perf.py`.
The bot is instantiated with a mock engine; events are injected directly.

| Test | Verifies |
|---|---|
| `test_startup_sends_gateway_connect` | On `run()`, the first PUSH message is `system.gateway_connect` |
| `test_auth_failure_exits` | Bot exits cleanly if `gateway_auth.accepted = false` |
| `test_quote_issued_after_book_update` | Bot sends `QUOTE` after receiving first `book.SYMBOL` in CONTINUOUS state |
| `test_reissue_after_fill` | `quote.fill` → timer fires → CANCEL sent → QUOTE sent |
| `test_reissue_batches_rapid_fills` | Three fills in 50 ms produce exactly one reissue |
| `test_drift_triggers_reprice` | Mid moves 4 ticks → CANCEL then QUOTE at new mid |
| `test_no_quote_in_auction` | Bot in QUOTING receives `session.state=OPENING_AUCTION` → CANCEL, no reissue |
| `test_resume_from_pause` | `session.state=CONTINUOUS` from PAUSED → bot re-enters QUOTING |
| `test_halt_cancels_quote` | `circuit_breaker.halt.AAPL` → CANCEL, state=PAUSED |
| `test_resume_after_halt` | `circuit_breaker.resume.AAPL` → state returns to QUOTING |
| `test_graceful_shutdown` | `bot.shutdown()` → CANCEL sent; sockets closed |
| `test_gap_obligation_check` | Bot startup fails cleanly if `--gap` exceeds `mm_max_spread_ticks` |

### 13.3 Running Tests

```bash
# Run all mm_bot tests
poetry run pytest tests/test_mm_bot.py -v

# Run just the pricer unit tests
poetry run pytest tests/test_mm_bot.py -v -k pricer

# Skip slow integration tests during development
poetry run pytest tests/test_mm_bot.py -v -k "not integration"
```



## 14. Open Questions and Future Work

### 14.1 Inventory Skewing

In a production MM system, when the bot has accumulated a long position it
widens the ask and narrows the bid (making it easier to sell and harder to buy
more). This **skewed quoting** reduces adverse selection and controls inventory.
`pm-mm-bot` v1 always quotes symmetrically around the mid. A future version
could add:

- `--max-position N` to cap net inventory in either direction.
- An `--inventory-skew` flag that shifts the mid by `inventory × skew_factor`.

### 14.2 Volatility-Adaptive Spread

During fast markets the spread should widen to compensate for increased adverse
selection risk. A future version could subscribe to a rolling volatility estimate
(e.g. from `pm-stats`) and scale `gap` dynamically:

```
effective_gap = base_gap × max(1.0, vol_factor)
```

### 14.3 Multi-Symbol Mode

Running one process per symbol is simple and isolated but requires more terminals
in a classroom. A future `--symbols AAPL,MSFT,TSLA` mode could manage multiple
quotes from a single process, similar to how `pm-ai-swarm` manages multiple
single-trader bots.

### 14.4 Config-File Mode

All bot parameters are currently CLI flags. A YAML config file mode
(`pm-mm-bot --config mm_aapl.yaml`) would allow complex configurations to be
version-controlled alongside `engine_config.yaml`, and would make the launch
script simpler.

### 14.5 Coordination Between MM Instances

Currently, two MM instances on the same symbol (`MM_AAPL_01` and `MM_AAPL_02`)
are completely independent. They may both drift-reprice at the same time,
temporarily leaving the book with a wider-than-intended spread during the cancel
window. A coordination mechanism (e.g. staggered reprice delays) could be
designed to prevent this, but adds complexity not needed for educational use.

### 14.6 Metrics and Observability

Add a `--metrics-port` option to expose a simple HTTP metrics endpoint
(Prometheus-style) showing:

- Current state, `_mid_price`, `_gap`, `quote_id`.
- Total quotes issued, fills received, reprices triggered.
- Uptime and last-quote timestamp.

This would allow an instructor to monitor all running bots from a single
dashboard during a classroom session.


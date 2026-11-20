# Risk Controls You Meet

!!! note "Learning objectives"
    After reading this page you will understand:

    - Which exchange safeguards can refuse, pause or cancel your orders
    - What each rejection or cancellation looks like, and what to do about it
    - What happens to your resting orders when a symbol halts, and how it
      reopens
    - What happens to your orders when you use the kill switch or your
      session ends
    - Where to look up the limits that apply to a symbol

    **Prerequisites**: [Order Types](020-order-types.md) and
    [A Full Trading Day](../part-1-trading-basics/030-the-trading-day-and-auctions.md).

Every exchange protects its market against mistakes and disorder: a mistyped
price, an extra zero on a quantity, a price that runs away in seconds, a bot
that will not stop. EduMatcher has the same safeguards. The operator sets
them in the exchange configuration; this page explains what they do to *your*
orders. How they are configured is in the Operator's Guide chapter
[Risk Controls](../../operator-guide/part-4-run-a-market/040-risk-controls.md).

| Control | Acts on | You see |
|---|---|---|
| [Tick size](#tick-size) | Every price you type | The order is refused before it is sent |
| [Order size and value limits](#order-size-and-value-limits) | A new or amended order | `REJECTED` `MAX_ORDER_QTY` / `MAX_ORDER_VALUE` |
| [Price collars](#price-collars) | A new or amended priced order | `REJECTED` `COLLAR_BREACH` |
| [Circuit breakers](#circuit-breakers-and-halts) | The symbol, after a sharp price move | The symbol halts; `MARKET`/`IOC`/`FOK` rejected `CIRCUIT_BREAKER_ACTIVE` |
| [Operator halts](#operator-halts) | A symbol or the whole market | `MARKET`/`IOC`/`FOK` rejected `INSTRUMENT_HALTED` |
| [Session phase](#session-phase) | Every order | `REJECTED` `MARKET_CLOSED` / `SESSION_NOT_PERMITTED` |
| [Kill switch](#the-kill-switch) | Your resting orders | `CANCELLED … reason=KILL_SWITCH` |
| [Disconnect behaviour](#when-your-session-ends) | Your resting orders when you log off | Orders cancelled, or left resting |
| [Self-match prevention](#self-match-prevention) | Your order meeting your own resting order | `CANCELLED … reason=SELF_MATCH_PREVENTED` |
| [Rate limits](#rate-limits) | How fast a program sends | Requests refused for a moment |

The messages below are what the trader console (`pm-alf-console`) prints;
the order id is shortened here. Other front-ends show the same `code` and
reason text.

## Tick size

Every symbol has a smallest price step, its *tick*: `0.01` for a symbol with
two decimals. A price that is not a whole number of ticks is refused by the
console before anything is sent:

```text
[TRADER01]> NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.001
150.001 is not a multiple of AAPL's tick size 0.01
```

`SYMBOLS` lists every symbol's tick. The ALF and REST gateways refuse such a
price with `TICK_VIOLATION`.

## Order size and value limits

A symbol can cap the size of a single order (`max_order_qty`) and its value,
quantity × price (`max_order_value`). They catch the order with an extra zero
that every price check would let through.

```text
REJECTED  601cb911… code=MAX_ORDER_QTY  Quantity 2000 exceeds max_order_qty 1000
REJECTED  50745acf… code=MAX_ORDER_VALUE  Order value 60000.00 exceeds max_order_value 50000.0
```

- The quantity cap applies to every order type; the value cap only to orders
  that carry a price (not `MARKET`).
- An amend is checked against the same caps, so you cannot place a small
  order and amend it up.
- An order over a cap is rejected, never cut down to fit. Split it into
  several orders, each within the limits.
- A symbol with no caps configured has no limit.

## Price collars

A collar rejects an order whose price is too far from where the symbol
trades, the classic "fat finger". It has two bands, both a percentage:

| Band | Measured from | Typical width |
|---|---|---|
| **Static** | The symbol's reference price at the start of the day | Wide, e.g. ±20% |
| **Dynamic** | The last trade of the session (skipped until the first trade) | Narrow, e.g. ±2% |

```text
REJECTED  cd464bb5… code=COLLAR_BREACH  STATIC_COLLAR_BREACH: price 13000 ticks is outside [8000, 12000] ticks (±20% from reference 10000)
REJECTED  ea225ff3… code=COLLAR_BREACH  DYNAMIC_COLLAR_BREACH: price 11100 ticks is outside [9000, 11000] ticks (±10% from last trade 10000)
```

The band is printed in ticks: `[9000, 11000]` on a two-decimal symbol is
90.00 to 110.00.

- Every order with a price is checked: `LIMIT`, `ICEBERG`, `IOC`, `FOK`,
  `STOP_LIMIT`, an amend's new price, and each leg of an OCO or combo (one
  leg outside the band rejects the whole OCO or combo).
- A `MARKET` order has no price and is not collared — one more reason to
  prefer a priced `IOC` when the book is thin.
- A market maker's two-sided quote is not collared.
- The dynamic band moves with every trade. A price refused now may be
  accepted a few trades later, once the market has moved towards it.

## Circuit breakers and halts

A collar refuses one order. A **circuit breaker** watches the trades instead,
and when a trade moves the price too far from its recent average (for example
more than 5% within five minutes), it **halts the symbol**. The trade that
tripped the breaker stands; trading in that symbol then pauses.

While a symbol is halted:

| Your order | What happens |
|---|---|
| `MARKET`, `IOC`, `FOK` | Rejected: `CIRCUIT_BREAKER_ACTIVE  AAPL is halted — MARKET orders rejected during circuit breaker halt` |
| `LIMIT`, `ICEBERG` | Accepted and rests, without matching, until the reopening |
| `STOP`, `STOP_LIMIT`, `TRAILING_STOP` | Accepted and stored; they can trigger only on a trade |
| Orders already resting | Stay on the book, untouched |
| Market-maker quotes | Cancelled when the halt starts; new quotes are rejected |
| Amend and cancel | Work as usual |

The halt lasts as long as its configured level says — a breaker can have
several levels, a bigger move halting for longer. A short random delay is
added to its end, so nobody can time an order to arrive at the last instant.

**The reopening is an auction.** Because limit orders rest without matching
during the halt, buyers and sellers can end up crossing each other. At the end
of the halt the engine uncrosses the book at a single price, exactly like
[the opening auction](../part-1-trading-basics/030-the-trading-day-and-auctions.md#the-uncross-how-the-opening-price-is-computed),
and then continuous trading resumes. If that reopening price would be too far
from the price before the halt, the symbol does **not** reopen yet: the
allowed band widens and the halt is extended, step by step, until a reopening
price fits. Your orders keep resting throughout. Auction prices never trip the
breaker themselves.

!!! tip "Use the halt"
    A halt is time to think, not just a pause. Check the news, look at the
    book, and cancel or re-price resting orders you no longer want filled at
    the reopening. A limit order placed during the halt takes part in the
    reopening auction.

The trader console does not announce a halt; you learn of it from the
`CIRCUIT_BREAKER_ACTIVE` rejection. The Trading GUI and TapeDeck show a `HALT`
badge on the symbol, with the level and the expected reopening time.

## Operator halts

The operator can halt a single symbol or the whole market at any time — for
pending news, a technical problem, or a classroom exercise. While halted,
orders behave exactly as under a circuit breaker, but the rejection code is
different:

```text
REJECTED  0b87dfbd… code=INSTRUMENT_HALTED  AAPL is halted — FOK orders rejected during trading halt
```

The difference matters: a `CIRCUIT_BREAKER_ACTIVE` halt ends by itself; an
`INSTRUMENT_HALTED` halt, without a level, lasts until the operator lifts it.

## Session phase

Outside continuous trading the phase decides what you may send; see
[A Full Trading Day](../part-1-trading-basics/030-the-trading-day-and-auctions.md).

| Rejection | Cause |
|---|---|
| `MARKET_CLOSED  Market is closed` | The session is `CLOSED`; no order is accepted |
| `SESSION_NOT_PERMITTED  MARKET orders not accepted during PRE_OPEN` | A `MARKET`, `IOC` or `FOK` outside continuous trading |
| `SESSION_NOT_PERMITTED  ATO orders only accepted during opening auction` | `TIF=ATO` outside the opening auction (likewise `ATC`) |

Type `SESSION` in the trader console to see the current phase.

## The kill switch

`KILL` cancels **all** your resting orders and quotes at once; `KILL|SYM=AAPL`
only those on one symbol. It is your emergency brake when a strategy or a bot
misbehaves:

```text
[TRADER01]> KILL
[10:12:48.453] CANCELLED 4d11d22b… reason=KILL_SWITCH
[10:12:48.455] CANCELLED 8ec835fc… reason=KILL_SWITCH
[10:12:48.456] KILL ACK  orders=2 quote_legs=0
```

The kill switch does not stop you: you can send new orders right after it.
Fills that already happened are not undone.

An operator can use the same switch on your gateway, on a symbol, or on the
whole market; your orders are then cancelled with the same `KILL_SWITCH`
reason. An operator can also disconnect your session, which cancels your
orders as described next.

## When your session ends

When you log off — `EXIT`, closing the window, a crash or a dropped network
connection — the exchange applies your participant's **disconnect
behaviour**, set by the operator:

| Setting | Your resting orders | Your quotes |
|---|---|---|
| `CANCEL_QUOTES_ONLY` (the default) | Stay on the book | Cancelled |
| `CANCEL_ALL` | Cancelled | Cancelled |
| `LEAVE_ALL` | Stay on the book | Stay on the book |

Ask your instructor which applies to you. Under `CANCEL_QUOTES_ONLY` or
`LEAVE_ALL` an order you forgot can still fill while you are away; when you
log on again, `ORDERS` shows what is still resting. Your orders also stay on
the book across a restart of the exchange itself — GTC orders indefinitely,
DAY orders until the end of their trading day.

## Self-match prevention

If your order would trade against **your own** resting order, the exchange
can stop it. What happens depends on the `SMP=` value of the incoming order,
or, when you leave it out, your participant's configured default:

| Value | Effect |
|---|---|
| `NONE` | The trade happens: you trade with yourself |
| `CANCEL_AGGRESSOR` | Your incoming order is cancelled; the resting one stays |
| `CANCEL_RESTING` | Your resting order is cancelled; the incoming order trades on against others |
| `CANCEL_BOTH` | Both are cancelled |

A cancelled order shows `reason=SELF_MATCH_PREVENTED`. It is a cancellation,
not a rejection: the order may already have traded with other participants
before it met your own. See the
[FAQ](../90-backmatter/010-faq-orders-and-positions.md#what-is-smp-and-why-did-my-order-get-cancelled).

## Rate limits

The gateways that programs use limit how fast one session may send:

- **REST API** (`pm-api-gwy`): a number of write requests (orders, amends,
  cancels) per second, with a short burst allowance; above it requests are refused with HTTP `429 RATE_LIMIT`.
  Slow down and resend.
- **ALF TCP gateway** (`pm-alf-gwy`): commands above the per-session rate are
  refused with `RATE_LIMITED`. A session that keeps sending commands the
  gateway refuses (by default 50 errors within a minute) is disconnected.

A person typing in the trader console never comes near these limits; a bot
in a tight loop does.

## Looking up a symbol's limits

- `SYMBOLS` in the trader console shows each symbol's tick size and, for
  market makers, the quoting obligation.
- The REST call `GET /api/v1/reference/symbols` returns each symbol's tick
  size, collar bands, order limits and circuit-breaker levels — see the
  [REST reference](../../protocols-and-clients/part-2-specifications/060-rest-and-websocket.md).
- Your instructor can show the full risk configuration, which an ADMIN sees
  on the Trading GUI's Risk Controls screen.

## Reject codes at a glance

| Code | Meaning | What to do |
|---|---|---|
| `UNKNOWN_SYMBOL` | The symbol is not listed | Run `SYMBOLS` |
| `MISSING_FIELD` / `UNSUPPORTED_FIELD` / `INVALID_VALUE` | A field the order type needs is missing, not allowed, or malformed | See [Fields each type takes](020-order-types.md#fields-each-type-takes) |
| `TICK_VIOLATION` | Price not on the tick grid | Round to the tick |
| `MAX_ORDER_QTY` / `MAX_ORDER_VALUE` | Order too large | Split it |
| `COLLAR_BREACH` | Price outside the collar | Price closer to the market |
| `CIRCUIT_BREAKER_ACTIVE` | Symbol halted by a circuit breaker | Wait for the reopening, or rest a `LIMIT` |
| `INSTRUMENT_HALTED` | Symbol halted by the operator | Wait for the operator, or rest a `LIMIT` |
| `MARKET_CLOSED` | Session closed | Wait for the next session |
| `SESSION_NOT_PERMITTED` | Not allowed in this phase | Use a `LIMIT`, or the right TIF |
| `INSUFFICIENT_LIQUIDITY` | A `FOK` (or a held-back combo) could not fill in full | Reduce the size or widen the price |
| `ORDER_NOT_FOUND` | Amend or cancel of an order that is not resting | Check `ORDERS`; it may have filled |
| `AMEND_NOT_PERMITTED` | That order type cannot be amended | Cancel and re-enter |
| `QTY_OUT_OF_RANGE` / `PRICE_OUT_OF_RANGE` | Amend to an impossible quantity or price | Check the new values |
| `DUPLICATE_ORDER` | The same order id sent twice (a program resending an order) | Give each order a new id |
| `RATE_LIMITED` | Sending too fast | Slow down |

The [message reference](../../protocols-and-clients/part-5-message-reference/010-message-reference.md)
lists every code.

## See also

- [Risk Controls](../../operator-guide/part-4-run-a-market/040-risk-controls.md) — how the operator configures all of the above
- [Order Types](020-order-types.md) — how each type behaves when it meets these controls
- [Market-Maker Quotes](../part-3-market-making/010-market-maker-quotes.md) — what halts and disconnects do to quotes

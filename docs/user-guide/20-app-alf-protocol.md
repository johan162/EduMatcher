# Appendix: ALF Protocol Reference

!!! note "Learning objectives"
    After reading this appendix you will understand:

    - what **ALF** means and how it differs from real FIX
    - the exact token-level syntax accepted by `pm-gateway`
    - which fields are required for each supported command
    - how all single-leg order types are expressed in ALF
    - how amendments, cancels, quotes, OCO orders, and combo orders are encoded
    - which parser behaviors are important when writing another client for EduMatcher

---

## 1. What ALF is

**ALF** stands for **ALmost Fix**.

It is EduMatcher's compact text command protocol for entering orders through
`pm-gateway`. ALF borrows the **field=value** idea from FIX, but it is **not**
FIX:

- there are no numeric tags
- there is no FIX session layer
- there are no sequence numbers
- there is no checksum or body length
- there are no repeating-group rules
- there are no standard FIX message types

ALF is intentionally smaller and easier to type by hand:

```text
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.25
```

This appendix is the **normative reference** for ALF syntax and semantics. If
another tool, bot, or GUI wants to generate ALF commands, this document is the
correct source to follow.

---

## 2. Scope and boundaries

ALF is the **text command language accepted by `pm-gateway`**. It is not the
internal engine wire format. The gateway converts ALF commands into the engine's
ZeroMQ + JSON message payloads.

That distinction matters:

- **ALF** is what a human or external client writes
- **engine messages** are what the gateway publishes internally

This appendix describes the **ALF side**, not the internal message bus.

---

## 3. Core syntax rules

### 3.1 Line structure

Every ALF command is a single line:

```text
<COMMAND>|<FIELD>=<VALUE>|<FIELD>=<VALUE>|...
```

The first token is always the command verb. Everything after that is a
pipe-delimited list of fields.

### Formal grammar

This notation is **ABNF-style** (Augmented Backus-Naur Form), not classic BNF.
The repetition form:

```text
n*m element
```

means "repeat `element` at least `n` times and at most `m` times".

Examples:

- `1*X` means **one or more** `X`
- `*X` means **zero or more** `X`
- `2*4X` means **between 2 and 4** `X`

So in the ALF grammar:

- `command = 1*( ALPHA / "_" )` means a command is made of **one or more**
  letters or underscores
- `key = 1*( ALPHA / DIGIT / "_" / "." )` means a key is **one or more**
  letters, digits, underscores, or dots

```text
alf-line      = command *( "|" segment )
command       = 1*( ALPHA / "_" )
segment       = key "=" value
key           = 1*( ALPHA / DIGIT / "_" / "." )
value         = *VCHAR
```

`VCHAR` is also ABNF terminology. It means a **visible printable character**.
So:

- `value = *VCHAR` means the value may contain **zero or more visible
  characters**
- the leading `*` is why the value is allowed to be empty

In strict ABNF, `VCHAR` usually means printable non-space ASCII characters.
For ALF, read this line as **simplified shorthand** for:

> everything after the first `=` up to the next `|`

That is closer to the real gateway parser behavior. The parser does not enforce
a full RFC-style character class check; it splits on `|`, then splits each
segment on the first `=`, and treats the remainder as the raw value text.

In practice:

- `|` separates segments
- the **first** `=` in a segment separates key from value
- no quoting or escaping layer exists

### 3.2 Whitespace

The gateway trims whitespace only at the very start and end of the full line.
It does **not** trim spaces around individual fields. Write:

```text
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.25
```

not:

```text
NEW | SYM=AAPL | SIDE=BUY
```

### 3.3 Case handling

ALF is effectively **case-insensitive** for command verbs, field names, enum
values, and symbols, because the gateway normalizes parsed values to uppercase.

These are treated the same:

```text
new|sym=aapl|side=buy|type=limit|qty=100|price=150.25
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.25
```

Important consequence: user-supplied labels are also normalized to uppercase.

Examples:

- `COMBO_ID=pair-01` becomes `PAIR-01`
- `OCO_ID=exit-aapl` becomes `EXIT-AAPL`
- `QUOTE_ID=mm-1` becomes `MM-1`

If you generate ALF programmatically, assume that **labels and symbols are
case-folded to uppercase** by the gateway.

### 3.4 Field order

After the command word, field order is generally **not significant**. The
gateway parses fields into a key/value map and then validates what is present.

These are equivalent:

```text
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.25
NEW|TYPE=LIMIT|PRICE=150.25|QTY=100|SIDE=BUY|SYM=AAPL
```

Exceptions:

- the command verb must be the first token
- combo leg numbering must be consistent with `LEG_COUNT`

### 3.5 Duplicate and unknown fields

If the same field appears more than once, the **last occurrence wins**.

Example:

```text
NEW|SYM=AAPL|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.25
```

This is parsed as `SYM=MSFT`.

Unknown fields are ignored by the gateway unless they are required for the
specific command being validated.

### 3.6 Numeric formatting

ALF uses human-readable decimal prices:

- `PRICE=150.25`
- `STOP=149.90`
- `TRAIL=1.50`

Quantities are integers:

- `QTY=100`
- `VISIBLE=25`

The gateway converts decimal prices to the symbol's internal tick representation
before sending them to the engine.

### 3.7 No escaping

ALF has **no escaping mechanism** for `|`. Do not place `|` inside values.

The first `=` in a segment splits key from value. Everything after that first
`=` is considered part of the value, but values containing additional `=` are
not part of the documented protocol and should be avoided.

---

## 4. Common field vocabulary

| Field | Meaning |
|---|---|
| `SYM` | Symbol, for example `AAPL` |
| `SIDE` | `BUY` or `SELL` |
| `TYPE` | Order type or high-level order family such as `COMBO` or `OCO` |
| `QTY` | Integer quantity |
| `PRICE` | Limit price in display units |
| `STOP` | Stop trigger price in display units |
| `TRAIL` | Trailing-stop offset in display units |
| `TIF` | Time in force: `DAY`, `GTC`, `ATO`, `ATC` |
| `VISIBLE` | Displayed peak size for iceberg orders |
| `SMP` | Self-match-prevention action |
| `ID` | Engine-generated single-order identifier |
| `COMBO_ID` | User-supplied combo label |
| `OCO_ID` | User-supplied OCO label |
| `QUOTE_ID` | User-supplied quote label |

### 4.1 Supported `TIF` values

| Value | Meaning |
|---|---|
| `DAY` | Valid for the trading day only |
| `GTC` | Good till cancelled |
| `ATO` | At the open; only meaningful during the opening auction |
| `ATC` | At the close; only meaningful during the closing auction |

### 4.2 Supported `SMP` values

| Value | Meaning |
|---|---|
| `NONE` | Allow self-trades |
| `CANCEL_AGGRESSOR` | Cancel the incoming order if it would self-match |
| `CANCEL_RESTING` | Cancel the resting order and continue matching |
| `CANCEL_BOTH` | Cancel both the incoming and resting order |

---

## 5. Command families

ALF commands fall into three groups:

| Group | Commands |
|---|---|
| Trading commands forwarded to the engine | `NEW`, `AMEND`, `CANCEL`, `QUOTE`, `QUOTE_CANCEL`, `KILL`, `SYMBOLS` |
| Gateway-local informational commands | `ORDERS`, `POS`, `HELP` |
| Session-control commands for the CLI process | `EXIT`, `QUIT` |

If you are writing another interface that wants to submit orders, the most
important commands are the **trading commands**.

---

## 6. Single-leg `NEW` orders

### 6.1 Generic form

```text
NEW|SYM=<symbol>|SIDE=<BUY|SELL>|TYPE=<order-type>|QTY=<quantity>[|...]
```

### Formal grammar

```text
new-single =
    "NEW"
    "|SYM=" symbol
    "|SIDE=" side
    "|TYPE=" order-type
    "|QTY=" quantity
    *( "|" option )
```

Where `option` depends on the selected order type.

### 6.2 Supported single-leg order types

| Type | Required fields | Optional fields | Notes |
|---|---|---|---|
| `MARKET` | `SYM`, `SIDE`, `TYPE=MARKET`, `QTY` | `TIF`, `SMP` | `TIF` is accepted syntactically but market-order behavior still applies |
| `LIMIT` | `SYM`, `SIDE`, `TYPE=LIMIT`, `QTY`, `PRICE` | `TIF`, `SMP` | Standard resting limit order |
| `IOC` | `SYM`, `SIDE`, `TYPE=IOC`, `QTY`, `PRICE` | `TIF`, `SMP` | Immediate-or-cancel behavior still applies even if `TIF` is supplied |
| `FOK` | `SYM`, `SIDE`, `TYPE=FOK`, `QTY`, `PRICE` | `TIF`, `SMP` | Fill-or-kill behavior still applies even if `TIF` is supplied |
| `STOP` | `SYM`, `SIDE`, `TYPE=STOP`, `QTY`, `STOP` | `TIF`, `SMP` | Becomes a market order when triggered |
| `STOP_LIMIT` | `SYM`, `SIDE`, `TYPE=STOP_LIMIT`, `QTY`, `STOP`, `PRICE` | `TIF`, `SMP` | Becomes a limit order when triggered |
| `ICEBERG` | `SYM`, `SIDE`, `TYPE=ICEBERG`, `QTY`, `PRICE`, `VISIBLE` | `TIF`, `SMP` | `VISIBLE` must be strictly less than `QTY` |
| `TRAILING_STOP` | `SYM`, `SIDE`, `TYPE=TRAILING_STOP`, `QTY`, `TRAIL` | `STOP`, `TIF`, `SMP` | `STOP` is optional; if omitted the engine derives the initial stop from the last trade price |

### 6.3 Formal syntax by order type

### MARKET

```text
NEW|SYM=<symbol>|SIDE=<BUY|SELL>|TYPE=MARKET|QTY=<quantity>[|TIF=<DAY|GTC|ATO|ATC>][|SMP=<...>]
```

Example:

```text
NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=100
```

### LIMIT

```text
NEW|SYM=<symbol>|SIDE=<BUY|SELL>|TYPE=LIMIT|QTY=<quantity>|PRICE=<price>[|TIF=<DAY|GTC|ATO|ATC>][|SMP=<...>]
```

Examples:

```text
NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=152.00
NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=200|PRICE=310.00|TIF=GTC
```

### IOC

```text
NEW|SYM=<symbol>|SIDE=<BUY|SELL>|TYPE=IOC|QTY=<quantity>|PRICE=<price>[|TIF=<DAY|GTC|ATO|ATC>][|SMP=<...>]
```

Example:

```text
NEW|SYM=AAPL|SIDE=BUY|TYPE=IOC|QTY=250|PRICE=150.20
```

### FOK

```text
NEW|SYM=<symbol>|SIDE=<BUY|SELL>|TYPE=FOK|QTY=<quantity>|PRICE=<price>[|TIF=<DAY|GTC|ATO|ATC>][|SMP=<...>]
```

Example:

```text
NEW|SYM=AAPL|SIDE=BUY|TYPE=FOK|QTY=100|PRICE=150.00
```

### STOP

```text
NEW|SYM=<symbol>|SIDE=<BUY|SELL>|TYPE=STOP|QTY=<quantity>|STOP=<stop-price>[|TIF=<DAY|GTC|ATO|ATC>][|SMP=<...>]
```

Example:

```text
NEW|SYM=AAPL|SIDE=SELL|TYPE=STOP|QTY=100|STOP=148.00
```

### STOP_LIMIT

```text
NEW|SYM=<symbol>|SIDE=<BUY|SELL>|TYPE=STOP_LIMIT|QTY=<quantity>|STOP=<stop-price>|PRICE=<limit-price>[|TIF=<DAY|GTC|ATO|ATC>][|SMP=<...>]
```

Example:

```text
NEW|SYM=AAPL|SIDE=SELL|TYPE=STOP_LIMIT|QTY=100|STOP=148.00|PRICE=147.50
```

### ICEBERG

```text
NEW|SYM=<symbol>|SIDE=<BUY|SELL>|TYPE=ICEBERG|QTY=<quantity>|PRICE=<price>|VISIBLE=<visible-quantity>[|TIF=<DAY|GTC|ATO|ATC>][|SMP=<...>]
```

Example:

```text
NEW|SYM=AAPL|SIDE=BUY|TYPE=ICEBERG|QTY=1000|PRICE=150.00|VISIBLE=100
```

### TRAILING_STOP

```text
NEW|SYM=<symbol>|SIDE=<BUY|SELL>|TYPE=TRAILING_STOP|QTY=<quantity>|TRAIL=<offset>[|STOP=<initial-stop>][|TIF=<DAY|GTC|ATO|ATC>][|SMP=<...>]
```

Examples:

```text
NEW|SYM=AAPL|SIDE=SELL|TYPE=TRAILING_STOP|QTY=100|TRAIL=1.50|STOP=148.00
NEW|SYM=AAPL|SIDE=SELL|TYPE=TRAILING_STOP|QTY=100|TRAIL=1.50
```

Semantics:

- `TRAIL` is mandatory
- `STOP` is optional
- if `STOP` is omitted, the engine derives the initial stop from the last trade
  price
- if `STOP` is omitted and no prior trade exists, the engine rejects the order

### 6.4 Auction-only `TIF` values

`ATO` and `ATC` are accepted by the single-leg parser even though they are not
prominent in tab completion.

Examples:

```text
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00|TIF=ATO
NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=100|PRICE=151.00|TIF=ATC
```

These are only meaningful during the opening and closing auction phases.

### 6.5 Practical parsing notes

- `PRICE`, `STOP`, and `TRAIL` are decimal display prices, not ticks
- `QTY` and `VISIBLE` must parse as integers
- `VISIBLE` must be strictly less than total `QTY`
- the gateway generates the final engine order ID; you do not supply it in
  `NEW`

---

## 7. `AMEND` - order amendments

`AMEND` applies only to **existing single-leg orders** identified by full
engine-generated order ID.

### Formal syntax

```text
AMEND|ID=<order-id>[|PRICE=<new-price>][|QTY=<new-total-quantity>]
```

At least one of `PRICE` or `QTY` must be present.

### Supported amendment forms

| Form | Meaning |
|---|---|
| `AMEND|ID=...|PRICE=...` | Price-only amendment |
| `AMEND|ID=...|QTY=...` | Quantity-only amendment |
| `AMEND|ID=...|PRICE=...|QTY=...` | Change both price and quantity |

### Examples

Price only:

```text
AMEND|ID=ORD-12345678|PRICE=151.00
```

Quantity only, lower quantity:

```text
AMEND|ID=ORD-12345678|QTY=80
```

Quantity only, higher quantity:

```text
AMEND|ID=ORD-12345678|QTY=200
```

Change both:

```text
AMEND|ID=ORD-12345678|PRICE=151.00|QTY=200
```

### Amendment semantics

As implemented today:

- only **resting `LIMIT` and `ICEBERG` orders** can be amended
- `MARKET`, `IOC`, `FOK`, `STOP`, `STOP_LIMIT`, and `TRAILING_STOP` orders are
  not amendable
- `QTY` is the **new total order quantity**, not a delta
- `QTY` must stay positive
- the new total quantity must be **greater than the already-filled quantity**

### Priority rules

The engine follows exchange-style amendment priority rules:

- **quantity decrease only, same price** -> priority is preserved
- **price change** -> priority is reset
- **quantity increase** -> priority is reset

Example:

1. `NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00`
2. `AMEND|ID=...|QTY=80` keeps queue priority if the price stays `150.00`
3. `AMEND|ID=...|PRICE=150.10` loses queue priority
4. `AMEND|ID=...|QTY=120` also loses queue priority

### Important identifier rule

Use the **full order ID** from the gateway's order table or acknowledgement
stream. Inline gateway messages often abbreviate IDs visually, but `AMEND`
requires the full internal ID.

---

## 8. `CANCEL` - order and group cancellation

### 8.1 Single order cancel

```text
CANCEL|ID=<order-id>
```

Example:

```text
CANCEL|ID=ORD-12345678
```

### 8.2 Combo cancel

```text
CANCEL|COMBO_ID=<combo-label>
```

Example:

```text
CANCEL|COMBO_ID=PAIR-001
```

### 8.3 OCO cancel

```text
CANCEL|OCO_ID=<oco-label>
```

Example:

```text
CANCEL|OCO_ID=EXIT-AAPL
```

### Cancellation semantics

- `ID` cancels one single-leg order
- `COMBO_ID` cancels a combo and its still-resting child legs
- `OCO_ID` cancels the whole OCO pair
- fills that already happened are never reversed by cancel

---

## 9. `NEW|TYPE=OCO` - one-cancels-other pairs

OCO syntax creates **two linked orders on the same symbol and with the same
quantity**. When one leg fills or is otherwise actioned, the sibling is
cancelled.

### Formal syntax

```text
NEW
|TYPE=OCO
|OCO_ID=<label>
|SYM=<symbol>
|QTY=<quantity>
[|TIF=<DAY|GTC|ATO|ATC>]
|LEG1_SIDE=<BUY|SELL>
|LEG1_TYPE=<order-type>
[|LEG1_PRICE=<price>]
[|LEG1_STOP=<stop-price>]
[|LEG1_TRAIL=<trail-offset>]
|LEG2_SIDE=<BUY|SELL>
|LEG2_TYPE=<order-type>
[|LEG2_PRICE=<price>]
[|LEG2_STOP=<stop-price>]
[|LEG2_TRAIL=<trail-offset>]
```

### OCO field semantics

| Field | Meaning |
|---|---|
| `OCO_ID` | User label for the pair |
| `SYM` | Shared symbol for both legs |
| `QTY` | Shared quantity for both legs |
| `TIF` | Shared TIF for both legs |
| `LEG1_*`, `LEG2_*` | Per-leg side, type, and trigger/limit fields |

If `TIF` is omitted, the gateway defaults it to `DAY`.

### OCO leg expressibility

ALF OCO syntax can express these leg types cleanly:

| Leg type | Supported in ALF OCO syntax | Required extra fields |
|---|---|---|
| `MARKET` | Yes | none |
| `LIMIT` | Yes | `LEGn_PRICE` |
| `IOC` | Yes | `LEGn_PRICE` |
| `FOK` | Yes | `LEGn_PRICE` |
| `STOP` | Yes | `LEGn_STOP` |
| `STOP_LIMIT` | Yes | `LEGn_STOP` and `LEGn_PRICE` |
| `TRAILING_STOP` | Yes | `LEGn_TRAIL`, optional `LEGn_STOP` |
| `ICEBERG` | No practical ALF support | ALF OCO syntax has no `LEGn_VISIBLE` field |

### Examples

Classic take-profit / stop-loss exit:

```text
NEW|TYPE=OCO|OCO_ID=EXIT-AAPL|SYM=AAPL|QTY=100|TIF=GTC|LEG1_SIDE=SELL|LEG1_TYPE=LIMIT|LEG1_PRICE=155.00|LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=148.00
```

Limit exit plus trailing-stop protection:

```text
NEW|TYPE=OCO|OCO_ID=EXIT-TRAIL|SYM=AAPL|QTY=100|TIF=GTC|LEG1_SIDE=SELL|LEG1_TYPE=LIMIT|LEG1_PRICE=155.00|LEG2_SIDE=SELL|LEG2_TYPE=TRAILING_STOP|LEG2_TRAIL=1.50
```

### OCO semantics

- both legs share the same `SYM`, `QTY`, `TIF`, and gateway identity
- each leg receives its own engine-generated order ID
- the gateway first receives an `OCO ACK`
- each leg is then posted and acknowledged as a normal order
- when one leg fills or is cancelled in a way that completes the OCO action, the
  sibling is auto-cancelled

---

## 10. `NEW|TYPE=COMBO` - multi-leg combo orders

Combo syntax creates a parent combo plus child orders across multiple symbols.

### Formal syntax

```text
NEW
|TYPE=COMBO
|COMBO_ID=<label>
[|COMBO_TYPE=AON]
[|TIF=<DAY|GTC|ATO|ATC>]
[|SMP=<NONE|CANCEL_AGGRESSOR|CANCEL_RESTING|CANCEL_BOTH>]
|LEG_COUNT=<n>
|LEG0.SYM=<symbol>
|LEG0.SIDE=<BUY|SELL>
|LEG0.QTY=<quantity>
[|LEG0.TYPE=<order-type>]
[|LEG0.PRICE=<price>]
...
|LEG<n-1>.SYM=<symbol>
|LEG<n-1>.SIDE=<BUY|SELL>
|LEG<n-1>.QTY=<quantity>
[|LEG<n-1>.TYPE=<order-type>]
[|LEG<n-1>.PRICE=<price>]
```

### Combo field semantics

| Field | Meaning |
|---|---|
| `TYPE=COMBO` | Selects combo mode |
| `COMBO_ID` | User label used later by `CANCEL|COMBO_ID=...` |
| `COMBO_TYPE=AON` | Optional today; defaults to `AON` |
| `TIF` | Shared TIF for all child legs |
| `SMP` | Shared SMP setting applied to all child legs |
| `LEG_COUNT` | Number of legs, from 2 to 10 |
| `LEGi.*` | Per-leg fields, using zero-based numbering |

If `COMBO_TYPE` is omitted, the gateway defaults it to `AON`. If `TIF` is
omitted, it defaults to `DAY`.

### Combo leg expressibility

This is an important ALF limitation.

The current text parser exposes only:

- `LEGi.SYM`
- `LEGi.SIDE`
- `LEGi.QTY`
- `LEGi.TYPE`
- `LEGi.PRICE`

It does **not** expose:

- `LEGi.STOP`
- `LEGi.TRAIL`
- `LEGi.VISIBLE`

So, in practical ALF terms:

| Leg type | Practical ALF combo support | Reason |
|---|---|---|
| `LIMIT` | Yes | Default leg type; `PRICE` available |
| `MARKET` | Yes | No extra fields required |
| `IOC` | Yes | `PRICE` available |
| `FOK` | Yes | `PRICE` available |
| `STOP` | No practical ALF support | No `LEGi.STOP` field |
| `STOP_LIMIT` | No practical ALF support | No `LEGi.STOP` field |
| `TRAILING_STOP` | No practical ALF support | No `LEGi.TRAIL` field |
| `ICEBERG` | No practical ALF support | No `LEGi.VISIBLE` field |

### Examples

Two-leg pairs trade:

```text
NEW|TYPE=COMBO|COMBO_ID=PAIR-001|COMBO_TYPE=AON|TIF=GTC|LEG_COUNT=2|LEG0.SYM=MSFT|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=415.00|LEG1.SYM=AAPL|LEG1.SIDE=SELL|LEG1.QTY=100|LEG1.PRICE=210.00
```

Three-leg arbitrage-style order:

```text
NEW|TYPE=COMBO|COMBO_ID=ARB-01|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=3|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=200|LEG0.PRICE=210.00|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=100|LEG1.PRICE=415.00|LEG2.SYM=GOOG|LEG2.SIDE=SELL|LEG2.QTY=50|LEG2.PRICE=170.00
```

### Combo semantics

- `LEG_COUNT` must be between 2 and 10
- leg numbering is zero-based: `LEG0`, `LEG1`, `LEG2`, ...
- duplicate symbols are rejected by the engine
- the engine posts child orders to the relevant per-symbol books
- if a child leg is cancelled or expires, the remaining legs are cascade-cancelled
- combo state is tracked separately from the ordinary `ORDERS` table

---

## 11. `QUOTE` and `QUOTE_CANCEL`

Quotes are a two-sided market-maker convenience command. One `QUOTE` submits or
replaces both a bid and an ask for the same symbol.

### Formal syntax

```text
QUOTE|SYM=<symbol>|BID=<bid-price>|ASK=<ask-price>|BID_QTY=<quantity>|ASK_QTY=<quantity>[|TIF=<DAY|GTC|ATO|ATC>][|QUOTE_ID=<label>]
```

Cancel syntax:

```text
QUOTE_CANCEL|SYM=<symbol>
```

### Example

```text
QUOTE|SYM=AAPL|BID=149.90|ASK=150.10|BID_QTY=500|ASK_QTY=500|TIF=DAY|QUOTE_ID=MM-AAPL-1
QUOTE_CANCEL|SYM=AAPL
```

### Quote semantics

- only gateways configured with the `MARKET_MAKER` role may submit quotes
- `BID` must be strictly less than `ASK`
- both quantities must be positive
- a new quote for the same gateway and symbol replaces the previous active quote
- a quote creates two internal `LIMIT` orders, one bid and one ask

---

## 12. `KILL`

`KILL` triggers the kill switch for the current gateway.

### Syntax

```text
KILL
KILL|SYM=<symbol>
```

### Examples

Cancel all eligible exposure for the gateway:

```text
KILL
```

Cancel only for one symbol:

```text
KILL|SYM=AAPL
```

### Semantics

`KILL` applies to the **current authenticated gateway only**. It does not cancel
other gateways' orders.

The engine performs these steps:

1. Validate that the gateway is currently allowed to submit risk actions
2. Cancel the gateway's active quote entry or entries
3. Cancel the gateway's remaining **resting non-quote orders**
4. Return a kill-switch acknowledgement with summary counts

More precisely:

- if no `SYM` is supplied, the engine removes **all active quotes** for that
  gateway from the internal quote index
- if `SYM` is supplied, it removes only the active quote for that
  `gateway + symbol` pair
- each removed quote entry then cancels its **bid leg** and **ask leg**
- after quote cancellation, the engine walks every order book and cancels every
  **resting** order where:
  - `order.gateway_id` matches the current gateway
  - the order is **not** a quote-origin order
  - the symbol matches `SYM` if a symbol filter was supplied

This means `KILL` cancels:

- active market-maker quote legs for the current gateway
- ordinary resting limit-style exposure for the current gateway
- any other gateway-owned resting child orders that are sitting in a book and
  are not quote-origin orders

This means `KILL` does **not**:

- cancel other gateways' orders
- reverse fills that already happened
- reach into already-completed orders that are no longer resting in a book
- count quotes as one unit; the acknowledgement counts **cancelled quote legs**
  separately from **cancelled non-quote orders**

If the gateway is not allowed to perform the action, the engine sends a reject
acknowledgement instead of cancelling anything.

### Acknowledgement behavior

The gateway receives a `KILL ACK` or `KILL REJ`.

On success, the acknowledgement includes:

- `cancelled_orders` - number of cancelled non-quote resting orders
- `cancelled_quotes` - number of cancelled quote legs

Important detail: `cancelled_quotes` counts **legs**, not quote records. One
two-sided quote typically contributes up to **2** to this count.

### Examples

If gateway `MM01` currently has:

- one active two-sided quote in `AAPL`
- one active two-sided quote in `MSFT`
- three resting non-quote orders in `AAPL`
- one resting non-quote order in `GOOG`

then:

```text
KILL|SYM=AAPL
```

will cancel:

- the `AAPL` quote's bid and ask legs
- the three resting non-quote `AAPL` orders

but it will leave:

- the `MSFT` quote untouched
- the `GOOG` resting order untouched

while:

```text
KILL
```

will cancel all of the above gateway-owned resting exposure across all symbols.

---

## 13. Informational gateway commands

These commands are part of the ALF command language accepted by `pm-gateway`,
but they are not order-entry messages in the strict sense.

### `ORDERS`

```text
ORDERS
```

Prints the gateway's local order table.

### `POS`

```text
POS
```

Prints positions and P&L computed from fills seen by this gateway instance.

### `SYMBOLS`

```text
SYMBOLS
```

Requests the currently active symbols from the engine.

### `HELP`

```text
HELP
```

Prints the gateway help text.

### `EXIT` / `QUIT`

```text
EXIT
QUIT
```

Stops the gateway process.

---

## 14. Worked examples

### 14.1 Basic buy-side session

```text
NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00
AMEND|ID=<returned-order-id>|QTY=80
CANCEL|ID=<returned-order-id>
```

### 14.2 Stop-protected exit

```text
NEW|TYPE=OCO|OCO_ID=EXIT-AAPL|SYM=AAPL|QTY=100|TIF=GTC|LEG1_SIDE=SELL|LEG1_TYPE=LIMIT|LEG1_PRICE=155.00|LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=148.00
```

### 14.3 Market-maker quoting

```text
QUOTE|SYM=MSFT|BID=414.90|ASK=415.10|BID_QTY=250|ASK_QTY=250|QUOTE_ID=MSFT-MM-01
QUOTE_CANCEL|SYM=MSFT
```

### 14.4 Multi-symbol combo

```text
NEW|TYPE=COMBO|COMBO_ID=PAIR-001|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=2|LEG0.SYM=MSFT|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=415.00|LEG1.SYM=AAPL|LEG1.SIDE=SELL|LEG1.QTY=100|LEG1.PRICE=210.00
```

---

## 15. Summary of important implementation truths

If you are writing another ALF producer, the most important exact behaviors are:

1. ALF is **not** FIX. It is a simpler pipe-delimited command language.
2. The command verb must be first; after that, field order is mostly free.
3. Parsed values are normalized to **uppercase**, including user labels.
4. Repeated fields use the **last value** seen.
5. Single-leg orders support all documented order types, including
   `TRAILING_STOP`.
6. `AMEND` applies only to resting `LIMIT` and `ICEBERG` orders.
7. OCO syntax can express stop and trailing-stop legs, but not iceberg legs.
8. Combo ALF syntax does **not** expose per-leg `STOP`, `TRAIL`, or `VISIBLE`
   fields, so some engine-level leg types are not practically expressible in
   ALF combo form.

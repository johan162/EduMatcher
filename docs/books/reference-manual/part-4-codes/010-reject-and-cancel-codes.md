# Reject and Cancel Codes

When the exchange refuses a request or ends an order itself, it gives a
stable, machine-readable code. Use this chapter to look up any code and find
out what triggers it. Codes come in two kinds, and a client must keep them
apart:

| | `reject_code` | `cancel_reason` |
|---|---|---|
| **Carried on** | `order.ack` with `accepted=false` (and the cancel acks of quotes, combos and OCOs) | `order.cancelled` |
| **What it means** | The request was refused. A refused new order never existed on the book | The order *was* accepted and the exchange ended it later, without the client asking |
| **ALF** | `ACK|…|ACCEPTED=FALSE|REJECT_CODE=…|REASON=…` | `CANCELLED|…|CANCEL_REASON=…` |
| **REST** | `reject_code` in the ack, or in the `error` object of a 4xx/5xx reply | `cancel_reason` on the `order.cancelled` event |
| **BALF** | one-byte `reject_code` in `ORDER_ACK` (see [below](#balf-numeric-codes)) | one-byte `cancel_reason` in `CANCEL_ACK` |

Both vocabularies are defined in `spec/messages/order.yaml`; the generated field
tables are in the [message reference](../../protocols-and-clients/part-5-message-reference/010-message-reference.md#orderackgateway_id).
New members may be added; existing ones are never removed or renamed. A client
must treat an unknown `reject_code` as `UNKNOWN` and an unknown `cancel_reason`
as "the exchange cancelled it".

The human-readable detail is always in `reason` (`REASON=`, `DETAIL=`, or
`message` on REST). The code never carries data values; the reason does.

!!! note "One code, one first failure"
    The engine checks a new order in a fixed order and reports the first thing
    wrong: gateway → symbol → fields → session → ATO/ATC window → halt →
    collar → can it rest → trailing-stop reference → the book. An order with
    two problems gets the code for the earlier check.

## Reject codes

**Where** says who sends the code: *engine* (every transport sees it the
same way), or a gateway (*ALF*, *BALF*, *REST*) that refuses before the
request reaches the engine.

### Message and field problems

| Code | Where | When |
|---|---|---|
| `MALFORMED_MESSAGE` | ALF, engine | ALF: a line that does not parse as a frame (`BAD_MESSAGE`). Engine: an `order.new` payload that does not decode, such as an unknown enum value |
| `MISSING_FIELD` | ALF, REST, engine | A field the command or order type needs is absent: `LIMIT` without a price, `AMEND` with neither price nor quantity, `CANCEL` with no ID. The engine also sends it for an `ICEBERG` with a non-positive visible quantity, and for a `TRAILING_STOP` with no `STOP=` and no trade yet to trail |
| `UNSUPPORTED_FIELD` | ALF, REST, engine | A field the order type does not take (`LIMIT` with a trail offset), `TAG` and `RTAG` mixed up, an unknown ALF command, or an unknown REST body field |
| `INVALID_VALUE` | ALF, REST, engine | A value of the wrong form: not a number, NaN/Inf, out of integer range, below a minimum, a `CLIENT` over 32 characters, a non-positive trail offset, or prices sent at a tick scale that differs from the symbol's |
| `TICK_VIOLATION` | ALF, REST, engine | A price that is not a multiple of the symbol's tick size. It is never rounded. The engine checks amends; the gateways check new orders |
| `PRICE_OUT_OF_RANGE` | engine | A price that is zero or negative, on a new order or an amend |
| `QTY_OUT_OF_RANGE` | engine | A quantity that is zero or negative, or an `ICEBERG` whose visible quantity exceeds its total; also an amend to an impossible quantity |
| `DUPLICATE_ORDER` | engine | A new order whose ID is already live, usually a client resending after a timeout |

### Identity and access

| Code | Where | When |
|---|---|---|
| `AUTH_REQUIRED` | ALF, REST, engine | Order entry before logging in: no `HELLO`, a login timeout, a second `HELLO` while one is pending, or a REST call without a bearer token. The engine sends it for a configured gateway with no live session (`Gateway not connected: <ID>`) |
| `AUTH_FAILED` | ALF, BALF, REST | The login itself was refused: wrong credentials, an unknown API key, a protocol-version mismatch, or a gateway ID that already has a session |
| `ROLE_DENIED` | ALF, REST | The participant's role does not allow the command: an admin command from a `TRADER`, a read-only API key on a gateway-scoped endpoint, or a request for another gateway's clearing data |
| `NOT_OWNER` | engine | A cancel or amend of an order that belongs to another gateway |
| `GATEWAY_NOT_CONFIGURED` | engine | The gateway ID is not in the configured participants |
| `RATE_LIMITED` | ALF, BALF, REST | The session sent more than its per-second message budget |

### Reference data

| Code | Where | When |
|---|---|---|
| `UNKNOWN_SYMBOL` | ALF, engine | The symbol is not configured. (REST answers an unknown symbol on a market-data path with HTTP 404 and `UNKNOWN`) |
| `SYMBOL_NOT_READY` | ALF, REST | The gateway has not yet received the symbol's tick precision, just after start-up. Transient; retry |

### Risk controls

| Code | Where | When |
|---|---|---|
| `COLLAR_BREACH` | engine | The price (new or amended) is outside the static or dynamic price collar. `reason` starts `STATIC_COLLAR_BREACH:` or `DYNAMIC_COLLAR_BREACH:` and gives the band. See [Risk Controls](../../operator-guide/part-4-run-a-market/040-risk-controls.md) |
| `MAX_ORDER_QTY` | engine | The quantity is above the symbol's `order_limits.max_order_qty` |
| `MAX_ORDER_VALUE` | engine | Quantity × price is above `order_limits.max_order_value`. An order without a price (`MARKET`) is not checked against it |

### Session and halts

| Code | Where | When |
|---|---|---|
| `MARKET_CLOSED` | engine | A new order or amend while the session is `CLOSED` |
| `SESSION_NOT_PERMITTED` | engine | The phase accepts orders, but not this one: an `ATO` order outside the opening auction, an `ATC` order outside the closing auction, or a `MARKET`, `IOC` or `FOK` order during an auction phase, when it could not trade and cannot rest |
| `CIRCUIT_BREAKER_ACTIVE` | engine | A `MARKET`, `IOC` or `FOK` order for a symbol a circuit breaker has halted. A `LIMIT` or `ICEBERG` is accepted and rests for the reopening |
| `INSTRUMENT_HALTED` | engine | The same, for a symbol an operator halted (per symbol or with halt-all) |

### Cancel and amend

| Code | Where | When |
|---|---|---|
| `ORDER_NOT_FOUND` | engine | Cancel or amend of an order that is not live (often it just filled), or a cancel of an unknown combo, OCO, or of a quote that is not active |
| `ORDER_ALREADY_TERMINAL` | engine, REST | Amend of an order that is already filled, cancelled, rejected or expired; cancel of a combo that has already ended; a REST replace whose original has already ended |
| `AMEND_NOT_PERMITTED` | engine | Amend of an order type that cannot be amended. Only `LIMIT` and `ICEBERG` orders can; cancel and re-enter the others |

### Liquidity and self-match

| Code | Where | When |
|---|---|---|
| `INSUFFICIENT_LIQUIDITY` | engine | A `FOK` order that cannot fill in full at its price or better. The check counts hidden iceberg quantity and leaves out the sender's own orders that self-match prevention would skip. Nothing trades. Also the first leg of an all-or-none combo that is short on one leg while another leg would trade now: the whole combo is refused and nothing is posted |
| `SELF_MATCH_PREVENTED` | — | In the vocabulary, but never sent as a reject code. A self-match is reported as a *cancel* (see below), including for a `FOK` whose shortfall was the sender's own orders |

### Faults

| Code | Where | When |
|---|---|---|
| `INTERNAL_ERROR` | ALF, REST, engine | A request the engine could not handle because of an internal fault, or the gateway could not reach the engine (`ENGINE_UNAVAILABLE`, an engine reply timeout). Usually transient |
| `UNKNOWN` | ALF, REST | A refusal with no more specific code: an ALF error that has no mapping, and REST's 404/405/409 errors. Also what a client should treat an unrecognised code as |

### Reserved codes

`LOT_VIOLATION`, `POSITION_LIMIT` and `KILL_SWITCH_ACTIVE` are in the
vocabulary, but no component sends them today. There is no lot-size check,
no position limit, and a kill switch is a one-time mass cancel: the gateway's
orders are cancelled with `KILL_SWITCH`, and new orders are accepted
afterwards.

## Cancel reasons

An `order.cancelled` with no `cancel_reason` is either the client's own cancel
(it carries the client's `request_tag`) or an exchange cancel whose cause is
not classified.

| `cancel_reason` | When |
|---|---|
| `INSUFFICIENT_LIQUIDITY` | The unfilled remainder of a `MARKET` order (the book ran out) or an `IOC` order (nothing left at its price or better). The order was accepted first: a `MARKET` order into an empty book gets `ACCEPTED=TRUE` and then a cancel for its full quantity, **not** a reject |
| `SELF_MATCH_PREVENTED` | Self-match prevention cancelled the order: the aggressor (`CANCEL_AGGRESSOR`, `CANCEL_BOTH`) or the resting order (`CANCEL_RESTING`, `CANCEL_BOTH`). A `FOK` short only because of the sender's own orders ends this way too. It takes precedence over `INSUFFICIENT_LIQUIDITY` |
| `KILL_SWITCH` | The gateway's own kill switch, or an operator's kill switch for it or for everyone |
| `CIRCUIT_BREAKER_HALT` | A halt (a circuit-breaker trip or an operator's halt-all) pulled a market maker's quote legs in the symbol. Ordinary resting orders stay on the book |
| `GATEWAY_DISCONNECT` | The owner disconnected and its `disconnect_behaviour` cancels orders |
| `ADMIN_CANCEL_SYMBOL` | An operator cancelled every order in the symbol |
| `QUOTE_REPLACED` | A market maker's new quote replaced this quote leg |
| `QUOTE_LEG_FILLED` | The other leg of the quote filled, and this one was pulled with it |

## BALF numeric codes

BALF carries both kinds of code as one byte. The engine's `reject_code`
maps onto `ORDER_ACK.reject_code` as follows; the full field tables are in
the [BALF specification](../../protocols-and-clients/part-2-specifications/020-balf.md).

| BALF | Constant | Engine `reject_code` |
|---|---|---|
| `0x01` | `RC_GW_NOT_CONFIGURED` | `GATEWAY_NOT_CONFIGURED` |
| `0x02` | `RC_GW_NOT_CONNECTED` | `AUTH_REQUIRED` |
| `0x03` | `RC_SYMBOL_NOT_CONFIGURED` | `UNKNOWN_SYMBOL` |
| `0x04` | `RC_MARKET_CLOSED` | `MARKET_CLOSED` |
| `0x05` | `RC_ATO_OUTSIDE_OPENING` | `SESSION_NOT_PERMITTED` (ATO) |
| `0x06` | `RC_ATC_OUTSIDE_CLOSING` | `SESSION_NOT_PERMITTED` (ATC) |
| `0x07` | `RC_HALT_REJECTION` | `INSTRUMENT_HALTED`, `CIRCUIT_BREAKER_ACTIVE` |
| `0x08` | `RC_PHASE_REJECTION` | `SESSION_NOT_PERMITTED` (any other) |
| `0x09` | `RC_TRAILING_STOP_NO_PRICE` | `MISSING_FIELD` (trailing stop with no reference price) |
| `0x0A` | `RC_INSUFFICIENT_LIQUIDITY` | `INSUFFICIENT_LIQUIDITY` |
| `0x0B` | `RC_PRICE_COLLAR` | `COLLAR_BREACH` |
| `0x0C` | `RC_INVALID_FIELD` | `MALFORMED_MESSAGE`, `MISSING_FIELD`, `INVALID_VALUE`, `UNSUPPORTED_FIELD`, `TICK_VIOLATION`, `PRICE_OUT_OF_RANGE`, `QTY_OUT_OF_RANGE` |
| `0x0D` | `RC_RATE_LIMITED` | `RATE_LIMITED` |
| `0x0E` | `RC_RISK_LIMIT` | `MAX_ORDER_QTY`, `MAX_ORDER_VALUE` |
| `0xFF` | `RC_OTHER` | anything else; read `reason` |

`CANCEL_ACK.cancel_reason` is `0` for the client's own cancel, then
`1` `SELF_MATCH_PREVENTED`, `2` `INSUFFICIENT_LIQUIDITY`, `3` `KILL_SWITCH`,
`4` `CIRCUIT_BREAKER_HALT`, `5` `GATEWAY_DISCONNECT`, `6` `ADMIN_CANCEL_SYMBOL`,
`7` `QUOTE_REPLACED`, `8` `QUOTE_LEG_FILLED`, `254` for an expiry (`DAY`, `ATO`,
`ATC` at the end of their period) and `255` for an unclassified exchange
cancel.

## See also

- [Reject codes at a glance](../../participant-guide/part-2-orders/025-risk-controls-you-meet.md#reject-codes-at-a-glance) — what to do about the common ones
- [Order Types](../../participant-guide/part-2-orders/020-order-types.md) — how each type ends when the book runs out
- [REST: unsolicited cancels](../../protocols-and-clients/part-2-specifications/060-rest-and-websocket.md#unsolicited-cancels-and-cancel_reason)
- [ALF gateway: unsolicited cancels](../../operator-guide/part-5-gateways/010-alf-gateway.md#unsolicited-cancels)

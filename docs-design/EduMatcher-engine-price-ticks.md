Version: 1.0.0

Date: 2026-08-24

Status: Proposed — not yet implemented. Written up after the asymmetry was
found and worked around at the display layer (`pm-orders`, `pm-board`)
rather than fixed at the source; this document proposes fixing the source.

# EduMatcher — Engine Order-Price Tick/Display-Money Asymmetry

## Table of Contents

- [EduMatcher — Engine Order-Price Tick/Display-Money Asymmetry](#edumatcher--engine-order-price-tickdisplay-money-asymmetry)
  - [Table of Contents](#table-of-contents)
  - [1. Motivation](#1-motivation)
  - [2. Problem Statement](#2-problem-statement)
  - [3. Background: the Conversion Boundary Rule](#3-background-the-conversion-boundary-rule)
  - [4. How the Boundary Actually Drifted](#4-how-the-boundary-actually-drifted)
    - [4.1 The gateways: `to_ticks()` moved to the wrong side](#41-the-gateways-to_ticks-moved-to-the-wrong-side)
    - [4.2 The engine: `_handle_new_order()` never converts on the way in](#42-the-engine-_handle_new_order-never-converts-on-the-way-in)
    - [4.3 The output side: some `"price"` fields convert, some don't](#43-the-output-side-price-fields-some-convert-some-dont)
    - [4.4 Why `_handle_amend()` is unaffected](#44-why-_handle_amend-is-unaffected)
    - [4.5 Why this went unnoticed](#45-why-this-went-unnoticed)
  - [5. Goals and Non-Goals](#5-goals-and-non-goals)
    - [5.1 Goals](#51-goals)
    - [5.2 Non-Goals](#52-non-goals)
  - [6. Proposal](#6-proposal)
    - [6.1 Option A — restore the documented rule (gateways send floats)](#61-option-a--restore-the-documented-rule-gateways-send-floats)
    - [6.2 Option B — codify what actually ships (gateways send ticks)](#62-option-b--codify-what-actually-ships-gateways-send-ticks)
    - [6.3 Recommendation](#63-recommendation)
  - [7. Detailed Design (Option B)](#7-detailed-design-option-b)
    - [7.1 `_handle_new_order()` output side](#71-_handle_new_order-output-side)
    - [7.2 OCO and combo order paths](#72-oco-and-combo-order-paths)
    - [7.3 `models/message.py` helper functions](#73-modelsmessagepy-helper-functions)
    - [7.4 Gateways](#74-gateways)
    - [7.5 Documentation](#75-documentation)
  - [8. Impact Zone](#8-impact-zone)
  - [9. Risks](#9-risks)
  - [10. Testing Strategy](#10-testing-strategy)
  - [11. Rollout Plan](#11-rollout-plan)
  - [12. Open Questions](#12-open-questions)
  - [13. Summary](#13-summary)

## 1. Motivation

While reworking `pm-orders`' display (making it show every order event in
real money instead of raw integers), the price column turned out to be
showing values like `15030` instead of `150.30` for some rows and the
correct `150.30` for others in the *same* table, depending only on which
event type produced the row. Chasing that down surfaced a genuine
asymmetry in `edumatcher.engine.main` (`_handle_new_order`): the price
echoed back on `order.ack` and on the aggressor side of `order.fill` is
whatever the client submitted, unconverted, while every other price the
engine ever publishes — `order.amended`, `book.*` snapshots, quote legs,
the OCO/combo ack paths, and the passive side of `order.fill` — is
correctly run through `from_ticks()` first.

The immediate problem (pm-orders showing raw integers) was fixed entirely
in the display layer, per explicit instruction at the time: pm-orders'
functionality was fine, only its visuals needed fixing, and the engine was
out of scope for that pass. `pm-orders` now special-cases these two fields
(preferring `fill_price` when present, otherwise converting `price`
itself) so the table always shows real money regardless of which field the
event happens to carry. That workaround is correct and should stay — but
it treats a symptom in one subscriber. Any other subscriber that reads
`order.ack.price` or the aggressor's `order.fill.price` today — a bot, a
future dashboard, an audit query — inherits the same raw-integer value
unless it independently knows to apply the same special case. This
document is the write-up of that asymmetry and a proposal to fix it at
the source.

## 2. Problem Statement

`edumatcher.engine.main.EngineProcess._handle_new_order()` publishes two
message types per accepted order:

- `order.ack` (topic `order_ack.<gateway>`) — the "gateway accepted this
  order" acknowledgement, published immediately, before matching runs.
- `order.fill` (topic `order_fill.<gateway>`) — one per order that
  executed any quantity, published from the post-matching events loop.

Both carry a `"price"` field. For `order.ack`, it is
`payload.get("price")` — read straight off the inbound ZMQ message with no
transformation. For `order.fill`, the *aggressor* order (the one that
triggered `_handle_new_order`, i.e. `evt is order`) reuses that same
unconverted value; the *passive* side (the resting order(s) it traded
against) instead gets `from_ticks(evt.price, evt.symbol)`, and the
`fill_price` field on both sides is always `from_ticks(...)`-converted.

Whether `payload.get("price")` is "raw ticks" or "display money" at that
point depends entirely on what the gateway that sent it chose to put
there — see §4. In the deployed system today, both shipped gateways
(`alf_gwy`, `balf_gwy`) send integer ticks, so the *practical* symptom is:
`order.ack.price` and the aggressor's `order.fill.price` are raw ticks
(e.g. `15030`) while `fill_price`, the passive side's `price`, and every
other price field the engine publishes are display money (e.g. `150.30`).
For a symbol whose `tick_decimals` is not 2, or for any price that is not
a whole number of cents, the two can look nothing alike, and a subscriber
that doesn't special-case these two fields will display or compute with
the wrong value.

## 3. Background: the Conversion Boundary Rule

`docs-design/EduMatcher-Tick_Migration_Plan.md` §4, "The Conversion
Boundary Rule," is the authoritative design for how prices are supposed to
cross the engine's process boundary. Its allowed/forbidden table is
explicit:

| Location | Allowed | Forbidden |
|---|---|---|
| Gateway | Parse `float` from user input; send float in JSON payload | Call `to_ticks()`; store int ticks |
| Engine `_handle_new_order()` (input boundary) | Call `to_ticks()` once per price field; validate result | Store raw float; pass float to OrderBook |
| Engine `OrderBook` (internal) | Integer arithmetic; integer key lookups; integer comparison | Accept float prices; call `from_ticks()` |
| Engine `_handle_new_order()` (output boundary) | Call `from_ticks()` before publishing to ZMQ | Publish raw int ticks directly |
| Subscriber processes | Display float prices received from ZMQ | Call `to_ticks()` on received prices; do arithmetic on float prices |

and its rationale (§4, "Why the Gateway Sends Floats but the Engine Uses
Ints") is equally explicit: the engine is "the only process that reads
`engine_config.yaml`" and therefore "the only process that can correctly
convert prices to ticks." Conversion is meant to happen exactly once in
each direction, both times inside the engine, at its I/O boundary.

If that rule were followed as written, this asymmetry could not exist:
`_handle_new_order()` would call `to_ticks()` on `payload["price"]` before
ever using it, `order.price` (and hence the aggressor's echoed price)
would already be an int, and every outbound `"price"` field — ack, fill,
amended, snapshot — would go through the same `from_ticks()` call before
publish. §7 (below) proposes restoring exactly that shape.

## 4. How the Boundary Actually Drifted

### 4.1 The gateways: `to_ticks()` moved to the wrong side

Both shipped gateways convert to ticks themselves, before the price ever
reaches the engine — the opposite of what §4's table says gateways are
allowed to do:

`src/edumatcher/alf_gwy/gateway.py` (text ALF protocol), building the
outbound `order.new` payload from a parsed `PRICE=150.30` command:

```python
order = Order.create(
    symbol=symbol,
    side=side,
    order_type=order_type,
    quantity=quantity,
    gateway_id=self._require_gw(session),
    tif=tif,
    price=to_ticks(price, symbol) if price is not None else None,
    stop_price=to_ticks(stop_price, symbol) if stop_price is not None else None,
    ...
)
```

`src/edumatcher/balf_gwy/translate.py` (binary BALF protocol), decoding a
scaled-integer wire price and re-encoding it as ticks before handing it to
the engine:

```python
price_display = decode_price(int(parsed["price"])) if parsed["price"] != 0 else None
...
# Convert display prices to engine ticks
price_ticks = to_ticks(price_display, symbol) if price_display is not None else None
```

Both gateways import `to_ticks` from `edumatcher.models.price` — the same
module the engine itself uses — so the *conversion* is correct; only its
*location* violates §4's rule. Each gateway process does read
`engine_config.yaml` (or an equivalent) for its own reasons already, so
the "gateway doesn't know tick size" argument in §4 no longer describes
the real codebase, even though it was accurate when that document was
written.

### 4.2 The engine: `_handle_new_order()` never converts on the way in

Because the gateways already send ticks, `_handle_new_order()` was never
written to convert on input:

```python
def _handle_new_order(self, payload: dict[str, Any]) -> None:
    order = Order.from_dict(payload)
    ...
```

`Order.from_dict()` (`src/edumatcher/models/order.py`) copies
`d.get("price")` straight into `o.price` with no conversion of any kind.
There is no `to_ticks()` call anywhere on this path. This is actually
*consistent* with the gateways described in §4.1 — the engine is trusting
that whatever arrives in `payload["price"]` is already ticks, because
that's what both real gateways do — but it means `_handle_new_order()`
also no longer matches §4's "input boundary: call `to_ticks()` once per
price field" rule. The rule has effectively been relocated to the
gateways without anyone updating the design document or the engine
handler's own comments to say so.

### 4.3 The output side: some `"price"` fields convert, some don't

This is the actual bug, and it's independent of where the input-side
conversion lives. Every *other* engine handler that publishes a price
converts it with `from_ticks()` immediately before publish:

- `order_to_display_dict()` (`engine/main.py`, used for order snapshots):
  `d["price"] = from_ticks(order.price, sym) if order.price is not None else None`
- `_active_quote_legs()` (quote-leg listings):
  `"price": from_ticks(leg_order.price, entry.symbol) if leg_order.price is not None else None`
- `_handle_amend()`'s `order.amended` publish:
  `price=(from_ticks(amended.price, amended.symbol) if amended.price is not None else None)`
- The OCO leg-ack path (`_handle_oco`, around the `make_ack_msg` call for
  each leg): `"price": (from_ticks(leg.price, leg.symbol) if leg.price is not None else None)`
- `order.fill`'s **passive** side: `from_ticks(evt.price, evt.symbol) if evt.price is not None else None`

`_handle_new_order()`'s own ACK, and the **aggressor** side of its own
`order.fill`, are the only two places in the entire engine that publish a
`"price"` field straight from `payload.get("price")` with no
`from_ticks()` call:

```python
_price_v = payload.get("price")  # None for MARKET orders
_pub.send_multipart([
    ack_topic,
    dumps({
        ...
        "price": _price_v,
        ...
    }),
])
```

and, in the fill loop, keyed off `_is_agg = evt is order`:

```python
"price": (
    _price_v
    if _is_agg
    else (
        from_ticks(evt.price, evt.symbol)
        if evt.price is not None
        else None
    )
),
```

The comments at this call site ("Hot path: fill payload built inline with
pre-cached topic bytes; for the aggressor (evt is order) canonical string
values from the payload are reused, see docs-design/perf-notes.md")
explain *why* the aggressor's `side`/`order_type`/`tif` strings are reused
from the payload instead of re-derived from `evt` — that's a legitimate,
narrow hot-path optimization for fields where the payload's string and the
canonical enum's `.value` are guaranteed identical. `price` was folded
into the same "reuse the payload value" pattern, but it isn't the same
kind of field: `side_v`/`ot_v`/`tif_v` are string round-trips with no
transformation either way, while `price` needs a unit conversion that the
passive side receives and the aggressor does not. This reads as the
optimization being applied one field too broadly, not a deliberate choice
to leave the aggressor's price unconverted.

### 4.4 Why `_handle_amend()` is unaffected

`_handle_amend()` (`engine/main.py`, `_handle_amend`) has the interesting
property of getting this exactly right, and it's worth calling out why:
its inbound `new_price = payload.get("price")` is explicitly converted
before use —

```python
new_price_ticks = (
    to_ticks(float(new_price), symbol) if new_price is not None else None
)
```

— and its outbound `order.amended` message converts back with
`from_ticks()` before publish (§4.3 above). This means `_handle_amend()`
still behaves as if callers send it *display-money* floats, matching §4's
original rule, while `_handle_new_order()` behaves as if callers send it
*ticks*. Both gateways, however, send ticks for new orders (§4.1) and (by
the same code path building the same `order.amend` message shape) likely
also send ticks for amends — meaning `_handle_amend()`'s `to_ticks()` call
is almost certainly double-converting an already-tick value today. This
document does not resolve that separately; §12 lists it as an open
question that needs a direct trace against the gateways' amend-building
code before any fix ships, since it changes the recommended direction in
§6.

### 4.5 Why this went unnoticed

No engine handler test in `tests/test_engine_handlers.py`,
`tests/test_engine_handlers2.py`, or `tests/test_engine_order_display.py`
asserts the numeric value of `order.ack["price"]` or the aggressor's
`order.fill["price"]` against an expected real-money figure for a symbol
whose `tick_decimals` differs from the engine-wide default of 2, or for a
price that isn't a whole number of ticks-as-cents. The existing assertions
either check `is not None`/`is None` (presence, not value) or use round
dollar amounts on `tick_decimals=2` symbols, where a raw-ticks value like
`15030` and a real-money value like `150.30` are both "the number 15030"
and "the number 150.30" respectively but neither test distinguishes them
because neither was written to. The bug is real but silent under every
existing test's assumptions — see §10 for what closes that gap.

## 5. Goals and Non-Goals

### 5.1 Goals

- Every `"price"` field the engine publishes on any topic represents the
  same unit (display money) consistently, with no per-field special
  cases required of subscribers.
- Restore a single, explicit, documented location where ticks and display
  money convert in each direction, matching the spirit of
  `EduMatcher-Tick_Migration_Plan.md` §4 even where the specific
  boundary's *location* is updated to match how the system has actually
  evolved (§6).
- `pm-orders`' current fill_price/price special-casing becomes provably
  redundant (not harmful — `from_ticks()` applied to an already-correct
  display-money value is idempotent under the fix in §7, since the fix
  makes `price` and `fill_price` always agree) rather than load-bearing.
- No change to wire-level behavior for any subscriber that already
  special-cases these two fields correctly (none are known to exist
  outside pm-orders' own workaround, per the grep in §4.5, but the fix
  must not assume that).

### 5.2 Non-Goals

- Re-litigating tick-size validation, rounding tolerance, or any other
  part of `EduMatcher-Tick_Migration_Plan.md` §2/§5 not directly touched
  by this asymmetry.
- Changing which side (gateway vs. engine) is the source of truth for
  `tick_decimals` — it remains the engine's `engine_config.yaml`/compiled
  `engine_config.json`, as today.
- Touching `_handle_amend()`'s correctness beyond the double-conversion
  question flagged in §4.4/§12, which needs its own trace before any code
  changes there.
- Removing pm-orders' or pm-board's own tick-decimals fallback/display
  logic — that code stays useful regardless of this fix, both as a
  defense against any future regression and because those tools must
  keep working against engine versions that predate the fix during a
  mixed-version rollout (§11).

## 6. Proposal

Two shapes of fix are possible, differing in which side of the boundary
moves.

### 6.1 Option A — restore the documented rule (gateways send floats)

Revert `alf_gwy/gateway.py` and `balf_gwy/translate.py` to send display
money, and add the `to_ticks()` call `_handle_new_order()` is currently
missing, exactly as §4's original table specifies. This is the smallest
conceptual change relative to the existing design document — no document
update needed beyond marking §4 "implemented as designed" — but it is the
larger *code* change: it touches both gateways' order-construction paths
(a change to a hot, well-tested, protocol-facing code path in each), and
anywhere else in either gateway that currently assumes an already-tick
value downstream of that conversion (position tracking, local order
books, risk checks — anywhere a gateway does its own arithmetic on the
price it just computed) would need to be re-audited for now receiving a
float instead.

### 6.2 Option B — codify what actually ships (gateways send ticks)

Leave the gateways as they are (both already send ticks, and nothing in
the current investigation found a correctness bug in that choice — only a
documentation/rule mismatch) and instead: (a) update
`EduMatcher-Tick_Migration_Plan.md` §4 to describe the boundary as it
actually exists — gateway is the float→ticks boundary, engine trusts
ticks on input and is the ticks→float boundary on output — and (b) fix
`_handle_new_order()`'s two unconverted output fields (§4.3) to call
`from_ticks()` like every other price-publishing path in the engine
already does. This is the smaller *code* change (two call sites in one
file, `engine/main.py`), confined entirely to the engine's hot order path
with no gateway changes, but it does mean formally revising a design
document's stated rule to match a drift that happened without anyone
deciding to make it, rather than reverting the drift.

### 6.3 Recommendation

Option B. The reasoning:

- The actual defect — the thing causing wrong numbers on the wire today —
  is entirely in §4.3's two call sites. Fixing those two lines removes
  the observable bug regardless of which option is chosen; Option A adds
  a second, larger, riskier change (touching both gateways' hot paths) to
  fix the same bug, in exchange for restoring a rule that, per §4.1, may
  have been moved for a real reason (both gateways already read
  `engine_config.yaml`/tick config for other purposes, so the original
  "gateway doesn't know tick size" justification no longer holds as
  written).
- Gateway-side tick conversion has apparently been running in production
  as the de facto design for long enough that both independent gateway
  implementations (`alf_gwy` and `balf_gwy`) converged on it. Reverting
  that now, without a specific benefit beyond document-conformance, is a
  larger blast radius for no behavioral gain — Option A's failure mode
  (a missed downstream float-vs-ticks assumption in either gateway) is
  exactly the kind of silent, hard-to-test bug this whole document is
  about.
- Option B still fully satisfies the goals in §5.1: one consistent unit
  on every published `"price"` field, one documented conversion boundary
  per direction — the boundary's location changes from "inside
  `_handle_new_order()`, both directions" to "gateway on input, engine on
  output," which is a smaller, more honest correction to the design
  document than Option A's full reversion.

If the answer to the `_handle_amend()` double-conversion question (§4.4,
§12) turns out to be "amend also already receives ticks from both
gateways," that finding folds cleanly into Option B: remove
`_handle_amend()`'s now-redundant `to_ticks()` call at the same time, for
the same reason.

## 7. Detailed Design (Option B)

### 7.1 `_handle_new_order()` output side

Two call sites change. The `order.ack` publish:

```python
_price_v = payload.get("price")  # None for MARKET orders
```

becomes

```python
_price_v = (
    from_ticks(order.price, order.symbol) if order.price is not None else None
)
```

reading the *converted* `order.price` that `Order.from_dict()` already
holds (an int, per §4.2 — no input-side change needed under Option B)
rather than the raw payload, so `_price_v` is display money everywhere it
is used from this point on — including its reuse for `side`/`order_type`/
`tif` is unaffected, since only the price derivation changes.

The fill-loop's aggressor branch:

```python
"price": (
    _price_v
    if _is_agg
    else (
        from_ticks(evt.price, evt.symbol)
        if evt.price is not None
        else None
    )
),
```

can then be simplified to always take the `from_ticks()` branch, since
`_price_v` is now already display money and the two branches compute the
same thing by construction:

```python
"price": (
    from_ticks(evt.price, evt.symbol) if evt.price is not None else None
),
```

removing the `_is_agg` special case entirely for this one field (the
`_is_agg` branching for `side`/`order_type`/`tif` stays — those remain a
legitimate reuse-vs-derive choice unrelated to unit conversion). The
`_is_agg` variable itself stays in scope for the other fields, so no
further restructuring is needed.

### 7.2 OCO and combo order paths

`_handle_oco`'s per-leg ACK (§4.3) already calls `from_ticks()` correctly
and needs no change. Its own fill-publication loop (visible around line
4527 in the current file, structurally similar to `_handle_new_order`'s)
should be checked for the same aggressor-reuse pattern found in §4.3 — the
excerpt reviewed for this document used `_o_fill_px.get(...)` for
`fill_price` but the surrounding `"price"` field (if the leg's own order
event loop has one) needs the same audit `_handle_new_order` just
received. Combo order handling should receive the same check. This is
called out explicitly because the bug in §4.3 was found by chance while
working on a display tool, not via a systematic audit — the fix should
not assume `_handle_new_order` is the only handler with this shape until
that audit is done (§10 turns this into a concrete test-writing step
rather than leaving it as a hope).

### 7.3 `models/message.py` helper functions

`make_ack_msg`, `make_fill_msg`, and `make_amended_msg` (all in
`src/edumatcher/models/message.py`) are thin message-shape builders; they
do not perform unit conversion themselves today and this proposal does
not add any — every call site above is responsible for passing an
already-converted value, matching how `_handle_amend` and
`order_to_display_dict` already call them. No signature changes are
proposed. (An alternative considered and rejected: push the
`from_ticks()` call *into* these helpers, which would make the bug in
§4.3 structurally impossible to reintroduce. Rejected for this proposal
because it would require every helper to also accept the `symbol` needed
for per-symbol tick precision, a larger signature change across every
call site in the engine for a benefit — future-proofing — that §10's new
regression test already covers without it. Worth revisiting if a second,
unrelated instance of this same class of bug turns up later.)

### 7.4 Gateways

No changes under Option B (§6.2). `alf_gwy/gateway.py` and
`balf_gwy/translate.py` continue converting to ticks before publishing
`order.new`/`order.amend`, exactly as today.

### 7.5 Documentation

`EduMatcher-Tick_Migration_Plan.md` §4's table and diagram get a
follow-up note (not a silent edit — the changelog convention this
document family already uses, per `EduMatcher-log-srv.md`'s "Changelog
vX.Y.Z" blocks) recording that the boundary's *location* differs from
what was originally specified: the gateway is now the recognized
float→ticks boundary, and the engine trusts already-tick input while
remaining the sole ticks→float boundary on output. The rationale in §4.1
of this document (both gateways already read tick configuration for other
purposes) becomes the recorded justification, so a future reader of the
migration plan is not left thinking the shipped gateways violate a rule
that was deliberately superseded.

## 8. Impact Zone

Files that change:

- `src/edumatcher/engine/main.py` — `_handle_new_order()`'s two call
  sites (§7.1); `_handle_oco`'s equivalent fill loop pending the audit in
  §7.2; possibly `_handle_amend()` pending §4.4/§12.
- `docs-design/EduMatcher-Tick_Migration_Plan.md` — §4 changelog note
  (§7.5).

Files that do NOT change:

- `src/edumatcher/alf_gwy/gateway.py`, `src/edumatcher/balf_gwy/translate.py`
  — Option B leaves both untouched (§7.4).
- `src/edumatcher/models/message.py` — no signature changes (§7.3).
- `src/edumatcher/models/order.py`, `src/edumatcher/models/price.py` — no
  changes; `Order.from_dict()` and `to_ticks()`/`from_ticks()` are used
  exactly as they exist today.
- `src/edumatcher/orders/main.py`, `src/edumatcher/board/main.py` — the
  existing fill_price/price special-casing added while fixing pm-orders'
  display stays in place (§5.1) and needs no code change; it simply
  becomes provably redundant once the engine always publishes
  already-converted prices. It should not be removed at the same time as
  the engine fix ships, to avoid a window where an old engine and a new
  pm-orders (or vice versa) disagree about units — see §11.

Every subscriber of `order.ack`/`order.fill` — every gateway
(`alf_gwy`, `balf_gwy`, `api_gwy`, `dc_gwy`, `md_gwy`, `ralf_gwy`), every
bot (`ai_trader`, `ai_swarm`, `mm_bot`), `pm-clearing`, `pm-stats`,
`pm-audit`, and any admin/CLI tool that reads the live bus rather than a
snapshot — is a *behavioral* consumer of the fixed field even though none
of their code changes. Each one that currently reads `order.ack.price` or
the aggressor's `order.fill.price` and does anything beyond passing it
through for display (arithmetic, comparison, storage) should be checked
for whether it was compensating for the raw-ticks value, matching
pm-orders' now-redundant workaround, or was unknowingly ingesting
raw-ticks values as if they were display money. §10 covers how to find
out which.

## 9. Risks

- **A compensating consumer breaks silently.** If any process besides
  pm-orders/pm-board already has its own workaround for the raw-ticks
  value (multiplying it back up, treating it as an int deliberately,
  etc.), fixing the engine's output makes that workaround wrong in the
  opposite direction — it would start double-converting a now-correct
  float. §8's subscriber list is the starting point for checking this
  before the fix ships; none were found in this investigation's grep of
  the display tools, but the full subscriber list was not exhaustively
  audited for this document.
- **The `_handle_amend()` double-conversion question (§4.4) changes the
  proposal's shape if answered "yes."** If both gateways also send
  already-tick prices for amends, `_handle_amend()` is currently
  converting a tick value with `to_ticks()` a second time — which, unlike
  the ack/fill bug, is a correctness bug with a much larger effective
  magnitude (a second multiplication by `10**tick_decimals`, not a missed
  single conversion) and would need its own, separate, higher-priority
  fix, not bundled silently into this one. This must be resolved by
  direct trace of both gateways' amend-payload construction before
  implementation starts, not assumed.
- **Hot-path performance.** `_handle_new_order`'s ACK and fill publish are
  explicitly called out as the hot path in the surrounding comments and
  in `docs-design/perf-notes.md`. Adding one `from_ticks()` call
  (`ticks / 10**tick_decimals`, a dict lookup plus a division) to a path
  that previously did zero conversion work is a small, likely
  unmeasurable cost next to the existing `dumps()`/ZMQ send, but should be
  confirmed against `perf-notes.md`'s existing benchmarks rather than
  assumed — this is exactly the kind of "hot path" file that documents
  its own performance budget.
- **Wire-format version skew during rollout.** A subscriber built against
  the old (buggy) behavior that has its own compensating logic, run
  against a new (fixed) engine, silently gets wrong numbers until
  updated — and the reverse, an old engine with a new subscriber that
  assumes the fix is already live. §11 addresses this with an explicit
  rollout order.
- **Scope creep into `_handle_oco`/combo paths.** §7.2 flags that the same
  bug shape may exist elsewhere but was not exhaustively confirmed for
  this document. Implementing only the confirmed `_handle_new_order` fix
  while leaving an equivalent bug live in the OCO/combo path would be a
  false sense of completion; §10's regression test needs to cover all
  three paths, not just the one found by chance.

## 10. Testing Strategy

- **Regression test, the core bug.** A new test in
  `tests/test_engine_handlers.py` (or a new
  `tests/test_engine_price_conversion.py`, mirroring the pattern of
  `test_engine_order_display.py`) that submits a `NEW` order for a symbol
  configured with `tick_decimals` other than the engine-wide default (2)
  — e.g. 4, matching the FX example in the migration plan's table — at a
  price that is *not* a whole number of cents, and asserts that
  `order.ack["price"]`, both sides' `order.fill["price"]`, and
  `order.fill["fill_price"]` are all equal to the same display-money
  float, none of them off by a factor of `10**tick_decimals`. This is the
  test whose absence is why §4.5's bug shipped unnoticed; it must use a
  non-default `tick_decimals` and a non-round price specifically so a
  future regression can't hide behind the same coincidence that let this
  one through.
- **OCO/combo audit, turned into tests.** Once §7.2's manual audit
  identifies every place a fill/ack price is published in the OCO and
  combo handlers, each gets the same non-default-tick_decimals assertion
  as above, whether or not the audit finds a live bug there — a passing
  test either way is what makes §7.2 "confirmed fixed" rather than
  "probably fine."
- **`_handle_amend()` trace.** Before any amend-path code changes, a
  focused trace (or a small standalone test harness, not necessarily a
  permanent test) confirming what unit `alf_gwy`/`balf_gwy` actually put
  in an `order.amend` payload's `"price"` field today, resolving §4.4's
  open question. If it confirms double-conversion, that becomes its own
  test asserting `order.amended["price"]` matches the originally
  requested display-money price, and its own fix, sequenced ahead of or
  alongside this document's Option B changes.
- **Cross-check against `pm-orders`' workaround.** After the engine fix
  lands, re-run (or write, if it doesn't already exist) a `pm-orders`
  test that feeds a synthetic `order.fill` event through
  `OrderMonitor._handle()` and confirms the displayed price is identical
  whether or not `fill_price` is present in the payload — proving the
  special-case in `orders/main.py` is now provably redundant (§5.1) rather
  than merely believed to be.
- **Full engine suite.** Run the existing
  `tests/test_engine_*.py`/`tests/test_*_gateway*.py`/
  `tests/test_*_integration.py` files unchanged, to catch any existing
  test that was inadvertently asserting the old (buggy) raw-ticks value —
  per §4.5 none were found in the handler-specific suites reviewed for
  this document, but the full suite is larger than what was checked here.

## 11. Rollout Plan

Because `order.ack`/`order.fill` are consumed live by multiple
independent processes (§8) with no version negotiation on the ZMQ pub/sub
bus, this should not be a flag-day change across every process
simultaneously:

1. Land the engine fix (§7.1, plus §7.2's audit results) behind normal
   code review and the tests in §10, but do not yet remove any
   subscriber-side workaround.
2. Confirm via §10's tests that `pm-orders`/`pm-board`'s existing
   fill_price/price special-casing is now redundant, but leave that code
   in place for at least one full deployment cycle — it is a no-op once
   the engine is fixed (a `from_ticks()`-converted value passed back
   through the same conversion path pm-orders would otherwise apply is
   idempotent, since `pm-orders` prefers `fill_price` when present and
   both fields now agree), so keeping it costs nothing and is a safety
   net during any window where an operator is running a mismatched engine
   version.
3. Audit the other bus subscribers named in §8 (gateways, bots,
   `pm-clearing`, `pm-stats`, `pm-audit`) for any code that reads
   `order.ack.price` or `order.fill.price` and does arithmetic or storage
   on it (not just display) — anything found gets the same "is this
   compensating for the old bug" review as §9's first risk before the
   engine fix goes to production, since those are the consumers actually
   at risk of silently breaking.
4. Only after that audit, and only if it finds nothing depending on the
   old behavior, consider removing pm-orders'/pm-board's now-redundant
   special-casing in a later, separate change — not bundled with the
   engine fix itself.

## 12. Open Questions

- Does `_handle_amend()`'s `to_ticks(float(new_price), symbol)` call
  (§4.4) double-convert an already-tick value from both gateways today?
  This needs a direct trace of `alf_gwy`'s and `balf_gwy`'s
  `order.amend`-building code (parallel to the `order.new` code already
  traced in §4.1) before Option B's scope is finalized — if confirmed,
  it's a separate, higher-priority fix per §9.
- Does the same aggressor-reuse-of-unconverted-price pattern (§4.3) exist
  in `_handle_oco`'s or the combo handler's fill-publication loops
  (§7.2), or was `_handle_new_order` the only place it was introduced?
  This document's investigation found the `_handle_new_order` instance by
  chance while working on `pm-orders` and did not have time to
  exhaustively re-read every handler in `engine/main.py` (231,950 bytes)
  for the same shape.
- Are there subscribers outside the four processes examined for this
  document (`pm-orders`, `pm-board`, and the two gateways for the input
  side) that read `order.ack.price` or the aggressor's `order.fill.price`
  and do arithmetic or storage on it rather than display? §11 step 3
  proposes auditing this before removing any workaround, but the audit
  itself is not yet done.
- Should `models/message.py`'s helper functions (`make_ack_msg`,
  `make_fill_msg`) eventually own the `from_ticks()` conversion
  themselves, so this class of bug becomes structurally impossible rather
  than caught by convention plus tests? §7.3 recommends deferring this;
  worth revisiting if a second independent instance of the same bug shape
  turns up.

## 13. Summary

`_handle_new_order()` in `engine/main.py` publishes `order.ack.price` and
the aggressor side of `order.fill.price` straight from the inbound
payload with no `from_ticks()` conversion, while every other price field
the engine ever publishes — `order.amended`, book snapshots, quote legs,
the OCO leg ack, and the *passive* side of `order.fill` — correctly
converts (§2, §4.3). The root cause traces to a documented rule in
`EduMatcher-Tick_Migration_Plan.md` §4 ("gateway sends floats, engine
converts both directions") that the shipped gateways (`alf_gwy`,
`balf_gwy`) no longer follow — both now send already-tick prices (§4.1) —
without anyone updating the engine's output side or the design document
to match, leaving two call sites that still assume their input needs no
further conversion when in fact it does. The fix, recommended as Option B
(§6.3) over reverting the gateways back to floats, is small and confined
to two call sites in `engine/main.py` (§7.1) plus an audit of the
structurally similar OCO/combo paths (§7.2) that were not exhaustively
checked for this document; it requires no gateway changes and no
subscriber changes, though the display-layer workaround already shipped
in `pm-orders`/`pm-board` should stay in place through one full rollout
cycle as a safety net (§11) rather than being removed in the same change.
The one open question that could change this proposal's shape is whether
`_handle_amend()` is independently double-converting an already-tick
price from the same gateways (§4.4, §12) — a distinct, likely
higher-severity bug that needs its own trace and, if confirmed, its own
fix before or alongside this one.

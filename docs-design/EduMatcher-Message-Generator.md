Version: 1.8.0

Date: 2026-08-08

Changes in 1.8.0 — Phase 4 is split into **4a (text/CALF)** and **4b
(binary/BALF)**, and 4a is implemented. Five corrections, all found by reading
the C and gateway code the design describes:

- **§B.13's text key-ordering rule — which 1.5.0 introduced — was wrong.** CALF
  injects `{CH,SYM,SEQ,TS}` before the payload; RALF appends `SEQ` *after* it.
  No single ordering rule covers both. It was also unnecessary: the generated
  projection emits only payload fields, so envelope order is not its problem.
- **§5.2's error-code table.** The claim that generated code "reuses the
  convention rather than inventing a second one" was already false:
  `calf_parser.c` uses `-1`..`-6` with meanings unrelated to `balf_parser.c`'s.
  Codes are now defined as per-function contracts, and every family emits a
  `strerror`.
- **§8 Phase 4's acceptance test was unwritable** — it compared against a
  "hand-written struct" that §1.4 says does not exist.
- **`execution_report` is filed under `order`, not `trade`** (§4.1 and §5.2
  contradicted each other).
- **cffi, the `msgen_c` marker and the `build-essential` CI step are all
  dropped** in favour of the compiled-test pattern `test_alf_examples.py`
  already uses.

Changes in 1.7.0 — Phase 3 is implemented. `pm-msgen check` now runs in
`make check` and in CI's `code-check` job, so §7.2's guarantee is live rather
than aspirational; §13.3 is rewritten to say so.

One correction, again found only by running it: **§7.2's CI snippet was wrong.**
It said `run: poetry run pm-msgen check`, which fails in the `code-check` job
because that job installs with `--no-root` and therefore has no console
scripts on `PATH`. §7.2 now carries the working invocation and an explanation,
because a wrong snippet in the normative section is worse than no snippet — it
gets copied. This is the third phase running in which the design was right
about structure and wrong about behaviour (§13.6).

Changes in 1.6.0 — Phases 1 and 2 are implemented; these are the two
corrections implementation forced, both recorded in §8:

- **§8.1** `pm-stats` adopts the generated *topic constant*, not the validating
  parser. A recorder must record what it received; validating it would make the
  recorder refuse exactly the malformed messages someone needs to investigate.
  Generalised into a rule for Phase 5.
- **§8.2** `make_*_unchecked` was reshaped. Phase 1's version routed through
  `from_dict`/dataclass/`to_dict` and measured 4.03 µs against the hand-written
  literal's 0.96 — unusable on a path where `perf-notes.md` counts 0.2–1.0 µs
  savings. It now builds the payload dict directly (1.47 µs, +0.50). Coercion is
  kept deliberately, because dropping it saves 0.34 µs and reintroduces a silent
  int/float wire divergence that mypy cannot catch.

Status: Design and Research Proposal (reviewed three times; code-grounded; normative IDL + parser design)

Changes in 1.5.0 — all seven are corrections found by grounding v1.4.0 against the
tree before Phase 1 began; see §12 for the evidence:

- §4.1's worked example keyed its bus encoding block `bus:`; §B.13/§B.20 key it
  by transport name. The appendix is normative, so §4.1 was wrong and is fixed
  to `engine_pub:`.
- **New normative rule (§5.1.1): `from_dict` coerces and never validates;
  `validate()` is the only strictness gate.** This is what makes a strict spec
  safe for a lenient archive, and it resolves the `aggressor_side` question.
- A.3's `make_*` bypassed `from_dict`, so it skipped the coercion the
  hand-written factory performs. `make_*` now routes through `from_dict`.
- Phase 2's "byte-identical" acceptance criterion asserted one invariant where
  the system has two of different strength; §8 Phase 2 now states both.
- Open question 4 (validating vs unchecked constructors) is promoted to a
  **Phase 2 requirement** for any family whose producer is on a hot path,
  because `trade` is such a family and `make_trade_msg` has no production
  callers (§12.2).
- §B.13 gains a normative key-ordering rule for text projections, without
  which a generated RALF line cannot reproduce the existing one.
- §B.6's `encoding` default and §B.18 rule 5 were both stated unconditionally
  and are unsatisfiable for text-only and BALF-only messages respectively.

One construct was added to the IDL rather than corrected: **`parse_default`**
(§B.7, §B.7.1). It is the syntax the new §5.1.1 rule needs and had no
expression in v1.4.0's grammar; per §B.20's closing paragraph the grammar was
extended rather than an ad-hoc key being introduced in a single spec file.
Open questions 4 and 6 are resolved (§12.5, §8 Phase 2).

# Message Generator - Canonical Message Specification and Code Generation

Generate the Python structures, the C structures, and the reference
documentation for every EduMatcher message from one canonical specification,
so the three can no longer disagree.

## 1. The problem, measured

A message in EduMatcher is currently described in at least three places, none
of which is authoritative and none of which is checked against the others.

Counted against the current tree:

| Surface | Count | Notes |
|---|---|---|
| `make_*` factories in `models/message.py` | 92 | The de-facto publisher API (`grep -cE '^def make_' `; was 78 at v1.0.0) |
| Typed payloads in `models/feed_schema.py` | 7 | Only the payloads clearing needed |
| Topics documented in `270-message-reference.md` | 66 | 2 222 lines, hand-maintained |
| Topics constructed by `encode()` in `message.py` | 53 | |
| **Distinct topic string literals outside `message.py`** | **108** | across **25 files** |

The counts are a point-in-time snapshot; the exact numbers matter less than
the shape they describe, and §7.4 provides the tooling to keep the literal
count honest rather than re-counting by hand. Three findings follow directly.

### 1.1 Payload shape is typed for 7 of 92 messages

`feed_schema.py` exists precisely because clearing needed a contract it could
rely on, and its module docstring says so — it documents units per field for
the handful of payloads it covers. The other 85 factories build a `dict`
literal inline. Nothing declares that `trade.executed` carries `tick_decimals`,
or that `price` is display money rather than ticks; a reader has to infer it
from the factory body.

### 1.2 Topic names are duplicated as literals in subscribers

`combo.ack.`, `circuit_breaker.halt.`, `depth.`, `log.event.` and 17 others are
documented in the reference but never constructed through `message.py`. They
are string literals in `api_gateway/events.py`, `alf_console/main.py`,
`alf_gwy/gateway.py`, `log_srv/pubsub.py` and elsewhere — 108 distinct literals
across 25 files.

A publisher-side rename is therefore silent. The subscriber keeps compiling,
keeps running, and simply stops receiving. This is the same failure class as
the statistics review's recurring theme: no error, just wrong.

### 1.3 The documentation drifts in both directions

Eight topics are constructed in code but absent from the reference:
`auction.indicative.{}`, `book.depth.{}`, `index.constituent_change_ack.{}`,
`index.corp_action_ack.{}`, `index.history.{}`, `risk.cancel_symbol_ack.{}`,
`risk.symbol_halt_ack.{}`, `risk.symbol_resume_ack.{}`.

The statistics work in this repository has already produced live examples of
the reverse: the `trades` example output lost a column when `aggressor_side`
was added, and `book.{SYMBOL}` gained `tick_decimals` in the corporate-actions
groundwork — each needing a manual documentation edit that could equally have
been forgotten.

### 1.4 The C surface has no message types at all

`docs/examples/calf/calf_parser.h` exposes a generic bag:

```c
typedef struct { char key[64]; char value[512]; } calf_field_t;
typedef struct { char msg_type[32]; int field_count; calf_field_t fields[64]; } calf_message_t;
const char *calf_get_field(const calf_message_t *msg, const char *key);
```

Every C client re-derives field names as string literals and re-implements
parsing per field. A field rename in Python cannot reach them at all.



## 2. Goals and non-goals

### Goals

1. One canonical file per message family; everything else generated.
2. Generated Python: typed payload, validating constructor, parser, topic
   constant.
3. Generated C: typed struct, accessors, validating constructor, parser, for
   the text and binary client protocols.
4. Generated documentation slotting into `270-message-reference.md` as an
   appendix without restyling the existing chapter.
5. Validation rules declared once and enforced by *both* language bindings.
6. Documentation-only metadata (motivation, examples, see-also) that never
   reaches the wire.
7. **A CI check that fails when generated output differs from what is
   committed** — the property that actually keeps the three aligned.

### Non-goals

- Replacing ZeroMQ, JSON or the existing wire formats. The generator describes
  what already flows; it does not change it.
- Generating engine business logic. Only message construction, parsing and
  validation.
- Generating stateful *normalisation*. `md_gateway/normaliser.py` and
  `ralf_gateway` keep their per-symbol caches and delta suppression; they call
  the generated projection instead of building field-map literals by hand
  (§4.6, N1).
- A big-bang migration. §8 is explicitly incremental.
- Cross-language RPC. This is a message-shape tool, not a service framework.



## 3. Why not an off-the-shelf IDL

| Option | Why it does not fit |
|---|---|
| Protocol Buffers / FlatBuffers | Would replace the wire format. EduMatcher's formats are pedagogical artefacts — students read CALF text and parse BALF binary by hand. Changing them removes the teaching value. |
| JSON Schema | Validates JSON only. No C generation, no binary layout, no topic model. |
| AsyncAPI | Closest fit, and the topic model is right, but generation targets are web-oriented and it cannot express BALF's fixed binary header or CALF's positional text. |
| Hand-written | The status quo. §1 measures the result. |

The differentiator is that EduMatcher carries **several encodings of one
logical event** — JSON on the internal bus, CALF text key-value, BALF binary
with a fixed header, RALF post-trade text — and each is a *projection* of the
bus payload, not a copy of it (§4.6): a transport carries a subset of fields
under its own names, and some events do not appear on some transports at all.
The docs must show every projection. No off-the-shelf tool covers that
projection-across-heterogeneous-wire-formats model, and the specification
needed is small enough that owning it is cheaper than bending one that does
not fit.



## 4. The canonical specification

One YAML file per family under `spec/messages/`, e.g. `spec/messages/trade.yaml`.

### 4.1 Worked example

```yaml
family: trade
version: 1

messages:
  - name: trade_executed
    topic: "trade.executed"
    transport: [engine_pub, calf, ralf]   # names resolved in §4.4's transport registry

    # ---- documentation-only, never reaches the wire ----
    doc:
      motivation: >
        Public print of a completed match. The authoritative record of what
        traded, consumed by statistics, clearing, index and market data.
      since: "1.0"
      see_also: ["book.{SYMBOL}", "order.fill.{GW_ID}"]
      example_note: >
        aggressor_side is AUCTION for uncross prints, where both sides rested
        and there is no true aggressor.

    fields:
      - name: id
        type: string
        required: true
        doc: >
          Engine trade counter, unique **within one engine run only** — it
          restarts at 1 on every launch.
        validate: { max_len: 64, pattern: '^[0-9]+$' }

      - name: symbol
        type: string
        required: true
        validate: { max_len: 16, pattern: '^[A-Z0-9._]+$' }

      - name: buy_order_id
        type: string
        required: true
        validate: { max_len: 64 }

      - name: sell_order_id
        type: string
        required: true
        validate: { max_len: 64 }

      - name: buy_gateway_id
        type: string
        required: true
        validate: { max_len: 32 }

      - name: sell_gateway_id
        type: string
        required: true
        validate: { max_len: 32 }

      - name: price
        type: float
        required: true
        unit: display_price          # <- unit is declared, not implied
        doc: Execution price in display money. Divide-free; see tick_decimals.
        validate: { gt: 0 }

      - name: quantity
        type: int
        required: true
        unit: shares
        validate: { gt: 0 }

      - name: aggressor_side
        type: enum
        values: [BUY, SELL, AUCTION]
        required: true

      - name: tick_decimals
        type: int
        required: false
        default: 2
        doc: Decimal scale; 1 tick = 10^-tick_decimals.
        validate: { ge: 0, le: 8 }

      - name: timestamp
        type: float
        required: true
        unit: epoch_seconds

    # ---- per-transport encoding (projection model: see §4.6) ----
    # NOTE: `encoding` is keyed by TRANSPORT NAME (§B.13), not by transport
    # class. There is no `bus:` key — the bus block for this message is
    # `engine_pub:`, matching the entry in `transport:` above.
    encoding:
      engine_pub:
        # encode() (models/message.py) returns exactly TWO frames
        # [topic, json_payload]. The per-topic sequence is a third frame added
        # by SequencedPublisher.send_multipart() (messaging/bus.py) at publish
        # time — never by make_*. Emitting it here would double-stamp and fail
        # the Phase 2 byte-identical test.
        frames: [topic, json_payload]
        include: all                       # every field above

      calf:
        # Public market-data print. md_gateway.normaliser.normalise_trade()
        # emits ONLY PX/QTY/SIDE; CH/SYM/SEQ/TS are gateway-injected, not
        # payload keys. The engine trade `id` is deliberately not on this feed.
        msg_type: TRADE
        include: [price, quantity, aggressor_side]
        keys: { price: PX, quantity: QTY, aggressor_side: SIDE }
        gateway_injected: [CH, SYM, SEQ, TS]

      ralf:
        # Post-trade dissemination. ralf_gateway._handle_trade() emits an EXEC
        # line carrying most of the bus fields. `id` feeds both EXEC_ID and
        # MATCH_ID (a projection may map one source field to several keys).
        msg_type: EXEC
        include: [id, buy_order_id, sell_order_id, buy_gateway_id,
                  sell_gateway_id, aggressor_side, quantity, price]
        keys:
          id: [EXEC_ID, MATCH_ID]
          buy_order_id: BUY_ORDER_ID
          sell_order_id: SELL_ORDER_ID
          buy_gateway_id: BUY_GW
          sell_gateway_id: SELL_GW
          aggressor_side: SIDE
          quantity: QTY
          price: PX
        gateway_injected: [CH, SYM, TS]

      # No `balf:` block. BALF is a per-gateway order-entry protocol and carries
      # no public trade print; the real BALF layout is shown by execution_report
      # below.
```

BALF is illustrated by a message that genuinely lives there. The layout,
`msg_type`, sizes and the fixed price scale are all taken from
`docs/examples/balf/balf_parser.py`, not invented:

```yaml
  - name: execution_report
    # BALF-only: a private per-order fill sent to the owning gateway session.
    # This is NOT the public trade.executed print — different transport,
    # different field set (see §4.6 on why they are separate messages).
    transport: [balf]

    fields:
      - { name: client_order_id, type: int,    required: true }
      - { name: order_id,        type: string, required: true, validate: { max_len: 16 } }
      - { name: fill_price,      type: float,  required: true, unit: display_price, validate: { gt: 0 } }
      - { name: fill_qty,        type: int,    required: true, unit: shares }
      - { name: remaining_qty,   type: int,    required: true, unit: shares }
      - { name: timestamp_ns,    type: int,    required: true, unit: epoch_nanos }
      - { name: symbol,          type: string, required: true, validate: { max_len: 8 } }
      - { name: side,            type: enum,   values: [BUY, SELL], required: true }
      - { name: status,          type: enum,   values: [NEW, PARTIAL, FILLED, CANCELLED], required: true }

    encoding:
      balf:
        msg_type: 0x20                 # MSG_EXECUTION_REPORT in balf_parser.py
        frame_size: 72                 # header(8) + body(64); MUST equal FRAME_SIZES[0x20]
        # Fixed 8-byte header (magic=0xBA, version=0x01, msg_type, flags,
        # seq_no u32 LE) is prepended automatically by the generator.
        price_scale: 100000000         # PRICE_SCALE = 1e8, FIXED for all BALF prices — never tick_decimals
        layout:                        # little-endian, offsets relative to body
          - { field: client_order_id, repr: u64,      offset: 0  }
          - { field: order_id,        repr: char[16], offset: 8  }
          - { field: fill_price,      repr: i64,       offset: 24, scale: price_scale }
          - { field: fill_qty,        repr: u32,       offset: 32 }
          - { field: remaining_qty,   repr: u32,       offset: 36 }
          - { field: timestamp_ns,    repr: u64,       offset: 40 }
          - { field: symbol,          repr: char[8],   offset: 48 }
          - { field: side,            repr: u8,        offset: 56, enum_map: { BUY: 1, SELL: 2 } }
          - { field: status,          repr: u8,        offset: 57 }
        # bytes 58..63 are reserved padding to reach the 64-byte body.
```

A second, shorter fragment shows the two type-table entries the example above
never exercises — `nested` and `list[T]` — using the real `book.{SYMBOL}`
shape from `feed_schema.BookLevelPayload`:

```yaml
  - name: book_snapshot
    topic: "book.{symbol}"
    transport: [engine_pub]

    fields:
      - name: symbol
        type: string
        required: true
        validate: { max_len: 16 }

      - name: bids
        type: list[nested]
        item: book_level
        required: true
        validate: { max_items: 32 }        # mandatory for C: fixes book_level_t bids[32]

      - name: asks
        type: list[nested]
        item: book_level
        required: true
        validate: { max_items: 32 }

    nested_types:
      book_level:
        fields:
          - { name: price, type: float, required: false, unit: display_price }
          - { name: qty,   type: int,   required: true,  default: 0, unit: shares }
          - { name: count, type: int,   required: true,  default: 0 }
```

For C, `list[nested]` generates a fixed-size array of the nested struct plus a
count field (`book_level_t bids[32]; uint8_t bids_count;`), never a pointer —
consistent with the fixed-buffer, no-allocation rule in §5.2.

### 4.2 Type system

| Spec type | Python | C | JSON | Notes |
|---|---|---|---|---|
| `string` | `str` | `char[N]` | string | `max_len` mandatory for C |
| `int` | `int` | `int64_t` / sized by `repr` | number | |
| `float` | `float` | `double` | number | |
| `bool` | `bool` | `uint8_t` | bool | |
| `enum` | `str` + `Literal` | `enum` + `_from_str`/`_to_str` | string | `values` mandatory |
| `ticks` | `int` | `int64_t` | number | Carries `tick_decimals` by convention |
| `list[T]` | `list[T]` | `T[N]` + count | array | `max_items` mandatory for C |
| `nested` | dataclass | struct | object | e.g. book levels |

`unit` is a declared enum (`display_price`, `ticks`, `shares`,
`epoch_seconds`, `epoch_nanos`, `percent`, `dimensionless`, `money`) and
appears in the generated documentation. It is *not* a conversion — declaring
that `price` is `display_price` while `trade_log.price` is `ticks` is exactly
the mismatch the statistics work spent a session untangling, and making it
declared makes it reviewable.

### 4.3 Validation vocabulary

Declared once, enforced in both languages: `required`, `default`, `gt`, `ge`,
`lt`, `le`, `max_len`, `min_len`, `pattern`, `values`, `max_items`.

Cross-field rules for the genuinely relational cases:

```yaml
    invariants:
      - rule: "price > 0 or order_type == 'MARKET'"
        message: "limit orders require a positive price"
```

Anything beyond that stays in hand-written code. The vocabulary is
deliberately small: a validation language rich enough to express the engine's
risk rules would be a second implementation of the engine.

### 4.4 Transport registry

The bus is not one socket. `docs/user-guide/270-message-reference.md` alone
distinguishes at least: order/command PUSH→PULL on `:5555`, engine PUB→SUB on
`:5556`, drop-copy PUB on `:5557`, `pm-index` PUB on a configurable address,
and `pm-log-srv` PUSH/PULL on `:5602` with its own PUB on `:5601`. A message
spec should name one of these, not restate address/pattern per message.

One `spec/transports.yaml`, referenced by name from every family:

```yaml
transports:
  engine_pub:
    pattern: PUB
    subscriber_pattern: SUB
    address_config_key: ENGINE_PUB_ADDR   # symbolic; resolved from engine_config at runtime, never hardcoded
  engine_push:
    pattern: PUSH
    subscriber_pattern: PULL
    address_config_key: ENGINE_PUSH_ADDR
  drop_copy_pub:
    pattern: PUB
    address_config_key: DROP_COPY_PUB_ADDR
  log_pub:
    pattern: PUB
    address_config_key: LOG_PUB_ADDR
  log_push:
    pattern: PUSH
    subscriber_pattern: PULL
    address_config_key: LOG_PUSH_ADDR
  index_pub:
    pattern: PUB
    address_config_key: INDEX_PUB_ADDR
  ralf:
    pattern: TCP            # post-trade dissemination gateway (pm-ralf-gwy), line protocol
    address_config_key: POST_TRADE_GATEWAY_PORT
```

The non-bus transports (`calf`, `balf`, `ralf`) are *external line/binary
protocols* fronted by their own gateway processes, not ZeroMQ endpoints; they
are named the same way so a message can list `transport: [engine_pub, calf,
ralf]` uniformly. The generator emits ZeroMQ helpers only for the bus
transports; for `calf`/`balf`/`ralf` it emits the field projection and
parse/serialise functions the gateways call (see §4.6, N1).

`pm-msgen lint` rejects a message whose `transport` entry is not one of these
names, and the generated docs table (§5.3) prints
the pattern and config key instead of a hand-typed sentence, which is what
keeps the `270-message-reference.md` "Published by" column from drifting the
way §1.3 describes.

### 4.5 Field deprecation

Removing or renaming a field is the one lifecycle event the vocabulary above
cannot express, and it is the one that will happen first the moment a real
family is migrated (§10 already documents a field, `aggressor_side`, that was
added after the fact). A field gains two optional keys:

```yaml
      - name: old_field_name
        type: string
        required: false
        deprecated_since: "1.2"
        removed_after: "1.4"     # generator refuses to remove it before this family version ships
        doc: "Superseded by new_field_name. Kept nullable for one minor version."
```

While deprecated: the field stays present and optional in the generated
Python/C/docs, `pm-msgen lint` requires a non-empty `doc`, and generated docs
move the field to a "Deprecated fields" sub-table instead of deleting it
outright. `pm-msgen check` fails the build if a field disappears from a spec
without having passed through `deprecated_since` first.

### 4.6 Per-transport field projection

This is the concept v1.0.0/1.1.0 missed and the reason the trade example was
wrong. The three client-facing encodings of a "trade" are **not the same
fields under three names** — they are three different projections of the
engine's internal payload, and this is visible directly in the code:

| Field (bus `trade.executed`) | bus (JSON) | CALF `TRADE` (`normalise_trade`) | RALF `EXEC` (`_handle_trade`) |
|---|---|---|---|
| `id` | `id` | — (not on public feed) | `EXEC_ID`, `MATCH_ID` |
| `symbol` | `symbol` | `SYM` (gateway-injected) | `SYM` (gateway-injected) |
| `buy_order_id` | `buy_order_id` | — | `BUY_ORDER_ID` |
| `sell_order_id` | `sell_order_id` | — | `SELL_ORDER_ID` |
| `buy_gateway_id` | `buy_gateway_id` | — | `BUY_GW` |
| `sell_gateway_id` | `sell_gateway_id` | — | `SELL_GW` |
| `price` | `price` | `PX` | `PX` |
| `quantity` | `quantity` | `QTY` | `QTY` |
| `aggressor_side` | `aggressor_side` | `SIDE` | `SIDE` |
| `timestamp` | `timestamp` | `TS` (gateway-injected) | `TS` (gateway-injected) |
| `tick_decimals` | `tick_decimals` | — | — |

So a projection is: **a subset of fields, each renamed, some marked as
gateway-injected rather than carried in the message body.** The spec models it
with three keys per `encoding.<transport>` block:

- `include:` — which source fields this transport carries (`all` or a list).
- `keys:` — the per-transport name for each included field. A source field may
  map to several keys (RALF's `id → [EXEC_ID, MATCH_ID]`).
- `gateway_injected:` — keys the gateway process supplies at send time
  (`CH`/`SYM`/`SEQ`/`TS`), which the generator documents and round-trips but
  does **not** source from the payload.

Two consequences the generator must enforce, checked by `pm-msgen lint`:

1. **A message may omit a transport entirely.** `trade_executed` has no `balf`
   block; `execution_report` has *only* `balf`. There is no requirement that a
   family appear on every transport.
2. **`include` may not name a field absent from `fields:`,** and every
   `required` field must be included by at least the bus transport (the
   authoritative one), or lint fails.

**Scope boundary (N1).** The generator owns the *projection and the
serialise/parse* of each transport — turning the bus payload dict into the
`{PX, QTY, SIDE}` field map and back. It does **not** own the stateful
*normalisation* around that: `md_gateway/normaliser.py` also updates a
top-of-book cache and suppresses unchanged deltas on every trade, and
`ralf_gateway` maintains per-symbol execution counts. That logic stays
hand-written; it simply calls the generated projection instead of hand-coding
the `{"PX": ..., "QTY": ..., "SIDE": ...}` literal it builds today. Drawing the
line here is what keeps the generator a message-shape tool (§2 non-goals)
rather than a second gateway.



## 5. Generated output

```
spec/messages/*.yaml
        │
        ├── src/edumatcher/models/generated/<family>.py       (Python)
        ├── docs/examples/generated/edumatcher_<family>.h/.c  (C)
        └── docs/user-guide/271-message-appendix.md           (docs)
```

All three are **committed**, so a reader browsing the repository or a student
compiling a C example never needs the generator. CI regenerates and diffs
(§7.2).

### 5.1 Python

```python
# GENERATED FROM spec/messages/trade.yaml — DO NOT EDIT
from edumatcher.models.generated._runtime import MessageValidationError

TOPIC_TRADE_EXECUTED = "trade.executed"

@dataclass(frozen=True, slots=True)
class TradeExecuted:
    id: str
    symbol: str
    buy_order_id: str
    sell_order_id: str
    buy_gateway_id: str
    sell_gateway_id: str
    price: float                    # unit: display_price
    quantity: int                   # unit: shares
    aggressor_side: Literal["BUY", "SELL", "AUCTION"]
    timestamp: float                # unit: epoch_seconds
    tick_decimals: int = 2

    def validate(self) -> None: ...          # raises MessageValidationError
    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TradeExecuted": ...
    def to_dict(self) -> dict[str, Any]: ...

def make_trade_executed(**kw: Any) -> list[bytes]:
    """Coercing + validating constructor. Returns the TWO bus frames.

    The per-topic sequence third frame is NOT added here — it is appended by
    SequencedPublisher.send_multipart() at publish time (messaging/bus.py).
    """

def make_trade_executed_unchecked(**kw: Any) -> list[bytes]:
    """Identical frames, no validate(). Measured hot paths only (§8 Phase 2)."""

def parse_trade_executed(frames: list[bytes]) -> TradeExecuted: ...
def is_trade_executed(topic: str) -> bool: ...
```

`MessageValidationError` does not exist in the tree today (the repo has
`CalfParseError`, `alf_gwy.protocol.ValidationError`,
`balf_gwy.protocol.BalfValidationError`, none of which fit). The generator
defines it **once**, hand-written and committed, in
`src/edumatcher/models/generated/_runtime.py`, subclassing `ValueError` so
existing `except ValueError` call sites keep working. Every generated family
module imports it from there rather than each declaring its own.

#### 5.1.1 Coercion and validation are different jobs (normative)

This rule is what lets the spec be strict about a field while the running
system remains tolerant of an archive written before the spec existed. It is
not an implementation detail; it is the contract:

| Function | Coerces? | Validates? |
|---|---|---|
| `from_dict(payload)` | **yes** | **no** |
| `validate()` | no | **yes** — the only strictness gate |
| `make_*(**kw)` | yes (via `from_dict`) | yes |
| `parse_*(frames)` | yes (via `from_dict`) | yes |
| `to_dict()` | no | no |

- **`from_dict` MUST NOT validate.** It performs exactly the `str()`/`int()`/
  `float()` coercion and `.get(field, default)` fallbacks the hand-written
  payload performs, and nothing else. A parser that cannot read the system's
  own archive is useless, and the migration in §8 depends on `from_dict` being
  a drop-in for the hand-written equivalent.
- **`validate()` MUST be the only place a rule is enforced**, so that a
  consumer reading historical data can choose leniency by calling `from_dict`
  alone, while every *producer* path is strict.
- **`make_*` MUST route through `from_dict`, not the dataclass constructor.**
  `Cls(**kw)` skips coercion, so `make_*(price=100)` would put an `int` on the
  wire where the hand-written factory puts a `float` — a silent wire difference
  and exactly the failure class this tool exists to remove. (Appendix A.3
  showed `TradeExecuted(**kw)`; that was a defect, corrected there.)

The practical consequence, worked through for the case that motivated the
rule. `trade.executed`'s `aggressor_side` is typed as a required `str` in
`models/trade.py` and `models/feed_schema.py`, yet five separate deserialisers
independently default it to `""` (`feed_schema.py:60`, `trade.py:113`,
`ralf_gateway/gateway.py:472`, `alf_gwy/gateway.py:935`), and
`clearing/main.py:120` then writes `trade.aggressor_side or None` to undo it.
Nobody decided `""` was legal; it accreted. Under the rule above the spec
declares the field `required: true, values: [BUY, SELL, AUCTION]` — the honest
contract — while generated `from_dict` keeps the `""` fallback verbatim. So:

- Nothing that reads history breaks.
- Every *published* message is checked, and the engine already always supplies
  a real value (`engine/order_book.py:1124`).
- `""` can never reach the generated C enum (§5.2), because C only ever sees
  the projection of a validated, published message — so no `EDU_AGG_UNKNOWN`
  sentinel has to be invented, and an accident is not exported into a second
  language and frozen in a wire contract.
- The `""` population becomes **countable for the first time**: run `validate()`
  over the clearing archive and read the failure count. Today nothing asserts,
  so nobody knows.

For parameterised topics the constants become functions, which is what removes
the 108 scattered literals:

```python
TOPIC_ORDER_ACK = "order.ack.{gateway_id}"
def topic_order_ack(gateway_id: str) -> str: ...
def match_order_ack(topic: str) -> str | None:   # returns gateway_id or None
PREFIX_ORDER_ACK = "order.ack."                  # for setsockopt(SUBSCRIBE)
```

### 5.2 C

A C struct mirrors the **transport projection** (§4.6), not the full bus
payload, because C clients speak CALF/BALF, never the internal bus. So a public
CALF trade yields a small struct — the three fields the feed actually carries —
while the BALF `execution_report` yields the full fixed-layout struct:

```c
/* GENERATED FROM spec/messages/trade.yaml (calf projection) — DO NOT EDIT */
typedef enum { EDU_AGG_BUY = 1, EDU_AGG_SELL = 2, EDU_AGG_AUCTION = 3 } edu_aggressor_side_t;

typedef struct {
    double               price;          /* PX,  unit: display_price */
    uint32_t             quantity;       /* QTY, unit: shares        */
    edu_aggressor_side_t aggressor_side; /* SIDE                     */
    /* SYM/TS are gateway-injected CALF fields, parsed into the frame envelope,
       not this message struct — see §4.6. */
} edu_trade_calf_t;

int  edu_trade_calf_parse(const calf_message_t *in, edu_trade_calf_t *out);
const char *edu_aggressor_side_to_str(edu_aggressor_side_t v);
```

```c
/* GENERATED FROM spec/messages/order.yaml (execution_report, balf) — DO NOT EDIT */
typedef enum { EDU_SIDE_BUY = 1, EDU_SIDE_SELL = 2 } edu_side_t;

typedef struct {
    uint64_t   client_order_id;
    char       order_id[17];      /* char[16] + NUL */
    double     fill_price;        /* i64 / 1e8, unit: display_price */
    uint32_t   fill_qty;
    uint32_t   remaining_qty;
    uint64_t   timestamp_ns;
    char       symbol[9];         /* char[8] + NUL — BALF symbol is 8 bytes */
    edu_side_t side;
    uint8_t    status;
} edu_execution_report_t;

int edu_execution_report_parse_balf(const uint8_t *buf, size_t len, edu_execution_report_t *out);
int edu_execution_report_validate(const edu_execution_report_t *m, char *err, size_t errlen);
```

Fixed-size buffers, no allocation, `int` returns — matching the existing
example clients' style so generated code drops in beside hand-written code.
The existing hand-written parsers use small negative-integer error codes
(`balf_parser.c`'s `parse_header`/`split_frame` return `-1`..`-5` for bad
length, bad magic, bad version, unknown `msg_type`, and length mismatch).
Generated `_parse_calf`/`_parse_balf`/`_validate` functions reuse the same
convention rather than inventing a second one:

| Return | Meaning |
|---|---|
| `0` | success |
| `-1` | frame/line too short |
| `-2` | bad magic (BALF only) |
| `-3` | bad version (BALF only) |
| `-4` | unknown `msg_type` |
| `-5` | length mismatch for this `msg_type` (BALF only) |
| `-6` | required field missing (CALF) or validation rule failed |
| `-7` | field value exceeds a fixed-size buffer (`max_len`/`max_items`) |

Codes `-6`/`-7` are new — negotiated once and then fixed, since a generated
header is a contract every hand-written C client compiles against.

**Correction (1.8.0): there was already more than one convention.** The
paragraph above cites `balf_parser.c`, whose `parse_header`/`split_frame` do
return `-1`..`-5` with exactly these meanings. But `calf_parser.c`'s
`calf_parse_line` also returns `-1`..`-6`, with entirely unrelated ones:

| Code | `calf_parse_line` | generated functions |
|---|---|---|
| `-1` | null argument | frame/line too short |
| `-2` | no first token | bad magic (BALF) |
| `-3` | invalid `MSGTYPE` | bad version (BALF) |
| `-4` | too many fields | unknown `msg_type` |
| `-5` | field token without `=` | length mismatch (BALF) |
| `-6` | empty field key | required field missing / rule failed |

So "reuse the convention rather than invent a second one" was already false when
written. Two things follow, and both are normative:

1. **A return code is a per-function contract, not a global registry.** The
   table in this section defines what the *generated* functions return. It does
   not redefine `calf_parse_line`, which keeps its own codes. A caller checks
   each call's result against the function it called — which is what callers do
   anyway, since the two are invoked in sequence on different arguments.
2. **Every generated family emits a `strerror`.** Because a bare `-4` is now
   genuinely ambiguous to a reader scanning a log, the generator emits
   `const char *edu_<family>_strerror(int rc)` returning a human-readable
   string. Generated code should be printed with it rather than as a number:

   ```c
   int rc = edu_trade_executed_calf_parse(&msg, &trade);
   if (rc != 0) {
       fprintf(stderr, "TRADE parse failed: %s\n", edu_trade_strerror(rc));
       return;
   }
   ```

Renumbering the generated codes into a disjoint range (`-20`..`-27`) was
considered and rejected: the generated BALF parser reimplements exactly what
`split_frame` does, and giving the same failure a different number in the
generated version would be its own kind of confusion.

### 5.3 Documentation

A generated `271-message-appendix.md` in the existing chapter's table style:
motivation and transports (with each transport's pattern and config key taken
from the registry, §4.4 — there is no `direction`/`publisher` field in the
spec; both are derived), then the field table with type, unit, required,
constraints and description, then one worked example per
*declared* transport (bus JSON, a CALF/RALF line, or a BALF hexdump) — only the
transports the message actually appears on (§4.6), so a public-feed message
shows no BALF example and an order-entry message shows no bus example.

The existing hand-written `270-message-reference.md` stays. It carries the
narrative — sequence diagrams, subscription tables, protocol walkthroughs —
that no generator should attempt. The appendix carries the mechanical field
detail that currently rots.

`mkdocs.yml`'s `nav` is a hand-maintained explicit list (it is today, for
every existing page under `user-guide/`) — it is **not** auto-discovered from
the directory. A generated `271-message-appendix.md` that isn't also added to
`nav` builds silently and is unreachable from the rendered site. `pm-msgen
generate` therefore also inserts/updates the single `nav` line for the
appendix (idempotently, keyed on the file path), and `pm-msgen check` fails if
the appendix file exists on disk but its `nav` entry does not match.


## 6. Helper surface

Generated per family, so no consumer hand-writes them:

| Helper | Purpose |
|---|---|
| `topic_*()` / `PREFIX_*` | Build and subscribe without literals |
| `match_*(topic)` | Extract the parameter, or `None` |
| `parse_*(frames)` | Frames → typed object, coerced **and** validated |
| `make_*(**kw)` | Coerced + validated construction → frames |
| `make_*_unchecked(**kw)` | Same frames, no `validate()`. Hot paths only (§8 Phase 2) |
| `to_dict` / `from_dict` | Interop with existing dict-based code. `from_dict` **coerces only** — see §5.1.1 |
| `validate()` | Standalone, the only strictness gate (§5.1.1) |
| `FAMILY_TOPICS` | Registry for routers and spy tools |
| `describe_*()` | Field metadata at runtime, for `pm-*-spy` pretty-printing |



## 7. Tooling and build integration

### 7.1 The generator

`src/edumatcher/msgen/` — following the same convention as every other
free-standing CLI in this repo (`cverifier`, `config_gen`, `audit`): a package
under `src/edumatcher/`, registered as a `[tool.poetry.scripts]` entry
(`pm-msgen = "edumatcher.msgen.cli:main"`), with tests under
`tests/test_msgen_*.py`. It carries no *runtime* dependency from the engine or
gateways (nothing under `edumatcher/engine`, `alf_gwy`, etc. imports it) —
only the generated output in `models/generated/` and `docs/examples/generated/`
is a runtime dependency, and those are committed, ordinary, hand-reviewable
Python/C files.

Code generation needs no new dependency (open question 6, resolved in 1.5.0 —
see §12.5). Templates are hand-rolled string assembly; spec parsing reuses the
`pyyaml` dependency already in `[tool.poetry.dependencies]`. There is therefore
**no `[tool.poetry.group.msgen.dependencies]` group**, and no change to
`poetry install --with dev,docs`.

```bash
pm-msgen generate --spec spec/messages --out-python src/edumatcher/models/generated \
                  --out-c docs/examples/generated --out-docs docs/user-guide
pm-msgen check                 # regenerate to temp, diff against committed
pm-msgen lint                  # spec-only: missing units, undocumented fields, cross-family collisions
```

### 7.2 The guarantee

`pm-msgen check` in CI is the whole point. It regenerates into a temporary
directory and diffs. Any of the following fails the build:

- a spec change without regenerating
- a hand-edit to a generated file
- documentation (including the `mkdocs.yml` nav entry, §5.3) drifting from the spec

This only works if generation is **deterministic**: byte-identical output for
an unchanged spec, run twice, on any machine. That means sorted dict/field
iteration (not insertion order of a `set`), no wall-clock timestamps or
absolute paths in the `DO NOT EDIT` banner, and stable enum-value ordering.
This requirement is not optional — a generator that occasionally reorders its
own output turns `pm-msgen check` into a source of flaky CI failures, which is
worse than not having the check at all.

Without the check, the generator is merely a scaffolder and §1 recurs within a
release. With it, the three surfaces are provably identical.

The real `Makefile` names its checks `format` (black), `lint` (flake8),
`typecheck` (mypy), `typecheck-pyright` (pyright), aggregated under `_check`;
`ci.yml` runs the equivalent `poetry run` commands directly rather than
through `make`. Add a matching target and wire it into both:

```make
# Makefile — stamp-cached like the other checks, on spec/*.yaml + src/**/*.py
msgen-check: $(MSGEN_STAMP)
_check: format lint typecheck typecheck-pyright msgen-check
```

```yaml
# .github/workflows/ci.yml, alongside the existing black/flake8/mypy steps
- name: Message spec drift check
  run: PYTHONPATH=src poetry run python -m edumatcher.msgen.cli check
```

**The CI invocation is not `poetry run pm-msgen check`, and that matters.**
v1.6.0 of this document said it was. The `code-check` job passes
`install-root: 'false'` to the shared setup action, which becomes
`poetry install --no-root`: dependencies are installed, the project itself is
not, and therefore none of its `[tool.poetry.scripts]` console scripts exist on
`PATH`. `poetry run pm-msgen check` fails there with `command not found` — which
looks like a broken tool rather than a missing regeneration, and would most
likely be "fixed" by deleting the step. Invoking the module with `PYTHONPATH=src`
works because `pyyaml`, the only thing the generator needs, is a main
dependency. `tests/test_msgen_ci_wiring.py` asserts this so the next person to
tidy that workflow finds out from a test rather than from a red build.

The `make` path has the opposite constraint: it runs against a fully installed
environment, so the console script is the right thing to use there.

### 7.3 Spec linting

`pm-msgen lint` catches what generation alone cannot: a field without a `unit`,
a `string` without `max_len` (which would break C generation), an enum without
`values`, a message without a `doc.motivation`, a topic parameter not present
in the field list, and — across the whole `spec/messages/` tree, not just one
file — the same topic string declared in two families, or two `transport`
entries pointing at a transport name absent from `spec/transports.yaml` (§4.4).

### 7.4 Migration helper

"Replace 108 literals across 25 files" (§8, Phase 5) is not a step a design
document can hand-wave; it needs a way to know when it is done. `pm-msgen
grep-literals` re-runs the same scan behind the counts in §1 — every quoted
string outside `models/generated/` and `models/message.py` matching a topic
pattern declared in `spec/messages/` — and lists remaining hits with
file:line. Each specified family should drive its count in that report to
zero before Phase 5 calls the family migrated; the report itself is the
acceptance check, not a manual `grep`.

### 7.5 Parsing and diagnostics — the way forward

The IDL is designed to be parsed into a typed AST with compiler-grade error
messages. The key realisation is that **the outer syntax is YAML**, so there is
no hand-written scanner for the file as a whole — `pyyaml` is the lexer and
parser. The parsing work splits into two layers, and only the second is a
purpose-built scanner. The existing `pm-cverifier` is the template for all of
it: the same coded-diagnostic model, the same layered gating.

#### 7.5.1 Two-layer architecture

**Layer A — outer structure (YAML → typed AST).** Load with `yaml.compose()`,
**not** `yaml.safe_load()`. `compose()` returns a node tree in which every
scalar, mapping and sequence carries `start_mark`/`end_mark` (line *and*
column). A recursive descent over that tree builds the AST of §B.19
(`Family`/`Message`/`Field`/…), attaching a `Span(line, col, end_line, end_col)`
to every AST node. This is the one deliberate upgrade over `cverifier`, which
loads with `safe_load` (`layer1_yaml.py`) and therefore has a line number only
for YAML *parse* errors (its `Y003`, read from `exc.problem_mark`) and nothing
for *semantic* errors. Preserving marks is what lets "unknown key `requird`"
point at `file:line:col` instead of "somewhere in this file".

**Layer B — embedded string sub-languages (a real scanner).** Four constructs
are opaque strings to YAML and need their own tokeniser to give
column-accurate errors *inside* the string. In descending order of how much
they benefit:

- **invariant expressions** (§B.15): `price > 0 or order_type == 'MARKET'` — a
  lexer feeding a small Pratt/recursive-descent parser that yields an
  expression AST. The §B.15 EBNF is exactly what it implements.
- **`type` expressions**: `list[list[int]]`, `nested` — a ~20-line recursive
  tokeniser.
- **`repr`**: `char[16]` — trivial.
- **topic patterns**: `order.ack.{gateway_id}` — a segment scanner that also
  yields the `{param}` list used by §B.18 rule 3.

Each embedded scanner reports offsets *within* its string; adding the enclosing
YAML node's `start_mark` promotes that to a file-absolute `file:line:col`
pointing at the exact character.

#### 7.5.2 The diagnostic model (reuse, don't reinvent)

Reuse `cverifier`'s types verbatim in spirit: a `Diagnostic` mirroring
`CheckResult(code, severity, message, suggestion, path, context)` plus a
`Severity` enum, rendered by a formatter of the same shape. Add one field the
config verifier does not need: a `Span` (from §7.5.1) so the renderer can print
a caret/underline snippet.

```python
@dataclass(frozen=True)
class Span:
    line: int
    col: int
    end_line: int
    end_col: int

@dataclass(frozen=True)
class Diagnostic:
    code: str                 # e.g. "G201", "V007" — namespaced (§7.5.4)
    severity: Severity        # ERROR | WARN | INFO
    message: str
    span: Span | None
    suggestion: str = ""      # "did you mean 'required'?"
    path: str = ""            # dotted spec path, e.g. messages[2].fields[0].validate
```

#### 7.5.3 Layered gating (never emit noise from a half-parsed file)

Run the same skip-on-earlier-failure discipline `cverifier` uses:

1. **Syntax (YAML).** `compose()` fails → one `Y###` diagnostic, stop.
2. **Shape (AST build).** Unknown keys, wrong node kinds, missing required
   keys, malformed `type`/`repr`/topic/expression strings → `G###`. All shape
   errors in the file are collected, not fail-on-first (see 7.5.5).
3. **Semantic (single family).** The 15 rules of §B.18 → `V###`, one code per
   rule (V001…V015 map 1:1 to B.18.1…B.18.15).
4. **Cross-family.** Duplicate topics / `msg_type` bytes / transport references
   across the whole `spec/messages/` tree (§7.3) → `X###`.

A later layer runs only if the earlier one produced no `ERROR`, so a mistyped
key never spawns a cascade of misleading semantic errors.

#### 7.5.4 Diagnostic code namespace

Mirror `cverifier`'s letter+number scheme so the two tools feel identical:

| Prefix | Layer | Examples |
|---|---|---|
| `Y###` | YAML syntax | `Y003` parse error (reused wording) |
| `G###` | grammar / AST shape | `G101` unknown key, `G102` wrong value type, `G120` bad `type` expression, `G121` bad `repr`, `G130` malformed invariant expression |
| `V###` | semantic (§B.18) | `V001` unknown transport … `V015` unknown key rejected (one per B.18 rule) |
| `X###` | cross-family | `X001` duplicate topic, `X002` duplicate BALF `msg_type` |

Every code is documented once in a table in the generated docs, so an error
message can end with "see `V007`" and a reader can look it up — the pattern the
statistics and config-verifier work already established.

#### 7.5.5 What makes the errors *excellent* (concrete requirements)

- **Every diagnostic carries a `Span`** (7.5.1). Non-negotiable; it is what the
  rest depends on.
- **Multiple errors per run.** Layers 2–4 collect a list and continue rather
  than raising on the first. The expression parser recovers by inserting an
  error node and resuming at the next operator, so one bad invariant yields one
  diagnostic, not a truncated parse.
- **"Did you mean …?"** For every closed vocabulary — field keys, `type`
  values, `unit` values, enum `values`, transport names — compute Levenshtein
  distance to the allowed set and suggest the nearest when distance ≤ 2. The
  strict-loader rule (§B.18.15) becomes `G101: unknown key 'requird' — did you
  mean 'required'?`.
- **Caret snippets.** With `start`/`end` marks the renderer prints the source
  line and underlines the exact span, rustc/ruff-style:

  ```
  error[G101]: unknown key 'requird'
    --> spec/messages/order.yaml:14:9
     |
  14 |       - { name: reason, requird: false }
     |                         ^^^^^^^ did you mean 'required'?
     |
  ```

- **Stable dotted `path`.** `messages[2].fields[0].validate` so a diagnostic is
  greppable and testable independent of line numbers.

#### 7.5.6 The invariant expression parser (the one real scanner)

Recommended: a hand-written ~50-line Pratt parser, no dependency. It stays
inside R2 ("small vocabulary, no Turing-complete rules") and matches open
question 6's hand-rolled-vs-library trade-off. The token set is tiny —
identifiers, number/string/bool literals, the six relational operators,
`and`/`or`, and parentheses — and the grammar is already written in §B.15.
`Lark` is a reasonable alternative *only* for this sub-language if a declarative
grammar is preferred; it must not be introduced for the outer (YAML) layer,
which the design keeps deliberately (§3). The parser resolves each
`field-name` against the message's declared fields at parse time, so an unknown
field in an invariant is a `G130` with a caret on the identifier, not a runtime
`KeyError` later.

#### 7.5.7 Placement and effort

This is the `spec.py` loader of §A.2 built properly (`compose`-based, span-
carrying) plus a small `expr.py`, both under `src/edumatcher/msgen/`, feeding
`pm-msgen lint`. The diagnostic renderer is a near-copy of
`cverifier/formatter.py`. The genuinely *new* code is the mark-preserving AST
builder and the expression scanner; everything else — the `Diagnostic` shape,
severities, layered reporting, suggestions, the `V###` rule list — is either
already shipped in `cverifier` or already specified in §B.18. It is therefore a
low-risk build, and a good Phase-1 stretch goal once the generator itself
(§A.5) is green.



## 8. Phased adoption

92 factories cannot move at once, and there is no reason to. Each phase is
independently shippable and independently verifiable.

### Phase 1 — Generator, one family, no adoption

Build `src/edumatcher/msgen/` (§7.1). Specify `trade.yaml` only. Generate all
three outputs. Commit them **unused**.

*Test:* generated `TradeExecuted.from_dict` accepts every payload the existing
`TradeExecutedPayload` accepts, and produces byte-identical `to_dict()` output.
Property test over generated payloads.

*Ships:* nothing user-visible. The generator proves itself against a message
that already has a hand-written typed equivalent.

### Phase 2 — Adopt for one family

`make_trade_msg` becomes a thin shim over `make_trade_executed`.
`engine/main.py::_publish_trade` adopts `make_trade_executed_unchecked`.
`pm-stats` adopts the generated **topic constant** — but deliberately not the
validating parser; see §8.1 below for why, and §8.2 for what the hot path cost.

*Test:* the entire existing suite passes unchanged — that is the acceptance
criterion. Plus a wire-compatibility test asserting **two claims of different
strength**, because the system has two producers with two different contracts:

| Comparison | Assertion | Why this strength |
|---|---|---|
| `make_trade_msg` vs `make_trade_executed` | **byte-identical frames** | Both derive from `to_dict()`. There is no excuse for a difference. |
| `engine/main.py::_publish_trade`'s inline dict vs `make_trade_executed` | **equal key sets and equal parsed payloads** | `_publish_trade` emits `tick_decimals` between `price` and `quantity`; `to_dict()` emits it last. Nothing on the wire cares — JSON objects are unordered and every consumer uses `.get` — so byte-identity here is *stronger than the system's actual contract* and would block a legitimate change. |

v1.4.0 asserted byte-identity for both. That was wrong in one direction and
would have pushed the fix in the wrong direction too: matching the spec's field
order to `_publish_trade`'s would let an incidental artefact of one hand-written
call site dictate the canonical field order forever.

**`make_*_unchecked` is a Phase 2 requirement, not a later optimisation.**
Open question 4 proposed generating a non-validating constructor for measured
hot paths and deferred the decision. For `trade` it cannot be deferred, because
of §12.2: `make_trade_msg` has **no production callers** — the only references
are in `tests/`. The real producer is the inline dict literal in
`engine/main.py:2140-2162`. Adopting only `make_trade_msg` would therefore
adopt the generator into code that never runs in anger: `pm-msgen check` goes
green, the engine keeps hand-writing the dict, and the generator has not
removed the drift for this family — it has added a *fourth* place a trade is
described.

So Phase 2 for a family whose producer is on a hot path MUST generate both
`make_<msg>` (validating) and `make_<msg>_unchecked` (identical field order and
serialiser, no `validate()` call), and MUST convert the producer. The
substitution is mechanical — `_publish_trade` already does
`send_multipart([_TRADE_TOPIC, dumps({...})])` and the unchecked function
returns exactly `[topic_bytes, dumps(...)]` — but it does mean **Phase 2 touches
the engine's hot path, which is higher-risk than this section implied at
v1.4.0.** Mitigation: the byte-identity test above, plus a `perf`-marked test
asserting the unchecked path costs no more than the inline literal.

*Ships:* one family, provably wire-compatible, with the *actual* producer
generated.

#### 8.1 A recorder must not validate (correction, found during Phase 2)

v1.5.0 said "`pm-stats` parses with the generated parser". Implementing it
showed that to be wrong, and the reason generalises to every consumer of this
kind.

`stats/main.py::_on_trade` is deliberately tolerant, in three separately
documented ways:

| Tolerance | Where | Why it is there |
|---|---|---|
| Returns early when `symbol`/`price`/`quantity` is missing | `_on_trade` head | a partial print is skipped, not fatal |
| Falls back to receipt time when `timestamp` is absent, with a warning | `_on_trade` | the row is still worth recording |
| Accepts a non-numeric `id`, disabling gap detection with one warning | `_check_trade_sequence` | "a synthetic or gateway-supplied id" is an expected input |

`parse_trade_executed` validates, so adopting it would make pm-stats **raise**
on a non-numeric `id`, on `aggressor_side == ""`, and on a non-positive price —
inputs the recorder currently handles on purpose. Even `from_dict` is stricter
about *presence* than `_on_trade` is: it raises `KeyError` where `_on_trade`
returns early or warns.

The principle: **a recorder records what it received.** Refusing to store a
message because it fails the current spec destroys exactly the evidence needed
to find out why it was malformed. Validation belongs on the *producer* side and
at trust boundaries, which is what §5.1.1 already says — `parse_*` is for a
consumer that would rather fail than act on a bad message, and a statistics
recorder is not one.

So pm-stats adopts `TOPIC_TRADE_EXECUTED` in place of its two `"trade.executed"`
literals (`TRADE_STREAM` and the dispatch test). That is a real gain against
§1.2 — a topic rename in the spec now reaches the recorder — at zero behavioural
risk. Its payload handling stays hand-written and tolerant.

**The general rule for Phase 5:** adopt the *topic constants* everywhere, and
adopt `parse_*` only where the consumer genuinely wants to reject a
non-conforming message. Do not assume every subscriber wants validation.

#### 8.2 `make_*_unchecked` had to be reshaped (correction, found during Phase 2)

As generated in Phase 1, `make_*_unchecked` routed through
`from_dict` → dataclass → `to_dict` → `encode`. Measured on `trade`
(200 000 iterations, `orjson`):

| Construction | µs/call | vs. the hand-written literal |
|---|---|---|
| `engine/main.py`'s inline dict + `dumps` | 0.96 | — |
| generated, dict literal, no coercion | 1.12 | +0.16 |
| **generated, dict literal, inline coercion** | **1.47** | **+0.50** |
| generated, via `from_dict`/dataclass/`to_dict` | 4.03 | +3.08 |

Two conclusions:

1. **The Phase 1 shape was unusable.** `perf-notes.md` records publication
   optimisations worth 0.2–1.0 µs each; +3.1 µs would undo all of them several
   times over. A constructor whose stated purpose is "measured hot paths only"
   cannot be four times slower than the code it replaces. `make_*_unchecked` is
   therefore generated as explicit keyword-only typed parameters building the
   payload dict literal directly, with the topic pre-encoded at import — the
   same optimisation the engine's own `_TRADE_TOPIC` was.
2. **Coercion stays, and the 0.34 µs is paid.** Dropping it is nearly free but
   makes `make_*_unchecked(price=100)` put an int on the wire where `make_*`
   puts a float. mypy does **not** catch this — `int` is promotable to `float`
   in the type system — so it would be a silent wire divergence between two
   functions documented as producing identical frames. That is the failure class
   in §1; paying 0.34 µs to keep it impossible is the whole point of the tool.

`make_*` (validating) keeps the `**kw: Any` + `from_dict` route: its callers
have a dict of uncertain provenance, which is exactly what `from_dict` is for,
and it is not on a hot path.

### Phase 3 — CI drift check

Add `pm-msgen check` to the Makefile and CI.

*Test:* deliberately edit a generated file; the check fails. Deliberately edit
a spec without regenerating; the check fails.

*Ships:* the guarantee. From here drift cannot be reintroduced for specified
families.

### Phase 4 — C generation adopted

Split into **4a (text/CALF)** and **4b (binary/BALF)** in 1.8.0. The two share
almost no emitter code — one produces `strtod`/`strcmp` over a key-value bag,
the other fixed-offset `memcpy` over a byte frame — and binary is where R4
(buffer truncation) and R7 (layout change breaks deployed clients) live. Each
half is independently shippable and independently verifiable, which is the rule
§8 applies to everything else.

#### Phase 4a — text projection and C structs for CALF

Spec gains a `calf:` encoding for `trade_executed`. The generator emits: the
Python projection (`project_*_calf` / `parse_*_calf`), and a C header + impl
with a typed struct, an enum with `to_str`/`from_str`, a parser over
`calf_message_t`, a validator, and `strerror`.

Adopted in two places: `md_gateway/normaliser.py::normalise_trade` builds its
field map through the generated projection instead of a dict literal, and
`calf_subscriber.c`'s TRADE handler reads the typed struct instead of
`calf_get_field` plus per-field conversion.

*Test:* the generated C compiles and a round-trip harness — Python projects a
payload, writes the CALF line, the compiled C parses it, and the values are
compared field by field — proves the two bindings agree on the wire. This is
capstone assertion 4 at one message's scale.

#### Phase 4b — binary layout for BALF

`execution_report`, with the full `layout`/`repr`/`offset`/`scale`/`enum_map`
machinery, in `spec/messages/order.yaml` (see below). Capstone assertion 5.

#### Corrections in 1.8.0

**The stated acceptance test was unwritable.** v1.7.0 said "a golden-file test
asserts the generated parser produces the same struct as the hand-written one
for a captured message corpus". There is no hand-written struct to compare
against — §1.4 is precisely the observation that *the C surface has no message
types at all*. The comparison that exists, and the one that matters, is
**generated C against generated Python**, which is what the capstone always
specified. The golden-corpus wording is replaced by the round-trip above.

**`execution_report` belongs to `order`, not `trade`.** §4.1 shows it inside
`trade.yaml`; §5.2's banner says `spec/messages/order.yaml`. The banner is
right: it is a private per-order fill sent to one gateway session, not a public
trade print, and filing it under the family named for public prints would
reproduce in the spec exactly the conflation §4.6/R13 warns against. Phase 4b
creates `order.yaml` containing only this message; Phase 5 fills in the rest of
the family. §4.1's placement is illustrative and is marked as such.

**No `cffi`, no `msgen_c` marker, no CI toolchain step.** A.7 proposed a cffi
harness and the capstone proposed a marker plus an `apt-get install
build-essential` step. All three are unnecessary: `cffi` is not a dependency
and adding one contradicts §12.5's reasoning; `tests/test_alf_examples.py`
already establishes this repository's pattern for compiled tests —
`shutil.which("cc")`, `subprocess`, and `pytest.skip` when the toolchain is
absent — which needs no marker because it self-skips; and `ubuntu-latest` ships
a C compiler, so nothing needs installing. R11 is closed by using the pattern
that already works here rather than importing one that does not.

*Ships:* C clients gain typed structs; a field rename now reaches them.

### Phase 5 — Remaining families, incrementally

Order-of-value: `order.*` (largest and most duplicated), then `book`/`depth`,
`session`, `risk`, `index`, `log`. One family per change, each with its
wire-compatibility test.

*Ships:* per family. Any family not yet specified keeps working exactly as
today.

### Phase 6 — Documentation appendix

Generate `271-message-appendix.md`; prune the mechanical field tables from
`270` where duplicated, leaving the narrative.

*Ships:* the documentation stops rotting.

### Capstone

`tests/test_msgen_roundtrip.py::test_every_message_survives_its_declared_transports`

For every message in every spec, over generated random payloads, and **only
for the transports that message declares** (§4.6 — a message need not appear on
all transports):

```
For a bus message (engine_pub / engine_push / ...):
  1. make_*(**payload)               -> frames
  2. parse_*(frames)                 -> object   == payload
For each declared text transport (calf / ralf):
  4. project -> serialise line -> C parse -> compare   == projection  (cffi)
For each declared binary transport (balf):
  5. serialise frame -> C parse -> compare             == payload      (cffi)
Always (every message has a Python reference binding):
  3. to_dict -> from_dict            -> object   == payload
  6. every validate() rule rejects an out-of-range mutation of each field
  7. generated docs list exactly the fields in the spec, no more, no fewer
  8. pm-msgen check reports no drift
```

Assertions 4 and 5 are the ones that matter: they prove the Python and C
bindings agree on the wire, which is the property no current test can state.
Because they compare against the transport's *projection* (§4.6), not the full
bus payload, a CALF trade round-trips `{PX, QTY, SIDE}` while a BALF
execution_report round-trips its own fields — neither is forced to carry the
other's.

They require a C compiler at test time. **No CI change and no marker are needed
for that** (corrected in 1.8.0): `tests/test_alf_examples.py` already compiles
and runs C from the suite using `shutil.which("cc")` plus `pytest.skip`, so the
test self-skips where no toolchain exists and needs no `-m` selector; and
`ubuntu-latest` ships a compiler, so there is nothing to `apt-get install`.
Using the pattern already proven in this repository closes R11 without adding a
dependency, a marker, or a workflow step.



## 9. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | Generated output silently diverges from hand-written behaviour during migration | **High** | Phase 2 byte-identical wire test per family; no family adopted without it |
| R2 | Generator becomes a second system to maintain | Medium | Deliberately small vocabulary (§4.3); no Turing-complete rules; ~1 500 lines projected |
| R3 | Spec expressiveness runs out mid-migration | Medium | Phase 5 is per-family, so an unspecifiable family simply stays hand-written; the generator is opt-in per message |
| R4 | C fixed-size buffers truncate a longer field | **High** | `max_len` mandatory for C targets; `lint` enforces; generated parser returns an error rather than truncating |
| R5 | Committed generated files make review noisy | Low | Generated files carry a `DO NOT EDIT` banner and live in `generated/` directories; reviewers read the spec diff |
| R6 | Enum drift between Python and C | Medium | Both generated from the same `values`; capstone assertion 4/5 compares round-trips |
| R7 | Binary layout changes break deployed C clients | **High** | `family.version` in the spec pins the *logical* layout; note the BALF wire header carries a **single global** version byte (`0x01`) shared by all messages, so the generator must refuse a layout change unless either the family version bumps *and* a compatibility note is written, or the global BALF version is bumped deliberately — the two are not the same knob |
| R8 | Two engineers edit the same generated file from different specs | Low | `pm-msgen check` in CI catches it before merge |
| R9 | Non-deterministic generation (dict/set iteration order, timestamps) makes `pm-msgen check` flaky, undermining the one guarantee that matters | **High** | §7.2 makes reproducibility an explicit requirement, tested by running `generate` twice and diffing |
| R10 | Generated `271-message-appendix.md` ships but isn't wired into `mkdocs.yml` nav (§5.3), so it never appears in the built docs | Medium | `pm-msgen check` also validates the nav entry, not just the file content |
| R11 | CI capstone C round-trip tests (assertions 4/5) need a C toolchain not currently installed in `ci.yml` | Low | Marker-gated test + toolchain install step added only to the job that needs it |
| R12 | Generator creep into stateful normalisation (top-of-book cache, exec counts) it cannot own | Medium | §4.6 (N1) fixes the scope boundary: generator owns projection + parse/serialise only; `md_gateway/normaliser.py` and `ralf_gateway` keep their business logic and call the generated projection |
| R13 | Same logical event modelled as one message across transports when the field sets genuinely differ (public trade vs private fill) | **High** | §4.6 projection model; `trade_executed` and `execution_report` are separate messages by design, not one message forced onto BALF |



## 10. What this would have prevented

Grounding the value in defects this repository actually produced:

- `book.{SYMBOL}` gained `tick_decimals` in the corporate-actions groundwork.
  Three surfaces needed the edit; the C clients were never going to get it.
- The `trades` CLI example output lost a column when `aggressor_side` was
  added, caught only by a later manual audit.
- Eight topics constructed in code are absent from the reference (§1.3).
- `EodBookPayload.from_dict` silently dropped `tick_decimals` because the typed
  payload had not been updated alongside the producer — found only by tracing
  the field through by hand.

Every one is a mechanical inconsistency between surfaces, which is exactly the
class a generator removes and a reviewer does not reliably catch.



## 11. Open questions

1. **Spec granularity** — one file per family (proposed) or one per message?
   Families keep related enums together; per-message files diff more cleanly.
2. **Should `models/feed_schema.py` be generated first?** It is the smallest
   surface (7 payloads), already typed, and already has clearing depending on
   it — arguably a better Phase 1 than `trade.yaml` alone.
3. **BALF layout ownership.** The spec would become authoritative for the
   binary layout, which currently lives in `910-app-balf-protocol.md` and the
   example parser. Migrating it is valuable but makes Phase 4 larger.
4. ~~**Runtime validation cost.**~~ **Resolved in 1.5.0 — promoted to a Phase 2
   requirement.** Generate both `make_*` (validating) and `make_*_unchecked`
   (not), and convert the hot-path producer to the latter. This is no longer
   optional for a family whose producer is on a hot path, because otherwise the
   family's real producer stays hand-written and the adoption is cosmetic
   (§8 Phase 2, §12.2).
5. **Versioning across the wire.** `family.version` covers layout changes, but
   there is no negotiation today. Out of scope here; worth its own note if
   external clients are ever versioned independently.
6. ~~**Templating engine choice.**~~ **Resolved in 1.5.0: hand-rolled, no new
   dependency.** See §12.5. §7.1's `[tool.poetry.group.msgen.dependencies]`
   block is therefore not added; `pyyaml` (already a runtime dependency) is the
   only thing the generator needs.
7. **Spec-file JSON Schema.** `pm-msgen lint` (§7.3) validates spec semantics,
   but nothing validates the YAML *shape* itself (e.g. a typo'd key like
   `requird: true`) before that. Worth deciding whether `lint` also loads a
   checked-in JSON Schema for the spec format, or whether the loader's own
   dataclass parsing is considered sufficient (it will reject unknown keys
   only if it is written strictly, which should be stated as a requirement).



## 12. Grounding notes for the corrections in 1.5.0

Each correction listed at the top of this document came from checking a v1.4.0
claim against the tree. Recorded here so a later reader can re-verify rather
than re-derive.

### 12.1 `aggressor_side` is undecided, not defaulted

| Site | Code |
|---|---|
| `models/trade.py:45` | `aggressor_side: str` — required, no default |
| `models/feed_schema.py:45` | `aggressor_side: str` — required, no default |
| `models/trade.py:113` | `d.get("aggressor_side", "")` |
| `models/feed_schema.py:60` | `str(payload.get("aggressor_side", ""))` |
| `ralf_gateway/gateway.py:472` | `str(payload.get("aggressor_side", ""))` |
| `alf_gwy/gateway.py:935` | `str(payload.get("aggressor_side", ""))` |
| `clearing/main.py:120` | `trade.aggressor_side or None` — undoes the `""` |
| `engine/order_book.py:1124` | always assigns a real value, never `""` |

The type says the field is required; four deserialisers say `""` is expected;
one consumer converts `""` back to `NULL`. No single site is wrong and the set
is incoherent. §5.1.1 resolves it by separating coercion from validation rather
than by picking one of the two existing answers.

### 12.2 `make_trade_msg` has no production callers

```
$ grep -rn "make_trade_msg" --include=*.py . | grep -v '^./tests/'
./src/edumatcher/models/message.py:284:def make_trade_msg(...)   # the definition
```

Only `tests/test_messages.py` and `tests/test_clearing_main.py` call it. The
same scan finds six further `make_*` factories with no `src/` caller
(`make_position_request_msg`, `make_log_subscribe_msg`, `make_log_renew_msg`,
`make_log_unsubscribe_msg`, `make_log_backfill_request_msg`,
`make_log_status_request_msg`) — noted, not touched; whether they are dead or
merely externally-facing is a separate question this work does not answer.

The consequence for §8 Phase 2 is in that section. The consequence for §1's
framing is worth stating too: the "92 `make_*` factories are the de-facto
publisher API" claim is *approximately* right but not uniformly so, and the
engine's hot path is exactly where it is least true.

### 12.3 The two trade producers disagree on key order

`engine/main.py:2146-2160` emits
`id, symbol, buy_order_id, sell_order_id, buy_gateway_id, sell_gateway_id,
price, tick_decimals, quantity, aggressor_side, timestamp`.

`feed_schema.TradeExecutedPayload.to_dict()` (`:66-78`) emits the same eleven
keys with `tick_decimals` **last**.

Both are valid JSON for the same logical message and every consumer uses
`.get`, so no consumer can tell. Only a byte-comparing test can — which is why
§8 Phase 2 now states two assertions of different strength instead of one.

### 12.4 Claims that checked out

Recorded so they are not re-investigated:

- §4.6's CALF projection table matches `md_gateway/normaliser.py:191-210`
  exactly: `normalise_trade` emits `{PX, QTY, SIDE}` and nothing else.
- §4.6's RALF projection matches `ralf_gateway/gateway.py:452-478`, including
  `id` feeding both `EXEC_ID` and `MATCH_ID`.
- §4.1's BALF `execution_report` layout matches
  `docs/examples/balf/balf_parser.py:139-161` byte-for-byte: `frame_size 72`
  = `FRAME_SIZES[0x20]`, 64-byte body, offsets 0/8/24/32/36/40/48/56/57,
  `PRICE_SCALE = 100_000_000`, `magic 0xBA`, `version 0x01`.
- §4.1's note that `encode()` returns two frames and `SequencedPublisher` adds
  the third matches `models/message.py:69-71` and `messaging/bus.py:42-72`.
- §7.1's claim that `pyproject.toml` has only `dev` and `docs` groups, and no
  Jinja2 or pydantic, holds.
- The capstone's warning about `--strict-markers` holds: `markers` registers
  only `perf`, so `msgen_c` must be added before any marked test is collected.
  (`addopts` additionally deselects `heavy`, `probabilistic` and
  `probabilistic_full`, none of which is registered — pre-existing, noted, not
  changed here.)

### 12.5 Open question 6 decided: hand-rolled templates

Phase 1 emits Python only, which is a few hundred lines of `str.join` over a
field list. Jinja2 would add a dependency group *and* a whitespace-control
problem in exchange for nothing at this size, and §B.17's byte-for-byte
determinism requirement is easier to audit in plain Python than in a template.
Revisit at Phase 4 if the C emitter grows unwieldy; that is a local decision
inside `generators/`, not a change to the spec model.

## 13. Where the intent stands after Phase 2

§1 opened by measuring the problem. This section measures the progress against
it honestly, including where the answer is "not yet". Written after Phases 1
and 2 shipped and updated for Phase 3; update it after each subsequent phase.

### 13.1 Against the §2 goals

| # | Goal | Status |
|---|---|---|
| 1 | One canonical file per family; everything else generated | **partial** — true for `trade`; 1 family of ~15 specified |
| 2 | Generated Python: typed payload, validating constructor, parser, topic constant | **done**, plus `describe_*`, `FAMILY_TOPICS`, `make_*_unchecked`, `project_*`/`parse_*_calf` |
| 3 | Generated C | **text done (4a)** — typed struct, enum + `to_str`/`from_str`, parser, validator, `strerror`; binary is 4b |
| 4 | Generated documentation appendix | not started (Phase 6) |
| 5 | Validation declared once, enforced by *both* bindings | **done for CALF** — `price > 0` and `quantity > 0` are enforced in Python and in C from one declaration, and a test asserts the two reject the same values |
| 6 | Documentation-only metadata that never reaches the wire | **done** — `doc.motivation`/`since`/`see_also`/`example_note`, surfaced through `describe_*` and the generated C block comments |
| 7 | **A CI check that fails on drift** | **done** — `make check` and CI; see 13.3 |

### 13.2 Against the §1 measurements

| §1 finding | Then | Now |
|---|---|---|
| 1.1 Payload shape typed for 7 of 92 messages | 7 typed by hand | 1 of those 7 now *generated* from a declared spec with units and constraints; the other 6 unchanged |
| 1.2 Topic names duplicated as literals in subscribers | `"trade.executed"` in 17 modules | **14 modules, 26 occurrences** — Phase 2 removed 3 modules (`engine/main.py`, `stats/main.py`, `models/message.py`) |
| 1.3 Documentation drifts in both directions | unchanged | unchanged — Phase 6 |
| 1.4 The C surface has no message types | a generic `calf_field_t` bag; every client re-derives field names as literals | **`trade.executed`'s CALF projection now has a typed struct**, a real enum, a parser and a validator, all generated. `calf_subscriber.c` uses them. The bag remains for every other message. |

The 1.2 number is the honest one to watch. Phase 2 adopted the *producer* side
of `trade.executed` completely, and three of seventeen consumers. A publisher-side
rename is therefore still silent for `ralf_gateway`, `board`, `api_gateway`,
`alf_console`, `audit`, `balf_gwy`, `index`, `alf_gwy`, `clearing`,
`ai_trader`, `md_gateway` and `mm_bot`. Driving that count to zero is what
§7.4's `pm-msgen grep-literals` exists to measure, and it is Phase 5 work.

### 13.3 The guarantee is live (Phase 3, done)

§7.2 says it plainly: *"Without the check, the generator is merely a scaffolder
and §1 recurs within a release."* As of Phase 3 that sentence no longer
describes this repository.

`pm-msgen check` runs in two places:

| Place | Invocation |
|---|---|
| `make check` → `_check` → `msgen-check` | `poetry run pm-msgen check`, stamp-cached on `spec/*.yaml` + `src/**/*.py` |
| `ci.yml`, `code-check` job | `PYTHONPATH=src poetry run python -m edumatcher.msgen.cli check` |

The CI job installs with `--no-root`, so the `pm-msgen` console script is not on
`PATH` there; only its dependencies are. Hence the module invocation. `pyyaml`
is a main dependency and is present. This is a footgun for whoever next tidies
that workflow, so `tests/test_msgen_ci_wiring.py` asserts it explicitly.

All three A.6 criteria were verified by running the real build, not by
inspection: a hand-edit to `trade.py` fails `make msgen-check` with a diff and
leaves no stamp; a `le: 8 → le: 6` spec edit without regeneration fails the same
way; `make msgen` fixes both.

**The wiring itself is tested.** `tests/test_msgen_ci_wiring.py` parses the
`Makefile` and `ci.yml` and fails if `msgen-check` drops out of `_check` or the
CI step disappears. This is not paranoia for its own sake: a guarantee that can
be removed by an unrelated refactor with nothing noticing is not a guarantee,
and this design's entire value proposition rests on this one check.

**What it does not cover.** The check protects *specified* families. One family
of roughly fifteen has a spec, so everything else still drifts exactly as §1
describes. The gate is now in place; filling it is Phase 5.

### 13.4 A duplicate this created, and why it was left

Phase 2 made the spec authoritative for the engine, `make_trade_msg` and
pm-stats — but `models/feed_schema.py::TradeExecutedPayload` is still
hand-written, still field-for-field identical to the generated `TradeExecuted`,
and still used by `clearing/main.py::_trade_from_payload`.

Two typed descriptions of one message is §1's problem in miniature, so this is a
real (if small) regression against the intent, created by this work. It is
guarded rather than removed: `TestNoDuplicateDescriptionSurvivesUnguarded`
asserts field-for-field parity, so drift fails the suite immediately.

It was not folded into an alias because `feed_schema` is imported by
`models/message.py`, which the generated module imports in turn; an alias would
create a cycle whose safety depends on statement order inside `feed_schema.py`.
That is worth doing deliberately, and it is the same decision as open question 2
(should `feed_schema` be generated?) — which Phase 5 should now answer *yes* to,
since the generator has proven it can reproduce these payloads exactly.

### 13.4a What Phase 4a actually proved

The headline is not "C generation works". It is that **one declaration now
produces enforcement in two languages, and a test says so.**
`validate: { gt: 0 }` on `price` in `trade.yaml` becomes
`raise MessageValidationError("price: ... must be > 0")` in Python and
`snprintf(err, errlen, "price must be > 0")` in C, and
`test_c_and_python_reject_the_same_values` asserts the two agree. That is design
goal 5, and before this phase there was no C binding for it to be half of.

Two smaller results worth recording:

- **The C compiles under `-Wall -Wextra -pedantic -Werror`.** The round-trip
  test builds it that way deliberately, so "generated" never becomes an excuse
  for code the project would not accept if a person had written it.
- **The example client got *better*, not just different.** Its TRADE handler
  previously printed `?` for any field it could not find and had no way to
  notice a zero price at all; it now reports `<unparseable: ...>` or
  `<invalid: price must be > 0>`.

### 13.5 What went better than the design predicted

- **R1 (generated output silently diverges during migration)** did not
  materialise, because the byte-identity test was written before the adoption
  rather than after. The design's insistence that no family is adopted without
  one earned its place.
- **R9 (non-deterministic generation)** was designed out rather than tested for:
  emitting black-formatted output directly, instead of shelling out to black,
  removed the dependence on a formatter version entirely.
- The **strict loader** (§B.18 rule 15) caught real typos during spec authoring,
  including one in this repository's own first `trade.yaml` draft. The
  "did you mean …?" suggestion cost about twenty lines and paid for itself
  immediately.

### 13.6 What the design got wrong, and the pattern in it

Three corrections were needed once implementation started (§8.1, §8.2, and the
seven fixed in 1.5.0). All three share a shape worth naming: **the design
reasoned about the system from its documentation and its structure, and was
right about both, but had not measured its behaviour.**

- §12.2: `make_trade_msg` *looked* like the publisher API; it had no callers.
- §8.2: routing `_unchecked` through the dataclass *looked* free; it was 4×.
- §8.1: pm-stats *looked* like a parser; it is a recorder, and its tolerance was
  load-bearing.
- §7.2 (Phase 3): the CI snippet *looked* obviously right — it is the same
  command the Makefile uses — but the `code-check` job installs with
  `--no-root`, so that command does not exist there.
- §B.13 (Phase 4a): the text key-ordering rule *looked* necessary, because
  gateways emit ordered lines. Reading both emitters showed they order
  differently and that the projection never emits envelope keys at all.
- §5.2 (Phase 4a): "reuse the existing convention" *looked* like one
  convention. `calf_parser.c` had a second one all along.
- Phase 4a adoption: adopting the typed struct in `calf_subscriber.c` *looked*
  like it should replace every `calf_get_field`, including `PX`. The file's own
  header comment explains it never reparses prices on purpose — reformatting a
  decimal needs the per-symbol tick scale. A first attempt at this change broke
  that and had to be reverted to printing `PX` from the wire string.
- Phase 4a projection: taking a constructed message *looked* like the typed,
  obvious signature. It forced a CALF gateway to hold eleven fields to emit
  three, and only the full test suite said so — eight `md_gateway` tests failed
  with `KeyError: 'id'`. See §B.13.

**The one that keeps recurring.** Three of these — §8.1 (pm-stats), the
`normalise_trade` failure mode, and the projection signature — are the same
error: *reasoning about what a consumer needs instead of reading what it
actually does.* §8.1 even states the rule, and the projection signature broke it
two phases later in the same file it was written about.

The concrete guard is cheap and should be used from Phase 4b onwards: **before
adopting a generated artefact in a module, read that module's existing tests.**
They encode the contract its callers actually rely on, which is more reliable
than either the design or the implementation. In this instance the eight failing
tests were not obstacles to work around — they were the specification, and the
code was wrong.

The lesson for Phases 4–6: before adopting a generated artefact in a module,
read what that module actually does with the message, and measure or run the
path rather than reasoning about it. The design is a good map; it is not the
territory.

Every one of the four was caught by executing something — a grep for callers, a
timing loop, reading a handler's error paths, running `make`. None would have
been caught by review.

## Appendix A — Phase 1 implementation starter

Sections 1–11 are the design. This appendix is the *how* for the first
engineer, scoped tightly to **Phase 1 only** (§8): generate the Python output
for the one `trade` family and prove it byte-identical to the existing
`TradeExecutedPayload`. It exists so a junior can start without first inventing
the module layout, the parsed-spec model, and one worked generated function.
Everything here is Phase 1; C generation (§5.2) and the cffi harness are
Phase 4 and get only a pointer at the end.

### A.1 Module layout

Mirror `cverifier`/`config_gen`. Build exactly this and no more for Phase 1:

```
src/edumatcher/msgen/
    __init__.py
    cli.py              # argparse dispatch: generate | check | lint  (grep-literals is Phase 5)
    spec.py             # parsed-spec dataclasses + strict YAML loader
    generate.py         # orchestration: load spec -> write output files
    generators/
        __init__.py
        python.py       # spec -> src/edumatcher/models/generated/<family>.py
        # c.py    -> Phase 4
        # docs.py -> Phase 6
    # no templates/ dir: hand-rolled string assembly (open question 6, §12.5)

src/edumatcher/models/generated/
    __init__.py
    _runtime.py         # hand-written, committed: MessageValidationError (see §5.1)

spec/messages/
    trade.yaml          # the only spec file in Phase 1

tests/
    test_msgen_spec.py           # loader accepts trade.yaml, rejects unknown keys
    test_msgen_python.py         # generator output compiles and imports
    test_msgen_trade_wire_compat.py   # THE Phase 1 acceptance test (A.5)
```

Register the script in `pyproject.toml`: `pm-msgen =
"edumatcher.msgen.cli:main"`. No dependency group is needed (§12.5).

### A.2 The parsed-spec data model (`spec.py`)

This is the single most useful artefact to build first: the typed shape the
YAML loads into, which every generator then consumes. It is *not* generated —
it is hand-written and is the generator's own contract.

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class Validate:
    gt: float | None = None
    ge: float | None = None
    lt: float | None = None
    le: float | None = None
    max_len: int | None = None
    min_len: int | None = None
    max_items: int | None = None
    pattern: str | None = None

@dataclass(frozen=True)
class Field:
    name: str
    type: str                       # string|int|float|bool|enum|ticks|list[...]
    required: bool = True
    default: Any = None
    unit: str | None = None
    doc: str = ""
    values: tuple[str, ...] | None = None      # enum only
    validate: Validate = field(default_factory=Validate)
    deprecated_since: str | None = None
    removed_after: str | None = None

@dataclass(frozen=True)
class Message:
    name: str
    topic: str
    transport: tuple[str, ...]
    fields: tuple[Field, ...]
    doc: dict[str, Any] = field(default_factory=dict)
    encoding: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class Family:
    family: str
    version: int
    messages: tuple[Message, ...]
```

**Loader requirement (open question 7): be strict.** Unknown keys must raise,
not be silently ignored — otherwise `requird: true` disables a field with no
error, which is the exact failure class this whole tool exists to kill:

```python
import yaml

_FIELD_KEYS = {f.name for f in dataclasses.fields(Field)}

def _load_field(raw: dict[str, Any]) -> Field:
    unknown = set(raw) - _FIELD_KEYS
    if unknown:
        raise SpecError(f"field {raw.get('name')!r}: unknown keys {sorted(unknown)}")
    v = raw.get("validate", {}) or {}
    return Field(
        name=raw["name"],
        type=raw["type"],
        required=raw.get("required", True),
        default=raw.get("default"),
        unit=raw.get("unit"),
        doc=raw.get("doc", ""),
        values=tuple(raw["values"]) if "values" in raw else None,
        validate=Validate(**v),          # Validate(**v) itself raises on a typo'd rule key
        deprecated_since=raw.get("deprecated_since"),
        removed_after=raw.get("removed_after"),
    )
```

### A.3 One fully-worked generated function

The design shows only signatures (§5.1). Here is the *complete* Python the
generator must emit for `trade`, so the junior has a target to pattern-match.
It is written to match `feed_schema.TradeExecutedPayload` field-for-field —
same field order, same `str()/int()/float()` coercion, same `.get()` defaults —
because A.5 asserts byte-identical `to_dict()`.

```python
# GENERATED FROM spec/messages/trade.yaml — DO NOT EDIT
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from edumatcher.models import message as _msg
from edumatcher.models.generated._runtime import MessageValidationError

TOPIC_TRADE_EXECUTED = "trade.executed"

@dataclass(frozen=True, slots=True)
class TradeExecuted:
    id: str
    symbol: str
    buy_order_id: str
    sell_order_id: str
    buy_gateway_id: str
    sell_gateway_id: str
    price: float
    quantity: int
    aggressor_side: Literal["BUY", "SELL", "AUCTION"]
    timestamp: float
    tick_decimals: int = 2

    def validate(self) -> None:
        if self.price <= 0:                          # from validate: { gt: 0 }
            raise MessageValidationError("price must be > 0")
        if self.quantity <= 0:                       # from validate: { gt: 0 }
            raise MessageValidationError("quantity must be > 0")
        if self.aggressor_side not in ("BUY", "SELL", "AUCTION"):
            raise MessageValidationError(f"bad aggressor_side {self.aggressor_side!r}")
        if not (0 <= self.tick_decimals <= 8):       # from validate: { ge: 0, le: 8 }
            raise MessageValidationError("tick_decimals out of [0, 8]")

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "TradeExecuted":
        return cls(
            id=str(p["id"]),
            symbol=str(p["symbol"]),
            buy_order_id=str(p["buy_order_id"]),
            sell_order_id=str(p["sell_order_id"]),
            buy_gateway_id=str(p["buy_gateway_id"]),
            sell_gateway_id=str(p["sell_gateway_id"]),
            price=float(p["price"]),
            quantity=int(p["quantity"]),
            aggressor_side=str(p.get("aggressor_side", "")),  # type: ignore[arg-type]
            timestamp=float(p["timestamp"]),
            tick_decimals=int(p.get("tick_decimals", 2)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "buy_order_id": self.buy_order_id,
            "sell_order_id": self.sell_order_id,
            "buy_gateway_id": self.buy_gateway_id,
            "sell_gateway_id": self.sell_gateway_id,
            "price": self.price,
            "quantity": self.quantity,
            "aggressor_side": self.aggressor_side,
            "timestamp": self.timestamp,
            "tick_decimals": self.tick_decimals,
        }

def make_trade_executed(**kw: Any) -> list[bytes]:
    # from_dict, NOT TradeExecuted(**kw): the constructor skips coercion, so
    # make_trade_executed(price=100) would put an int on the wire where the
    # hand-written factory puts a float. See §5.1.1 (normative).
    obj = TradeExecuted.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_TRADE_EXECUTED, obj.to_dict())   # two frames — sequence added by the bus

def make_trade_executed_unchecked(**kw: Any) -> list[bytes]:
    """Same frames, no validate(). For measured hot paths only (§8 Phase 2)."""
    return _msg.encode(TOPIC_TRADE_EXECUTED, TradeExecuted.from_dict(kw).to_dict())

def parse_trade_executed(frames: list[bytes]) -> TradeExecuted:
    _topic, payload = _msg.decode(frames)
    obj = TradeExecuted.from_dict(payload)
    obj.validate()
    return obj

def is_trade_executed(topic: str) -> bool:
    return topic == TOPIC_TRADE_EXECUTED
```

The generator's job in Phase 1 is to produce exactly the above from the field
list and `validate:` rules — a template with one loop over `fields` for the
dataclass body, one over `fields` for `from_dict`/`to_dict`, and a small
`rule → line` map for `validate()` (`gt` → `<= 0 raise`, `ge/le` → range
check, `values` → membership, `pattern` → `re.fullmatch`).

### A.4 Parameterised topics (the `match_*`/`topic_*` derivation)

For a topic like `order.ack.{gateway_id}` the generator derives three things
mechanically; this is the algorithm the design shows only as output (§5.1):

```python
# pattern = "order.ack.{gateway_id}"
# PREFIX  = pattern up to the first "{"           -> "order.ack."
# regex   = re.escape each literal run, replace {param} with (?P<param>[^.]+)
#           -> r"^order\.ack\.(?P<gateway_id>[^.]+)$"
def topic_order_ack(gateway_id: str) -> str:
    return f"order.ack.{gateway_id}"

_ORDER_ACK_RE = re.compile(r"^order\.ack\.(?P<gateway_id>[^.]+)$")
def match_order_ack(topic: str) -> str | None:
    m = _ORDER_ACK_RE.match(topic)
    return m.group("gateway_id") if m else None

PREFIX_ORDER_ACK = "order.ack."   # for setsockopt(zmq.SUBSCRIBE, ...)
```

`[^.]+` (not `.+`) matters: topic segments are dot-delimited, so a greedy `.+`
would swallow a trailing `.suffix`. `trade_executed` has no `{param}` so it
gets only the constant and `is_trade_executed`.

### A.5 The Phase 1 acceptance test (write this first)

This is the definition of done for Phase 1 and should be written *before* the
generator, red-to-green:

```python
# tests/test_msgen_trade_wire_compat.py
import pytest
from edumatcher.models.feed_schema import TradeExecutedPayload
from edumatcher.models.generated.trade import TradeExecuted

_SAMPLE = {
    "id": "42", "symbol": "ACME",
    "buy_order_id": "b-1", "sell_order_id": "s-1",
    "buy_gateway_id": "GW1", "sell_gateway_id": "GW2",
    "price": 101.5, "quantity": 300,
    "aggressor_side": "BUY", "timestamp": 1_700_000_000.0, "tick_decimals": 2,
}

def test_to_dict_byte_identical_to_hand_written():
    hand = TradeExecutedPayload.from_dict(_SAMPLE).to_dict()
    gen  = TradeExecuted.from_dict(_SAMPLE).to_dict()
    assert gen == hand
    assert list(gen) == list(hand)          # key ORDER too — to_dict feeds orjson
    # frames must also match: generated make_* and the existing make_trade_msg
    from edumatcher.models.message import make_trade_msg
    from edumatcher.models.generated.trade import make_trade_executed
    assert make_trade_executed(**_SAMPLE) == make_trade_msg(_SAMPLE)

def test_from_dict_coerces_but_does_not_validate():
    """§5.1.1: from_dict is lenient; validate() is the only strictness gate."""
    loose = {**_SAMPLE, "price": 101, "quantity": "300", "id": 42}
    obj = TradeExecuted.from_dict(loose)     # must NOT raise
    assert obj.price == 101.0 and isinstance(obj.price, float)
    assert obj.quantity == 300 and isinstance(obj.quantity, int)
    assert obj.id == "42"
    # and the archive case: a payload with no aggressor_side parses, then fails
    # validate() — which is what makes the "" population countable (§5.1.1).
    archived = {k: v for k, v in _SAMPLE.items() if k != "aggressor_side"}
    assert TradeExecuted.from_dict(archived).aggressor_side == ""
    with pytest.raises(MessageValidationError):
        TradeExecuted.from_dict(archived).validate()

@pytest.mark.parametrize("bad", [
    {**_SAMPLE, "price": 0}, {**_SAMPLE, "quantity": 0},
    {**_SAMPLE, "tick_decimals": 9}, {**_SAMPLE, "aggressor_side": "X"},
])
def test_validate_rejects_out_of_range(bad):
    from edumatcher.models.generated._runtime import MessageValidationError
    obj = TradeExecuted.from_dict(bad)
    with pytest.raises(MessageValidationError):
        obj.validate()
```

If both tests pass and `black`/`flake8`/`mypy`/`pyright` are clean on the
generated file, Phase 1 is done.

### A.6 Per-phase definition-of-done checklist

- [x] **Phase 1** `spec.py` loads `trade.yaml` and rejects unknown keys;
  `generators/python.py` emits `models/generated/trade.py`; A.5 passes; static
  tools clean on the generated file; `_runtime.py` committed.
- [x] **Phase 2** `make_trade_msg` delegates to `make_trade_executed`;
  `engine/main.py::_publish_trade` delegates to `make_trade_executed_unchecked`;
  full existing suite passes unchanged; **both** wire assertions of §8 Phase 2
  hold (byte-identity factory-vs-factory, payload+key-set equality
  engine-vs-factory); a `perf`-marked test shows no hot-path regression.
- [x] **Phase 3** `pm-msgen check` added to `_check` and `ci.yml`; a
  deliberate hand-edit to `trade.py` fails CI; a spec edit without regen fails
  CI; generation proven deterministic (`generate` twice → identical bytes).
- [x] **Phase 4a** `calf:` encoding on `trade_executed`; Python projection and
  C header/impl generated; `normalise_trade` and `calf_subscriber.c`'s TRADE
  handler adopt them; a compiled round-trip test proves Python and C agree.
- [ ] **Phase 4b** BALF `layout` support; `order.yaml` with `execution_report`;
  capstone assertion 5.
- [ ] **Phase 5** one family per PR, each with its own wire-compat test;
  `grep-literals` count for the family driven to zero.
- [ ] **Phase 6** `271-message-appendix.md` generated and wired into
  `mkdocs.yml` nav.

### A.7 Pointer for Phase 4 (not Phase 1)

The cffi harness that assertions 4/5 of the capstone need is a `cffi`
`ffi.cdef(generated_header) + ffi.verify(generated_c)` at test-collection time,
then calling `edu_execution_report_parse_balf(bytes, len, out)` and comparing
`out` field-by-field against the Python object. A junior should not attempt
this in Phase 1; it is listed here only so the shape is known when Phase 4
arrives. The serialisation algorithm (`repr` → `struct.pack` format code,
`offset` placement, `enum_map`, fixed `price_scale`) is likewise Phase 4 and
should get its own short design note once Phase 1–3 have shaken out the spec
model.



## Appendix B — IDL specification (normative)

This appendix is the **authoritative** definition of the specification
language. Where a prose example earlier in this document disagrees with this
appendix, this appendix wins. Sections 4–5 are illustrative; Appendix B is the
contract the generator, the loader (Appendix A.2 is a Phase-1 subset of it),
and `pm-msgen lint` implement.

### B.1 Conformance and notation

- The key words **MUST**, **MUST NOT**, **REQUIRED**, **OPTIONAL** and
  **DEFAULT** are normative.
- A spec is a **YAML 1.2** document restricted to the subset defined here:
  mappings, sequences, and the scalar types string, integer, float, boolean.
  No anchors, aliases, tags, or multi-document streams.
- Grammar is given as a schema over YAML nodes using EBNF (§B.19). `{ X }`
  means zero-or-more; `[ X ]` means optional; `A | B` means alternation.
- Every generated artefact is a pure function of the spec files; see §B.17
  (determinism) — this is what makes `pm-msgen check` sound.

### B.2 File organisation

Two kinds of file, both under `spec/`:

| File | Cardinality | Root key | Defines |
|---|---|---|---|
| `spec/transports.yaml` | exactly one | `transports:` | the transport registry (§B.4) |
| `spec/messages/<family>.yaml` | one per family | `family:` | one message family (§B.5) |

`<family>` in the filename MUST equal the `family:` value inside it.

### B.3 Lexical rules

| Token | Rule |
|---|---|
| `identifier` | `^[a-z][a-z0-9_]*$` — snake_case; used for family, message, field, nested-type and transport names |
| `enum-name` | `^[A-Z][A-Z0-9_]*$` — SCREAMING_SNAKE; used for enum `values` and `enum_map` keys |
| `key-name` | `^[A-Z][A-Z0-9_]*$` — a CALF/RALF wire field key (e.g. `PX`, `EXEC_ID`) |
| `msg-type-text` | `^[A-Z][A-Z0-9_]*$` — a CALF/RALF `MSGTYPE` (e.g. `TRADE`, `EXEC`) |
| `msg-type-bin` | integer literal `0x00`–`0xFF` — a BALF message-type byte |
| `topic-pattern` | dot-delimited segments; a segment is either a literal `^[a-z0-9_]+$` or a single placeholder `{identifier}`; e.g. `order.ack.{gateway_id}` |
| `version-str` | `^[0-9]+\.[0-9]+$` — a two-part version used by `since`, `deprecated_since`, `removed_after` |

### B.4 Transport registry — `spec/transports.yaml`

```yaml
transports:
  <identifier>:
    pattern: <PUB|SUB|PUSH|PULL|TCP>          # REQUIRED
    subscriber_pattern: <PUB|SUB|PUSH|PULL>   # OPTIONAL; the peer pattern for a bus transport
    address_config_key: <IDENTIFIER>          # REQUIRED; symbolic key resolved from engine_config at runtime
```

- A transport whose `pattern` is `TCP` is an **external line/binary protocol**
  fronted by a gateway (CALF/BALF/RALF). Bus transports use the ZeroMQ patterns.
- `address_config_key` MUST NOT be a literal address; it is a name the runtime
  resolves. This keeps ports/addresses out of the generated code.
- The names `calf`, `balf`, `ralf` are **reserved** external-protocol
  transport names. They MAY be declared in the registry to bind an
  `address_config_key` (as `ralf` is in §4.4) or referenced bare (as `calf`
  and `balf` are, when their address is fully owned by the gateway); either way
  `lint` accepts them. Every *other* transport reference MUST be a registry
  entry.

### B.5 Family file — top level

```yaml
family:   <identifier>          # REQUIRED; MUST equal the filename stem
version:  <integer>             # REQUIRED; the logical layout version (see §B.17)
messages: [ <message>, ... ]    # REQUIRED; non-empty
```

### B.6 Message object

| Key | Req. | Type | Notes |
|---|---|---|---|
| `name` | REQUIRED | identifier | unique within the family |
| `topic` | CONDITIONAL | topic-pattern | REQUIRED iff `transport` lists ≥1 bus transport; MUST be omitted for purely external-protocol messages (e.g. BALF-only) |
| `transport` | REQUIRED | list of transport-ref | non-empty; each entry is a registry name or `calf`/`balf`/`ralf` |
| `doc` | OPTIONAL | doc-block (§B.16) | documentation-only; never reaches the wire |
| `fields` | REQUIRED | list of field (§B.7) | non-empty; declaration order is authoritative (§B.17) |
| `nested_types` | CONDITIONAL | map of identifier → nested-def (§B.8) | REQUIRED iff any field is `list[nested]` or `nested` |
| `encoding` | CONDITIONAL | map of transport-ref → encoding-def (§B.13) | A **bus** transport's block MAY be omitted, defaulting to `frames: [topic, json_payload]`, `include: all`. A **text** or **binary** transport's block is REQUIRED, because `keys`/`msg_type` (text) and `layout`/`frame_size` (binary) have no defensible default — there is nothing to infer a wire key or a byte offset from. |
| `invariants` | OPTIONAL | list of invariant (§B.15) | cross-field rules |

### B.7 Field object

| Key | Req. | Type | Default | Notes |
|---|---|---|---|---|
| `name` | REQUIRED | identifier | — | unique within the field's message or nested type |
| `type` | REQUIRED | type (§B.9) | — | |
| `required` | OPTIONAL | boolean | `true` | |
| `default` | OPTIONAL | scalar | — | type MUST match `type`; only meaningful when `required: false`. A **producer** may omit the field; the value is legal and passes `validate()` |
| `parse_default` | OPTIONAL | scalar | — | the lenient fallback `from_dict` substitutes when the key is **absent from an inbound payload**. Distinct from `default` and NOT required to be a legal value (§B.7.1) |
| `unit` | OPTIONAL | unit (§B.11) | — | REQUIRED by `lint` for numeric fields (§B.18 rule 15) |
| `doc` | OPTIONAL | string | `""` | REQUIRED non-empty when the field is deprecated |
| `values` | CONDITIONAL | list of enum-name | — | REQUIRED iff `type == enum`; order is authoritative |
| `item` | CONDITIONAL | identifier | — | REQUIRED iff `type == list[nested]`; names a `nested_types` entry |
| `validate` | OPTIONAL | validate-map (§B.12) | `{}` | |
| `deprecated_since` | OPTIONAL | version-str | — | see §B.17 |
| `removed_after` | OPTIONAL | version-str | — | generator refuses to delete the field before this family version |

#### B.7.1 `default` vs `parse_default` (normative)

The two keys look similar and are not interchangeable. They exist because
§5.1.1 splits coercion from validation, and each half needs its own fallback:

| | `default` | `parse_default` |
|---|---|---|
| Consumed by | the **producer** side — `make_*`, the generated dataclass field default | the **consumer** side — `from_dict` only |
| Question it answers | "what value does a producer get if it omits this field?" | "what does `from_dict` substitute if this key is missing from an inbound payload?" |
| Must be a legal value? | **yes** — it must pass `validate()` | **no** — it may be a value `validate()` rejects |
| Meaningful when | `required: false` | either |

`from_dict`'s emission rule follows directly, in this precedence:

1. `parse_default` declared → `p.get("<name>", <parse_default>)`
2. else `required: false` with a `default` → `p.get("<name>", <default>)`
3. else → `p["<name>"]` (raises `KeyError`, matching the hand-written payloads)

The key exists because the very first message needs it. `trade.executed`'s
`aggressor_side` is `required: true, values: [BUY, SELL, AUCTION]` — the honest
contract, and what the engine always publishes — while
`feed_schema.py:60` reads it as `p.get("aggressor_side", "")` because archived
and replayed payloads predate the field (§12.1). Without `parse_default` the
spec would have to choose between lying about the contract (declaring `""` a
legal `aggressor_side`, which then has to become a C enum member) and breaking
every reader of the archive. It expresses "strict for producers, lenient for
readers" as one declared line instead of an accident spread over five files.

`parse_default` never reaches the wire, never appears in `to_dict`, and never
weakens `validate()`.

### B.8 Nested type object

```yaml
nested_types:
  <identifier>:
    fields: [ <field>, ... ]     # same field grammar as §B.7; nested types MAY nest further
```

A nested type is referenced by `type: nested` (single) with an `item:` naming
it, or by `type: list[nested]` with `item:` naming it. Recursion (a nested type
referencing itself, directly or transitively) is **forbidden**; the generator
emits fixed-size structs and cannot size a cyclic type.

### B.9 Type system (logical `type` → bindings)

| `type` | Python | C | JSON | Required companions |
|---|---|---|---|---|
| `string` | `str` | `char[N]` | string | `validate.max_len` REQUIRED when any transport is external (fixes `N`) |
| `int` | `int` | `int64_t` (or sized by `repr`) | number | — |
| `float` | `float` | `double` | number | — |
| `bool` | `bool` | `uint8_t` | bool | — |
| `enum` | `str` + `Literal[values]` | generated `enum` + `_to_str`/`_from_str` | string | `values` REQUIRED; `enum_map` REQUIRED for a binary transport |
| `ticks` | `int` | `int64_t` | number | conventionally paired with a `tick_decimals` field |
| `list[T]` | `list[T]` | `T[N] + <name>_count` | array | `validate.max_items` REQUIRED when any transport is external (fixes `N`) |
| `nested` | dataclass | struct | object | `item` REQUIRED; entry in `nested_types` |

`list[T]` nests: `list[int]`, `list[nested]` are both legal. `T` MUST itself be
a valid `type`.

### B.10 `repr` reference (binary layout only)

| `repr` | Bytes | Wire meaning |
|---|---|---|
| `u8` `u16` `u32` `u64` | 1/2/4/8 | little-endian unsigned integer |
| `i8` `i16` `i32` `i64` | 1/2/4/8 | little-endian signed integer |
| `f32` `f64` | 4/8 | IEEE-754 (rare; EduMatcher money is scaled integers, not floats) |
| `char[N]` | N | zero-padded ASCII, `N` MUST equal the field's `validate.max_len` |

A numeric `repr` MAY carry `scale:` (§B.13) to convert a wire integer to a
display float. `enum_map` MAY accompany a `u8`/`u16` carrying an enum.

### B.11 `unit` reference (complete enumeration)

`display_price`, `ticks`, `shares`, `epoch_seconds`, `epoch_nanos`, `percent`,
`dimensionless`, `money`. A `unit` is **declarative metadata** only — it appears
in generated docs and is never a runtime conversion. Any other value is a
lint error.

### B.12 Validation vocabulary (complete)

Field-level keys (§B.7): `required`, `default`, `values`. The `validate:` block
holds the remaining constraints:

| `validate` key | Applies to | Meaning |
|---|---|---|
| `gt` / `ge` / `lt` / `le` | int, float, ticks | strict/inclusive bounds |
| `max_len` / `min_len` | string | length bounds; `max_len` also fixes C `char[N]` |
| `max_items` | list[T] | element-count bound; also fixes C array size |
| `pattern` | string | full-match regular expression (`re.fullmatch` semantics) |

No other `validate` keys are permitted. Anything more expressive than the above
belongs in `invariants` (§B.15) or stays hand-written (§4.3).

### B.13 Encoding object

`encoding` is a map keyed by transport-ref. Three shapes, selected by the
transport's class:

**Bus** (ZeroMQ transports — `engine_pub`, `engine_push`, …):

```yaml
bus:
  frames: [ topic, json_payload ]   # ordered; allowed tokens: topic, json_payload
  include: <all | [field, ...]>     # DEFAULT all
```

`frames` MUST NOT contain a `sequence` token — the per-topic sequence is a
third frame injected by `SequencedPublisher` at publish time, never declared
here (see §4.1, B6).

**Text** (`calf`, `ralf`):

```yaml
calf:
  msg_type: <msg-type-text>                 # REQUIRED
  include: <all | [field, ...]>             # DEFAULT all
  keys: { <field>: <key-name | [key-name, ...]>, ... }   # REQUIRED for every included field
  gateway_injected: [ <key-name>, ... ]     # OPTIONAL; keys the gateway supplies, not the payload
```

A `keys` entry MAY map one source field to several wire keys (RALF
`id: [EXEC_ID, MATCH_ID]`). `gateway_injected` keys MUST NOT collide with any
`keys` value.

**Key emission order (normative; corrected in 1.8.0).** The generated text
projection emits **only the included payload fields, in `include` order** (or
`fields` declaration order when `include: all`), each expanded to its `keys`
targets in declaration order. `gateway_injected` keys are **documentation
only** — the projection never emits them, and their order in the spec carries
no meaning.

v1.5.0 stated the opposite: that the projection emits `gateway_injected` keys
first, then the payload. That rule was both unnecessary and unsatisfiable.

*Unnecessary*, because §4.6 N1 already draws the line: the generator owns the
payload field map, and the gateway owns the envelope around it.
`md_gateway/normaliser.py::normalise_trade` returns `{PX, QTY, SIDE}` and
nothing else; `CH`/`SYM`/`SEQ`/`TS` are added by
`md_gateway/gateway.py::_emit_stream_event`, which the generator does not
replace. The projection is never responsible for envelope keys, so it never has
to order them.

*Unsatisfiable*, because the two gateways inject in different positions and no
single rule covers both:

| Gateway | Code | Resulting order |
|---|---|---|
| CALF | `md_gateway/gateway.py:735-755` — builds `{CH, SYM, SEQ, TS}` then `.update(payload_fields)` | injected **first**, payload after |
| RALF | `ralf_gateway/gateway.py:513-519` — `merged = dict(fields)` (already carrying `CH`, `SYM`, `TS`) then `merged["SEQ"] = str(seq)` | `SEQ` **last**, after the payload |

Any rule that put all injected keys in one block would produce a line RALF does
not produce. Since the projection emits none of them, the question does not
arise — which is the correct resolution rather than a workaround.

**A projection takes a payload mapping, not a fully-built message (normative).**
`project_<msg>_<transport>(payload: Mapping[str, Any]) -> dict[str, str]` reads
**only the included fields**, with the same read precedence as `from_dict`
(§B.7.1), and coerces each to its declared type before rendering.

The first Phase 4a implementation took a constructed message object instead, so
`normalise_trade` had to build a whole `TradeExecuted` — eleven fields — in
order to emit three. Eight existing `md_gateway` tests failed with
`KeyError: 'id'`, and they were right to: every one of them passes exactly the
fields the CALF feed carries.

The rule this fixes is worth stating plainly, because it is the projection model
of §4.6 applied to the code rather than to the documentation: **a projection is
a subset, so it must depend on a subset.** A gateway feeding one transport must
never be required to hold fields that transport drops. If it were, the spec
would have re-coupled exactly the surfaces the projection model exists to
separate.

`project_*(payload)` and `project_*(msg.to_dict())` are interchangeable, and a
test asserts it.

**Enum values are emitted uppercase.** For a field of `type: enum` the text
projection emits `str(value).upper()`. This is idempotent for any value in the
declared `values` (§B.3 requires SCREAMING_SNAKE enum names), and it reproduces
`normalise_trade`'s existing `str(payload.get("aggressor_side", "")).upper()`
exactly, so adoption is wire-compatible by construction.

**Numeric text formatting.** `int`/`ticks` emit `str(int(v))`, `float` emits
`str(v)`, `string` emits `str(v)`. These match `md_gateway/normaliser.py`'s
`_as_int_text` and `_as_decimal` (both trivial: `str(int(raw))` and `str(raw)`).
One consequence worth stating: because the projection is applied to a *coerced*
message, a `float` field always formats through Python's float repr — a payload
carrying an integer `price` of `150` yields `"150.0"`, where the hand-written
normaliser fed the raw value and produced `"150"`. Engine-published trades have
carried a float `price` since Phase 2 adopted the generated constructor, so this
is unreachable for live data; it is noted because a replayed pre-Phase-2 capture
could hit it.

**Binary** (`balf`):

```yaml
balf:
  msg_type: <msg-type-bin>          # REQUIRED; 0x00–0xFF, unique within the transport
  frame_size: <integer>             # REQUIRED; total bytes = 8-byte header + body
  price_scale: <integer>            # OPTIONAL; fixed divisor for scaled prices (e.g. 100000000)
  layout: [ <layout-entry>, ... ]   # REQUIRED; ordered
```

`layout-entry` is one of:

```yaml
- { field: <field>, repr: <repr>, offset: <int>,
    scale: <int | price_scale>,          # OPTIONAL; integer or the literal token price_scale
    enum_map: { <ENUM_NAME>: <int>, ... } }   # OPTIONAL; REQUIRED when the field is an enum
- { reserved: <int>, offset: <int> }     # explicit zero-padding run of <int> bytes
```

The fixed 8-byte header (`magic=0xBA`, `version`, `msg_type`, `flags`,
`seq_no` u32 LE) is **implicit** and prepended by the generator; it MUST NOT be
declared in `layout`. `offset` is relative to the **body** (byte 0 = first byte
after the header).

### B.14 Projection semantics

For each transport a message declares, the generated projection carries exactly
the fields named by `include` (or all fields when `include: all`), renamed per
`keys` (text) or placed per `layout` (binary). Fields not in `include` are
absent from that transport. `gateway_injected` keys are documented and
round-tripped by the gateway but are **not** sourced from the message payload
(§4.6).

### B.15 Invariant expression grammar

`invariants` express cross-field rules the per-field vocabulary cannot. The
expression language is deliberately **not** Turing-complete: boolean
combination of comparisons over fields and literals, nothing else.

```yaml
invariants:
  - rule: "price > 0 or order_type == 'MARKET'"    # REQUIRED; see grammar below
    message: "limit orders require a positive price" # REQUIRED; used as the error text
```

```ebnf
expr     ::= or-expr
or-expr  ::= and-expr { "or" and-expr }
and-expr ::= comparison { "and" comparison }
comparison ::= operand rel-op operand | "(" expr ")"
rel-op   ::= "==" | "!=" | ">" | ">=" | "<" | "<="
operand  ::= field-name | number | "'" string "'" | "true" | "false"
```

Every `field-name` in an invariant MUST be a field of the message. No function
calls, no arithmetic operators, no indexing.

### B.16 `doc` object

```yaml
doc:
  motivation:   <string>              # REQUIRED by lint for every message
  since:        <version-str>         # OPTIONAL
  see_also:     [ <string>, ... ]     # OPTIONAL; free-form topic/message references
  example_note: <string>              # OPTIONAL
```

Nothing under `doc` reaches the wire; it feeds the generated documentation
appendix (§5.3) only.

### B.17 Versioning and determinism

- `family.version` (integer) is the **logical layout version** of the family.
  It is distinct from the single global BALF wire-header version byte (`0x01`)
  shared by all binary messages (R7): a family bump does not change the header
  byte, and the header byte changes only by a deliberate protocol-wide decision.
- A field MUST pass through `deprecated_since` before it may be removed, and MUST
  NOT be deleted before the family reaches `removed_after` (§4.5).
- **Determinism (normative):** generated output MUST be a byte-for-byte pure
  function of the spec. Field/enum/message order in every artefact follows
  **declaration order** in the spec; mappings are emitted in a stable
  (declaration or lexicographic) order; no timestamps, absolute paths, or
  set-iteration-dependent ordering may appear. This is what makes `pm-msgen
  check` (§7.2) a reliable gate rather than a flaky one.

### B.18 Static semantic rules (normative; enforced by `pm-msgen lint`)

A spec is **valid** only if all of the following hold. Each is a lint error.

1. Every `transport` entry is a registry name or one of `calf`/`balf`/`ralf`.
2. `topic` is present iff the message lists ≥1 bus transport, and matches the
   `topic-pattern` lexical rule.
3. Every `{param}` in `topic` names a field of the message.
4. `include` (every transport) names only declared fields; `all` is allowed.
5. **If the message declares a bus transport,** every `required` field appears
   in that bus projection's `include` (the bus payload is authoritative). A
   message with no bus transport (e.g. the BALF-only `execution_report`) is
   exempt — there is no authoritative projection to check against, and rules 6
   and 10 already constrain its external encodings.
6. For a **text** encoding, `keys` covers exactly the included, non-gateway-injected
   fields; no `keys` value collides with a `gateway_injected` key.
7. An `enum` field has `values`; a binary encoding of an enum field has an
   `enum_map` covering **every** name in `values`.
8. A `string` field reaching any external transport has `validate.max_len`; a
   binary `char[N]` has `N == validate.max_len`.
9. A `list[nested]`/`nested` field has `item` naming a declared `nested_types`
   entry; `list[...]` reaching an external transport has `validate.max_items`.
10. Binary `layout` offsets are non-overlapping, in range `[0, frame_size-8)`,
    and every non-reserved byte up to `frame_size-8` is covered by exactly one
    entry (gaps MUST be explicit `reserved` runs). A `scale: price_scale`
    reference requires `price_scale` to be declared on the same `balf` block;
    every `char[N]` in the layout matches its field's `max_len` (rule 8).
11. Binary `msg_type` is a byte and unique within its transport across all families.
12. Deprecated fields carry a non-empty `doc`; a field is not deleted before
    `removed_after` (§B.17).
13. `unit`, when present, is one of the §B.11 values; `lint` additionally
    requires a `unit` on numeric (`int`/`float`/`ticks`) fields.
14. `topic` strings are unique across **all** families (§7.3).
15. Unknown keys anywhere in the spec are rejected (strict loader, §A.2, §7.3).

Rules 1–15 are properties of a spec (`V001`–`V015`, §7.5.4). One further rule
binds the **loader itself**, not the spec: it MUST load via `yaml.compose()`
(not `safe_load`) so every diagnostic carries `file:line:col` (§7.5.1), every
diagnostic MUST be a coded `Diagnostic` (§7.5.2) rather than a bare exception,
and a run MUST report all errors in a layer instead of failing on the first
(§7.5.5).

### B.19 Formal grammar (authoritative summary)

```ebnf
(* ---- transport registry: spec/transports.yaml ---- *)
transport-file ::= "transports:" { identifier ":" transport-def }
transport-def  ::= "pattern:" pattern
                   [ "subscriber_pattern:" pattern ]
                   "address_config_key:" identifier
pattern        ::= "PUB" | "SUB" | "PUSH" | "PULL" | "TCP"

(* ---- family file: spec/messages/<family>.yaml ---- *)
family-file    ::= "family:" identifier
                   "version:" integer
                   "messages:" nonempty-list(message)

message        ::= "name:" identifier
                   [ "topic:" topic-pattern ]
                   "transport:" nonempty-list(transport-ref)
                   [ "doc:" doc-block ]
                   "fields:" nonempty-list(field)
                   [ "nested_types:" { identifier ":" nested-def } ]
                   [ "encoding:" { transport-ref ":" encoding-def } ]
                   [ "invariants:" list(invariant) ]
transport-ref  ::= identifier | "calf" | "balf" | "ralf"

nested-def     ::= "fields:" nonempty-list(field)

field          ::= "name:" identifier
                   "type:" type
                   [ "required:" boolean ]
                   [ "default:" scalar ]
                   [ "parse_default:" scalar ]
                   [ "unit:" unit ]
                   [ "doc:" string ]
                   [ "values:" nonempty-list(enum-name) ]
                   [ "item:" identifier ]
                   [ "validate:" validate-map ]
                   [ "deprecated_since:" version-str ]
                   [ "removed_after:" version-str ]

type           ::= "string" | "int" | "float" | "bool" | "enum" | "ticks"
                 | "nested" | "list[" type "]"

unit           ::= "display_price" | "ticks" | "shares" | "epoch_seconds"
                 | "epoch_nanos" | "percent" | "dimensionless" | "money"

validate-map   ::= "{" { validate-key ":" scalar } "}"
validate-key   ::= "gt" | "ge" | "lt" | "le"
                 | "max_len" | "min_len" | "max_items" | "pattern"

encoding-def   ::= bus-enc | text-enc | binary-enc
bus-enc        ::= "frames:" "[" frame-token { "," frame-token } "]"
                   [ "include:" include-spec ]
frame-token    ::= "topic" | "json_payload"
text-enc       ::= "msg_type:" msg-type-text
                   [ "include:" include-spec ]
                   "keys:" "{" { identifier ":" key-target } "}"
                   [ "gateway_injected:" "[" key-name { "," key-name } "]" ]
key-target     ::= key-name | "[" key-name { "," key-name } "]"
binary-enc     ::= "msg_type:" hex-byte
                   "frame_size:" integer
                   [ "price_scale:" integer ]
                   "layout:" nonempty-list(layout-entry)
layout-entry   ::= "{" "field:" identifier "," "repr:" repr "," "offset:" integer
                       [ "," "scale:" ( integer | "price_scale" ) ]
                       [ "," "enum_map:" "{" { enum-name ":" integer } "}" ] "}"
                 | "{" "reserved:" integer "," "offset:" integer "}"
repr           ::= "u8"|"u16"|"u32"|"u64"|"i8"|"i16"|"i32"|"i64"
                 | "f32"|"f64"|"char[" integer "]"
include-spec   ::= "all" | "[" identifier { "," identifier } "]"

invariant      ::= "rule:" invariant-expr "message:" string
doc-block      ::= [ "motivation:" string ] [ "since:" version-str ]
                   [ "see_also:" "[" string { "," string } "]" ]
                   [ "example_note:" string ]
```

### B.20 Complete worked example (exercises every construct)

The following single family file exercises every feature of the grammar —
bus/text/binary encodings, `all` and explicit `include`, one-to-many `keys`,
`gateway_injected`, `nested_types` + `list[nested]`, every `type`, every
`validate` key, `enum_map`, `scale`/`price_scale`, `reserved` padding, an
`invariant`, a full `doc` block, deprecation keys, and a parameterised topic.

```yaml
family: sample
version: 2

messages:
  # --- bus + text projections, parameterised topic, invariant, deprecation ---
  - name: order_ack
    topic: "order.ack.{gateway_id}"          # {gateway_id} MUST be a field
    transport: [engine_pub, ralf]
    doc:
      motivation: "Acknowledge acceptance or rejection of a new order."
      since: "1.0"
      see_also: ["order.new", "order.fill.{GW_ID}"]
      example_note: "reason is empty on ACCEPTED."
    fields:
      - { name: gateway_id, type: string, required: true, validate: { max_len: 32 } }
      - { name: order_id,   type: string, required: true, validate: { max_len: 64, pattern: '^[0-9]+$' } }
      - name: status
        type: enum
        values: [ACCEPTED, REJECTED]
        required: true
      - { name: reason, type: string, required: false, default: "", doc: "Rejection detail.",
          validate: { max_len: 128, min_len: 0 } }
      - name: limit_price
        type: float
        required: false
        unit: display_price
        validate: { gt: 0 }
      - name: order_type
        type: enum
        values: [LIMIT, MARKET]
        required: true
      - { name: legacy_flag, type: bool, required: false, default: false,
          deprecated_since: "1.2", removed_after: "2.0", doc: "Superseded by status." }
      - { name: ts, type: float, required: true, unit: epoch_seconds }
    invariants:
      - rule: "limit_price > 0 or order_type == 'MARKET'"
        message: "limit orders require a positive price"
    encoding:
      engine_pub:
        frames: [topic, json_payload]
        include: all
      ralf:
        msg_type: ACK
        include: [order_id, status, reason]
        keys: { order_id: [OID, ORDER_ID], status: ST, reason: RSN }
        gateway_injected: [CH, GW, TS]

  # --- nested + list[nested] projection over the bus ---
  - name: book_snapshot
    topic: "book.{symbol}"
    transport: [engine_pub]
    fields:
      - { name: symbol, type: string, required: true, validate: { max_len: 16 } }
      - { name: depth,  type: int,    required: true, unit: dimensionless, validate: { ge: 1, le: 50 } }
      - { name: bids,   type: list[nested], item: level, required: true, validate: { max_items: 32 } }
      - { name: asks,   type: list[nested], item: level, required: true, validate: { max_items: 32 } }
    nested_types:
      level:
        fields:
          - { name: price, type: float, required: false, unit: display_price }
          - { name: qty,   type: int,   required: true,  default: 0, unit: shares }
          - { name: count, type: int,   required: true,  default: 0, unit: dimensionless }

  # --- binary-only message: full layout, scale, enum_map, reserved padding ---
  - name: execution_report
    transport: [balf]                          # no `topic:` — not a bus message
    fields:
      - { name: client_order_id, type: int,    required: true, unit: dimensionless }
      - { name: order_id,        type: string, required: true, validate: { max_len: 16 } }
      - { name: fill_price,      type: float,  required: true, unit: display_price, validate: { gt: 0 } }
      - { name: fill_qty,        type: int,    required: true, unit: shares }
      - { name: timestamp_ns,    type: int,    required: true, unit: epoch_nanos }
      - { name: symbol,          type: string, required: true, validate: { max_len: 8 } }
      - name: side
        type: enum
        values: [BUY, SELL]
        required: true
      - name: status
        type: enum
        values: [NEW, PARTIAL, FILLED, CANCELLED]
        required: true
    encoding:
      balf:
        msg_type: 0x20
        frame_size: 64           # 8-byte header + 56-byte body
        price_scale: 100000000
        layout:
          - { field: client_order_id, repr: u64,      offset: 0  }
          - { field: order_id,        repr: char[16], offset: 8  }
          - { field: fill_price,      repr: i64,       offset: 24, scale: price_scale }
          - { field: fill_qty,        repr: u32,       offset: 32 }
          - { field: timestamp_ns,    repr: u64,       offset: 36 }
          - { field: symbol,          repr: char[8],   offset: 44 }
          - { field: side,            repr: u8,        offset: 52, enum_map: { BUY: 1, SELL: 2 } }
          - { field: status,          repr: u8,        offset: 53, enum_map: { NEW: 0, PARTIAL: 1, FILLED: 2, CANCELLED: 3 } }
          - { reserved: 2, offset: 54 }     # pad body to 56 bytes -> frame_size 64
```

If a construct is needed that this grammar cannot express, that is a defect in
this appendix and MUST be resolved by extending §B.19 (and this example) — not
by an ad-hoc key in a single spec file.

### B.21 Coverage check

Every construct used anywhere in this document is defined above:

| Construct (first used in) | Defined in |
|---|---|
| `family` / `version` / `messages` (§4.1) | §B.5 |
| `topic` with `{param}` (§4.1, §5.1) | §B.3, §B.6, §B.18 r2–3 |
| `transport` list, registry, `calf`/`balf`/`ralf` (§4.4) | §B.4, §B.6 |
| `doc` block: motivation/since/see_also/example_note (§4.1) | §B.16 |
| `fields`, all `type` values (§4.1, §4.2) | §B.7, §B.9 |
| `unit` enumeration (§4.2) | §B.11 |
| `validate` keys gt/ge/lt/le/max_len/min_len/max_items/pattern (§4.3) | §B.12 |
| `required` / `default` / `values` (§4.1) | §B.7 |
| `parse_default` (§5.1.1, §12.1) | §B.7, §B.7.1 |
| `nested_types`, `item`, `list[nested]` (§4.1) | §B.8, §B.9 |
| `encoding.bus` `frames`/`include` (§4.1) | §B.13 |
| `encoding.calf`/`ralf` `msg_type`/`include`/`keys`/`gateway_injected`, one-to-many keys (§4.1, §4.6) | §B.13, §B.14 |
| `encoding.balf` `msg_type`/`frame_size`/`price_scale`/`layout` (§4.1) | §B.13 |
| layout `repr`/`offset`/`scale`/`enum_map`/`reserved` (§4.1, §5.2) | §B.10, §B.13 |
| `invariants` `rule`/`message` + expression language (§4.3) | §B.15 |
| `deprecated_since` / `removed_after` (§4.5) | §B.7, §B.17 |
| determinism guarantee (§7.2) | §B.17 |
| strict-loader / lint rules (§7.3, §A.2) | §B.18 |
| parsing, source spans, coded diagnostics, expression scanner (§7.5) | §B.18 (loader rule), §B.15 (expression grammar) |

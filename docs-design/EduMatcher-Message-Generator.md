Version: 1.10.0

Date: 2026-08-08

Changes in 1.10.0 — Phase 5.0 and 5.1a.

- **`pm-msgen grep-literals`** (§7.4) built; `trade`'s 26 topic literals across
  14 subscribers driven to **zero**, closing §1.2 for that family.
- **Two new field keys, `nullable` and `omit_when_none`** (§B.7.0). The
  `order.*` events omit keys rather than defaulting them, and the IDL could not
  say so. Verified before adding: absence and `null` are indistinguishable to
  every consumer in this system, so one flag suffices and no tri-state is
  needed.
- **§B.18 rule 5 refined**: a topic parameter need not appear in the bus
  payload. `order.ack.{gateway_id}` names the gateway in the topic, and the
  hand-written builder never repeated it in the body.
- **`parse_*` now recovers topic parameters from the topic.** Without it,
  `parse_order_ack` returned a message with an empty `gateway_id` — found by a
  test written for 5.1a.
- **One accepted wire change**: a MARKET order's `order.ack`/`order.fill` no
  longer carries `"price": null`. Semantically invisible; see §B.7.0.
- **§14 added**: a full decomposition of the engine latency the generator adds,
  what is irreducible, and which optimisations remain.

Changes in 1.9.0 — Phase 4b (BALF binary) is implemented, and it began by
finding a live defect that this design had propagated:

- **§4.1's `execution_report` layout was wrong** — `frame_size: 72`,
  `order_id` as `char[16]`, everything after it shifted eight bytes. It was
  taken from `docs/examples/balf/balf_parser.py`, which disagrees with the
  normative protocol reference, the gateway codec and the gateway's tests. The
  example is eight bytes too large on **all six messages carrying an
  `order_id`**, because it models that field as a sixteen-byte string where the
  protocol defines a `u64`. §4.1 now follows
  `docs/user-guide/910-app-balf-protocol.md`.
- **§12.4 listed the old layout as verified.** The verification was real; the
  source was wrong. Withdrawn, with the reasoning kept — see §13.6, where it is
  the clearest evidence in this document that the problem §1 describes is real.
- The example parsers are corrected as part of this phase, and a test now
  asserts their frame-size table against `codec.py`'s.

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
`msg_type`, sizes and the fixed price scale are taken from
`docs/user-guide/910-app-balf-protocol.md` — which declares itself "the
**normative reference** for BALF `1.0.0`" — and cross-checked against
`src/edumatcher/balf_gwy/codec.py`, the gateway that actually emits these
frames. See the correction note below.

```yaml
  - name: execution_report
    # BALF-only: a private per-order fill sent to the owning gateway session.
    # This is NOT the public trade.executed print — different transport,
    # different field set (see §4.6 on why they are separate messages).
    transport: [balf]

    fields:
      - { name: client_order_id, type: int,    required: true, unit: dimensionless }
      - { name: order_id,        type: int,    required: true, unit: dimensionless }
      - { name: fill_price,      type: float,  required: true, unit: display_price, validate: { gt: 0 } }
      - { name: fill_qty,        type: int,    required: true, unit: shares }
      - { name: remaining_qty,   type: int,    required: true, unit: shares }
      - { name: timestamp_ns,    type: int,    required: true, unit: epoch_nanos }
      - { name: symbol,          type: string, required: true, validate: { max_len: 8 } }
      - { name: side,            type: enum,   values: [BUY, SELL], required: true }
      - { name: status,          type: enum,   values: [PARTIAL, FILLED], required: true }

    encoding:
      balf:
        msg_type: 0x20                 # MSG_EXECUTION_REPORT
        frame_size: 64                 # header(8) + body(56); MUST equal codec.FRAME_SIZE[0x20]
        # Fixed 8-byte header (magic=0xBA, version=0x01, msg_type, flags,
        # seq_no u32 LE) is prepended automatically by the generator.
        price_scale: 100000000         # PRICE_SCALE = 1e8, FIXED for all BALF prices — never tick_decimals
        layout:                        # little-endian, offsets relative to body
          - { field: client_order_id, repr: u64,     offset: 0  }
          - { field: order_id,        repr: u64,     offset: 8  }
          - { field: fill_price,      repr: i64,     offset: 16, scale: price_scale }
          - { field: fill_qty,        repr: u32,     offset: 24 }
          - { field: remaining_qty,   repr: u32,     offset: 28 }
          - { field: timestamp_ns,    repr: u64,     offset: 32 }
          - { field: symbol,          repr: char[8], offset: 40 }
          - { field: side,            repr: u8,      offset: 48, enum_map: { BUY: 1, SELL: 2 } }
          - { field: status,          repr: u8,      offset: 49, enum_map: { PARTIAL: 1, FILLED: 2 } }
          - { reserved: 6, offset: 50 }  # must be zero; pads the body to 56
```

> **Correction (1.9.0). Versions up to 1.8.0 printed this example with
> `frame_size: 72`, `order_id` as `char[16]`, and every field after it shifted
> by eight bytes.** That layout was taken from
> `docs/examples/balf/balf_parser.py`, which is wrong. The example parser models
> `order_id` as a sixteen-byte string where the protocol defines a `u64`, and it
> is consequently eight bytes too large on **every one of the six messages that
> carries an `order_id`** — `ORDER_ACK`, `CANCEL_ORDER`, `CANCEL_ACK`,
> `AMEND_ORDER`, `AMEND_ACK` and `EXECUTION_REPORT`. The normative document, the
> gateway codec and the gateway's unit tests (which assert `side` at body offset
> 48) all agree with each other and against the example.
>
> §12.4 of this document listed the old layout under "claims that checked out",
> having verified it against `balf_parser.py:139-161`. The verification was
> real; the source was wrong. That is worth more than an erratum — it is this
> design's own thesis demonstrated on itself. One message described in four
> places, no declared authority, and the copy a customer is pointed at is the
> broken one. See §13.6.

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
- ~~§4.1's BALF `execution_report` layout matches
  `docs/examples/balf/balf_parser.py:139-161` byte-for-byte.~~ **Withdrawn in
  1.9.0.** It did match that file, and that file is wrong. The normative
  reference (`910-app-balf-protocol.md`), `balf_gwy/codec.py` and
  `tests/test_balf_gwy_unit.py` all say `frame_size 64`, a 56-byte body, and
  `order_id` as `u64`. Only `PRICE_SCALE = 100_000_000`, `magic 0xBA` and
  `version 0x01` survive from the original claim. See the correction note in
  §4.1 and the lesson in §13.6.
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
| 1 | One canonical file per family; everything else generated | **partial** — 2 families of ~15 (`trade`, `order`); 11 messages. `order` is complete except `order.combo`/`order.oco`, which §15 shows the IDL cannot express |
| 2 | Generated Python: typed payload, validating constructor, parser, topic constant | **done**, plus `describe_*`, `FAMILY_TOPICS`, `make_*_unchecked`, `project_*`/`parse_*_calf` |
| 3 | Generated C | **done** — text (4a) and binary (4b): typed struct, enum + `to_str`/`from_str`, parser, validator, `strerror`, for both CALF key-value lines and BALF fixed frames |
| 4 | Generated documentation appendix | not started (Phase 6) |
| 5 | Validation declared once, enforced by *both* bindings | **done for CALF** — `price > 0` and `quantity > 0` are enforced in Python and in C from one declaration, and a test asserts the two reject the same values |
| 6 | Documentation-only metadata that never reaches the wire | **done** — `doc.motivation`/`since`/`see_also`/`example_note`, surfaced through `describe_*` and the generated C block comments |
| 7 | **A CI check that fails on drift** | **done** — `make check` and CI; see 13.3 |

### 13.2 Against the §1 measurements

| §1 finding | Then | Now |
|---|---|---|
| 1.1 Payload shape typed for 7 of 92 messages | 7 typed by hand | 1 of those 7 now *generated* from a declared spec with units and constraints; the other 6 unchanged |
| 1.2 Topic names duplicated as literals in subscribers | `"trade.executed"` in 17 modules | **zero.** Phase 2 removed 3 (`engine/main.py`, `stats/main.py`, `models/message.py`); Phase 5 removed the remaining 26 across 14 subscribers. `pm-msgen grep-literals` reports `trade: 0 literals - migrated`, and `tests/test_msgen_literals.py` fails the suite if one returns. |
| 1.3 Documentation drifts in both directions | unchanged | unchanged — Phase 6 |
| 1.4 The C surface has no message types | a generic `calf_field_t` bag; every client re-derives field names as literals | **Two messages now have typed C structs** — `trade.executed`'s CALF projection and `execution_report`'s BALF frame — with real enums, parsers, validators and a shared `strerror`. `calf_subscriber.c` and `balf_parser.c` use them. The bag remains for every other message. |
| — (found in 4b) | `docs/examples/balf` disagreed with the gateway on **6 of 12 frame sizes**, undetected | corrected, and guarded by a test comparing the examples' table against `codec.py` |

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

### 13.4b What Phase 4b actually proved

The capstone is complete: assertions 4 and 5 both hold, for a text projection
and for a binary frame, against compiled C. But the result worth recording is
narrower and sharper.

**The generated binary binding is byte-identical to the production gateway.**
`serialise_execution_report_balf(payload, seq_no=7)` equals
`codec.build_execution_report(...)` for every case tested, including the
extremes (`order_id = 2^64-1`, `fill_price = 1e-8`, `remaining_qty = 2^32-1`).
That is what makes the spec trustworthy: it was written from the normative
document, and the gateway is the thing that actually reaches a client, so
agreement between the two is the only evidence that the reading was right.

**The layout-coverage rule (B.18 r10) is the rule that pays.** Requiring every
body byte to be covered exactly once, with gaps as explicit `reserved` runs, is
what turns "eight bytes short of `frame_size`" from an invisible defect into a
load-time error naming the uncovered range. The wrong example parser had
exactly that shape.

**`-Werror` caught two real generator bugs** that a human reviewer plausibly
would not have: readers emitted in alphabetical order, so `edu_rd_i64` called
`edu_rd_u64` before its declaration; and a `ge: 0` rule emitted as
`unsigned < 0`, which gcc rejects as always-false. The second is interesting —
the rule is genuinely vacuous on an unsigned wire type, so the generator now
omits it in C and keeps it in Python, where the value is signed and the check
means something.

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

- Phase 4b (§4.1): the BALF layout *looked* verified — §12.4 said so, against a
  file called "Reference BALF parser" that the user guide offers customers. It
  disagrees with the normative specification on six of twelve frame sizes.

**The Phase 4b finding deserves its own note**, because it is this design's
argument made against the design itself. §1 says a message is described in
several places with no authority and that the copies drift. `EXECUTION_REPORT`
is described in four: the normative appendix, the gateway codec, the gateway's
tests, and the customer reference parser. Three agree. The fourth — the one a
customer is told to copy — is wrong, and has been wrong on six message types by
exactly eight bytes each, because it models `order_id` as a sixteen-byte string
where the protocol defines a `u64`.

Nobody noticed because nothing compared them. The example has a self-test, and
it passes: it checks the parser against frames the *same file* built. That is
the failure mode §7.2 exists to close, and it is why the capstone's
cross-language assertion is the one that matters — a binding that only agrees
with itself proves nothing.

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

### 13.7 After Phase 5.1

Three more instances of 13.6's pattern, all found by executing rather than
reviewing, and all in the same direction — *the code knew something the design
did not*:

1. **The "two shapes" of `order.new` were one contract.** The fork dissolved on
   reading `Order.from_dict`, which states its requirement field by field and
   maps exactly onto the three presence regimes. The general rule that fell out
   — *describe what the consumer requires, then reproduce the dominant
   producer's bytes* — also explains why 5.1a and 5.1b reached opposite answers
   on `omit_when_none` from the same principle.
2. **`price` means ticks inbound and display money outbound.** Copying 5.1a's
   field definitions into 5.1b would have typechecked and been wrong on the
   wire. `unit:` exists precisely to make that visible, and it did.
3. **The emitter's black reproduction had drifted, unmeasured.** Nothing checked
   it until an eight-value enum pushed a line past 88 columns. The fix was not
   to reproduce three more black rules but to remove the need for them (named
   enum aliases), plus a test that runs black over the committed output.

And one new item for the pattern itself: **two latent bugs were found by the
post-phase holistic review, not by the build.** A one-value enum's `_VALUES`
tuple would have been emitted as a plain string when split, and nothing
prevented an alias name from colliding with a class name. Both would have
produced valid, black-clean Python that passed `pm-msgen check` and meant
something different. That is the failure mode this design is least protected
against, and it argues for keeping the review step rather than treating a green
build as sufficient.

## 14. Engine latency: where the added microsecond goes

Phase 2 replaced the dict literal in `engine/main.py::_publish_trade` with a
generated constructor, and that made the engine's trade-publication path
measurably slower. This section answers three questions properly, because a
trading engine is the wrong place to wave a hand: **how much**, **why**, and
**how much of it could be recovered.**

All figures below are `min` of 7 repeats × 400 000 iterations, CPython with
`orjson`, one machine. Absolute values will differ elsewhere; the *ratios* and
the *decomposition* are the point.

### 14.1 The measurement

| Construction | µs/call | vs. hand-written | of which orjson |
|---|---|---|---|
| `orjson.dumps` of an already-built dict | 0.511 | −0.444 | 100 % |
| hand-written inline dict literal (pre-Phase-2) | 0.955 | — | 53 % |
| generated, no coercion | 1.133 | **+0.178** | 45 % |
| generated, numeric coercion only | 1.225 | **+0.270** | 42 % |
| **generated, full coercion (ships today)** | **1.507** | **+0.551** | 34 % |

Decomposed, the +0.551 µs is:

| Component | Cost | Recoverable? |
|---|---|---|
| Call shape: keyword parameters + a dict built in a callee, versus a literal inlined at the call site | +0.165 µs | **No** — not while the builder is a function |
| Coercion: eleven `str()`/`int()`/`float()` calls | +0.393 µs | **Partly** — see §14.3 |

### 14.2 What is irreducible, and why

**Roughly half of the *original* call was never ours.** `orjson.dumps` alone is
0.511 µs of the hand-written 0.955. Whatever the generator does, that half
stands. Framing the change as "+58 % slower" is arithmetically true and
misleading; the honest framing is that a fixed 0.51 µs of serialisation now
carries 0.72 µs of Python around it instead of 0.44 µs.

**The +0.165 µs call-shape cost is structural.** A dict literal written inline
compiles to `BUILD_MAP` over constants already on the stack in the caller's
frame. Routing the same values through a function costs a frame push, keyword
binding for eleven parameters, and the return — and buys the thing the whole
design exists for: the field list lives in one place. There is no way to have a
generated *function* and not pay for the function. The only constructions that
avoid it are ones that put the literal back at the call site, which is precisely
what was removed.

So: **no, the generated code cannot be made as fast as the hand-written literal**,
and the reason is not inefficiency in what was generated. It is that a shared
definition is a call and a copied definition is not. The floor for any generated
builder here is ~1.13 µs against 0.96.

### 14.3 What could still be recovered — and what it would cost

Coercion is the +0.393 µs, and the surprise is that it is almost entirely
**call overhead, not conversion work**: ~36 ns × 11 fields. `str()` on a `str`
and `float()` on a `float` return the argument unchanged; CPython still pays for
the call.

Three things were measured, one of which is counter-intuitive:

**(a) Binding `dumps` and the builtins to locals: ~0.03 µs.** Replacing
`_msg.dumps(...)` with a name bound at import removes one attribute lookup per
call, and binding `str`/`int`/`float` to module globals or default arguments
removes a builtins-dict lookup each. Measured saving is at the edge of noise
(0.028 µs) and the default-argument variant was *slower*. **Not worth the
readability cost of a generated file full of `_s(...)`, `_i(...)`.**

**(b) A type test instead of a call is slower.** The natural idea —
`price if price.__class__ is float else float(price)` — measured **1.370 µs
against 1.507**, saving less than skipping coercion entirely, and it is *worse*
than the numeric-only option below while being much harder to read. `LOAD_ATTR
__class__` plus `IS_OP` plus a branch is not cheaper than a builtin call in
modern CPython. Recorded because it looks like an obvious win and is not.

**(c) Coercing only the numeric fields: +0.270 µs instead of +0.551 — a real
halving.** This is the one genuine optimisation available, and it rests on a
precise observation about what a type checker can and cannot catch:

| Declared | A caller could wrongly pass | Does mypy reject it? |
|---|---|---|
| `str` (string, enum) | `42` | **Yes** — `int` is not `str` |
| `int` / `ticks` | `1.5` | **Yes** — `float` is not `int` |
| `int` / `ticks` | `True` | **No** — `bool` subclasses `int`; would serialise as `true` |
| `float` | `100` | **No** — the numeric tower promotes `int` to `float`; would serialise as `100` |

`make_*_unchecked` takes explicit keyword-only typed parameters, so a static
checker already guards the rows it can. Only the two rows it *cannot* guard need
a runtime call. For `trade` that is four fields instead of eleven, and the
measured overhead falls from +0.551 to +0.270 µs — a 51 % reduction — while
still fixing `price=100` → `100.0` and `quantity=True` → `1`.

**Why it is not applied.** One caller shape defeats it:
`make_*_unchecked(**payload)` where `payload` is a `dict[str, Any]`. A type
checker gives up on `**`-unpacking, so a string field would go out as a JSON
*number* rather than a string — a silent change of wire *type*, which is worse
than the value-formatting difference full coercion prevents. `_unchecked`
currently promises frames byte-identical to `make_*` **for any input**; option
(c) weakens that to "for input a type checker has seen".

That is a defensible trade — 0.28 µs of engine latency against a guarantee that
only holds at typed call sites — but it is a **deliberate change to a documented
contract, not a micro-optimisation**, and it should be taken (if at all) with a
measurement showing the trade path actually needs it. The engine currently calls
with explicit keyword arguments, so it would be safe *today*; the risk is the
next caller.

### 14.4 If this ever needs to be free

Two routes remove the cost entirely rather than shrinking it, and both are
larger changes than the problem currently justifies:

1. **Generate the call site, not just the callee.** If the spec also emitted the
   publisher's inline dict literal — a generated fragment inlined into
   `_publish_trade` — there would be no call and no coercion, and the field list
   would still come from one place. It trades a clean function boundary for
   generated code embedded in hand-written code, which is much harder to review
   and to keep `pm-msgen check`-able.
2. **Stop building a `dict` at all.** The payload is serialised immediately, so
   a generated function could emit the JSON bytes directly with pre-encoded key
   fragments and `bytes.join`, skipping both the dict and orjson. That could
   plausibly beat the *hand-written* version, since it removes the 0.511 µs
   floor — but it means owning a JSON serialiser, which §2's non-goals rule out
   for good reason.

Neither is recommended now. They are recorded so the question does not have to
be re-derived: the answer to "can it be free?" is *yes, by generating past the
function boundary or past orjson*, and both cost more in review surface than
0.55 µs is worth on a path that publishes once per match.

### 14.5 Guard

`tests/test_msgen_trade_perf.py` (marker `perf`) bounds the generated
constructor at 3× the hand-written literal — deliberately loose, because it is a
guard against an order-of-magnitude regression rather than a benchmark, and CI
timing is noisy. The shape it exists to catch is the one Phase 4b's review
found: `make_*_unchecked` built on `from_dict`/dataclass/`to_dict` measured
**4.03 µs**, over four times the literal, and that is what "unusable on a hot
path" looks like.

## 15. Where the IDL runs out: combo and OCO

Phase 5.1c set out to specify four topics — `order.combo`, `order.combo_cancel`,
`order.oco`, `order.oco_cancel` — and could only specify two. This section
records why, because "we skipped it" and "it cannot be expressed" are very
different statements about a design.

### 15.1 What the two structure submissions carried, and what they carry now

`order.combo` was `ComboOrder.to_dict()`, which is why it looked so hard:

| Field | Shape | Expressible? | Status |
|---|---|---|---|
| `combo_id`, `gateway_id`, `combo_type`, `tif` | scalars | yes | kept |
| `legs` | list of leg objects | needs `list[T]` + `nested` | kept |
| `id`, `timestamp`, `status` | scalars | yes | **removed** — engine-assigned |
| `child_order_ids` | list of strings | needs `list[T]` | **removed** — engine state |
| `leg_fill_qty`, `leg_statuses` | maps, integer keys stringified | **no construct** | **removed** — engine state |

`order.oco` carries two named leg objects, `leg1` and `leg2`, and no state.

`SCALAR_TYPES` is `("string", "int", "float", "bool", "enum", "ticks")`.
Appendix B names `nested` and `list[T]` as constructs the loader rejects
explicitly rather than half-supporting.

Two of the three obstacles have since been removed rather than accommodated —
the units trap in 15.2, and the state-on-the-submission problem in 15.4. What
remains is `nested` and `list[T]`, which is a normal feature request.

The pattern is worth naming, because it recurred twice within one phase: **when
the IDL cannot express a message, check whether the message is right before
extending the IDL.** Both times the wire was wrong, and the schema's inability
to describe it was the useful signal rather than the problem.

### 15.2 The units trap — found here, then fixed

Section 13.6 records "reasoning about what a consumer needs instead of reading
what it does" as this design's recurring failure. Specifying combo and OCO
surfaced a system-wide instance of it, which has since been fixed. The account
below is kept because the *shape* of the problem is the reusable part.

**What was there.** `to_ticks` returned an `int` argument unchanged, on the
convention that "an integer is already ticks". The unit of a price was
therefore carried by its runtime type, and the three inbound paths disagreed
about which side of the convention they were on:

| Path | Producer sent | Consumer did | Ambiguous? |
|---|---|---|---|
| `order.new` | ticks (all four gateways call `to_ticks`) | `if isinstance(price, float): to_ticks(...)` | yes |
| `order.combo` | ticks (`build_combo_payload`) | `if isinstance(leg.price, float): to_ticks(...)` | yes |
| `order.oco` | **display money** | `to_ticks(float(raw["price"]), ...)` — always | no |

OCO was not the broken one. It was the only *unambiguous* one; it had simply
picked the other unit. The genuine defect was that a display price of exactly
`150` was indistinguishable from `150` ticks — a silent 100x mispricing on a
two-decimal instrument, in either direction.

**The resolution.** Ticks are now the sole engine-inbound unit, converting is
the submitting gateway's job, and:

1. `to_ticks`'s int passthrough is gone; the function is total, `float → int`.
2. The three OCO gateways (`api_gateway`, `alf_console`, `alf_gwy`) convert
   before publishing, as the `order.new` and combo paths already did.
3. The two defensive `isinstance` blocks in `_handle_new_order` and
   `_handle_combo_order` are deleted — with one unit there is nothing to sniff.
4. `_handle_oco_order` **rejects** a non-integer leg price rather than
   truncating it. A gateway that forgets to convert now gets a rejection, not a
   position at 1/100th of the intended price.
5. `tests/test_wire_price_units.py` drives the real producers and asserts the
   invariant, and fails on any display float appearing in an engine-inbound leg
   payload anywhere in the suite. 29 such payloads across eight test modules
   were converted; they had passed only because the engine used to convert
   them for free.

### 15.3 What shipped in 5.1c

`order.combo_cancel` and `order.oco_cancel` are flat `{id, gateway_id}` pairs,
specified and adopted, which took the `order` family's topic-literal count to
zero.

`order.oco` followed once the IDL grew `nested`, and `order.combo` once it grew
`list[T]` (15.5). **The whole of section 15 is now resolved**: every message in
the `order` family is specified, and the family's topic-literal count is zero.

A note on the guard that covered this. `test_the_nested_topics_are_deliberately_
unspecified` asserted both topics were absent, and it **fired** when `order.oco`
landed — correctly. Its stated condition was never "stay absent" but "if you
appear, do it because the IDL grew a construct, not because the legs were
flattened away", so the fix was to turn it into the positive assertion: the
legs are still records. A guard that has to be updated when the thing it guards
changes legitimately is doing its job; one that never fires is decoration.

### 15.4 The maps were never needed — one serialiser was doing three jobs

The map problem dissolved the same way the units problem did: by reading what
the code does. `ComboOrder.to_dict()` was serving three unrelated contracts —
the `order.combo` submission, the `combo.ack` event payload, and GTC
persistence. The submission inherited the other two's fields as a result.

A submitter fills in none of `id`, `status`, `child_order_ids`, `leg_fill_qty`
or `leg_statuses`: the lists and maps are always empty and the status is always
PENDING. And the `combo.ack` state dump turned out to be read by **nobody** —
`alf_console`, `alf_gwy`, `pm-stats` and the api_gateway event stream all take
only `combo_id`, `accepted` and `reason`.

So the three roles are now three:

* `to_submission_dict()` / `from_submission_dict()` — the wire shape, five
  fields, no engine state. `id`, `timestamp` and `status` are assigned by the
  engine, which also closes a small hole: a client could previously choose its
  own internal combo id.
* `combo.ack` carries three scalars. The state dump is gone.
* `to_dict()` / `from_dict()` are persistence's alone, unchanged.

**No map now reaches any wire**, and `tests/test_combo_wire_shapes.py` asserts
it. The IDL therefore needs no map construct — which is the right outcome,
because an integer-keyed side map is a denormalisation the wire should not have
carried in the first place: `leg_fill_qty: {0: 5}` is only ever
`legs[0].filled_qty = 5`, and the list index already is the key. Should a
future `combo.ack` want per-leg fill state, it should carry it *on the legs*.

Record this as a stated exclusion rather than an omission: **the IDL does not
support maps, deliberately.** A spec that appears to need one is describing a
message that should have been a list of records.

### 15.5 `nested` (shipped) and `list[T]` (not yet)

**`nested` is implemented**, for JSON bus payloads only. A family declares
record types under a top-level `types:` block and a field references one by
name:

```yaml
types:
  OcoLeg:
    fields:
      - { name: side, type: enum, values: [BUY, SELL] }
      - { name: price, type: ticks, unit: ticks, required: false,
          nullable: true, omit_when_none: true }

messages:
  - name: order_oco
    fields:
      - { name: leg1, type: nested, ref: OcoLeg }
      - { name: leg2, type: nested, ref: OcoLeg }
```

The generator emits one dataclass per type, before the messages that embed it,
with the same `from_dict` / `to_dict` / `validate` trio a message gets. The
implementation is small because a nested type is presented to the emitters *as*
a topicless message (`_as_message`), so it borrows the existing machinery
rather than duplicating it.

Four deliberate restrictions, each an error in a spec file rather than a wrong
answer in a committed binding:

* **A record may not contain a record.** Nothing here needs deeper structure,
  and the restriction keeps both generators non-recursive.
* **No external transports.** A record inside a CALF key-value line or a fixed
  BALF frame is an unsolved layout question; the loader rejects it outright.
* **No `make_*_unchecked` for a message carrying a record.** That builder is a
  dict literal and a record has no literal form. Neither OCO nor combo is a
  measured hot path (section 14), so omitting it is more honest than emitting a
  slow function under a name that promises speed. The omission is per-message:
  `order.oco_cancel` in the same family still has one.
* **An unreferenced type is an error**, since it generates a class nothing
  constructs.

**`list[T]` is implemented too**, under the same restrictions, and carries
`min_items` / `max_items`:

```yaml
- name: legs
  type: list
  ref: ComboLeg
  validate: { min_items: 2, max_items: 10 }
```

Three notes on how it landed:

* **Two leg types, not one.** An earlier draft of this section claimed a single
  shared `leg` type could serve both topics. It cannot, and the two generated
  records show why: `ComboLeg` carries `symbol`, `quantity` and `smp_action`
  per leg, `OcoLeg` carries `trail_offset` and takes symbol and quantity from
  the OCO itself.
* **The bounds were a wire rule enforced in one place.** `ComboRequest`
  declared `min_length=2, max_length=10` in pydantic, so it held for
  `api_gateway` and for nobody else — the ALF console and gateway could submit
  a one-legged combo. Declaring it in the spec makes it a property of the
  message rather than of one producer.
* **The restrictions came for free.** `list` joined `nested` in `RECORD_TYPES`,
  so the JSON-transport-only rule and the `make_*_unchecked` omission applied
  to it without new code. That is the payoff for having written them as
  properties of "a field that embeds a record" rather than of `nested`.

**And a correction, found by the post-phase review rather than the build.** The
JSON-transport-only rule did not work. It tested
`set(message.encoding) & EXTERNAL_TRANSPORTS`, but `message.encoding` holds the
*bus* encoding only — CALF and BALF live in `text_encoding` and
`binary_encoding` — so the intersection was always empty and the guard never
fired. It was written, documented in this section, and believed for a whole
phase. It now reads `message.transport`, and a test asserts a record on a CALF
transport is rejected.

The lesson is narrow and worth stating: **a restriction with no test is a
comment.** Every other rule in section 15.5 had a test; this one had prose in a
design document, which is exactly the kind of thing this generator exists to
stop being the source of truth.

A second review find, same class: a `list` could be declared `nullable`, which
generated a `to_dict` that iterates `None`. Lists are now non-nullable by
construction — an empty list is how a list says it has nothing, and null would
be a second spelling every reader would have to handle.

### 15.6 The general rule this suggests

A message whose meaning depends on a value's *runtime type* rather than its
declared type is outside what a schema-first generator can describe. The right
response is not to teach the IDL to express the ambiguity — it is to remove the
ambiguity from the wire, which is what 15.2 did.

Stated as a design rule: **a unit belongs in a field's declaration, never in its
representation.** `unit:` exists for exactly this, and the generator can enforce
it in both bindings. A convention that encodes meaning in int-vs-float cannot
be enforced anywhere, which is why it survived undetected across three inbound
paths and 29 test payloads.

## 16. Presence, finished: the fourth regime and the pair that was a record

Phase 5.2a specified `session`, and found the last two presence shapes the IDL
could not describe. One became a construct; the other became a record.

### 16.1 `omit_when_empty` — the regime the codebase used most

`SessionStatePayload.to_dict` dropped `prev_state` with `if self.prev_state:` —
on the **empty string**, not on null. B.7.0's three regimes all key on `None`,
so none of them could say it.

This is not a session quirk. **27 hand-written builders in `models/message.py`
omit a key the same way.** It is the most common presence rule in the system and
the one the remaining families will lean on hardest.

It is deliberately narrow:

* **Strings only.** On a number, falsy-omit would silently drop a legitimate
  zero; on an enum, `""` is not a declared value.
* **Mutually exclusive with `omit_when_none`.** A field omits on `""` or on
  null, not both — two regimes, one field.
* **Implies `required: false`**, like the others.

`from_dict` reads it as `str(p.get(key, ""))`: absent and `""` are the same
thing to this regime, so it round-trips exactly.

That read is also why `omit_when_empty` and `default:` are rejected together —
a finding from this phase's holistic review rather than from the build. The
read ignores a declared default entirely, so a spec carrying both said one
thing while the generated code did another, silently. The empty string *is* the
absence here; there is nothing left for a default to supply.

### 16.2 The pair that was a record

Two field groups travelled together or not at all:

```python
if next_state and next_at:        # in two builders
if command_id and gateway_id:
```

The obvious move was a `co_present: [a, b]` constraint. **The IDL grew nothing.**
Those pairs are records that had been flattened into `a_b` names for want of
one, and `nested` had landed in 5.1d.

The reasons, in the order they mattered:

1. **A constraint describes a symptom; a record describes the thing.**
   `co_present` says "these keys travel together" and leaves *why* to a
   comment. A nullable `NextTransition` says "there is either a next transition
   or there isn't", and the co-presence is a consequence.
2. **Illegal states become unconstructible, not merely detected.** With
   `co_present` the half-set payload can be built and is rejected afterwards.
   With a record it cannot be built. This is the same move as §15.2's: replace
   a convention that must be checked with a type that cannot be wrong.
3. **It composes.** A record can be reused, nested, validated once and
   documented in one place. A constraint must be restated at every message that
   carries the pair, and two statements of it are free to differ.
4. **C decides it.** `co_present` in C is two struct members plus a `has_next`
   flag the caller must remember to test — the sentinel problem §15.2 spent a
   phase removing from prices. A nested record is a named struct and a null
   pointer, which is self-describing.

The naming argument is not decorative: `reply_to` says what
`command_id`+`gateway_id` *is* — a return address — where the flat pair could
only be described as "if both of these happen to be set, someone wants an
answer".

### 16.3 The first deliberate shape change

Every family before this was byte-identical to the code it replaced. `session`
is not: `{"next_state": ..., "next_at": ...}` became `{"next": {...}}`.

That is worth flagging as a precedent rather than letting it pass. The rule it
follows is §15.6's, widened by one word: **a unit belongs in a field's
declaration, never in its representation — and so does a relationship between
fields.** `next_state`/`next_at` encoded "these belong together" in a shared
name prefix, which is a convention no generator can enforce, in exactly the way
int-vs-float encoded a price's unit in its runtime type.

The migration cost was 21 literals across 10 modules plus three consumers, and
`tests/test_command_correlation.py` — which pins the old flat shape — is where
the change was visible. Those tests were updated, not deleted: they still
assert the *behaviour* (both or neither, scheduler gets no reply address), only
the shape moved.

### 16.4 A duplicate definition removed

`SessionStatePayload` in `models/feed_schema.py` was a hand-written copy of what
the generator now emits. Both were deleted down to one: `clearing` reads the
generated `SessionState`. Keeping both would have been two definitions of one
wire shape, free to drift — which is the failure this whole design exists to
remove, and it had been sitting in the repo the entire time.

## 17. `book` and `depth`: records at scale, and three review finds

Phase 5.2b specified the first family whose payloads are *mostly* records — a
book snapshot is two price ladders and a trade tape, three lists in one
message. It was unspecifiable in any earlier phase.

### 17.1 A topic parameter is not automatically topic-only

`book.{symbol}` names the symbol in its topic **and** carries it in the body:
`OrderBook.snapshot()` emits `"symbol"`, and every subscriber reads it from
there. The default projection rule drops a topic parameter from the payload —
which is right for `order.ack.{gateway_id}`, whose hand-written builder never
repeated it — so the first generated binding silently lost the key.

The fix is an explicit `include:` list, which §4.6's projection model already
supports. The lesson is that "named in the topic" and "absent from the body"
are two different facts, and only the second is a wire property. A default that
conflates them is fine as long as it can be overridden per message.

### 17.2 The two topics that drifted, now declared together

`make_depth_msg` published `book.depth.{symbol}` while the engine published
`depth.{symbol}` inline. Worse, `book.depth.X` matches a `book.` prefix
subscription, and pm-stats derives the symbol as everything after the first
dot — so it recorded a phantom instrument literally named `depth.AAPL`.

Both topics are now in one spec file, and a test asserts `depth.{symbol}` does
*not* match `PREFIX_BOOK_SNAPSHOT`. That is the whole argument for a single
canonical file stated in miniature: the two definitions could disagree because
they were two definitions.

### 17.3 Three bugs, none found by a test

Worth recording because the pattern is now consistent — the build catches what
the tests do not.

1. **Two lists in one `validate()` shared a loop name.** Every list emitted
   `for item in ...`, so two lists of different record types bound `item` to
   the first — Python has no block scope — and **mypy** rejected the second.
   The loop variable is now named after its field.
2. **Black splits an over-long ternary at its own keywords.** A nullable
   `float` read inside a parenthesised argument exceeded 88 columns even after
   parenthesising, and the emitter had no rule for the next split. Caught by
   `test_generated_files_are_black_clean`.
3. **List bounds were never checked for sanity.** `min_items: 5, max_items: 2`
   loaded, generated, passed `pm-msgen check` — and would have failed *every*
   message at runtime with nothing pointing at the rule. Negative bounds were
   accepted too. Found by the post-phase review probing the loader with specs
   nobody had written yet.

The third is the one to generalise: **a validation rule can itself be invalid,
and the loader is the only place that can say so.** Every rule the IDL grows
should be asked whether it has an unsatisfiable configuration, and if it does,
that configuration belongs in the loader's rejection set rather than in a
runtime failure.

## 18. `log`: lists of scalars, and a rule that moved house

Phase 5.2c specified the five subscriber to pm-log-srv control messages.

### 18.1 `list` learned `item:`

`LogFilter`'s `processes`, `loggers` and `sessions` are lists of plain strings.
`list` required `ref:` naming a declared record, so it could not describe them.

This is an ordinary feature gap, not a wire problem: `["engine", "gateway"]` is
a list of names, not a flattened record. So `list` now takes **either**
`ref: <TypeName>` for records or `item: <scalar>` for scalars, and exactly one
of the two. `enum` and `ticks` are excluded as element types — an enum needs
`values:` per element, and a tick list has no use here; a record is the answer
if the elements need rules.

A scalar list keeps its `make_*_unchecked`, since it embeds no record.

### 18.2 The record restriction was narrowed, not lifted

"A nested type's fields are scalars only" (15.5) existed to keep both
generators non-recursive. A list of *strings* is flat, so it was never the
thing being excluded — the rule was simply written more broadly than its
reason. A record may now hold a scalar list; a record, or a list of records,
inside a record is still rejected.

Worth generalising: **when a restriction blocks something, check whether it
blocks it for the stated reason.** This one did not, and the fix was to narrow
the rule to its justification rather than to carve out an exception.

### 18.3 Three bugs, and one of them was a regression

1. **`default: []` on a list did not import.** Python rejects a mutable
   dataclass default outright, so the generated module raised `ValueError` at
   class creation. The emitter now uses `field(default_factory=list)`, and the
   loader rejects any non-empty list default — a value nobody chose would
   otherwise appear on the wire as if they had.
2. **An optional list read through a strict subscript.** `p["loggers"]` raised
   on a payload that simply had nothing to say. Absent and empty are the same
   thing to a list, so it reads `p.get(key, [])`.
3. **A regression, found by the review.** The "a list may not be nullable"
   rule from 15.5 lived inside the loader's *record* branch. When `list` learned
   `item:`, a scalar list took a different branch and slipped past it. The rule
   was still tested — but only for record lists, so nothing noticed.

The third is the one to remember, and it sharpens 17.3's lesson. A tested rule
is not a safe rule if the test only covers one path into it. **When a construct
grows a second form, every rule about the first form needs re-asking against the
second** — the loader is one function, but its branches are not.

Scalar rules (`max_len`, `gt`, `pattern`, …) on a list are now rejected too:
they silently did nothing, which is worse than either enforcing or refusing.

## 19. `log` server-side: two exclusions, two different answers

Phase 5.2d specified pm-log-srv's ten outbound topics. Two of the IDL's
declared exclusions stood in the way, and asking about each separately is what
kept the answers from being the same.

### 19.1 Depth was a rule broader than its reason

`log.status` carries a subscription, and a subscription carries its own filter
— a record two levels deep, which "a nested type's fields are scalars only"
forbade.

That rule's stated justification was keeping both generators non-recursive. But
`SubscriptionStatus` embedding `LogFilter` is not recursion: it is one more
level, statically known, with no cycle. **What the generators cannot survive is
a cycle, not depth.**

So the restriction became a cycle check:

* A record may embed another record, or a list of them, to any depth.
* The loader walks the reference graph and **rejects cycles**, naming the path:
  `types form a reference cycle (Outer -> Inner -> Outer)`.
* Types are emitted in **dependency order**, not declaration order, since the
  generated dataclasses reference each other by name at class-definition time.
  A spec may therefore declare its types top-down and read naturally.

The alternative was flattening — `subscription_filter_min_level` and friends —
which is precisely the `a_b` flattening §16.2 argued against. This is now the
third time the same narrowing has happened (§18.2 for scalar lists, §15.2 for
units), and the pattern is worth stating plainly: **when a restriction blocks
something, check whether it blocks it for the stated reason.** Twice out of
three times the rule was simply written more broadly than its justification.

### 19.2 The map was the wire being wrong

`log.notify` carried `levels: {"INFO": 3, "ERROR": 1}`. §15.4 already recorded
maps as a deliberate exclusion, with the reasoning that a spec appearing to
need one is describing a message that should have been a list of records.

That was exactly true here: the key was a *value* — the level name — so
`[{"level": "INFO", "count": 3}, ...]` says the same thing with the level as a
field. The server now emits that shape, and `test_log_srv_pubsub.py` was
updated rather than deleted: it still asserts the counts, only the traversal
changed.

The contrast with 19.1 is the useful part. Both were exclusions; one was the
rule being wrong and one was the wire being wrong, and only reading each case
told them apart.

### 19.3 Two more emitter bugs, both from the toolchain

1. **An `omit_when_empty` field defaulted to `None` in the hot-path builder's
   signature**, against a `str` annotation — it declares no `default:`, since
   the empty string is its absence, so `f.default` was None. Caught by mypy.
2. **An always-emitted nullable record's `to_dict` entry was not wrapped**, so
   a long one exceeded 88 columns. The omitted branch wrapped; the always
   branch did not. Caught by `test_generated_files_are_black_clean`.

### 19.4 Five guards fired, and all five were updated

The depth narrowing broke five tests written in 5.1d and 5.2c that asserted
"a record may not contain a record". Every one was **updated rather than
deleted**, and each now asserts the new boundary — depth allowed, cycles
rejected — with a docstring saying when and why it moved. A guard that fails
when the rule it guards changes deliberately is doing its job; the discipline
is to move it rather than remove it.

## 20. `index`: the last flattened record, and a rule narrowed a fourth time

Phase 5.2e specified the `index` family's ten topics. The spec and the binding
are committed; **adoption is deliberately a separate phase** (5.2f), for the
reason §20.6 gives.

### 20.1 The third paired-presence group, and the evidence that it is the last

`make_index_update_msg` carried the shape §16.2 named:

```python
if day_open is not None:
    payload["day_open"] = day_open
    payload["day_high"] = day_high
    payload["day_low"] = day_low
```

Three keys, one guard, all-or-nothing — the same thing as `session`'s
`next_state`/`next_at` and `command_id`/`gateway_id`, one field wider. It is
now a nullable `DaySummary { open, high, low }`, and the producer confirms the
reading rather than merely permitting it: `_update_day_ohlc` sets all three in
one branch and `_reset_for_new_session` clears all three, so no state has ever
existed where one is known and another is not.

Three instances is enough to state the rule generally: **an `a_b`-prefixed
group of fields sharing one guard is a record that was flattened for want of
one.**

It is also, on the evidence, the last one. §20's investigation grepped
`risk`'s 30 topics before locking the shape, precisely because three instances
suggested a fourth. There is none: every guard across the whole `risk` family
is single-key — `if command_id:`, `if note:`, `if level:` — which is regime 4,
not a flattened record. Checking cost one grep and removed the possibility of
discovering a fourth instance mid-`risk`.

### 20.2 `omit_when_empty` was narrower than its reason — the fourth time

`index.history` replays a five-shape union from an append-only JSONL archive:
INIT, CORP_ACTION, ADD_CONSTITUENT, DELIST, REBALANCE. Two of the five carry a
list — INIT's `constituents`, REBALANCE's `symbols` — and a list is always
emitted, so one `HistoryRecord` would have added `"constituents": []` and
`"symbols": []` to the four record types that have neither.

That is a change to **already-written data**. The archive is the wire here:
`IndexHistory.query` reads JSONL off disk and passes the dicts straight
through. Specifying the family would have rewritten history.

`omit_when_empty` was strings-only. Its stated reasons are that falsy-omit
would silently drop a legitimate zero on a number, and that `""` is not a
declared value of an enum. **Neither applies to a list.** §18.3 had already
established the opposite for the read side: absent and empty are the same
thing to a list, which is why an optional list reads through `p.get(key, [])`.
A list that omits when empty is therefore exactly symmetric with its own read,
and round-trips byte for byte.

So the rule was narrowed to its justification rather than carved out around.
This is the fourth time (§15.2 units, §18.2 scalar lists in records, §19.1
depth), and the tally is now worth stating as a habit rather than an
observation: **when a restriction blocks something, check whether it blocks it
for the stated reason.** Three of the four times, the rule was simply written
more broadly than its reason.

Two new rejections came with it. The first is of §17.3's class:
`omit_when_empty` together with a positive `min_items` is a loader error. A
list that must carry an item can never be empty, so the omission could never
fire and the field would silently always be present. `min_items: 0` is fine —
it says nothing.

The second came from the holistic review rather than the build, and is §18.3's
regression shape a second time. **`parse_default` on a list loaded, generated
and did nothing.** A list reads through `p.get(key, [])` in a branch that
returns before any of the `parse_default` machinery, so a declared
`parse_default: ["SENTINEL"]` never appeared in the emitted read. It had been
rejected all along — but only on the `ref:` branch, so a scalar list slipped
past exactly as the nullable rule did in 5.2c. It is now rejected for every
list, with the same objection §18.1 made to scalar `validate` rules: silently
doing nothing is worse than either enforcing or refusing.

Both are worth noting as evidence for §18.3's rule rather than as bugs:
**when a construct grows a second form, every rule about the first form needs
re-asking against the second.** That has now caught three defects across two
phases, all in the same six lines of the loader.

### 20.3 The variant type that was not built

`index.corp_action` is a discriminated union in all but name: `action` selects
which of three parameter groups the payload carries — `ratio_numerator` +
`ratio_denominator` for SPLIT, `dividend_per_share` for CASH_DIVIDEND,
`new_shares_outstanding` for SHARES_ISSUANCE — and `_handle_corp_action` reads
each with `.get(key, 0)` inside its own branch. `HistoryRecord` is the same
shape again, with five variants instead of three.

The IDL has no variant construct and did not grow one. The reasoning, against
§15.1's rule that the message should be checked before the IDL is extended:

* **The message is right.** Unlike the map in §19.2, there is no better flat
  shape hiding here. A corporate action genuinely has action-specific
  parameters, and the archive genuinely has five record shapes.
* **But one family is not evidence.** `risk`'s 30 topics contain no variant
  (§20.1's grep), so `index` would be the only user. A construct built for one
  caller is the abstraction §15.5's restrictions exist to avoid.
* **The cost is bounded and visible.** Flat optional fields describe the field
  set, the types and the units correctly — which is everything all six
  consumers need, since every one of them is a `.get`-dispatcher on the
  discriminant. What the spec cannot say is "a SPLIT requires both ratio
  fields". That rule stays in the handler.

Recorded as a **stated limitation rather than an omission**, the way §15.4
recorded maps — with the difference that maps were the wire being wrong and
this is the IDL being incomplete. `test_the_spec_cannot_say_a_split_needs_both_
ratio_fields` asserts the gap so it stays a known one. If `risk` or a later
family produces a second genuine variant, that is the point to build it.

### 20.4 A default that silently dropped a record type

`make_index_history_request_msg` defaulted `types` to `["INIT", "CORP_ACTION",
"ADD_CONSTITUENT", "DELIST"]`. `IndexHistory.query`'s own default is
`sorted(STRUCTURAL_RECORD_TYPES)`, which is those four **plus `REBALANCE`**.

So every caller taking the builder's default silently never saw a rebalance
record, and nothing errored — the request was well-formed, the reply was
well-formed, and one record type was missing from it. That is §1's failure
class exactly, in a default value rather than a field name.

The spec omits `types` when unset instead, which is what `log.subscribe` does
with `lease_sec` and for the same reason: the server applies its own default
and cannot tell an omitted value from one that happens to equal it. Declaring
the client's copy of a server-side default is how the two drift.
`max_records` keeps its default, because there the two agree.

`test_the_five_structural_types_agree_with_the_server` pins the enum against
`STRUCTURAL_RECORD_TYPES` so the two cannot part again.

### 20.5 A documented behaviour that had never been executed

§18.1 stated that a scalar list keeps its `make_*_unchecked` "since it embeds
no record". True as a decision, false as code: `_coerce_arg` looked up
`_COERCE["list"]` and raised `KeyError` at generation time.

Nothing caught it because **no committed spec had ever put a scalar list on a
message**. `log`'s three are inside `LogFilter`, and a record gets no hot-path
builder, so the branch was unreachable from every spec in the tree.
`index.history_request.types` is the first, and it crashed the generator on
the first `generate`.

This is §15.5's "a restriction with no test is a comment" pointing the other
way: a *capability* with no spec exercising it is equally a comment. The
narrow lesson is that the emitter's per-type branches need a spec that reaches
each of them, and the roadmap's families are not a plan for that — they are a
plan for the system's messages, which is a different coverage question.

Two more emitter defects came from the same message set, both from
`index_constituent_change_ack` being the longest message name in any spec and
both caught by the toolchain rather than by a test:

1. **`make_*`'s return exceeded 88 columns** when a parameterised topic
   builder and `obj.to_dict()` shared the line. Caught by
   `test_generated_files_are_black_clean`.
2. **`parse_*`'s signature exceeded 88 columns** on its own, with no wrapping
   rule for a `def` line. Same test.

Both wrapping helpers are byte-neutral for the five previously-committed
families — regenerating rewrote `index.py` and nothing else, which is the
cheapest available proof that a formatting change did not quietly reformat
the tree.

### 20.6 Why adoption is a separate phase

Every family before this was specified and adopted in one phase. `index` is
not, and the reason is worth recording rather than treating as a shortfall.

The `day` record is the second deliberate wire change in the project (§16.3
was the first), and its blast radius is larger than `session`'s: three
consumers read the flat triple — `alf_console/display.py`, `stats/main.py`'s
snapshot writer and `md_gateway/normaliser.py`'s CALF projection — and
`day_open` appears across six test modules and three user-guide chapters.
Adoption is a coherent piece of work, and half of it is worse than none: a
tree where `pm-msgen check` passes while three consumers read a key the
producer no longer sends is precisely the "no error, just wrong" state §1
describes.

So 5.2e ships the Phase 1 shape — **spec and binding committed, nothing
importing them** — and 5.2f does the ten builders, the three consumers and
the 23 literals as one change. The roadmap and the status warning in
`06-msgen.md` both say so, because a specified-but-unadopted family looks
exactly like an adopted one from the outside, and that is the misreading most
worth preventing.

### 20.7 The audit record that dropped its own input

`index/admin_cli.py`'s history renderer reads `rec.get('shares_outstanding')`
for an ADD_CONSTITUENT record, and the column had always printed empty. The
first reading was "a renderer reads a key nobody writes" — a cosmetic defect,
unrelated to this phase. That was the wrong way round, and the difference is
§13.6's recurring failure again: reasoning about the symptom instead of
reading the producer.

`_handle_constituent_change` does this:

```python
shares = int(payload.get("shares_outstanding", 0))
initial_price = float(payload.get("initial_price", 0.0))
idx.calc.add_constituent(symbol, shares, initial_price)   # shares used here
...
event_payload = {"symbol": symbol, "reference_price": initial_price, ...}
```

The share count does the work that determines the constituent's weight and is
then dropped from the audit entry. It is not a renderer reading a missing
key; it is **the structural audit log failing to record the input to a
structural change.** Three things followed from it, all real:

* The renderer printed `shares=` blank on every ADD row, while `index/cli.py`
  renders the same records and only prints `ref_price=`. Two renderers
  disagreeing about a record's contents is §17.2 in miniature.
* `pm-index-admin-cli shares --delta` could not resolve a baseline for a
  constituent added but never re-issued: `_resolve_delta` skipped
  ADD_CONSTITUENT records *because* they carried no count, and failed with
  "pass --new-shares instead" — for a symbol whose share count the operator
  had supplied one command earlier.
* The count was durably recorded nowhere. The calculator holds it in
  `_outstanding_shares`, `_persist_state` does not write it, and the only
  durable trace of any later change is a CORP_ACTION `detail="shares=1000"`
  string — a rendered summary, not a field.

So it was fixed here rather than deferred, which is §15.1's rule applying
cleanly: the IDL surfaced a wire that was wrong, and it is cheaper to correct
the record while `HistoryRecord` is being written than to specify the gap and
add the field in a later phase. The handler now records `shares_outstanding`,
the spec carries it as **optional** — the archive on disk holds records
without it, and requiring it would make the spec reject the very history it
exists to describe — and `_resolve_delta` reads it when present, falling back
to the SHARES_ISSUANCE path for older records.

The guard that pinned the old behaviour,
`test_delta_resolution_ignores_add_constituent_records`, stated its condition
as a general fact about ADD records. It is now
`..._ignores_legacy_add_constituent_records`, covering the pre-5.2e shape,
with a companion asserting `--delta` resolves from the new one. Same
discipline as §19.4: the guard moved to the new boundary rather than being
deleted, with a docstring saying when and why.

The wider point is about how the finding was nearly lost. It was written up
as "a find left alone, per the rule that a change should trace to the
request" — a correct-sounding application of a good rule to a misdiagnosis.
The surgical-change rule protects against scope creep; it is not a reason to
leave a defect undiagnosed, and "unrelated to this phase" is a conclusion that
has to be earned by reading the producer rather than assumed from the
consumer.

## 21. Adopting `index`: the defect adoption itself introduced

Phase 5.2f wired the family in. Nine of ten builders delegate, the `day`
record replaced three flat keys in three consumers, and `index` is at zero
topic literals — the sixth family to get there.

The interesting part is not the migration. It is that **adoption introduced a
denial of service**, and nothing in a 4 493-test suite noticed.

### 21.1 A bounded field fed by an unbounded one

Every rejection path in pm-index quotes the identifier it could not resolve:

```python
make_index_error_msg(gateway_id, f"Unknown index_id '{index_id}'")
```

`index_id` is `str(payload.get("index_id", ""))` — straight off the wire, no
bound. `reason` is declared `max_len: 512`, and `gateway_id` `max_len: 32`.

Before adoption the hand-written builder was a dict literal: a five-thousand
character `index_id` produced an oversized reason and an enormous topic, which
is bad and harmless. After adoption `make_*` **validates**, so the same input
raises `MessageValidationError` out of `_handle_history_request` — which has
no `try`/`except` — out of the pull dispatch, out of the run loop, and
pm-index stops. One malformed request from any client on the PULL socket kills
the index process.

Four handlers had the shape, on eight identifier reads plus a symbol inside
the rebalance loop. They clamp now, and `_clamp_id`'s docstring says why the
bound is load-bearing rather than tidy. Truncation loses nothing: an
identifier longer than the spec allows cannot name an index or a gateway that
exists, so a clamped one fails the same lookup and yields the same rejection.

### 21.2 Why the suite could not have caught it

This is the part worth generalising. The tests are not weak here — they are
comprehensive about the handlers' *logic*, including the unknown-index and
invalid-window rejection paths. They pass identifiers like `"UNKNOWN"` and
`"EDU100"`, because those are what a caller sends.

The defect needs an input **no reasonable test would write**, reaching a
validation rule that **did not exist when the tests were written**. Adoption
is exactly the moment when the second half becomes true: it is the phase that
turns a permissive producer into a validating one, so every previously
harmless input has to be re-asked against the new rules.

§12's warning about `make_trade_msg` said the same thing more narrowly — "if
something that used to publish now raises, it was publishing something the
spec says is invalid" — and framed it as a *finding*: fix the producer. That
framing is right for a producer with a bug. It is wrong for a producer
faithfully relaying hostile input, where the answer is to bound the input
rather than to loosen the spec or to accept the crash.

So the rule this phase adds: **when adoption makes a builder validate, list
every field whose value originates outside the process, and check the spec's
bound against the source's bound.** Where the source has none, the boundary
needs one. It is a five-minute audit and it is not optional, because the
failure mode is a crash on a path whose whole purpose is to handle bad input
gracefully.

### 21.3 The archive is why one builder did not delegate

`make_index_history_msg` takes the topic constant and nothing else. Its
`records` are replayed verbatim from an append-only JSONL file, so routing
them through `HistoryRecord` would coerce and validate every stored row — and
one legacy row missing a field the spec calls required would raise in the same
unguarded handler, with the same result as §21.1.

Verified rather than assumed: a probe confirmed that a row missing `level`,
and a row whose `type` the spec does not declare, both replay unchanged
through the adopted builder. §12's rule — *a recorder records what it
received* — extends to the replayer, and for the same reason. The spec states
the record's shape; the archive stays the thing that decides what a stored row
looks like.

### 21.4 What the day record removed besides three keys

`_ManagedIndex` held `day_open`, `day_high` and `day_low` as three optional
floats, and `_update_day_ohlc` had to write

```python
idx.day_high = max(idx.day_high or level, level)
```

`or`, not `is None` — so a high of exactly `0.0` would have been silently
replaced by the current level. Unreachable for an index level, and the same
falsy-versus-None confusion §16.1 made `omit_when_empty` strings-only to
avoid. The defensive read existed only because the type could not express
that the three move together; holding one optional `DaySummary` deletes both
the `or` and the question.

That is the argument in §16.2 point 2 showing up in the *producer* rather than
on the wire. A record makes the half-set state unconstructible everywhere it
is held, not merely unsendable — which is why the in-process representation
was worth changing too, rather than assembling the record at the publish call.

### 21.5 Two guards fired, one of them late

`test_make_index_history_request_msg_defaults_to_structural_types` pinned the
four-type client-side default — the very drift §20.4 found. Its stated intent
("never ask for LEVEL/EOD") survives; the mechanism does not, since the key is
omitted now. Updated to assert absence, plus that the server's own
`STRUCTURAL_RECORD_TYPES` contains neither LEVEL nor EOD and does contain
REBALANCE.

`test_msgen_session.py::test_it_is_rejected_on_a_number` fired for a change
made in **5.2e**, and should have been caught then: that phase ran seven msgen
test files and `test_msgen_session.py` was not among them, so a widened
rejection message went unnoticed for a phase. The verification lesson is
narrow and worth stating — **the msgen change set is the whole `test_msgen_*`
group, not the files the phase happens to be thinking about** — and it is the
same shape as §18.3's regression: a rule changed in one place, checked in the
places that came to mind.

### 21.6 What did not change

Three things were left flat on purpose, each because the wire is not the only
consumer:

* **pm-stats' `index_level_snapshots`** keeps `day_open` / `day_high` /
  `day_low` columns. A column per value is what SQL wants; reshaping a schema
  to mirror a message is the tail wagging the dog.
* **pm-index's state file** keeps the same three keys. It is a persisted
  diagnostic, nothing reads them back, and it is not the wire.
* **`docs/user-guide/150-market-index.md`**'s JSON sample is that state file,
  not `index.update` — so it was correctly left alone. A find-and-replace over
  `day_open` across the docs would have silently corrupted it, which is a
  small reminder that "the same three field names" is not the same thing as
  "the same three fields".

## 22. `risk`, part one: the audit that ran before adoption

Phase 5.3a specified and adopted the three kill switches — `risk.kill_switch`,
`risk.kill_switch_gateway`, `risk.kill_switch_global` and their acks. Six
topics of sixteen; the other ten are 5.3b.

### 22.1 Where the family splits, and why that boundary

`risk` divides by **what the command acts on**:

* a gateway's *exposure* — the three kill switches, at three scopes: the
  caller's own, one named participant (ADMIN only), everyone.
* an *instrument* — `symbol_halt`, `symbol_resume`, `cancel_symbol`, and the
  two circuit-breaker sweeps.

The two groups share nothing but `gateway_id` and `reason`. That is the
property that matters for a two-session phase: either half can land complete,
with its builders delegating and its literals at zero, without leaving the
other half in the state §20.6 warned about — a tree where `pm-msgen check`
passes while consumers read keys the producer no longer sends.

Splitting by *direction* — all eight submissions, then all eight acks — would
have had exactly that defect. A submission whose ack is still hand-written is
half a conversation.

Nothing in the IDL had to grow, which was known before the phase started:
§20.1 grepped all thirty of this family's guards while deciding whether
`DaySummary` was the third paired-presence group or merely the third of many.
Every one is single-key. The family is presence regimes 1 and 4 throughout —
no records, no lists, no variants.

### 22.2 A field the handler read and no producer could send

`_handle_kill_switch` did this, and had for a long time:

```python
note = str(payload.get("note", ""))
...
self._publish_admin_action(gateway_id, command_id, "kill_switch.self",
                           {"symbol": ..., "note": note, ...})
```

`make_kill_switch_msg` had no `note` parameter, and none of its four producers
— api_gateway, alf_console, commands/client, alf_gwy — sent one. So the value
was always `""`, and `kill_switch.self` was the one admin action whose note was
permanently blank while `kill_switch.gateway` and `kill_switch.global` both
recorded a real one.

This is §20.7's shape a second time, and the second time it was worth checking
rather than filing as cosmetic: the admin monitor exists, by its own comment,
so that `/admin/monitor` has *one uniform shape to watch regardless of which
command ran*. A permanently blank field in one of three sibling actions is a
gap in that uniformity, not a rendering quirk.

The message carries `note` now, `omit_when_empty` like its two siblings.
Deliberately **not** done: inventing an API parameter for it. The
self-kill-switch route is `/orders`' mass-cancel, which has no reason field,
and threading one through would be speculative surface. The field exists on the
wire and any producer with a note can send it; giving an operator somewhere to
type one is a separate, non-message change.

### 22.3 The §21.2 audit, run before adoption rather than after

§21.2's rule — *when adoption makes a builder validate, list every field whose
value originates outside the process and check the spec's bound against the
source's bound* — was written after the fact in 5.2f. This is the first phase
to run it up front, and it found the same class of defect again:

`_gateway_status` builds `f"Gateway not configured: {gw_id}"` from the inbound
`gateway_id`, unbounded, and that lands in an ack whose `reason` the spec
bounds at 512 characters.

**But the consequence is different, and only reading the dispatch showed
that.** pm-index had no exception guard, so the equivalent input killed the
process. The engine's `_dispatch_pull_message` wraps every branch in a
try/except — so no crash. What it does instead is worse in a quieter way:
`_reject_after_error` returns early for any topic outside `_ORDER_TOPICS`, and
the risk topics are outside it. So the handler's exception is logged and
counted, no ack is sent, and the caller waits for a timeout — where before
adoption it received a real, if oversized, answer.

A silent non-answer on the path whose entire job is answering is not obviously
better than a crash. The three handlers clamp their identifiers now, and
`_gateway_status` carries a docstring note saying why the bound matters, since
the coupling is not local: an unbounded id reaching that line becomes a
validation error two calls away, inside a generated constructor.

The generalisation worth keeping: **"is it guarded?" is not the same question
as "is it safe?"** A guard converts a crash into a dropped reply, and whether
that is an improvement depends entirely on what the caller does next.

### 22.4 The emitter learned black's quoting rule

`kill_switch.symbol`'s doc is the first text in any spec containing a double
quote — *`"" cancels across all of them`*. The emitter escaped it, producing
`"\"\" cancels..."`. Black would rather switch the outer quotes than escape:
a string containing `"` and no `'` is emitted single-quoted.

Caught by `test_generated_files_are_black_clean`, which is now four for four
across phases — every formatting defect this generator has had was found by
running black over the committed output rather than by any test in the
generator's own suite. That is the right division: the emitter reproduces
black's rules (risk R9), so the check that it did so correctly has to be black
itself.

Worth recording how nearly it was missed. A blanket `black src/ tests/` during
verification *reformatted the generated file*, which turned one clear failure
into three confusing ones — `pm-msgen check` reporting drift, the
reproducibility test failing, and the black-clean test failing — none of which
named the actual cause. **Never run a formatter across `src/` while verifying
a generator**: it repairs the evidence. Format the hand-written tree, and let
the committed bindings be checked, not fixed.

### 22.5 A report that is true and misleading

`pm-msgen grep-literals` counts literals of *declared* topics, per family. With
six of sixteen topics declared it prints:

```
risk: 0 literals - migrated
```

while ten `risk.*` topics are still hard-coded in four modules. Every word of
that is accurate and the line as a whole is not, because "migrated" has meant
"this family is done" in every previous phase.

No code changed for this — the count is correct and a half-specified family is
a new situation, not a bug. What changed is that `risk` stays out of `MIGRATED`
in `tests/test_msgen_literals.py` until 5.3b, and both this document and
`06-msgen.md` say why. A test asserts the omission, so finishing 5.3b without
adding it fails rather than passing quietly.

### 22.6 Two lines that should not have been touched

A scripted edit matched `gateway_id = ...upper()` three times where two were
intended, and clamped `_handle_quote_bootstrap_request` and
`_handle_quote_legs_request` — the `quote` family, nothing to do with this
phase. Caught by checking which handlers the replacement had actually hit
rather than trusting the count it printed, and reverted.

Harmless as code and still wrong as a change: those handlers' acks are not
generated, so the clamp would have been dead defensive code sitting in an
unrelated family, waiting to confuse whoever specified `quote`. The working
rule is that every changed line traces to the request; a bulk substitution
makes it cheap to violate that without noticing, so the count a script reports
is worth reading rather than skimming.

## 23. `risk`, part two — and the gate that could not see

Phase 5.3b specified and adopted the ten instrument-scoped topics, completing
`risk` and with it every specified family. The migration itself was
unremarkable: eleven wire shapes verified byte-identical, ten builders
delegated, presence regimes 1 and 4 throughout, no IDL change.

Then the holistic review found that the acceptance gate had been wrong for six
phases.

### 23.1 A gate that could not see the common case

`literals.py` built its needle as `re.compile(f'"{needle}"')` — the topic
prefix with a **closing quote immediately after it**. A parameterised topic
hard-coded as an f-string never has one:

```python
f"order.fill.{gateway_id}"     # continues with `{`, not `"`
```

So `grep-literals` reported `order: 0 literals - migrated` while **forty
hard-coded parameterised topics sat in eight modules**, and had reported it
since 5.1e. `book` had six, `session` one. Forty-six in all.

The uncomfortable part is why it went unnoticed. Every family migrated before
this *was* migrated correctly — because each phase also grepped by hand, found
the f-strings that way, and fixed them. The tool was never the thing finding
them; it was the thing agreeing afterwards. A gate that only ever confirms what
you already did cannot tell you when you have missed something, and it looked
green the entire time.

Stated generally: **a check that has never disagreed with you has not been
tested.** §15.5 said a restriction with no test is a comment; this is the same
claim about the acceptance gate itself. The fix is four lines — drop the
closing anchor for parameterised prefixes, keep it for exact topics so
`"risk.kill_switch"` cannot match `"risk.kill_switch_gateway"` — and five tests
now pin both halves, including the false-positive case that makes dropping the
anchor safe (a parameterised needle ends in `.`, and the quote must sit
immediately before it).

### 23.2 The correlation gap that is not a defect

The two circuit-breaker sweeps carry no `note` and no `command_id`, where the
six per-symbol topics carry both. Their acks therefore have no identifier at
all, so two concurrent halt-alls for one gateway are indistinguishable —
exactly the problem §22.2's `command_id` was added to `risk.kill_switch` to
solve.

It is nevertheless **not the same finding**, and the difference is worth being
precise about. `risk.kill_switch`'s handler *read* a `note` that no producer
could send: a half-wire, where one side believed in a field the other could not
supply. Here both handlers read only `gateway_id`, both builders send only
`gateway_id`, and the acks carry no identifier. The two halves agree. Adding
correlation would be a feature request, not a repair.

So the spec describes what is there and this section records the gap. The test
that pins it asserts the contrast rather than the absence — the six per-symbol
topics *do* declare `command_id` — so the asymmetry stays visible rather than
becoming folklore.

### 23.3 The audit found a submission this time

§21.2's rule had been applied to *acks*: fields the engine echoes back. Probing
the adopted builders with inputs no test sends found the other direction.

`CircuitBreakerTriggerRequest.level` is `str | None` with no `max_length`.
`symbol` had `min_length=1` and no maximum. `reason` had neither. All three
reach `make_symbol_halt_msg`, which since this phase validates against
`max_len` 32, 16 and 256. An API client posting a five-thousand-character
`level` would therefore have turned a bad request into a **500**, where FastAPI
would otherwise have returned a 422 naming the field.

Five request models are bounded now, at the edge where the error can still say
what was wrong. The widened rule: **when adoption makes a builder validate,
audit both directions** — every field the process echoes outward, and every
field it accepts inward from a boundary that did not previously constrain it.

### 23.4 What a bulk edit cost

Forty-six sites across twelve modules is more than is comfortable by hand, so
the migration was scripted. Three defects came straight back out of that
decision, and all three are the same mistake in different clothes: a regular
expression does not know what it is editing.

1. **A topic that was never declared.** The substitution table included
   `order.orders.` — which no spec declares. `topic_order_orders` does not
   exist, so five modules stopped importing. Caught immediately by mypy, but
   the substitution table should have been derived from the loader's own topic
   list rather than typed out.
2. **A documented invariant, violated.** The script added a *by-name* import
   from a generated module to `models/message.py` — whose own header comment
   explains, at length, that the two modules import each other and that binding
   them by name "would raise ImportError whenever the generated module happened
   to be imported first". The file said exactly what not to do and the edit did
   it anyway.
3. **Nested parentheses.** The revert used `\\(([^)]+)\\)`, which stops at the
   first `)`, so `topic_order_orders(target_gw.upper())` came back as
   `f"order.orders.{target_gw.upper(}")`. A syntax error, so harmless — but it
   is the same class as (1) and (2) and it was the third in one sitting.

None of these survived; the toolchain caught all three within a minute. The
lesson is not "do not script bulk edits" — forty-six sites by hand would have
its own error rate. It is that **a scripted edit needs the same reading a
hand-written one gets**: check what it matched, not just how many. §22.6
recorded a two-line version of this in the previous phase; this is the same
rule failing at larger scale, which suggests it is worth stating as a habit
rather than an anecdote.

### 23.5 A formatting rule, again from the longest name

`risk.circuit_breaker_resume_all_ack.{gateway_id}` is the longest topic in any
spec, and assigning it to a constant named after it runs one character past 88
columns. Black cannot split a string literal, so it parenthesises the
right-hand side instead; the emitter had no rule for a long module-level
assignment.

That is the fifth formatting defect found by `test_generated_files_are_black_
clean` and the second in two phases traceable to `risk`'s name lengths. Both
fixes are byte-neutral for every previously committed family, which is the
cheapest available evidence that a formatting change did not quietly reformat
the tree — and worth re-checking each time, because the alternative is
discovering it through a diff nobody reads.

## 24. `structure`: the map that was one field in a costume

Phase 6.1a specified the four events that report what became of a multi-leg
structure — `combo.ack`, `combo.status`, `oco.ack`, `oco.cancelled`. Three
were byte-identical; one carried the last map on any wire in this system.

### 24.1 Phase 6.1 is six phases

Worth recording as a planning correction rather than burying it. "The
unspecified families" sounded like one phase and is about **45 topics across
seven roots**: `combo`/`oco` (4), `quote` (4), `circuit_breaker` (3),
`auction` (2), `drop_copy` (2), `admin` (1) and `system` (29). At the rate
`index` and `risk` set — ten to sixteen topics per two sessions — that is five
or six.

The ordering follows value per topic rather than size. `combo`/`oco` came
first because it closes a genuine half-conversation: `order.combo` and
`order.oco` have been specified since 5.1c/5.1d while what happens to them was
not, which is the same asymmetry §20.6 refused to ship inside a single family.
`system` goes last because 29 request/reply pairs is the one group that
benefits from every lesson the others produce.

### 24.2 A map with exactly one key, ever

`combo.status` carried `details: dict[str, Any] | None`. §15.4 excludes maps
from the IDL on the grounds that *a spec appearing to need one is describing a
message that should have been something simpler* — usually a list of records,
as §19.2's `log.notify` levels turned out to be.

This was the thinnest instance the project has found. Not a list of anything:
**one string in a dict.** The single producer that populates it does

```python
details={"reason": reason} if reason else None
```

and both consumers immediately take it back out — `alf_console` with
`details.get("reason", "") if details else ""`, `alf_gwy` with an
`isinstance(details, dict)` guard around the same call. Six lines across two
modules to move one string through a wrapper nobody wanted.

`reason` is a top-level `omit_when_empty` string now, and reads like every
other reason in the tree. The `if reason else None` guard became the presence
regime it always was.

The generalisation is §15.4's, unchanged and now three-for-three: every map
this project has met was the wire being wrong. `leg_fill_qty` was a
denormalised list index, `log.notify`'s `levels` was a list of records with
the key as a field, and `details` was a field with a box around it. **The IDL
still has no map construct and has never needed one** — which is the outcome
that makes the exclusion a design decision rather than a gap.

### 24.3 The third field one side believed in alone

Counting: `shares_outstanding` on the ADD_CONSTITUENT audit record (§20.7),
`note` on `risk.kill_switch` (§22.2), and now `details` — with the twist that
`details` was *half*-supplied. Two of its three producers pass nothing, so
`combo.status` events for MATCHED and PARTIALLY_MATCHED never carried it, and
only the terminal-status path did.

The three differ in what was wrong and therefore in the fix, which is the part
worth keeping:

| Case | What was true | Fix |
|---|---|---|
| §20.7 `shares_outstanding` | producer had the value and dropped it | record it |
| §22.2 `note` | consumer read a field the message could not carry | add it to the message |
| §24.2 `details` | both sides agreed, and the shape was wrong | flatten it |

Only reading each one settled which. A rule that said "a field read but not
written is a bug, add it" would have been right once out of three.

### 24.4 A family is named after its topic root

`combo.*` and `oco.*` events could have been appended to `order.yaml` — the
submissions they answer live there. They are a separate family because a
family file's name is its **topic root**, and that is what `FAMILY_TOPICS` and
the literal scanner key on. Folding them into `order` would have made that
family's registry advertise topics it does not own, so a router built from
`order.FAMILY_TOPICS` would subscribe to four topics `order` never publishes.

The two are related by `see_also` instead, which costs nothing and says the
same thing without lying to a registry. A test pins it: `order.FAMILY_TOPICS`
contains `order.combo` and `order.oco` and nothing starting `combo.` or
`oco.`.

## 25. `quote`: the inbound path the units rule missed

Phase 6.1b specified the four quote messages. Three were byte-identical. The
fourth carried the last engine-inbound price in the system that was not ticks.

### 25.1 What was actually wrong

`_handle_quote_new` did `to_ticks(float(payload["bid_price"]), symbol)`, so
`quote.new` carried **display money** while `order.new`, `order.combo` and
`order.oco` all carried integer ticks after §15.2.

It is important to be precise about the defect, because the obvious reading is
wrong. This was **not** §15.2's ambiguity. That one was dangerous because three
paths disagreed *and* `to_ticks` passed integers through unchanged, so a
display price of `150` and `150` ticks were the same bytes with different
meanings. Here all four producers agreed on display money, the engine always
converted, and nothing was ever mispriced.

What was wrong was the **rule**. §15.2 left behind a test file whose docstring
opens *"Engine-inbound prices are ticks, everywhere, with no exceptions"*, and
that sentence was false. A developer writing a fifth quote producer, reading
the invariant, would send `bid_price: 150` meaning ticks and have it read as
$150 — the same silent 100x error, arrived at by *following the
documentation*.

So the hazard was not in the code as it stood; it was in the gap between the
code and a claim about it. That is worth separating from an ordinary bug: no
test failed, no wire was wrong, and the thing that would eventually break was
someone trusting a sentence.

### 25.2 Why quotes were missed, and what that suggests

§15.2 enumerated three inbound paths by name and converted them. Quotes were a
fourth and are not mentioned anywhere in that section — not excluded, not
deferred, simply absent. The phase's own test file then generalised from the
three it knew about to "everywhere".

The narrow lesson is about how invariants get written: **a rule stated over
"everywhere" needs a check that enumerates everywhere, not the cases that
prompted it.** §15.2's tests assert the three paths it converted; nothing
walked the set of engine-inbound messages and asked which carried prices. The
generator can now answer that question — `unit:` is declared per field and
`describe_*()` exposes it — which is a better foundation for the invariant
than a list maintained by hand.

The fix follows §15.2's own resolution: the four producers convert, the wire
carries ticks, and the engine **rejects** a float rather than truncating it,
with the same wording and reasoning as `_handle_oco_order`'s `_leg_ticks`.
`TestQuotePricesAreTicks` in `test_wire_price_units.py` is what keeps the
docstring true, and the file now names quotes explicitly rather than implying
them.

One small hardening on the way past: the guard tests
`isinstance(value, bool)` as well, because `isinstance(True, int)` is `True`
in Python. Unreachable from any producer, but it costs one clause and the OCO
guard it mirrors has the same hole.

### 25.3 The test payloads, again

§15.2 converted 29 payloads across eight test modules. This one converted 32
across six, and the count is not the interesting part — the shape of the work
is. Two thirds of them went through a helper (`engine_harness.submit_quote`,
`test_engine_review_highs._quote`) that takes display prices and builds the
payload, so the conversion belongs *in the helper*: call sites keep reading in
display money, which is what a test author wants to write, and the helper
plays the part a real gateway plays.

That is the same boundary the production code draws — `build_quote_payload`
converts because the API speaks display money to its clients — and it is worth
noticing that the test helper and the API gateway ended up with identical
responsibilities. A test double that converts where the real thing converts is
testing the right wire.

Three files matched a naive search and were **not** converted:
`test_gateway_and_scheduler.py`, `test_commands.py` and part of
`test_mm_bot.py` carry `bid_price` inside `system.quote_bootstrap` snapshots —
engine→gateway state dumps in display money, a different message in the other
direction. `test_config_gen_*` carry it as configuration seed values. A
find-and-replace on the field name would have corrupted all five, which is
§21.6's lesson holding for the third phase running: the same field name in a
different message is a different field.

## 26. `circuit_breaker` and `auction`: a fork that was a presence regime

Phase 6.1c specified and adopted five topics across two families. Seven
producers, one of which disagreed with the other two about the shape of its
own message, and a docs surface that had believed in a field the wire never
carried.

### 26.1 Two files, because a family is its topic root

`circuit_breaker.resume` and `auction.result` are published microseconds
apart — a reopening auction *is* how a halt ends — and there was an obvious
temptation to describe the five topics in one file. §24.4 is why that would be
wrong, and the argument transfers unchanged: `FAMILY_TOPICS` is what a router
subscribes from, so a combined family would advertise `auction.*` to a
consumer that wants only halts. They are related by `see_also`.

The evidence that this is the right cut is in the consumers rather than in the
taxonomy. `md_gateway` subscribes to all five and `alf_gwy` to two of the
three `circuit_breaker` topics and none of `auction`; `api_gateway` reads
`auction.result` and no `circuit_breaker` topic at all. Three consumers, three
different subsets, and not one of them wants the union.

### 26.2 The corridor: a flattened record that stayed flat

`circuit_breaker.halt` has three producers. The price-triggered path splats
`**self._corridor_payload(cb, symbol)`; the two ADMIN paths omit the three
keys it adds. `_corridor_payload` returns `corridor_low`, `corridor_high` and
`expansion` as `None` together when `cb.corridor()` is `None`, so the wire
carried two spellings of one absence — three nulls from one producer, nothing
from the other two.

§20.1's rule fits it exactly: *an `a_b`-prefixed group of fields sharing one
guard is a record that was flattened for want of one.* §21.4 adds a second
argument, and it also fits: the producer already holds the value as an
all-or-nothing `tuple[int, int] | None` and flattens it at the publish call.
The shape was nevertheless left flat, with three `omit_when_none` fields, and
the reasons are worth recording because two good rules pointed the other way.

* **`expansion` shares the guard but not the concept.** `cb.corridor()`
  returns the bounds; `expansion_index` is a separate attribute that is always
  a real integer and is `None` on the wire only because `_corridor_payload`
  returns early. A `Corridor {low, high}` record would leave `expansion`
  outside it still sharing the same guard — which *relocates* the half-set
  state rather than removing it, and removing it is the whole point of the
  record. Putting `expansion` inside forces the record to be read as "corridor
  state" rather than "corridor bounds", which is a worse name for a worse fit.
* **Both structural readers immediately unpack it.** `normalise_cb_halt` and
  `normalise_cb_extend` turn the three into three independent CALF fields
  (`CORRIDORLO`, `CORRIDORHI`, `EXPANSION`). The CALF wire is flat either way,
  so a record would add a pack on one side and an unpack on the other with no
  reader between them holding it as a unit.
* **Regime 3 already collapses the fork, with no byte change on either
  dominant path.** A price-triggered halt with a corridor still carries all
  three; the ADMIN halts still carry none. The only shape that moves is a
  price-triggered halt with ACE disabled, which stops saying `null` three
  times and says nothing — and absence and null are the same value to the only
  reader, which reaches every one of them through `payload.get`.

So §20.1's count stands at three, not four. The narrow correction is to that
section's closing claim: it grepped `risk`'s thirty topics and concluded the
third instance was the last, which was a generalisation from the family in
front of it. `circuit_breaker` was not in that grep. The rule is sound; *"and
there are no more"* was never checked over the topics nobody had specified
yet, and there are two families left to find out about.

### 26.3 `imbalance_side`: the falsy sentinel, and the option that would have broken

`imbalance_side` is `"BUY"`, `"SELL"` or `""` on three messages across both
families, and `AuctionResult.imbalance_side` is documented in
`engine/auction.py` as exactly that. An enum cannot carry `""` (§16.1), so the
choice was between a plain string with `default: ""` — byte-identical, and
silent about the two values it can hold — and an enum of `[BUY, SELL]` that
omits when unset.

It is an omitting enum now. Every reader already goes through
`str(payload.get("imbalance_side", "")).upper()` and skips on falsy, so an
absent key and an empty one are the same event to all three; the spec gains
the enumeration, and the falsy sentinel — the pattern §16.1, §21.4 and §24.2
have each cleaned up once — leaves one more wire.

The rejected option is the interesting one. Regime 2 (`nullable`, key always
present as `null`) reads like the conservative choice and is the one that
breaks: `str(None).upper()` is `"NONE"` in Python, which is truthy, so all
three normalisers would have emitted `IMB=NONE` on the CALF wire for a
balanced book. Nothing in the spec or the IDL would have caught it — the
payload is valid, the projection is valid, and the value is wrong. The only
thing that found it was reading the four lines of the reader, which is §13.6
for the fifth time and the cheapest habit in this document.

### 26.4 `include: all` does not mean all

All five messages name `{symbol}` in the topic *and* carry it in the body, and
every consumer reads it from the body — `alf_gwy` broadcasts
`payload["symbol"]`, `normalise_auction_result` derives the CALF symbol from
it. The first draft of both specs wrote `include: all` and dropped the key
from all five payloads. `pm-msgen check` passed, the generator was correct,
and five wires had silently lost a field.

`include: all` means "every field except the topic parameters". That default
is right — `order.ack.{gateway_id}` does not repeat the gateway in the body —
and `book.yaml` already works around it by enumerating all nine of
`book_snapshot`'s fields, with a comment explaining why. These two families
now do the same, which makes four messages in the tree carrying a hand-written
field list that must be updated whenever a field is added, or the new field
silently never reaches the wire.

That is §1's failure class in the spec language itself, and it is worth
recording as a **known rough edge rather than fixing here**: the fix is either
a third value for `include` or making `all` literal, and both change the
meaning of a key that four committed specs already use. It wants its own
change with its own regeneration diff, not a passenger on a family phase.

### 26.5 What the audit found, in both directions

§23.3's widened rule — audit every field the process echoes outward *and*
every field it accepts inward — found one of each, and the inward one was not
introduced by this phase.

**Outward, and new.** `circuit_breaker.halt.level` is a level name from the
symbol's `circuit_breaker.levels` config, bounded at 32 by the spec and
unbounded by `config_loader`. A deployment declaring a longer name would have
loaded cleanly and then raised `MessageValidationError` inside the generated
builder on the first halt of that symbol — far from the config line that
caused it, and taking the halt with it. Bounded at config load, where the
error can name the file, the symbol and the key.

**Inward, and pre-existing.** `_handle_symbol_halt` reads `level` off the wire
unbounded and quotes it verbatim into `f"Unknown circuit-breaker level for
{symbol}: {level_name}"`, which becomes the `reason` of a `symbol_halt_ack`
that the `risk` spec bounds at 512. A five-thousand-character level therefore
raises inside the ack builder — and since `_reject_after_error` returns early
for non-order topics, the caller gets **no ack at all** and waits for a
timeout. This is §22.3's silent non-answer exactly, on a handler 5.3b bounded
at the *API* edge (`_MAX_CB_LEVEL` in `schemas.py`) and not at the engine's.

That gap is the useful finding, and it is a small correction to how §23.3's
rule was applied rather than to the rule: bounding the FastAPI request model
protects clients that go through FastAPI. The engine's PULL socket is a
boundary of its own, and every other identifier reaching that handler was
already clamped there by `_clamp_wire_id` — `level` was the one field on the
message that was not an identifier, so it was not in the list the audit swept.
**A per-type sweep misses the field that is not of that type.**

Both are pinned by probes rather than by reasoning: the ack builder was called
with a 5 040-character reason and the halt builder with a 40-character level,
and both raised before either fix went in.

### 26.6 A field three documents believed in alone

`docs/user-guide/120-risk-controls.md` showed an ADMIN resume as
`{"symbol": "AAPL", "mode": "MANUAL"}` in four places — two payload samples, a
sequence diagram and a prose sentence — and
`270-message-reference.md` repeated it. **No producer has ever sent a `mode`
key.** The payload is `{symbol, halt_source}`, and `halt_source` is `"ADMIN"`
there.

This is §24.3's table gaining a fourth row, and a new kind: the previous three
were a producer that dropped a value, a consumer that read a field the message
could not carry, and a shape that was wrong on both sides. This one is neither
side — both halves of the wire agree, and the *documentation* is the party
that believes in the field. It costs nothing at runtime and it is the most
expensive kind to leave, because §1's whole argument is that the docs are one
of the three surfaces that drift, and this is the drift it predicted.

Two smaller instances of the same, both found by writing the spec and
comparing it against the prose:

* `auction.result.reason` has **four** values. `_run_uncross` is called with
  `BACKSTOP` from the closing backstop, and the builder's own docstring,
  `normalise_auction_result`'s docstring and the reference table all listed
  three. Nothing was broken — `reason` is a passthrough string on every path —
  but a consumer switching on the documented three would fall through on a
  real event, and the backstop is the one uncross where the price was imposed
  rather than discovered, which is precisely when a consumer wants to know.
* The `imbalance_side` rows in the reference documented `""` for balanced.
  True until this phase, and updated with the omission.

The generalisation is §25.1's, arriving from the other direction. There the
hazard was a *rule* that had gone false while the code stayed right; here it
is a *sample payload*. Both are things no test asserts and no reader can
falsify without going to the source — which is the argument for 6.2 generating
the reference appendix from the spec rather than maintaining it by hand.

## 27. `drop_copy` and `admin`: the last two maps

Phase 6.1d specified and adopted three topics. Both families carried a map,
which is the construct §15.4 excluded from the IDL on the grounds that a spec
appearing to need one is describing a message that should have been something
simpler. That claim was three-for-three at §24.2. It is now five-for-five, and
the two new cases resolved in *opposite* directions — which is the part worth
keeping, because it means the rule is not "always flatten".

### 27.1 One map became a record, the other became a signature

| | What the map held | What it is now |
|---|---|---|
| `admin.action.scope` | seven keys, six actions, closed set | a declared `AdminActionScope` record, still nested |
| `drop_copy` `**payload` | five keys, one caller, one event type | nine flat fields and a typed publisher method |

`scope` stayed nested because the box means something: the envelope
(`command_id`, `initiator_gateway_id`, `action`, `accepted`, `reason`) is what
every admin action has, and `scope` is what this particular one acted on. A
monitor renders the first and displays the second. §24.2 flattened
`combo.status`'s `details` because it was one string in a box and the box said
nothing; the test is whether the grouping survives being named, and this one
does — imperfectly, since three of the seven keys are outcome counts rather
than scope, which is recorded in the type's own docstring rather than fixed.

`drop_copy`'s did not survive that test, because there was no grouping at all:
`**payload` was splatted flat into the message beside four fixed keys, so the
"map" never had a boundary on the wire in the first place. It was a signature
being generic, not a message being nested.

The general form, replacing "every map is the wire being wrong": **a map is
either a record that was never declared or a signature that was never
narrowed, and reading the producers tells you which.** Both are still the
wire being wrong. Neither needs a map construct, and the IDL still has none.

### 27.2 Adoption forced the drop-copy question rather than raising it

The typed signature is not tidiness. `from_dict` reads *declared keys only*,
so a generic `**payload` routed through a generated builder **silently drops**
anything the spec does not declare: the publisher returns normally, the
recipient receives a well-formed message, and a field is simply missing.

```python
>>> _topic, payload = decode(make_admin_action_msg(
...     "A", "c", "kill_switch.self", {"index_id": "EDU100"}, True))
>>> payload["scope"]
{}
```

That is §1's failure class, and adopting a builder underneath the old
signature would have *introduced* it — the first time in this project that
adoption would have made a wire less safe rather than more. So
`DropCopyPublisher.publish(gateway_id, event_type, payload)` is
`publish_fill(gateway_id, *, order_id, symbol, fill_qty, fill_price,
liquidity_flag)`, and `DropCopyMessage` holds named fields instead of a dict.

`admin.action` has the same hazard and could not take the same fix: twelve
call sites build `scope` as a dict literal, and typing the parameter would be
a twelve-site change to remove a developer error rather than a runtime one.
`test_msgen_admin.py` walks the engine's AST instead and fails on an
undeclared key — a static gate, no runtime cost, and one that will disagree
the first time somebody adds an eighth key. It also asserts it found twelve
call sites, because a scan that matched nothing would pass for the wrong
reason: §23.1's rule applied to a check written in the same commit as the
thing it checks.

### 27.3 Two capabilities that existed only in prose

Specifying a family means reading every producer, and that turned up two
documented behaviours with no implementation behind them.

* **`drop_copy.replay_request`.** `engine/drop_copy.py`'s module docstring
  described a participant sending one with `from_seq=N`. No producer, no
  subscriber, no handler, no spec — and `dc_gateway`'s own header says the
  opposite in plain terms: "`DropCopyPublisher.replay()` is in-process only,
  not reachable [by any protocol]". Two files in the same subsystem
  disagreeing about whether a message exists.
* **`DropCopyPublisher.publish`'s "every fill and cancel".** Only fills exist.
  One call site, one `event_type`.

Both are §26.6's shape — documentation believing in something the wire does
not carry — and both are now corrected in place rather than implemented. A
cancel drop-copy event is a real gap and a real feature; inventing one while
specifying the family would be the speculative work §15.5's restrictions
exist to prevent. What the spec does instead is make the gap *cost something
to ignore*: `event_type` is an enum of one value, so a second event type is a
spec change with a regenerated binding rather than a new dict key no reader
knows about.

### 27.4 The tests were the reason the map looked open

This is the finding that would have changed the answer if it had been trusted.

The old `publish` was exercised with `{"order_id": "X1", "qty": 100}`,
`{"n": 1}`, `{"i": i}` and event types `"a"` and `"b"`. **None of those keys
or values has ever been on the wire.** `qty`, `n` and `i` are test inventions;
the single producer has always sent the same five fields.

So the evidence for "this payload is genuinely open" came entirely from the
tests of the thing itself. §20.5 recorded the inverse — a documented
capability with no spec exercising it is a comment — and this is the mirror:
**a capability exercised only by its own tests is not a capability the system
has.** The tests were testing the transport's genericity, and the transport
had no reason to be generic.

They are migrated rather than deleted: every assertion — two frames, the
topic, the monotone sequence, the buffer bound, the replay window — was about
publisher behaviour and still is. Only the payloads changed, to real fills.
`engine_harness.FakeDropCopy` moved with them and kept recording
`(gateway_id, event_type, payload)`, so the M13 liquidity-flag assertions that
read `events[i][2]["liquidity_flag"]` are untouched: the double is a spy on
the wire shape, and the wire shape did not change.

### 27.5 The audit found a third failure mode

§21.2 found a crash. §22.3 found a silent non-answer. This phase found the one
in between, and it is the worst of the three to debug.

`scope.note` is bounded at 256 by the spec and was read unbounded:
`note = str(payload.get("note", ""))`, six handlers. The API gateway maps
`body.reason` (bounded 256) onto it, so a client going through FastAPI is
fine; a raw PUSH client is not, and §22.3 already recorded that the engine's
PULL socket is a boundary of its own.

What makes it different is the **ordering**. `_handle_kill_switch` publishes
the ack and *then* the monitor record:

```python
self.pub_sock.send_multipart(make_kill_switch_ack_msg(...))   # accepted: true
self._publish_admin_action(gateway_id, command_id, "kill_switch.self", {...})
```

So an over-long note does not crash the engine and does not withhold the
answer. The kill switch **runs**, the caller is told `accepted: true`, and the
audit record of a privileged action vanishes into a logged exception. For a
feed whose entire purpose is being the uniform record of admin commands, a
missing entry that nobody is waiting on is worse than either previous
outcome — nothing is blocked, so nothing prompts anyone to look.

Stated as the rule this adds to §21.2 and §22.3: **the consequence of an
unbounded field depends on where in the handler the validating builder sits.**
Before the reply it is a dropped answer; after it, it is a lost record of work
that actually happened. The six reads clamp now, and the constant's docstring
says why the bound is load-bearing rather than tidy.

The inward direction was clean this time, which is itself worth noting after
§23.3: `note` has no API request model to bound because §22.2 deliberately
declined to invent one, so the engine's own clamp is not merely the best place
for it but the only one.

### 27.6 Smaller corrections, all of the same kind

* `make_admin_action_msg`'s docstring offered `index_id` as an example of what
  `scope` might carry. No producer has ever sent it, and index rebalance
  emits no `admin.action` at all — which `260-api-gateway.md` correctly says
  in a note four lines below the sample that shows `scope`. The docstring was
  describing a design, not the code beneath it.
* `pm-dc-spy` printed `f"drop_copy.event.{gateway}"` as the subscription it
  had made, next to a client that subscribes `EVENT_TOPIC_PREFIX + gateway`.
  The same string twice, so the banner could report a subscription the process
  had not made. It reads the option object now, which removed the literal and
  the possibility together — the one case this phase where `grep-literals`
  pointing at what looked like display text was pointing at a real drift.

None of these three is a bug in the running system. All three are the
documentation surface of §1's triangle drifting from the other two, which is
the argument for 6.2 generating the reference appendix rather than
maintaining it — now four phases running.

### 27.7 Two more emitter defects, both from firsts in the spec

`test_generated_files_are_black_clean` is now **six for six**: every
formatting defect this generator has had was found by running black over the
committed output, never by a test in the generator's own suite. Both of this
phase's came from a spec construct no previous family had used.

1. **An all-omitting record emitted an empty dict across two lines.**
   `AdminActionScope`'s seven fields are every one of them optional, so
   `to_dict` starts from nothing — and the emitter wrote

   ```python
   payload: dict[str, Any] = {
   }
   ```

   where black writes `{}`. The branch had existed since the first
   `omit_when_none` field and had never been reachable, because until now
   every message and record in the tree had at least one field that is
   always emitted. Fixed in both places that build a payload incrementally,
   `to_dict` and `make_*_unchecked`.

2. **`_pystr` tested for a quote instead of counting them.** §22.4 taught the
   emitter that black switches to single quotes rather than escaping a `"`.
   The rule it learned was *presence*: a string containing `"` and no `'`.
   `drop_copy.event_type`'s doc is the first text in any spec containing
   **both** — two `"` and one `'` — so the presence test picked double quotes
   and escaped twice where black picks single and escapes once. Black keeps
   whichever spelling needs fewer escapes and prefers double on a tie, which
   is a count.

Both are §20.2's habit and §18.3's rule meeting: a rule written for the case
that prompted it, then reached by a case that satisfies its letter and not its
reason. The presence test was *correct* for every string in the tree when it
was written, and stayed correct for four phases.

Both fixes are byte-neutral for the fifteen previously committed bindings —
regenerating rewrote `admin.py` and `drop_copy.py` and nothing else, which is
the cheapest available proof that a formatting change did not quietly reformat
the tree. §23.5 asks for that check each time and this is the third phase it
has been worth doing.

## 28. `system` part one: the shadow the generator cast on itself

Phase 6.1e specified and adopted fifteen topics — the largest phase in the
project, and the first whose worst defect was in the generator rather than in
a wire. Five maps, nine consumer modules, a REST-visible change, two additions
to the IDL, and one bug that every existing check passed.

### 28.1 The collision, and why nothing caught it

The spec declared a record type `SessionSchedule` — the five-key trading-day
clock — beside a message named `session_schedule`. The Python emitter derives
a message's class name by PascalCasing it, so both wrote **`class
SessionSchedule` into the same module**. Python does not complain; the second
definition shadows the first, and the nested field resolved to the message
class at runtime.

What makes this the sharpest instance of §1's failure class so far is the list
of things that agreed the spec was fine:

* `pm-msgen lint` — the loader checks duplicate *message* names and duplicate
  *field* names, and type names come from a YAML mapping whose keys are unique
  by construction. Nobody had checked the two namespaces against each other.
* `pm-msgen check` — the committed output matched the spec exactly. It did:
  the spec really does ask for two classes with one name.
* black — the file is perfectly formatted. It is also wrong.
* the whole test suite — nothing constructed a `SessionTimes` yet.

It was found by a probe, which is §7's habit paying for itself again: building
one full `system.reference` payload by hand raised `TypeError: SessionSchedule
.__init__() got an unexpected keyword argument 'pre_open'`.

The loader rejects it now, with the transform repeated in `spec.py` rather
than imported from `generators/python.py` — the loader must not depend on a
generator, and the alternative was moving the check somewhere `lint` cannot
reach. Two tests, because §23.1 asks for both halves: one that the guard fires
on `Thing` beside `thing`, and one that it *does not* fire on `ThingDetail`
beside `thing`, which is the shape every family in the tree already has.

`test_msgen_system.py` adds a third, and it is the one worth keeping: an AST
scan asserting that **no generated module defines a class twice**, over all
fourteen. The loader guard fails a bad spec; the scan fails a bad emitter, and
a future change to `_class_name` would break the second without touching the
first. It asserts it scanned at least fourteen modules, because a scan that
matched nothing passes for the wrong reason.

The general form, which is new: **a check that validates two namespaces
separately has not validated the namespace they share.** §26.5 recorded the
per-*type* version of this — a sweep over identifiers missed the one field
that was not an identifier. This is the per-*namespace* version.

### 28.2 Five maps, five judgements

§27.1's general form — a map is either a record that was never declared or a
signature that was never narrowed — held five more times, and the interesting
result is that no two resolved the same way.

| Map | What it was | What it is |
|---|---|---|
| the whole `system.reference` payload | a `dict[str, Any]` passed to `encode` unread, built in one place with five fixed top-level keys | a record, with a typed builder |
| `reference.symbols` | keyed by symbol | §19.2's list of records, key as a field |
| `reference.risk.levels` | keyed by level name | the same |
| `session_schedule.schedule` | annotated `dict[str, str] \| None` | a fixed five-key record. **Never a map at all** — only the annotation said otherwise |
| `symbols.symbol_meta` | keyed by symbol, parallel to a `symbols` list of those same strings | **deleted**, folded into the list it duplicated |

The last is the one §15.4 predicted and none of the previous ten instances had
produced: not a map that should have been a record, but a map that should not
have existed. `symbols` and `symbol_meta` were built in the same loop, over
the same `sorted(self.books.keys())`, and nine readers joined them back
together with `meta.get(sym)`. The key *was* the identity of the row, which is
`leg_fill_qty` exactly. One `symbols: list[SymbolInfo]` now, and the two can no
longer disagree about which instruments exist.

`reference`'s conversion carried a second finding. `make_reference_msg` took a
single `reference: dict[str, Any]`, and `from_dict` reads declared keys only —
so adopting a generated builder underneath that signature would have silently
dropped anything the spec did not declare. That is §27.2's `drop_copy` hazard
for the second time, and it takes the same fix: named parameters.

### 28.3 One shape, always — and one spelling, always

Two smaller unifications, both of which removed a compensating read somewhere
else.

**The bundle had two shapes.** Before an engine config was loaded,
`_handle_reference_request` answered `{"config_version": None}` and nothing
else. Every slicing endpoint absorbed that with `.get(key, {})`, so the second
shape was invisible until one of them stopped. The bundle is complete now —
empty collections, null version — and the five defaults went with it.

**Tick scale had three spellings.** The engine held `tick_decimals`, an
integer, and published `tick_size = 10 ** -tick_decimals`, a float that cannot
represent most of its own values exactly. `pm-stats` recovered the exponent
with `round(-log10(x))`; `alf_gwy` and `balf_gwy` each had their own
`_infer_decimals`; `book` and `system.eod` had been carrying `tick_decimals`
under that name the whole time. And `api_gateway/engine_client.py` read
`symbol_meta[sym]["tick_decimals"]` — **a key no producer has ever sent**, so
its `register_tick_decimals` call had never once fired.

That last one is §24.3's table gaining a fifth row, and a new combination: the
producer dropped a value (row 1) *and* a consumer believed in the field it
dropped (row 2), in the same field, in opposite directions, cancelling out
into silence. Nothing failed. Three consumers reconstructed the number the
producer had thrown away, and the fourth quietly did nothing at all.

`tick_decimals` is on the wire now and `tick_size` is off it. Two
`_infer_decimals` helpers went with it, and the API gateway's registration
works for the first time.

**And the schedule was described twice.** `session_schedule.schedule` and
`reference.schedule` are the same five keys off `engine_cfg.schedule`. One
`SessionTimes` record, nested inside `ReferenceSchedule`, which is why
`GET /reference/schedule` returns three keys where it returned seven. This is
also why the two topics could not be split across 6.1e and 6.1f: describing
the record in one phase and re-describing it in the next is the drift §1 is
about.

### 28.4 The REST surface moved, on purpose

`api_gateway/routers/reference.py` slices the bundle and returns the slices
verbatim, so three wire changes are HTTP changes:

* `GET /reference/symbols` — a list of objects each carrying its own `symbol`,
  where it was an object keyed by symbol. A client can iterate this without
  knowing the keys, which is the better JSON and not merely the changed one.
* `GET /reference/schedule` — `{sessions_enabled, country, schedule{…}}`.
* `GET /symbols` — the `system.symbols` reply verbatim, so the `symbol_meta`
  fold is visible here too. This one was not in the phase's plan; it turned up
  by reading the router rather than the design note, which is §13.6 for the
  seventh time.

All three are sanctioned under the standing instruction to take the best
long-term shape and not weigh backward compatibility, and all three are
recorded in `260-api-gateway.md`.

### 28.5 What the phase declined to build

* **A cross-family record.** `EodBookLevel` and `book.BookLevel` are the same
  three fields, and records are family-scoped, so the shape is declared twice.
  A `shared:` construct would fix it. One instance is not evidence for a
  construct — §15.5's restriction, and the same argument that kept `include`'s
  rough edge unfixed in §26.4. Recorded here so the second instance can be
  counted against it rather than rediscovered.
* **A variant type.** `SymbolInfo`'s market-maker fields are present together
  or not at all, depending on whether the caller is a configured gateway.
  §20.3's limitation, third occurrence, still not enough.

### 28.6 The half-specified family, second occurrence

`grep-literals` counts literals of *declared* topics, so `system` now reports a
real non-zero count while fourteen of its topics remain unspecified. §22.5
recorded this for `risk`; the response is the same and the *test* is the part
worth copying. Keeping `system` out of `MIGRATED` is not enough on its own:
adding it early fails loudly, but finishing 6.1f and forgetting to add it would
fail **silently**, leaving the family unchecked forever. So the assertion is on
the omission itself — `test_system_is_not_in_migrated_yet` — and 6.1f's job
includes deleting it.

### 28.7 Two additions to the IDL, one of which is a unit

`unit: duration_nanos`. `halt_duration_ns` and `reference_window_ns` are
durations; `epoch_nanos` names an instant, and using it would have been the
kind of documentation-that-is-wrong §25.1 is about. `dimensionless` was the
honest placeholder and it discards the scale. The registry is documentation
the reviewer reads, so a unit that cannot tell "sixty seconds" from "1970 plus
sixty nanoseconds" is a unit not doing its job.

This is the first time the IDL has been extended rather than the message
corrected — six previous occasions went the other way (§7). The test is
whether the *message* is wrong, and here it is not: a halt really does last a
duration. Worth stating so the count stays honest: **seven times asked, once
extended.**

### 28.8 The audit: five reads, all of them the same failure mode

Every `*_request` in this half reads `gateway_id` off the engine's PULL socket
and echoes it into a reply topic and a spec-bounded field. Four did so
unclamped, as did `reference_reload`'s `command_id`. Each sits *before* its
reply, so §27.5's rule places all five at §22.3's outcome: the caller gets no
answer and waits for a timeout.

The fix needed a second helper, and the reason is worth recording because
reusing the existing one would have introduced a bug while fixing another.
`_clamp_wire_id` **upper-cases**, because it normalises ids the engine matches
against configuration. Two of these five keys are not that: they are
correlation keys echoed into a reply topic the caller is already waiting on,
and the API gateway passes a mixed-case **API key** there for read-only
reference callers. Upper-casing it would have sent every read-only reference
reply to a topic nobody was subscribed to — a clean, silent, total failure of
the endpoint. `_clamp_wire_text` bounds without touching case.

**A helper named for what it does to a value is safe to reuse; one named for
the kind of value it expects is not.** `_clamp_wire_id` is the second.

## 29. `system` part two: finishing a family, and the guard that caught its author

Phase 6.1f specified and adopted the remaining fourteen topics — seven
request/reply pairs, all of them snapshots of what is true right now. It is the
last family. Every topic in EduMatcher is now declared, generated and adopted,
and `grep-literals` reports zero for every family with nothing left excluded.

### 29.1 The guard from 6.1e fired on the phase that wrote it

§28.1 added a loader check rejecting a record type whose generated class name
collides with a message's. Two tests pinned it and an AST scan pinned the
property. The first spec written after it — this one — declared a
`QuoteBootstrap` record beside a `quote_bootstrap` message and `pm-msgen lint`
refused it by name, one phase later:

```
pm-msgen: spec error: message 'quote_bootstrap' and type 'QuoteBootstrap'
both generate 'class QuoteBootstrap'. Rename the type
```

§23.1 asks for a check that has disagreed with somebody. This one disagreed
with its own author on its first outing, which is about as direct an answer as
that rule can get. The record is `ActiveQuote` now, and the name is better:
`QuoteBootstrap` named the message it arrived on rather than the thing it is.

**The generalisation is about naming, not about the guard.** A record named
after the message that carries it will collide with that message roughly
whenever the message carries exactly one collection — which is the commonest
shape in this family. Naming a record for what it *is* avoids the collision as
a side effect of being the better name.

### 29.2 The corridor: one helper, two shapes

`_corridor_payload` returns `{corridor_low, corridor_high, expansion}`.
`circuit_breaker.halt` and `.extend` splat it **flat** — §26.2 examined that and
deliberately left it flat, because both readers immediately unpack it into
independent CALF fields. `risk_state` nested the identical dict under a key
called `corridor`, so its wire read:

```json
"corridor": {"corridor_low": 8.0, "corridor_high": 12.0, "expansion": 1}
```

The prefix and the box say the same thing, and `corridor.corridor_low` is the
stutter that gives it away. One producer, one helper, two shapes on two wires.

Flat here too, matching the event, and the third key becomes
`corridor_expansion` — distinguishing it from `expansion_index`, which sits
beside it on the same record and is a genuinely different value:
`expansion_index` is always a real integer, `corridor_expansion` is null
exactly when the corridor is.

This is §26.2 arriving at its own conclusion from the other end. That section
declined to build a `Corridor` record and recorded three reasons; none of them
mentioned that a second message was already nesting the same three values,
because that message had not been read yet. The rule §26.2 stated survives —
what changes is that "the shape was left flat" is now true of both wires
instead of one.

### 29.3 Seven maps, twelve of twelve

`risk_state.symbols` and `volume.symbols` were the last two maps in the tree,
and both were §19.2's shape with no argument on either side: keyed by symbol,
built in a `for` loop over sorted symbols, read by exactly one consumer each.
§15.4's claim finishes twelve-for-twelve.

`volume` also settles a question §28.2 did not have to answer. Its totals are
carried alongside the per-symbol rows, which looks like the redundancy a record
conversion would remove. They stay, because they are not a sum of the rows:
they are the engine's own running counters, and a caller adding up `symbols`
would disagree with the engine about any instrument whose book was removed
mid-session. **Redundant on the wire is not the same as derivable from the
wire**, and only reading the producer tells you which one you have.

### 29.4 Four fields named `symbols`, four types

With the family complete, `system` carries `symbols` on four messages:
`SymbolInfo`, `ReferenceSymbol`, `SymbolRiskState`, `SymbolVolume`. They share
a name and nothing else — different fields, different lifetimes, different
consumers. The handover that opened 6.1e flagged this as the worst available
find-and-replace target in the project, and it survived two phases of editing
precisely because it was written down before the editing started.

The type names carry the distinction the field names cannot:
`SymbolCircuitBreaker` is a symbol's configured ladder, `LiveCircuitBreaker` is
where its breaker stands now; `ReferenceRisk` is the definitions,
`SymbolRiskState` is the state. Four types rather than two with optional
halves, because a caller wants exactly one of each pair and a merged record
would make "which half is populated" a runtime question.

### 29.5 A regime chosen against the IDL's instinct

`quote_legs` carries `legs` and `recent`, and only one of them is populated for
a `show` of `ACTIVE` or `RECENT`. That is regime 4's textbook case: an absent
list and an empty one are the same value to `alf_gwy`, the only structural
reader, and §18's `HistoryRecord` argument applies almost word for word.

They are required lists instead, always present and empty when unused, and the
reason is a surface §18 did not have: `GET /quotes/legs` returns this payload
verbatim, so a REST client doing `resp["legs"]` would `KeyError` on a reply
that is entirely well-formed. The rule that decides it: **regime 4 says "this
message does not have that concept"; `[]` says "it has none right now".**
`quote_legs` always has both concepts, so `[]` is the true statement and the
omission would be an invented one.

Which is the same test §26.3 applied to `imbalance_side` and reached the
opposite answer on — there, absence really did mean the concept was absent.
Same rule, different fact, different regime.

### 29.6 The scripted edit, and reading what it matched

102 topic literals across 17 modules had to become generated constants. The
mapping is mechanical — exact topic to `TOPIC_X`, prefix to `PREFIX_X`,
f-string to `topic_x(expr)` — and it was done by script, with the constant
table built by reading the generated module rather than by writing the names
out again.

The substitutions were right. **The import placement was not**: the script
inserted its `from ... import (...)` block after the last line matching an
import, which for eleven files landed *inside* an existing parenthesised
import and produced eleven syntax errors. They were found by parsing every
file with `ast`, and repaired by a second pass that used `ast` to find the end
of the last top-level import statement — the thing the first pass had
approximated with a string match.

§7's rule says to read what a scripted edit matched rather than how many. The
correction this adds is that the edit is not only the substitution: **the
scaffolding around a scripted edit needs the same scepticism as the edit**. The
regex that chose *what* to replace was carefully built from the generated
module; the heuristic that chose *where* to put the import was written in
passing, and it was the one that broke. A syntax error is the friendly version
of that mistake — the unfriendly version places a valid import in a scope where
it shadows something.

### 29.7 Two literals that were not migrations

The last three literals resisted the script, and two of them were real:

* `pm-stats` subscribed `"system.symbols.STATS"` and requested with
  `make_symbols_request_msg("STATS")` — the same identity written twice, once
  in a subscription and once in a request, with nothing tying them together. It
  is `STATS_GATEWAY_ID` now, and the subscription is `topic_symbols` of it.
* `pm-scheduler` logged `"subscribed to session.state and
  system.session_status.%s"` two lines below the subscription it was
  describing. §27.6's `pm-dc-spy` exactly: display text that can claim a
  subscription the process did not make. It logs the topic objects now, which
  removed the literal and the possibility together.

Both are the pattern §27.6 named and neither is a bug in the running system.
Two families running, the last literals in a migration have been *identity
duplicated across two call sites* rather than topics anybody forgot — which is
a hint about where to look first in whatever the next migration turns out to
be.

## 30. The third surface

Phase 6.2 generates `270-message-reference.md` from the spec. §1 opened this
document by naming three places a message is described — the publisher, the
subscriber, and the documentation — and observing that nothing links them. The
publisher has been generated since 5.1 and the subscriber since the last topic
literal went in 6.1f. This closes the third, which means the sentence §1 was
written to justify is no longer true of this system.

Four phases running, every family's adoption turned up a documentation defect
and every one of them ended with the same note: *this is the argument for 6.2*.
§26.6 found a `mode` field in four places that no producer has ever sent. §27.3
found two capabilities that existed only in prose. §27.6 found a docstring
describing a design rather than the code beneath it. §28.3 found a consumer
reading a key under a name nothing emits. All four are the same failure, and
all four are gone by construction now: a statement about a message that the
spec does not make cannot appear on the page.

### 30.1 What is generated, and what deliberately is not

The page is one artifact built from two halves:

| Half | Source | Checked |
|---|---|---|
| topic index, record types, one section per message | `spec/messages/*.yaml` | yes — `pm-msgen check` |
| bus concepts, transports, the CALF protocol | `docs/user-guide/270-preamble.md` | no, and correctly not |

The split is the load-bearing decision. A documentation generator that starts
producing narrative starts inventing, which relocates §1's failure rather than
removing it. The preamble is prose the spec has no field for, so it stays
hand-written and is copied through **byte for byte** — a property with a test,
for a reason given in §30.4.

### 30.2 `published_by`: prose became a closed vocabulary

The hand-written page carried lines like:

> **Published by:** Requesting client process (for example pm-alf-console,
> pm-admin, pm-viewer, pm-stats, bots, or the API gateway) via PUSH :5555

Five process names and a port, none of them checkable — and `pm-viewer` is not
a process this system has. That is §26.6 in the surface §26.6 was about.

`doc.published_by` is now a required key holding a list drawn from a closed
vocabulary of eleven process *roles*. Closed on §27.3's reasoning: an enum
makes a twelfth role a spec change with a regenerated page, rather than a new
string nobody notices. A typo fails the loader by name.

**It is deliberately coarse, and that is the interesting part.** The obvious
richer design is module paths, which a test could verify exist. It was
rejected: a module path moves with every refactor and a port with every
deployment, so the precise version would be wrong more often than the vague
one. *A fact worth tabulating is one that changes less often than the thing it
describes.* Ports and sockets live in `doc.example_note`, which is prose about
one message rather than a column the appendix aligns.

Populating all 106 was done by reading the tree, not by writing them out: an
AST pass collected every module that calls each message's builder — resolving
the hand-written wrappers in `models/message.py` through their own bodies — and
mapped module to role. Seventy-six resolved that way. The remaining thirty
build their payload through `encode()` directly rather than a generated
builder, and were read by hand; they are listed in the population script's
`MANUAL` table rather than guessed, and every one of them is a message whose
direction is unambiguous.

That residue is itself a finding: **thirty messages are still constructed
without going through their generated builder.** They are correct today and
nothing is broken, but they are the population for which `from_dict`'s silent
key-dropping (§27.2) cannot help, because nothing validates them. A phase 6.3
worth having is adopting those thirty, and the `MANUAL` table is the worklist.

### 30.3 What the appendix says that the hand-written page could not

* **Coverage.** 67 `###` sections for 106 messages. A reference that silently
  omits a third of the system is worse than one merely out of date, because
  nothing about reading it reveals the omission. `test_msgen_docs.py` asserts
  every topic and every record type has a section.
* **Presence.** The old page wrote "optional" for all four regimes, so a reader
  could not tell an absent key from a null one without going to the producer —
  which is §13.6's habit forced on every reader of the documentation. The
  generated table has a phrase per regime.
* **Units.** `unit` exists to be reviewable (§15.2), which requires being
  visible. It had never appeared in the reference at all.
* **Bounds.** `max_len 32` on the page and in the builder are now the same
  fact. Four phases of audits (§21.2, §22.3, §26.5, §27.5) turned on a bound a
  reader had no way to look up.

### 30.4 The bug the generator had, and it was the predictable one

The first draft normalised blank-line runs across the whole rendered page —
harmless-looking, and it kept the output stable regardless of which optional
blocks a message carried. It also **silently reformatted the hand-written
preamble on every run.**

A documentation generator quietly editing the prose a human owns is a small
version of exactly what this tool exists to stop, and it is the failure mode
the split in §30.1 was designed to prevent, appearing anyway in the one line
that spanned both halves. It was caught by the test asserting the preamble
appears verbatim — written before the bug, for a different reason.

The fix normalises only the body. The test that would have hidden it —
"the page contains no triple newline" — was **inverted** rather than deleted:
it now asserts the property over the body alone, and a second test asserts the
preamble *does* still contain a blank run. A test that passes because the
generator flattened the evidence is worse than no test, and §23.1's rule reads
the same way from this direction: a check that cannot fail for the right reason
has not been written yet.

### 30.5 Where this leaves the argument

§1's claim was that three surfaces drift because nothing links them. The record
across nine phases is that **the wire was wrong six times, the consumer four
times, and the documentation seven** — and the documentation is the only one of
the three whose defects cost nothing at runtime, which is exactly why it
accumulated the most. Nothing failed, so nothing prompted anyone to look.

That asymmetry is the argument for generating it, stated more precisely than
§1 managed: it is not that documentation drifts faster, it is that **drift in
documentation has no symptom.** A wrong builder raises. A wrong subscriber goes
quiet. A wrong reference page is read, believed, and acted on.

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
- [x] **Phase 4b** BALF `layout` support; `order.yaml` with `execution_report`;
  capstone assertion 5; generated frames byte-identical to `balf_gwy/codec.py`;
  the wrong example parsers corrected and guarded.
- [ ] **Phase 5** one family per PR, each with its own wire-compat test;
  `grep-literals` count for the family driven to zero.
  - [x] **5.0** `pm-msgen grep-literals` built (§7.4); `trade`'s 26 literals
    across 14 subscribers driven to zero; `tests/test_msgen_literals.py` keeps
    it there.
  - [ ] **5.1** `order.*` — the largest and most duplicated family.
    - [x] **5.1a** the five engine→gateway events (`ack`, `fill`, `cancelled`,
      `expired`, `amended`): `nullable`/`omit_when_none` added, all five
      specified and adopted in `models/message.py`, 30 prefix literals across
      4 modules driven to zero.
    - [ ] **5.1b** inbound commands (`order.new`, `order.cancel`, `order.amend`).
    - [ ] **5.1c** combo and OCO topics.
  - [ ] **5.2** `book` / `depth`, then `session`, `risk`, `index`, `log`.
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

#### B.7.0 Presence: the three regimes (normative)

A field is one of three things on the wire, and `required: false` alone does
not say which. The spec must:

| Declaration | Wire | Python |
|---|---|---|
| `required: true` | always present | `T` |
| `required: false` + `default: X` | always present, `X` when unset | `T = X` |
| `required: false` + `nullable: true` | always present, `null` when unset | `T \| None = None` |
| `required: false` + `nullable: true` + `omit_when_none: true` | **absent** when unset | `T \| None = None` |

`omit_when_none` implies `nullable`; declaring it without is a lint error, as
is `required: false` that states none of the three — the loader refuses to
guess, because the three differ on the wire and a silent choice is how a spec
comes to say something its author did not mean.

**Why `omit_when_none` exists rather than "just emit null".** It was added in
1.10.0 for the `order.*` events, which omit keys deliberately. The alternative
was to emit `null` and accept a wire change; that was rejected because
`models/message.py` documents the omission as a decision:

> *Absent keys are omitted rather than emitted as `null`: an ordinary single
> order carries none of these, and its events should not grow four empty
> fields to say so.*

**Why one flag is enough — the thing worth checking before adding more.**
Absence and `null` are indistinguishable to every reader in this system, which
was verified rather than assumed: `engine/main.py::_handle_amend` does
`payload.get("price")` and then tests `is None`, never `in payload`;
`Order.from_dict` uses `.get`; no consumer and no test distinguishes them.
So the omission is a wire-size choice, not a semantic one, and nothing here
needs the tri-state (`absent` ≠ `null` ≠ value) that a PATCH-style protocol
would. Had any consumer tested presence, one flag would have been the wrong
model and this table would need a fourth row.

**The block regime that was deliberately not modelled.** `order.ack` and
`order.fill` had a third shape: six enrichment fields present *together* or
absent together, with `price: null` emitted for a MARKET order. Reproducing
that exactly would have meant a `block`/`group` construct in the IDL, existing
only to preserve bytes no consumer reads. Phase 5.1a instead applies
`omit_when_none` uniformly and accepts one byte change — a MARKET order's ack
and fill no longer carry `"price": null`. That is the same judgement as
`aggressor_side` in Phase 1: do not ratify an accident by encoding it in the
specification language.

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

`display_price`, `ticks`, `shares`, `epoch_seconds`, `epoch_nanos`,
`duration_nanos`, `percent`,
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
                 | "epoch_nanos" | "duration_nanos" | "percent"
                 | "dimensionless" | "money"

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

Version: 1.0.0

Date: 2026-08-04

Status: Design and Research Proposal

# Message Generator — Canonical Message Specification and Code Generation

Generate the Python structures, the C structures, and the reference
documentation for every EduMatcher message from one canonical specification,
so the three can no longer disagree.

---

## 1. The problem, measured

A message in EduMatcher is currently described in at least three places, none
of which is authoritative and none of which is checked against the others.

Counted against the current tree:

| Surface | Count | Notes |
|---|---|---|
| `make_*` factories in `models/message.py` | 78 | The de-facto publisher API |
| Typed payloads in `models/feed_schema.py` | 7 | Only the payloads clearing needed |
| Topics documented in `270-message-reference.md` | 66 | 2 222 lines, hand-maintained |
| Topics constructed by `encode()` in `message.py` | 53 | |
| **Distinct topic string literals outside `message.py`** | **108** | across **25 files** |

Three findings follow directly from those numbers.

### 1.1 Payload shape is typed for 7 of 78 messages

`feed_schema.py` exists precisely because clearing needed a contract it could
rely on, and its module docstring says so — it documents units per field for
the handful of payloads it covers. The other 71 factories build a `dict`
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

---

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
- A big-bang migration. §8 is explicitly incremental.
- Cross-language RPC. This is a message-shape tool, not a service framework.

---

## 3. Why not an off-the-shelf IDL

| Option | Why it does not fit |
|---|---|
| Protocol Buffers / FlatBuffers | Would replace the wire format. EduMatcher's formats are pedagogical artefacts — students read CALF text and parse BALF binary by hand. Changing them removes the teaching value. |
| JSON Schema | Validates JSON only. No C generation, no binary layout, no topic model. |
| AsyncAPI | Closest fit, and the topic model is right, but generation targets are web-oriented and it cannot express BALF's fixed binary header or CALF's positional text. |
| Hand-written | The status quo. §1 measures the result. |

The differentiator is that EduMatcher carries **three encodings of the same
logical message** — JSON on the internal bus, CALF text key-value, BALF binary
with a fixed header — and the docs must show all three. No off-the-shelf tool
covers that trio, and the specification needed is small enough that owning it
is cheaper than bending one that does not fit.

---

## 4. The canonical specification

One YAML file per family under `spec/messages/`, e.g. `spec/messages/trade.yaml`.

### 4.1 Worked example

```yaml
family: trade
version: 1

messages:
  - name: trade_executed
    topic: "trade.executed"
    direction: engine->all
    transport: [bus, calf, balf]

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

    # ---- per-transport encoding ----
    encoding:
      bus:
        frames: [topic, json_payload, sequence]
      calf:
        msg_type: TRADE
        keys: { id: ID, symbol: SYM, price: PX, quantity: QTY,
                aggressor_side: AGG, timestamp: TS }
      balf:
        msg_type: 0x21
        layout:                       # little-endian, matching balf_parser.c
          - { field: id,        repr: u64 }
          - { field: symbol,    repr: char[16] }
          - { field: price,     repr: i64, scale: tick_decimals }
          - { field: quantity,  repr: u32 }
          - { field: aggressor_side, repr: u8, enum_map: { BUY: 1, SELL: 2, AUCTION: 3 } }
          - { field: timestamp, repr: u64, unit: epoch_nanos }
```

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

---

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
TOPIC_TRADE_EXECUTED = "trade.executed"

@dataclass(frozen=True, slots=True)
class TradeExecuted:
    id: str
    symbol: str
    price: float                    # unit: display_price
    quantity: int                   # unit: shares
    aggressor_side: Literal["BUY", "SELL", "AUCTION"]
    timestamp: float                # unit: epoch_seconds
    tick_decimals: int = 2

    def validate(self) -> None: ...          # raises MessageValidationError
    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TradeExecuted": ...
    def to_dict(self) -> dict[str, Any]: ...

def make_trade_executed(*, id: str, symbol: str, ...) -> list[bytes]:
    """Validating constructor. Returns ZMQ frames."""

def parse_trade_executed(frames: list[bytes]) -> TradeExecuted: ...
def is_trade_executed(topic: str) -> bool: ...
```

For parameterised topics the constants become functions, which is what removes
the 108 scattered literals:

```python
TOPIC_ORDER_ACK = "order.ack.{gateway_id}"
def topic_order_ack(gateway_id: str) -> str: ...
def match_order_ack(topic: str) -> str | None:   # returns gateway_id or None
PREFIX_ORDER_ACK = "order.ack."                  # for setsockopt(SUBSCRIBE)
```

### 5.2 C

```c
/* GENERATED FROM spec/messages/trade.yaml — DO NOT EDIT */
typedef enum { EDU_AGG_BUY = 1, EDU_AGG_SELL = 2, EDU_AGG_AUCTION = 3 } edu_aggressor_side_t;

typedef struct {
    char                 id[65];
    char                 symbol[17];
    double               price;          /* unit: display_price */
    uint32_t             quantity;       /* unit: shares       */
    edu_aggressor_side_t aggressor_side;
    int32_t              tick_decimals;
    double               timestamp;      /* unit: epoch_seconds */
} edu_trade_executed_t;

int  edu_trade_executed_parse_calf(const calf_message_t *in, edu_trade_executed_t *out);
int  edu_trade_executed_parse_balf(const uint8_t *buf, size_t len, edu_trade_executed_t *out);
int  edu_trade_executed_validate(const edu_trade_executed_t *m, char *err, size_t errlen);
const char *edu_aggressor_side_to_str(edu_aggressor_side_t v);
```

Fixed-size buffers, no allocation, `int` returns — matching the existing
example clients' style so generated code drops in beside hand-written code.

### 5.3 Documentation

A generated `271-message-appendix.md` in the existing chapter's table style:
motivation, publisher, direction, transports, then the field table with type,
unit, required, constraints and description, then a worked example per
transport (JSON, CALF line, BALF hexdump).

The existing hand-written `270-message-reference.md` stays. It carries the
narrative — sequence diagrams, subscription tables, protocol walkthroughs —
that no generator should attempt. The appendix carries the mechanical field
detail that currently rots.

---

## 6. Helper surface

Generated per family, so no consumer hand-writes them:

| Helper | Purpose |
|---|---|
| `topic_*()` / `PREFIX_*` | Build and subscribe without literals |
| `match_*(topic)` | Extract the parameter, or `None` |
| `parse_*(frames)` | Frames → typed object, validated |
| `make_*(**kw)` | Validated construction → frames |
| `to_dict` / `from_dict` | Interop with existing dict-based code |
| `validate()` | Standalone, for tests and gateways |
| `FAMILY_TOPICS` | Registry for routers and spy tools |
| `describe_*()` | Field metadata at runtime, for `pm-*-spy` pretty-printing |

---

## 7. Tooling and build integration

### 7.1 The generator

`tools/msgen/` — a standalone Python package, no runtime dependency from
`edumatcher`.

```bash
pm-msgen generate --spec spec/messages --out-python src/edumatcher/models/generated \
                  --out-c docs/examples/generated --out-docs docs/user-guide
pm-msgen check                 # regenerate to temp, diff against committed
pm-msgen lint                  # spec-only: missing units, undocumented fields
```

### 7.2 The guarantee

`pm-msgen check` in CI is the whole point. It regenerates into a temporary
directory and diffs. Any of the following fails the build:

- a spec change without regenerating
- a hand-edit to a generated file
- documentation drifting from the spec

Without this the generator is merely a scaffolder and §1 recurs within a
release. With it, the three surfaces are provably identical.

Add to the `Makefile` alongside the existing checks:

```make
msgen-check: ; pm-msgen check
check: black flake8 mypy pyright msgen-check test
```

### 7.3 Spec linting

`pm-msgen lint` catches what generation alone cannot: a field without a `unit`,
a `string` without `max_len` (which would break C generation), an enum without
`values`, a message without a `doc.motivation`, a topic parameter not present
in the field list.

---

## 8. Phased adoption

78 factories cannot move at once, and there is no reason to. Each phase is
independently shippable and independently verifiable.

### Phase 1 — Generator, one family, no adoption

Build `tools/msgen`. Specify `trade.yaml` only. Generate all three outputs.
Commit them **unused**.

*Test:* generated `TradeExecuted.from_dict` accepts every payload the existing
`TradeExecutedPayload` accepts, and produces byte-identical `to_dict()` output.
Property test over generated payloads.

*Ships:* nothing user-visible. The generator proves itself against a message
that already has a hand-written typed equivalent.

### Phase 2 — Adopt for one family

`make_trade_msg` becomes a thin shim over `make_trade_executed`. `pm-stats`
parses with the generated parser.

*Test:* the entire existing suite passes unchanged — that is the acceptance
criterion. Plus a wire-compatibility test asserting generated frames are
byte-identical to the previous hand-written ones.

*Ships:* one family, provably wire-compatible.

### Phase 3 — CI drift check

Add `pm-msgen check` to the Makefile and CI.

*Test:* deliberately edit a generated file; the check fails. Deliberately edit
a spec without regenerating; the check fails.

*Ships:* the guarantee. From here drift cannot be reintroduced for specified
families.

### Phase 4 — C generation adopted

Regenerate the CALF and BALF example clients against generated headers.

*Test:* the existing C example builds and connects (the `test_alf_examples.py`
pattern); a golden-file test asserts the generated parser produces the same
struct as the hand-written one for a captured message corpus.

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

`tests/test_msgen_roundtrip.py::test_every_specified_message_survives_all_transports`

For every message in every spec, over generated random payloads:

```
1. make_*(**payload)                 -> frames
2. parse_*(frames)                   -> object   == payload
3. to_dict -> from_dict              -> object   == payload
4. CALF encode -> C parse -> compare           == payload   (via cffi harness)
5. BALF encode -> C parse -> compare           == payload
6. every validate() rule rejects an out-of-range mutation of each field
7. generated docs list exactly the fields in the spec, no more, no fewer
8. pm-msgen check reports no drift
```

Assertions 4 and 5 are the ones that matter: they prove the Python and C
bindings agree on the wire, which is the property no current test can state.

---

## 9. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | Generated output silently diverges from hand-written behaviour during migration | **High** | Phase 2 byte-identical wire test per family; no family adopted without it |
| R2 | Generator becomes a second system to maintain | Medium | Deliberately small vocabulary (§4.3); no Turing-complete rules; ~1 500 lines projected |
| R3 | Spec expressiveness runs out mid-migration | Medium | Phase 5 is per-family, so an unspecifiable family simply stays hand-written; the generator is opt-in per message |
| R4 | C fixed-size buffers truncate a longer field | **High** | `max_len` mandatory for C targets; `lint` enforces; generated parser returns an error rather than truncating |
| R5 | Committed generated files make review noisy | Low | Generated files carry a `DO NOT EDIT` banner and live in `generated/` directories; reviewers read the spec diff |
| R6 | Enum drift between Python and C | Medium | Both generated from the same `values`; capstone assertion 4/5 compares round-trips |
| R7 | Binary layout changes break deployed C clients | **High** | `family.version` in the spec; BALF header already carries a version byte; generator refuses to change a layout without a version bump |
| R8 | Two engineers edit the same generated file from different specs | Low | `pm-msgen check` in CI catches it before merge |

---

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

---

## 11. Open questions

1. **Spec granularity** — one file per family (proposed) or one per message?
   Families keep related enums together; per-message files diff more cleanly.
2. **Should `models/feed_schema.py` be generated first?** It is the smallest
   surface (7 payloads), already typed, and already has clearing depending on
   it — arguably a better Phase 1 than `trade.yaml` alone.
3. **BALF layout ownership.** The spec would become authoritative for the
   binary layout, which currently lives in `910-app-balf-protocol.md` and the
   example parser. Migrating it is valuable but makes Phase 4 larger.
4. **Runtime validation cost.** Generated `make_*` validates on every
   construction. The engine's hot path publishes per order; the perf notes are
   explicit about microseconds. Proposal: generate `make_*` (validating) and
   `make_*_unchecked` (not), with the engine opting into the latter on
   measured paths only.
5. **Versioning across the wire.** `family.version` covers layout changes, but
   there is no negotiation today. Out of scope here; worth its own note if
   external clients are ever versioned independently.

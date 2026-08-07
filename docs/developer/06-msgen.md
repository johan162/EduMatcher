# Message Generator (`pm-msgen`)

!!! note "Learning objectives"
    After reading this page you will understand:

    - Why a message described in three places drifts, and what a generator does
      about it that a code review does not
    - How to read and write a message specification in `spec/messages/`
    - How to use a generated binding: building, parsing, validating and
      subscribing without a single topic string literal
    - Why `from_dict` deliberately accepts payloads that `validate()` rejects,
      and when you want each
    - What `pm-msgen check` guarantees, and why generation must be
      byte-for-byte deterministic for that guarantee to be worth anything

!!! info "Current status: Phase 2"
    The generator emits the **Python** binding for the **`trade`** family, and
    that binding is now **live**: `models/message.py::make_trade_msg` delegates
    to it, `engine/main.py::_publish_trade` publishes through it, and `pm-stats`
    subscribes with its topic constant. Everything on this page about Python is
    real and tested today. The CI drift check (Phase 3), C generation (Phase 4)
    and the documentation appendix (Phase 6) are not built yet and are marked as
    such. The full plan lives in
    `docs-design/EduMatcher-Message-Generator.md`.

## The problem

A message in EduMatcher is described in at least three places, none of which is
authoritative and none of which is checked against the others:

| Surface | Where |
|---|---|
| The publisher's payload shape | a `make_*` factory in `models/message.py`, or an inline dict in the producer |
| The subscriber's expectations | a topic string literal, repeated across gateways and tools |
| The documentation | `docs/user-guide/270-message-reference.md`, hand-maintained |

Nothing links them. Rename a field on the publisher side and the subscriber
keeps compiling, keeps running, and simply stops seeing the value — no error,
just wrong. That is the failure class this tool removes.

The fix is not more discipline. It is to make one file the source of truth and
**generate** the rest, then have CI fail when the generated output and the spec
disagree.

## How it fits together

```
spec/transports.yaml          the transport registry (ZeroMQ patterns, config keys)
spec/messages/<family>.yaml   one file per message family — the source of truth
        │
        │  pm-msgen generate
        ▼
src/edumatcher/models/generated/<family>.py     committed, DO NOT EDIT
```

Generated files are **committed**. A reader browsing the repository never needs
to run the generator, and `pm-msgen check` in CI proves the committed copy still
matches the spec.

## Commands

```bash
poetry run pm-msgen lint       # validate the spec only
poetry run pm-msgen generate   # write the generated files
poetry run pm-msgen check      # fail if committed output differs from the spec
```

Exit codes follow the `pm-cverifier` convention: `0` success, `1` drift
detected, `2` the spec itself is broken.

Both `generate` and `check` accept `--spec DIR` and `--out-python DIR`, which is
mostly useful in tests. The defaults are the repository layout.

## Writing a specification

### A minimal family

```yaml
family: heartbeat          # MUST equal the filename stem: spec/messages/heartbeat.yaml
version: 1

messages:
  - name: engine_alive
    topic: "system.heartbeat"
    transport: [engine_pub]
    doc:
      motivation: "Liveness ping so a subscriber can tell a quiet engine from a dead one."
    fields:
      - name: sent_at
        type: float
        required: true
        unit: epoch_seconds
        doc: When the engine emitted this ping.
```

That is enough to generate a dataclass, a validating constructor, a parser and a
topic constant.

### Field keys

| Key | Meaning |
|---|---|
| `name` | snake_case identifier, unique within the message |
| `type` | `string`, `int`, `float`, `bool`, `enum`, `ticks` |
| `required` | default `true`. A `required: false` field **must** declare a `default` |
| `default` | what a *producer* gets when it omits the field. Must be a legal value |
| `parse_default` | what `from_dict` substitutes when the key is missing from an *inbound* payload. Need not be legal — see [Coercion vs validation](#coercion-and-validation-are-different-jobs) |
| `unit` | required on every numeric field. One of `display_price`, `ticks`, `shares`, `epoch_seconds`, `epoch_nanos`, `percent`, `dimensionless`, `money` |
| `doc` | prose for the generated documentation and the `describe_*()` table |
| `values` | required for `type: enum`; declaration order is authoritative |
| `validate` | `gt`, `ge`, `lt`, `le`, `max_len`, `min_len`, `max_items`, `pattern` |

!!! warning "The loader is strict, on purpose"
    An unknown key **raises**. It is not ignored, and it is not warned about.

    ```
    SpecError: spec/messages/order.yaml: messages[0] ('order_ack').fields[3]:
      unknown key(s) 'requird' (did you mean 'required'?)
    ```

    A silently-ignored `requird: true` would disable a field with no error,
    which is precisely the class of bug the generator exists to kill. Tolerating
    it here would defeat the whole tool.

### Why `unit` is mandatory on numbers

`unit` never converts anything. It is documentation that the reviewer can see
and the generator can print. It exists because `trade.executed.price` is
display money while `trade_log.price` is ticks — a mismatch that cost a full
session to untangle, and which no type system catches because both are numbers.
Declaring it makes it reviewable.

```yaml
      - name: price
        type: float
        unit: display_price      # not ticks; the publisher already converted
        validate: { gt: 0 }
```

### Topics with parameters

A topic segment may be a `{placeholder}` naming a field of the message:

```yaml
  - name: order_ack
    topic: "order.ack.{gateway_id}"
    transport: [engine_pub]
    doc:
      motivation: "Acknowledge acceptance or rejection of a new order."
    fields:
      - { name: gateway_id, type: string, validate: { max_len: 32 } }
      - { name: order_id,   type: string, validate: { max_len: 64 } }
      - name: status
        type: enum
        values: [ACCEPTED, REJECTED]
```

This is what removes scattered topic literals from subscribers. See
[Example 4](#example-4-subscribing-without-a-topic-literal).

### Transports

A message names transports from `spec/transports.yaml` rather than restating a
pattern and address per message:

```yaml
transports:
  engine_pub:
    pattern: PUB
    subscriber_pattern: SUB
    address_config_key: ENGINE_PUB_ADDR    # symbolic; resolved at runtime
```

`address_config_key` must be a symbolic name, never a literal address — that is
what keeps ports out of generated code. `pm-msgen lint` rejects anything that
looks like `tcp://...`.

!!! info "External protocols are Phase 4"
    `calf`, `balf` and `ralf` are reserved names for the external line and
    binary protocols. Listing one in `transport:` is currently **rejected** with
    a clear message, because nothing generates their projections yet. Declaring
    a spec block that no generator reads would be an unexercised code path
    pretending to be a contract.

## Using a generated binding

Everything below uses the committed `trade` family. Import from
`edumatcher.models.generated.trade`.

### What you get

| Symbol | Purpose |
|---|---|
| `TradeExecuted` | frozen dataclass, one attribute per field |
| `TOPIC_TRADE_EXECUTED` | the topic constant |
| `is_trade_executed(topic)` | topic test, for messages with no parameters |
| `topic_*()` / `PREFIX_*` / `match_*()` | build, subscribe and destructure a *parameterised* topic |
| `make_trade_executed(**kw)` | coerce, validate, return the two bus frames |
| `make_trade_executed_unchecked(**kw)` | identical frames, no validation — hot paths only |
| `parse_trade_executed(frames)` | frames to a validated object |
| `.from_dict()` / `.to_dict()` | interop with existing dict-based code |
| `.validate()` | standalone strictness check |
| `describe_trade_executed()` | field metadata at runtime, for spy tools |
| `FAMILY`, `FAMILY_VERSION`, `FAMILY_TOPICS` | registry, for routers |

### Example 1 — publishing

```python
from edumatcher.models.generated.trade import make_trade_executed

frames = make_trade_executed(
    id="42",
    symbol="ACME",
    buy_order_id="b-1",
    sell_order_id="s-1",
    buy_gateway_id="GW1",
    sell_gateway_id="GW2",
    price=101.5,
    quantity=300,
    aggressor_side="BUY",
    timestamp=1_700_000_000.0,
    tick_decimals=2,
)
# [b'trade.executed',
#  b'{"id":"42","symbol":"ACME",...,"tick_decimals":2}']

publisher.send_multipart(frames)
```

`make_*` returns **exactly two frames**. The per-topic sequence number is a
third frame appended by `SequencedPublisher.send_multipart()` in
`messaging/bus.py` at publish time — never by `make_*`. Adding it here would
double-stamp every message.

!!! tip "Missing and mistyped arguments"
    `make_*` takes keyword arguments and routes them through `from_dict`, so it
    coerces on the way in. `price=100` (an `int`) puts `100.0` on the wire, the
    same as the hand-written factory does. A missing required field raises
    `KeyError`, matching the existing payload classes.

### Example 2 — consuming

```python
from edumatcher.models.generated.trade import (
    is_trade_executed,
    parse_trade_executed,
)
from edumatcher.models.message import decode

frames = subscriber.recv_multipart()
topic, _payload = decode(frames)

if is_trade_executed(topic):
    trade = parse_trade_executed(frames)
    print(f"{trade.symbol} {trade.quantity} @ {trade.price} ({trade.aggressor_side})")
```

`parse_*` coerces *and* validates, so a malformed payload raises
`MessageValidationError` at the boundary rather than producing a plausible-
looking object that fails somewhere deeper. It reads only the first two frames,
so a sequence-stamped message parses unchanged.

### Example 3 — validating without parsing

You often have a payload dict already (from a log, a replay file, a database
row). Skip the frames:

```python
from edumatcher.models.generated.trade import TradeExecuted
from edumatcher.models.generated._runtime import MessageValidationError

trade = TradeExecuted.from_dict(row)     # coerces, never raises on a rule
try:
    trade.validate()
except MessageValidationError as exc:
    log.warning("archived trade %s is not spec-conformant: %s", row.get("id"), exc)
```

This split is the whole point of the next section.

### Example 4 — subscribing without a topic literal

For a parameterised topic the generator emits three helpers, which is what
removes hand-typed topic strings from subscribers:

```python
from edumatcher.models.generated.orders import (   # Phase 5 — illustrative
    PREFIX_ORDER_ACK,
    match_order_ack,
    topic_order_ack,
)

sock.setsockopt_string(zmq.SUBSCRIBE, PREFIX_ORDER_ACK)   # "order.ack."

topic, _payload = decode(sock.recv_multipart())
gateway_id = match_order_ack(topic)      # "GW1", or None if it isn't this topic
if gateway_id is not None:
    ...

# and to publish:
sock.send_multipart(encode(topic_order_ack("GW1"), payload))
```

!!! warning "Why `[^.]+` and not `.+`"
    `match_*` matches a single dot-delimited segment. A greedy `.+` would make
    `order.ack.GW1.extra` match and return `"GW1.extra"` — a subtly wrong
    gateway id rather than a clean `None`. The generated regex is
    `^order\.ack\.(?P<gateway_id>[^.]+)$`.

### Example 5 — runtime field metadata

`describe_*()` returns the spec's own field table, which is what lets a spy or
pretty-printer render units and constraints without hard-coding them:

```python
from edumatcher.models.generated.trade import describe_trade_executed

for field in describe_trade_executed():
    unit = f" [{field['unit']}]" if field["unit"] else ""
    print(f"{field['name']:<16}{field['type']:<8}{unit}")

# id              string
# symbol          string
# ...
# price           float   [display_price]
# quantity        int     [shares]
# aggressor_side  enum
# timestamp       float   [epoch_seconds]
# tick_decimals   int     [dimensionless]
```

### Example 6 — the hot path

`make_*` validates on every call. The engine publishes per match, and the perf
notes are explicit about microseconds, so the generator also emits a
non-validating twin. This is what `engine/main.py::_publish_trade` actually
does today:

```python
from edumatcher.models.generated.trade import make_trade_executed_unchecked

self.pub_sock.send_multipart(
    make_trade_executed_unchecked(
        id=trade.id,
        symbol=trade.symbol,
        buy_order_id=trade.buy_order_id,
        sell_order_id=trade.sell_order_id,
        buy_gateway_id=trade.buy_gateway_id,
        sell_gateway_id=trade.sell_gateway_id,
        price=from_ticks(trade.price, trade.symbol),
        quantity=trade.quantity,
        aggressor_side=trade.aggressor_side,
        timestamp=trade.timestamp / 1_000_000_000,
        tick_decimals=get_tick_decimals(trade.symbol),
    )
)
```

Note the signature difference: `make_*` takes `**kw` because its callers have a
dict of uncertain provenance, while `make_*_unchecked` takes **explicit
keyword-only typed parameters**, so a typo is a `TypeError` at the call site
rather than a missing key on the wire.

The two produce **byte-identical frames** for any input — not just valid input
— which is the only thing that makes the unchecked variant safe to reach for.
See [the cost of the hot path](#the-cost-of-the-hot-path) for why it is built
the way it is.

!!! danger "Use `_unchecked` only on a measured path"
    It exists for the engine's trade publication loop, not for convenience.
    Everywhere else, the validation is the point: it is what stops a malformed
    message reaching a subscriber that cannot tell.

## The cost of the hot path

Adopting a generated constructor on a per-match path is the one place this tool
can make the system *worse*, so the decision was measured rather than assumed.
200 000 iterations, `orjson`:

| Construction | µs/call | vs. hand-written | Byte-identical to `make_*`? |
|---|---|---|---|
| the hand-written dict literal it replaced | 0.96 | — | n/a |
| generated dict literal, **no** coercion | 1.12 | +0.16 | **No** |
| **generated dict literal, inline coercion** — what ships | **1.47** | **+0.50** | Yes |
| via `from_dict` → dataclass → `to_dict` | 4.03 | +3.08 | Yes |

Two things fell out of that table, both of which changed the implementation:

**The obvious implementation was unusable.** Building `_unchecked` on top of
`from_dict` and `to_dict` is the natural way to guarantee the two constructors
agree, and it costs +3.1 µs. `perf-notes.md` records publication optimisations
worth 0.2–1.0 µs *each*; this would have undone all of them several times over.
A function whose entire purpose is "measured hot paths only" cannot be 4× slower
than the code it replaces. So `make_*_unchecked` is generated as a direct dict
literal with the topic pre-encoded at import — the same optimisation the
engine's own `_TRADE_TOPIC` constant was, now generated instead of hand-written.

**Dropping coercion was tempting and wrong.** It saves a further 0.34 µs, and
the engine already passes correctly-typed values, so it looks free. It is not:
`make_*_unchecked(price=100)` would then put `100` on the wire where `make_*`
puts `100.0`. And mypy does **not** catch it — `int` is promotable to `float`,
so `price=100` against `price: float` type-checks clean. That is a silent
divergence between two functions documented as producing identical frames,
which is the exact failure class in [The problem](#the-problem). The 0.34 µs is
paid.

`tests/test_msgen_trade_perf.py` (marker `perf`, deselected by default) guards
against a reversion to the 4× shape. Its threshold is deliberately loose — 3×,
against a measured 1.5× — because it is a guard, not a benchmark, and CI timing
is noisy.

## What adoption looks like

Phase 2 wired the `trade` family in. Three changes, each a different kind:

### `make_trade_msg` — a delegating shim

```python
def make_trade_msg(trade_dict: dict[str, Any]) -> list[bytes]:
    return _gen_trade.make_trade_executed(**trade_dict)
```

Byte-identical output. **One deliberate behaviour change:** it now validates. A
zero price, or a payload with no `aggressor_side`, previously went out on the
wire without complaint and now raises `MessageValidationError`. That is the
point — producers are held to the contract — and because the error subclasses
`ValueError`, callers already guarding with `except ValueError` keep working.

!!! warning "This is the change most likely to surprise you"
    If something that used to publish now raises, it was publishing something
    the spec says is invalid. Fix the producer, or — if the spec is wrong —
    fix the spec. Do not reach for `make_*_unchecked` to make the error go
    away; that variant is for measured hot paths, not for silencing a real
    finding.

### `_publish_trade` — the actual producer

The dict literal is gone; the field list now lives only in the spec. This is
where the value is: before Phase 2, adding a field to `trade.executed` meant
three coordinated edits and still never reached the C clients. Now it is one
edit to `trade.yaml`.

The published **key order changed** as a side effect (`tick_decimals` moved from
the middle to the end). No consumer can observe this — JSON objects are
unordered and every reader uses `.get` — which is exactly why the wire test
asserts equal keys and values rather than equal bytes for this comparison.

### `pm-stats` — the topic constant only, *not* the parser

This one is worth understanding, because it generalises.

`pm-stats` adopted `TOPIC_TRADE_EXECUTED` in place of its three
`"trade.executed"` literals — the ZMQ subscription, the dispatch test, and the
`feed_gaps.stream` name. A topic rename in the spec now reaches the recorder
instead of silently leaving it subscribed to a topic nobody publishes.

It did **not** adopt `parse_trade_executed`, even though the original plan said
it should. `stats/main.py::_on_trade` is deliberately tolerant in three
separately documented ways:

| Tolerance | Why it is there |
|---|---|
| returns early when `symbol`/`price`/`quantity` is missing | a partial print is skipped, not fatal |
| falls back to receipt time when `timestamp` is absent, with a warning | the row is still worth recording |
| accepts a non-numeric `id`, disabling gap detection with one warning | "a synthetic or gateway-supplied id" is an expected input |

`parse_*` validates, so adopting it would make the recorder **raise** on inputs
it currently handles on purpose.

!!! tip "The rule this gives you for Phase 5"
    **A recorder records what it received.** Refusing to store a message
    because it fails the current spec destroys exactly the evidence you need to
    find out why it was malformed.

    So: adopt the **topic constants everywhere** — that is pure gain and zero
    risk. Adopt **`parse_*` only where the consumer genuinely wants to reject a
    non-conforming message** rather than record it. Do not assume every
    subscriber wants validation.

## Coercion and validation are different jobs

This is the one rule worth internalising, because it is unusual and it is
deliberate.

| Function | Coerces? | Validates? |
|---|---|---|
| `from_dict(payload)` | **yes** | **no** |
| `validate()` | no | **yes** — the only strictness gate |
| `make_*(**kw)` | yes | yes |
| `make_*_unchecked(**kw)` | yes | no |
| `parse_*(frames)` | yes | yes |
| `to_dict()` | no | no |

**Why:** the spec should state the honest contract, but the system has an
archive written before that contract existed. Those two requirements conflict
unless reading and asserting are separated.

The concrete case is `aggressor_side`. It is typed as a required `str` in
`models/trade.py` and `models/feed_schema.py`, and the engine always publishes
one of `BUY`, `SELL`, `AUCTION`. Yet four independent deserialisers default it
to `""`, and `clearing/main.py` then writes `trade.aggressor_side or None` to
undo that. Nobody decided `""` was legal; it accreted.

The spec therefore declares the strict contract and adds one lenient fallback:

```yaml
      - name: aggressor_side
        type: enum
        values: [BUY, SELL, AUCTION]
        required: true
        parse_default: ""          # what from_dict substitutes; NOT a legal value
```

```python
archived = {...}                                  # no aggressor_side key
TradeExecuted.from_dict(archived).aggressor_side  # ""  — reads fine
TradeExecuted.from_dict(archived).validate()      # MessageValidationError
make_trade_executed(**archived)                   # MessageValidationError
```

Four consequences worth spelling out:

1. **Nothing that reads history breaks.** `from_dict` is a drop-in for the
   hand-written payload, byte-for-byte.
2. **Every published message is checked**, and the engine already always
   supplies a real value.
3. **`""` never becomes a permanent part of the contract.** Had the spec
   declared it a legal enum value, it would have to become a C enum member in
   Phase 4 — an invented `EDU_AGG_UNKNOWN` sentinel exporting the accident into
   a second language and freezing it in a wire format.
4. **The `""` population becomes countable.** Run `validate()` over the clearing
   archive and read the failure count. Today nothing asserts, so nobody knows
   how many there are.

!!! note "Which should I call?"
    - Reading data your system already published (replay, archive, audit,
      migration): `from_dict`, and `validate()` separately if you want to know.
    - Receiving a live message: `parse_*`. Fail at the boundary.
    - Publishing: `make_*`. Always.

`MessageValidationError` subclasses `ValueError`, so existing call sites that
already guard with `except ValueError` keep working unchanged.

## The guarantee: `pm-msgen check`

Without a check, a generator is a scaffolder and the drift returns within a
release. `pm-msgen check` re-renders every artefact from the spec and diffs it
against what is committed. Any of these fails:

- a spec change without regenerating
- a hand-edit to a generated file
- a missing generated file

```
$ pm-msgen check
pm-msgen check: generated output is out of date with the spec.
Run `pm-msgen generate` and commit the result.

--- generated/trade.py (committed)
+++ generated/trade.py (from spec)
@@ -140,7 +140,7 @@
-    tick_decimals: int = 4
+    tick_decimals: int = 2
```

!!! warning "Determinism is not optional"
    The check only works if generation is byte-identical for an unchanged spec,
    run twice, on any machine. A generator that occasionally reorders its own
    output turns the check into a source of flaky CI failures — which is worse
    than not having it.

    The emitter therefore walks spec declaration order everywhere, never
    iterates a `set`, and puts no timestamp or absolute path in the banner. Three
    tests assert this, including one that regenerates under three different
    `PYTHONHASHSEED` values in separate processes.

Wiring the check into `make _check` and `ci.yml` is **Phase 3** and has not been
done yet.

## Why the generated file looks the way it does

A few decisions that look odd until you know the reason:

**It is already `black`-formatted, and `black` is never invoked.** The emitter
reproduces black's rules directly — double quotes, two blank lines around
top-level definitions, a call exploded across lines only when the single-line
form would exceed 88 columns. Running black at generation time would make the
output depend on the installed black version, reintroducing exactly the flaky-
check risk the previous section is about.

**An enum is not always a `Literal`.** `aggressor_side` is annotated `str`, not
`Literal["BUY", "SELL", "AUCTION"]`, because its `parse_default` of `""` is
outside those values — `from_dict` can legitimately produce it. Annotating it
`Literal` anyway would make the type a lie that every call site has to silence
with a `type: ignore`. Narrowing is `validate()`'s job. An enum *without* a
non-conforming `parse_default` does get a proper `Literal`.

**Regex patterns are module constants, interpolated by object.** A validation
message reads `{_TRADE_EXECUTED_ID_RE.pattern!r}` rather than embedding the
pattern text, because a spec pattern may contain quotes or braces — either of
which would break the f-string that carried it.

## Adding a family

1. Write `spec/messages/<family>.yaml`. Run `pm-msgen lint` until it passes.
2. Run `pm-msgen generate`. Review the generated file as you would any other.
3. Write a wire-compatibility test comparing the generated output against the
   existing hand-written producer for that family. **No family is adopted
   without one.**
4. Only then change call sites.

### Two comparisons, not one

Step 3 needs care, because "byte-identical" is the right assertion in one
direction and the wrong one in the other:

| Comparison | Assert | Why |
|---|---|---|
| hand-written factory vs generated `make_*` | **byte-identical frames** | Both derive from a `to_dict()` over the same fields. There is no excuse for a difference. |
| an inline producer dict vs the generated payload | **equal key sets and equal values** | JSON objects are unordered and every consumer reads with `.get`, so key order is not part of the contract. Asserting byte-identity would be stronger than the system actually promises, and would block a legitimate change. |

The `trade` family shows why the distinction matters:
`engine/main.py::_publish_trade` emits `tick_decimals` between `price` and
`quantity`, while `feed_schema.TradeExecutedPayload.to_dict()` emits it last.
Both are correct. Nothing on the wire can tell. Only a byte-comparing test can,
and it would be testing the wrong thing.

`tests/test_msgen_trade_wire_compat.py` makes both claims explicitly, and pins
the divergence so it cannot be quietly forgotten.

## Testing

| File | Covers |
|---|---|
| `tests/test_msgen_spec.py` | the loader and its strictness — every rejection is a test |
| `tests/test_msgen_python.py` | determinism, drift detection, parameterised topics, every `validate` rule |
| `tests/test_msgen_trade_wire_compat.py` | wire compatibility, and exactly what Phase 2 adoption changed |
| `tests/test_msgen_trade_perf.py` | hot-path budget (marker `perf`, deselected by default) |

Two tests in the wire-compat file are worth knowing about because they will
fail if you change the wrong thing:

- `test_no_trade_executed_literal_remains_in_adopted_modules` scans the adopted
  modules for a `"trade.executed"` string literal. It is how "adoption" is
  measured against the 108-literal problem, and it caught a subscription literal
  I had missed.
- `test_key_order_differs_as_documented` pins the pre- and post-adoption key
  orders against each other, so the divergence stays a recorded decision rather
  than becoming folklore.

## Scope

What the generator owns: message shape, projection, construction, parsing and
validation.

What it does not, and will not:

- **The wire formats.** It describes what already flows. CALF text and BALF
  binary are pedagogical artefacts that students read and parse by hand;
  replacing them with Protobuf would remove the teaching value.
- **Stateful normalisation.** `md_gateway/normaliser.py` keeps its top-of-book
  cache and delta suppression; `ralf_gateway` keeps its per-symbol execution
  counts. In Phase 4 they will call the generated projection instead of
  hand-coding a `{"PX": ..., "QTY": ...}` literal, but the business logic stays
  hand-written. Drawing the line here is what keeps this a message-shape tool
  rather than a second gateway.
- **Engine business logic**, and anything needing a validation language rich
  enough to express the risk rules — that would be a second implementation of
  the engine.

## Roadmap

| Phase | Ships | Status |
|---|---|---|
| 1 | Generator + `trade.yaml` + Python binding, committed unused | **done** |
| 2 | Adopt for `trade`: `make_trade_msg`, `_publish_trade`, `pm-stats` topics | **done** |
| 3 | `pm-msgen check` in `make _check` and `ci.yml` | not started |
| 4 | C generation; CALF/BALF/RALF projections; cffi round-trip harness | not started |
| 5 | Remaining families, one per change | not started |
| 6 | Generated `271-message-appendix.md` | not started |

!!! warning "Phase 3 is the one that matters most, and it is not done"
    Until `pm-msgen check` runs in CI, nothing stops someone hand-editing
    `models/generated/trade.py` and having it merge. The generator is currently
    a scaffolder with a good test suite; the check is what makes it a
    guarantee. Run `poetry run pm-msgen check` before committing until then.

## See also

- `docs-design/EduMatcher-Message-Generator.md` — the full design, including the
  normative IDL in Appendix B
- [Message Reference](../user-guide/270-message-reference.md) — the hand-written
  narrative reference this generator will eventually supplement

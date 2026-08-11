Version: 2.0.0

Date: 2026-08-11

Status: Design Specification — implemented; describes the shipped system

> This is a clean re-statement of the message-generator design, written after
> the fact to read as the design *should* have read with perfect foresight. It
> folds every lesson the phased implementation produced back into the rationale,
> so each decision is presented with the reason it turned out to be right rather
> than as a correction to an earlier draft. The phase-by-phase history — what was
> tried, got wrong, and fixed — lives in the git history of this file (up to
> v1.10.0) and in the commit log; it is not repeated here. Where the shipped
> system deliberately departs from "generate everything," §9 says so and why.

# Message Generator — Canonical Message Specification and Code Generation

Generate the Python bindings, the C bindings, and the reference documentation
for every EduMatcher message from one canonical specification, so the three can
no longer disagree — and make a CI check fail the build the moment they do.

The system is complete: **fourteen families, 106 messages, 34 record types**,
each with a Python binding; `trade` and `order` also carry C bindings for their
CALF text and BALF binary projections. Every producer in the tree reaches the
wire through a generated builder, with exactly two deliberate exceptions (§9),
and `docs/user-guide/270-message-reference.md` is generated from the same specs.

## Table of Contents

1. [The problem, measured](#1-the-problem-measured)
2. [Goals and non-goals](#2-goals-and-non-goals)
3. [Why not an off-the-shelf IDL](#3-why-not-an-off-the-shelf-idl)
4. [The specification model](#4-the-specification-model)
5. [Generated output](#5-generated-output)
6. [Determinism and the drift check](#6-determinism-and-the-drift-check)
7. [The generator: structure, linting, diagnostics](#7-the-generator-structure-linting-diagnostics)
8. [Adoption](#8-adoption)
9. [The one deviation](#9-the-one-deviation)
10. [Engine latency: the cost of one source of truth](#10-engine-latency-the-cost-of-one-source-of-truth)
11. [Risks](#11-risks)
12. [What this prevents](#12-what-this-prevents)
13. [Design principles](#13-design-principles)
- [Appendix A — IDL specification (normative)](#appendix-a--idl-specification-normative)

---

## 1. The problem, measured

A message in EduMatcher was, before this tool, described in at least three
places, none authoritative and none checked against the others:

| Surface | Where |
|---|---|
| the publisher's payload shape | a `make_*` factory in `models/message.py`, or an inline `dict` literal in the producer |
| the subscriber's expectations | a topic string literal, repeated across gateways, tools and clients |
| the documentation | `docs/user-guide/270-message-reference.md`, hand-maintained |

Counted against the tree at the outset: 92 `make_*` factories but only 7 typed
payloads; 108 distinct topic string literals across 25 files outside
`message.py`; a 2 200-line reference page that omitted a third of the messages
and documented topics no producer emits; and a C client surface with **no
message types at all** — a generic `calf_field_t` key/value bag every client
re-parsed by hand.

Three failure classes follow, and all three are silent:

- **A publisher-side rename stops a subscriber receiving, with no error.** The
  subscriber keeps compiling and running and simply stops matching the topic.
- **A field added to a producer never reaches a hand-written consumer or the
  C clients**, because nothing links the surfaces.
- **The documentation drifts in both directions** — describing fields no
  producer sends and omitting messages that exist — and its defects cost nothing
  at runtime, so nobody is ever prompted to look. That asymmetry is the deepest
  part of the problem: a wrong builder raises, a wrong subscriber goes quiet, but
  **a wrong reference page is read, believed, and acted on.**

The measurements are a point-in-time snapshot; the shape they describe is the
point, and §7's tooling keeps the counts honest rather than re-derived by hand.

## 2. Goals and non-goals

### Goals

1. One canonical file per message family; everything else generated.
2. Generated Python per message: a typed payload, a validating constructor, a
   parser, and topic constants/helpers — so no consumer hand-writes a topic.
3. Generated C: a typed struct, accessors, a validating parser and a `strerror`,
   for the text (CALF) and binary (BALF) client protocols.
4. Generated reference documentation, alongside a hand-written narrative half the
   generator never touches.
5. Validation rules declared once and enforced by *both* language bindings.
6. Documentation-only metadata (motivation, units, examples, provenance) that
   never reaches the wire but is checkable.
7. **A CI check that fails when generated output differs from what is
   committed** — the property that actually keeps the surfaces aligned. Without
   it the generator is a scaffolder and the problem recurs within a release.

### Non-goals

- **Replacing the wire formats.** JSON on the bus, CALF text, BALF binary and
  RALF post-trade text are pedagogical artefacts — students read and parse them
  by hand. The generator describes what already flows; it does not change it.
- **Generating business logic.** Only message construction, parsing and
  validation. A validation language rich enough to express the engine's risk
  rules would be a second implementation of the engine.
- **Generating stateful normalisation.** `md_gateway/normaliser.py` and
  `ralf_gateway` keep their per-symbol caches and delta suppression; they call
  the generated *projection* instead of hand-coding field-map literals (§4.9).
- **A big-bang migration.** Adoption is per family, per message, and each step is
  independently wire-compatible (§8).
- **Cross-language RPC.** This is a message-shape tool, not a service framework.

## 3. Why not an off-the-shelf IDL

| Option | Why it does not fit |
|---|---|
| Protocol Buffers / FlatBuffers | Replace the wire format. EduMatcher's formats are the teaching artefact; changing them removes the value. |
| JSON Schema | Validates JSON only. No C generation, no binary layout, no topic model. |
| AsyncAPI | Closest on the topic model, but its generation targets are web-oriented and it cannot express BALF's fixed binary header or CALF's positional text. |

The differentiator is that EduMatcher carries **several encodings of one logical
event** — JSON on the internal bus, CALF text key/value, BALF binary with a fixed
header, RALF post-trade text — and each is a **projection** of the bus payload,
not a copy of it: a transport carries a *subset* of fields, under its own names,
and some events do not appear on some transports at all. No off-the-shelf tool
covers that projection-across-heterogeneous-wire-formats model, and the
specification it needs is small enough that owning it is cheaper than bending one
that does not fit. Owning it is also what makes the IDL a place to encode the
system's own hard rules — units, presence, the absence of maps — which a generic
tool has no vocabulary for.

## 4. The specification model

One YAML file per family under `spec/messages/`, plus one `spec/transports.yaml`
registry. The normative grammar is Appendix A; this section is the design and its
motivation.

### 4.1 One file per family

A family file names its `family`, an integer `version` (the logical layout
version), a list of `messages`, and — when a message embeds structured data — a
top-level `types` block of reusable record definitions. Related messages and the
records they share live together, which is what a router built from a family's
`FAMILY_TOPICS` needs. **A family's name is its topic root**: `combo.*` events
are a separate family from `order` even though they answer `order.combo`, because
folding them into `order` would make that family's registry advertise topics it
does not own, and a router would subscribe to topics `order` never publishes.
Relationships across roots are expressed with `see_also`, which costs nothing and
does not lie to a registry.

### 4.2 Coercion and validation are different jobs (the central contract)

This is the one rule the whole design turns on, because it is what lets the spec
be **strict** about a field while the running system stays **tolerant** of an
archive written before the spec existed.

| Function | Coerces? | Validates? |
|---|---|---|
| `from_dict(payload)` | **yes** | **no** |
| `validate()` | no | **yes** — the only strictness gate |
| `make_*(**kw)` | yes (via `from_dict`) | yes |
| `parse_*(frames)` | yes (via `from_dict`) | yes |
| `to_dict()` | no | no |

Three normative consequences:

- **`from_dict` never validates.** It performs exactly the `str()`/`int()`/
  `float()` coercion and `.get(field, parse_default)` fallbacks the hand-written
  payload performed, and nothing else. A parser that cannot read the system's own
  archive is useless, and every adoption depends on `from_dict` being a drop-in
  for the hand-written equivalent.
- **`validate()` is the only place a rule is enforced.** A consumer reading
  historical data can choose leniency by calling `from_dict` alone, while every
  *producer* path is strict.
- **`make_*` routes through `from_dict`, never the dataclass constructor.**
  `Cls(**kw)` skips coercion, so `make_*(price=100)` would put an `int` on the
  wire where the hand-written factory puts a `float` — a silent wire difference,
  and exactly the failure class this tool exists to remove.

The worked case that motivated it: `trade.executed`'s `aggressor_side` is
`required` with values `[BUY, SELL, AUCTION]` — the honest contract, and what the
engine always publishes — while five deserialisers historically defaulted it to
`""` for replayed archives. The spec declares the strict contract; `from_dict`
keeps the `""` fallback via `parse_default`; and the `""` population becomes
*countable for the first time* by running `validate()` over the archive. Strict
for producers, lenient for readers, expressed as one declared line instead of an
accident spread across five files.

The corollary for consumers is a rule, not a preference: **a recorder records
what it received.** A statistics recorder or an archive replayer adopts the
generated *topic constant* but **not** `parse_*`, because refusing to store a
message that fails today's spec destroys exactly the evidence needed to find out
why it was malformed. Validation belongs on the producer side and at trust
boundaries. This is why `parse_*` and the topic constants are separate helpers,
and why §9's deviation exists at all.

### 4.3 Presence: four regimes, and two shapes deliberately not modelled

`required: false` alone does not say what a field is on the wire, and the three
possibilities differ observably, so the spec must be explicit. There are **four**
presence regimes:

| Declaration | Wire | Python |
|---|---|---|
| `required: true` | always present | `T` |
| `required: false` + `default: X` | always present, `X` when unset | `T = X` |
| `required: false` + `nullable: true` | always present, `null` when unset | `T \| None = None` |
| `required: false` + `nullable` + `omit_when_none` | **absent** when unset | `T \| None = None` |
| `required: false` + `omit_when_empty` | **absent** on the empty string | `str = ""` |

`omit_when_empty` is the most common presence rule in the system — 27
hand-written builders omit a key on `if self.x:` (the empty string, not null) —
and it is deliberately strings-only: on a number falsy-omit would silently drop a
legitimate zero, and on an enum `""` is not a declared value. `omit_when_none`
and `omit_when_empty` are mutually exclusive on a field, and the loader **refuses
a `required: false` that states none of the four**, because the four differ on
the wire and a silent choice is how a spec comes to say something its author did
not mean.

Two shapes are deliberately *not* modelled, each because the simpler thing is
correct:

- **A tri-state `absent ≠ null ≠ value`** (PATCH-style). Verified rather than
  assumed: every consumer in the tree reads these fields with `.get` and tests
  `is None`, never `in payload`. Absence and null are indistinguishable to every
  reader, so one flag suffices; a tri-state would be a model nobody needs.
- **A "these fields are present together or absent together" block.** That is a
  record (§4.5), not a presence flag — and a record makes the half-set state
  *unconstructible* rather than merely detected.

### 4.4 Units live in the declaration, never the representation

A field's `unit` (`display_price`, `ticks`, `shares`, `epoch_seconds`,
`epoch_nanos`, `duration_nanos`, `percent`, `dimensionless`, `money`) is declared
metadata: it appears in the generated documentation and is enforced-by-review, and
it is **never** a runtime conversion. This is a hard design rule, and the reason is
a class of bug the alternative guarantees:

Encoding a price's unit in its *runtime type* — "an int is already ticks, a float
is display money" — cannot be enforced anywhere, so it drifts. A display price of
exactly `150` is then indistinguishable from `150` ticks: a silent 100× mispricing
on a two-decimal instrument. The design therefore fixes one engine-inbound unit —
**ticks, everywhere, with no exceptions** — makes converting the *submitting
gateway's* job, and has the engine **reject** a non-integer inbound price rather
than sniff its type and truncate it. A gateway that forgets to convert gets a
rejection, not a position at 1/100th of the intended price. `unit:` exists so that
this rule is visible in the spec and the docs; a convention that lived in
int-vs-float would survive undetected, which it did across several inbound paths.

The wider principle, which recurs: **a unit — and a relationship between fields —
belongs in a field's declaration, never in its representation.** A generator can
enforce a declaration; it cannot enforce a convention.

### 4.5 Records, not flat pairs and not maps

Structured data is expressed with two constructs and, deliberately, no third.

**`nested` and `list[T]` — records.** A family declares record types under
`types:` and a field references one by name (`type: nested, ref: Foo`) or holds a
list of them (`type: list, ref: Foo`). Records may embed records to **any
depth** — the loader walks the reference graph and rejects only a *cycle*, naming
the path, because what the fixed-size C generator cannot survive is a cycle, not a
level. Types are emitted in dependency order so a spec may declare them top-down
and read naturally. Two guiding choices:

- **A group of fields that travel together is a record, not an `a_b`-prefixed
  flat pair.** `next_state`/`next_at`, `command_id`/`gateway_id`,
  `day_open`/`day_high`/`day_low`, `corridor_low`/`corridor_high` were each one
  guard (`if a and b:`) away from being a nullable record. A record beats a
  co-presence constraint on four counts: it *describes the thing* rather than a
  symptom; it makes the half-set state **unconstructible** instead of merely
  rejected; it composes and is documented once; and in C it is a named struct and
  a null pointer rather than two members plus a `has_x` flag the caller must
  remember to test. The naming carries meaning the flat pair could not:
  `reply_to` says what `command_id`+`gateway_id` *is* — a return address.
- **A record is named for what it is, not the message that carries it.** A record
  named after its message (`QuoteBootstrap` on `quote_bootstrap`) collides with
  that message's generated class, because both PascalCase to one name; the loader
  rejects the collision, but the fix is the better name (`ActiveQuote`) — which
  is what the record *is* — not a suffix.

**No maps, deliberately.** The IDL has no map construct and has never needed one.
Every map the system carried was one of two things, and reading the producer told
which:

- **a record that was never declared** — the key was a *value*. `log.notify`'s
  `{"INFO": 3}` is a list of `{level, count}` records; `leg_fill_qty: {0: 5}` is
  `legs[0].filled_qty`, the list index already being the key.
- **a signature that was never narrowed** — a generic `**payload` splatted onto
  the wire (`drop_copy`), which named fields replace.

Both are the wire being wrong. Naming this out has a sharp payoff at adoption:
`from_dict` reads *declared keys only*, so routing a generic `**payload` through a
generated builder **silently drops** anything the spec does not declare — the one
way adoption could make a wire *less* safe. Narrowing the signature to named
parameters (or a declared record) removes the map and the hazard together.

### 4.6 The type system

| Spec type | Python | C | JSON | Required companions |
|---|---|---|---|---|
| `string` | `str` | `char[N]` | string | `max_len` when any transport is external |
| `int` | `int` | `int64_t`/sized by `repr` | number | `unit` (lint) |
| `float` | `float` | `double` | number | `unit` (lint) |
| `bool` | `bool` | `uint8_t` | bool | — |
| `enum` | `str` + `Literal` | `enum` + `_to_str`/`_from_str` | string | `values`; `enum_map` for binary |
| `ticks` | `int` | `int64_t` | number | `unit` |
| `list` | `list[T]` | `T[N]` + count | array | `item:` (scalar) **or** `ref:` (record), exactly one; `max_items` when external |
| `nested` | dataclass | struct | object | `ref:` naming a `types` entry |

`list` takes `item:` for a scalar element (`list of string`) or `ref:` for a
record element, and exactly one — a list of names is not a flattened record, so
requiring a record type for it was a restriction wider than its reason. `enum`
and `ticks` are excluded as scalar element types (an enum needs `values:` per
element; a record is the answer when elements need rules). For C, `list`
generates a fixed-size array plus a count, never a pointer, consistent with the
no-allocation rule (§5.2). Lists are **non-nullable by construction** — an empty
list is how a list says it has nothing, and null would be a second spelling every
reader must handle.

### 4.7 Validation, invariants, and invalid rules

Per-field rules, enforced in both languages: `gt`, `ge`, `lt`, `le`, `max_len`,
`min_len`, `max_items`, `pattern`, plus `required`/`default`/`values`. Genuinely
relational rules use `invariants`, a deliberately non-Turing-complete boolean
combination of comparisons over the message's own fields (grammar in Appendix A);
anything richer stays hand-written.

Three loader guarantees that a validation rule cannot itself be silently broken:

- **A rule can be invalid.** `min_items: 5, max_items: 2`, negative bounds, or an
  `omit_when_empty` field with a positive `min_items` (which can never be empty,
  so the omission can never fire) are **loader errors**, not runtime surprises —
  the loader is the only place that can say so before every message fails.
- **A rule that does nothing is rejected.** Scalar `validate` keys on a list, a
  non-empty list `default`, `default` alongside `omit_when_empty`, `parse_default`
  on a list — each silently did nothing, which is worse than either enforcing or
  refusing.
- **When a construct grows a second form, every rule about the first is re-asked
  against it.** The loader is one function but its branches are not: a rule tested
  only on the `ref:` branch does not protect the `item:` branch. This is a
  standing obligation on the loader's tests, not a one-off.

### 4.8 The transport registry

`spec/transports.yaml` names each transport once — its ZeroMQ pattern (or `TCP`
for the external line/binary protocols) and a **symbolic** `address_config_key`
resolved from config at runtime, never a literal address. A message lists
`transport: [engine_pub, calf, ralf]` by name; `pm-msgen lint` rejects an unknown
transport, and the generated docs print the pattern and config key rather than a
hand-typed "Published by" sentence that would drift. The generator emits ZeroMQ
helpers for bus transports and field projections + parse/serialise functions for
the external ones (`calf`/`balf`/`ralf`).

### 4.9 Per-transport projection

The three client-facing encodings of a "trade" are **not the same fields under
three names**; they are three projections of the engine's bus payload. The CALF
`TRADE` line carries `{PX, QTY, SIDE}` and drops the engine trade id; the RALF
`EXEC` line carries most fields and maps one source field to several keys
(`id → [EXEC_ID, MATCH_ID]`); the BALF `execution_report` is a private per-order
fill that is not the public print at all. Each `encoding.<transport>` block says:

- `include:` — which source fields the transport carries (`all` or a list).
- `keys:` — the per-transport name(s) for each field.
- `gateway_injected:` — envelope keys (`CH`/`SYM`/`SEQ`/`TS`) the gateway supplies
  at send time; documented and round-tripped, never sourced from the payload.

Two rules the projection model forces, both learned the hard way and both
normative:

- **A projection depends on a subset, so its function takes a payload mapping,
  not a constructed message.** `project_<msg>_<transport>(payload)` reads only the
  included fields. Requiring a gateway to hold eleven fields in order to emit
  three would re-couple exactly the surfaces the projection exists to separate.
- **`include: all` means "every field except the topic parameters."** A topic
  parameter (`order.ack.{gateway_id}`) is dropped from the body by default — but
  a message that also *carries* the parameter in its body (`book.{symbol}`) must
  enumerate its fields, because "named in the topic" and "absent from the body"
  are two different facts and only the second is a wire property. This default is
  a known rough edge: four specs carry a hand-written field list a new field
  could be forgotten from. Making `all` literal, or adding a third value, is a
  future change with its own regeneration diff.

The generator owns the projection and its serialise/parse; it does **not** own the
stateful normalisation around them. `md_gateway/normaliser.py` keeps its
top-of-book cache and delta suppression and simply calls the generated
projection. That line is what keeps the tool a message-shape tool, not a second
gateway.

### 4.10 Deprecation

A field gains `deprecated_since` and `removed_after`. While deprecated it stays
present and optional, `lint` requires a non-empty `doc`, and the generated docs
move it to a "Deprecated fields" sub-table. `pm-msgen check` fails if a field
disappears from a spec without first passing through `deprecated_since`.

## 5. Generated output

```
spec/messages/*.yaml
        │
        ├── src/edumatcher/models/generated/<family>.py       (Python)
        ├── docs/examples/generated/edumatcher_<family>.h/.c  (C, trade + order)
        └── docs/user-guide/270-message-reference.md          (docs)
```

All committed, so a reader browsing the repo or a student compiling a C example
never runs the generator; CI regenerates and diffs (§6).

### 5.1 Python

Per message: a `@dataclass(slots=True)` payload with a `Literal` for each enum, a
`validate()`, `from_dict`/`to_dict`, `make_*` (coerce+validate) and, where the
message carries no record, `make_*_unchecked` (§8.4); `parse_*`, `is_*`, and for a
parameterised topic the trio `topic_*()`, `match_*()`/`PREFIX_*`. A single
hand-written, committed `_runtime.MessageValidationError` (subclassing
`ValueError`, so existing `except ValueError` sites keep working) is imported by
every family module rather than each declaring its own.

### 5.2 C

A C struct mirrors the transport **projection**, not the full bus payload, because
C clients speak CALF/BALF and never the internal bus: a public CALF trade yields a
three-field struct, the BALF `execution_report` yields its full fixed-layout
struct. Fixed-size buffers, no allocation, `int` returns, matching the existing
example clients so generated code drops in beside hand-written code. The generated
C compiles under `-Wall -Wextra -pedantic -Werror` — "generated" is not an excuse
for code the project would reject from a person, and `-Werror` has caught real
generator bugs (a `ge: 0` rule emitted as `unsigned < 0`, readers emitted out of
declaration order).

Error codes are a **per-function contract, not a global registry**, because the
hand-written parsers already had two incompatible conventions: `0` success, then
small negatives whose meaning is documented per generated function, and every
family emits `edu_<family>_strerror(int)` so a bare `-4` in a log is legible.
Binary layout is byte-exact against the production gateway codec: the layout rule
requires every body byte covered once, gaps as explicit `reserved` runs, so "eight
bytes short of `frame_size`" is a load-time error naming the uncovered range
rather than an invisible defect — which is precisely the defect that shipped in the
hand-written example parser this tool replaced.

### 5.3 Documentation

`270-message-reference.md` is one page built from two halves:

| Half | Source | Checked by `pm-msgen check` |
|---|---|---|
| topic index, record types, one section per message | `spec/messages/*.yaml` | yes |
| bus concepts, transports, the CALF protocol narrative | `270-preamble.md` (hand-written) | no — copied **byte for byte** |

The split is load-bearing. A documentation generator that starts producing
narrative starts inventing, which relocates §1's failure rather than removing it.
The preamble is prose the spec has no field for, so it stays hand-written and is
reproduced verbatim — a property with its own test, because the first thing a
naïve blank-line normaliser does is silently reformat the human's prose.

`doc.published_by` is a required key holding a list from a **closed vocabulary of
process roles**. It is deliberately coarse — a role, not a module path or a port —
because *a fact worth tabulating changes less often than the thing it describes*:
a module path moves with every refactor and would be wrong more often than the
role. A twelfth role is a spec change with a regenerated page, and a typo fails the
loader by name. Sockets and ports, which do move, live in `doc.example_note` (prose
about one message) rather than in a column the appendix aligns.

The generated page states what the hand-written one could not: **coverage** (a
test asserts every topic and record type has a section — a page that silently omits
a third of the system is worse than one merely out of date), **presence** (a phrase
per regime, so a reader can tell an absent key from a null one), **units** (which
had never appeared in the reference), and **bounds** (`max_len 32` on the page and
in the builder are now the same fact).

### 5.4 The helper surface

Generated per family, so no consumer hand-writes them: `topic_*`/`PREFIX_*`,
`match_*`, `parse_*`, `make_*`, `make_*_unchecked` (where applicable), `to_dict`/
`from_dict`, `validate`, `FAMILY_TOPICS` (for routers and spy tools) and
`describe_*` (field metadata at runtime, for `pm-*-spy` pretty-printing and for
answering "which inbound messages carry a price?" from the spec rather than a
hand-maintained list).

## 6. Determinism and the drift check

`pm-msgen check` regenerates into a temporary tree and diffs against what is
committed. It fails on a spec change without regeneration, a hand-edit to a
generated file, or documentation drifting from the spec. This is the whole point:
without it the generator is a scaffolder and §1 recurs within a release.

The check is only sound if generation is **byte-for-byte deterministic** — same
spec, same bytes, any machine, any run. That requires declaration-ordered
iteration (never `set` order), no wall-clock timestamps or absolute paths in the
`DO NOT EDIT` banner, and stable enum ordering. Two design choices protect it:

- **The emitter produces black-formatted output directly**, rather than shelling
  out to `black`, so the output does not depend on a formatter version. The proof
  that it reproduces black's rules is `black` itself: a test runs `black --check`
  over the committed bindings. Every formatting defect this generator has had was
  found that way — which is the correct division of labour, and the reason a
  formatter must **never** be run across `src/` while verifying the generator: it
  repairs the evidence, turning one clear failure into three confusing ones.
- **The check runs in CI as `PYTHONPATH=src python -m edumatcher.msgen.cli check`,
  not `pm-msgen check`.** The `code-check` job installs with `--no-root`, so the
  console script is not on `PATH` there; the module invocation works because the
  generator's only dependency, `pyyaml`, is a main dependency. A test parses the
  `Makefile` and CI workflow and fails if the check drops out of either — a
  guarantee an unrelated refactor can silently remove is not a guarantee.

## 7. The generator: structure, linting, diagnostics

`src/edumatcher/msgen/` — a package under `src/edumatcher/`, registered as
`pm-msgen = "edumatcher.msgen.cli:main"`, with tests under `tests/test_msgen_*.py`,
following the `cverifier`/`config_gen` convention. No new dependency: templates are
hand-rolled string assembly (Jinja2 would add a dependency and a whitespace-control
problem in exchange for nothing at this size, and byte-for-byte determinism is
easier to audit in plain Python), and the outer syntax is YAML so `pyyaml` is the
lexer. Nothing under `engine`/`alf_gwy`/… imports the generator; only the committed
output is a runtime dependency.

`pm-msgen lint` catches what generation alone cannot: a numeric field without a
`unit`, a `string` without `max_len` reaching an external transport, an enum
without `values`, a message without `doc.motivation` or `doc.published_by`, a topic
parameter absent from the fields, a record type whose class name collides with a
message's, a reference cycle among records, and — across the whole tree — a topic
declared in two families or a transport reference absent from the registry.

The loader is built for compiler-grade errors: it loads with `yaml.compose()`
(not `safe_load`) so every AST node carries `file:line:col`; every diagnostic is a
coded `Diagnostic` (namespaced `Y`/`G`/`V`/`X`, mirroring `cverifier`) with a
caret snippet and a "did you mean 'required'?" suggestion for any closed
vocabulary; a run reports **all** errors in a layer rather than failing on the
first; and layers gate — a mistyped key never spawns a cascade of misleading
semantic errors. The strict loader (unknown keys are an error) is not optional:
`requird: true` silently disabling a field is precisely the failure class this
tool exists to kill.

`pm-msgen grep-literals` measures the migration: every quoted topic literal
outside `models/generated/` and `models/message.py` matching a declared topic.
Its needle must handle parameterised topics written as f-strings — the closing
`"` anchor that is right for an exact topic must be *dropped* for a prefix, or the
scanner reports "migrated" while `f"order.fill.{gw}"` sits hard-coded (which it
did, for forty topics across eight modules, undetected). The lesson is general:
**a check that has never disagreed with you has not been tested** — the tool that
only ever confirms what you already found by hand cannot tell you when you missed
something.

## 8. Adoption

### 8.1 Incremental, per family

A message is **adopted** when its producer reaches the wire through the generated
`make_*` (or `make_*_unchecked`) builder rather than an open `encode(topic, dict)`.
Adoption is per family, each step independently wire-compatible, gated by a test of
one of two strengths:

- **byte-identical frames**, where two builders derive from the same `to_dict()` —
  there is no excuse for a difference; or
- **equal key sets and equal parsed payloads**, where a hand-written producer emits
  keys in a different order — JSON objects are unordered and every consumer uses
  `.get`, so byte-identity there would be stronger than the system's actual
  contract and would freeze an incidental field order forever.

Each producer is **key-set probed before adoption, not after**: the emitted keys
must be exactly the declared set, because `from_dict` reads declared keys only and
would silently drop the rest. An enumeration test (`test_msgen_adoption.py`) pins
the set of *unadopted* messages to exactly the one deviation of §9, so a new
`encode`-built producer, or a deleted builder, fails the suite instead of merging
quietly.

### 8.2 A recorder records; it does not validate

Restating §4.2 as an adoption rule because it is the one most easily got wrong:
adopt the *topic constants* everywhere, but adopt `parse_*` only where the consumer
genuinely wants to reject a non-conforming message. A statistics recorder, an audit
log, or an archive replayer adopts the constant and keeps its tolerant hand-written
payload handling. **Read the consumer's existing tests before adopting** — they
encode the contract its callers rely on, which is more reliable than either the
design or a reading of the handler.

### 8.3 The boundary audit

Adoption turns a permissive producer into a validating one, so **every previously
harmless input must be re-asked against the new rules**. When a builder starts to
validate, list every field whose value originates *outside* the process — inbound
identifiers echoed into replies, outbound strings built from wire input — and check
the spec's bound against the source's bound. Where the source has none, the boundary
needs one, because an unbounded value reaching a `max_len`-bounded field becomes a
`MessageValidationError` **inside the generated builder**, far from the line that
produced it.

The consequence of that error depends on *where in the handler the validating
builder sits*, and all three outcomes have been observed:

- **before any guard** — the process crashes (a handler with no `try/except`);
- **before the reply** — the caller gets no answer and waits for a timeout;
- **after the reply** — the action runs, the caller is told `accepted: true`, and
  the audit record of a privileged action vanishes into a logged exception, which
  on a feed whose purpose is being the record is the worst of the three because
  nothing is blocked to prompt a look.

So the audit runs in **both directions** (fields echoed outward and fields accepted
inward) and clamps at the boundary the value crosses. A subtlety worth encoding: a
clamp helper *named for what it does to a value* (`_clamp_wire_text`) is safe to
reuse; one *named for the kind of value it expects* (`_clamp_wire_id`, which
upper-cases) is not — reusing the upper-casing clamp on a mixed-case correlation
key would route replies to a topic nobody is subscribed to.

### 8.4 `make_*_unchecked` and the hot path

The generator emits `make_*_unchecked` for measured hot paths — a builder with the
same field order and serialiser as `make_*` but no `validate()`. Two design
decisions:

- **It builds the payload dict literal directly, not via `from_dict`/dataclass/
  `to_dict`.** The routed shape measured 4.03 µs against a hand-written literal's
  0.96 — four times slower, unusable on a path where publication optimisations are
  counted in tenths of a microsecond. The direct build is ~1.47 µs.
- **Coercion is kept even in `unchecked`.** Dropping it saves ~0.34 µs and
  reintroduces a silent int/float wire divergence mypy cannot catch (`int` promotes
  to `float`; `bool` subclasses `int`). Paying 0.34 µs to keep two functions
  documented as byte-identical actually so is the whole point of the tool.

A message carrying a **record** gets no `unchecked` variant — a record has no dict-
literal form — and no such message is a measured hot path, so omitting it is more
honest than emitting a slow function under a name that promises speed.

## 9. The one deviation

The design's rule is that every producer reaches the wire through a generated
builder. Exactly one message deliberately does not, and it is pinned by
`test_msgen_adoption.py` so the exception cannot quietly grow.

**`order.execution_report` — the BALF binary frame.** It has no bus topic and
makes no `make_*` call, so the AST enumeration that defines "adopted" (a module
calling `make_<name>`) does not see it. But its **layout comes from the spec**: the
generated C and Python binary projections are round-trip tested byte-for-byte
against the production gateway codec. It is adopted in the sense that matters — the
spec is authoritative for its bytes — and excluded only because a binary frame is
constructed by packing a struct, not by calling a JSON builder. The deviation is a
property of *how binary messages are built*, not a gap in coverage.

**Formerly two: `index.index_history`.** The history reply once took only its topic
constant, on the reasoning that it replays records verbatim from an append-only
JSONL archive and that coercing every stored row through the generated
`HistoryRecord` builder would let one legacy row missing a now-required field raise
inside an unguarded pull handler — taking pm-index down *while serving history*.
That traded a real hazard for a permanent hole in the contract. It is now closed by
making the archive canonical instead of trusting it blind: `IndexHistory.append`
validates on write, and `IndexHistory.query` drops any non-conforming row with a
warning before it can reach the builder. The reply goes through
`make_index_history_msg` like every other builder, and the unguarded handler is
safe because a row that would fail validation never arrives.

The remaining deviation follows directly from §4.2's central contract: validation
belongs on the producer side, and a message whose "producer" is a byte-packer is
exactly the case the contract carves out. It is not a compromise of the design; it
is the design's own boundary, drawn where it said it would be.

## 10. Engine latency: the cost of one source of truth

Adopting the generated constructor on the engine's trade-publication path made it
measurably slower, and a trading engine is the wrong place to wave a hand, so the
cost is decomposed here as design rationale rather than discovered afterward. All
figures are `min` of repeated runs with `orjson`; the ratios are the point.

| Construction | µs/call | vs. hand-written |
|---|---|---|
| `orjson.dumps` of an already-built dict | 0.511 | −0.444 |
| hand-written inline dict literal | 0.955 | — |
| generated, no coercion | 1.133 | +0.178 |
| **generated, full coercion (ships)** | 1.507 | **+0.551** |
| generated via `from_dict`/dataclass/`to_dict` | 4.03 | +3.08 (rejected, §8.4) |

Two facts make +0.551 µs the right price:

- **Roughly half the *original* call was never ours** — `orjson.dumps` alone is
  0.511 of the hand-written 0.955. A fixed serialisation cost now carries a little
  more Python around it, not "+58 % of our code."
- **The +0.165 µs call-shape cost is structural and irreducible.** A dict literal
  written inline compiles to `BUILD_MAP` over constants in the caller's frame;
  routing the same values through a function costs a frame push and keyword
  binding, and buys the thing the whole design exists for — the field list in one
  place. **A shared definition is a call; a copied definition is not.** No generated
  *function* can be as fast as the literal it replaces, and the only constructions
  that avoid the call put the literal back at the call site, which is what was
  removed.

Coercion is the remaining +0.393 µs and is almost entirely call overhead, not
conversion work. A measured, *rejected* optimisation is recorded so it is not
re-derived: coercing only the two field classes a type checker cannot guard (`bool`
into `int`, `int` into `float`) halves the overhead — but it fails at
`make_*_unchecked(**payload)` call sites, where the checker gives up on `**` and a
string field could go out as a JSON number. That trades 0.28 µs against a documented
byte-identical guarantee, so it is a deliberate contract change to take only with a
measurement showing a path needs it, not a free micro-optimisation. A `perf`-marked
test bounds the generated constructor at 3× the literal — a guard against an
order-of-magnitude regression, not a benchmark.

## 11. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | generated output silently diverges from hand-written behaviour during migration | High | per-family byte-identity (or key-set) test **before** adoption; no family adopted without it |
| R2 | the generator becomes a second system to maintain | Medium | deliberately small vocabulary; no Turing-complete rules; ~1 500 lines |
| R3 | spec expressiveness runs out mid-migration | Medium | adoption is per family; an unspecifiable family stays hand-written |
| R4 | C fixed-size buffers truncate a longer field | High | `max_len`/`max_items` mandatory for C; the parser returns an error rather than truncating |
| R5 | committed generated files make review noisy | Low | `DO NOT EDIT` banner; reviewers read the spec diff |
| R6 | enum drift between Python and C | Medium | both from one `values`; round-trip test compares |
| R7 | a binary layout change breaks deployed C clients | High | `family.version` pins the logical layout; the single global BALF header version byte is a separate, deliberate knob; the layout-coverage rule turns a size mismatch into a load-time error |
| R8 | non-deterministic generation makes the drift check flaky | High | determinism is a normative requirement, tested by generating twice; black-clean output emitted directly |
| R9 | the generated docs page ships un-wired into `mkdocs.yml` nav | Medium | the check validates the nav entry, not just the file |
| R10 | generator creep into stateful normalisation it cannot own | Medium | §4.9 fixes the boundary: projection + parse/serialise only |
| R11 | one logical event modelled as one message across transports when field sets genuinely differ | High | the projection model; public print and private fill are separate messages by design |
| R12 | adoption makes a builder validate an input the spec bounds tighter than its source, crashing or silencing a handler | High | the boundary audit (§8.3), run in both directions, at the boundary the value crosses |

## 12. What this prevents

Grounded in defects this repository actually produced, all of which are mechanical
inconsistencies between surfaces — the class a generator removes and a reviewer does
not reliably catch:

- `book.{SYMBOL}` gained `tick_decimals`; three surfaces needed the edit and the C
  clients were never going to get it.
- The `trades` example lost a column when `aggressor_side` was added, caught only by
  a later manual audit.
- The customer-facing BALF example parser modelled `order_id` as a 16-byte string
  where the protocol defines a `u64`, making it eight bytes wrong on six message
  types — undetected because its self-test checked the parser against frames the
  same file built. A binding that only agrees with itself proves nothing; the
  cross-language round-trip is the assertion that matters.
- The reference page documented a `mode` field on an admin resume that no producer
  has ever sent, and a consumer read a `tick_decimals` key under a name nothing
  emits — the documentation and a consumer each believing in a field alone.

## 13. Design principles

The rules below shaped the design; each is stated as the principle it is, and each
earned its place by being violated at least once before it was written down. They
are the reusable part.

- **Read the consumer; do not reason about it.** The recurring error was inferring
  what a consumer needs from its structure or its documentation instead of reading
  what it does — and being wrong. A grep for callers, a timing loop, a handler's
  error paths, a probe with an input no test writes: execute, do not deduce. Before
  adopting a generated artefact in a module, read that module's tests; they are the
  specification its callers rely on.
- **A check that has never disagreed with you has not been tested.** A gate that
  only confirms what you already found by hand cannot warn you when you miss
  something. Prove each check by making it fire — on a real collision, a real
  f-string topic, a real out-of-range value.
- **A restriction should be as narrow as its reason.** "Records are scalars-only",
  "lists need a record type", "`omit_when_empty` is strings-only" were each written
  wider than their justification and blocked something they had no reason to. When a
  restriction blocks something, check whether it blocks it for the stated reason,
  and narrow it to that.
- **When a construct grows a second form, re-ask every rule about the first.** The
  loader is one function; its branches are not. A rule tested on one branch is a
  comment on the other.
- **A unit — and a relationship between fields — belongs in the declaration, never
  the representation.** int-vs-float for a price's unit, an `a_b` prefix for "these
  travel together": conventions a generator cannot enforce. Make them declarations
  it can.
- **A map is the wire being wrong.** Every one was a record never declared or a
  signature never narrowed. The IDL has no map construct and has never needed one.
- **The scaffolding around a scripted edit needs the same scepticism as the edit.**
  Check what a bulk edit *matched*, not how many; a regex does not know what it is
  editing, and the heuristic that placed an import broke more files than the
  substitution that chose them.
- **A green build is not sufficient.** The two bugs a build cannot catch — a
  one-value enum tuple emitted as a bare string, a record class shadowing a message
  class — are valid, black-clean, check-passing code that means something different.
  Keep the holistic review; probe the adopted builders with inputs nobody wrote.
- **Take the best long-term shape and record the deviation.** Where a wire was wrong,
  it was fixed rather than ratified — a MARKET order's ack no longer carries
  `"price": null`, `session` sends `{next: {...}}` rather than two flat keys, three
  REST endpoints changed shape. Backward compatibility was not weighed; every such
  change is stated in the docs so the wire has a written history.

---

## Appendix A — IDL specification (normative)

This appendix is the **authoritative** definition of the specification language.
Where the prose above disagrees with it, this appendix wins.

### A.1 Conformance and notation

- **MUST**, **MUST NOT**, **REQUIRED**, **OPTIONAL**, **DEFAULT** are normative.
- A spec is a **YAML 1.2** document restricted to mappings, sequences and scalar
  strings/integers/floats/booleans. No anchors, aliases, tags or multi-document
  streams.
- Grammar is a schema over YAML nodes in EBNF (§A.18). `{ X }` is zero-or-more,
  `[ X ]` optional, `A | B` alternation.
- Every generated artefact is a byte-for-byte pure function of the spec (§A.16).

### A.2 File organisation

| File | Cardinality | Root key | Defines |
|---|---|---|---|
| `spec/transports.yaml` | exactly one | `transports:` | the transport registry (§A.4) |
| `spec/messages/<family>.yaml` | one per family | `family:` | one family (§A.5) |

`<family>` in the filename MUST equal the `family:` value.

### A.3 Lexical rules

| Token | Rule |
|---|---|
| `identifier` | `^[a-z][a-z0-9_]*$` — family, message, field, type, transport names |
| `type-name` | `^[A-Z][A-Za-z0-9]*$` — a record type under `types:` |
| `enum-name` / `key-name` / `msg-type-text` | `^[A-Z][A-Z0-9_]*$` |
| `msg-type-bin` | integer `0x00`–`0xFF` |
| `topic-pattern` | dot-delimited; each segment is `^[a-z0-9_]+$` or a single `{identifier}` |
| `version-str` | `^[0-9]+\.[0-9]+$` |

### A.4 Transport registry — `spec/transports.yaml`

```yaml
transports:
  <identifier>:
    pattern: <PUB|SUB|PUSH|PULL|TCP>          # REQUIRED
    subscriber_pattern: <PUB|SUB|PUSH|PULL>   # OPTIONAL; the peer for a bus transport
    address_config_key: <IDENTIFIER>          # REQUIRED; symbolic, resolved at runtime
```

`TCP` transports are external line/binary protocols fronted by a gateway;
`address_config_key` MUST NOT be a literal address. `calf`, `balf`, `ralf` are
reserved external-protocol names, referenceable bare or via a registry entry;
every other transport reference MUST be a registry entry.

### A.5 Family file — top level

```yaml
family:   <identifier>          # REQUIRED; equals the filename stem
version:  <integer>             # REQUIRED; logical layout version (§A.16)
types:    { <type-name>: <record-def>, ... }   # OPTIONAL; record definitions (§A.8)
messages: [ <message>, ... ]    # REQUIRED; non-empty
```

### A.6 Message object

| Key | Req. | Type | Notes |
|---|---|---|---|
| `name` | REQUIRED | identifier | unique in the family |
| `topic` | CONDITIONAL | topic-pattern | REQUIRED iff ≥1 bus transport; MUST be omitted for a purely external message (BALF-only) |
| `transport` | REQUIRED | list of transport-ref | non-empty |
| `doc` | REQUIRED | doc-block (§A.15) | `motivation` and `published_by` are required |
| `fields` | REQUIRED | list of field (§A.7) | non-empty; declaration order authoritative |
| `encoding` | CONDITIONAL | map transport-ref → encoding-def (§A.13) | a bus block MAY be omitted (defaults `frames: [topic, json_payload]`, `include: all`); a text/binary block is REQUIRED |
| `invariants` | OPTIONAL | list of invariant (§A.14) | cross-field rules |

A message's generated class name is its PascalCase; it MUST NOT collide with any
`type-name` in the family (§A.17 r16).

### A.7 Field object

| Key | Req. | Type | Default | Notes |
|---|---|---|---|---|
| `name` | REQUIRED | identifier | — | unique in the message/record |
| `type` | REQUIRED | type (§A.9) | — | |
| `required` | OPTIONAL | boolean | `true` | |
| `nullable` | OPTIONAL | boolean | `false` | see presence (§A.7.1) |
| `omit_when_none` | OPTIONAL | boolean | `false` | implies `nullable` |
| `omit_when_empty` | OPTIONAL | boolean | `false` | strings only; mutually exclusive with `omit_when_none` |
| `default` | OPTIONAL | scalar | — | producer-side; MUST pass `validate()`; meaningful only when `required: false` |
| `parse_default` | OPTIONAL | scalar | — | consumer-side (`from_dict` only); need not be a legal value (§A.7.2) |
| `unit` | OPTIONAL | unit (§A.11) | — | REQUIRED by lint on numeric fields |
| `doc` | OPTIONAL | string | `""` | REQUIRED non-empty when deprecated |
| `values` | CONDITIONAL | list of enum-name | — | REQUIRED iff `type == enum` |
| `ref` | CONDITIONAL | type-name | — | REQUIRED iff `type == nested`, or `list` of records |
| `item` | CONDITIONAL | scalar-type | — | REQUIRED iff `type == list` of scalars |
| `validate` | OPTIONAL | validate-map (§A.12) | `{}` | |
| `deprecated_since` / `removed_after` | OPTIONAL | version-str | — | §A.16 |

#### A.7.1 Presence (normative)

Every `required: false` field MUST select exactly one regime; the loader rejects
one that selects none, and rejects `omit_when_none` with `omit_when_empty`:

| Declaration | Wire | Python |
|---|---|---|
| `required: true` | always present | `T` |
| `required: false` + `default: X` | always present, `X` unset | `T = X` |
| `required: false` + `nullable` | always present, `null` unset | `T \| None = None` |
| `required: false` + `nullable` + `omit_when_none` | absent unset | `T \| None = None` |
| `required: false` + `omit_when_empty` (string) | absent on `""` | `str = ""` |

Lists are never `nullable` (§A.9). `omit_when_empty` with a positive `min_items`
is a loader error (§A.17 r17).

#### A.7.2 `default` vs `parse_default`

`default` is the producer-side fallback and MUST be a legal value; `parse_default`
is the consumer-side fallback `from_dict` substitutes for a missing key and need
not be legal (it expresses "strict for producers, lenient for readers"; §4.2).
`from_dict` precedence: `parse_default` → `default` → `p["name"]` (raises).

### A.8 Record types

```yaml
types:
  <type-name>:
    fields: [ <field>, ... ]     # same grammar as §A.7
```

A record is referenced by `type: nested, ref: <T>` or `type: list, ref: <T>`.
Records MAY embed records to any depth; a **reference cycle** is a loader error
naming the path. Types are emitted in dependency order. An unreferenced type is a
loader error. A `type-name` MUST NOT collide with a message's PascalCase name.

### A.9 Type system

| `type` | Python | C | JSON | Companions |
|---|---|---|---|---|
| `string` | `str` | `char[N]` | string | `validate.max_len` when external |
| `int` / `float` / `bool` | `int`/`float`/`bool` | `int64_t`/`double`/`uint8_t` | number/bool | `unit` (numeric, lint) |
| `enum` | `str` + `Literal` | enum + `_to/from_str` | string | `values`; `enum_map` for binary |
| `ticks` | `int` | `int64_t` | number | `unit` |
| `list` | `list[T]` | `T[N]` + count | array | exactly one of `item:` (scalar) or `ref:` (record); `max_items` when external |
| `nested` | dataclass | struct | object | `ref:` |

`list` scalar `item:` excludes `enum` and `ticks`. Lists are non-nullable.

### A.10 `repr` (binary layout only)

`u8/u16/u32/u64`, `i8/i16/i32/i64` (little-endian), `f32/f64`, `char[N]`
(zero-padded ASCII, `N == validate.max_len`). A numeric `repr` MAY carry `scale:`
(integer or the token `price_scale`); a `u8`/`u16` carrying an enum MAY carry
`enum_map`.

### A.11 `unit` (complete)

`display_price`, `ticks`, `shares`, `epoch_seconds`, `epoch_nanos`,
`duration_nanos`, `percent`, `dimensionless`, `money`. Declarative only; never a
runtime conversion. Any other value is a lint error.

### A.12 `validate` vocabulary (complete)

`gt`, `ge`, `lt`, `le` (numeric); `max_len`, `min_len` (string); `max_items`,
`min_items` (list); `pattern` (string, `re.fullmatch`). No other key is permitted.
A rule that can never fire or can never pass (`min_items > max_items`, negative
bounds, a scalar rule on a list) is a loader error.

### A.13 Encoding object

**Bus** (ZeroMQ): `frames: [topic, json_payload]` (no `sequence` token — the
per-topic sequence is a third frame the bus adds at publish time), `include:`
(DEFAULT `all`, meaning every field except topic parameters).

**Text** (`calf`/`ralf`): `msg_type`, `include`, `keys` (per field, one-to-many
allowed), `gateway_injected` (documented, never emitted by the projection). The
projection emits **only included payload fields**, in `include`/declaration order,
enums uppercased; `project_*(payload)` takes a **mapping, not a message**, reading
only the included fields.

**Binary** (`balf`): `msg_type` (unique byte), `frame_size`, optional
`price_scale`, and an ordered `layout` of `{field, repr, offset, scale?, enum_map?}`
entries and explicit `{reserved: N, offset}` runs. The 8-byte header
(`magic 0xBA`, version, `msg_type`, flags, `seq_no` u32 LE) is implicit; `offset`
is body-relative; every body byte MUST be covered exactly once.

### A.14 Invariant grammar

```ebnf
expr       ::= or-expr
or-expr    ::= and-expr { "or" and-expr }
and-expr   ::= comparison { "and" comparison }
comparison ::= operand rel-op operand | "(" expr ")"
rel-op     ::= "==" | "!=" | ">" | ">=" | "<" | "<="
operand    ::= field-name | number | "'" string "'" | "true" | "false"
```

Every `field-name` MUST be a field of the message. No calls, arithmetic or
indexing.

### A.15 `doc` object

```yaml
doc:
  motivation:   <string>                 # REQUIRED
  published_by: [ <process-role>, ... ]  # REQUIRED; closed vocabulary of eleven roles
  since:        <version-str>            # OPTIONAL
  see_also:     [ <string>, ... ]        # OPTIONAL
  example_note: <string>                 # OPTIONAL — ports/sockets live here, not in a column
```

Nothing under `doc` reaches the wire. `published_by` values outside the vocabulary
are a lint error.

### A.16 Versioning and determinism

`family.version` is the logical layout version, distinct from the single global
BALF header version byte. A field MUST pass through `deprecated_since` before
removal and MUST NOT be deleted before `removed_after`. **Determinism is normative:**
output is a byte-for-byte pure function of the spec — declaration-ordered
iteration, stable mapping order, no timestamps or absolute paths — which is what
makes the drift check a reliable gate. The emitter produces black-formatted output
directly and a test asserts it with `black --check`.

### A.17 Static semantic rules (enforced by `pm-msgen lint`)

1. Every `transport` is a registry name or `calf`/`balf`/`ralf`.
2. `topic` present iff ≥1 bus transport, matching the lexical rule.
3. Every `{param}` in `topic` names a field.
4. `include` names only declared fields; `all` allowed.
5. If a bus transport is declared, every `required` field is in its projection
   (a BALF-only message is exempt; r6/r10 constrain it).
6. A text `keys` covers exactly the included, non-injected fields; no `keys` value
   collides with a `gateway_injected` key.
7. An `enum` has `values`; a binary enum has an `enum_map` covering every value.
8. A `string` reaching an external transport has `max_len`; a binary `char[N]` has
   `N == max_len`.
9. A `nested`/`list`-of-records field has a valid `ref:`; a `list` of scalars has a
   valid `item:`; exactly one of the two; a `list` reaching an external transport
   has `max_items`.
10. Binary `layout` offsets are non-overlapping and cover `[0, frame_size-8)`
    exactly, gaps as `reserved`; `scale: price_scale` requires `price_scale`.
11. Binary `msg_type` is a byte, unique across all families.
12. Deprecated fields carry a non-empty `doc`; none deleted before `removed_after`.
13. `unit`, when present, is a §A.11 value; numeric fields require one.
14. `topic` strings are unique across all families.
15. Unknown keys anywhere are rejected (strict loader).
16. No `type-name` collides with a message's PascalCase name; the record reference
    graph is acyclic; every declared type is referenced.
17. A validation rule that can never fire or never pass is rejected;
    `omit_when_empty` requires `min_items` absent or `0`; a `required: false`
    field selects exactly one presence regime; `parse_default`/`default` on a list,
    a non-empty list `default`, and `default` with `omit_when_empty` are rejected.

The loader itself MUST load via `yaml.compose()` so every diagnostic carries
`file:line:col`, MUST emit coded `Diagnostic`s, and MUST report all errors in a
layer rather than the first.

### A.18 Formal grammar (authoritative summary)

```ebnf
transport-file ::= "transports:" { identifier ":" transport-def }
transport-def  ::= "pattern:" pattern [ "subscriber_pattern:" pattern ]
                   "address_config_key:" identifier
pattern        ::= "PUB" | "SUB" | "PUSH" | "PULL" | "TCP"

family-file    ::= "family:" identifier "version:" integer
                   [ "types:" { type-name ":" record-def } ]
                   "messages:" nonempty-list(message)
record-def     ::= "fields:" nonempty-list(field)

message        ::= "name:" identifier [ "topic:" topic-pattern ]
                   "transport:" nonempty-list(transport-ref)
                   "doc:" doc-block
                   "fields:" nonempty-list(field)
                   [ "encoding:" { transport-ref ":" encoding-def } ]
                   [ "invariants:" list(invariant) ]
transport-ref  ::= identifier | "calf" | "balf" | "ralf"

field          ::= "name:" identifier "type:" type
                   [ "required:" boolean ] [ "nullable:" boolean ]
                   [ "omit_when_none:" boolean ] [ "omit_when_empty:" boolean ]
                   [ "default:" scalar ] [ "parse_default:" scalar ]
                   [ "unit:" unit ] [ "doc:" string ]
                   [ "values:" nonempty-list(enum-name) ]
                   [ "ref:" type-name ] [ "item:" scalar-type ]
                   [ "validate:" validate-map ]
                   [ "deprecated_since:" version-str ] [ "removed_after:" version-str ]

type           ::= "string" | "int" | "float" | "bool" | "enum" | "ticks"
                 | "nested" | "list"
scalar-type    ::= "string" | "int" | "float" | "bool"
unit           ::= "display_price" | "ticks" | "shares" | "epoch_seconds"
                 | "epoch_nanos" | "duration_nanos" | "percent"
                 | "dimensionless" | "money"
validate-map   ::= "{" { validate-key ":" scalar } "}"
validate-key   ::= "gt"|"ge"|"lt"|"le"|"max_len"|"min_len"|"max_items"|"min_items"|"pattern"

encoding-def   ::= bus-enc | text-enc | binary-enc
bus-enc        ::= "frames:" "[" frame-token { "," frame-token } "]" [ "include:" include-spec ]
frame-token    ::= "topic" | "json_payload"
text-enc       ::= "msg_type:" msg-type-text [ "include:" include-spec ]
                   "keys:" "{" { identifier ":" key-target } "}"
                   [ "gateway_injected:" "[" key-name { "," key-name } "]" ]
key-target     ::= key-name | "[" key-name { "," key-name } "]"
binary-enc     ::= "msg_type:" hex-byte "frame_size:" integer [ "price_scale:" integer ]
                   "layout:" nonempty-list(layout-entry)
layout-entry   ::= "{" "field:" identifier "," "repr:" repr "," "offset:" integer
                       [ "," "scale:" ( integer | "price_scale" ) ]
                       [ "," "enum_map:" "{" { enum-name ":" integer } "}" ] "}"
                 | "{" "reserved:" integer "," "offset:" integer "}"
repr           ::= "u8"|"u16"|"u32"|"u64"|"i8"|"i16"|"i32"|"i64"|"f32"|"f64"|"char[" integer "]"
include-spec   ::= "all" | "[" identifier { "," identifier } "]"
invariant      ::= "rule:" invariant-expr "message:" string
doc-block      ::= "motivation:" string "published_by:" "[" process-role { "," process-role } "]"
                   [ "since:" version-str ] [ "see_also:" "[" string { "," string } "]" ]
                   [ "example_note:" string ]
```

If a construct is needed that this grammar cannot express, that is a defect in this
appendix and MUST be resolved by extending §A.18 — never by an ad-hoc key in a
single spec file. The bar for extending it is high: the IDL was asked to grow seven
times during implementation and did so once (`duration_nanos`), because six of the
seven were the *message* being wrong, and the schema's inability to describe a
wrong message is the useful signal, not the problem.

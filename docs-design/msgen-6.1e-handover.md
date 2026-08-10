# Handover: `pm-msgen` Phase 6.1e

Continue the message-generator work. Next up: **6.1e — the first half of the
`system` family, 15 topics.** The investigation is done and recorded below;
the split and the two design calls are settled. Do not repeat them.

Branch `msg-gen`. HEAD is 6.1b; **6.1c and 6.1d are complete in the working
tree and uncommitted** — see §2.

---

## 1. Read these first — and only these

| Read | Why | Size |
|---|---|---|
| `docs/developer/06-msgen.md` | the IDL reference; current and authoritative | ~1500 lines — do not read whole. Field-keys table **L150–166**, presence regimes **L180–239**, records/`types:`/`nested`/`list` **L256–349**, roadmap at the end |
| `docs-design/EduMatcher-Message-Generator.md` **§26–§28 only** | the last two phases' findings; §26 and §27 are the ones whose lessons 6.1e will need | ~350 lines. §1–25 are settled history |
| `spec/messages/admin.yaml` | most recent worked example: a `types:` record, an all-optional record, an enum with dotted values | 150 lines |
| `spec/messages/drop_copy.yaml` | why two messages with identical bodies duplicate their field lists | 160 lines |
| `spec/messages/book.yaml` **L88–101 only** | the `include:` enumeration idiom you will need on four messages | 15 lines |
| `tests/test_msgen_admin.py` | the shape a phase's tests take, including the AST gate | 210 lines |

Fifteen spec files exist: `admin, auction, book, circuit_breaker, drop_copy,
index, log, order, quote, risk, session, structure, trade` (13 families,
77 messages, 10 record types).

---

## 2. State

**Thirteen families specified and adopted, all at zero topic literals.**

Green as of the working tree:

- `pm-msgen check: OK — 17 generated file(s) match the spec`
- `pm-msgen grep-literals: no topic literals remain for any specified family`
- black clean, flake8 clean
- `mypy src tests`: **Success, 399 source files**
- pyright: 0 errors
- full suite: **4 667 passing**

### Uncommitted work

6.1c (`circuit_breaker`, `auction`) and 6.1d (`drop_copy`, `admin`) are both
complete and verified but **not committed**. Commit them as two commits before
starting 6.1e, so a bisect can tell the phases apart.

`docs-design/msgen-6.1c-handover.md` is stale and should be deleted — the
sandbox cannot unlink it through the mount, so do it from the host.

### Known-environmental failures — all five pre-existing, none code-related

1. `test_command_correlation.py::test_a_transition_timeout_leaves_no_waiter_behind[asyncio]` — 3.10 asyncio
2. `test_api_gateway_runtime.py::test_await_event_timeout_cleans_up` — 3.10 asyncio
3. `test_config_gen_cli_help.py::test_pm_config_gen_help_runs` — no `poetry` binary
4. `test_alf_examples.py::test_c_example_client_builds_connects_and_exits` — `make clean` cannot unlink prebuilt binaries through the mount
5. `test_ralf_examples.py::test_c_example_builds_and_receives_gateway_exec` — same

`test_calf_spy.py` and `test_ralf_spy.py` occasionally fail **under `-n 8`
only** (port collision) and pass serially. Not real.

---

## 3. Sandbox setup — do this first, it is not obvious

The repo's `.venv` is a macOS venv and will not run. The sandbox is **Python
3.10** and the project needs **3.11+** (`datetime.UTC`). Without the shim, 122
test modules fail to collect and you will misread it as breakage.

```bash
pip install --quiet --break-system-packages \
  black flake8 mypy pytest pytest-cov pytest-xdist pytest-timeout \
  pyzmq orjson prompt_toolkit rich fastapi httpx pydantic uvicorn \
  websockets python-dotenv pyyaml holidays

mkdir -p ~/shim && cat > ~/shim/sitecustomize.py <<'PY'
import datetime as _dt
if not hasattr(_dt, "UTC"):
    _dt.UTC = _dt.timezone.utc
PY
```

---

## 4. Verification — the project's own commands

```bash
export P=$HOME/shim:src
PYTHONPATH=$P python -m edumatcher.msgen.cli check
PYTHONPATH=$P python -m edumatcher.msgen.cli grep-literals
python -m black --check src/ tests/
python -m flake8 src tests
PYTHONPATH=$HOME/shim python -m mypy src tests --cache-dir=$HOME/mypy_cache
npx --yes pyright@1.1.411 src/edumatcher
PYTHONPATH=$P timeout 540 python -m pytest tests/ -q -p no:cacheprovider \
    --no-cov -n 8 --timeout=90
```

Three traps, all learned the hard way:

- **Never run `black src/ tests/` (without `--check`) while verifying.** It
  reformats the *generated* bindings, turning one clear emitter bug into three
  confusing failures — `pm-msgen check` drift, the reproducibility test and
  the black-clean test — none of which names the cause. Format only
  hand-written files; let the committed bindings be *checked*.
- **Do not delete `.mypy_cache`.** It cannot be recreated on the mount and
  mypy dies with an INTERNAL ERROR. Use `--cache-dir=$HOME/mypy_cache`.
- **Run the whole `test_msgen_*` group AND the full suite.** 6.1d passed the
  whole msgen group and still broke `test_engine_review_highs.py`, because the
  affected surface was a test double in a file the phase never thought about.

The Makefile target is `_check`.

---

## 5. The 6.1e investigation — already done, do not repeat

### 5.1 The split, and why this one

`system` is **29 topics = 14 request/reply pairs + `system.eod`**. Confirmed
by enumerating the builders in `models/message.py`, not from the roadmap.

**6.1e is the static/reference half plus connection lifecycle — 15 topics:**

| Pair | Topics |
|---|---|
| connect | `system.gateway_connect`, `system.gateway_auth.{gw}` |
| disconnect | `system.gateway_disconnect`, `system.gateway_bye.{gw}` |
| end of day | `system.eod` (broadcast, no request) |
| symbols | `system.symbols_request`, `system.symbols.{gw}` |
| reference | `system.reference_request`, `system.reference.{gw}` |
| reload | `system.reference_reload`, `system.reference_reload_ack.{gw}` |
| session state | `system.session_state_request`, `system.session_status.{gw}` |
| schedule | `system.session_schedule_request`, `system.session_schedule.{gw}` |

**6.1f is the live-state snapshots — 14 topics:** `halt_status`, `position`,
`quote_bootstrap`, `quote_legs`, `risk_state`, `volume`, `gateways`, each a
`*_request` / reply pair.

The cut reads as *"what the venue is, and joining or leaving it"* versus
*"what is true right now"*, which is §22.1's rule — split by what the message
acts on, never by direction, and each half lands as complete conversations.

Two constraints forced it and are worth restating because they rule out the
obvious alternative of isolating `reference` into its own phase:

1. **`session_schedule.schedule` and `reference.schedule` are the same
   record.** Both are the five-key `{pre_open, opening_auction_start,
   continuous_start, closing_auction_start, closing_auction_end}` block off
   `engine_cfg.schedule`; `reference`'s adds `sessions_enabled` and `country`.
   Splitting them describes one shape twice in two phases.
2. **`reference.symbols[sym].circuit_breaker.levels` is the same ladder
   `circuit_breaker.halt.level` names.** 6.1c bounded config level names at 32
   for exactly that reason (§26.5). The static definition and the event that
   quotes it want the same `max_len`.

### 5.2 The five maps, and what each actually is

§15.4 excludes maps from the IDL, and is five-for-five that a map is the wire
being wrong (§24.2, §27.1). `system` carries five more. **The decision is to
convert all of them, judged individually** — confirmed with the user, on the
explicit instruction to take the best long-term shape and not weigh backward
compatibility.

| Map | Where | What it actually is |
|---|---|---|
| the whole `system.reference` payload | `make_reference_msg(gw, reference)` passes the dict straight to `encode` | a record. Built in one place, `_rebuild_reference_cache` (**engine/main.py L1440–1521**), with fixed top-level keys `symbols`, `risk`, `indexes`, `schedule`, `config_version` |
| `reference.symbols` | same | keyed by symbol → §19.2's list-of-records with the key as a field |
| `reference.risk.levels` | same | keyed by level name → same shape |
| `session_schedule.schedule` | `dict[str, str] \| None`, engine/main.py **L1802–1817** | a fixed five-key record. Not a map at all — the annotation is the only thing that says otherwise |
| `symbols.symbol_meta` | `dict[str, Any] \| None`, message.py **L354** | keyed by symbol → list of records, or fold into `symbols` |

`reference.symbols[sym]` is itself nested three deep — `{tick_size, level,
collar{static_band_pct, dynamic_band_pct}, circuit_breaker{reference_window_ns,
levels[{name, price_shift_pct, halt_duration_ns}]}}` — with `collar` and
`circuit_breaker` both optional. Both are nullable records with
`omit_when_none`, which is what §16.2 built that combination for.

`reference.indexes` is already a list of records
(`{id, description, base_value, constituents[]}`). `eod.books` likewise, via
`EodBookPayload` (feed_schema.py **L113**).

**`symbol_meta` deserves its own look before you convert it.** `symbols` and
`symbol_meta` are two parallel collections keyed by the same thing — one a
list of ids, the other a map from id to metadata — which is the denormalised
shape §15.4's `leg_fill_qty` turned out to be. The likely right answer is one
list of records and no `symbol_meta` key at all, but **read the three readers
first**: `api_gateway/caches.py:91`, `api_gateway/engine_client.py:512`,
`alf_console/main.py:683` + `display.py:235`.

### 5.3 The REST surface — this is the part that makes 6.1e large

`api_gateway/routers/reference.py` **slices the reference bundle and returns
the slices verbatim as HTTP responses**:

```python
@router.get("/reference/symbols")
    return {"symbols": bundle.get("symbols", {}), "config_version": ...}
@router.get("/reference/risk")
    risk = bundle.get("risk", {});  return {**risk, "config_version": ...}
@router.get("/reference/schedule")
    schedule = bundle.get("schedule", {});  return {**schedule, ...}
```

So converting `reference.symbols` from a map to a list of records is a
**REST-visible change**, not only a ZMQ one. That is sanctioned — and it is
the better JSON shape, since a list of objects each carrying its own `symbol`
is what an API client can iterate without knowing the keys. But it means
`docs/user-guide/260-api-gateway.md`'s samples and any OpenAPI expectations
move with it, and it is the single largest reason this half is 15 topics
rather than 25.

`GET /admin/indexes` also slices the bundle (`routers/admin.py:311`).

### 5.4 Consumers — read these before choosing any presence regime

§13.6 records four bugs that came from reasoning about what a consumer needs
instead of reading what it does. The surface here is **thirteen modules**,
much wider than any previous phase:

| Topic | Structural readers |
|---|---|
| `gateway_auth.{gw}` | `alf_gwy`, `alf_console`, `ai_trader`, `balf_gwy`, `api_gateway/engine_client.py` + `events.py` (it is in `PRIVATE_PREFIXES`) |
| `gateway_bye.{gw}` | `clearing/main.py` — the only one |
| `gateway_connect` / `gateway_disconnect` | `engine/main.py`, `clearing/main.py`, `balf_gwy` |
| `eod` | `clearing`, `index`, `stats`, `ralf_gateway` — four, the widest fan-out in the half |
| `symbols.{gw}` | `ai_trader`, `alf_console`, `alf_gwy`, `balf_gwy`, `api_gateway` (events + reference router) |
| `reference.{gw}` | `api_gateway/routers/reference.py` only — but see §5.3 |
| `reference_reload_ack.{gw}` | `api_gateway/engine_client.py` |
| `session_status.{gw}` | `alf_console`, `alf_gwy`, `commands/client.py`, `api_gateway` |
| `session_schedule.{gw}` | `commands/client.py`, `api_gateway/routers/admin.py` |
| `session_state_request` | `scheduler/main.py` produces it |

### 5.5 Hand-written typed payloads this phase replaces

`models/feed_schema.py` holds three dataclasses that are exactly what the
generator emits — `SystemEodPayload` (**L162**), `GatewayAuthPayload`
(**L181**), `GatewayByePayload` (**L208**), plus `EodBookPayload` (**L113**)
and `BookLevelPayload`. Replacing them is the point, but check what else
imports `feed_schema` before deleting anything: `book.yaml` already declares a
`BookLevel` record, so there may be a duplicate shape to reconcile rather than
two to keep.

### 5.6 `include:` — four messages need the enumeration idiom

`include: all` means *"every field except the topic parameters"* (§26.4).
These carry their own id in the body as well as the topic and will silently
lose it otherwise:

- `system.gateway_auth.{gateway_id}` — body has `gateway_id`
- `system.gateway_bye.{gateway_id}` — body has `gateway_id`

The other parameterised replies (`symbols`, `reference`, `session_status`,
`session_schedule`, `reference_reload_ack`) do **not** repeat the gateway in
the body, so the default projection is right for them. Verify each rather than
assuming; `pm-msgen check` will pass either way, which is precisely how 6.1c
nearly shipped five messages with `symbol` missing.

### 5.7 The half-specified-family problem, second occurrence

§22.5: `grep-literals` counts literals of *declared* topics, so after 6.1e it
will print `system: N literals in M modules` — accurate, and the first time
since `risk` that a family is half specified. Keep `system` **out of**
`MIGRATED` in `tests/test_msgen_literals.py` until 6.1f, add a test asserting
the omission so finishing 6.1f without adding it fails, and say why in both
`06-msgen.md` and the design doc.

---

## 6. Remaining roadmap

| Phase | Scope | Topics |
|---|---|---|
| **6.1e** | `system` part one — lifecycle, symbols, reference, schedule | 15 |
| 6.1f | `system` part two — the seven live-state snapshot pairs | 14 |
| 6.2 | generated `271-message-appendix.md` | — |

---

## 7. How to work

### Investigation

- **Read the producers *and* the consumers**, and the module's existing tests,
  before adopting anything. §13.6: four bugs from reasoning about a consumer
  instead of reading it.
- **Follow the consumer, then the dominant producer.** It has given opposite
  answers in different families, which is the sign it is the real rule.
- **When the IDL cannot express a message, check whether the message is right
  before extending the IDL.** Six times now; five of them the wire was wrong.
  6.1d invented a `flatten:` key for about ninety seconds before checking —
  the loader is strict and rejected it, which is the loader working.
- **A field one side believes in alone needs diagnosis, not a rule.** Four
  instances, four *different* correct fixes (§24.3, §27.6): record the dropped
  value, add the field, flatten the shape, or fix the documentation that
  invented it.

### The standing audit, before adopting

**When adoption makes a builder validate, audit both directions:** every field
the process echoes outward, and every field it accepts inward from a boundary
that did not previously constrain it. Check the spec's bound against the
source's bound; where the source has none, bound it at the edge.

Three findings, three different consequences, and §27.5 is the one to have in
mind here: **the consequence depends on where in the handler the validating
builder sits.** Before the reply it is a dropped answer; after it, it is a lost
record of work that actually happened, which nothing is waiting on.

For 6.1e the inbound surface is every `*_request` — all of them read
`gateway_id` off the wire. Most are already clamped by `_clamp_wire_id`; check
each, and check `command_id` on `reference_reload`.

### Changes

- **Ignore backward compatibility.** Deliberate wire changes are fine when
  they are the better long-term shape; record them in the design.
- **A guard that fails on a deliberate change is doing its job.** Update it to
  the new boundary with a docstring saying when and why it moved — never
  delete it. 6.1d found a test that had pinned the *wrong* rule for four
  phases; the tell was black disagreeing with a passing test.
- **Surgical.** Every changed line traces to the request. Read what a scripted
  edit matched, not how many.
- **The same field name in a different message is a different field.**
  `symbols` appears as a list of strings on `system.symbols`, a map on
  `reference`, a map on `risk_state` and a map on `volume`. Four different
  fields. A find-and-replace across them would be the worst version of this
  mistake the project has had the chance to make.

### After implementation

- Run **the whole `test_msgen_*` group and the full suite**, not the files the
  phase is thinking about.
- **Do a holistic review before declaring done**: probe the loader and the
  adopted builders with specs and inputs nobody has written. Every phase found
  at least one real bug that way.
- **A check that has never disagreed with you has not been tested** (§23.1).
  When you write a static gate in the same commit as the thing it gates, also
  assert that it *found* something — 6.1d's AST scan asserts it matched twelve
  call sites, because a scan matching nothing passes for the wrong reason.

---

## 8. Documentation to keep current

- `docs/developer/06-msgen.md` — the IDL reference whenever the IDL changes;
  the **status block at the top** (currently "Phase 6.1d", thirteen families,
  77 messages, 10 record types) and the **roadmap table**.
- `docs-design/EduMatcher-Message-Generator.md` — a new numbered section per
  phase. **§28 is next.**
- `docs/user-guide/270-message-reference.md` and `260-api-gateway.md` — the
  latter carries the REST shapes §5.3 changes.
- `tests/test_msgen_literals.py::MIGRATED` — **not** `system`, until 6.1f.

---

## 9. Context budget

Work **one phase per session**. Prefer targeted `grep -n ... -A 10` over whole
file reads; batch verification into one call; avoid touching many files in a
single turn — modified files are echoed back in full each turn and that
dominates the budget late in a session.

6.1e is the largest phase in the project: 15 topics, five maps, thirteen
consumer modules and a REST-visible change. **Budget for it starting fresh.**
If you run short, stop and report rather than half-finishing — a tree where
`pm-msgen check` passes while consumers read keys the producer no longer sends
is precisely the state §20.6 refused to ship. That has worked every time,
including the two phases that produced this document and its predecessor.

# Handover: `pm-msgen` Phase 6.3

Continue the message-generator work. Next up: **6.3 — adopting the 29 messages
that are still built without their generated builder.** The enumeration is
done and recorded below, and four of them have already been probed. Do not
redo that.

Branch `msg-gen`. HEAD is 6.1f. **6.2 is complete in the working tree and
uncommitted** — see §2.

---

## 1. Read these first — and only these

| Read | Why | Size |
|---|---|---|
| `docs/developer/06-msgen.md` | the IDL reference; current and authoritative | ~1500 lines — do not read whole. Field-keys table **L150–170**, presence regimes **L185–245**, records **L260–355** |
| `docs-design/EduMatcher-Message-Generator.md` **§27, §30 only** | §27.2 is the hazard this whole phase turns on; §30.2 is where the 29 were counted and why | ~260 lines. §1–26, §28–29 are settled history |
| `src/edumatcher/models/message.py` | where 26 of the 29 are built, all via `encode()` | 1700 lines — **grep, do not read**. The `encode(` call sites are the worklist |
| `spec/messages/order.yaml` **the `order_new` message only** | the largest unadopted message, 23 fields, and the one already proved safe | 60 lines |
| `tests/test_msgen_drop_copy.py` | the worked example of adopting a builder whose signature was generic | 180 lines |

Fourteen families, **106 messages, 34 record types**, all specified. Every
topic is at zero literals. `pm-msgen check` covers 19 artifacts, one of which
is `docs/user-guide/270-message-reference.md`.

---

## 2. State

**Everything is specified and the whole tree is green.** What is *not* done is
that 29 messages reach the wire through `encode(TOPIC, some_dict)` rather than
through the generated builder that would validate them.

Green as of the working tree:

- `pm-msgen check: OK — 19 generated file(s) match the spec`
- `pm-msgen lint: OK — 14 family/families, 106 message(s)`
- `pm-msgen grep-literals: no topic literals remain for any specified family`
- black clean, flake8 clean
- `mypy src tests`: **Success, 403 source files**
- pyright: 0 errors
- full suite: **4 727 passing**

### Uncommitted work

6.2 is complete and verified but **not committed**. It spans `msgen/spec.py`
(the `published_by` key), `msgen/generators/markdown.py` (new),
`msgen/generate.py` and `cli.py` (the docs artifact), all fourteen spec files
(`published_by` on 106 messages), `docs/user-guide/270-preamble.md` (new),
`270-message-reference.md` (now generated), `tests/test_msgen_docs.py` (new),
and `published_by` added to ~57 inline spec fixtures across the msgen tests.
Commit it before starting 6.3 so a bisect can tell the phases apart.

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
PYTHONPATH=$P timeout 500 python -m pytest tests/ -q -p no:cacheprovider \
    --no-cov -n 8 --timeout=90
```

Five traps, the last two learned in 6.1f and 6.2:

- **Never run `black src/ tests/` (without `--check`) while verifying.** It
  reformats the *generated* bindings, turning one clear emitter bug into three
  confusing failures. Format only hand-written files by name.
- **Do not delete `.mypy_cache`.** It cannot be recreated on the mount and
  mypy dies with an INTERNAL ERROR. Use `--cache-dir=$HOME/mypy_cache`.
- **Run the whole `test_msgen_*` group AND the full suite.**
- **`pm-msgen check` now covers a documentation file.** Editing a spec's `doc:`
  block and not regenerating fails the check the same way a field change does.
  Run `generate`, and commit `270-message-reference.md` with the spec.
- **Any new message needs `doc.published_by`.** Required, and a closed
  vocabulary of eleven process roles (§30.2). Inline spec fixtures in tests
  need it too — that is what broke 57 tests in 6.2.

The Makefile target is `_check`.

---

## 5. The 6.3 investigation — already done, do not repeat

### 5.1 The 29, and the four clusters they fall into

Produced by an AST pass, not by reading: a message is *unadopted* when no
module calls `make_<name>` or `make_<name>_unchecked` for it. The script is in
§7.3 — rerun it rather than trusting this list after you start changing things.

| Cluster | Count | Built where | Character |
|---|---|---|---|
| **A. `log` family** | 15 | `log_srv/pubsub.py` (10 server-side) and `models/message.py` (5 client-side) | the server side goes through one generic `_publish(topic, payload)` helper |
| **B. `order` inbound** | 7 | `models/message.py`, `encode(TOPIC, dict)` | gateway→engine commands; `order_new` takes a whole open dict |
| **C. `book`** | 3 | `models/message.py` | `book_snapshot` and `depth` are hot-path publishes |
| **D. singletons** | 4 | various | `quote.quote_new`, `session.session_transition`, `index.index_history`, `order.execution_report` |

The full list, family and topic:

```
book     book_snapshot            book.{symbol}
book     book_snapshot_request    book.snapshot_request
book     depth                    depth.{symbol}
index    index_history            index.history.{gateway_id}
log      log_subscribe            log.subscribe
log      log_renew                log.renew
log      log_unsubscribe          log.unsubscribe
log      log_backfill_request     log.backfill_request
log      log_status_request       log.status_request
log      log_subscribe_ack        log.subscribe_ack.{sub_id}
log      log_renew_ack            log.renew_ack.{sub_id}
log      log_unsubscribe_ack      log.unsubscribe_ack.{sub_id}
log      log_status               log.status.{sub_id}
log      log_backfill             log.backfill.{sub_id}
log      log_event                log.event.{sub_id}
log      log_notify               log.notify.{sub_id}
log      log_lease_expired        log.lease_expired.{sub_id}
log      log_error                log.error.{sub_id}
log      log_server_state         log.server_state
order    execution_report         (no bus topic — BALF frame)
order    order_new                order.new
order    order_cancel             order.cancel
order    order_amend              order.amend
order    order_combo              order.combo
order    order_combo_cancel       order.combo_cancel
order    order_oco                order.oco
order    order_oco_cancel         order.oco_cancel
quote    quote_new                quote.new
session  session_transition       session.transition
```

**It is 29, not 30.** §30.2 of the design doc says thirty; that count came
from the population script's `MANUAL` table, which also carried
`system.position_request` — and that one *does* go through a builder. Correct
the design doc when you write §31.

### 5.2 The hazard, and the four probes already run

§27.2 is the whole reason this phase is not mechanical: **`from_dict` reads
declared keys only**, so routing an open dict through a generated builder
*silently drops* anything the spec does not declare. The publisher returns
normally, the recipient gets a well-formed message, and a field is gone. That
is §1's failure class, and adopting carelessly would introduce it rather than
remove it — which 6.1d found on `drop_copy` and fixed by narrowing the
signature.

So every one of the 29 needs a **key-set probe before adoption**, not after.
The recipe:

```python
from edumatcher.models.generated import order as G
declared = set(G.OrderNew.__annotations__)
emitted  = set(<a real payload from the actual producer>)
print("DROPPED:", sorted(emitted - declared))
print("spec-only:", sorted(declared - emitted))
```

Four are already done:

| Message | Result |
|---|---|
| `order.order_new` (from `Order.to_dict()`) | **23 keys, 23 declared, nothing dropped.** Safe |
| `book.book_snapshot` (from `OrderBook.snapshot()`) | 9 for 9, nothing dropped. Safe |
| `log.log_subscribe` | clean |
| `log.log_error` | clean |

`order.order_new` being a perfect match is the encouraging result, because it
is the biggest and the one with an open `dict[str, Any]` signature. **But it
was probed on one path only.** `balf_gwy/translate.py::build_engine_new_order`
builds an order dict *by hand* rather than from `Order.to_dict()`, and a crude
scrape of it suggested a mismatch that was probably an artifact of the scrape.
**Probe that path properly before adopting `order.new`** — it is the one place
in the tree where two different constructions feed one builder.

### 5.3 Cluster A: the generic publisher, which is §27.1's second half

`log_srv/pubsub.py` ends every server-side send at:

```python
def _publish(self, topic: str, payload: dict[str, Any]) -> None:
    self._pub.send_multipart(encode(topic, payload), zmq.NOBLOCK)
```

Ten call sites pass a topic helper and a dict literal. This is exactly
`DropCopyPublisher.publish(gateway_id, event_type, payload)` at family scale,
and §27.1's rule names it: *a map is either a record that was never declared or
a signature that was never narrowed* — this is the second kind.

The `drop_copy` fix was to replace the generic method with a typed one per
event. Ten typed methods is a lot; the alternative worth weighing is keeping
`_publish` as the transport and calling the generated builder at each of the
ten sites, so the dict literal becomes keyword arguments and `_publish` never
sees an untyped payload. **Read the ten call sites before choosing** — that is
§13.6, and it has given opposite answers in different families.

Note the log family's HWM behaviour: `_publish` deliberately **drops** on
`zmq.Again` rather than blocking. A validating builder raises *before*
`_publish` is called, so by §27.5's rule the consequence sits before the send:
a raise here is a dropped log event with a logged exception, on a feed whose
purpose is being the record. Bound the inbound fields accordingly.

### 5.4 Cluster B: seven inbound commands, and where the bounds are

All seven are gateway→engine and all seven are built in `models/message.py`
with `encode()`. They are the messages a hostile or buggy client controls
most directly, and none of them is validated on construction today.

`order_amend` is the interesting one: it builds its payload conditionally
(`if price is not None`), which is regime 3 hand-rolled. Check the spec
declares the same regime before adopting, or the wire changes.

The standing audit applies in the usual direction: when adoption makes a
builder validate, check every field the process echoes outward *and* every
field it accepts inward. For this cluster the inbound surface is the engine's
`_dispatch_pull_message`, and most identifiers there are already clamped by
`_clamp_wire_id`. **Use `_clamp_wire_text` instead wherever the value is a
correlation key echoed into a reply topic** — `_clamp_wire_id` upper-cases,
which 6.1f nearly used to break every read-only `/reference` reply. See §29.8.

### 5.5 Cluster D: the one that is genuinely different

`order.execution_report` has **no bus topic at all** — it is the BALF binary
frame, built in `balf_gwy/codec.py` by `build_execution_report()` packing a
struct. There is no `encode()` to replace and no JSON payload to validate; the
generated C and Python binary projections already exist and are round-trip
tested (`test_msgen_balf_roundtrip.py`).

**Decide early whether it is in scope.** The honest reading is that it is
already adopted in the sense that matters — the layout comes from the spec —
and it appears in the list only because the AST scan looks for `make_*` calls,
which a binary frame does not use. If you agree, say so in §31 and take it out
of the count rather than leaving the next person to rediscover it.

### 5.6 What to check about the docs, now that they are generated

Adoption does not change a payload's shape if it is done correctly, so
`270-message-reference.md` should be **byte-identical** before and after each
message. If regenerating rewrites it, the adoption changed the wire — which is
either a bug or a deliberate change that needs recording. That is the cheapest
available check in this phase and it did not exist before 6.2.

---

## 6. Remaining roadmap

| Phase | Scope | Count |
|---|---|---|
| **6.3** | adopt the messages still built with `encode()` | 29 (or 28, see §5.5) |
| 6.4? | not planned. See §7.4 before inventing one |

---

## 7. How to work

### 7.1 Investigation

- **Probe the key sets before adopting, not after.** §5.2. This is the one
  habit that makes the difference between adoption removing a failure class
  and introducing one.
- **Read the producers *and* the consumers**, and the module's existing tests.
  §13.6: four bugs from reasoning about a consumer instead of reading it.
- **When the IDL cannot express a message, check whether the message is right
  before extending the IDL.** Seven times asked, once extended (`duration_nanos`,
  §28.7). The prior is strongly against.
- **A field one side believes in alone needs diagnosis, not a rule.** Five
  instances, five *different* correct fixes.

### 7.2 Changes

- **Ignore backward compatibility.** Deliberate wire changes are fine when they
  are the better long-term shape; record them in the design doc.
- **A guard that fails on a deliberate change is doing its job.** Update it to
  the new boundary with a docstring saying when and why it moved — never delete
  it. 6.2 *inverted* one rather than deleting it (§30.4) and that is the
  pattern to copy.
- **Surgical.** Every changed line traces to the request.
- **Scripted edits: the scaffolding needs the same scepticism as the edit.**
  6.1f's literal migration substituted correctly and then broke eleven files on
  *where it inserted the import*. If you script anything, parse every touched
  file with `ast` afterwards. §29.6.
- **Naming:** a record named after the message that carries it will collide
  with that message's generated class. The loader rejects it now, but the fix
  is to name the record for what it is. §29.1.

### 7.3 The enumeration script

Rerun this rather than trusting §5.1 once you have started:

```python
import ast, pathlib, collections
from edumatcher.msgen.spec import load_all
_r, fams = load_all(pathlib.Path("spec"))
SRC = pathlib.Path("src/edumatcher")
calls = collections.defaultdict(set)
for p in SRC.rglob("*.py"):
    if "generated" in p.parts or "msgen" in p.parts:
        continue
    for n in ast.walk(ast.parse(p.read_text())):
        if isinstance(n, ast.Call):
            f = n.func
            nm = getattr(f, "id", None) or getattr(f, "attr", None)
            if nm and nm.startswith("make_"):
                calls[nm].add(p.relative_to(SRC).as_posix())
for f in fams:
    for m in f.messages:
        g = f"make_{m.name}"
        if not (calls.get(g) or calls.get(g + "_unchecked")):
            print(f"{f.family:10s} {m.name:24s} {m.topic}")
```

**Turn it into a test at the end of the phase.** A count that only ever
existed in a handover is a count nobody will check again — which is how the
"thirty" in §30.2 went unverified for one phase. A test asserting the
unadopted set is exactly what 6.3 chose to leave (empty, or the BALF frame
alone) is the artifact this phase should produce alongside the adoptions.

### 7.4 After implementation

- Run **the whole `test_msgen_*` group and the full suite**.
- **Regenerate and confirm `270-message-reference.md` did not move.** §5.6.
- **Do a holistic review before declaring done**: probe the adopted builders
  with inputs nobody has written. Every phase found at least one real bug that
  way, including 6.2, whose only bug was found by a test written for something
  else.
- **A check that has never disagreed with you has not been tested** (§23.1).
  6.1e's class-collision guard disagreed with its own author one phase later,
  which is the standard to aim for.
- **Say whether the project is finished.** After 6.3 there is no planned 6.4.
  If the honest answer is that the generator is done, write that down in
  `06-msgen.md`'s status block rather than leaving an open-ended roadmap table
  implying otherwise.

---

## 8. Documentation to keep current

- `docs/developer/06-msgen.md` — the **status block at the top** (currently
  "Phase 6.2 — complete", 14 families, 106 messages, 34 record types) and the
  **roadmap table**.
- `docs-design/EduMatcher-Message-Generator.md` — a new numbered section per
  phase. **§31 is next**, and it should correct §30.2's "thirty".
- `docs/user-guide/270-preamble.md` — the hand-written half of the reference.
  The other half regenerates itself; do not edit
  `270-message-reference.md` by hand, `pm-msgen check` will fail.
- `tests/test_msgen_literals.py::MIGRATED` — all fourteen families are in it.
  Nothing to do unless a family is added.

---

## 9. Context budget

Work **one cluster per session** if the whole phase does not fit. The four in
§5.1 are genuinely independent — `log` touches only `log_srv` and
`logclient`, `order` inbound touches the four gateways, `book` touches the
engine's hot path. Any one of them lands as a complete, verifiable change.

Prefer targeted `grep -n ... -A 10` over whole file reads; batch verification
into one call; avoid touching many files in a single turn — modified files are
echoed back in full each turn and that dominates the budget late in a session.

`models/message.py` is 1700 lines and **26 of the 29 live in it**. Do not read
it whole; grep for `encode(` and work from the call sites.

If you run short, stop and report rather than half-finishing. A tree where
some producers validate and others do not is the state this phase exists to
end, so leaving it half-done is worse here than in most phases — but it is
recoverable, because §7.3's script tells the next session exactly where you
stopped. That has worked every time, including the three phases that produced
this document and its predecessors.

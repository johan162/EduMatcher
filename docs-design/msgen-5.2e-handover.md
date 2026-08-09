# Handover prompt — Phase 5.2e (`index` family)

Paste the block below into a fresh session. Delete this file once 5.2e lands.

---

Continue the `pm-msgen` message-generator work in this repo with Phase **5.2e**:
specify and adopt the **`index`** message family. Work in the same careful way
the earlier phases were done.

## Read these first, in this order

1. `docs/developer/06-msgen.md` — the current IDL reference. It is up to date:
   four presence regimes, `types:` / `nested` / `list` (records *and* scalars
   via `item:`), and the table of what records deliberately do not do.
2. `docs-design/EduMatcher-Message-Generator.md` **sections 15–19 only** — the
   decisions and the recurring lessons. Do not read the whole file; it is 3000+
   lines and §1–14 are settled history.
3. `spec/messages/log.yaml` — the most recent worked example. It shows record
   types, a record inside a record, lists of records and lists of scalars.
4. `tests/test_msgen_log_server.py` — the shape a phase's tests take.

## State

Seven families specified and at **zero topic literals**: `trade`, `order`,
`session`, `book` (incl. `depth`), `log`. `index` and `risk` remain.

Everything is green as of the last commit: black, flake8, `mypy src tests`
(383 files), pyright 0 real errors, `pm-msgen check: OK — 9 generated files`,
full suite 4452 passing. Three known-environmental failures, all pre-existing
and unrelated (two Python 3.10 asyncio, one missing `poetry` binary in the
sandbox).

## The 5.2e investigation already done — do not repeat it

`index` has **23 topic literals across 8 modules** and ten builders in
`models/message.py` (`make_index_update_msg`, `..._history_request_msg`,
`..._history_msg`, `..._corp_action_msg`, `..._constituent_change_msg`, three
`_ack` variants, `..._rebalance_msg`, `..._error_msg`).

**It needs no new IDL construct.** Everything it carries is expressible with
what 5.2a–5.2d built. Specifically:

- **`index.update` has a third paired-presence group.** In
  `models/message.py::make_index_update_msg`:

  ```python
  if day_open is not None:
      payload["day_open"] = day_open
      payload["day_high"] = day_high
      payload["day_low"] = day_low
  ```

  Three keys, one guard, all-or-nothing. Design §16.2 already settled how to
  express this: a **nullable record**, `DaySummary { open, high, low }` with
  `nullable: true, omit_when_none: true`. That makes the half-set state
  unrepresentable rather than merely invalid, and names the thing.

  This is the **third** instance of the pattern (after `session`'s
  `next_state`/`next_at` and `command_id`/`gateway_id`), which is enough to
  state it generally: *an `a_b`-prefixed group of fields sharing one guard is a
  record that was flattened for want of one.*

- `index.history` carries `records: list[...]` (structural audit entries: INIT,
  CORP_ACTION, ADD_CONSTITUENT, DELIST) and `warnings: list[string]` — both
  supported since 5.2c.
- The six `*_ack` topics are flat.
- `index.error.{gateway_id}` and `index.history.{gateway_id}` are parameterised
  like every other addressed reply.

**Before locking the `DaySummary` shape, grep `risk`'s 30 topics for more
guarded groups.** Three instances suggests there are more, and it is cheaper to
find them now than to discover a fourth mid-phase.

## How to work

- **Investigate before specifying.** Read the producers *and* the consumers,
  and read the module's existing tests before adopting anything there. The
  design's §13.6 records four separate bugs that came from reasoning about what
  a consumer needs instead of reading what it does.
- **Follow the consumer, then the dominant producer.** That rule decided every
  presence question so far, and it has given opposite answers in different
  families — which is the sign it is the real rule.
- **When the IDL cannot express a message, check whether the message is right
  before extending the IDL.** This has now happened four times; twice the wire
  was wrong, twice the restriction was written more broadly than its reason.
- **Ignore backward compatibility.** Deliberate wire changes are fine when they
  are the better long-term shape; record them in the design.
- **A guard that fails on a deliberate change is doing its job.** Update it to
  the new boundary with a docstring saying when and why it moved — do not
  delete it.
- **Verify with the project's own commands**, not approximations:
  `black`, `flake8 src tests`, **`mypy src tests`** (not `mypy src` — that miss
  cost a round), `pyright`, `pm-msgen check`, and the test suite. The Makefile
  target is `_check`.
- **Do a holistic review when the phase is done**, before declaring it
  complete: probe the loader with specs nobody has written yet. Every phase so
  far found at least one real bug that way, including two that would have
  produced valid, black-clean, `check`-passing code that meant something
  different.

## Documentation to keep current

- `docs/developer/06-msgen.md` — the IDL reference, whenever the IDL changes.
- `docs-design/EduMatcher-Message-Generator.md` — a new numbered section per
  phase recording what was found and why each decision went the way it did.
  §20 is next.
- The roadmap table in `06-msgen.md`.

## Context budget

Work **one phase per session**. Prefer targeted `grep -n ... -A 10` over whole
file reads, batch the verification commands into one call, and avoid touching
many files in a single turn — modified files are echoed back in full each turn
and that dominates the budget late in a session. If you run short, **stop and
report** rather than half-finishing; that has worked well every time.

`risk` is 30 topics — plan it as two sessions from the start.
